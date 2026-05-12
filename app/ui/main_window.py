"""
MainWindow – top-level application window.

Wires together:
  • Sidebar  (left panel, 224 px)
  • GridView (right panel, elastic)
  • FolderScanner (background QThread)
  • ThumbnailLoader (QThreadPool)
  • PhotoDB  (SQLite)
  • PreviewWindow (launched on demand)

All destructive file operations show a confirmation dialog.
"""
from __future__ import annotations
import os
from pathlib import Path

from PIL import Image
import datetime
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMainWindow,
    QMenu, QMessageBox, QProgressBar, QSplitter,
    QStatusBar, QWidget,
)

from app.database import PhotoDB
from app.scanner import FolderScanner
from app.thumbnailer import ThumbnailLoader
from app.ui.grid_view import GridModel, GridView
from app.ui.year_scrubber import YearScrubber
from app.ui.preview_window import PreviewWindow
from app.ui.properties_dialog import PropertiesDialog
from app.ui.sidebar import Sidebar

_MENU_SS = """
    QMenu {
        background: #2c2c2e;
        color: #d4d4d4;
        border: 1px solid #48484a;
        border-radius: 6px;
        padding: 4px 0;
    }
    QMenu::item          { padding: 7px 22px; }
    QMenu::item:selected { background: #3a3aff22; color: #fff; }
    QMenu::separator     { height: 1px; background: #3a3a3e; margin: 4px 10px; }
"""


class MainWindow(QMainWindow):
    def __init__(self, db: PhotoDB, config: dict):
        super().__init__()
        self._db      = db
        self._config  = config
        self._scanner: FolderScanner | None = None
        self._filter  = ("all", None)    # (kind, value)
        self._sort_asc = False

        cache = str(
            Path(config.get("thumbnail_cache", "~/.cache/photo_app/thumbs")).expanduser()
        )
        self._loader = ThumbnailLoader(cache)

        self._build_ui()
        self._build_status_bar()
        self._reload_grid()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle("Photo Organizer")
        self.resize(1480, 920)
        self.setStyleSheet("""
            QMainWindow        { background: #1c1c1e; }
            QSplitter::handle  { background: #38383e; }
            QStatusBar         { background: #1e1e22; color: #66666e;
                                  font-size: 12px; border-top: 1px solid #2e2e34; }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setHandleWidth(1)
        lay.addWidget(self._splitter)

        # Sidebar
        self._sidebar = Sidebar(self._db)
        self._splitter.addWidget(self._sidebar)

        # Grid
        self._model    = GridModel(self._loader)
        self._grid     = GridView(self._model)

        # Grid + year scrubber container
        grid_container = QWidget()
        grid_container.setStyleSheet("QWidget { background: #1c1c1e; }")
        gc_layout = QHBoxLayout(grid_container)
        gc_layout.setContentsMargins(0, 0, 0, 0)
        gc_layout.setSpacing(0)
        gc_layout.addWidget(self._grid, 1)

        self._scrubber = YearScrubber()
        self._scrubber.jump_to_row.connect(self._grid.scroll_to_row)
        gc_layout.addWidget(self._scrubber)

        self._splitter.addWidget(grid_container)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([224, 1256])

        # Wire sidebar signals
        self._sidebar.add_folder_requested.connect(self._add_folder)
        self._sidebar.all_photos_selected.connect(
            lambda: self._set_filter("all", None)
        )
        self._sidebar.source_selected.connect(
            lambda sid: self._set_filter("source", sid)
        )
        self._sidebar.album_selected.connect(
            lambda aid: self._set_filter("album", aid)
        )
        self._sidebar.tag_selected.connect(
            lambda tid: self._set_filter("tag", tid)
        )
        self._sidebar.remove_source_requested.connect(self._remove_source)
        self._sidebar.new_album_requested.connect(self._new_album)
        self._sidebar.delete_album_requested.connect(self._delete_album)
        self._sidebar.new_tag_requested.connect(self._new_tag)
        self._sidebar.delete_tag_requested.connect(self._delete_tag)

        # Wire grid signals
        self._grid.image_activated.connect(self._open_preview)
        self._grid.customContextMenuRequested.connect(self._context_menu)

        # Delete key shortcuts scoped to the grid widget
        for key in (QKeySequence.Delete, QKeySequence(Qt.Key_Backspace)):
            sc = QShortcut(key, self._grid)
            sc.setContext(Qt.WidgetShortcut)
            sc.activated.connect(self._delete_selected)

        # Debounce timer for live scan updates
        self._reload_timer = QTimer(singleShot=True)
        self._reload_timer.timeout.connect(self._reload_grid)

    def _build_status_bar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)

        self._status_lbl = QLabel()
        self._scan_lbl   = QLabel()
        self._scan_lbl.setStyleSheet("color: #4a9eff;")
        self._progress   = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedWidth(140)
        self._progress.setFixedHeight(10)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        self._progress.setStyleSheet("""
            QProgressBar { border:none; background:#38383e; border-radius:5px; }
            QProgressBar::chunk { background:#4a9eff; border-radius:5px; }
        """)

        sb.addWidget(self._status_lbl)
        sb.addPermanentWidget(self._scan_lbl)
        sb.addPermanentWidget(self._progress)

    # ── Grid data management ───────────────────────────────────────────────

    def _reload_grid(self):
        kind, value = self._filter
        if kind == "all":
            images = self._db.get_images(asc=self._sort_asc)
        elif kind == "source":
            images = self._db.get_images(source_id=value, asc=self._sort_asc)
        elif kind == "album":
            images = self._db.get_images(album_id=value, asc=self._sort_asc)
        elif kind == "tag":
            images = self._db.get_images(tag_id=value, asc=self._sort_asc)
        else:
            images = []

        self._model.load_images(images)
        n     = len(images)
        total = self._db.get_image_count()
        self._status_lbl.setText(
            f"{n:,} photos"
            + (f"  (library: {total:,})" if n != total else "")
        )
        self._update_scrubber(images)

    def _update_scrubber(self, images: list):
        year_rows: dict[str, int] = {}
        for i, img in enumerate(images):
            date = img.get("date_taken") or ""
            if date and len(date) >= 4 and date[:4].isdigit():
                year = date[:4]
            else:
                try:
                    year = str(datetime.datetime.fromtimestamp(img["mtime"]).year)
                except Exception:
                    year = "????"
            if year not in year_rows:
                year_rows[year] = i
        self._scrubber.update_years(year_rows)

    def _set_filter(self, kind: str, value):
        self._filter = (kind, value)
        self._reload_grid()

    # ── Folder / source management ─────────────────────────────────────────

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Add")
        if not folder:
            return
        source_id = self._db.add_source(folder)
        self._sidebar.refresh()
        self._start_scan([(folder, source_id)])

    def _remove_source(self, source_id: int):
        sources = {s["id"]: s for s in self._db.get_sources()}
        src = sources.get(source_id)
        if not src:
            return
        ret = QMessageBox.question(
            self, "Remove Source",
            f"Stop tracking  \"{src['path']}\"?\n\n"
            "Images are removed from the library index — no files are deleted.",
            QMessageBox.Yes | QMessageBox.Cancel,
        )
        if ret == QMessageBox.Yes:
            self._db.remove_source(source_id)
            self._sidebar.refresh()
            self._set_filter("all", None)

    # ── Scanner ────────────────────────────────────────────────────────────

    def _start_scan(self, paths_with_ids: list[tuple[str, int]]):
        if self._scanner and self._scanner.isRunning():
            self._scanner.stop()
            self._scanner.wait(3000)

        self._scanner = FolderScanner(paths_with_ids, self._db)
        self._scanner.image_found.connect(self._on_image_found)
        self._scanner.progress.connect(self._on_scan_progress)
        self._scanner.done.connect(self._on_scan_done)

        self._progress.setVisible(True)
        self._scan_lbl.setText("Scanning…")
        self._scanner.start()

    def _on_image_found(self, path: str, source_id: int, mtime: float, date: str):
        self._db.upsert_image(path, source_id, mtime, date)
        kind, value = self._filter
        if kind == "all" or (kind == "source" and value == source_id):
            self._reload_timer.start(400)

    def _on_scan_progress(self, count: int, path: str):
        fname = os.path.basename(path)
        self._scan_lbl.setText(f"Scanning  {count:,}  ({fname[:32]})")

    def _on_scan_done(self, count: int):
        self._progress.setVisible(False)
        self._scan_lbl.setText(f"✓  {count:,} images scanned")
        self._reload_grid()
        QTimer.singleShot(4000, lambda: self._scan_lbl.setText(""))

    # ── Albums / Tags ──────────────────────────────────────────────────────

    def _new_album(self):
        name, ok = QInputDialog.getText(self, "New Album", "Album name:")
        if ok and name.strip():
            self._db.add_album(name.strip())
            self._sidebar.refresh()

    def _delete_album(self, album_id: int):
        ret = QMessageBox.question(
            self, "Delete Album",
            "Delete this album?\n\nPhotos are not deleted from disk.",
        )
        if ret == QMessageBox.Yes:
            self._db.delete_album(album_id)
            self._sidebar.refresh()
            if self._filter == ("album", album_id):
                self._set_filter("all", None)

    def _new_tag(self):
        name, ok = QInputDialog.getText(self, "New Tag", "Tag name:")
        if ok and name.strip():
            self._db.add_tag(name.strip())
            self._sidebar.refresh()

    def _delete_tag(self, tag_id: int):
        ret = QMessageBox.question(self, "Delete Tag", "Delete this tag?")
        if ret == QMessageBox.Yes:
            self._db.delete_tag(tag_id)
            self._sidebar.refresh()
            if self._filter == ("tag", tag_id):
                self._set_filter("all", None)

    # ── Preview ────────────────────────────────────────────────────────────

    def _open_preview(self, row: int):
        images = self._model.all_images()
        if not images:
            return
        win = PreviewWindow(images, row, self)
        win.file_changed.connect(self._on_file_changed)
        win.show()

    # ── Context menu ───────────────────────────────────────────────────────

    def _context_menu(self, pos):
        idx = self._grid.indexAt(pos)
        if not idx.isValid():
            return
        img = self._model.get_image(idx.row())
        if not img:
            return

        path     = img["path"]
        image_id = img["id"]

        # Collect all selected image IDs (for multi-select tag/album ops)
        selected_rows = [i.row() for i in self._grid.selectedIndexes()]
        if idx.row() not in selected_rows:
            selected_rows = [idx.row()]
        selected_ids = [
            self._model.get_image(r)["id"]
            for r in selected_rows
            if self._model.get_image(r)
        ]
        multi = len(selected_ids) > 1

        menu = QMenu(self)
        menu.setStyleSheet(_MENU_SS)

        if not multi:
            menu.addAction("ℹ️  Properties").triggered.connect(
                lambda: PropertiesDialog(path, self).exec()
            )
            menu.addAction("🔍  Preview").triggered.connect(
                lambda: self._open_preview(idx.row())
            )
            menu.addAction("📂  Open in Default App").triggered.connect(
                lambda: os.system(f'xdg-open "{path}"')
            )
            menu.addAction("📋  Copy Path").triggered.connect(
                lambda: QApplication.clipboard().setText(path)
            )
            menu.addAction("📁  Show in File Manager").triggered.connect(
                lambda: os.system(f'xdg-open "{os.path.dirname(path)}"')
            )
            menu.addSeparator()
            menu.addAction("↻  Rotate 90° CW").triggered.connect(
                lambda: self._rotate(path, -90)
            )
            menu.addAction("↺  Rotate 90° CCW").triggered.connect(
                lambda: self._rotate(path, 90)
            )
            menu.addSeparator()
        else:
            menu.addAction(f"  {len(selected_ids)} photos selected").setEnabled(False)
            menu.addSeparator()

        # ── Tags submenu (applies to all selected) ─────────────────────────
        tag_label = f"🏷  Tags  ({len(selected_ids)} photos)" if multi else "🏷  Tags"
        tags_menu = menu.addMenu(tag_label)
        tags_menu.setStyleSheet(_MENU_SS)
        all_tags = self._db.get_tags()
        # Check mark if ALL selected images have the tag
        img_tags = {t["id"] for t in self._db.get_image_tags(image_id)}
        for tag in all_tags:
            check = "✓  " if tag["id"] in img_tags else "      "
            act   = tags_menu.addAction(f"{check}#{tag['name']}")
            tid   = tag["id"]
            sids  = list(selected_ids)
            act.triggered.connect(
                lambda _checked=False, t=tid, ids=sids: (
                    [self._db.untag_image(i, t) for i in ids]
                    if t in img_tags else
                    [self._db.tag_image(i, t) for i in ids]
                )
            )
        tags_menu.addSeparator()
        tags_menu.addAction("＋  New Tag…").triggered.connect(
            lambda: self._new_tag_for_image(image_id)
        )

        # ── Albums submenu (applies to all selected) ───────────────────────
        alb_label = f"🗂  Add to Album  ({len(selected_ids)} photos)" if multi else "🗂  Add to Album"
        alb_menu = menu.addMenu(alb_label)
        alb_menu.setStyleSheet(_MENU_SS)
        for alb in self._db.get_albums():
            act = alb_menu.addAction(alb["name"])
            aid = alb["id"]
            sids = list(selected_ids)
            act.triggered.connect(
                lambda _checked=False, a=aid, ids=sids: [self._db.add_to_album(a, i) for i in ids]
            )
        alb_menu.addSeparator()
        alb_menu.addAction("＋  New Album…").triggered.connect(
            lambda: self._new_album_for_image(image_id)
        )

        if not multi:
            menu.addSeparator()
            menu.addAction("📁  Move to Folder…").triggered.connect(
                lambda: self._move_file(img)
            )
            menu.addAction("✏️  Rename…").triggered.connect(
                lambda: self._rename_file(img)
            )
        menu.addSeparator()
        del_label = f"🗑  Delete {len(selected_ids)} Files…" if multi else "🗑  Delete File…"
        menu.addAction(del_label).triggered.connect(
            lambda: self._delete_selected_images(selected_ids)
        )

        menu.exec(self._grid.viewport().mapToGlobal(pos))

    # ── File operations ────────────────────────────────────────────────────

    def _rotate(self, path: str, degrees: int):
        try:
            self._loader.invalidate(path)
            self._model.invalidate_thumb(path)
            with Image.open(path) as img:
                rotated = img.rotate(degrees, expand=True)
                rotated.save(path)
            # Re-request thumbnail
            self._loader.request(path)
        except Exception as exc:
            QMessageBox.warning(self, "Rotate Failed", str(exc))

    def _move_file(self, img: dict):
        old = img["path"]
        folder = QFileDialog.getExistingDirectory(self, "Move To")
        if not folder:
            return
        new = os.path.join(folder, os.path.basename(old))
        try:
            os.rename(old, new)
            self._db.update_image_path(old, new)
            self._reload_grid()
        except Exception as exc:
            QMessageBox.warning(self, "Move Failed", str(exc))

    def _rename_file(self, img: dict):
        old  = img["path"]
        name = os.path.basename(old)
        new_name, ok = QInputDialog.getText(
            self, "Rename", "New filename:", text=name
        )
        if not ok or not new_name.strip() or new_name.strip() == name:
            return
        new = os.path.join(os.path.dirname(old), new_name.strip())
        try:
            os.rename(old, new)
            self._db.update_image_path(old, new)
            self._reload_grid()
        except Exception as exc:
            QMessageBox.warning(self, "Rename Failed", str(exc))

    def _delete_selected_images(self, image_ids: list):
        images = [img for img in self._model.all_images() if img["id"] in set(image_ids)]
        if not images:
            return
        if len(images) == 1:
            msg = f"Permanently delete this file?\n\n{images[0]['path']}"
        else:
            msg = f"Permanently delete {len(images)} files?"
        ret = QMessageBox.question(
            self, "Delete", msg, QMessageBox.Yes | QMessageBox.Cancel
        )
        if ret == QMessageBox.Yes:
            for img in images:
                try:
                    os.remove(img["path"])
                    self._db.delete_image(img["path"])
                    self._loader.invalidate(img["path"])
                except Exception:
                    pass
            self._reload_grid()

    def _delete_file(self, img: dict):
        path = img["path"]
        ret  = QMessageBox.question(
            self, "Delete File",
            f"Permanently delete this file?\n\n{path}",
            QMessageBox.Yes | QMessageBox.Cancel,
        )
        if ret == QMessageBox.Yes:
            try:
                os.remove(path)
                self._db.delete_image(path)
                self._loader.invalidate(path)
                self._reload_grid()
            except Exception as exc:
                QMessageBox.warning(self, "Delete Failed", str(exc))

    def _new_tag_for_image(self, image_id: int):
        name, ok = QInputDialog.getText(self, "New Tag", "Tag name:")
        if ok and name.strip():
            tid = self._db.add_tag(name.strip())
            self._db.tag_image(image_id, tid)
            self._sidebar.refresh()

    def _new_album_for_image(self, image_id: int):
        name, ok = QInputDialog.getText(self, "New Album", "Album name:")
        if ok and name.strip():
            aid = self._db.add_album(name.strip())
            self._db.add_to_album(aid, image_id)
            self._sidebar.refresh()

    def _delete_selected(self):
        rows = sorted(set(i.row() for i in self._grid.selectedIndexes()), reverse=True)
        images = [self._model.get_image(r) for r in rows if self._model.get_image(r)]
        if not images:
            return
        if len(images) == 1:
            msg = f"Permanently delete this file?\n\n{images[0]['path']}"
        else:
            msg = f"Permanently delete {len(images)} files?"
        ret = QMessageBox.question(
            self, "Delete", msg, QMessageBox.Yes | QMessageBox.Cancel
        )
        if ret == QMessageBox.Yes:
            for img in images:
                try:
                    os.remove(img["path"])
                    self._db.delete_image(img["path"])
                    self._loader.invalidate(img["path"])
                except Exception:
                    pass
            self._reload_grid()

    def _on_file_changed(self, path: str):
        """Called after enhance Apply — regenerate thumbnail and refresh grid."""
        self._loader.invalidate(path)
        self._model.invalidate_thumb(path)
        self._loader.request(path)

    # ── Cleanup ────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._scanner and self._scanner.isRunning():
            self._scanner.stop()
            self._scanner.wait(4000)
        self._loader._pool.waitForDone(2000)
        event.accept()
