"""Regenerate the pictures used by the Help window (securewrity/data/help/*.png).

Runs the real app in a hidden (offscreen) window with a throwaway account,
recreates each situation and saves a cropped screenshot.

    python3 tools/help_screenshots.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="securewrity-shots-")
os.environ["SECUREWRITY_HOME"] = TMP
OUT = ROOT / "securewrity" / "data" / "help"
OUT.mkdir(parents=True, exist_ok=True)

from PyQt6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFrame, QVBoxLayout  # noqa: E402

from securewrity.app import Controller  # noqa: E402
from securewrity.core import crypto  # noqa: E402

crypto.DEFAULT_KDF = {"name": "scrypt", "n": 2 ** 12, "r": 8, "p": 1}

app = QApplication(sys.argv)
c = Controller(app)
c.start()
c.set_theme("dark")


def pump(n=3):
    for _ in range(n):
        app.processEvents()


def save(widget, name, rect: QRect | None = None):
    pm = widget.grab(rect) if rect is not None else widget.grab()
    pm.save(str(OUT / name))
    print("saved", name, pm.width(), "x", pm.height())


def region(host, *widgets, pad=10):
    """Bounding rectangle (in host coordinates) around several child widgets."""
    r = QRect()
    for w in widgets:
        tl = w.mapTo(host, QPoint(0, 0))
        r = r.united(QRect(tl, w.size()))
    return r.adjusted(-pad, -pad, pad, pad).intersected(host.rect())


# --- protection choice (before logging in) -------------------------------------------
from securewrity.ui.protection import ProtectionWizard  # noqa: E402

wiz = ProtectionWizard(None, mode="create")
wiz.resize(560, 520)
wiz.show()
pump()
save(wiz, "protect.png")
wiz.close()

acc, store = c.accounts.create_account("demo", [])
c.on_unlocked(acc, store, first_run=False)
w = c.window
w.resize(1180, 760)
w.show()
pump()
ed = w.editor
repo = c.ctx.repo


def fresh_page(title, blocks):
    pid = repo.create_page(None, title)
    repo.save_blocks(pid, blocks)
    repo.commit()
    w.open_page(pid)
    pump()
    return pid


def B(t, text="", children=(), **props):
    return {"type": t, "content": [{"t": text}] if text else [], "props": props, "children": list(children)}


# --- sidebar --------------------------------------------------------------------------
proj = repo.create_page(None, "Projects", icon="📁")
for title, icon in (("Kali lab notes", "🐧"), ("Reading list", "📚")):
    sub = repo.create_page(proj, title, icon=icon)
repo.create_page(sub, "Chapter notes")
journal = repo.create_page(None, "Journal", icon="📓")
repo.update_page(journal, favorite=1)
repo.commit()
w.sidebar.refresh()
for i in range(w.sidebar.tree.topLevelItemCount()):
    w.sidebar.tree.topLevelItem(i).setExpanded(True)
pump()

# --- toggles ----------------------------------------------------------------------------
fresh_page("Toggles", [
    B("toggle_h1", "Toggle heading 1 (open)", collapsed=False, children=[
        B("paragraph", "Everything indented under it folds away."),
        B("toggle_h2", "Toggle heading 2 (closed)", collapsed=True, children=[B("paragraph", "hidden")]),
        B("toggle", "A regular-size toggle (open)", collapsed=False, children=[
            B("bullet", "It can hold any block"),
            B("todo", "Even to-dos", checked=True),
        ]),
    ]),
    B("toggle_h3", "Toggle heading 3 (closed)", collapsed=True, children=[B("paragraph", "hidden")]),
    B("toggle_h4", "Toggle heading 4 (closed)", collapsed=True, children=[B("paragraph", "hidden")]),
])
save(w.sidebar, "sidebar.png")
first, last = ed.blocks[0], ed.blocks[-1]
save(ed, "toggles.png", region(ed, first, last, pad=14))

# --- slash menu --------------------------------------------------------------------------
fresh_page("Slash", [B("paragraph", "Type / on an empty line:"), B("paragraph")])
bw = ed.blocks[-1]
ed.focus_block(bw, "start")
pump()
QTest.keyClicks(bw.text, "/")
pump()
assert ed.slash.isVisible(), "slash menu did not open"
save(ed, "slash.png", region(ed, ed.blocks[0], ed.slash, pad=12))
QTest.keyClick(bw.text, Qt.Key.Key_Escape)
pump()

# --- selection toolbar ---------------------------------------------------------------------
fresh_page("Format", [B("paragraph"), B("paragraph"), B("paragraph"),
                      B("paragraph", "Select some words to format or color them.")])
bw = ed.blocks[3]
ed.focus_block(bw, "start")
pump()
cur = bw.text.textCursor()
cur.setPosition(7)
cur.setPosition(17, cur.MoveMode.KeepAnchor)
bw.text.setTextCursor(cur)
pump()
ed.update_inline_toolbar(bw)
pump()
assert ed.toolbar.isVisible(), "toolbar did not show"
save(ed, "toolbar.png", region(ed, bw, ed.toolbar, pad=12))

# --- color palette -------------------------------------------------------------------------
from securewrity.ui.editor.popups import ColorPalette  # noqa: E402

frame = QFrame()
frame.setObjectName("Popup")
frame.setStyleSheet(app.styleSheet())
QVBoxLayout(frame).addWidget(ColorPalette(lambda *a: None))
frame.adjustSize()
frame.show()
pump()
save(frame, "palette.png")
frame.close()

# --- block menu --------------------------------------------------------------------------------
from PyQt6.QtWidgets import QMenu  # noqa: E402

m = QMenu(w)
ed.build_block_menu(bw, m)
m.popup(w.mapToGlobal(QPoint(200, 200)))
pump()
save(m, "blockmenu.png")
m.close()

# --- link picker ----------------------------------------------------------------------------------
from securewrity.ui.dialogs import PageSearchDialog  # noqa: E402

d = PageSearchDialog(c.ctx, w, mode="link", initial="")
d.resize(520, 360)
d.show()
pump()
QTest.keyClicks(d.q, "no")
pump()
save(d, "link.png")
d.close()

w.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
print("done")
