"""Search / page picker, trash, plugins and settings dialogs."""
from __future__ import annotations

import time

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QMessageBox, QPushButton, QSpinBox, QVBoxLayout)


def _ago(ts: float) -> str:
    d = time.time() - ts
    for unit, sec in (("d", 86400), ("h", 3600), ("m", 60)):
        if d >= sec:
            return f"{int(d // sec)}{unit} ago"
    return "just now"


class PageSearchDialog(QDialog):
    """mode='switch' -> quick switcher (Ctrl+P); 'pick' -> choose a page;
    'link' -> choose a page or enter a URL, or create a new page; 'move' -> where to move blocks."""

    def __init__(self, ctx, parent=None, mode="switch", initial=""):
        super().__init__(parent)
        self.ctx, self.mode, self.result_value = ctx, mode, None
        self.setWindowTitle({"switch": "Search", "pick": "Choose a page", "link": "Link to…",
                            "move": "Move blocks to…"}[mode])
        self.resize(560, 440)
        lay = QVBoxLayout(self)
        self.q = QLineEdit(initial)
        self.q.setPlaceholderText({"switch": "Search pages and content…",
                                   "pick": "Search for a page…",
                                   "move": "Search for the page to move them to…",
                                   "link": "Search pages, or paste a URL…"}[mode])
        self.q.textChanged.connect(self.refresh)
        self.q.installEventFilter(self)
        lay.addWidget(self.q)
        self.list = QListWidget()
        self.list.itemActivated.connect(self._activate)
        lay.addWidget(self.list, 1)
        hint = QLabel("↑↓ to navigate · Enter to select · Esc to close")
        hint.setObjectName("Muted")
        lay.addWidget(hint)
        self.refresh()

    def eventFilter(self, obj, ev):
        if obj is self.q and ev.type() == ev.Type.KeyPress:
            k = ev.key()
            if k in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                n = self.list.count()
                if n:
                    d = 1 if k == Qt.Key.Key_Down else -1
                    self.list.setCurrentRow((self.list.currentRow() + d) % n)
                return True
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                it = self.list.currentItem()
                if it:
                    self._activate(it)
                return True
        return False

    def _add(self, text, value):
        it = QListWidgetItem(text)
        it.setData(Qt.ItemDataRole.UserRole, value)
        self.list.addItem(it)

    def refresh(self):
        q = self.q.text().strip()
        self.list.clear()
        repo = self.ctx.repo
        if self.mode == "link" and q.startswith(("http://", "https://", "mailto:", "file://")):
            self._add(f"🌐  Link to URL: {q}", ("url", q))
        if q:
            for r in repo.search(q):
                p = r["page"]
                path = " / ".join((a["title"] or "Untitled") for a in repo.ancestors(p["id"]))
                line = f"{p['icon'] or '📄'}  {p['title'] or 'Untitled'}"
                if path:
                    line += f"      — in {path}"
                if r["snippet"]:
                    line += f"\n        …{r['snippet']}…"
                self._add(line, ("page", p["id"]))
            if self.mode in ("link", "pick", "move"):
                self._add(f"＋  New page “{q}” (inside current page)", ("new", q))
        else:
            pages = sorted(repo.list_pages(), key=lambda p: -p["updated"])[:30]
            here = self.ctx.window.editor.page_id if self.mode == "move" else None
            for p in pages:
                if p["id"] == here:
                    continue
                self._add(f"{p['icon'] or '📄'}  {p['title'] or 'Untitled'}      · {_ago(p['updated'])}",
                          ("page", p["id"]))
        if self.list.count():
            self.list.setCurrentRow(0)

    def _activate(self, it):
        kind, val = it.data(Qt.ItemDataRole.UserRole)
        if kind == "new":
            editor = self.ctx.window.editor
            val = self.ctx.window.create_page(parent_id=editor.page_id, title=val, open_it=False)
        self.result_value = val
        self.accept()

    @classmethod
    def choose(cls, ctx, parent=None, mode="pick", initial=""):
        d = cls(ctx, parent, mode, initial)
        return d.result_value if d.exec() else None


class TrashDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Trash")
        self.resize(480, 400)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Pages in the trash (sub-pages are restored/deleted with their parent)."))
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, fn, obj in (("Restore", self.restore, ""), ("Delete forever", self.delete, "Danger"),
                              ("Empty trash", self.empty, "Danger")):
            b = QPushButton(text)
            if obj:
                b.setObjectName(obj)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for p in self.ctx.repo.trashed_roots():
            it = QListWidgetItem(f"{p['icon'] or '📄'}  {p['title'] or 'Untitled'}")
            it.setData(Qt.ItemDataRole.UserRole, p["id"])
            self.list.addItem(it)

    def _sel(self):
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def restore(self):
        pid = self._sel()
        if pid:
            self.ctx.repo.restore_page(pid)
            self.ctx.events.emit("pages_changed")
            self.refresh()

    def delete(self):
        pid = self._sel()
        if pid and QMessageBox.question(self, "Delete forever", "Permanently delete this page and its sub-pages?") \
                == QMessageBox.StandardButton.Yes:
            self.ctx.repo.delete_page(pid)
            self.ctx.events.emit("pages_changed")
            self.refresh()

    def empty(self):
        roots = self.ctx.repo.trashed_roots()
        if roots and QMessageBox.question(self, "Empty trash", f"Permanently delete {len(roots)} page(s)?") \
                == QMessageBox.StandardButton.Yes:
            for p in roots:
                self.ctx.repo.delete_page(p["id"])
            self.ctx.events.emit("pages_changed")
            self.refresh()


class PluginsDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.c = controller
        self.setWindowTitle("Plugins")
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        info = QLabel(f"Drop .py plugin files into:<br><code>{controller.user_plugin_dir}</code><br>"
                      "Changes take effect after restarting Securewrity.")
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info.setWordWrap(True)
        lay.addWidget(info)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        disabled = set(controller.config.get("disabled_plugins", []))
        for p in controller.plugin_infos:
            status = "error: " + p["error"] if p.get("error") else ("loaded" if p["loaded"] else "disabled")
            it = QListWidgetItem(f"{p['name']}  v{p.get('version', '?')}   [{p['source']}]  — {status}\n"
                                 f"    {p.get('description', '')}")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked if p["id"] in disabled else Qt.CheckState.Checked)
            it.setData(Qt.ItemDataRole.UserRole, p["id"])
            self.list.addItem(it)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def save(self):
        disabled = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() != Qt.CheckState.Checked:
                disabled.append(it.data(Qt.ItemDataRole.UserRole))
        self.c.config["disabled_plugins"] = disabled
        self.c.save_config()
        self.accept()


class SettingsDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Settings")
        lay = QFormLayout(self)
        self.theme = QComboBox()
        self.theme.addItems(["dark", "light"])
        self.theme.setCurrentText(ctx.controller.config.get("theme", "dark"))
        lay.addRow("Theme", self.theme)
        self.font_size = QSpinBox()
        self.font_size.setRange(10, 22)
        self.font_size.setValue(ctx.controller.config.get("font_size", 14))
        lay.addRow("UI font size", self.font_size)
        self.autolock = QSpinBox()
        self.autolock.setRange(0, 600)
        self.autolock.setSuffix(" min")
        self.autolock.setSpecialValueText("Never")
        self.autolock.setValue(ctx.repo.get_setting("autolock_minutes", 15 if ctx.store.encrypted else 0))
        lay.addRow("Auto-lock when idle", self.autolock)
        self.spell = QCheckBox("Open the last page on unlock")
        self.spell.setChecked(ctx.repo.get_setting("reopen_last", True))
        lay.addRow("", self.spell)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def save(self):
        c = self.ctx.controller
        c.config["font_size"] = self.font_size.value()
        self.ctx.repo.set_setting("autolock_minutes", self.autolock.value())
        self.ctx.repo.set_setting("reopen_last", self.spell.isChecked())
        c.set_theme(self.theme.currentText())
        self.ctx.window.setup_autolock()
        self.accept()
