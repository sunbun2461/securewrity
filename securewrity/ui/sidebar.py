"""Left sidebar: account menu, search, favorites, nested page tree, trash."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QMenu, QPushButton,
                             QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

ROLE = Qt.ItemDataRole.UserRole


def _label(p: dict) -> str:
    return f"{p['icon'] or '📄'}  {p['title'] or 'Untitled'}"


class PageTree(QTreeWidget):
    def __init__(self, sidebar, draggable=True):
        super().__init__()
        self.sidebar = sidebar
        self.setHeaderHidden(True)
        self.setIndentation(14)
        self.setMouseTracking(True)
        self.setAnimated(True)
        self.setExpandsOnDoubleClick(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if draggable:
            self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemClicked.connect(lambda it, _: sidebar.window.open_page(it.data(0, ROLE)))
        self.itemEntered.connect(self._hover)
        self.add_btn = QToolButton(self.viewport())
        self.add_btn.setText("+")
        self.add_btn.setToolTip("Add a page inside")
        self.add_btn.setFixedSize(22, 22)
        self.add_btn.hide()
        self.add_btn.clicked.connect(self._add_inside)
        self._hover_pid = None

    def _hover(self, item):
        r = self.visualItemRect(item)
        self._hover_pid = item.data(0, ROLE)
        self.add_btn.move(self.viewport().width() - 26, r.y() + (r.height() - 22) // 2)
        self.add_btn.show()
        self.add_btn.raise_()

    def leaveEvent(self, e):
        super().leaveEvent(e)
        if not self.add_btn.underMouse():
            self.add_btn.hide()

    def _add_inside(self):
        if self._hover_pid:
            self.sidebar.window.create_page(parent_id=self._hover_pid)

    def _menu(self, pos: QPoint):
        it = self.itemAt(pos)
        if not it:
            return
        m = QMenu(self)
        self.sidebar.window.populate_page_menu(m, it.data(0, ROLE))
        m.exec(self.viewport().mapToGlobal(pos))

    def dropEvent(self, e):
        super().dropEvent(e)
        QTimer.singleShot(0, self.sync_to_repo)

    def sync_to_repo(self):
        repo = self.sidebar.window.ctx.repo

        def walk(parent_item, parent_id):
            n = parent_item.childCount() if parent_item else self.topLevelItemCount()
            for i in range(n):
                it = parent_item.child(i) if parent_item else self.topLevelItem(i)
                repo.move_page(it.data(0, ROLE), parent_id, float(i))
                walk(it, it.data(0, ROLE))
        walk(None, None)
        repo.commit()
        self.sidebar.window.ctx.events.emit("pages_changed")


class Sidebar(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setObjectName("Sidebar")
        self.setMinimumWidth(200)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 8, 6, 8)
        v.setSpacing(2)

        acc = window.ctx.account
        icon = "👤" if acc.is_guest else ("🔒" if window.ctx.store.encrypted else "🔓")
        self.user_btn = QPushButton(f"{icon}  {acc.username}  ▾")
        self.user_btn.setObjectName("SideButton")
        self.user_btn.setStyleSheet("font-weight:600;")
        self.user_btn.clicked.connect(self._user_menu)
        v.addWidget(self.user_btn)

        for text, fn in (("🔍  Search            Ctrl+P", window.quick_switch),
                         ("＋  New page        Ctrl+N", lambda: window.create_page())):
            b = QPushButton(text)
            b.setObjectName("SideButton")
            b.clicked.connect(fn)
            v.addWidget(b)
        v.addSpacing(8)

        self.fav_label = QLabel("FAVORITES")
        self.fav_label.setObjectName("SectionLabel")
        self.fav_label.setContentsMargins(8, 4, 0, 2)
        v.addWidget(self.fav_label)
        self.favs = PageTree(self, draggable=False)
        self.favs.setRootIsDecorated(False)
        self.favs.setMaximumHeight(160)
        v.addWidget(self.favs)

        head = QHBoxLayout()
        lab = QLabel("PAGES")
        lab.setObjectName("SectionLabel")
        lab.setContentsMargins(8, 4, 0, 2)
        head.addWidget(lab)
        head.addStretch(1)
        add = QToolButton()
        add.setText("+")
        add.setToolTip("New page")
        add.clicked.connect(lambda: window.create_page())
        head.addWidget(add)
        v.addLayout(head)

        self.tree = PageTree(self)
        self.tree.itemExpanded.connect(self._save_expanded)
        self.tree.itemCollapsed.connect(self._save_expanded)
        v.addWidget(self.tree, 1)

        for text, fn in (("📥  Import", self._import_menu),
                         ("🗑  Trash", window.show_trash), ("⚙  Settings", window.show_settings),
                         ("❓  Help", lambda: window.show_help())):
            b = QPushButton(text)
            b.setObjectName("SideButton")
            b.clicked.connect(fn)
            v.addWidget(b)
        self._restoring = False

    def _import_menu(self):
        m = QMenu(self)
        m.addAction("📄  Markdown files or Notion .zip…", lambda: self.window.import_markdown())
        m.addAction("📁  A folder of pages…", lambda: self.window.import_markdown(folder=True))
        m.exec(self.cursor().pos())

    def _user_menu(self):
        m = QMenu(self)
        self.window.populate_app_menu(m)
        m.exec(self.user_btn.mapToGlobal(QPoint(0, self.user_btn.height())))

    def refresh(self):
        repo = self.window.ctx.repo
        pages = repo.list_pages()
        expanded = set(repo.get_setting("sidebar_expanded", []))
        current = self.window.editor.page_id
        self._restoring = True
        scroll = self.tree.verticalScrollBar().value()
        self.tree.clear()
        items: dict[str, QTreeWidgetItem] = {}
        by_parent: dict = {}
        for p in pages:
            by_parent.setdefault(p["parent_id"], []).append(p)
        ids = {p["id"] for p in pages}

        def build(parent_id, parent_item):
            for p in by_parent.get(parent_id, []):
                it = QTreeWidgetItem([_label(p)])
                it.setData(0, ROLE, p["id"])
                it.setToolTip(0, p["title"] or "Untitled")
                if parent_item is None:
                    self.tree.addTopLevelItem(it)
                else:
                    parent_item.addChild(it)
                items[p["id"]] = it
                build(p["id"], it)
        build(None, None)
        # orphans (parent missing) show at top level
        for pid, lst in by_parent.items():
            if pid is not None and pid not in ids:
                for p in lst:
                    if p["id"] not in items:
                        it = QTreeWidgetItem([_label(p)])
                        it.setData(0, ROLE, p["id"])
                        self.tree.addTopLevelItem(it)
                        items[p["id"]] = it
                        build(p["id"], it)
        for pid, it in items.items():
            if pid in expanded:
                it.setExpanded(True)
        if current in items:
            self.tree.setCurrentItem(items[current])
        self.tree.verticalScrollBar().setValue(scroll)

        self.favs.clear()
        favs = [p for p in pages if p["favorite"]]
        for p in favs:
            it = QTreeWidgetItem([_label(p)])
            it.setData(0, ROLE, p["id"])
            self.favs.addTopLevelItem(it)
        self.favs.setVisible(bool(favs))
        self.fav_label.setVisible(bool(favs))
        self.favs.setFixedHeight(min(160, 30 * len(favs) + 6))
        self._restoring = False
        self.items = items

    def reveal(self, page_id: str):
        """Expand ancestors and select the page."""
        it = getattr(self, "items", {}).get(page_id)
        if not it:
            return
        p = it.parent()
        changed = False
        while p:
            if not p.isExpanded():
                p.setExpanded(True)
                changed = True
            p = p.parent()
        self.tree.setCurrentItem(it)
        self.tree.scrollToItem(it)
        if changed:
            self._save_expanded()

    def _save_expanded(self, *_):
        if self._restoring:
            return
        out = []

        def walk(it):
            if it.isExpanded():
                out.append(it.data(0, ROLE))
            for i in range(it.childCount()):
                walk(it.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        self.window.ctx.repo.set_setting("sidebar_expanded", out)
