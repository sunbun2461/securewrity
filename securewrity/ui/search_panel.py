"""The sidebar search bar: searches every page (titles and text, tables included).

Type in the bar and the page tree is replaced by results: each page with matches, and under
it every matching line with the match highlighted. Click a line (or Enter) to open the page
at that spot, with the words highlighted (the Ctrl+F bar opens with the same search, so Enter
there goes to the next match on that page). Esc or clearing the bar brings the page tree back.
Ctrl+Shift+F jumps to the bar from anywhere.
"""
from __future__ import annotations

from PyQt6.QtCore import QRect, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFontMetrics, QPainter
from PyQt6.QtWidgets import (QLabel, QLineEdit, QStyle, QStyledItemDelegate, QTreeWidget,
                             QTreeWidgetItem)

from . import theme

HIT = Qt.ItemDataRole.UserRole          # {"page_id", "block_id", "nth"}
SPAN = Qt.ItemDataRole.UserRole + 1     # (start, length) of the match inside the item's text


class SearchField(QLineEdit):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.setPlaceholderText("🔍  Search all notes   Ctrl+Shift+F")
        self.setClearButtonEnabled(True)
        self.setObjectName("SidebarSearch")

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.clear()
            self.panel.window.editor.setFocus()
            return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.panel.timer.stop()
            self.panel.run()
            self.panel.open_first()
            return
        if k == Qt.Key.Key_Down and self.panel.results.isVisible():
            self.panel.results.setFocus()
            self.panel.results.setCurrentItem(self.panel.results.topLevelItem(0))
            return
        super().keyPressEvent(e)


class _HitDelegate(QStyledItemDelegate):
    """Draws a result line with the matching words highlighted."""

    def paint(self, p: QPainter, opt, index):
        span = index.data(SPAN)
        if span is None:
            return super().paint(p, opt, index)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        opt.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, p, opt.widget)
        r = opt.rect.adjusted(4, 0, -4, 0)
        top = not index.parent().isValid()  # a page title: bold, normal ink
        if top:
            opt.font.setBold(True)
        ink = QColor(theme.t("text" if top else "muted"))
        p.save()
        p.setFont(opt.font)
        fm = QFontMetrics(opt.font)
        s, n = span
        head, mid, tail = text[:s], text[s:s + n], text[s + n:]
        x = r.x()
        y = r.y() + (r.height() + fm.ascent() - fm.descent()) // 2
        p.setClipRect(r)
        p.setPen(ink)
        p.drawText(x, y, head)
        x += fm.horizontalAdvance(head)
        w = fm.horizontalAdvance(mid)
        p.fillRect(QRect(x - 1, r.y() + 3, w + 2, r.height() - 6), QColor("#FFE36E"))
        p.setPen(QColor("#1d1d1d"))
        p.drawText(x, y, mid)
        x += w
        p.setPen(ink)
        p.drawText(x, y, tail)
        p.restore()

    def sizeHint(self, opt, index):
        s = super().sizeHint(opt, index)
        return QSize(s.width(), max(s.height(), 24))


class SearchPanel:
    """Wires the field, the results tree and the sidebar's normal widgets together."""

    def __init__(self, sidebar, normal_widgets):
        self.sidebar = sidebar
        self.window = sidebar.window
        self.normal = normal_widgets  # hidden while results show
        self.field = SearchField(self)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setContentsMargins(8, 2, 0, 2)
        self.status.hide()
        self.results = QTreeWidget()
        self.results.setObjectName("Sidebar")
        self.results.setHeaderHidden(True)
        self.results.setIndentation(14)
        self.results.setUniformRowHeights(False)
        self.results.setItemDelegate(_HitDelegate(self.results))
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.itemClicked.connect(self.open_item)
        self.results.itemActivated.connect(self.open_item)
        self.results.hide()
        self.timer = QTimer(self.results, singleShot=True, interval=220, timeout=self.run)
        self.field.textChanged.connect(self._changed)
        self._last = None

    def _changed(self, text):
        if text.strip():
            self.timer.start()
        else:
            self.timer.stop()
            self.show_results(False)

    def show_results(self, on: bool):
        for w in self.normal:
            w.setVisible(not on)
        if not on:
            self.sidebar.refresh()  # puts favorites back only if there are any
        self.results.setVisible(on)
        self.status.setVisible(on)
        if not on:
            self.results.clear()
            self._last = None

    def refresh(self):
        """Pages changed (saved, renamed…): redo the search if results are showing."""
        if self.results.isVisible():
            self._last = None
            self.timer.start()

    def run(self):
        q = self.field.text().strip()
        if not q:
            return self.show_results(False)
        if q == self._last:
            return
        self._last = q
        self.window.editor.save_now()  # so what you just typed is searchable
        res = self.window.ctx.repo.search_hits(q)
        self.results.setUpdatesEnabled(False)
        self.results.clear()
        total = 0
        for e in res:
            p = e["page"]
            n = e["total"]
            total += n
            title = f"{p['icon'] or '📄'}  {p['title'] or 'Untitled'}"
            top = QTreeWidgetItem([title + (f"   · {n}" if n else "")])
            top.setData(0, HIT, {"page_id": p["id"]})
            tip = (e["path"] + " / " if e.get("path") else "") + (p["title"] or "Untitled")
            top.setToolTip(0, tip)
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            if e["title_hit"]:
                i = title.lower().find(q.lower())
                if i >= 0:
                    top.setData(0, SPAN, (i, len(q)))
            for h in e["hits"]:
                it = QTreeWidgetItem([h["snippet"]])
                start = h["start"] + (1 if h["snippet"].startswith("…") else 0)
                it.setData(0, SPAN, (start, len(q)))
                it.setData(0, HIT, {"page_id": p["id"], "block_id": h["block_id"], "nth": h["nth"]})
                it.setToolTip(0, h["snippet"])
                top.addChild(it)
            if n > len(e["hits"]):
                more = QTreeWidgetItem([f"   … {n - len(e['hits'])} more on this page"])
                more.setData(0, HIT, {"page_id": p["id"]})
                more.setForeground(0, QColor(theme.t("muted")))
                top.addChild(more)
            self.results.addTopLevelItem(top)
            top.setExpanded(True)
        self.results.setUpdatesEnabled(True)
        pages = len(res)
        self.status.setText("No matches" if not pages else
                            f"{total} match{'es' if total != 1 else ''} in {pages} page{'s' if pages != 1 else ''}"
                            if total else f"{pages} page{'s' if pages != 1 else ''} by title")
        self.show_results(True)

    def open_first(self):
        top = self.results.topLevelItem(0)
        if top is not None:
            self.open_item(top.child(0) or top)

    def open_item(self, item, _col=0):
        hit = item.data(0, HIT) if item is not None else None
        if not hit:
            return
        ed = self.window.editor
        if ed.page_id != hit["page_id"]:
            self.window.open_page(hit["page_id"])
        q = self.field.text().strip()
        if hit.get("block_id"):
            ed.find_bar.start(q, hit["block_id"], hit["nth"])
        elif any(item.child(i) for i in range(item.childCount())) or "more on this page" in item.text(0):
            ed.find_bar.start(q)
