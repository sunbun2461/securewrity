"""Selecting whole blocks: drag the mouse across blocks (or down the page margin), Ctrl+A twice
(whole page), Esc (this block), Shift+click a ⋮⋮ handle. Drag any selected block to move them all.

While blocks are selected the editor itself has keyboard focus:
  Backspace / Delete  delete them        Ctrl+C / Ctrl+X  copy / cut them
  Ctrl+A              select every block  Esc / click      stop selecting
Copied blocks paste back as real blocks (with colors and toggles) inside Securewrity,
and as plain indented text anywhere else.
"""
from __future__ import annotations

import json

from PyQt6.QtCore import QMimeData, QPoint, Qt
from PyQt6.QtWidgets import QApplication

BLOCKS_MIME = "application/x-securewrity-blocks"


def _fresh(data: dict) -> dict:
    d = {k: v for k, v in data.items() if k != "id"}
    d["children"] = [_fresh(c) for c in data.get("children", [])]
    return d


def _plain(blocks, depth=0) -> list[str]:
    out = []
    for b in blocks:
        text = "".join(r.get("t", "") for r in b.get("content", []))
        if b["type"] == "divider":
            text = "---"
        out.append("    " * depth + text)
        out += _plain(b.get("children", []), depth + 1)
    return out


class SelectionMixin:
    """Mixed into PageEditor."""

    def selected_blocks(self) -> list:
        """Selected blocks in page order, without ones already inside another selected block."""
        sel = getattr(self, "_selected", set())
        return [b for b in self.all_blocks()
                if id(b) in sel and not any(id(a) in sel for a in b.ancestors())]

    def has_selection(self) -> bool:
        return bool(getattr(self, "_selected", None))

    def select_blocks(self, blocks):
        self.clear_selection(refocus=False)
        self._selected = {id(b) for b in blocks}
        for b in blocks:
            b.set_selected(True)
            if b.text and b.text.textCursor().hasSelection():
                c = b.text.textCursor()
                c.clearSelection()
                b.text.setTextCursor(c)
        if blocks:
            self.toolbar.hide()
            self.slash.close_menu()
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            n = len(self.selected_blocks())
            self.set_status("selection", f"{n} block{'s' if n != 1 else ''} selected: drag to move, "
                                         f"Backspace deletes, Esc or click elsewhere to stop")

    def is_in_selection(self, bw) -> bool:
        sel = getattr(self, "_selected", None)
        return bool(sel) and (id(bw) in sel or any(id(a) in sel for a in bw.ancestors()))

    def block_at(self, global_pos):
        """The visible block whose row is at (or nearest to) a screen point."""
        vis = self.visible_blocks()
        if not vis:
            return None
        y = self._canvas.mapFromGlobal(global_pos).y()
        for b in vis:
            top = b.row.mapTo(self._canvas, QPoint(0, 0)).y()
            if y < top + b.row.height():
                return b
        return vis[-1]

    def select_range(self, a, b):
        """Select every visible block from a to b (either order), as mouse-dragging does."""
        if a is None or b is None:
            return
        vis = self.visible_blocks()
        if a not in vis or b not in vis:
            return
        i, j = sorted((vis.index(a), vis.index(b)))
        blocks = vis[i:j + 1]
        if {id(x) for x in blocks} != getattr(self, "_selected", set()):
            self.select_blocks(blocks)

    def toggle_selected(self, bw):
        sel = set(getattr(self, "_selected", set()))
        sel.symmetric_difference_update({id(bw)})
        self.select_blocks([b for b in self.all_blocks() if id(b) in sel])

    def select_all_blocks(self):
        self.select_blocks(self.all_blocks())
        if self.blocks:
            self.scroll.ensureWidgetVisible(self.blocks[0].row, 0, 60)

    def clear_selection(self, refocus: bool = False):
        sel = getattr(self, "_selected", None)
        if not sel:
            return
        first = None
        for b in self.all_blocks():
            if id(b) in sel:
                first = first or b
                b.set_selected(False)
        self._selected = set()
        self.set_status("selection", "")
        if refocus and first is not None:
            self.focus_block(first, "end")

    def focusOutEvent(self, e):
        """Clicking anywhere else (title, sidebar, another app) ends the selection; menus don't."""
        super().focusOutEvent(e)
        if e.reason() not in (Qt.FocusReason.PopupFocusReason, Qt.FocusReason.ActiveWindowFocusReason) \
                and not getattr(self, "_dragging", None):
            self.clear_selection()

    def copy_selected(self):
        tops = self.selected_blocks()
        if not tops:
            return
        data = [b.to_data() for b in tops]
        mime = QMimeData()
        mime.setData(BLOCKS_MIME, json.dumps(data).encode())
        mime.setText("\n".join(_plain(data)))
        QApplication.clipboard().setMimeData(mime)
        self.ctx.window.notify(f"Copied {len(tops)} block{'s' if len(tops) != 1 else ''}")

    def delete_selected(self):
        tops = self.selected_blocks()
        if not tops:
            return
        before = self.prev_visible(tops[0])
        while before is not None and any(before is t or any(a is t for a in before.ancestors()) for t in tops):
            before = self.prev_visible(before)
        self.clear_selection()
        for b in tops:
            self.delete_block(b, focus=False)
        target = before if before is not None and before.parent() is not None else (self.blocks[0] if self.blocks else None)
        self.focus_block(target, "end")

    @staticmethod
    def blocks_from_mime(source) -> list[dict] | None:
        if source is None or not source.hasFormat(BLOCKS_MIME):
            return None
        try:
            return [_fresh(b) for b in json.loads(bytes(source.data(BLOCKS_MIME)).decode())]
        except (ValueError, TypeError):
            return None

    def selection_key(self, e) -> bool:
        """Keys while blocks are selected. Returns True if handled."""
        K = Qt.Key
        key, ctrl = e.key(), bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if key in (K.Key_Backspace, K.Key_Delete):
            self.delete_selected()
        elif ctrl and key == K.Key_C:
            self.copy_selected()
        elif ctrl and key == K.Key_X:
            self.copy_selected()
            self.delete_selected()
        elif ctrl and key == K.Key_A:
            self.select_all_blocks()
        elif key == K.Key_Escape:
            self.clear_selection(refocus=True)
        elif key in (K.Key_Up, K.Key_Down, K.Key_Return, K.Key_Enter):
            tops = self.selected_blocks()
            target = tops[0] if key == K.Key_Up else tops[-1] if tops else None
            self.clear_selection()
            self.focus_block(target, "start" if key == K.Key_Up else "end")
        else:
            return False
        return True
