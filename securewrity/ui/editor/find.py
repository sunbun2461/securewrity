"""Ctrl+F: find on the current page.

A small bar at the top right of the page. Every match is highlighted (text blocks and table
cells, including inside closed toggles); the current one is orange and scrolled into view.
  Enter / F3 / Ctrl+G              next match
  Shift+Enter / Shift+F3           previous match
  Aa                               match case
  Esc                              close; the cursor goes to the current match
The search follows the page while you edit it, and when you open another page.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QTextEdit, QToolButton

MATCH_BG, CURRENT_BG, INK = "#FFE36E", "#FF9F43", "#1d1d1d"


class FindBar(QFrame):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setObjectName("Popup")
        self.hide()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 4, 4)
        lay.setSpacing(2)
        self.q = QLineEdit()
        self.q.setPlaceholderText("Find on this page")
        self.q.setClearButtonEnabled(True)
        self.q.setMinimumWidth(200)
        self.q.textChanged.connect(lambda _: self.search(keep_place=False))
        self.q.installEventFilter(self)
        lay.addWidget(self.q, 1)
        self.count = QLabel("")
        self.count.setObjectName("Muted")
        self.count.setMinimumWidth(70)
        self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.count)
        self.case = self._btn("Aa", "Match case", None)
        self.case.setCheckable(True)
        self.case.toggled.connect(lambda _: self.search(keep_place=False))
        self._btn("↑", "Previous match (Shift+Enter)", lambda: self.step(-1))
        self._btn("↓", "Next match (Enter)", lambda: self.step(1))
        self._btn("✕", "Close (Esc)", self.close_bar)
        self.matches: list[tuple] = []   # (bw, start, length) or (bw, ("cell", row, col))
        self.index = -1
        self._tables = []                # table bodies with highlighted cells
        self.refresh_timer = QTimer(self, singleShot=True, interval=250,
                                    timeout=lambda: self.search(keep_place=True))

    def _btn(self, text, tip, cb):
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setAutoRaise(True)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if cb:
            b.clicked.connect(cb)
        self.layout().addWidget(b)
        return b

    # --- open / close ----------------------------------------------------------------
    def open_bar(self):
        ed = self.editor
        bw = ed.current
        if bw is not None and bw.text is not None and bw.text.textCursor().hasSelection():
            sel = bw.text.textCursor().selectedText()
            if " " not in sel and len(sel) < 200:
                self.q.blockSignals(True)
                self.q.setText(sel)
                self.q.blockSignals(False)
        self.place()
        self.show()
        self.raise_()
        self.q.setFocus()
        self.q.selectAll()
        self.search(keep_place=False)

    def start(self, query: str, block_id: str | None = None, nth: int = 0):
        """Open with `query` and jump to its nth match in block `block_id` (sidebar search)."""
        self.q.blockSignals(True)
        self.q.setText(query)
        self.q.blockSignals(False)
        self.case.blockSignals(True)
        self.case.setChecked(False)
        self.case.blockSignals(False)
        self.place()
        self.show()
        self.raise_()
        self.search(keep_place=False)
        if block_id and self.matches:
            mine = [i for i, m in enumerate(self.matches) if getattr(m[0], "id", None) == block_id]
            if mine:
                self.index = mine[min(nth, len(mine) - 1)]
            self._paint(scroll=True)
        elif self.matches:
            self.index = 0
            self._paint(scroll=True)

    def close_bar(self, to_match: bool = True):
        if not self.isVisible():
            return
        cur = self.matches[self.index] if 0 <= self.index < len(self.matches) else None
        self.hide()
        self.refresh_timer.stop()
        self._clear()
        self.matches, self.index = [], -1
        if to_match and cur is not None and cur[0].parent() is not None:
            bw = cur[0]
            if bw.text is not None and isinstance(cur[1], int):
                bw.text.setFocus()
                c = bw.text.textCursor()
                c.setPosition(cur[1])
                c.setPosition(cur[1] + cur[2], QTextCursor.MoveMode.KeepAnchor)
                bw.text.setTextCursor(c)
            elif bw.body is not None:
                bw.body.setFocus()
        elif self.editor.current is not None:
            self.editor.focus_block(self.editor.current, "end")

    def place(self):
        vp = self.editor.scroll.viewport()
        top_right = vp.mapTo(self.editor, QPoint(vp.width(), 0))
        self.adjustSize()
        w = min(max(self.sizeHint().width(), 380), max(200, vp.width() - 16))
        self.resize(w, self.sizeHint().height())
        self.move(top_right.x() - w - 12, top_right.y() + 8)

    def eventFilter(self, obj, ev):
        if obj is self.q and ev.type() == ev.Type.KeyPress:
            k, mods = ev.key(), ev.modifiers()
            shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F3):
                self.step(-1 if shift else 1)
                return True
            if k == Qt.Key.Key_G and mods & Qt.KeyboardModifier.ControlModifier:
                self.step(-1 if shift else 1)
                return True
            if k == Qt.Key.Key_Escape:
                self.close_bar()
                return True
            if k == Qt.Key.Key_F and mods & Qt.KeyboardModifier.ControlModifier:
                self.q.selectAll()
                return True
        return False

    # --- searching ---------------------------------------------------------------------
    def page_changed(self):
        """Called when the page is edited, rebuilt (undo) or another page is opened."""
        if self.isVisible():
            self.refresh_timer.start()

    def search(self, keep_place: bool):
        old = self.matches[self.index] if keep_place and 0 <= self.index < len(self.matches) else None
        self._clear()
        needle = self.q.text()
        self.matches = []
        if needle:
            cs = self.case.isChecked()
            n = needle if cs else needle.lower()
            for bw in self.editor.all_blocks():
                if bw.text is not None:
                    hay = bw.plain() if cs else bw.plain().lower()
                    i = hay.find(n)
                    while i >= 0:
                        self.matches.append((bw, i, len(needle)))
                        i = hay.find(n, i + max(1, len(n)))
                elif bw.type_key == "table":
                    for r, row in enumerate(bw.props.get("rows") or []):
                        for c, cell in enumerate(row):
                            cell = str(cell)
                            if n in (cell if cs else cell.lower()):
                                self.matches.append((bw, ("cell", r, c)))
        self.index = -1
        if self.matches:
            self.index = 0
            if old is not None:  # stay at (or just after) where we were while the page is edited
                order = [b.id for b in self.editor.all_blocks()]  # ids survive undo / reloads
                rank = lambda m: (order.index(m[0].id) if m[0].id in order else -1,
                                  (m[1],) if isinstance(m[1], int) else m[1][1:])
                try:
                    want = rank(old)
                    self.index = next((i for i, m in enumerate(self.matches) if rank(m) >= want), 0)
                except (ValueError, TypeError):
                    self.index = 0
            elif self.editor.current is not None:  # start from where the cursor is
                order = self.editor.all_blocks()
                if self.editor.current in order:
                    here = order.index(self.editor.current)
                    self.index = next((i for i, m in enumerate(self.matches)
                                       if m[0] in order and order.index(m[0]) >= here), 0)
        self._paint(scroll=not keep_place)

    def step(self, delta: int):
        if not self.matches:
            return
        self.index = (self.index + delta) % len(self.matches)
        self._paint(scroll=True)

    # --- highlighting --------------------------------------------------------------------
    def _clear(self):
        for bw in self.editor.all_blocks():
            if bw.text is not None and bw.text.extraSelections():
                bw.text.setExtraSelections([])
        for body in self._tables:
            try:
                body.find_highlight(set(), None)
            except RuntimeError:  # deleted
                pass
        self._tables = []

    def _paint(self, scroll: bool):
        self._clear()
        n = len(self.matches)
        if not self.q.text():
            self.count.setText("")
        else:
            self.count.setText(f"{self.index + 1} of {n}" if n else "No matches")
        self.q.setStyleSheet("" if n or not self.q.text() else "QLineEdit{color:#d64545;}")
        per_text: dict = {}
        per_table: dict = {}
        for i, m in enumerate(self.matches):
            bw = m[0]
            if isinstance(m[1], int):
                per_text.setdefault(bw, []).append((m[1], m[2], i == self.index))
            else:
                cells, cur = per_table.setdefault(bw, (set(), [None]))
                cells.add(m[1][1:])
                if i == self.index:
                    cur[0] = m[1][1:]
        for bw, spans in per_text.items():
            sels = []
            for start, length, current in spans:
                s = QTextEdit.ExtraSelection()
                c = QTextCursor(bw.text.document())
                c.setPosition(start)
                c.setPosition(min(start + length, len(bw.plain())), QTextCursor.MoveMode.KeepAnchor)
                s.cursor = c
                f = QTextCharFormat()
                f.setBackground(QBrush(QColor(CURRENT_BG if current else MATCH_BG)))
                f.setForeground(QBrush(QColor(INK)))
                s.format = f
                sels.append(s)
            bw.text.setExtraSelections(sels)
        for bw, (cells, cur) in per_table.items():
            if bw.body is not None and hasattr(bw.body, "find_highlight"):
                bw.body.find_highlight(cells, cur[0])
                self._tables.append(bw.body)
        if scroll and 0 <= self.index < n:
            self._reveal(self.matches[self.index])

    def _reveal(self, m):
        bw = m[0]
        ed = self.editor
        opened = False
        for a in bw.ancestors():  # a match inside a closed toggle: open it
            if a.is_collapsed():
                a.toggle_collapsed()
                opened = True
        if opened:
            ed.restructure()
            QTimer.singleShot(0, lambda: self._scroll_to(m))  # after the layout catches up
        else:
            self._scroll_to(m)

    def _scroll_to(self, m):
        bw = m[0]
        if bw.parent() is None:
            return
        ed = self.editor
        canvas = ed.scroll.widget()
        if bw.text is not None and isinstance(m[1], int):
            c = QTextCursor(bw.text.document())
            c.setPosition(m[1])
            r = bw.text.cursorRect(c)
            pt = bw.text.viewport().mapTo(canvas, r.center())
        elif bw.body is not None and hasattr(bw.body, "cell_point"):
            pt = bw.body.cell_point(m[1][1], m[1][2], canvas)
        else:
            pt = bw.mapTo(canvas, QPoint(0, 0))
        bar_h = self.height() + 24
        ed.scroll.ensureVisible(pt.x(), pt.y(), 40, max(80, bar_h + 20))
