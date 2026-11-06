"""Page-wide undo / redo for the editor.

Every state is a snapshot of the whole page's block tree (JSON), plus where the cursor was.
A snapshot is taken:
  * after typing pauses (the editor's autosave, ~0.6 s), so typing undoes in chunks;
  * just before a structural change (a block added, removed, moved, recolored…),
    so e.g. "type a sentence, press Enter" is two steps, not one.
Undo restores the previous snapshot by rebuilding the blocks. Sub-pages that a deleted
"page" block sent to the Trash come back when that block comes back.
"""
from __future__ import annotations

import json

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

LIMIT = 300


def _key(tree) -> str:
    """Comparison key: opening/closing a toggle alone is not an undo step."""
    def strip(blocks):
        return [{**b, "props": {k: v for k, v in b["props"].items() if k != "collapsed"},
                 "children": strip(b["children"])} for b in blocks]
    return json.dumps(strip(tree), sort_keys=True)


def arrow_icon(color: str, redo: bool, size: int = 18) -> QIcon:
    """A curved undo / redo arrow drawn in code, so it looks the same with any font or icon theme."""
    icon = QIcon()
    for scale in (1, 2):
        px = QPixmap(size * scale, size * scale)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(scale, scale)
        if redo:  # mirror
            p.translate(size, 0)
            p.scale(-1, 1)
        pen = QPen(QColor(color), 1.8, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        path = QPainterPath(QPointF(4.5, 7.5))
        path.lineTo(11, 7.5)
        path.arcTo(QRectF(7.5, 7.5, 7, 7), 90, -180)
        path.lineTo(7, 14.5)
        p.drawPath(path)
        head = QPainterPath(QPointF(7.5, 4))
        head.lineTo(4, 7.5)
        head.lineTo(7.5, 11)
        p.drawPath(head)
        p.end()
        px.setDevicePixelRatio(scale)
        icon.addPixmap(px)
    return icon


class HistoryMixin:
    """Mixed into PageEditor. Needs: tree_data(), current, focus_block(), _rebuild()."""

    def history_reset(self):
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._pre_open = False
        if self.page_id:
            self._undo.append(self._snapshot())
        self.update_history_buttons()

    def _snapshot(self) -> dict:
        tree = self.tree_data()
        cur = self.current
        return {"tree": tree, "key": _key(tree),
                "focus": (cur.id, cur.cursor_pos()) if cur is not None and cur.parent() is not None else None}

    def checkpoint(self) -> bool:
        """Record the page as it is now, if it changed since the last snapshot."""
        if getattr(self, "_loading", False) or not self.page_id or not hasattr(self, "_undo"):
            return False
        snap = self._snapshot()
        if self._undo and self._undo[-1]["key"] == snap["key"]:
            self._undo[-1]["focus"] = snap["focus"] or self._undo[-1]["focus"]
            return False
        self._undo.append(snap)
        del self._undo[:-LIMIT]
        self._redo.clear()
        self.update_history_buttons()
        return True

    def before_structure_change(self):
        """Called by every structural edit: snapshot once per event, before the first change."""
        if getattr(self, "_loading", False) or getattr(self, "_pre_open", False):
            return
        self.checkpoint()
        self._pre_open = True
        QTimer.singleShot(0, self._close_pre)

    def _close_pre(self):
        self._pre_open = False
        self.checkpoint()  # and the result, so typing that follows is a separate step

    def can_undo(self) -> bool:
        return len(getattr(self, "_undo", [])) > 1 or self.save_timer.isActive()

    def can_redo(self) -> bool:
        return bool(getattr(self, "_redo", None))

    def undo(self):
        self.checkpoint()
        if len(self._undo) < 2:
            self.ctx.window.notify("Nothing to undo")
            return
        leaving = self._undo.pop()
        self._redo.append(leaving)
        self._restore(self._undo[-1], leaving["focus"] or self._undo[-1]["focus"])

    def redo(self):
        self.checkpoint()
        if not self._redo:
            self.ctx.window.notify("Nothing to redo")
            return
        snap = self._redo.pop()
        self._undo.append(snap)
        self._restore(snap, snap["focus"])

    def _restore(self, snap: dict, focus):
        self.save_timer.stop()
        self._rebuild(snap["tree"])
        # bring back sub-pages whose page block is back on the page
        restored = False
        for b in self.all_blocks():
            pid = b.props.get("page_id") if b.type_key == "page" else None
            page = self.repo.get_page(pid) if pid else None
            if page and page["trashed"]:
                self.repo.restore_page(pid)
                restored = True
        tree = self.tree_data()
        self.repo.save_blocks(self.page_id, tree)
        self._saved_key = (self.page_id, json.dumps(tree, sort_keys=True))
        self.flash_saved()
        if restored:
            self.ctx.events.emit("pages_changed")
        self.ctx.events.emit("page_saved", self.page_id)
        self._undo[-1]["focus"] = focus
        target = None
        if focus:
            target = next((b for b in self.all_blocks() if b.id == focus[0]), None)
        if target is not None:
            for a in target.ancestors():
                if a.is_collapsed():
                    a.toggle_collapsed()
            self.focus_block(target, focus[1])
        elif self.blocks:
            self.focus_block(self.blocks[0], "start")
        self.update_history_buttons()

    def update_history_buttons(self):
        if hasattr(self, "undo_btn"):
            self.undo_btn.setEnabled(self.can_undo())
            self.redo_btn.setEnabled(self.can_redo())
