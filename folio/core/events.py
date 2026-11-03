"""Tiny publish/subscribe event bus used by the app and by plugins.

Events emitted by the app (payload in parentheses):
    app_ready(window)              main window shown, plugins loaded
    page_opened(page_id)           a page was opened in the editor
    page_saved(page_id)            a page's blocks were written to storage
    page_created(page_id)
    page_deleted(page_id)
    pages_changed()                page tree changed (rename, move, trash ...)
    theme_changed(theme_name)
    locking()                      account is about to lock / close
"""
from __future__ import annotations

import logging
import traceback
from collections import defaultdict
from typing import Callable

log = logging.getLogger("folio.events")


class EventBus:
    def __init__(self):
        self._subs: dict[str, list[Callable]] = defaultdict(list)

    def on(self, event: str, fn: Callable) -> Callable:
        self._subs[event].append(fn)
        return fn

    def off(self, event: str, fn: Callable) -> None:
        if fn in self._subs.get(event, []):
            self._subs[event].remove(fn)

    def emit(self, event: str, *args, **kwargs) -> None:
        for fn in list(self._subs.get(event, [])):
            try:
                fn(*args, **kwargs)
            except Exception:  # a broken plugin must never crash the app
                log.error("Handler for %s failed:\n%s", event, traceback.format_exc())

    def clear(self) -> None:
        self._subs.clear()
