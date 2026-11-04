"""The page editor: header (icon, title, breadcrumbs) + a tree of BlockWidgets."""
from __future__ import annotations

import re
from html import escape

from PyQt6.QtCore import QPoint, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QFont, QKeySequence, QTextCharFormat
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu,
                             QPushButton, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout,
                             QWidget)

from ...blocks.registry import registry
from .. import theme
from . import richtext
from ...core.markdown_import import looks_like_markdown, parse_markdown
from .block_widget import BlockWidget
from .richtext import html_to_markdown
from .popups import EmojiPicker, InlineToolbar, SlashMenu, add_color_actions

K = Qt.Key
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
ALT = Qt.KeyboardModifier.AltModifier
LIST_TYPES = {"bullet", "numbered", "todo", "toggle", "quote", "callout"}
NUM_RE = re.compile(r"^\d+\.$")
HANDLE_PAD = 22  # aligns header with block text (handle width + spacing)


def _first_line(te) -> bool:
    c = te.textCursor()
    b = c.block()
    if b != te.document().firstBlock():
        return False
    line = b.layout().lineForTextPosition(c.positionInBlock())
    return (not line.isValid()) or line.lineNumber() == 0


def _last_line(te) -> bool:
    c = te.textCursor()
    b = c.block()
    if b != te.document().lastBlock():
        return False
    line = b.layout().lineForTextPosition(c.positionInBlock())
    return (not line.isValid()) or line.lineNumber() == b.layout().lineCount() - 1


def _fresh_ids(data: dict) -> dict:
    d = dict(data)
    d.pop("id", None)
    d["children"] = [_fresh_ids(c) for c in data.get("children", [])]
    return d


class _ClickArea(QWidget):
    def __init__(self, cb):
        super().__init__()
        self.cb = cb
        self.setMinimumHeight(160)
        self.setCursor(Qt.CursorShape.IBeamCursor)

    def mousePressEvent(self, e):
        self.cb()


class PageEditor(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("EditorRoot")
        self.page_id: str | None = None
        self.blocks: list[BlockWidget] = []
        self.current: BlockWidget | None = None
        self._loading = False
        self._status: dict[str, str] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # top bar -----------------------------------------------------------
        bar = QWidget()
        bar.setFixedHeight(42)
        self.bar_layout = QHBoxLayout(bar)
        self.bar_layout.setContentsMargins(10, 4, 10, 4)
        self.crumbs = QHBoxLayout()
        self.crumbs.setSpacing(0)
        self.bar_layout.addLayout(self.crumbs)
        self.bar_layout.addStretch(1)
        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.bar_layout.addWidget(self.status)
        self.fav_btn = QToolButton()
        self.fav_btn.setToolTip("Add to favorites")
        self.fav_btn.clicked.connect(self.toggle_favorite)
        self.bar_layout.addWidget(self.fav_btn)
        self.more_btn = QToolButton()
        self.more_btn.setText("⋯")
        self.more_btn.setToolTip("Page options")
        self.more_btn.clicked.connect(self.show_page_menu)
        self.bar_layout.addWidget(self.more_btn)
        self.help_btn = QToolButton()
        self.help_btn.setText("?")
        self.help_btn.setToolTip("Help (F1)")
        self.help_btn.setStyleSheet("QToolButton{font-weight:700;}")
        self.help_btn.clicked.connect(lambda: self.ctx.window.show_help())
        self.bar_layout.addWidget(self.help_btn)
        root.addWidget(bar)

        # scrollable canvas -------------------------------------------------
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        canvas = QWidget()
        canvas.setObjectName("EditorCanvas")
        h = QHBoxLayout(canvas)
        h.setContentsMargins(40, 20, 40, 0)
        h.addStretch(1)
        self.column = QWidget()
        self.column.setMaximumWidth(900)
        self.column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        h.addWidget(self.column, 6)
        h.addStretch(1)
        col = QVBoxLayout(self.column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        self.icon_btn = QToolButton()
        self.icon_btn.setStyleSheet("QToolButton{font-size:54px; padding:2px;}")
        self.icon_btn.clicked.connect(self.pick_icon)
        self.add_icon_btn = QPushButton("☺  Add icon")
        self.add_icon_btn.setObjectName("SideButton")
        self.add_icon_btn.clicked.connect(self.pick_icon)
        ib = QHBoxLayout()
        ib.setContentsMargins(HANDLE_PAD, 0, 0, 0)
        ib.addWidget(self.icon_btn)
        ib.addWidget(self.add_icon_btn)
        ib.addStretch(1)
        col.addLayout(ib)

        self.title = QLineEdit()
        self.title.setObjectName("Title")
        self.title.setPlaceholderText("Untitled")
        self.title.textEdited.connect(self._title_edited)
        self.title.returnPressed.connect(self._title_enter)
        self.title.installEventFilter(self)
        tl = QHBoxLayout()
        tl.setContentsMargins(HANDLE_PAD, 4, 0, 12)
        tl.addWidget(self.title)
        col.addLayout(tl)

        self.blocks_host = QWidget()
        self.root_layout = QVBoxLayout(self.blocks_host)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)
        col.addWidget(self.blocks_host)
        col.addWidget(_ClickArea(self.click_below))

        self.backlinks = QWidget()
        self.backlinks_layout = QVBoxLayout(self.backlinks)
        self.backlinks_layout.setContentsMargins(HANDLE_PAD, 0, 0, 40)
        col.addWidget(self.backlinks)
        col.addStretch(1)
        self.scroll.setWidget(canvas)
        root.addWidget(self.scroll, 1)

        # timers & popups ---------------------------------------------------
        self.save_timer = QTimer(self, singleShot=True, interval=600, timeout=self.save_now)
        self.title_timer = QTimer(self, singleShot=True, interval=500, timeout=self._save_title)
        self.slash = SlashMenu(self)
        self.toolbar = InlineToolbar(self, self)

    # =====================================================================
    # loading & saving
    # =====================================================================
    @property
    def repo(self):
        return self.ctx.repo

    def base_font(self) -> QFont:
        return QApplication.font()

    def load(self, page_id: str):
        self.save_now()
        self.slash.close_menu()
        self.toolbar.hide()
        self._loading = True
        for b in self.blocks:
            b.setParent(None)
            b.deleteLater()
        self.blocks = []
        self.current = None
        self.page_id = page_id
        page = self.repo.get_page(page_id)
        if not page:
            self.page_id = None
            self._loading = False
            return
        self.title.setText(page["title"])
        self._render_icon(page["icon"])
        for data in self.repo.get_blocks(page_id):
            self._insert_widget(BlockWidget(self, data), None, len(self.blocks))
        if not self.blocks:
            self._insert_widget(BlockWidget(self, {"type": "paragraph"}), None, 0)
        self._loading = False
        self.restructure()
        self.refresh_header()
        self.scroll.verticalScrollBar().setValue(0)
        self.ctx.events.emit("page_opened", page_id)

    def reload_keep_focus(self):
        if self.page_id:
            self.save_now()
            self.load(self.page_id)

    def changed(self):
        if not self._loading and self.page_id:
            self.save_timer.start()

    def save_now(self):
        self.save_timer.stop()
        if self.title_timer.isActive():
            self.title_timer.stop()
            self._save_title()
        if not self.page_id or self._loading:
            return
        tree = [b.to_data() for b in self.blocks]
        self.repo.save_blocks(self.page_id, tree)
        self.ctx.events.emit("page_saved", self.page_id)

    def tree_data(self) -> list[dict]:
        return [b.to_data() for b in self.blocks]

    # =====================================================================
    # header
    # =====================================================================
    def refresh_header(self):
        while self.crumbs.count():
            w = self.crumbs.takeAt(0).widget()
            if w:
                w.hide()  # deleteLater alone leaves the old path visible until the next event loop pass
                w.deleteLater()
        if not self.page_id:
            return
        page = self.repo.get_page(self.page_id)
        if not page:
            return
        chain = self.repo.ancestors(self.page_id) + [page]
        for i, p in enumerate(chain):
            if i:
                sep = QLabel(" / ")
                sep.setObjectName("Muted")
                self.crumbs.addWidget(sep)
            b = QPushButton(f"{p['icon'] + ' ' if p['icon'] else ''}{(p['title'] or 'Untitled')[:28]}")
            b.setObjectName("SideButton")
            b.clicked.connect(lambda _=False, pid=p["id"]: self.ctx.window.open_page(pid))
            self.crumbs.addWidget(b)
        self.fav_btn.setText("★" if page["favorite"] else "☆")
        self.refresh_backlinks()
        self.refresh_page_links()

    def refresh_backlinks(self):
        while self.backlinks_layout.count():
            w = self.backlinks_layout.takeAt(0).widget()
            if w:
                w.deleteLater()
        links = self.repo.backlinks(self.page_id) if self.page_id else []
        if not links:
            return
        lab = QLabel(f"Linked from {len(links)} page{'s' if len(links) > 1 else ''}")
        lab.setObjectName("SectionLabel")
        self.backlinks_layout.addWidget(lab)
        for p in links:
            b = QPushButton(f"↗  {p['icon'] or '📄'} {p['title'] or 'Untitled'}")
            b.setObjectName("SideButton")
            b.clicked.connect(lambda _=False, pid=p["id"]: self.ctx.window.open_page(pid))
            self.backlinks_layout.addWidget(b)

    def refresh_page_links(self):
        for b in self.all_blocks():
            if b.type_key in ("page", "link_to_page") and b.body is not None and hasattr(b.body, "refresh"):
                b.body.refresh()

    def _render_icon(self, icon: str):
        self.icon_btn.setText(icon)
        self.icon_btn.setVisible(bool(icon))
        self.add_icon_btn.setVisible(not icon)

    def pick_icon(self):
        anchor = self.icon_btn if self.icon_btn.isVisible() else self.add_icon_btn
        e = EmojiPicker.pick(anchor)
        if e is None or not self.page_id:
            return
        self.repo.update_page(self.page_id, icon=e)
        self._render_icon(e)
        self.ctx.events.emit("pages_changed")

    def _title_edited(self, _):
        self.title_timer.start()

    def _save_title(self):
        if self.page_id:
            self.repo.update_page(self.page_id, title=self.title.text())
            self.ctx.events.emit("pages_changed")

    def _title_enter(self):
        if self.blocks:
            first = self.blocks[0]
            if first.text and first.plain():
                first = self.insert_block({"type": "paragraph"}, None, 0)
            self.focus_block(first, "start")

    def eventFilter(self, obj, ev):
        if obj is self.title and ev.type() == ev.Type.KeyPress and ev.key() == K.Key_Down and self.blocks:
            self.focus_block(self.blocks[0], "start")
            return True
        return False

    def toggle_favorite(self):
        if not self.page_id:
            return
        p = self.repo.get_page(self.page_id)
        self.repo.update_page(self.page_id, favorite=0 if p["favorite"] else 1)
        self.refresh_header()
        self.ctx.events.emit("pages_changed")

    def show_page_menu(self):
        m = QMenu(self)
        self.ctx.window.populate_page_menu(m, self.page_id)
        m.exec(self.more_btn.mapToGlobal(QPoint(0, self.more_btn.height())))

    def set_status(self, key: str, text: str):
        if text:
            self._status[key] = text
        else:
            self._status.pop(key, None)
        self.status.setText("   ·   ".join(self._status.values()))

    # =====================================================================
    # tree structure
    # =====================================================================
    def siblings(self, bw) -> list[BlockWidget]:
        return bw.parent_block.children if bw.parent_block else self.blocks

    def _list(self, parent):
        return parent.children if parent else self.blocks

    def _layout(self, parent):
        return parent.child_layout if parent else self.root_layout

    def _insert_widget(self, bw, parent, index):
        bw.parent_block = parent
        self._list(parent).insert(index, bw)
        self._layout(parent).insertWidget(index, bw)
        bw.show()

    def _detach(self, bw):
        lst = self.siblings(bw)
        if bw in lst:
            lst.remove(bw)
        self._layout(bw.parent_block).removeWidget(bw)
        old_parent = bw.parent_block
        if old_parent:
            old_parent.update_collapsed()
        return old_parent

    def insert_block(self, data: dict, parent, index: int) -> BlockWidget:
        bw = BlockWidget(self, data, parent)
        self._insert_widget(bw, parent, index)
        if parent:
            parent.update_collapsed()
        self.restructure()
        self.changed()
        return bw

    def insert_after(self, bw, data: dict) -> BlockWidget:
        return self.insert_block(data, bw.parent_block, self.siblings(bw).index(bw) + 1)

    def append_block(self, data: dict) -> BlockWidget:
        last = self.blocks[-1] if self.blocks else None
        if last and last.type_key == "paragraph" and not last.plain() and not last.children:
            return self.turn_into(last, data["type"], props=data.get("props"))
        return self.insert_block(data, None, len(self.blocks))

    def move_widget(self, bw, parent, index):
        had_focus = bw.text.hasFocus() if bw.text else False
        pos = bw.cursor_pos()
        self._detach(bw)
        self._insert_widget(bw, parent, index)
        if parent:
            if parent.is_collapsed():
                parent.toggle_collapsed()
            parent.update_collapsed()
        self.restructure()
        self.changed()
        if had_focus:
            self.focus_block(bw, pos)

    def delete_block(self, bw, trash_pages: bool = True, focus: bool = True):
        target = self.prev_visible(bw) or self.next_visible(bw, skip_children=True)
        if trash_pages:
            stack = [bw]
            trashed = False
            while stack:
                b = stack.pop()
                stack.extend(b.children)
                if b.type_key == "page" and b.props.get("page_id"):
                    self.repo.trash_page(b.props["page_id"])
                    trashed = True
            if trashed:
                self.ctx.events.emit("pages_changed")
        self._detach(bw)
        bw.setParent(None)
        bw.deleteLater()
        if self.current is bw:
            self.current = None
        if not self.blocks:
            target = self.insert_block({"type": "paragraph"}, None, 0)
        self.restructure()
        self.changed()
        if focus and target:
            self.focus_block(target, "end")

    def turn_into(self, bw, key: str, props: dict | None = None, cursor=None) -> BlockWidget:
        bt = registry.get(key)
        data = bw.to_data()
        pos = bw.cursor_pos() if cursor is None else cursor
        keep = {k: v for k, v in data["props"].items() if k in ("color", "bg")}
        data["props"] = {**bt.default_props(), **keep, **(props or {})}
        data["type"] = key
        if not bt.has_text:
            data["content"] = []
        moved_children = []
        if not bt.can_have_children:
            moved_children, data["children"] = data["children"], []
        parent, idx = bw.parent_block, self.siblings(bw).index(bw)
        self._loading = True
        self._detach(bw)
        bw.setParent(None)
        bw.deleteLater()
        nb = BlockWidget(self, data, parent)
        self._insert_widget(nb, parent, idx)
        for i, c in enumerate(moved_children):
            self._insert_widget(BlockWidget(self, c, parent), parent, idx + 1 + i)
        self._loading = False
        if parent:
            parent.update_collapsed()
        self.restructure()
        self.changed()
        self.focus_block(nb, pos)
        return nb

    def restructure(self):
        """Refresh numbering, bullet glyphs and toggle visibility."""
        def walk(lst):
            n = 0
            for b in lst:
                if b.type_key == "numbered":
                    n += 1
                    b.prefix.setText(f"{n}.")
                else:
                    n = 0
                if b.type_key == "bullet":
                    b.btype.refresh(b)
                b.update_collapsed()
                walk(b.children)
        walk(self.blocks)

    def all_blocks(self):
        def walk(lst):
            for b in lst:
                yield b
                yield from walk(b.children)
        return list(walk(self.blocks))

    def visible_blocks(self):
        def walk(lst):
            for b in lst:
                yield b
                if not b.is_collapsed():
                    yield from walk(b.children)
        return list(walk(self.blocks))

    def prev_visible(self, bw):
        v = self.visible_blocks()
        i = v.index(bw) if bw in v else -1
        return v[i - 1] if i > 0 else None

    def next_visible(self, bw, skip_children=False):
        v = self.visible_blocks()
        if bw not in v:
            return None
        i = v.index(bw) + 1
        if skip_children:
            desc = set(id(x) for x in bw.children)
            while i < len(v) and (id(v[i]) in desc or any(a is bw for a in v[i].ancestors())):
                i += 1
        return v[i] if i < len(v) else None

    def focus_block(self, bw, where="end", x: int | None = None):
        if bw is None:
            return
        self.current = bw  # don't wait for the (possibly delayed) focus-in event
        if bw.text:
            bw.text.setFocus()
            if x is not None:
                y = 4 if where == "start" else bw.text.height() - 6
                c = bw.text.cursorForPosition(QPoint(x, y))
                bw.text.setTextCursor(c)
            else:
                bw.set_cursor(where)
            self.scroll.ensureWidgetVisible(bw.text, 0, 60)
        elif bw.body is not None:
            bw.body.setFocus()
            self.scroll.ensureWidgetVisible(bw.body, 0, 60)

    # =====================================================================
    # editing operations
    # =====================================================================
    def split_block(self, bw):
        text = bw.plain()
        pos = bw.cursor_pos()
        bt = bw.btype
        if not text and bw.type_key in LIST_TYPES:
            if bw.parent_block and bw.parent_block.type_key == bw.type_key:
                return self.outdent(bw)
            return self.turn_into(bw, "paragraph")
        new_type = bw.type_key if bt.continues else "paragraph"
        if pos == 0 and text:
            nb = self.insert_block({"type": new_type}, bw.parent_block, self.siblings(bw).index(bw))
            self.focus_block(bw, "start")
            return nb
        left, right = richtext.split_runs(bw.runs(), pos)
        if right:
            bw.set_runs(left)
        data = {"type": new_type, "content": right}
        if (bt.toggle and not bw.is_collapsed()) or (bw.children and not bw.is_collapsed()):
            nb = self.insert_block({"type": "paragraph", "content": right}, bw, 0)
        else:
            nb = self.insert_after(bw, data)
        self.focus_block(nb, "start")
        return nb

    def merge_into_prev(self, bw):
        prev = self.prev_visible(bw)
        if prev is None:
            return
        if prev.text is None:
            if not bw.plain():
                self.delete_block(bw, focus=False)
                self.focus_block(prev)
            elif prev.type_key == "divider":
                self.delete_block(prev, focus=False)
                self.focus_block(bw, "start")
            else:
                self.focus_block(prev)
            return
        join = len(prev.plain())
        prev.set_runs(richtext.merge_runs(prev.runs() + bw.runs()))
        # bw's children move up to bw's position
        lst = self.siblings(bw)
        idx = lst.index(bw)
        for i, c in enumerate(list(bw.children)):
            self._detach(c)
            self._insert_widget(c, bw.parent_block, idx + 1 + i)
        self.delete_block(bw, focus=False)
        self.focus_block(prev, join)

    def backspace_at_start(self, bw):
        if bw.type_key != "paragraph":
            return self.turn_into(bw, "paragraph", cursor=0)
        if bw.parent_block:
            return self.outdent(bw)
        self.merge_into_prev(bw)

    def delete_at_end(self, bw):
        nxt = self.next_visible(bw)
        if nxt is None:
            return
        if nxt.text is None:
            if nxt.type_key == "divider":
                self.delete_block(nxt, focus=False)
                self.focus_block(bw, "end")
            return
        self.merge_into_prev(nxt)

    def indent(self, bw):
        lst = self.siblings(bw)
        i = lst.index(bw)
        if i == 0:
            return
        prev = lst[i - 1]
        if not prev.btype.can_have_children:
            return
        self.move_widget(bw, prev, len(prev.children))

    def outdent(self, bw):
        parent = bw.parent_block
        if not parent:
            return
        lst = parent.children
        i = lst.index(bw)
        following = lst[i + 1:]
        gp = parent.parent_block
        idx = self._list(gp).index(parent) + 1
        self.move_widget(bw, gp, idx)
        for c in following:  # later siblings become this block's children (Notion behaviour)
            self._detach(c)
            self._insert_widget(c, bw, len(bw.children))
        bw.update_collapsed()
        self.restructure()

    def move_up_down(self, bw, delta: int):
        lst = self.siblings(bw)
        i = lst.index(bw)
        j = i + delta
        if 0 <= j < len(lst):
            self.move_widget(bw, bw.parent_block, j)

    def duplicate(self, bw):
        nb = self.insert_after(bw, _fresh_ids(bw.to_data()))
        self.focus_block(nb, "end")

    def add_first_child(self, bw):
        nb = self.insert_block({"type": "paragraph"}, bw, 0)
        self.focus_block(nb, "start")

    def click_below(self):
        last = self.blocks[-1] if self.blocks else None
        if last and last.type_key == "paragraph" and not last.plain() and not last.children:
            return self.focus_block(last, "end")
        nb = self.insert_block({"type": "paragraph"}, None, len(self.blocks))
        self.focus_block(nb, "start")

    def handle_paste(self, bw, text: str, html: str = "", plain: bool = False):
        """Paste. Markdown (including what AIs call "Notion format") and copied web
        pages become real blocks; Ctrl+Shift+V (plain=True) pastes plain text."""
        text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        if plain or bw.type_key == "code" or not bw.text:
            if bw.text:
                bw.text.insertPlainText(text)
            return
        source = None
        if looks_like_markdown(text):
            source = text
        elif html and re.search(r"<(h[1-6]|li|pre|blockquote|strong|b|em|i|a\s|table|details)\b", html, re.I):
            source = html_to_markdown(html) or text
        elif "\n" in text.strip():
            source = text
        if source is None:
            bw.text.insertPlainText(text)
            return
        blocks = parse_markdown(source)
        if not blocks:
            return
        self.insert_parsed(bw, blocks)

    def insert_parsed(self, bw, blocks: list[dict]):
        """Insert a parsed block tree at the cursor in bw."""
        left, right = richtext.split_runs(bw.runs(), bw.cursor_pos())
        first = blocks[0]
        simple_first = first["type"] == "paragraph" and not first["children"]
        # one plain paragraph: just inline text (keeps its bold/links/colors)
        if len(blocks) == 1 and simple_first:
            bw.set_runs(richtext.merge_runs(left + first["content"] + right))
            self.focus_block(bw, len(richtext.plain_text(left + first["content"])))
            self.changed()
            return
        empty = not richtext.plain_text(left + right).strip() and not bw.children
        prev = bw
        rest = blocks
        if not empty:
            if simple_first:
                bw.set_runs(richtext.merge_runs(left + first["content"]))
                rest = blocks[1:]
            else:
                bw.set_runs(richtext.merge_runs(left))
        for data in rest:
            prev = self.insert_after(prev, data)
        if right:
            if prev.text and prev.btype.has_text and not prev.children:
                end = len(prev.plain())
                prev.set_runs(richtext.merge_runs(prev.runs() + right))
                self.focus_block(prev, end)
                return
            prev = self.insert_after(prev, {"type": "paragraph", "content": right})
        if empty:
            self.delete_block(bw, trash_pages=False, focus=False)
        last = prev
        while last.children and not last.is_collapsed():
            last = last.children[-1]
        if last.text:
            self.focus_block(last, "end")
        self.changed()

    # =====================================================================
    # keyboard
    # =====================================================================
    def handle_key(self, bw, e) -> bool:
        key, mods = e.key(), e.modifiers()
        ctrl, shift = bool(mods & CTRL), bool(mods & SHIFT)
        te = bw.text
        cur = te.textCursor()
        pos, has_sel = cur.position(), cur.hasSelection()

        if self.slash.isVisible() and self.slash.bw is bw:
            if key in (K.Key_Up, K.Key_Down):
                self.slash.move_sel(-1 if key == K.Key_Up else 1)
                return True
            if key in (K.Key_Return, K.Key_Enter, K.Key_Tab):
                self.slash.activate()
                return True
            if key == K.Key_Escape:
                self.slash.close_menu()
                return True

        if key in (K.Key_Return, K.Key_Enter):
            if ctrl:
                if bw.type_key == "todo":
                    bw.prefix.toggle()
                elif bw.btype.toggle:
                    bw.toggle_collapsed()
                return True
            if shift:
                return False
            if bw.type_key == "code":
                text = te.toPlainText()
                if pos == len(text) and text.endswith("\n"):
                    c = te.textCursor()
                    c.deletePreviousChar()
                    nb = self.insert_after(bw, {"type": "paragraph"})
                    self.focus_block(nb, "start")
                    return True
                return False
            self.split_block(bw)
            return True

        if key == K.Key_Backspace and not has_sel and pos == 0 and not ctrl:
            self.backspace_at_start(bw)
            return True
        if key == K.Key_Delete and not has_sel and pos == len(te.toPlainText()) and not ctrl:
            self.delete_at_end(bw)
            return True
        if key == K.Key_Tab:
            if bw.type_key == "code":
                te.insertPlainText("    ")
            else:
                self.indent(bw)
            return True
        if key == K.Key_Backtab:
            self.outdent(bw)
            return True

        if ctrl and shift and key in (K.Key_Up, K.Key_Down):
            self.move_up_down(bw, -1 if key == K.Key_Up else 1)
            return True
        if key == K.Key_Up and not shift and not ctrl and _first_line(te):
            prev = self.prev_visible(bw)
            if prev:
                self.focus_block(prev, "end", te.cursorRect().x() if prev.text else None)
            else:
                self.title.setFocus()
            return True
        if key == K.Key_Down and not shift and not ctrl and _last_line(te):
            nxt = self.next_visible(bw)
            if nxt:
                self.focus_block(nxt, "start", te.cursorRect().x() if nxt.text else None)
            return True
        if key == K.Key_Left and not shift and not has_sel and pos == 0:
            prev = self.prev_visible(bw)
            if prev:
                self.focus_block(prev, "end")
                return True
            return False
        if key == K.Key_Right and not shift and not has_sel and pos == len(te.toPlainText()):
            nxt = self.next_visible(bw)
            if nxt:
                self.focus_block(nxt, "start")
                return True
            return False

        if ctrl and not shift:
            if key == K.Key_D:
                self.duplicate(bw)
                return True
            if bw.btype.rich:
                attr = {K.Key_B: "b", K.Key_I: "i", K.Key_U: "u", K.Key_E: "code"}.get(key)
                if attr:
                    self.toggle_inline(attr)
                    return True
                if key == K.Key_K:
                    self.link_selection()
                    return True
        if ctrl and shift and key == K.Key_S and bw.btype.rich:
            self.toggle_inline("s")
            return True

        # Markdown-style shortcuts: "# " "- " "[] " "> " "1. " ...
        if key == K.Key_Space and not ctrl and bw.type_key == "paragraph" and not has_sel:
            before = te.toPlainText()[:pos]
            target = None
            props = None
            if before in ("[x]", "[X]"):
                target, props = "todo", {"checked": True}
            elif NUM_RE.match(before):
                target = "numbered"
            else:
                bt = registry.for_markdown(before)
                target = bt.key if bt and bt.key != "paragraph" else None
            if target:
                c = te.textCursor()
                c.setPosition(0)
                c.setPosition(pos, c.MoveMode.KeepAnchor)
                c.removeSelectedText()
                if registry.get(target).has_text:
                    self.turn_into(bw, target, props=props, cursor=0)
                elif not bw.plain():
                    nb = self.turn_into(bw, target)
                    self.focus_block(self.insert_after(nb, {"type": "paragraph"}), "start")
                return True
        return False

    def after_key(self, bw, e):
        """Runs after the default key handling inserted the character."""
        ch = e.text()
        if not ch or not bw.text:
            return
        text = bw.plain()
        pos = bw.cursor_pos()
        if ch == "/" and bw.type_key != "code":
            self.slash.open_for(bw, pos)
        elif ch == "[" and text[max(0, pos - 2):pos] == "[[" and bw.btype.rich:
            c = bw.text.textCursor()
            c.setPosition(pos - 2)
            c.setPosition(pos, c.MoveMode.KeepAnchor)
            c.removeSelectedText()
            self.link_selection()
        elif ch == "-" and text == "---" and pos == 3 and bw.type_key == "paragraph":
            bw.set_runs([])
            nb = self.turn_into(bw, "divider")
            self.focus_block(self.insert_after(nb, {"type": "paragraph"}), "start")
        elif ch == "`" and text.startswith("```") and pos == 3 and bw.type_key == "paragraph":
            c = bw.text.textCursor()
            c.setPosition(0)
            c.setPosition(3, c.MoveMode.KeepAnchor)
            c.removeSelectedText()
            self.turn_into(bw, "code", cursor=0)

    def handle_nontext_key(self, bw, e):
        key, mods = e.key(), e.modifiers()
        if key in (K.Key_Backspace, K.Key_Delete):
            self.delete_block(bw)
        elif key == K.Key_Up:
            if mods & CTRL and mods & SHIFT:
                self.move_up_down(bw, -1)
            else:
                prev = self.prev_visible(bw)
                self.focus_block(prev, "end") if prev else self.title.setFocus()
        elif key == K.Key_Down:
            if mods & CTRL and mods & SHIFT:
                self.move_up_down(bw, 1)
            else:
                self.focus_block(self.next_visible(bw), "start")
        elif key in (K.Key_Return, K.Key_Enter):
            if bw.type_key in ("page", "link_to_page") and bw.props.get("page_id"):
                self.ctx.window.open_page(bw.props["page_id"])
            else:
                self.focus_block(self.insert_after(bw, {"type": "paragraph"}), "start")
        elif key == K.Key_D and mods & CTRL:
            self.duplicate(bw)

    def on_text_changed(self, bw):
        if self.slash.isVisible() and self.slash.bw is bw:
            self.slash.on_text_changed()

    def on_block_blur(self, bw):
        QTimer.singleShot(150, self._check_blur)

    def _check_blur(self):
        fw = QApplication.focusWidget()
        if QApplication.activePopupWidget() is not None or QApplication.activeModalWidget() is not None:
            return
        cur_text = self.current.text if self.current else None
        if fw is not cur_text:
            self.toolbar.hide()
            self.slash.close_menu()

    # =====================================================================
    # slash menu
    # =====================================================================
    def apply_slash(self, bw, entry: dict, slash_pos: int):
        # remove "/query"
        c = bw.text.textCursor()
        end = c.position()
        c.setPosition(max(0, slash_pos - 1))
        c.setPosition(max(end, slash_pos - 1), c.MoveMode.KeepAnchor)
        c.removeSelectedText()
        bw.text.setTextCursor(c)
        kind, key = entry["kind"], entry["key"]
        if kind in ("c", "bg"):
            bw.set_prop("color" if kind == "c" else "bg", None if key == "default" else key)
            self.focus_block(bw, c.position())
            return
        empty = not bw.plain()
        props = None
        if key == "page":
            self.save_now()
            pid = self.ctx.window.create_page(parent_id=self.page_id, link_in_parent=False, open_it=False)
            props = {"page_id": pid}
        elif key == "link_to_page":
            from ..dialogs import PageSearchDialog
            res = PageSearchDialog.choose(self.ctx, self, mode="pick")
            if not res:
                self.focus_block(bw, c.position())
                return
            props = {"page_id": res}
        if empty and not bw.children:
            nb = self.turn_into(bw, key, props=props, cursor=0)
        else:
            nb = self.insert_after(bw, {"type": key, "props": props or {}})
            self.focus_block(nb, "start")
        if key == "page":
            self.save_now()
            self.ctx.window.open_page(props["page_id"], focus_title=True)
        elif not registry.get(key).has_text:
            # non-text blocks: give the user somewhere to keep typing
            nxt = self.next_visible(nb, skip_children=True)
            if nxt is None or nxt.text is None:
                nxt = self.insert_after(nb, {"type": "paragraph"})
            self.focus_block(nxt, "start")

    # =====================================================================
    # inline formatting & links
    # =====================================================================
    def _text_block(self):
        bw = self.current
        return bw if bw and bw.text and bw.btype.rich else None

    def toggle_inline(self, attr: str):
        bw = self._text_block()
        if not bw:
            return
        te = bw.text
        cur = te.textCursor()
        if not cur.hasSelection():
            f = te.currentCharFormat()
            if attr == "b":
                f.setFontWeight(400 if f.fontWeight() >= 600 else 700)
            elif attr == "i":
                f.setFontItalic(not f.fontItalic())
            elif attr == "u":
                f.setFontUnderline(not f.fontUnderline())
            elif attr == "s":
                f.setFontStrikeOut(not f.fontStrikeOut())
            else:
                return
            te.setCurrentCharFormat(f)
            return
        all_on = all(r.get(attr) for r in richtext.selection_runs(cur))

        def fn(r):
            if all_on:
                r.pop(attr, None)
            else:
                r[attr] = 1
            return r
        richtext.transform_selection(cur, fn)
        self.changed()

    def set_inline_color(self, kind: str, name: str):
        bw = self._text_block()
        if not bw:
            return
        cur = bw.text.textCursor()

        def fn(r):
            if name == "default":
                r.pop(kind, None)
            else:
                r[kind] = name
            return r
        richtext.transform_selection(cur, fn)
        self.changed()

    def link_selection(self):
        bw = self._text_block()
        if not bw:
            return
        from ..dialogs import PageSearchDialog
        te = bw.text
        cur = te.textCursor()
        selected = cur.selectedText()
        self.save_now()
        res = PageSearchDialog.choose(self.ctx, self, mode="link", initial=selected)
        bw.text.setFocus()
        if not res:
            return
        if res.startswith(("http://", "https://", "mailto:", "file://")):
            href, label = res, res
        else:
            href = f"page:{res}"
            p = self.repo.get_page(res)
            label = (p["title"] if p else "") or "Untitled"
        te.setTextCursor(cur)
        if cur.hasSelection():
            richtext.transform_selection(cur, lambda r: {**r, "link": href})
        else:
            cur.insertText(label, richtext.make_format({"link": href}))
            te.setTextCursor(cur)
            te.setCurrentCharFormat(QTextCharFormat())
        self.changed()
        self.save_now()
        self.refresh_backlinks()

    def open_link(self, href: str):
        if href.startswith("page:"):
            self.ctx.window.open_page(href[5:])
        else:
            QDesktopServices.openUrl(QUrl(href))

    def update_inline_toolbar(self, bw):
        if bw.text and bw.btype.rich and bw.text.hasFocus() and bw.text.textCursor().hasSelection():
            self.toolbar.show_for(bw)
        else:
            self.toolbar.hide()

    # =====================================================================
    # menus
    # =====================================================================
    def build_block_menu(self, bw, m: QMenu):
        if bw.type_key in ("page", "link_to_page") and bw.props.get("page_id"):
            m.addAction("Open page", lambda: self.ctx.window.open_page(bw.props["page_id"]))
            m.addSeparator()
        turn = m.addMenu("Turn into")
        for bt in registry.all():
            if bt.has_text and bt.in_slash_menu:
                a = turn.addAction(f"{bt.icon}   {bt.label}")
                a.setCheckable(True)
                a.setChecked(bt.key == bw.type_key)
                a.triggered.connect(lambda _=False, k=bt.key: self.turn_into(bw, k))
        if not bw.btype.has_text:
            turn.setEnabled(False)
        color = m.addMenu("Color")
        add_color_actions(color, lambda kind, n: bw.set_prop("color" if kind == "c" else "bg",
                                                              None if n == "default" else n))
        m.addSeparator()
        m.addAction("Duplicate\tCtrl+D", lambda: self.duplicate(bw))
        m.addAction("Move up\tCtrl+Shift+↑", lambda: self.move_up_down(bw, -1))
        m.addAction("Move down\tCtrl+Shift+↓", lambda: self.move_up_down(bw, 1))
        m.addAction("Indent\tTab", lambda: self.indent(bw))
        m.addAction("Outdent\tShift+Tab", lambda: self.outdent(bw))
        for label, cb in self.ctx.api.block_menu_items:
            m.addAction(label, lambda cb=cb: cb(bw))
        m.addSeparator()
        m.addAction("Delete", lambda: self.delete_block(bw))

    def show_block_menu(self, bw):
        m = QMenu(self)
        self.build_block_menu(bw, m)
        m.exec(bw.handle.mapToGlobal(QPoint(0, bw.handle.height())))

    def extend_context_menu(self, bw, menu: QMenu):
        menu.addSeparator()
        if bw.btype.rich:
            fmt = menu.addMenu("Format")
            for label, attr, sc in (("Bold", "b", "Ctrl+B"), ("Italic", "i", "Ctrl+I"),
                                    ("Underline", "u", "Ctrl+U"), ("Strikethrough", "s", "Ctrl+Shift+S"),
                                    ("Inline code", "code", "Ctrl+E")):
                fmt.addAction(f"{label}\t{sc}", lambda a=attr: self.toggle_inline(a))
            col = menu.addMenu("Text color")
            add_color_actions(col, self.set_inline_color)
            menu.addAction("Link to page / URL…\tCtrl+K", self.link_selection)
        blk = menu.addMenu("Block")
        self.build_block_menu(bw, blk)

