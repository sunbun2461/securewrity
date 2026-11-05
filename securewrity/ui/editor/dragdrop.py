"""Drag blocks by their ⋮⋮ handle (or a selection by any selected block): reorder them, or drop them inside another block.

Where a block lands is shown by a blue line while dragging:
  * top part of a block          → above it
  * a toggle (most of its row)   → inside it, as the first item (line is indented)
  * bottom part of other blocks  → below it; move the pointer right (past the start of the
                                   text) and it goes inside that block instead (line is indented)
  * below the last block         → end of the page
Dragging a block that is part of a selection moves the whole selection.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QMimeData, QPoint, Qt
from PyQt6.QtGui import QColor, QDrag, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QFrame, QToolButton

from .. import theme

DRAG_MIME = "application/x-securewrity-drag"
CHILD_INDENT = 26
NEST_SHIFT = 50  # px right of a block's text start that means "put it inside this block"


class DragHandle(QToolButton):
    """The ⋮⋮ handle: click → block menu (Shift+click → select), drag → move the block."""

    def __init__(self, bw):
        super().__init__()
        self.bw = bw
        self._press: QPoint | None = None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (self._press is not None and e.buttons() & Qt.MouseButton.LeftButton
                and (e.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance()):
            self._press = None
            self.setDown(False)
            self.bw.editor.start_drag(self.bw)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        was_click = self._press is not None
        self._press = None
        self.setDown(False)
        if was_click and e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            ed = self.bw.editor
            if e.modifiers() & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier):
                ed.toggle_selected(self.bw)
            else:
                ed.show_block_menu(self.bw)


class DragDropMixin:
    """Mixed into PageEditor. Call setup_drag_drop(canvas) once the canvas exists."""

    def setup_drag_drop(self, canvas):
        self._canvas = canvas
        canvas.setAcceptDrops(True)
        canvas.installEventFilter(self)
        self._drop_line = QFrame(canvas)
        self._drop_line.setFixedHeight(3)
        self._drop_line.hide()
        self._dragging: list = []
        self._drop_at = None

    def start_drag(self, bw):
        tops = self.selected_blocks() if self.is_in_selection(bw) else [bw]
        self.save_now()
        self._dragging = tops
        mime = QMimeData()
        mime.setData(DRAG_MIME, b"1")
        drag = QDrag(self)
        drag.setMimeData(mime)
        pix = bw.row.grab()
        faded = QPixmap(pix.size())
        faded.fill(Qt.GlobalColor.transparent)
        p = QPainter(faded)
        p.setOpacity(0.6)
        p.drawPixmap(0, 0, pix)
        if len(tops) > 1:  # badge: how many blocks are coming along
            p.setOpacity(1.0)
            label = f"{len(tops)} blocks"
            fm = p.fontMetrics()
            r = fm.boundingRect(label).adjusted(-7, -3, 7, 3)
            r.moveTopRight(QPoint(pix.width() - 4, 2))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.t("accent")))
            p.drawRoundedRect(r, 8, 8)
            p.setPen(QColor("white"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)
        p.end()
        drag.setPixmap(faded)
        drag.setHotSpot(QPoint(10, min(12, pix.height() // 2)))
        drag.exec(Qt.DropAction.MoveAction)
        self._dragging = []
        self._drop_line.hide()

    # --- target finding ----------------------------------------------------------------
    def _row_rect(self, b):
        top = b.row.mapTo(self._canvas, QPoint(0, 0))
        return top.x(), top.y(), b.row.width(), b.row.height()

    def _is_dragged(self, b) -> bool:
        return any(b is d or any(a is d for a in b.ancestors()) for d in self._dragging)

    def drop_target(self, pos: QPoint):
        """(parent, index, line_x, line_y) for a point in canvas coordinates, or None."""
        vis = self.visible_blocks()
        if not vis:
            return None
        y = pos.y()
        hit = None
        for b in vis:
            x0, top, w, h = self._row_rect(b)
            if y < top + h:
                hit = b
                break
        if hit is None:  # below everything: end of the page
            last = self.blocks[-1]
            x0 = self._row_rect(last)[0]
            return None, len(self.blocks), x0, last.mapTo(self._canvas, QPoint(0, last.height())).y()
        x0, top, w, h = self._row_rect(hit)
        if self._is_dragged(hit):
            return None
        frac = max(0.0, (y - top) / max(h, 1))
        sibs = self.siblings(hit)
        idx = sibs.index(hit)
        if y < top or frac < (0.3 if hit.btype.toggle else 0.5):
            return hit.parent_block, idx, x0, top
        if hit.btype.toggle and not (hit.is_collapsed() and frac > 0.75):
            return hit, 0, x0 + CHILD_INDENT, top + h
        if hit.btype.can_have_children and not hit.is_collapsed():
            # under its own indented items, or pointer moved right past the text start: nest inside it
            text_x = (hit.text.mapTo(self._canvas, QPoint(0, 0)).x() if hit.text else x0 + 22)
            if hit.children or pos.x() > text_x + NEST_SHIFT:
                return hit, 0, x0 + CHILD_INDENT, top + h
        return hit.parent_block, idx + 1, x0, top + h

    # --- events ----------------------------------------------------------------------------
    def drag_event(self, ev) -> bool:
        t = ev.type()
        if t == QEvent.Type.DragLeave:
            self._drop_line.hide()
            return True
        if not ev.mimeData().hasFormat(DRAG_MIME) or not self._dragging:
            return False
        if t == QEvent.Type.DragEnter:
            ev.acceptProposedAction()
            return True
        pos = ev.position().toPoint()
        if t == QEvent.Type.DragMove:
            self._autoscroll(pos)
            target = self.drop_target(pos)
            self._drop_at = target
            if target is None:
                self._drop_line.hide()
                ev.ignore()
                return True
            _, _, lx, ly = target
            right = self.column.mapTo(self._canvas, QPoint(self.column.width(), 0)).x()
            self._drop_line.setStyleSheet(f"background:{theme.t('accent')}; border-radius:1px;")
            self._drop_line.setGeometry(lx + 20, ly - 1, max(40, right - lx - 20), 3)
            self._drop_line.show()
            self._drop_line.raise_()
            ev.acceptProposedAction()
            return True
        if t == QEvent.Type.Drop:
            self._drop_line.hide()
            target = self.drop_target(pos)
            if target is not None:
                ev.acceptProposedAction()
                self.move_blocks(self._dragging, target[0], target[1])
            return True
        return False

    def _autoscroll(self, pos: QPoint):
        vp = self.scroll.viewport()
        y = self._canvas.mapTo(vp, pos).y()
        bar = self.scroll.verticalScrollBar()
        if y < 40:
            bar.setValue(bar.value() - 24)
        elif y > vp.height() - 40:
            bar.setValue(bar.value() + 24)

    def move_blocks(self, blocks, parent, index):
        """Move blocks (in page order) to `parent` (None = page) starting at `index`."""
        if parent is not None and (any(parent is b or any(a is b for a in parent.ancestors()) for b in blocks)
                                   or not parent.btype.can_have_children):
            return
        focus = self.current if self.current in blocks else None
        for b in blocks:
            lst = self._list(parent)
            if b in lst and lst.index(b) < index:
                index -= 1
            self.move_widget(b, parent, index)
            index += 1
        self.clear_selection()
        self.save_now()
        if focus is not None:
            self.focus_block(focus, "end")
