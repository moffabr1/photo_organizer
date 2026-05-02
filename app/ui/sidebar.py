"""
Left sidebar with three collapsible sections:
  • All Photos (top-level shortcut)
  • Sources    (filesystem folders)
  • Albums     (virtual collections)
  • Tags       (keyword labels)

Right-click items for remove/delete actions.
Signals flow up to MainWindow which performs the actual DB operations,
then calls sidebar.refresh().
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QLabel, QMenu, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

_HEADER_STYLE = QColor("#666")


class Sidebar(QWidget):
    # ── Outgoing signals ───────────────────────────────────────────────────
    add_folder_requested   = Signal()
    all_photos_selected    = Signal()
    source_selected        = Signal(int)    # source_id
    album_selected         = Signal(int)    # album_id
    tag_selected           = Signal(int)    # tag_id
    remove_source_requested = Signal(int)
    new_album_requested    = Signal()
    delete_album_requested = Signal(int)
    new_tag_requested      = Signal()
    delete_tag_requested   = Signal(int)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db = db
        self._build_ui()

    # ── Setup ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setFixedWidth(224)
        self.setStyleSheet("""
            QWidget        { background: #242426; color: #d0d0d0; }
            QLabel         { color: #e8e8e8; }
            QTreeWidget {
                background: #242426;
                border: none;
                font-size: 13px;
                color: #c8c8c8;
                outline: none;
            }
            QTreeWidget::item          { padding: 5px 6px; border-radius: 5px; }
            QTreeWidget::item:hover    { background: #2e2e32; }
            QTreeWidget::item:selected { background: #38383e; color: #fff; }
            QTreeWidget::branch        { background: transparent; }
            QPushButton {
                background: #3a3a3f;
                border: 1px solid #505056;
                border-radius: 6px;
                color: #d4d4d4;
                padding: 7px 14px;
                font-size: 13px;
            }
            QPushButton:hover  { background: #46464e; }
            QPushButton:pressed { background: #2e2e36; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(6)

        # Title
        title = QLabel("  📷  Photo Organizer")
        title.setStyleSheet(
            "font-size: 14px; font-weight: 600; "
            "padding: 4px 4px 10px 4px; color: #f0f0f0;"
        )
        layout.addWidget(title)

        # Tree
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(14)
        self.tree.itemClicked.connect(self._on_item_click)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_ctx_menu)
        layout.addWidget(self.tree, 1)

        # Separator line
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #38383e;")
        layout.addWidget(sep)

        # Add-folder button
        self._add_btn = QPushButton("＋   Add Folder")
        self._add_btn.clicked.connect(self.add_folder_requested)
        layout.addWidget(self._add_btn)

        self._populate()

    # ── Tree population ────────────────────────────────────────────────────

    def _make_header(self, label: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label])
        item.setData(0, Qt.UserRole, ("header", None))
        item.setForeground(0, _HEADER_STYLE)
        f = QFont()
        f.setPointSize(10)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
        item.setFont(0, f)
        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
        return item

    def _populate(self):
        self.tree.clear()

        # ── All Photos ─────────────────────────────────────────────────────
        all_item = QTreeWidgetItem(["  🖼   All Photos"])
        all_item.setData(0, Qt.UserRole, ("all", None))
        self.tree.addTopLevelItem(all_item)

        # ── Sources ────────────────────────────────────────────────────────
        src_hdr = self._make_header("  SOURCES")
        self.tree.addTopLevelItem(src_hdr)
        src_hdr.setExpanded(True)
        for src in self._db.get_sources():
            label = src["path"]
            if len(label) > 26:
                label = "…" + label[-24:]
            child = QTreeWidgetItem([f"    {label}"])
            child.setData(0, Qt.UserRole, ("source", src["id"]))
            child.setToolTip(0, src["path"])
            src_hdr.addChild(child)

        # ── Albums ─────────────────────────────────────────────────────────
        alb_hdr = self._make_header("  ALBUMS")
        self.tree.addTopLevelItem(alb_hdr)
        alb_hdr.setExpanded(True)
        for alb in self._db.get_albums():
            child = QTreeWidgetItem([f"    {alb['name']}"])
            child.setData(0, Qt.UserRole, ("album", alb["id"]))
            alb_hdr.addChild(child)

        # ── Tags ───────────────────────────────────────────────────────────
        tag_hdr = self._make_header("  TAGS")
        self.tree.addTopLevelItem(tag_hdr)
        tag_hdr.setExpanded(True)
        for tag in self._db.get_tags():
            child = QTreeWidgetItem([f"    #{tag['name']}"])
            child.setData(0, Qt.UserRole, ("tag", tag["id"]))
            tag_hdr.addChild(child)

    def refresh(self):
        self._populate()

    # ── Interaction handlers ───────────────────────────────────────────────

    def _on_item_click(self, item: QTreeWidgetItem, _col: int):
        kind, value = item.data(0, Qt.UserRole)
        if kind == "all":
            self.all_photos_selected.emit()
        elif kind == "source":
            self.source_selected.emit(value)
        elif kind == "album":
            self.album_selected.emit(value)
        elif kind == "tag":
            self.tag_selected.emit(value)

    def _on_ctx_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
        kind, value = item.data(0, Qt.UserRole)
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background:#2c2c2e; color:#d4d4d4; border:1px solid #48484a; }"
            "QMenu::item { padding:6px 20px; }"
            "QMenu::item:selected { background:#3a3a3f; }"
        )
        gpos = self.tree.viewport().mapToGlobal(pos)

        if kind == "source":
            act = menu.addAction("🗑   Remove Source")
            if menu.exec(gpos) == act:
                self.remove_source_requested.emit(value)

        elif kind == "header" and "ALBUMS" in item.text(0):
            act = menu.addAction("＋   New Album")
            if menu.exec(gpos) == act:
                self.new_album_requested.emit()

        elif kind == "album":
            act = menu.addAction("🗑   Delete Album")
            if menu.exec(gpos) == act:
                self.delete_album_requested.emit(value)

        elif kind == "header" and "TAGS" in item.text(0):
            act = menu.addAction("＋   New Tag")
            if menu.exec(gpos) == act:
                self.new_tag_requested.emit()

        elif kind == "tag":
            act = menu.addAction("🗑   Delete Tag")
            if menu.exec(gpos) == act:
                self.delete_tag_requested.emit(value)
