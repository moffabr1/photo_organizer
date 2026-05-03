"""
Full-size image preview window with simple non-destructive enhancement.

Navigation : ← → Space Esc
Enhancement: Brightness / Contrast / Saturation / Sharpness sliders
             + Auto-enhance button.
             Changes are preview-only until Apply is clicked.
             Apply writes to disk and emits file_changed(path).
"""
from __future__ import annotations
import os
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSlider, QVBoxLayout, QWidget, QMessageBox,
)

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".m4v",
    ".wmv", ".flv", ".webm", ".3gp", ".mts", ".m2ts",
}

_BTN = """
    QPushButton {
        background: #3a3a3f; border: none; color: #c8c8c8;
        border-radius: 5px; font-size: 13px; padding: 5px 12px;
    }
    QPushButton:hover   { background: #4a4a52; }
    QPushButton:pressed { background: #28282e; }
    QPushButton:disabled { color: #505055; background: #2a2a2e; }
    QPushButton:checked { background: #2a4a7a; color: #7ab8ff; }
"""
_SLIDER_SS = """
    QSlider::groove:horizontal {
        background: #3a3a3f; height: 4px; border-radius: 2px;
    }
    QSlider::handle:horizontal {
        background: #7ab8ff; width: 14px; height: 14px;
        margin: -5px 0; border-radius: 7px;
    }
    QSlider::sub-page:horizontal { background: #4a9eff; border-radius: 2px; }
"""


def _is_video(path: str) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def _pil_to_pixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGB":
        img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    from PySide6.QtGui import QImage
    qi = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qi)


class PreviewWindow(QDialog):
    file_changed = Signal(str)   # emitted after Apply so grid refreshes thumb

    def __init__(self, images: list[dict], start_index: int = 0, parent=None):
        super().__init__(parent)
        self._images  = images
        self._idx     = max(0, min(start_index, len(images) - 1))
        self._orig_pil: Image.Image | None = None   # full-res PIL for enhance
        self._enhance_open = False
        self._zoom = 1.0

        self.setWindowTitle("Preview")
        self.setModal(False)
        self.resize(1280, 860)
        self.setStyleSheet("QDialog { background: #111113; }")
        self._build_ui()
        self._show_current()

    # ── Layout ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Image area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignCenter)
        self._scroll.setStyleSheet(
            "QScrollArea { border: none; background: #111113; }"
        )
        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignCenter)
        self._img_lbl.setStyleSheet("background: #111113;")
        self._scroll.setWidget(self._img_lbl)
        root.addWidget(self._scroll, 1)

        # Enhance panel (hidden by default)
        self._enhance_widget = self._build_enhance_panel()
        self._enhance_widget.setVisible(False)
        root.addWidget(self._enhance_widget)

        # Bottom bar
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet(
            "QWidget { background: #1e1e22; border-top: 1px solid #2e2e34; }"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 14, 0)

        self._prev_btn = QPushButton("◀")
        self._next_btn = QPushButton("▶")
        for btn in (self._prev_btn, self._next_btn):
            btn.setFixedSize(34, 28)
            btn.setStyleSheet(_BTN)

        self._info_lbl = QLabel()
        self._info_lbl.setStyleSheet(
            "color: #909098; font-size: 12px; background: transparent;"
        )

        self._enhance_btn = QPushButton("✦  Enhance")
        self._enhance_btn.setCheckable(True)
        self._enhance_btn.setStyleSheet(_BTN)

        open_btn = QPushButton("Open Externally")
        open_btn.setStyleSheet(_BTN + "QPushButton { font-size: 12px; }")

        self._prev_btn.clicked.connect(self._prev)
        self._next_btn.clicked.connect(self._next)
        self._enhance_btn.toggled.connect(self._toggle_enhance)
        open_btn.clicked.connect(self._open_external)

        row.addWidget(self._prev_btn)
        row.addWidget(self._next_btn)
        row.addSpacing(10)
        row.addStretch()
        row.addWidget(self._info_lbl)
        row.addStretch()
        row.addWidget(self._enhance_btn)
        row.addSpacing(8)
        row.addWidget(open_btn)

        root.addWidget(bar)

    def _build_enhance_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet(
            "QWidget { background: #1a1a1e; border-top: 1px solid #2e2e36; }"
            "QLabel  { color: #909098; font-size: 11px; background: transparent; }"
        )
        panel.setFixedHeight(92)

        outer = QHBoxLayout(panel)
        outer.setContentsMargins(18, 10, 18, 10)
        outer.setSpacing(28)

        self._sliders: dict[str, QSlider] = {}
        self._slider_labels: dict[str, QLabel] = {}

        for name in ("Brightness", "Contrast", "Saturation", "Sharpness"):
            col = QVBoxLayout()
            col.setSpacing(4)
            lbl = QLabel(name)
            lbl.setAlignment(Qt.AlignCenter)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(-100, 100)
            sl.setValue(0)
            sl.setFixedWidth(130)
            sl.setStyleSheet(_SLIDER_SS)
            sl.valueChanged.connect(self._on_slider_changed)
            val_lbl = QLabel("0")
            val_lbl.setAlignment(Qt.AlignCenter)
            col.addWidget(lbl)
            col.addWidget(sl)
            col.addWidget(val_lbl)
            outer.addLayout(col)
            self._sliders[name] = sl
            self._slider_labels[name] = val_lbl

        outer.addSpacing(12)

        # Buttons column
        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)
        auto_btn   = QPushButton("Auto")
        reset_btn  = QPushButton("Reset")
        apply_btn  = QPushButton("Apply")
        apply_btn.setStyleSheet(
            _BTN + "QPushButton { background: #1a4a2a; color: #6af0a0; }"
                   "QPushButton:hover { background: #1e5e34; }"
        )
        auto_btn.setStyleSheet(_BTN)
        reset_btn.setStyleSheet(_BTN)
        auto_btn.clicked.connect(self._auto_enhance)
        reset_btn.clicked.connect(self._reset_sliders)
        apply_btn.clicked.connect(self._apply_enhance)
        btn_col.addWidget(auto_btn)
        btn_col.addWidget(reset_btn)
        btn_col.addWidget(apply_btn)
        outer.addLayout(btn_col)

        return panel

    # ── Navigation ─────────────────────────────────────────────────────────

    def _show_current(self):
        if not self._images:
            return
        img = self._images[self._idx]
        path = img["path"]

        self._orig_pil = None
        self._zoom = 1.0
        self._reset_sliders(update_preview=False)

        if _is_video(path):
            self._img_lbl.setText(
                f'<span style="color:#909098; font-size:14px;">'
                f'🎬  Video file — double-click in grid to open in player<br>'
                f'<small>{path}</small></span>'
            )
            self._enhance_btn.setEnabled(False)
        else:
            self._enhance_btn.setEnabled(True)
            try:
                self._orig_pil = Image.open(path).copy()
                ImageOps.exif_transpose(self._orig_pil, in_place=True)
            except Exception:
                self._orig_pil = None
            self._refresh_preview()

        fname = os.path.basename(path)
        date  = (img.get("date_taken") or "")[:10]
        pos   = f"{self._idx + 1} / {len(self._images)}"
        parts = [fname]
        if self._orig_pil:
            parts.append(f"{self._orig_pil.width}×{self._orig_pil.height}")
        if date:
            parts.append(date)
        parts.append(pos)
        self._info_lbl.setText("   ·   ".join(parts))
        self.setWindowTitle(f"Preview — {fname}")

        self._prev_btn.setEnabled(self._idx > 0)
        self._next_btn.setEnabled(self._idx < len(self._images) - 1)

    def _refresh_preview(self):
        """Re-render the preview from _orig_pil with current slider values and zoom."""
        if self._orig_pil is None:
            return
        img = self._apply_adjustments(self._orig_pil)
        pix = _pil_to_pixmap(img)

        if self._zoom == 1.0:
            # Fit to window
            available = self._scroll.size() - QSize(24, 24)
            if available.width() < 1:
                available = QSize(1200, 780)
            scaled = pix.scaled(available, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            # Zoom relative to natural size
            w = int(pix.width() * self._zoom)
            h = int(pix.height() * self._zoom)
            scaled = pix.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        self._img_lbl.setPixmap(scaled)
        self._img_lbl.resize(scaled.size())

    def _apply_adjustments(self, img: Image.Image) -> Image.Image:
        """Return a new PIL image with all slider adjustments applied."""
        def factor(val: int) -> float:
            # slider -100..+100 → factor 0.0..2.0 (1.0 = no change)
            return 1.0 + val / 100.0

        img = ImageEnhance.Brightness(img).enhance(
            factor(self._sliders["Brightness"].value())
        )
        img = ImageEnhance.Contrast(img).enhance(
            factor(self._sliders["Contrast"].value())
        )
        img = ImageEnhance.Color(img).enhance(
            factor(self._sliders["Saturation"].value())
        )
        img = ImageEnhance.Sharpness(img).enhance(
            factor(self._sliders["Sharpness"].value())
        )
        return img

    def _prev(self):
        if self._idx > 0:
            self._idx -= 1
            self._show_current()

    def _next(self):
        if self._idx < len(self._images) - 1:
            self._idx += 1
            self._show_current()

    def _open_external(self):
        if self._images:
            os.system(f'xdg-open "{self._images[self._idx]["path"]}"')

    # ── Enhance panel ──────────────────────────────────────────────────────

    def _toggle_enhance(self, checked: bool):
        self._enhance_widget.setVisible(checked)

    def _on_slider_changed(self, _val: int):
        # Update the numeric label next to each slider
        for name, sl in self._sliders.items():
            self._slider_labels[name].setText(str(sl.value()))
        self._refresh_preview()

    def _reset_sliders(self, update_preview: bool = True):
        for sl in self._sliders.values():
            sl.blockSignals(True)
            sl.setValue(0)
            sl.blockSignals(False)
        for lbl in self._slider_labels.values():
            lbl.setText("0")
        if update_preview:
            self._refresh_preview()

    def _auto_enhance(self):
        if self._orig_pil is None:
            return
        # Auto-contrast then slight sharpness boost
        auto = ImageOps.autocontrast(self._orig_pil, cutoff=0.5)
        # Reflect roughly in sliders (contrast up a bit, sharpness up a bit)
        self._sliders["Contrast"].setValue(15)
        self._sliders["Sharpness"].setValue(20)
        self._sliders["Brightness"].setValue(0)
        self._sliders["Saturation"].setValue(0)
        # Override preview with actual autocontrast result
        available = self._scroll.size() - QSize(24, 24)
        pix = _pil_to_pixmap(auto)
        scaled = pix.scaled(available, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._img_lbl.setPixmap(scaled)

    def _apply_enhance(self):
        if self._orig_pil is None:
            return
        path = self._images[self._idx]["path"]
        ret = QMessageBox.question(
            self, "Apply Enhancement",
            "Save changes to disk? This overwrites the original file.",
        )
        if ret != QMessageBox.Yes:
            return
        try:
            result = self._apply_adjustments(self._orig_pil)
            result.save(path)
            self._orig_pil = result.copy()
            self._reset_sliders()
            self.file_changed.emit(path)
        except Exception as exc:
            QMessageBox.warning(self, "Save Failed", str(exc))

    # ── Events ─────────────────────────────────────────────────────────────

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self._zoom = min(self._zoom * 1.15, 8.0)
        else:
            self._zoom = max(self._zoom / 1.15, 0.1)
        self._refresh_preview()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent):
        k = event.key()
        if k == Qt.Key_Escape:
            self.close()
        elif k in (Qt.Key_Right, Qt.Key_Space):
            self._next()
        elif k == Qt.Key_Left:
            self._prev()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_preview()