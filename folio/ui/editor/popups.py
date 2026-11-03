"""Floating UI used by the editor: slash menu, inline toolbar, color menus, emoji picker."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMenu, QPushButton, QToolButton,
                             QVBoxLayout, QWidget)

from ...blocks.registry import registry
from .. import theme

# --- color helpers -----------------------------------------------------------------


def swatch_icon(name: str, background: bool) -> QIcon:
    pm = QPixmap(22, 22)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor(theme.t("border")))
    p.setBrush(QColor(theme.bg_color(name) or theme.t("bg")) if background else QColor(theme.t("bg")))
    p.drawRoundedRect(1, 1, 20, 20, 4, 4)
    if not background:
        p.setPen(QColor(theme.text_color(name)))
        f = QFont()
        f.setPixelSize(14)
        f.setBold(True)
        p.setFont(f)
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "A")
    p.end()
    return QIcon(pm)


def add_color_actions(menu: QMenu, on_pick) -> None:
    """on_pick(kind, name) where kind is 'c' (text) or 'bg'."""
    head = menu.addAction("Text color")
    head.setEnabled(False)
    for n in theme.COLOR_NAMES:
        a = menu.addAction(swatch_icon(n, False), n.capitalize())
        a.triggered.connect(lambda _=False, n=n: on_pick("c", n))
    menu.addSeparator()
    head = menu.addAction("Background")
    head.setEnabled(False)
    for n in theme.COLOR_NAMES:
        a = menu.addAction(swatch_icon(n, True), (n.capitalize() + " background") if n != "default" else "Default background")
        a.triggered.connect(lambda _=False, n=n: on_pick("bg", n))


# --- slash menu ----------------------------------------------------------------------


class SlashMenu(QFrame):
    """Command list shown after typing '/'. Never takes keyboard focus; the
    block editor forwards Up/Down/Enter/Esc to it while it is open."""

    def __init__(self, editor):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName("Popup")
        self.editor = editor
        self.bw = None
        self.slash_pos = 0
        self.misses = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.list = QListWidget()
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setIconSize(QSize(22, 22))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.itemClicked.connect(lambda _: self.activate())
        lay.addWidget(self.list)
        self.setFixedSize(360, 380)

    def entries(self):
        out = []
        for bt in registry.all():
            if bt.in_slash_menu:
                out.append({"kind": "block", "key": bt.key, "label": bt.label, "icon": bt.icon,
                            "desc": bt.description, "terms": " ".join((bt.label, bt.key) + tuple(bt.aliases)).lower()})
        for n in theme.COLOR_NAMES:
            out.append({"kind": "c", "key": n, "label": f"{n.capitalize()} text", "icon": None,
                        "desc": "Text color", "terms": f"{n} color text"})
        for n in theme.COLOR_NAMES:
            out.append({"kind": "bg", "key": n, "label": f"{n.capitalize()} background", "icon": None,
                        "desc": "Background color", "terms": f"{n} background bg highlight"})
        return out

    def open_for(self, bw, slash_pos: int):
        self.bw, self.slash_pos, self.misses = bw, slash_pos, 0
        self.refilter("")
        te = bw.text
        pt = te.viewport().mapToGlobal(te.cursorRect().bottomLeft()) + QPoint(0, 6)
        screen = te.screen().availableGeometry()
        if pt.y() + self.height() > screen.bottom():
            pt = te.viewport().mapToGlobal(te.cursorRect().topLeft()) - QPoint(0, self.height() + 6)
        self.move(pt)
        self.show()
        self.raise_()

    def refilter(self, query: str):
        q = query.lower().strip()
        self.list.clear()
        ranked = []
        for i, e in enumerate(self.entries()):
            if q and not all(word in e["terms"] for word in q.split()):
                continue
            # rank: label starts with query < a word starts with it < substring match
            label = e["label"].lower()
            words = e["terms"].split()
            rank = 0 if label.startswith(q) else 1 if any(w.startswith(q.split()[0]) for w in words) else 2
            ranked.append((rank if q else 0, i, e))
        for _, _, e in sorted(ranked, key=lambda x: (x[0], x[1])):
            it = QListWidgetItem(f"{e['label']}\n{e['desc']}")
            if e["kind"] == "block":
                it.setIcon(self._text_icon(e["icon"]))
            else:
                it.setIcon(swatch_icon(e["key"], e["kind"] == "bg"))
            it.setData(Qt.ItemDataRole.UserRole, e)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)
            self.misses = 0
            return True
        self.misses += 1
        return False

    @staticmethod
    def _text_icon(text: str) -> QIcon:
        pm = QPixmap(22, 22)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setPen(QColor(theme.t("text")))
        p.setBrush(QColor(theme.t("hover")))
        p.drawRoundedRect(0, 0, 21, 21, 4, 4)
        f = QFont()
        f.setPixelSize(13 if len(text) == 1 else 11 if len(text) == 2 else 9)
        f.setBold(True)
        p.setFont(f)
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, text)
        p.end()
        return QIcon(pm)

    def on_text_changed(self):
        if not self.isVisible() or not self.bw or not self.bw.text:
            return
        text = self.bw.plain()
        pos = self.bw.cursor_pos()
        if pos < self.slash_pos or self.slash_pos < 1 or text[self.slash_pos - 1: self.slash_pos] != "/":
            return self.close_menu()
        query = text[self.slash_pos:pos]
        if len(query) > 30 or "\n" in query:
            return self.close_menu()
        if not self.refilter(query) and self.misses > 3:
            self.close_menu()

    def move_sel(self, delta: int):
        n = self.list.count()
        if n:
            self.list.setCurrentRow((self.list.currentRow() + delta) % n)

    def activate(self):
        it = self.list.currentItem()
        bw, start = self.bw, self.slash_pos
        self.close_menu()
        if it and bw:
            self.editor.apply_slash(bw, it.data(Qt.ItemDataRole.UserRole), start)

    def close_menu(self):
        self.hide()
        self.bw = None


# --- inline formatting toolbar ----------------------------------------------------------


class InlineToolbar(QFrame):
    def __init__(self, editor, parent: QWidget):
        super().__init__(parent)
        self.editor = editor
        self.setObjectName("Popup")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(0)
        specs = [("B", "Bold (Ctrl+B)", "b", "font-weight:bold;"),
                 ("i", "Italic (Ctrl+I)", "i", "font-style:italic;"),
                 ("U", "Underline (Ctrl+U)", "u", "text-decoration:underline;"),
                 ("S", "Strikethrough (Ctrl+Shift+S)", "s", "text-decoration:line-through;"),
                 ("</>", "Inline code (Ctrl+E)", "code", "font-family:monospace;")]
        for label, tip, attr, css in specs:
            b = self._btn(label, tip, css)
            b.clicked.connect(lambda _=False, a=attr: editor.toggle_inline(a))
            lay.addWidget(b)
        link = self._btn("🔗 Link", "Link to a page or URL (Ctrl+K)", "")
        link.clicked.connect(lambda: editor.link_selection())
        lay.addWidget(link)
        color = self._btn("A ▾", "Text / background color", "")
        color.clicked.connect(lambda: self._color_menu(color))
        lay.addWidget(color)
        self.hide()

    def _btn(self, text, tip, css):
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setStyleSheet(f"QToolButton{{{css} padding:4px 8px;}}")
        return b

    def _color_menu(self, anchor):
        m = QMenu(self)
        add_color_actions(m, lambda kind, n: self.editor.set_inline_color(kind, n))
        m.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))

    def show_for(self, bw):
        te = bw.text
        c = te.textCursor()
        c2 = te.textCursor()
        c2.setPosition(c.selectionStart())
        rect = te.cursorRect(c2)
        self.adjustSize()
        p = te.viewport().mapTo(self.parentWidget(), rect.topLeft()) - QPoint(0, self.height() + 6)
        p.setX(max(4, min(p.x(), self.parentWidget().width() - self.width() - 4)))
        p.setY(max(4, p.y()))
        self.move(p)
        self.show()
        self.raise_()


# --- emoji picker -----------------------------------------------------------------------

EMOJIS = ("📄 📝 📓 📔 📒 📕 📗 📘 📙 📚 🗂 📁 📂 🗃 🗒 📌 📍 📎 🔖 🏷 "
          "💡 ⭐ 🌟 ✨ 🔥 ⚡ ✅ ☑️ ❗ ❓ ⚠️ 🚀 🎯 🏁 🧠 💭 💬 🗨 📣 🔔 "
          "🔒 🔑 🛡 🐧 💻 🖥 ⌨️ 🖱 🧪 🔬 🧰 🔧 🔨 ⚙️ 🧩 🐞 🕵️ 📡 🌐 🗺 "
          "📅 🗓 ⏰ ⌛ 📈 📉 📊 💰 💳 🏠 🏢 ✈️ 🚗 🎵 🎮 🎨 📷 🍕 ☕ "
          "❤️ 💙 💚 💛 💜 🖤 🤍 🟥 🟧 🟨 🟩 🟦 🟪 ⬛ 🙂 😀 😎 🤔 👀 👍").split()


class EmojiPicker(QDialog):
    def __init__(self, parent, allow_remove: bool):
        super().__init__(parent, Qt.WindowType.Popup)
        self.result_value = None
        self.setObjectName("Popup")
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.custom = QLineEdit()
        self.custom.setPlaceholderText("Type or paste any emoji / character…")
        self.custom.returnPressed.connect(lambda: self._done(self.custom.text().strip()[:4] or None))
        top.addWidget(self.custom, 1)
        if allow_remove:
            rm = QPushButton("Remove")
            rm.clicked.connect(lambda: self._done(""))
            top.addWidget(rm)
        lay.addLayout(top)
        grid = QGridLayout()
        grid.setSpacing(2)
        for i, e in enumerate(EMOJIS):
            b = QToolButton()
            b.setText(e)
            b.setFixedSize(34, 34)
            b.setStyleSheet("QToolButton{font-size:20px;padding:0;}")
            b.clicked.connect(lambda _=False, e=e: self._done(e))
            grid.addWidget(b, i // 10, i % 10)
        lay.addLayout(grid)

    def _done(self, v):
        self.result_value = v
        self.accept()

    @classmethod
    def pick(cls, anchor: QWidget, allow_remove: bool = True):
        """Returns emoji string, '' for remove, or None if cancelled."""
        d = cls(anchor, allow_remove)
        d.move(anchor.mapToGlobal(QPoint(0, anchor.height())))
        d.exec()
        return d.result_value


class HintLabel(QLabel):
    def __init__(self, text=""):
        super().__init__(text)
        self.setObjectName("Muted")
