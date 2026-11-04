"""Application controller: login → unlocked session → lock → login ..."""
from __future__ import annotations

import json
import logging
import os
import sys
from types import SimpleNamespace

from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication

from . import APP_ID, APP_NAME
from .blocks.builtin import register_builtin_blocks
from .core.accounts import AccountManager
from .core.events import EventBus
from .core.repo import Repo
from .plugin_api import PluginAPI, load_plugins
from .ui import theme
from .ui.login import LoginWindow
from .welcome import create_welcome_pages

FONT_FAMILIES = ["Noto Sans", "Cantarell", "Ubuntu", "DejaVu Sans", "Liberation Sans", "Sans Serif",
                 "Noto Color Emoji"]


class Controller:
    def __init__(self, app: QApplication, root=None):
        self.app = app
        self.accounts = AccountManager(root)
        self.config_path = self.accounts.root / "config.json"
        self.config = self._load_config()
        self.events = EventBus()
        self.api = PluginAPI(self)
        self.ctx = None
        self.window = None
        self.login = None
        register_builtin_blocks()
        self.user_plugin_dir = self.accounts.root / "plugins"
        self.user_plugin_dir.mkdir(exist_ok=True)
        self.plugin_infos = load_plugins(self)
        self.apply_appearance()

    # --- config ----------------------------------------------------------------
    def _load_config(self) -> dict:
        try:
            return json.loads(self.config_path.read_text())
        except (OSError, ValueError):
            return {"theme": "dark", "font_size": 14}

    def save_config(self):
        tmp = self.config_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.config, indent=2))
        os.replace(tmp, self.config_path)

    def apply_appearance(self):
        theme.set_theme(self.config.get("theme", "dark"))
        f = QFont()
        f.setFamilies(FONT_FAMILIES)
        f.setPixelSize(int(self.config.get("font_size", 14)))
        self.app.setFont(f)
        self.app.setStyleSheet(theme.stylesheet().replace("font-size: 14px", f"font-size: {f.pixelSize()}px", 1))

    def set_theme(self, name: str):
        self.config["theme"] = name
        self.save_config()
        self.apply_appearance()
        if self.window:
            self.window.apply_theme()
        self.events.emit("theme_changed", name)

    # --- session lifecycle -------------------------------------------------------------
    def start(self):
        self.show_login()

    def show_login(self):
        if self.login is None:
            self.login = LoginWindow(self)
        self.login.refresh()
        self.login.show()
        self.login.raise_()
        self.login.activateWindow()

    def on_unlocked(self, account, store, first_run=False):
        from .ui.main_window import MainWindow
        repo = Repo(store)
        if not repo.list_pages() and not repo.get_setting("welcome_done"):
            create_welcome_pages(repo, account)
            repo.set_setting("welcome_done", True)
        self.ctx = SimpleNamespace(controller=self, account=account, store=store, repo=repo,
                                   events=self.events, api=self.api, window=None)
        self.config["last_user"] = account.username
        self.save_config()
        self.window = MainWindow(self.ctx)
        self.window.show()
        if self.login:
            self.login.hide()
        self.events.emit("app_ready", self.window)
        if getattr(store, "recovered_from", None):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self.window, "Recovered your notes",
                f"The main notes file was missing or damaged (probably a crash or power loss during a save), "
                f"so your notes were opened from {store.recovered_from}. Anything typed in the last few seconds "
                f"before the crash may be missing. The next save repairs the main file.")

    def _end_session(self):
        if not self.window:
            return
        self.events.emit("locking")
        w = self.window
        w.locking = True
        w.shutdown()
        self.ctx.store.close()
        self.window = None
        self.ctx = None
        w.close()
        w.deleteLater()

    def lock(self):
        self.show_login()
        self._end_session()

    def quit_from_window(self):
        self._end_session()
        self.app.quit()


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    argv = argv if argv is not None else sys.argv
    if sys.version_info < (3, 11):
        sys.exit("Securewrity needs Python 3.11 or newer.")
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(QIcon.fromTheme("accessories-text-editor"))
    controller = Controller(app)
    controller.start()
    app.aboutToQuit.connect(controller._end_session)
    return app.exec()
