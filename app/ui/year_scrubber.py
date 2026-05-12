"""
Year scrubber — narrow vertical strip to the right of the grid.
Shows years present in the current view; clicking jumps to that year.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

_BTN_SS = """
    QPushButton {
        background: transparent;
        border: none;
        color: #606068;
        font-size: 11px;
        font-weight: 600;
        padding: 2px 0;
        letter-spacing: 0.5px;
    }
    QPushButton:hover  { color: #4a9eff; }
    QPushButton:pressed { color: #2a7adf; }
"""

_ACTIVE_SS = """
    QPushButton {
        background: transparent;
        border: none;
        color: #4a9eff;
        font-size: 11px;
        font-weight: 600;
        padding: 2px 0;
        letter-spacing: 0.5px;
    }
"""


class YearScrubber(QWidget):
    jump_to_row = Signal(int)   # emits first row of the clicked year

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(44)
        self.setStyleSheet("QWidget { background: #1c1c1e; }")
        self._year_rows: dict[str, int] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scrollable inner area so long year lists don't overflow
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: #1c1c1e; }"
        )

        inner = QWidget()
        inner.setStyleSheet("QWidget { background: #1c1c1e; }")
        self._inner_layout = QVBoxLayout(inner)
        self._inner_layout.setContentsMargins(0, 12, 0, 12)
        self._inner_layout.setSpacing(0)
        self._inner_layout.addStretch()

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def update_years(self, year_rows: dict[str, int]):
        """year_rows: {'2024': first_row, '2023': first_row, ...}"""
        self._year_rows = year_rows
        self._buttons.clear()

        # Clear existing buttons (keep the stretch at the end)
        while self._inner_layout.count() > 1:
            item = self._inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Add years newest first
        for year in sorted(year_rows.keys(), reverse=True):
            row = year_rows[year]
            btn = QPushButton(year)
            btn.setFixedHeight(24)
            btn.setFixedWidth(44)
            btn.setStyleSheet(_BTN_SS)
            btn.clicked.connect(
                lambda checked=False, r=row: self.jump_to_row.emit(r)
            )
            self._inner_layout.insertWidget(
                self._inner_layout.count() - 1, btn
            )
            self._buttons[year] = btn

    def highlight_year(self, year: str):
        for y, btn in self._buttons.items():
            btn.setStyleSheet(_ACTIVE_SS if y == year else _BTN_SS)
