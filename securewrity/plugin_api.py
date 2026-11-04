"""Plugin API.

A plugin is a single .py file (or a package folder with __init__.py) placed in
    ~/.local/share/securewrity/plugins/        (your own plugins)
    securewrity/plugins/                       (bundled plugins)

It must define:

    PLUGIN = {"name": "My plugin", "version": "1.0", "description": "..."}

    def register(api):        # api is a PluginAPI
        api.add_command("Say hi", lambda: api.notify("hi!"), shortcut="Ctrl+Alt+H")
        api.events.on("page_saved", lambda page_id: ...)
        api.register_block_type(MyBlockType())

Everything a plugin may rely on lives on this class. Keep it backwards
compatible: add new methods rather than changing existing ones.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .blocks.registry import BlockType, registry

API_VERSION = 1
log = logging.getLogger("securewrity.plugins")


@dataclass
class Command:
    id: str
    label: str
    callback: Callable
    shortcut: str | None = None
    scope: str = "app"      # "app": callback()   "page": callback(page_id)


class PluginAPI:
    version = API_VERSION

    def __init__(self, controller):
        self._c = controller
        self.events = controller.events
        self.commands: list[Command] = []
        self.block_menu_items: list[tuple[str, Callable]] = []

    # --- state of the running app (None while locked) -----------------------------
    @property
    def repo(self):
        """Data access (securewrity.core.repo.Repo) for the unlocked account, or None."""
        return self._c.ctx.repo if self._c.ctx else None

    @property
    def window(self):
        return self._c.window

    @property
    def account(self):
        return self._c.ctx.account if self._c.ctx else None

    def current_page_id(self) -> str | None:
        w = self._c.window
        return w.editor.page_id if w else None

    def current_page_blocks(self) -> list[dict]:
        """Block tree of the open page, including unsaved edits."""
        w = self._c.window
        return w.editor.tree_data() if w and w.editor.page_id else []

    # --- extension points --------------------------------------------------------
    def register_block_type(self, block_type: BlockType) -> None:
        registry.register(block_type)

    def add_command(self, label: str, callback: Callable, shortcut: str | None = None,
                    scope: str = "app", id: str | None = None) -> Command:
        cmd = Command(id or label.lower().replace(" ", "_"), label, callback, shortcut, scope)
        self.commands.append(cmd)
        return cmd

    def add_page_command(self, label: str, callback: Callable[[str], None]) -> Command:
        """Shows up in the page '⋯' menu and the sidebar right-click menu."""
        return self.add_command(label, callback, scope="page")

    def add_block_menu_item(self, label: str, callback: Callable) -> None:
        """Adds an entry to every block's ⋮⋮ menu. callback(block_widget)."""
        self.block_menu_items.append((label, callback))

    def add_help_section(self, title: str, html: str, level: int = 1) -> None:
        """Adds a section to the Help window (F1). html may use simple tags: p, b, ul/li, table, code."""
        from .ui import help as help_ui
        sid = "plugin-" + "".join(ch if ch.isalnum() else "-" for ch in title.lower())
        help_ui.extra_sections[:] = [s for s in help_ui.extra_sections if s["id"] != sid]
        help_ui.extra_sections.append({"id": sid, "title": title, "level": level, "html": html})

    # --- helpers ----------------------------------------------------------------
    def open_page(self, page_id: str) -> None:
        if self._c.window:
            self._c.window.open_page(page_id)

    def create_page(self, title: str = "", parent_id: str | None = None,
                    blocks: list[dict] | None = None, open_it: bool = True) -> str | None:
        w = self._c.window
        if not w:
            return None
        pid = w.create_page(parent_id=parent_id, title=title, open_it=False)
        if blocks:
            w.ctx.repo.save_blocks(pid, blocks)
        if open_it:
            w.open_page(pid)
        return pid

    def notify(self, text: str) -> None:
        if self._c.window:
            self._c.window.notify(text)

    def set_status(self, key: str, text: str) -> None:
        """Small text in the editor's top bar (e.g. word count). Empty text removes it."""
        if self._c.window:
            self._c.window.editor.set_status(key, text)

    @property
    def data_dir(self) -> Path:
        d = self._c.accounts.root / "plugin-data"
        d.mkdir(exist_ok=True)
        return d


def load_plugins(controller) -> list[dict]:
    """Import every plugin and call register(api). Errors are recorded, not raised."""
    disabled = set(controller.config.get("disabled_plugins", []))
    sources = [("bundled", Path(__file__).resolve().parent / "plugins"),
               ("user", controller.user_plugin_dir)]
    infos = []
    for source, directory in sources:
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.name.startswith(("_", ".")):
                continue
            if path.is_dir() and (path / "__init__.py").exists():
                file = path / "__init__.py"
            elif path.suffix == ".py":
                file = path
            else:
                continue
            pid = f"{source}:{path.stem}"
            info = {"id": pid, "name": path.stem, "source": source, "loaded": False, "path": str(path)}
            infos.append(info)
            if pid in disabled:
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"securewrity_plugin_{source}_{path.stem}", file)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = mod
                spec.loader.exec_module(mod)
                meta = getattr(mod, "PLUGIN", {})
                info.update({k: meta[k] for k in ("name", "version", "description") if k in meta})
                if meta.get("api", API_VERSION) > API_VERSION:
                    raise RuntimeError(f"needs plugin API {meta['api']}, this Securewrity has {API_VERSION}")
                mod.register(controller.api)
                info["loaded"] = True
            except Exception as e:
                info["error"] = str(e)
                log.error("Plugin %s failed:\n%s", pid, traceback.format_exc())
    return infos
