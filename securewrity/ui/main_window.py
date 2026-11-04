"""Main application window: sidebar + page editor, menus, shortcuts, auto-lock."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (QApplication, QDialog, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMainWindow, QMenu, QSplitter, QStackedWidget,
                             QVBoxLayout, QWidget)

from .. import APP_NAME
from .dialogs import PageSearchDialog, PluginsDialog, SettingsDialog, TrashDialog
from .editor.page_editor import PageEditor
from .protection import SecurityDialog
from .sidebar import Sidebar


class _ActivityFilter(QObject):
    def __init__(self, cb):
        super().__init__()
        self.cb = cb

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel):
            self.cb()
        return False


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        ctx.window = self
        self.locking = False
        self._subs = []
        self.resize(1280, 820)

        self.editor = PageEditor(ctx)
        self.sidebar = Sidebar(self)
        self.empty = QLabel("No page selected.\n\nPress Ctrl+N to create one.")
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.editor)

        self.splitter = QSplitter()
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.stack)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([ctx.repo.get_setting("sidebar_width", 260), 1000])
        self.splitter.setHandleWidth(1)
        self.setCentralWidget(self.splitter)

        self.toast = QLabel(self)
        self.toast.setObjectName("Popup")
        self.toast.setStyleSheet("padding:8px 14px;")
        self.toast.hide()
        self.toast_timer = QTimer(self, singleShot=True, interval=2600, timeout=self.toast.hide)

        self.refresh_timer = QTimer(self, singleShot=True, interval=250, timeout=self._refresh_pages)
        self._on("pages_changed", lambda: self.refresh_timer.start())
        self._on("page_saved", lambda pid: None)

        self._install_shortcuts()
        self.activity = _ActivityFilter(self._activity)
        QApplication.instance().installEventFilter(self.activity)
        self.lock_timer = QTimer(self, singleShot=True, timeout=self._autolock)
        self.setup_autolock()

        self.sidebar.refresh()
        last = ctx.repo.get_setting("last_page")
        pages = ctx.repo.list_pages()
        target = None
        if last and ctx.repo.get_setting("reopen_last", True):
            p = ctx.repo.get_page(last)
            target = last if p and not p["trashed"] else None
        if not target and pages:
            target = next((p["id"] for p in pages if p["parent_id"] is None), pages[0]["id"])
        if target:
            self.open_page(target)
        else:
            self._update_title()

    # --- events helpers -------------------------------------------------------
    def _on(self, name, fn):
        self.ctx.events.on(name, fn)
        self._subs.append((name, fn))

    def _refresh_pages(self):
        self.sidebar.refresh()
        if self.editor.page_id:
            p = self.ctx.repo.get_page(self.editor.page_id)
            if not p or p["trashed"]:
                self._show_fallback()
            else:
                self.editor.refresh_header()
        self._update_title()

    def _update_title(self):
        page = self.ctx.repo.get_page(self.editor.page_id) if self.editor.page_id else None
        user = self.ctx.account.username
        lock = "🔒 " if self.ctx.store.encrypted else ""
        name = (page["title"] or "Untitled") + " — " if page else ""
        self.setWindowTitle(f"{name}{APP_NAME} · {lock}{user}")

    # --- navigation ----------------------------------------------------------------
    def open_page(self, page_id: str, focus_title: bool = False):
        p = self.ctx.repo.get_page(page_id)
        if not p:
            self.notify("That page no longer exists.")
            return
        if p["trashed"]:
            self.notify("That page is in the trash.")
            return
        if self.editor.page_id != page_id:
            self.editor.load(page_id)
        self.stack.setCurrentWidget(self.editor)
        self.ctx.repo.set_setting("last_page", page_id)
        self.sidebar.reveal(page_id)
        self._update_title()
        if focus_title or not p["title"]:
            self.editor.title.setFocus()
        elif self.editor.blocks:
            self.editor.focus_block(self.editor.blocks[0], "end")

    def _show_fallback(self):
        pages = self.ctx.repo.list_pages()
        self.editor.page_id = None
        if pages:
            self.open_page(pages[0]["id"])
        else:
            self.editor.load("")
            self.stack.setCurrentWidget(self.empty)

    def create_page(self, parent_id=None, title="", link_in_parent=True, open_it=True) -> str:
        self.editor.save_now()
        repo = self.ctx.repo
        pid = repo.create_page(parent_id, title)
        if parent_id and link_in_parent:
            block = {"type": "page", "props": {"page_id": pid}}
            if self.editor.page_id == parent_id:
                self.editor.append_block(block)
                self.editor.save_now()
            else:
                tree = repo.get_blocks(parent_id)
                tree.append(block)
                repo.save_blocks(parent_id, tree)
        self.ctx.events.emit("page_created", pid)
        self.sidebar.refresh()
        if open_it:
            self.open_page(pid, focus_title=True)
        return pid

    def trash_page(self, page_id: str):
        self.editor.save_now()
        p = self.ctx.repo.get_page(page_id)
        self.ctx.repo.trash_page(page_id)
        self.ctx.events.emit("page_deleted", page_id)
        cur = self.editor.page_id
        if cur and (cur == page_id or page_id in [a["id"] for a in self.ctx.repo.ancestors(cur)]):
            self.editor.page_id = None
            if p and p["parent_id"]:
                self.open_page(p["parent_id"])
            else:
                self._show_fallback()
        self.sidebar.refresh()
        self.notify("Moved to trash.")

    def move_page_dialog(self, page_id: str):
        target = PageSearchDialog.choose(self.ctx, self, mode="pick")
        if not target or target == page_id:
            return
        if target in self.ctx.repo.descendants(page_id):
            self.notify("Can't move a page inside its own sub-page.")
            return
        self.ctx.repo.move_page(page_id, target, 1e9)
        self.ctx.repo.commit()
        self.ctx.events.emit("pages_changed")

    # --- menus ----------------------------------------------------------------------
    def populate_page_menu(self, m: QMenu, page_id: str):
        if not page_id:
            return
        repo = self.ctx.repo
        p = repo.get_page(page_id)
        if not p:
            return
        m.addAction("Open", lambda: self.open_page(page_id))
        m.addAction("＋  Add sub-page", lambda: self.create_page(parent_id=page_id))
        m.addAction("☆  Remove from favorites" if p["favorite"] else "★  Add to favorites",
                    lambda: (repo.update_page(page_id, favorite=0 if p["favorite"] else 1),
                             self.ctx.events.emit("pages_changed")))
        m.addAction("↪  Move to…", lambda: self.move_page_dialog(page_id))
        if p["parent_id"]:
            m.addAction("⇱  Move to top level", lambda: (repo.move_page(page_id, None, 1e9), repo.commit(),
                                                          self.ctx.events.emit("pages_changed")))
        page_cmds = [c for c in self.ctx.api.commands if c.scope == "page"]
        if page_cmds:
            m.addSeparator()
            for c in page_cmds:
                m.addAction(c.label, lambda c=c: self._run(c, page_id))
        m.addSeparator()
        m.addAction("🗑  Move to trash", lambda: self.trash_page(page_id))

    def populate_app_menu(self, m: QMenu):
        m.addAction("🔐  Security & encryption…", self.show_security)
        m.addAction("⚙  Settings…", self.show_settings)
        m.addAction("🎨  Toggle dark / light\tCtrl+Shift+L", self.toggle_theme)
        m.addAction("🧩  Plugins…", lambda: PluginsDialog(self.ctx.controller, self).exec())
        m.addAction("⌘  Command palette\tCtrl+Shift+P", self.command_palette)
        m.addAction("📥  Import Markdown file…", self.import_markdown)
        m.addAction("❓  Help\tF1", self.show_help)
        app_cmds = [c for c in self.ctx.api.commands if c.scope == "app"]
        if app_cmds:
            sub = m.addMenu("Plugin commands")
            for c in app_cmds:
                sub.addAction(c.label + (f"\t{c.shortcut}" if c.shortcut else ""), lambda c=c: self._run(c))
        m.addSeparator()
        m.addAction("🔒  Lock / switch user\tCtrl+L", self.lock)
        m.addAction("⏻  Quit\tCtrl+Q", self.close)

    def _run(self, cmd, page_id=None):
        try:
            if cmd.scope == "page":
                cmd.callback(page_id or self.editor.page_id)
            else:
                cmd.callback()
        except Exception as e:  # plugins must not crash the app
            import traceback
            traceback.print_exc()
            self.notify(f"Plugin command failed: {e}")

    def _install_shortcuts(self):
        def add(seq, fn):
            a = QAction(self)
            a.setShortcut(QKeySequence(seq))
            a.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            a.triggered.connect(fn)
            self.addAction(a)
        add("Ctrl+P", self.quick_switch)
        add("Ctrl+N", lambda: self.create_page())
        add("Ctrl+Shift+N", lambda: self.create_page(parent_id=self.editor.page_id))
        add("Ctrl+L", self.lock)
        add("Ctrl+Q", self.close)
        add("Ctrl+\\", self.toggle_sidebar)
        add("Ctrl+Shift+L", self.toggle_theme)
        add("Ctrl+Shift+P", self.command_palette)
        add("Ctrl+S", lambda: (self.editor.save_now(), self.notify("Saved")))
        add("Alt+Left", self.go_parent)
        add("F1", self.show_help)
        for c in self.ctx.api.commands:
            if c.shortcut:
                add(c.shortcut, lambda c=c: self._run(c))

    def go_parent(self):
        p = self.ctx.repo.get_page(self.editor.page_id) if self.editor.page_id else None
        if p and p["parent_id"]:
            self.open_page(p["parent_id"])

    def all_commands(self):
        builtin = [
            ("New page", lambda: self.create_page()),
            ("New sub-page", lambda: self.create_page(parent_id=self.editor.page_id)),
            ("Search pages", self.quick_switch),
            ("Toggle dark / light theme", self.toggle_theme),
            ("Toggle sidebar", self.toggle_sidebar),
            ("Security & encryption", self.show_security),
            ("Settings", self.show_settings),
            ("Trash", self.show_trash),
            ("Plugins", lambda: PluginsDialog(self.ctx.controller, self).exec()),
            ("Lock", self.lock),
            ("Help", self.show_help),
            ("Import Markdown file", self.import_markdown),
        ]
        for c in self.ctx.api.commands:
            builtin.append((c.label, lambda c=c: self._run(c)))
        return builtin

    def command_palette(self):
        d = QDialog(self)
        d.setWindowTitle("Command palette")
        d.resize(460, 380)
        v = QVBoxLayout(d)
        q = QLineEdit()
        q.setPlaceholderText("Type a command…")
        lst = QListWidget()
        v.addWidget(q)
        v.addWidget(lst)
        cmds = self.all_commands()

        def fill():
            lst.clear()
            for label, fn in cmds:
                if q.text().lower() in label.lower():
                    it = QListWidgetItem(label)
                    it.setData(Qt.ItemDataRole.UserRole, fn)
                    lst.addItem(it)
            lst.setCurrentRow(0)

        chosen = []

        def run(it=None):
            it = it or lst.currentItem()
            if it:
                chosen.append(it.data(Qt.ItemDataRole.UserRole))
                d.accept()
        q.textChanged.connect(fill)
        q.returnPressed.connect(run)
        lst.itemActivated.connect(run)
        fill()
        d.exec()
        if chosen:
            chosen[0]()

    # --- dialogs ---------------------------------------------------------------------
    def quick_switch(self):
        pid = PageSearchDialog.choose(self.ctx, self, mode="switch")
        if pid:
            self.open_page(pid)

    def show_trash(self):
        self.editor.save_now()
        TrashDialog(self.ctx, self).exec()
        self._refresh_pages()

    def import_markdown(self, path: str | None = None):
        """Make a new page from a .md file (an AI answer saved to a file, a Notion export…)."""
        from pathlib import Path

        from PyQt6.QtWidgets import QFileDialog

        from ..core.markdown_import import parse_markdown
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Import Markdown", str(Path.home()),
                                                  "Markdown (*.md *.markdown *.txt);;All files (*)")
        if not path:
            return None
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            self.notify(f"Couldn't read the file: {e}")
            return None
        blocks = parse_markdown(text)
        title = Path(path).stem
        if blocks and blocks[0]["type"] in ("h1", "toggle_h1") and not blocks[0]["children"]:
            title = "".join(r["t"] for r in blocks.pop(0)["content"]) or title
        # Notion export file names end in a 32-character id
        import re
        title = re.sub(r"\s+[0-9a-f]{32}$", "", title)
        repo = self.ctx.repo
        pid = repo.create_page(None, title)
        repo.save_blocks(pid, blocks)
        repo.commit()
        self.ctx.events.emit("pages_changed")
        self.open_page(pid)
        self.notify(f"Imported “{title}”")
        return pid

    def show_help(self, section: str | None = None):
        from .help import HelpWindow
        if getattr(self, "help_window", None) is None:
            self.help_window = HelpWindow(self)
        self.help_window.show_section(section)

    def show_settings(self):
        SettingsDialog(self.ctx, self).exec()

    def show_security(self):
        SecurityDialog(self.ctx, self).exec()
        icon = "👤" if self.ctx.account.is_guest else ("🔒" if self.ctx.store.encrypted else "🔓")
        self.sidebar.user_btn.setText(f"{icon}  {self.ctx.account.username}  ▾")
        self._update_title()

    def toggle_sidebar(self):
        self.sidebar.setVisible(not self.sidebar.isVisible())

    def toggle_theme(self):
        c = self.ctx.controller
        c.set_theme("light" if c.config.get("theme", "dark") == "dark" else "dark")

    def notify(self, text: str, ms: int = 2600):
        self.toast.setText(text)
        self.toast.adjustSize()
        self.toast.move((self.width() - self.toast.width()) // 2, self.height() - self.toast.height() - 30)
        self.toast.show()
        self.toast.raise_()
        self.toast_timer.start(ms)

    # --- theme / auto-lock / shutdown ------------------------------------------------
    def apply_theme(self):
        self.editor.reload_keep_focus()
        self.sidebar.refresh()
        if getattr(self, "help_window", None) is not None:
            self.help_window.retheme()

    def setup_autolock(self):
        default = 15 if self.ctx.store.encrypted else 0
        minutes = self.ctx.repo.get_setting("autolock_minutes", default)
        self.lock_timer.stop()
        self._lock_ms = int(minutes) * 60_000 if minutes else 0
        if self._lock_ms:
            self.lock_timer.start(self._lock_ms)

    def _activity(self):
        if self._lock_ms:
            self.lock_timer.start(self._lock_ms)

    def _autolock(self):
        self.ctx.controller.lock()

    def lock(self):
        self.ctx.controller.lock()

    def shutdown(self):
        """Save everything and detach from the event bus."""
        self.editor.save_now()
        try:
            self.ctx.repo.set_setting("sidebar_width", self.splitter.sizes()[0])
        except Exception:
            pass
        for t in (self.lock_timer, self.refresh_timer, self.editor.save_timer, self.editor.title_timer):
            t.stop()
        QApplication.instance().removeEventFilter(self.activity)
        self.editor.slash.close()
        if getattr(self, "help_window", None) is not None:
            self.help_window.close()
        for name, fn in self._subs:
            self.ctx.events.off(name, fn)
        self._subs.clear()

    def closeEvent(self, e):
        if not self.locking:
            self.ctx.controller.quit_from_window()
        e.accept()
