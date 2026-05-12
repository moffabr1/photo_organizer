"""
SQLite database layer for Photo Organizer.
Thread-safe via per-thread connections using threading.local().
"""
from __future__ import annotations
import sqlite3
import threading
from pathlib import Path


class PhotoDB:
    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path).expanduser())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    # ── Connection management ──────────────────────────────────────────────

    @property
    def conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            c = sqlite3.connect(self.db_path, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=ON")
            self._local.conn = c
        return self._local.conn

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
                id   INTEGER PRIMARY KEY,
                path TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS images (
                id         INTEGER PRIMARY KEY,
                path       TEXT UNIQUE NOT NULL,
                source_id  INTEGER REFERENCES sources(id) ON DELETE CASCADE,
                mtime      REAL,
                date_taken TEXT,
                width      INTEGER DEFAULT 0,
                height     INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_images_source ON images(source_id);
            CREATE INDEX IF NOT EXISTS idx_images_date   ON images(date_taken);
            CREATE TABLE IF NOT EXISTS tags (
                id   INTEGER PRIMARY KEY,
                name TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS image_tags (
                image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
                tag_id   INTEGER REFERENCES tags(id)   ON DELETE CASCADE,
                PRIMARY KEY (image_id, tag_id)
            );
            CREATE TABLE IF NOT EXISTS albums (
                id   INTEGER PRIMARY KEY,
                name TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS album_images (
                album_id INTEGER REFERENCES albums(id) ON DELETE CASCADE,
                image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
                PRIMARY KEY (album_id, image_id)
            );
        """)
        self.conn.commit()

    # ── Sources ────────────────────────────────────────────────────────────

    def add_source(self, path: str) -> int:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO sources (path) VALUES (?)", (path,)
            )
        return self.conn.execute(
            "SELECT id FROM sources WHERE path=?", (path,)
        ).fetchone()["id"]

    def remove_source(self, source_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM sources WHERE id=?", (source_id,))

    def get_sources(self) -> list[dict]:
        return [
            dict(r)
            for r in self.conn.execute("SELECT * FROM sources ORDER BY path")
        ]

    # ── Images ─────────────────────────────────────────────────────────────

    def upsert_image(
        self,
        path: str,
        source_id: int,
        mtime: float,
        date_taken: str,
        width: int = 0,
        height: int = 0,
    ) -> int:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO images (path, source_id, mtime, date_taken, width, height)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    mtime=excluded.mtime,
                    date_taken=excluded.date_taken,
                    width=excluded.width,
                    height=excluded.height
                """,
                (path, source_id, mtime, date_taken, width, height),
            )
        return self.conn.execute(
            "SELECT id FROM images WHERE path=?", (path,)
        ).fetchone()["id"]

    def get_images(
        self,
        source_id: int | None = None,
        album_id: int | None = None,
        tag_id: int | None = None,
        asc: bool = False,
    ) -> list[dict]:
        params: list = []
        joins = ""
        wheres: list[str] = []

        if album_id is not None:
            joins += " JOIN album_images ai ON ai.image_id = i.id"
            wheres.append("ai.album_id = ?")
            params.append(album_id)

        if tag_id is not None:
            joins += " JOIN image_tags it ON it.image_id = i.id"
            wheres.append("it.tag_id = ?")
            params.append(tag_id)

        if source_id is not None:
            wheres.append("i.source_id = ?")
            params.append(source_id)

        where_clause = f"WHERE {' AND '.join(wheres)}" if wheres else ""
        year_order = "ASC" if asc else "DESC"

        # Sort by year (date_taken preferred, mtime fallback), then path for stability
        sort_year = """
            CAST(COALESCE(
                NULLIF(CAST(substr(i.date_taken, 1, 4) AS INTEGER), 0),
                CAST(strftime('%Y', datetime(i.mtime, 'unixepoch')) AS INTEGER)
            ) AS INTEGER)
        """

        sql = (
            f"SELECT DISTINCT i.* FROM images i {joins} "
            f"{where_clause} ORDER BY {sort_year} {year_order}, i.path ASC"
        )
        return [dict(r) for r in self.conn.execute(sql, params)]

    def get_image_by_path(self, path: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM images WHERE path=?", (path,)
        ).fetchone()
        return dict(row) if row else None

    def delete_image(self, path: str):
        with self.conn:
            self.conn.execute("DELETE FROM images WHERE path=?", (path,))

    def update_image_path(self, old_path: str, new_path: str):
        with self.conn:
            self.conn.execute(
                "UPDATE images SET path=? WHERE path=?", (new_path, old_path)
            )

    def purge_missing(self, source_id: int) -> int:
        """Remove DB rows for files that no longer exist on disk."""
        rows = self.conn.execute(
            "SELECT path FROM images WHERE source_id=?", (source_id,)
        ).fetchall()
        missing = [r["path"] for r in rows if not Path(r["path"]).exists()]
        if missing:
            with self.conn:
                self.conn.executemany(
                    "DELETE FROM images WHERE path=?", [(p,) for p in missing]
                )
        return len(missing)

    def get_image_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]

    # ── Tags ───────────────────────────────────────────────────────────────

    def add_tag(self, name: str) -> int:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,)
            )
        return self.conn.execute(
            "SELECT id FROM tags WHERE name=?", (name,)
        ).fetchone()["id"]

    def get_tags(self) -> list[dict]:
        return [
            dict(r)
            for r in self.conn.execute("SELECT * FROM tags ORDER BY name")
        ]

    def delete_tag(self, tag_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM tags WHERE id=?", (tag_id,))

    def tag_image(self, image_id: int, tag_id: int):
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO image_tags VALUES (?, ?)",
                (image_id, tag_id),
            )

    def untag_image(self, image_id: int, tag_id: int):
        with self.conn:
            self.conn.execute(
                "DELETE FROM image_tags WHERE image_id=? AND tag_id=?",
                (image_id, tag_id),
            )

    def get_image_tags(self, image_id: int) -> list[dict]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT t.* FROM tags t "
                "JOIN image_tags it ON it.tag_id=t.id "
                "WHERE it.image_id=?",
                (image_id,),
            )
        ]

    # ── Albums ─────────────────────────────────────────────────────────────

    def add_album(self, name: str) -> int:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO albums (name) VALUES (?)", (name,)
            )
        return self.conn.execute(
            "SELECT id FROM albums WHERE name=?", (name,)
        ).fetchone()["id"]

    def get_albums(self) -> list[dict]:
        return [
            dict(r)
            for r in self.conn.execute("SELECT * FROM albums ORDER BY name")
        ]

    def delete_album(self, album_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM albums WHERE id=?", (album_id,))

    def add_to_album(self, album_id: int, image_id: int):
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO album_images VALUES (?, ?)",
                (album_id, image_id),
            )

    def remove_from_album(self, album_id: int, image_id: int):
        with self.conn:
            self.conn.execute(
                "DELETE FROM album_images WHERE album_id=? AND image_id=?",
                (album_id, image_id),
            )
