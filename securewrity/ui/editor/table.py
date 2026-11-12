"""Table block, Notion style: a grid of cells you click into and type.

Data (block props): rows = [[cell text, ...], ...], header_row / header_col = bool,
widths = [column width px or None, ...].

  click a cell → type          Tab / Shift+Tab → next / previous cell (Tab on the last cell adds a row)
  + under / right of the table → add a row / column      drag a column's right border → resize
  right-click → insert / delete rows and columns, header row / column, copy as Markdown
  Delete → clear the selected cells    Ctrl+C / Ctrl+V → copy / paste cells (works with spreadsheets)
  Esc → select the whole table block   ↑ on the top row / ↓ on the bottom row → leave the table
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics
from PyQt6.QtWidgets import (QAbstractItemDelegate, QAbstractItemView, QApplication, QGridLayout,
                             QMenu, QSizePolicy, QTableWidget, QTableWidgetItem, QToolButton)

from .. import theme
from .block_widget import NonTextBody

MIN_COL, MAX_AUTO_COL, DEFAULT_COL = 60, 320, 140
GRIP = 4  # px either side of a column border that starts a resize
K = Qt.Key


def _rows(props) -> list[list[str]]:
    rows = props.get("rows")
    if not isinstance(rows, list) or not rows:
        return [["", ""], ["", ""]]
    rows = [[str(c) for c in r] if isinstance(r, list) else [str(r)] for r in rows]
    cols = max(1, max(len(r) for r in rows))
    return [r + [""] * (cols - len(r)) for r in rows]


def to_markdown(props) -> str:
    rows = _rows(props)
    esc = [[c.replace("|", "\\|").replace("\n", "<br>") for c in r] for r in rows]
    out = ["| " + " | ".join(esc[0]) + " |", "|" + "|".join(" --- " for _ in esc[0]) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in esc[1:]]
    return "\n".join(out)


class _Table(QTableWidget):
    def __init__(self, body: "TableBody"):
        super().__init__()
        self.body = body
        self.horizontalHeader().hide()
        self.verticalHeader().hide()
        self.setWordWrap(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ContiguousSelection)
        self.setTabKeyNavigation(True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.viewport().installEventFilter(self)
        self.viewport().setMouseTracking(True)
        self._resizing = None  # (column, press x, width at press)

    # --- scrolling: the page scrolls, not the table (except sideways when it's too wide)
    def wheelEvent(self, e):
        d = e.angleDelta()
        if abs(d.y()) >= abs(d.x()):
            e.ignore()
            return
        super().wheelEvent(e)

    # --- column resizing by dragging a border -------------------------------------------
    def _border_at(self, x: int):
        for c in range(self.columnCount()):
            edge = self.columnViewportPosition(c) + self.columnWidth(c)
            if abs(x - edge) <= GRIP:
                return c
        return None

    def eventFilter(self, obj, ev):
        if obj is self.viewport():
            t = ev.type()
            if t == QEvent.Type.MouseMove:
                x = int(ev.position().x())
                if self._resizing is not None:
                    c, x0, w0 = self._resizing
                    self.setColumnWidth(c, max(MIN_COL, w0 + x - x0))
                    self.body.update_size()
                    return True
                if not ev.buttons():
                    if self._border_at(x) is not None:
                        self.viewport().setCursor(Qt.CursorShape.SplitHCursor)
                    else:
                        self.viewport().unsetCursor()
            elif t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                c = self._border_at(int(ev.position().x()))
                if c is not None:
                    self._resizing = (c, int(ev.position().x()), self.columnWidth(c))
                    return True
            elif t == QEvent.Type.MouseButtonRelease and self._resizing is not None:
                self._resizing = None
                self.body.save_widths()
                return True
        return super().eventFilter(obj, ev)

    # --- keys -----------------------------------------------------------------------------
    def closeEditor(self, editor, hint):
        last = (self.currentRow() == self.rowCount() - 1 and self.currentColumn() == self.columnCount() - 1)
        if hint == QAbstractItemDelegate.EndEditHint.EditNextItem and last:
            super().closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
            self.body.insert_row(self.rowCount())
            self.setCurrentCell(self.rowCount() - 1, 0)
            self.edit(self.currentIndex())
            return
        super().closeEditor(editor, hint)

    def keyPressEvent(self, e):
        ed = self.body.bw.editor
        bw = self.body.bw
        if ed.history_key(e):
            return
        key, mods = e.key(), e.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        if key == K.Key_Escape:
            ed.select_blocks([bw])
        elif key in (K.Key_Delete, K.Key_Backspace):
            self.body.clear_cells()
        elif ctrl and key == K.Key_C:
            self.body.copy_cells()
        elif ctrl and key == K.Key_V:
            self.body.paste_cells()
        elif key == K.Key_Tab and self.currentRow() == self.rowCount() - 1 \
                and self.currentColumn() == self.columnCount() - 1:
            self.body.insert_row(self.rowCount())
            self.setCurrentCell(self.rowCount() - 1, 0)
        elif key == K.Key_Up and self.currentRow() <= 0 and not ctrl:
            prev = ed.prev_visible(bw)
            ed.focus_block(prev, "end") if prev else ed.title.setFocus()
        elif key == K.Key_Down and self.currentRow() >= self.rowCount() - 1 and not ctrl:
            nxt = ed.next_visible(bw, skip_children=True)
            if nxt is None:
                nxt = ed.insert_after(bw, {"type": "paragraph"})
            ed.focus_block(nxt, "start")
        elif key in (K.Key_Return, K.Key_Enter) and self.state() != QAbstractItemView.State.EditingState:
            self.edit(self.currentIndex())
        else:
            super().keyPressEvent(e)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        ed = self.body.bw.editor
        ed.current = self.body.bw
        if not (e.reason() == Qt.FocusReason.MouseFocusReason and ed.is_in_selection(self.body.bw)):
            ed.clear_selection()
        if self.currentRow() < 0 and self.rowCount():
            self.setCurrentCell(0, 0)

    def contextMenuEvent(self, e):
        idx = self.indexAt(e.pos())
        if idx.isValid():
            self.setCurrentCell(idx.row(), idx.column())
        m = QMenu(self)
        self.body.add_menu_actions(m)
        m.addSeparator()
        self.body.bw.editor.build_block_menu(self.body.bw, m.addMenu("Block"))
        m.exec(e.globalPos())


class _Plus(QToolButton):
    def __init__(self, tip, cb):
        super().__init__()
        self.setText("+")
        self.setToolTip(tip)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(cb)
        sp = self.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        self.setSizePolicy(sp)
        self.hide()


class TableBody(NonTextBody):
    def __init__(self, bw):
        super().__init__(bw)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 6, 0, 2)
        grid.setSpacing(2)
        self.table = _Table(self)
        self.setFocusProxy(self.table)
        self.add_col_btn = _Plus("Add a column", lambda: self.insert_col(self.table.columnCount()))
        self.add_row_btn = _Plus("Add a row", lambda: self.insert_row(self.table.rowCount()))
        self.add_col_btn.setFixedWidth(18)
        self.add_row_btn.setFixedHeight(16)
        grid.addWidget(self.table, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self.add_col_btn, 0, 1)
        grid.addWidget(self.add_row_btn, 1, 0)
        grid.setColumnStretch(2, 1)
        self._building = False
        self.table.itemChanged.connect(self._cell_edited)
        self.refresh(force=True)

    def _style(self, focused: bool):
        self.setStyleSheet("QFrame#NonText{background:transparent;}")

    def enterEvent(self, e):
        self.add_col_btn.show()
        self.add_row_btn.show()

    def leaveEvent(self, e):
        self.add_col_btn.hide()
        self.add_row_btn.hide()

    # --- props ↔ grid ----------------------------------------------------------------------
    def rows(self) -> list[list[str]]:
        return _rows(self.bw.props)

    def grid_rows(self) -> list[list[str]]:
        t = self.table
        return [[(t.item(r, c).text() if t.item(r, c) else "") for c in range(t.columnCount())]
                for r in range(t.rowCount())]

    def refresh(self, force: bool = False):
        rows = self.rows()
        t = self.table
        g = QColor(theme.t("muted"))
        g.setAlpha(90)
        grid = g.name(QColor.NameFormat.HexArgb)
        text = theme.t("text")
        t.setStyleSheet(
            f"QTableWidget{{background:transparent; gridline-color:{grid}; border:1px solid {grid};"
            f" color:{text}; selection-background-color:rgba(35,131,226,0.22); selection-color:{text};}}"
            f" QTableWidget::item{{padding:5px 7px;}}"
            f" QTableWidget QLineEdit, QTableWidget QLineEdit:focus, QTableWidget QLineEdit:hover"
            f"{{background:{theme.t('bg')}; color:{text}; border:none; border-radius:0; padding:0 4px; margin:0;}}")
        if not force and rows == self.grid_rows():
            self._paint_headers()
            self.update_size()
            return
        self._building = True
        cur = (t.currentRow(), t.currentColumn())
        t.setRowCount(len(rows))
        t.setColumnCount(len(rows[0]))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                it = t.item(r, c)
                if it is None:
                    t.setItem(r, c, QTableWidgetItem(val))
                elif it.text() != val:
                    it.setText(val)
        widths = self.bw.props.get("widths") or []
        bold = QFont(t.font())
        bold.setBold(True)
        fm = QFontMetrics(bold)  # measure as bold: header cells are, and it's never too narrow
        for c in range(t.columnCount()):
            w = widths[c] if c < len(widths) and widths[c] else None
            if not w:  # fit the longest line in the column, within limits
                longest = max((fm.horizontalAdvance(line) for row in rows for line in row[c].split("\n")), default=0)
                w = max(DEFAULT_COL if not any(row[c] for row in rows) else MIN_COL,
                        min(MAX_AUTO_COL, longest + 34))
            t.setColumnWidth(c, int(w))
        self._paint_headers()
        if 0 <= cur[0] < t.rowCount() and 0 <= cur[1] < t.columnCount():
            t.setCurrentCell(*cur)
        self._building = False
        self.update_size()

    def _paint_headers(self):
        t = self.table
        hr, hc = bool(self.bw.props.get("header_row")), bool(self.bw.props.get("header_col"))
        shade = QColor(theme.t("hover"))
        self._building = True
        for r in range(t.rowCount()):
            for c in range(t.columnCount()):
                it = t.item(r, c)
                if it is None:
                    continue
                head = (hr and r == 0) or (hc and c == 0)
                f = QFont(t.font())
                f.setBold(head)
                it.setFont(f)
                it.setBackground(shade if head else QColor(0, 0, 0, 0))
                found, cur = getattr(self, "_find", (set(), None))
                if (r, c) in found:
                    from .find import CURRENT_BG, INK, MATCH_BG
                    it.setBackground(QColor(CURRENT_BG if (r, c) == cur else MATCH_BG))
                    it.setForeground(QColor(INK))
                else:
                    it.setData(Qt.ItemDataRole.ForegroundRole, None)
                it.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._building = False

    def update_size(self):
        t = self.table
        t.resizeRowsToContents()
        total_w = sum(t.columnWidth(c) for c in range(t.columnCount())) + 2
        avail = max(120, self.width() - 24) if self.width() > 60 else total_w
        w = min(total_w, avail)
        h = sum(t.rowHeight(r) for r in range(t.rowCount())) + 2
        if total_w > avail:
            h += t.horizontalScrollBar().sizeHint().height()
        t.setFixedSize(w, h)
        self.add_col_btn.setFixedHeight(h)
        self.add_row_btn.setFixedWidth(w)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.update_size()

    def _save(self, rows=None, **extra):
        props_rows = rows if rows is not None else self.grid_rows()
        bw = self.bw
        bw.editor.before_structure_change()
        bw.props["rows"] = props_rows
        for k, v in extra.items():
            if v is None:
                bw.props.pop(k, None)
            else:
                bw.props[k] = v
        self.refresh()
        bw.editor.changed()

    # --- Ctrl+F ----------------------------------------------------------------------------
    def find_highlight(self, cells: set, current):
        """Color matching cells (current one orange); an empty set clears."""
        self._find = (set(cells), current)
        self._paint_headers()

    def cell_point(self, r: int, c: int, to):
        t = self.table
        rect = t.visualRect(t.model().index(r, c))
        return t.viewport().mapTo(to, rect.center())

    def _cell_edited(self, item):
        if not self._building:
            self._save()
            self.update_size()

    def save_widths(self):
        t = self.table
        self._save(widths=[t.columnWidth(c) for c in range(t.columnCount())])

    def _widths(self):
        w = list(self.bw.props.get("widths") or [])
        return w + [None] * (self.table.columnCount() - len(w))

    # --- structure -------------------------------------------------------------------------
    def insert_row(self, at: int):
        rows = self.grid_rows()
        rows.insert(at, [""] * self.table.columnCount())
        self._save(rows)

    def insert_col(self, at: int):
        rows = [r[:at] + [""] + r[at:] for r in self.grid_rows()]
        w = self._widths()
        w.insert(at, None)
        self._save(rows, widths=w if any(w) else None)

    def delete_row(self, r: int):
        rows = self.grid_rows()
        if len(rows) > 1:
            del rows[r]
            self._save(rows)

    def delete_col(self, c: int):
        rows = self.grid_rows()
        if len(rows[0]) > 1:
            rows = [x[:c] + x[c + 1:] for x in rows]
            w = self._widths()
            del w[c]
            self._save(rows, widths=w if any(w) else None)

    def toggle(self, key: str):
        self._save(**{key: None if self.bw.props.get(key) else True})

    # --- cells -----------------------------------------------------------------------------
    def _selected_box(self):
        rs = self.table.selectedRanges()
        if not rs:
            r, c = max(0, self.table.currentRow()), max(0, self.table.currentColumn())
            return r, c, r, c
        x = rs[0]
        return x.topRow(), x.leftColumn(), x.bottomRow(), x.rightColumn()

    def clear_cells(self):
        r0, c0, r1, c1 = self._selected_box()
        rows = self.grid_rows()
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                rows[r][c] = ""
        self._save(rows)

    def copy_cells(self):
        r0, c0, r1, c1 = self._selected_box()
        rows = self.grid_rows()
        QApplication.clipboard().setText("\n".join("\t".join(rows[r][c0:c1 + 1]) for r in range(r0, r1 + 1)))

    def paste_cells(self):
        text = QApplication.clipboard().text().replace("\r", "").rstrip("\n")
        if not text:
            return
        data = [line.split("\t") for line in text.split("\n")]
        r0, c0, _, _ = self._selected_box()
        rows = self.grid_rows()
        cols = max(len(rows[0]), c0 + max(len(d) for d in data))
        rows = [r + [""] * (cols - len(r)) for r in rows]
        while len(rows) < r0 + len(data):
            rows.append([""] * cols)
        for i, d in enumerate(data):
            for j, val in enumerate(d):
                rows[r0 + i][c0 + j] = val
        self._save(rows)

    # --- menus -----------------------------------------------------------------------------
    def add_menu_actions(self, m: QMenu):
        t = self.table
        r, c = max(0, t.currentRow()), max(0, t.currentColumn())
        m.addAction("Insert row above", lambda: self.insert_row(r))
        m.addAction("Insert row below", lambda: self.insert_row(r + 1))
        m.addAction("Insert column left", lambda: self.insert_col(c))
        m.addAction("Insert column right", lambda: self.insert_col(c + 1))
        m.addSeparator()
        a = m.addAction("Delete row", lambda: self.delete_row(r))
        a.setEnabled(t.rowCount() > 1)
        a = m.addAction("Delete column", lambda: self.delete_col(c))
        a.setEnabled(t.columnCount() > 1)
        m.addSeparator()
        for label, key in (("Header row", "header_row"), ("Header column", "header_col")):
            a = m.addAction(label, lambda k=key: self.toggle(k))
            a.setCheckable(True)
            a.setChecked(bool(self.bw.props.get(key)))
        a = m.addAction("Reset column widths", lambda: self._save(widths=None))
        a.setEnabled(bool(self.bw.props.get("widths")))
        m.addAction("Copy as Markdown", lambda: (QApplication.clipboard().setText(to_markdown(self.bw.props)),
                                                 self.bw.editor.ctx.window.notify("Table copied as Markdown")))
