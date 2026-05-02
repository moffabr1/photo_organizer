"""
Asynchronous thumbnail loader.

Images  → Pillow resize + EXIF rotation
Videos  → ffmpeg frame grab at 1s (falls back to 0s for short clips)

Disk cache: JPEG thumbnails named by MD5(path).
"""
from __future__ import annotations
import hashlib
import shutil
import subprocess
import threading
from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QPixmap

THUMB_SIZE = 200

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".m4v",
    ".wmv", ".flv", ".webm", ".3gp", ".mts", ".m2ts",
}

_FFMPEG = shutil.which("ffmpeg")


class _ThumbSignals(QObject):
    ready = Signal(str, QPixmap)


class _ThumbTask(QRunnable):
    def __init__(self, path: str, cache_dir: str, signals: _ThumbSignals):
        super().__init__()
        self.path = path
        self.cache_dir = cache_dir
        self.signals = signals
        self.setAutoDelete(True)

    def _cache_path(self) -> str:
        h = hashlib.md5(self.path.encode()).hexdigest()
        return str(Path(self.cache_dir) / f"{h}.jpg")

    def run(self):
        try:
            pixmap = self._load()
        except Exception:
            pixmap = None
        if pixmap is not None:
            self.signals.ready.emit(self.path, pixmap)

    def _is_video(self) -> bool:
        return Path(self.path).suffix.lower() in VIDEO_EXTENSIONS

    def _load(self) -> QPixmap | None:
        cache = self._cache_path()

        if Path(cache).exists():
            pix = QPixmap(cache)
            if not pix.isNull():
                return pix

        if self._is_video():
            return self._load_video(cache)
        return self._load_image(cache)

    def _load_image(self, cache: str) -> QPixmap | None:
        try:
            with Image.open(self.path) as img:
                img = ImageOps.exif_transpose(img)
                img.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                img.save(cache, "JPEG", quality=85, optimize=True)
        except Exception:
            return None
        pix = QPixmap(cache)
        return pix if not pix.isNull() else None

    def _load_video(self, cache: str) -> QPixmap | None:
        if not _FFMPEG:
            return None

        # Try at 1 second, fall back to first frame for short clips
        for seek in ("1", "0"):
            try:
                result = subprocess.run(
                    [
                        _FFMPEG, "-y",
                        "-ss", seek,
                        "-i", self.path,
                        "-vframes", "1",
                        "-vf", f"scale={THUMB_SIZE}:{THUMB_SIZE}:force_original_aspect_ratio=decrease",
                        "-q:v", "3",
                        cache,
                    ],
                    capture_output=True,
                    timeout=15,
                )
                if result.returncode == 0 and Path(cache).exists():
                    pix = QPixmap(cache)
                    if not pix.isNull():
                        return pix
            except (subprocess.TimeoutExpired, OSError):
                pass

        return None


class ThumbnailLoader(QObject):
    thumbnail_ready = Signal(str, QPixmap)

    def __init__(self, cache_dir: str, parent=None):
        super().__init__(parent)
        self.cache_dir = cache_dir
        Path(cache_dir).mkdir(parents=True, exist_ok=True)

        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(4)

        self._pending: set[str] = set()
        self._lock = threading.Lock()

        self._signals = _ThumbSignals()
        self._signals.ready.connect(self._on_ready)

    def request(self, path: str):
        with self._lock:
            if path in self._pending:
                return
            self._pending.add(path)
        task = _ThumbTask(path, self.cache_dir, self._signals)
        self._pool.start(task)

    def invalidate(self, path: str):
        h = hashlib.md5(path.encode()).hexdigest()
        cache = Path(self.cache_dir) / f"{h}.jpg"
        try:
            cache.unlink(missing_ok=True)
        except OSError:
            pass

    def _on_ready(self, path: str, pixmap: QPixmap):
        with self._lock:
            self._pending.discard(path)
        self.thumbnail_ready.emit(path, pixmap)
