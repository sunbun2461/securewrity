"""Help window: searchable documentation with a clickable table of contents."""
from __future__ import annotations

import re
from html import unescape
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QKeySequence, QShortcut, QTextCharFormat, QTextCursor, QTextDocument
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QSplitter, QTextBrowser, QTextEdit,
                             QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import help_docs
from . import theme

IMAGES = Path(__file__).resolve().parent.parent / "data" / "help"

# sections added by plugins: list of {"id", "title", "level", "html"}
extra_sections: list[dict] = []


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip().lower()


class HelpWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Securewrity Help")
        self.setObjectName("EditorRoot")
        self.resize(1040, 720)
        self.matches: list[QTextCursor] = []
        self.match_i = -1

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter()
        root.addWidget(split)

        # left: search + contents
        left = QWidget()
        left.setObjectName("Sidebar")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(10, 10, 6, 10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Search help…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        self.search.returnPressed.connect(lambda: self.step(1))
        lv.addWidget(self.search)
        nav = QHBoxLayout()
        self.count = QLabel("")
        self.count.setObjectName("Muted")
        nav.addWidget(self.count, 1)
        self.prev_btn = QToolButton(text="▲", toolTip="Previous match (Shift+Enter)")
        self.next_btn = QToolButton(text="▼", toolTip="Next match (Enter)")
        self.prev_btn.clicked.connect(lambda: self.step(-1))
        self.next_btn.clicked.connect(lambda: self.step(1))
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.next_btn)
        lv.addLayout(nav)
        head = QLabel("CONTENTS")
        head.setObjectName("SectionLabel")
        lv.addWidget(head)
        self.toc = QTreeWidget()
        self.toc.setHeaderHidden(True)
        self.toc.setIndentation(14)
        self.toc.itemClicked.connect(self._toc_clicked)
        self.toc.itemActivated.connect(self._toc_clicked)
        lv.addWidget(self.toc, 1)
        split.addWidget(left)

        # right: the document
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._link)
        self.view.setSearchPaths([str(IMAGES)])
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setStyleSheet(f"QTextBrowser{{background:{theme.t('bg')}; border:none; padding:12px 28px;}}")
        self.view.verticalScrollBar().valueChanged.connect(lambda: self.sync_timer.start())
        split.addWidget(self.view)
        split.setSizes([260, 780])
        split.setStretchFactor(1, 1)

        self.search_timer = QTimer(self, singleShot=True, interval=150, timeout=self.run_search)
        self.sync_timer = QTimer(self, singleShot=True, interval=60, timeout=self._sync_toc)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: (self.search.setFocus(), self.search.selectAll()))
        QShortcut(QKeySequence("Shift+Return"), self.search, activated=lambda: self.step(-1))
        QShortcut(QKeySequence("Esc"), self, activated=self._escape)
        self.build()

    # ------------------------------------------------------------------ content
    def build(self):
        self.sections = help_docs.sections() + list(extra_sections)
        for s in self.sections:
            s["plain"] = _plain(s["title"] + " " + s["html"])
        h1 = f"font-size:24px; font-weight:700; margin-top:26px;"
        h2 = f"font-size:18px; font-weight:600; margin-top:18px;"
        parts = [f"<div style='font-size:14px; color:{theme.t('text')};'>"]
        for s in self.sections:
            style = h1 if s["level"] == 1 else h2
            parts.append(f"<a name='{s['id']}'></a><p style='{style}'>{s['title']}</p>{s['html']}")
        parts.append("<p>&nbsp;</p>" * 12 + "</div>")  # room to scroll the last section to the top
        doc = self.view.document()
        doc.setDefaultStyleSheet(f"a {{ color: {theme.t('link')}; }} code {{ background-color: {theme.t('hover')}; }}")
        self.view.setHtml("".join(parts))
        self._anchor_pos = self._find_anchor_positions()

        self.toc.clear()
        self.items: dict[str, QTreeWidgetItem] = {}
        parent = None
        for s in self.sections:
            if s["level"] == 1 or parent is None:
                it = QTreeWidgetItem(self.toc, [s["title"]])
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
                parent = it
            else:
                it = QTreeWidgetItem(parent, [s["title"]])
            it.setData(0, Qt.ItemDataRole.UserRole, s["id"])
            self.items[s["id"]] = it
        self.toc.expandAll()

    def _find_anchor_positions(self) -> list[tuple[int, str]]:
        out = []
        block = self.view.document().begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                for name in frag.charFormat().anchorNames():
                    out.append((frag.position(), name))
                it += 1
            block = block.next()
        return sorted(out)

    def retheme(self):
        self.view.setStyleSheet(f"QTextBrowser{{background:{theme.t('bg')}; border:none; padding:12px 28px;}}")
        q = self.search.text()
        self.build()
        if q:
            self.run_search()

    # ------------------------------------------------------------------ navigation
    def show_section(self, section_id: str | None = None):
        self.show()
        self.raise_()
        self.activateWindow()
        if section_id:
            self.view.scrollToAnchor(section_id)
            if section_id in self.items:
                self.toc.setCurrentItem(self.items[section_id])

    def _toc_clicked(self, item, _col=0):
        sid = item.data(0, Qt.ItemDataRole.UserRole)
        self.view.scrollToAnchor(sid)
        # with a search running, jump to the first match inside that section
        if self.matches:
            start = dict((n, p) for p, n in self._anchor_pos).get(sid, 0)
            for i, c in enumerate(self.matches):
                if c.position() >= start:
                    self.match_i = i - 1
                    self.step(1)
                    break

    def _link(self, url: QUrl):
        if url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)
        elif url.hasFragment():
            self.show_section(url.fragment())

    def _sync_toc(self):
        """Highlight the contents entry for the section at the top of the view."""
        top = self.view.cursorForPosition(self.view.viewport().rect().topLeft()).position()
        current = None
        for pos, name in self._anchor_pos:
            if pos <= top + 1:
                current = name
            else:
                break
        if current in self.items and self.toc.currentItem() is not self.items[current]:
            self.toc.blockSignals(True)
            self.toc.setCurrentItem(self.items[current])
            self.toc.scrollToItem(self.items[current])
            self.toc.blockSignals(False)

    # ------------------------------------------------------------------ search
    def run_search(self):
        q = self.search.text().strip().lower()
        words = q.split()
        # filter the contents: keep matching sections, and the parents of matching sub-sections
        for s in self.sections:
            it = self.items[s["id"]]
            it.setHidden(bool(words) and not all(w in s["plain"] for w in words))
        for i in range(self.toc.topLevelItemCount()):
            top = self.toc.topLevelItem(i)
            if any(not top.child(j).isHidden() for j in range(top.childCount())):
                top.setHidden(False)
        # highlight every occurrence of each word in the document
        self.matches = []
        sels = []
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#F5D76E"))
        fmt.setForeground(QColor("#1A1A1A"))
        doc = self.view.document()
        for w in words:
            c = QTextCursor(doc)
            while True:
                c = doc.find(w, c)
                if c.isNull():
                    break
                self.matches.append(QTextCursor(c))
                sel = QTextEdit.ExtraSelection()
                sel.cursor, sel.format = QTextCursor(c), fmt
                sels.append(sel)
        self.matches.sort(key=lambda c: c.position())
        self.view.setExtraSelections(sels)
        self.match_i = -1
        if not words:
            self.count.setText("")
        elif not self.matches:
            self.count.setText("No matches")
        else:
            self.step(1)

    def step(self, delta: int):
        if not self.matches:
            return
        self.match_i = (self.match_i + delta) % len(self.matches)
        c = self.matches[self.match_i]
        self.view.setTextCursor(c)
        self.view.ensureCursorVisible()
        # put the match a little below the top so its heading stays in view
        sb = self.view.verticalScrollBar()
        y = self.view.cursorRect(c).top()
        if y > self.view.viewport().height() * 0.6 or y < 0:
            sb.setValue(sb.value() + y - 120)
        self.count.setText(f"{self.match_i + 1} of {len(self.matches)} matches")

    def _escape(self):
        if self.search.text():
            self.search.clear()
        else:
            self.close()
