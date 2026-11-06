"""Drag blocks by their ⋮⋮ handle (or a selection by any selected block): reorder them, or drop
them inside another block. A block always moves together with everything nested inside it.

The drag is done by the editor itself (follow the mouse, draw a preview, drop on release) rather
than the system's drag-and-drop, so it behaves the same on X11, Wayland and in tests.

Where blocks land is shown by a blue line while dragging:
  * top part of a block          → above it
  * a toggle (most of its row)   → inside it, as the first item (line is indented)
  * bottom part of other blocks  → below it; move the pointer right (past the start of the
                                   text) and it goes inside that block instead (line is indented)
  * below the last block         → end of the page
Esc while dragging cancels. Dragging a block that is part of a selection moves the whole selection.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QPainter, QPixmap
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication, QFrame, QLabel, QToolButton

from .. import theme

DRAG_MIME = "application/x-securewrity-drag"  # kept for plugins that check for it
CHILD_INDENT = 26
NEST_SHIFT = 50  # px right of a block's text start that means "put it inside this block"
GHOST_MAX_H = 220


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
        ed = self.bw.editor
        if ed.is_dragging():
            ed.drag_move(e.globalPosition().toPoint())
            return
        if (self._press is not None and e.buttons() & Qt.MouseButton.LeftButton
                and (e.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance()):
            self._press = None
            self.setDown(False)
            ed.start_drag(self.bw, e.globalPosition().toPoint())
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        ed = self.bw.editor
        if ed.is_dragging():
            ed.finish_drag(e.globalPosition().toPoint())
            return
        was_click = self._press is not None
        self._press = None
        self.setDown(False)
        if was_click and e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            if e.modifiers() & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier):
                ed.toggle_selected(self.bw)
            else:
                ed.show_block_menu(self.bw)


class DragDropMixin:
    """Mixed into PageEditor. Call setup_drag_drop(canvas) once the canvas exists."""

    def setup_drag_drop(self, canvas):
        self._canvas = canvas
        self._drop_line = QFrame(canvas)
        self._drop_line.setFixedHeight(3)
        self._drop_line.hide()
        self._ghost = QLabel(canvas)
        self._ghost.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._ghost.hide()
        self._dragging: list = []
        self._drag_source = None
        self._last_global = QPoint()
        self._scroll_timer = QTimer(self, interval=40, timeout=self._drag_tick)

    def is_dragging(self) -> bool:
        return bool(self._dragging)

    # --- start / move / finish ----------------------------------------------------------
    def start_drag(self, bw, global_pos: QPoint):
        tops = self.selected_blocks() if self.is_in_selection(bw) else [bw]
        self.save_now()
        self.toolbar.hide()
        self.slash.close_menu()
        self._dragging = tops
        self._drag_source = bw
        self._ghost.setPixmap(self._ghost_pixmap(tops))
        self._ghost.adjustSize()
        self._ghost.show()
        self._ghost.raise_()
        QApplication.setOverrideCursor(Qt.CursorShape.ClosedHandCursor)
        self.grabKeyboard()  # Esc cancels
        self._scroll_timer.start()
        self.drag_move(global_pos)

    def drag_move(self, global_pos: QPoint):
        if not self._dragging:
            return
        self._last_global = global_pos
        pos = self._canvas.mapFromGlobal(global_pos)
        self._ghost.move(pos + QPoint(12, 8))
        self._show_drop_line(self.drop_target(pos))

    def _show_drop_line(self, target):
        if target is None:
            self._drop_line.hide()
            return
        _, _, lx, ly = target
        right = self.column.mapTo(self._canvas, QPoint(self.column.width(), 0)).x()
        self._drop_line.setStyleSheet(f"background:{theme.t('accent')}; border-radius:1px;")
        self._drop_line.setGeometry(lx + 20, ly - 1, max(40, right - lx - 20), 3)
        self._drop_line.show()
        self._drop_line.raise_()

    def finish_drag(self, global_pos: QPoint | None = None, cancel: bool = False):
        if not self._dragging:
            return
        blocks = self._dragging
        target = None if cancel else self.drop_target(self._canvas.mapFromGlobal(global_pos or self._last_global))
        self._end_drag()
        if target is not None:
            self.move_blocks(blocks, target[0], target[1])

    def cancel_drag(self):
        self.finish_drag(cancel=True)

    def _end_drag(self):
        self._dragging = []
        self._scroll_timer.stop()
        self._ghost.hide()
        self._drop_line.hide()
        self.releaseKeyboard()
        if QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()
        src, self._drag_source = self._drag_source, None
        if src is not None and src.parent() is not None:
            src.handle.hide()

    def _drag_tick(self):
        """Scroll when the pointer rests near the top or bottom edge, and follow the page."""
        if not self._dragging:
            return
        vp = self.scroll.viewport()
        y = vp.mapFromGlobal(QCursor.pos()).y()
        bar = self.scroll.verticalScrollBar()
        step = -18 if y < 40 else 18 if y > vp.height() - 40 else 0
        if step and bar.minimum() <= bar.value() + step <= bar.maximum():
            bar.setValue(bar.value() + step)
            self.drag_move(QCursor.pos())

    def _ghost_pixmap(self, tops) -> QPixmap:
        """A faded picture of the first block, sub-blocks included, plus an 'N blocks' badge."""
        src = tops[0].grab()
        h = min(src.height(), GHOST_MAX_H)
        w = min(src.width(), 560)
        out = QPixmap(w, h)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        bg = QColor(theme.t("bg"))
        bg.setAlpha(225)
        p.fillRect(0, 0, w, h, bg)  # the grab has no page background of its own
        p.setOpacity(0.85)
        p.drawPixmap(0, 0, src, 0, 0, w, h)
        p.setOpacity(1.0)
        pen = QColor(theme.t("accent"))
        p.setPen(pen)
        p.drawRoundedRect(0, 0, w - 1, h - 1, 4, 4)
        n = len(tops)
        def count(b):
            return sum(1 + count(c) for c in b.children)
        nested = sum(count(b) for b in tops)
        label = f"{n} blocks" if n > 1 else (f"+ {nested} inside" if nested else "")
        if label:
            fm = p.fontMetrics()
            r = fm.boundingRect(label).adjusted(-7, -3, 7, 3)
            r.moveTopRight(QPoint(w - 4, 3))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(pen)
            p.drawRoundedRect(r, 8, 8)
            p.setPen(QColor("white"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)
        p.end()
        return out

    # --- images dragged in from other apps (file manager, browser) -------------------------
    def image_drop_event(self, ev, widget) -> bool:
        """Drag-enter / move / leave / drop of outside images over `widget`. True if handled."""
        from .images import images_from_mime, might_have_images
        t = ev.type()
        if t == QEvent.Type.DragLeave:
            self._drop_line.hide()
            return False
        if not might_have_images(ev.mimeData()):
            return False
        g = widget.mapToGlobal(ev.position().toPoint())
        target = self.drop_target(self._canvas.mapFromGlobal(g))
        if t in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            ev.acceptProposedAction()
            self._show_drop_line(target)
            return True
        if t == QEvent.Type.Drop:
            self._drop_line.hide()
            ev.acceptProposedAction()
            parent, index = (target[0], target[1]) if target else (None, len(self.blocks))
            self.insert_images(images_from_mime(ev.mimeData()), parent, index)
            return True
        return False

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

    def move_blocks(self, blocks, parent, index):
        """Move blocks (in page order, each with everything nested in it) to `parent`
        (None = page) starting at `index`."""
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
