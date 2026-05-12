"""
High-performance thumbnail grid.

GridModel         – QAbstractListModel; dispatches async thumbnail requests.
ThumbnailDelegate – custom painter: centered image, play overlay for videos,
                    selection ring, placeholder while loading.
GridView          – QListView wired to the model.
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, QPoint, QSize, Qt, Signal,
)
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygon
from PySide6.QtWidgets import (
    QAbstractItemView, QListView, QStyle, QStyledItemDelegate,
)

THUMB_SIZE = 200
CELL_SIZE  = THUMB_SIZE + 16

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".m4v",
    ".wmv", ".flv", ".webm", ".3gp", ".mts", ".m2ts",
}


def _is_video(path: str) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


# ── Model ──────────────────────────────────────────────────────────────────

class GridModel(QAbstractListModel):
    def __init__(self, thumb_loader, parent=None):
        super().__init__(parent)
        self._images: list[dict] = []
        self._cache: dict[str, QPixmap] = {}
        self._max_cache = 800
        self._loader = thumb_loader
        self._loader.thumbnail_ready.connect(self._on_thumb_ready)

    def load_images(self, images: list[dict]):
        self.beginResetModel()
        self._images = images
        self.endResetModel()

    def get_image(self, row: int) -> dict | None:
        if 0 <= row < len(self._images):
            return self._images[row]
        return None

    def all_images(self) -> list[dict]:
        return self._images

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._images)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._images):
            return None
        img = self._images[index.row()]

        if role == Qt.DecorationRole:
            path = img["path"]
            if path in self._cache:
                return self._cache[path]
            self._loader.request(path)
            return None

        if role == Qt.ToolTipRole:
            date = img.get("date_taken", "") or ""
            label = "🎬 " if _is_video(img["path"]) else ""
            return f"{label}{img['path']}\n{date[:10]}" if date else f"{label}{img['path']}"

        if role == Qt.UserRole:
            return img

        return None

    def _on_thumb_ready(self, path: str, pixmap: QPixmap):
        for i, img in enumerate(self._images):
            if img["path"] == path:
                if len(self._cache) >= self._max_cache:
                    oldest = next(iter(self._cache))
                    del self._cache[oldest]
                self._cache[path] = pixmap
                idx = self.index(i)
                self.dataChanged.emit(idx, idx, [Qt.DecorationRole])
                return

    def invalidate_thumb(self, path: str):
        self._cache.pop(path, None)


# ── Delegate ───────────────────────────────────────────────────────────────

class ThumbnailDelegate(QStyledItemDelegate):
    _ACCENT           = QColor(74, 158, 255)
    _PLACEHOLDER      = QColor(55, 55, 58)
    _PLACEHOLDER_TEXT = QColor(100, 100, 105)
    _PLAY_BG          = QColor(0, 0, 0, 140)
    _PLAY_FG          = QColor(255, 255, 255, 220)

    def sizeHint(self, option, index):
        return QSize(CELL_SIZE, CELL_SIZE)

    def paint(self, painter: QPainter, option, index):
        painter.save()

        selected = bool(option.state & QStyle.State_Selected)
        r = option.rect.adjusted(4, 4, -4, -4)

        painter.fillRect(option.rect, QColor(28, 28, 30))

        pixmap: QPixmap | None = index.data(Qt.DecorationRole)
        img = index.data(Qt.UserRole)
        is_vid = img is not None and _is_video(img["path"])

        if pixmap is None:
            painter.fillRect(r, self._PLACEHOLDER)
            painter.setPen(self._PLACEHOLDER_TEXT)
            painter.drawText(r, Qt.AlignCenter, "🎬" if is_vid else "⏳")
        else:
            pw, ph = pixmap.width(), pixmap.height()
            x = option.rect.x() + (option.rect.width()  - pw) // 2
            y = option.rect.y() + (option.rect.height() - ph) // 2
            painter.drawPixmap(x, y, pixmap)

            # Play badge for videos
            if is_vid:
                self._draw_play_badge(painter, option.rect)

        if selected:
            pen = QPen(self._ACCENT, 3)
            painter.setPen(pen)
            painter.drawRect(option.rect.adjusted(2, 2, -2, -2))

        painter.restore()

    def _draw_play_badge(self, painter: QPainter, cell_rect):
        """Draw a semi-transparent play circle in the bottom-right corner."""
        r = 18
        margin = 10
        cx = cell_rect.right()  - margin - r
        cy = cell_rect.bottom() - margin - r

        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self._PLAY_BG)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # Triangle
        size = 8
        tri = QPolygon([
            QPoint(cx - size // 3,       cy - size // 2),
            QPoint(cx - size // 3,       cy + size // 2),
            QPoint(cx + (size * 2) // 3, cy),
        ])
        painter.setBrush(self._PLAY_FG)
        painter.drawPolygon(tri)


# ── View ───────────────────────────────────────────────────────────────────

class GridView(QListView):
    image_activated = Signal(int)

    def __init__(self, model: GridModel, parent=None):
        super().__init__(parent)
        self.setModel(model)
        self.setItemDelegate(ThumbnailDelegate())
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setUniformItemSizes(True)
        self.setGridSize(QSize(CELL_SIZE, CELL_SIZE))
        self.setSpacing(2)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

        self.setStyleSheet("""
            QListView {
                background: #1c1c1e;
                border: none;
                outline: none;
            }
            QListView::item { background: transparent; }
            QListView::item:selected { background: transparent; }
            QScrollBar:vertical {
                background: #1c1c1e;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #48484a;
                border-radius: 4px;
                min-height: 32px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }
        """)

        self.doubleClicked.connect(lambda idx: self.image_activated.emit(idx.row()))

    def scroll_to_row(self, row: int):
        idx = self.model().index(row, 0)
        self.scrollTo(idx, QAbstractItemView.PositionAtTop)
