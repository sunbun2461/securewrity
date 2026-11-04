"""Convert between stored rich-text runs and a QTextDocument."""
from __future__ import annotations

from PyQt6.QtGui import QBrush, QColor, QTextCharFormat, QTextCursor, QTextFormat

from .. import theme

_UP = int(QTextFormat.Property.UserProperty.value)
P_COLOR, P_BG, P_CODE = _UP + 1, _UP + 2, _UP + 3
MONO = "Monospace"
ATTRS = ("b", "i", "u", "s", "code", "c", "bg", "link")


def make_format(run: dict) -> QTextCharFormat:
    """Build a *fresh* format: only properties the run actually has are set, so
    everything else is inherited from the block (e.g. a heading's bold font)."""
    f = QTextCharFormat()
    if run.get("b"):
        f.setFontWeight(700)
    if run.get("i"):
        f.setFontItalic(True)
    if run.get("s"):
        f.setFontStrikeOut(True)
    if run.get("u") or run.get("link"):
        f.setFontUnderline(True)
    if run.get("c"):
        f.setProperty(P_COLOR, run["c"])
        f.setForeground(QBrush(QColor(theme.text_color(run["c"]))))
    elif run.get("link"):
        f.setForeground(QBrush(QColor(theme.t("link"))))
    if run.get("bg"):
        f.setProperty(P_BG, run["bg"])
        f.setBackground(QBrush(QColor(theme.bg_color(run["bg"]) or theme.t("hover"))))
        if not run.get("c") and not run.get("link") and not run.get("code"):
            ink = theme.readable_text(None, run["bg"])
            if ink != theme.t("text"):
                f.setForeground(QBrush(QColor(ink)))
    if run.get("code"):
        f.setProperty(P_CODE, True)
        f.setFontFamilies([MONO])
        if not run.get("bg"):
            f.setBackground(QBrush(QColor(theme.t("code_bg"))))
        if not run.get("c"):
            f.setForeground(QBrush(QColor(theme.text_color("red"))))
    if run.get("link"):
        f.setAnchor(True)
        f.setAnchorHref(run["link"])
    return f


def transform_selection(cursor: QTextCursor, fn) -> None:
    """Apply fn(run) -> run to every formatted piece inside the selection.
    Re-creates formats from scratch, so attributes can be removed cleanly."""
    if not cursor.hasSelection():
        return
    doc = cursor.document()
    start, end = cursor.selectionStart(), cursor.selectionEnd()
    pieces = []
    block = doc.findBlock(start)
    while block.isValid() and block.position() < end:
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            fs, fe = frag.position(), frag.position() + frag.length()
            s, e = max(fs, start), min(fe, end)
            if s < e:
                pieces.append((s, e, run_from_format("", frag.charFormat())))
            it += 1
        block = block.next()
    c = QTextCursor(doc)
    c.beginEditBlock()
    for s, e, run in pieces:
        c.setPosition(s)
        c.setPosition(e, QTextCursor.MoveMode.KeepAnchor)
        c.setCharFormat(make_format(fn(dict(run))))
    c.endEditBlock()


def selection_runs(cursor: QTextCursor) -> list[dict]:
    """Formats inside the selection (text omitted) — used to decide toggles."""
    out = []
    if not cursor.hasSelection():
        return [run_from_format("", cursor.charFormat())]
    doc = cursor.document()
    start, end = cursor.selectionStart(), cursor.selectionEnd()
    block = doc.findBlock(start)
    while block.isValid() and block.position() < end:
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if max(frag.position(), start) < min(frag.position() + frag.length(), end):
                out.append(run_from_format("", frag.charFormat()))
            it += 1
        block = block.next()
    return out or [{}]


def run_from_format(text: str, f: QTextCharFormat) -> dict:
    r = {"t": text}
    if f.fontWeight() >= 600:
        r["b"] = 1
    if f.fontItalic():
        r["i"] = 1
    if f.fontStrikeOut():
        r["s"] = 1
    href = f.anchorHref() if f.isAnchor() else ""
    if href:
        r["link"] = href
    elif f.fontUnderline():
        r["u"] = 1
    if f.property(P_CODE):
        r["code"] = 1
    c = f.property(P_COLOR)
    if c:
        r["c"] = c
    bg = f.property(P_BG)
    if bg:
        r["bg"] = bg
    return r


def _same(a: dict, b: dict) -> bool:
    return all(a.get(k) == b.get(k) for k in ATTRS)


def merge_runs(runs: list[dict]) -> list[dict]:
    out: list[dict] = []
    for r in runs:
        if not r.get("t"):
            continue
        if out and _same(out[-1], r):
            out[-1] = dict(out[-1], t=out[-1]["t"] + r["t"])
        else:
            out.append(dict(r))
    return out


def runs_from_document(doc) -> list[dict]:
    runs = []
    block = doc.begin()
    first = True
    while block.isValid():
        if not first:
            runs.append({"t": "\n"})
        first = False
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                runs.append(run_from_format(frag.text().replace(" ", "\n"), frag.charFormat()))
            it += 1
        block = block.next()
    # newline runs are unformatted; attach them to neighbours when merging
    return merge_runs(runs)


def load_runs(doc, runs: list[dict], plain: bool = False) -> None:
    doc.clear()
    cur = QTextCursor(doc)
    for r in runs or []:
        cur.insertText(r.get("t", ""), QTextCharFormat() if plain else make_format(r))


def plain_text(runs: list[dict]) -> str:
    return "".join(r.get("t", "") for r in runs or [])


def split_runs(runs: list[dict], offset: int) -> tuple[list[dict], list[dict]]:
    left, right, pos = [], [], 0
    for r in runs:
        t = r.get("t", "")
        if pos + len(t) <= offset:
            left.append(r)
        elif pos >= offset:
            right.append(r)
        else:
            k = offset - pos
            left.append(dict(r, t=t[:k]))
            right.append(dict(r, t=t[k:]))
        pos += len(t)
    return merge_runs(left), merge_runs(right)
