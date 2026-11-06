"""Turn Markdown text into Securewrity blocks.

Understands what people (and AIs asked for "Notion format") usually produce:

* Standard Markdown: # headings, - * + bullets, 1. lists, - [ ] to-dos, > quotes,
  ``` code fences, --- dividers, | tables |, **bold** *italic* ~~strike~~ `code`
  [links](url), nesting by indentation.
* Toggles: <details><summary>…</summary>…</details>, lines starting with ▶ / ▸,
  "▶ ## Heading" or "## ▶ Heading" (toggle heading), and the "#> " shortcut.
* Notion-flavoured Markdown: `## Heading {toggle="true" color="blue"}`,
  <callout icon="💡">…</callout>, <span color="red">…</span>, <empty-block/>,
  <aside>…</aside> (Notion's callout export), > [!NOTE] alerts.
* Some HTML: <b> <i> <u> <s> <code> <mark> <a href> <br>.

Output is the block tree used by Repo.save_blocks:
    {"type": str, "content": [runs], "props": {}, "children": [...]}
Pure Python, no Qt: safe to use from tests and plugins.
"""
from __future__ import annotations

import re

from ..ui import theme

TOGGLE_GLYPHS = "▶▸►▷⏵▼▾"
MAX_HEADING = 4
TOGGLE_RANK = MAX_HEADING + 1  # a plain toggle ranks below every heading when deciding what nests

# --- colors -------------------------------------------------------------------------------


def color_name(value: str | None) -> tuple[str | None, bool]:
    """'red' -> ('red', False); 'blue_background' / 'blue_bg' -> ('blue', True);
    'pastel mint' -> ('mint', False). Unknown -> (None, False)."""
    if not value:
        return None, False
    v = value.strip().strip("'\"").lower().replace("-", " ").replace("_", " ")
    bg = False
    for suffix in (" background", " bg"):
        if v.endswith(suffix):
            v, bg = v[: -len(suffix)].strip(), True
    if v.startswith("pastel "):
        v = v[7:].strip()
    v = {"grey": "gray", "violet": "purple", "cyan": "teal"}.get(v, v)
    if v in theme.COLOR_NAMES and v != "default":
        return v, bg
    return None, False


def _attrs(s: str) -> dict:
    return {k.lower(): v for k, v in re.findall(r'([\w-]+)\s*=\s*"([^"]*)"', s)}


# --- inline -------------------------------------------------------------------------------

_ESC = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|~>=<])")
_PRIV = 0xE000  # escaped characters are parked in the private-use area while parsing

_INLINE = re.compile(
    r"(?P<code>(`+)(?P<code_t>.+?)\2)"
    r"|(?P<img>!\[(?P<img_alt>[^\]]*)\]\((?P<img_url>[^)\s]+)[^)]*\))"
    r"|(?P<link>\[(?P<link_t>[^\]]+)\]\((?P<link_url>[^)\s]+)(?:\s+\"[^\"]*\")?\))"
    r"|(?P<bold>\*\*(?P<bold_t>.+?)\*\*|__(?P<bold_t2>.+?)__)"
    r"|(?P<strike>~~(?P<strike_t>.+?)~~)"
    r"|(?P<mark>==(?P<mark_t>[^=].*?)==)"
    r"|(?P<ital>\*(?P<ital_t>[^\s*](?:.*?[^\s*])?)\*|(?<![\w])_(?P<ital_t2>[^\s_](?:.*?[^\s_])?)_(?![\w]))"
    r"|(?P<html><(?P<tag>b|strong|i|em|u|s|del|strike|code|mark)>(?P<html_t>.*?)</(?P=tag)>)"
    r"|(?P<span><span\b(?P<span_a>[^>]*)>(?P<span_t>.*?)</span>)"
    r"|(?P<a><a\s[^>]*href=\"(?P<a_url>[^\"]+)\"[^>]*>(?P<a_t>.*?)</a>)"
    r"|(?P<mention><mention-(?:page|database|user|date)\b[^>]*?(?:/>|>(?P<mention_t>.*?)</mention-\w+>))"
    r"|(?P<auto><(?P<auto_url>https?://[^>\s]+)>)"
    r"|(?P<url>(?<![\w(\"'])https?://[^\s<>()]+[^\s<>().,;:!?'\"])",
    re.S,
)


def _clean(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</?(?!span|a\b|b>|strong|i>|em>|u>|s>|del|strike|code|mark|mention)[a-zA-Z][^>]*>", "", text)
    return text


def _unescape(text: str) -> str:
    out = []
    for ch in text:
        o = ord(ch)
        out.append(chr(o - _PRIV) if _PRIV <= o < _PRIV + 128 else ch)
    import html
    return html.unescape("".join(out))


def parse_inline(text: str) -> list[dict]:
    """Markdown/HTML inline text -> runs [{'t': ..., 'b': 1, 'c': 'red', ...}]."""
    text = _ESC.sub(lambda m: chr(_PRIV + ord(m.group(1))) if ord(m.group(1)) < 128 else m.group(1), text)
    runs = _inline(_clean(text), {})
    # merge neighbours with identical style, drop empties
    out: list[dict] = []
    for r in runs:
        r["t"] = _unescape(r["t"])
        if not r["t"]:
            continue
        if out and {k: v for k, v in out[-1].items() if k != "t"} == {k: v for k, v in r.items() if k != "t"}:
            out[-1]["t"] += r["t"]
        else:
            out.append(r)
    return out


def _inline(text: str, style: dict) -> list[dict]:
    runs, pos = [], 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            runs.append({"t": text[pos:m.start()], **style})
        pos = m.end()
        g = m.group
        if g("code"):
            runs.append({"t": g("code_t").strip(" ") or g("code_t"), **style, "code": 1})
        elif g("img"):
            runs.append({"t": "🖼 " + (g("img_alt") or "image"), **style, "link": g("img_url"), "img": 1})
        elif g("link"):
            runs += _inline(g("link_t"), {**style, "link": g("link_url")})
        elif g("bold"):
            runs += _inline(g("bold_t") or g("bold_t2"), {**style, "b": 1})
        elif g("strike"):
            runs += _inline(g("strike_t"), {**style, "s": 1})
        elif g("mark"):
            runs += _inline(g("mark_t"), {**style, "bg": "yellow"})
        elif g("ital"):
            runs += _inline(g("ital_t") or g("ital_t2"), {**style, "i": 1})
        elif g("html"):
            key = {"b": "b", "strong": "b", "i": "i", "em": "i", "u": "u", "s": "s", "del": "s",
                   "strike": "s", "code": "code", "mark": "bg"}[g("tag").lower()]
            runs += _inline(g("html_t"), {**style, key: "yellow" if key == "bg" else 1})
        elif g("span"):
            runs += _inline(g("span_t"), {**style, **_span_style(g("span_a"))})
        elif g("a"):
            runs += _inline(g("a_t"), {**style, "link": g("a_url")})
        elif g("mention"):
            t = g("mention_t") or ""
            if t:
                runs += _inline(t, style)
        elif g("auto"):
            runs.append({"t": g("auto_url"), **style, "link": g("auto_url")})
        elif g("url"):
            runs.append({"t": g("url"), **style, "link": g("url")})
    if pos < len(text):
        runs.append({"t": text[pos:], **style})
    return runs


def _span_style(attr_text: str) -> dict:
    st = {}
    a = _attrs(attr_text)
    if a.get("underline") == "true":
        st["u"] = 1
    name, bg = color_name(a.get("color"))
    if name:
        st["bg" if bg else "c"] = name
    css = a.get("style", "")
    m = re.search(r"(?<![-\w])color\s*:\s*([^;]+)", css)
    if m:
        n, _ = color_name(m.group(1))
        if n:
            st["c"] = n
    m = re.search(r"background(?:-color)?\s*:\s*([^;]+)", css)
    if m:
        n, _ = color_name(m.group(1))
        if n:
            st["bg"] = n
    if re.search(r"font-weight\s*:\s*(bold|[6-9]00)", css):
        st["b"] = 1
    if re.search(r"font-style\s*:\s*italic", css):
        st["i"] = 1
    if "underline" in css:
        st["u"] = 1
    if "line-through" in css:
        st["s"] = 1
    return st


# --- blocks -------------------------------------------------------------------------------

def _block(type_, text="", props=None, runs=None):
    return {"type": type_, "content": runs if runs is not None else (parse_inline(text) if text else []),
            "props": dict(props or {}), "children": []}


_TRAIL_ATTRS = re.compile(r"\s*\{((?:\s*[\w-]+\s*=\s*\"[^\"]*\"\s*)+)\}\s*$")
_ALERTS = {"note": "💡", "tip": "💡", "important": "❗", "warning": "⚠️", "caution": "⚠️"}


def _apply_block_color(block, attrs):
    name, bg = color_name(attrs.get("color"))
    if name:
        block["props"]["bg" if bg else "color"] = name


def _indent_width(s: str) -> int:
    n = 0
    for ch in s:
        if ch == "\t":
            n += 4
        elif ch == " ":
            n += 1
        else:
            break
    return n


def _classify(line: str) -> tuple[dict, int | None]:
    """One stripped line -> (block, heading_level_if_toggle_heading)."""
    attrs = {}
    m = _TRAIL_ATTRS.search(line)
    if m:
        attrs = _attrs(m.group(1))
        line = line[: m.start()]
    toggle_attr = attrs.get("toggle") == "true"
    hlevel = None

    def heading(level, text, toggle):
        nonlocal hlevel
        level = max(1, min(level, MAX_HEADING))
        t = text.strip()
        if t[:1] and t[0] in TOGGLE_GLYPHS:
            toggle, t = True, t[1:].strip()
        if toggle:
            hlevel = level
            return _block(f"toggle_h{level}", t, {"collapsed": False})
        return _block(f"h{level}", t)

    if m2 := re.match(r"^(#{1,6})>\s+(.*)$", line) or re.match(r"^>(#{1,6})\s+(.*)$", line):
        b = heading(len(m2.group(1)), m2.group(2), True)
    elif m2 := re.match(r"^(#{1,6})\s+(.*)$", line):
        b = heading(len(m2.group(1)), m2.group(2), toggle_attr)
    elif line[:1] in TOGGLE_GLYPHS and line[:1]:
        rest = line[1:].strip()
        if m2 := re.match(r"^(#{1,6})\s+(.*)$", rest):
            b = heading(len(m2.group(1)), m2.group(2), True)
        else:
            b = _block("toggle", rest, {"collapsed": False})
    elif m2 := re.match(r"^[-*+•]\s+\[([ xX✓✔]?)\]\s?(.*)$", line) or re.match(r"^\[([ xX✓✔]?)\]\s+(.*)$", line):
        b = _block("todo", m2.group(2), {"checked": m2.group(1).strip() != ""})
    elif m2 := re.match(r"^[-*+•◦▪]\s+(.*)$", line):
        body = m2.group(1)
        if body[:1] in TOGGLE_GLYPHS and body[:1]:
            b = _block("toggle", body[1:].strip(), {"collapsed": False})
        else:
            b = _block("bullet", body)
    elif m2 := re.match(r"^\d+[.)]\s+(.*)$", line):
        b = _block("numbered", m2.group(1))
    elif re.match(r"^(-\s*){3,}$|^(\*\s*){3,}$|^(_\s*){3,}$", line):
        b = _block("divider")
    elif re.match(r"^<empty-block\s*/?>$", line):
        b = _block("paragraph")
    elif m2 := re.match(r"^<page\b[^>]*>(.*?)</page>$", line):
        b = _block("paragraph", "📄 " + m2.group(1))
    else:
        b = _block("paragraph", line)
    if toggle_attr and b["type"] in ("paragraph", "bullet"):
        b = {**b, "type": "toggle", "props": {"collapsed": False}}
    if b["type"] == "toggle":
        hlevel = TOGGLE_RANK
    _apply_block_color(b, attrs)
    return b, hlevel


def _clean_cell(c: str) -> str:
    c = _unescape(re.sub(r"<br\s*/?>", "\n", c, flags=re.I))
    c = re.sub(r"<[^>]+>", "", c)
    c = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", c)       # [text](link) → text
    return re.sub(r"\*\*|__|`|~~", "", c).strip()


def _table_block(rows: list[list[str]], header_row: bool = True) -> dict:
    """A real table block: props rows = list of rows of cell strings."""
    rows = [[_clean_cell(c) for c in r] for r in rows]
    rows = [r for r in rows if r]
    if not rows:
        return _block("paragraph")
    cols = max(len(r) for r in rows)
    rows = [r + [""] * (cols - len(r)) for r in rows]
    return {"type": "table", "content": [],
            "props": {"rows": rows, "header_row": bool(header_row and len(rows) > 1)}, "children": []}


_SEP_MD = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_SEP_ASCII = re.compile(r"^[-+ ]+$")


def table_from_text(text: str) -> dict | None:
    """Turn table text back into a table block: a Markdown pipe table, or the 'a | b' /
    '--+--' text older versions of Securewrity made from tables. None if it isn't one."""
    lines = [l for l in text.replace("\r", "").split("\n") if l.strip()]
    if len(lines) < 2 or not all("|" in l or _SEP_ASCII.match(l) for l in lines):
        return None
    rows, header = [], False
    for n, l in enumerate(lines):
        if _SEP_MD.match(l) or ("-" in l and _SEP_ASCII.match(l)):
            header = header or n == 1
            continue
        t = l.strip()
        if t.startswith("|") and t.endswith("|") and len(t) > 1:
            t = t[1:-1]
        rows.append(t.split("|"))
    if len(rows) < 1 or max(len(r) for r in rows) < 2:
        return None
    return _table_block(rows, header_row=header)


def parse_markdown(text: str) -> list[dict]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    # put HTML container tags on their own lines so the line loop can see them
    text = re.sub(r"(<details\b[^>]*>)\s*(<summary>)", r"\1\n\2", text, flags=re.I)
    text = re.sub(r"(</summary>)[ \t]*(\S)", r"\1\n\2", text, flags=re.I)
    lines = text.split("\n")

    roots: list[dict] = []
    # stack entries: {"indent", "block", "sticky" (closed only by a tag), "hlevel", "scope"}
    stack: list[dict] = []

    def attach(block, indent, *, hlevel=None, scope=False, sticky=None):
        # close containers this block doesn't belong to
        while stack:
            top = stack[-1]
            if top["sticky"]:
                break
            if top["hlevel"] and top["scope"] and indent == top["indent"]:
                # an un-indented toggle takes the lines below it only up to the next heading or toggle
                if _heading_level(block) is not None:
                    stack.pop()
                    continue
                break
            if top["indent"] >= indent:
                stack.pop()
                continue
            break
        parent = stack[-1]["block"] if stack else None
        (parent["children"] if parent else roots).append(block)
        if sticky or _can_hold(block):
            stack.append({"indent": indent, "block": block, "sticky": sticky, "hlevel": hlevel, "scope": scope})
        return block

    def close_sticky(tag):
        while stack:
            top = stack.pop()
            if top["sticky"] == tag:
                return

    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        indent = _indent_width(raw)
        i += 1
        if not line:
            continue
        # "last line of content</callout>": handle the content, then the closing tag
        if (m := re.match(r"^(.+?)\s*(</(?:callout|aside|details)>)$", line, re.I)) and not line.startswith("<"):
            lines.insert(i, " " * indent + m.group(2))
            line = m.group(1)

        # fenced code
        if m := re.match(r"^(```+|~~~+)\s*([\w+#.-]*)", line):
            fence, lang, body = m.group(1), m.group(2), []
            while i < len(lines) and not lines[i].strip().startswith(fence):
                body.append(lines[i][min(_indent_width(raw), _indent_width(lines[i])):] if lines[i].strip() else "")
                i += 1
            i += 1  # closing fence
            b = {"type": "code", "content": [{"t": "\n".join(body)}] if body else [],
                 "props": {"language": lang} if lang else {}, "children": []}
            attach(b, indent)
            continue

        # pipe tables
        if line.startswith("|") and line.count("|") >= 2:
            rows = []
            j = i - 1
            while j < len(lines) and lines[j].strip().startswith("|"):
                cells = [c for c in lines[j].strip().strip("|").split("|")]
                if not all(re.match(r"^\s*:?-{2,}:?\s*$", c) for c in cells):
                    rows.append(cells)
                j += 1
            i = j
            attach(_table_block(rows), indent)
            continue

        # HTML tables (Notion-flavoured <table>)
        if re.match(r"^<table\b", line, re.I):
            chunk = [line]
            while i < len(lines) and "</table>" not in chunk[-1].lower():
                chunk.append(lines[i])
                i += 1
            html = "\n".join(chunk)
            rows = [re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)
                    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I)]
            attach(_table_block(rows), indent)
            continue

        # <details> toggles
        if m := re.match(r"^<details\b([^>]*)>$", line, re.I):
            b = _block("toggle", "", {"collapsed": False})
            _apply_block_color(b, _attrs(m.group(1)))
            attach(b, indent, sticky="details")
            continue
        if m := re.match(r"^<summary>(.*?)</summary>$", line, re.I):
            target = next((s["block"] for s in reversed(stack) if s["sticky"] == "details"), None)
            if target is not None:
                summary = m.group(1).strip()
                if hm := re.match(r"^(#{1,6})\s+(.*)$", summary):
                    target["type"] = f"toggle_h{min(len(hm.group(1)), MAX_HEADING)}"
                    summary = hm.group(2)
                elif hm := re.match(r"^<h([1-6])>(.*)</h\1>$", summary, re.I):
                    target["type"] = f"toggle_h{min(int(hm.group(1)), MAX_HEADING)}"
                    summary = hm.group(2)
                target["content"] = parse_inline(summary)
                continue
        if re.match(r"^</details>$", line, re.I):
            close_sticky("details")
            continue

        # callouts: <callout icon="💡">text</callout>, <aside>…</aside>
        if m := re.match(r"^<(callout|aside)\b([^>]*)>(.*)$", line, re.I):
            tag, attrs, rest = m.group(1).lower(), _attrs(m.group(2)), m.group(3)
            single = re.search(rf"</{tag}>\s*$", rest, re.I)
            if single:
                rest = rest[: single.start()]
            emoji = attrs.get("icon") or ""
            rest = rest.strip()
            if not emoji and rest and not rest[0].isalnum() and not rest[0] in "*_[<`~":
                emoji, rest = rest.split(" ", 1)[0], (rest.split(" ", 1)[1] if " " in rest else "")
            b = _block("callout", rest, {"emoji": emoji or "💡"})
            _apply_block_color(b, attrs)
            if single:
                attach(b, indent)
            else:
                attach(b, indent, sticky=tag)
                stack[-1]["first"] = not rest
            continue
        if m := re.match(r"^</(callout|aside)>$", line, re.I):
            close_sticky(m.group(1).lower())
            continue
        top = stack[-1] if stack else None
        if top and top["sticky"] in ("callout", "aside") and top.get("first"):
            # first text line inside a multi-line callout becomes the callout's text
            top["first"] = False
            first, _, rest = line.partition(" ")
            if first and not first[0].isascii() and not first[0].isalnum() and len(first) <= 4:
                top["block"]["props"]["emoji"] = first
                line = rest
            top["block"]["content"] = parse_inline(line)
            continue

        # quotes: consecutive "> " lines become one block; "> 💡 …" and "> [!NOTE]" become callouts
        if line.startswith(">") and not re.match(r"^>#{1,6}\s", line):
            body = [line[1:].lstrip()]
            while i < len(lines) and lines[i].strip().startswith(">") and not re.match(r"^>#{1,6}\s", lines[i].strip()):
                body.append(lines[i].strip()[1:].lstrip())
                i += 1
            first = body[0]
            if first[:1] and first[0] in TOGGLE_GLYPHS:
                tb, hl = _classify(first)
                attach(tb, indent, hlevel=hl, scope=True)
                for extra in body[1:]:
                    if extra.strip():
                        attach(_classify(extra)[0], indent + 1)
                continue
            if am := re.match(r"^\[!(\w+)\]\s*(.*)$", first):
                emoji = _ALERTS.get(am.group(1).lower(), "💡")
                rest = [am.group(2)] + body[1:]
                b = _block("callout", "\n".join(x for x in rest if x).strip(), {"emoji": emoji})
            elif first[:1] and not first[0].isascii() and not first[0].isalnum():
                emoji, _, rest = first.partition(" ")
                b = _block("callout", "\n".join([rest] + body[1:]).strip(), {"emoji": emoji})
            else:
                b = _block("quote", "\n".join(body).strip())
            attach(b, indent)
            continue

        block, hlevel = _classify(line)
        scope = False
        if hlevel:
            # a toggle (heading) followed by un-indented content: that content belongs inside it
            nxt = next((ln for ln in lines[i:] if ln.strip()), "")
            scope = _indent_width(nxt) <= _indent_width(raw)
        attach(block, indent, hlevel=hlevel, scope=scope)
    return roots


def _heading_level(block) -> int | None:
    """Rank used to end a toggle's scope: headings 1-4, then plain toggles."""
    t = block["type"]
    if re.match(r"^(toggle_)?h\d$", t):
        return int(t[-1])
    if t == "toggle":
        return TOGGLE_RANK
    return None


def _can_hold(block) -> bool:
    return block["type"] not in ("code", "divider", f"h1", "h2", "h3", "h4")


def looks_like_markdown(text: str, glyphs: bool = True) -> bool:
    """Does a pasted snippet use Markdown/Notion syntax worth converting?
    glyphs=False ignores lines that only start with a ▶ toggle arrow."""
    glyph = "|[▶▸►]\\s" if glyphs else ""
    if re.search(r"^\s*(#{1,6}>?\s|>#{1,6}\s|[-*+]\s|\d+[.)]\s|>\s?|```|---\s*$|\|.*\|\s*$" + glyph + ")",
                 text, re.M):
        return True
    if re.search(r"<(details|callout|aside|span|summary|empty-block)\b", text):
        return True
    return bool(re.search(r"\*\*[^*\n]+\*\*|__[^_\n]+__|~~[^~\n]+~~|`[^`\n]+`|\[[^\]\n]+\]\([^)\s]+\)", text))
