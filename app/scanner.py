"""
Asynchronous folder scanner.
Walks one or more directory trees in a background QThread, emitting a signal
for every image or video found so the UI can update incrementally.
"""
from __future__ import annotations
import os
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QThread, Signal

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp",
    ".tiff", ".tif", ".bmp", ".gif",
}

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".m4v",
    ".wmv", ".flv", ".webm", ".3gp", ".mts", ".m2ts",
}

ALL_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


def get_exif_date(path: str) -> str:
    """Return DateTimeOriginal from EXIF, or '' on any failure."""
    try:
        with Image.open(path) as img:
            exif = img._getexif()  # type: ignore[attr-defined]
            if exif:
                dt = exif.get(36867) or exif.get(36868) or exif.get(306)
                if dt:
                    return str(dt)
    except Exception:
        pass
    return ""


class FolderScanner(QThread):
    """
    Signals
    -------
    image_found(path, source_id, mtime, date_taken)
        Emitted for every new/changed image or video found.
    progress(count, current_path)
        Emitted periodically so the status bar can update.
    done(total_count)
        Emitted when the scan finishes (or is aborted).
    """

    image_found: Signal = Signal(str, int, float, str)
    progress: Signal = Signal(int, str)
    done: Signal = Signal(int)

    def __init__(self, paths_with_ids: list[tuple[str, int]], db, parent=None):
        super().__init__(parent)
        self._paths = paths_with_ids
        self._db = db
        self._abort = False

    def stop(self):
        self._abort = True

    def run(self):
        count = 0
        for folder, source_id in self._paths:
            for root, dirs, files in os.walk(folder, followlinks=False):
                dirs.sort()
                for fname in sorted(files):
                    if self._abort:
                        self.done.emit(count)
                        return

                    ext = Path(fname).suffix.lower()
                    if ext not in ALL_EXTENSIONS:
                        continue

                    full_path = os.path.join(root, fname)
                    try:
                        mtime = os.path.getmtime(full_path)

                        existing = self._db.get_image_by_path(full_path)
                        if existing and abs(existing["mtime"] - mtime) < 0.01:
                            count += 1
                            if count % 50 == 0:
                                self.progress.emit(count, full_path)
                            continue

                        # Only try EXIF on images, not video
                        if ext in IMAGE_EXTENSIONS:
                            date_taken = get_exif_date(full_path)
                        else:
                            date_taken = ""

                        self.image_found.emit(full_path, source_id, mtime, date_taken)
                        count += 1
                        if count % 20 == 0:
                            self.progress.emit(count, full_path)

                    except OSError:
                        pass

        self.done.emit(count)
