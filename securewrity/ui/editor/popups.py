"""Floating UI used by the editor: slash menu, inline toolbar, color menus, emoji picker."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMenu, QPushButton, QToolButton,
                             QVBoxLayout, QWidget, QWidgetAction)

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


class ColorPalette(QWidget):
    """Grid of swatches: text colors on top, backgrounds below, each split into
    a regular row and a pastel row. on_pick(kind, name), kind is 'c' or 'bg'."""

    def __init__(self, on_pick, parent=None):
        super().__init__(parent)
        self.on_pick = on_pick
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)
        for kind, title in (("c", "Text color"), ("bg", "Background")):
            head = QLabel(title)
            head.setObjectName("SectionLabel")
            lay.addWidget(head)
            grid = QGridLayout()
            grid.setSpacing(3)
            rows = (("Regular", ["default"] + theme.REGULAR_COLORS), ("Pastel", theme.PASTEL_COLORS))
            for r, (row_name, names) in enumerate(rows):
                lab = QLabel(row_name)
                lab.setObjectName("Muted")
                grid.addWidget(lab, r, 0)
                for i, n in enumerate(names):
                    b = QToolButton()
                    b.setIcon(swatch_icon(n, kind == "bg"))
                    b.setIconSize(QSize(22, 22))
                    b.setFixedSize(30, 30)
                    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                    tip = "Default" if n == "default" else theme.color_label(n)
                    b.setToolTip(tip + (" background" if kind == "bg" else " text"))
                    b.setAccessibleName(b.toolTip())
                    b.clicked.connect(lambda _=False, k=kind, n=n: self._pick(k, n))
                    grid.addWidget(b, r, i + 1 + (1 if row_name == "Pastel" else 0))
            lay.addLayout(grid)
        self.picked = None

    def _pick(self, kind, n):
        self.picked = (kind, n)
        w = self.parentWidget()
        while w is not None and not isinstance(w, QMenu):
            w = w.parentWidget()
        # close the whole menu chain before applying, so focus is back on the text
        top = w
        while isinstance(top, QMenu) and isinstance(top.parentWidget(), QMenu):
            top = top.parentWidget()
        if top is not None:
            top.close()
        self.on_pick(kind, n)


def add_color_actions(menu: QMenu, on_pick) -> None:
    """Put a swatch palette into a menu. on_pick(kind, name) where kind is 'c' (text) or 'bg'."""
    act = QWidgetAction(menu)
    act.setDefaultWidget(ColorPalette(on_pick, menu))
    menu.addAction(act)


# --- slash menu ----------------------------------------------------------------------


class SlashMenu(QFrame):
    """Command list shown after typing '/'. Never takes keyboard focus; the
    block editor forwards Up/Down/Enter/Esc to it while it is open."""

    def __init__(self, editor):
        # A child overlay of the editor (not a separate window): separate tooltip
        # windows are unreliable on Wayland and some X11 window managers.
        super().__init__(editor)
        self.setObjectName("Popup")
        self.hide()
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
            lab = theme.color_label(n)
            out.append({"kind": "c", "key": n, "label": f"{lab} text", "icon": None, "color": True,
                        "desc": "Text color", "terms": f"{lab} color colour text".lower()})
        for n in theme.COLOR_NAMES:
            lab = theme.color_label(n)
            out.append({"kind": "bg", "key": n, "label": f"{lab} background", "icon": None, "color": True,
                        "desc": "Background color", "terms": f"{lab} color colour background bg highlight".lower()})
        return out

    def open_for(self, bw, slash_pos: int):
        self.bw, self.slash_pos, self.misses = bw, slash_pos, 0
        self.refilter("")
        te, host = bw.text, self.editor
        pt = te.viewport().mapTo(host, te.cursorRect().bottomLeft()) + QPoint(0, 6)
        if pt.y() + self.height() > host.height() - 4:
            above = te.viewport().mapTo(host, te.cursorRect().topLeft()) - QPoint(0, self.height() + 6)
            pt = above if above.y() >= 4 else QPoint(pt.x(), max(4, host.height() - self.height() - 4))
        pt.setX(max(4, min(pt.x(), host.width() - self.width() - 4)))
        self.move(pt)
        self.show()
        self.raise_()

    def refilter(self, query: str):
        q = query.lower().strip()
        self.list.clear()
        ranked = []
        for i, e in enumerate(self.entries()):
            if not q and e.get("color"):
                continue
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
        color = self._btn("🎨 Color ▾", "Text / background color (20 colors, regular and pastel)", "")
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
