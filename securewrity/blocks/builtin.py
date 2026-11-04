"""Built-in block types. Plugins can add more the same way."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QToolButton

from ..ui import theme
from .registry import BlockType, registry

PREFIX_W = 24
HEADING_PX = (30, 24, 19, 16)
MAX_HEADING = 4


def _line_h(bt: BlockType) -> int:
    return int(bt.font_px * 1.55) + 2


class _PrefixLabel(QLabel):
    def __init__(self, text, bt, bw=None):
        super().__init__(text)
        self.setFixedSize(PREFIX_W, _line_h(bt))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bw = bw

    def mousePressEvent(self, e):
        if self.bw is not None and self.bw.text:
            self.bw.editor.focus_block(self.bw, "start")


# --- text ----------------------------------------------------------------------
class Paragraph(BlockType):
    key, label, icon = "paragraph", "Text", "¶"
    description = "Just start writing with plain text."
    aliases = ("text", "plain", "paragraph")
    placeholder = "Type '/' for commands"

    def to_markdown(self, text, block, depth, number=1):
        return text


class Heading(BlockType):
    group = "Headings"

    def __init__(self, level: int):
        self.level = level
        self.key = f"h{level}"
        self.label = f"Heading {level}"
        self.icon = f"H{level}"
        self.description = ("Big", "Medium", "Small", "Smallest")[level - 1] + " section heading."
        self.aliases = (f"h{level}", "heading", "title")
        self.markdown = ("#" * level,)
        self.font_px = HEADING_PX[level - 1]
        self.bold = True
        self.top_margin = (18, 14, 8, 6)[level - 1]
        self.placeholder = f"Heading {level}"
        self.can_have_children = False

    def to_markdown(self, text, block, depth, number=1):
        return "#" * self.level + " " + text


class _ToggleArrow(QToolButton):
    def __init__(self, bw, bt):
        super().__init__()
        self.bw = bw
        self.setFixedSize(PREFIX_W, _line_h(bt))
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QToolButton{padding:0;font-size:%dpx;}" % max(12, int(bt.font_px * 0.6)))
        self.clicked.connect(bw.toggle_collapsed)
        self.update_state()

    def update_state(self):
        self.setText("▶" if self.bw.is_collapsed() else "▼")


class Toggle(BlockType):
    key, label, icon = "toggle", "Toggle", "▸"
    description = "Regular-size text with an arrow that hides what's inside."
    aliases = ("toggle", "toggle text", "toggle list", "collapse", "dropdown", "details")
    markdown = (">",)
    toggle = True
    continues = True
    placeholder = "Toggle"

    def default_props(self):
        return {"collapsed": False}

    def make_prefix(self, bw):
        return _ToggleArrow(bw, self)

    def refresh(self, bw):
        if bw.prefix:
            bw.prefix.update_state()

    def to_markdown(self, text, block, depth, number=1):
        return "<details><summary>" + text + "</summary>"


class ToggleHeading(Toggle):
    group = "Headings"
    continues = False

    def __init__(self, level: int):
        h = Heading(level)
        self.level = level
        self.key = f"toggle_h{level}"
        self.label = f"Toggle heading {level}"
        self.icon = f"▸{level}"
        self.description = f"Heading {level} with an arrow that hides what's inside."
        self.aliases = (f"toggle h{level}", f"th{level}", "toggle heading", "collapsible heading")
        self.markdown = ("#" * level + ">", ">" + "#" * level)
        self.font_px, self.bold, self.top_margin = h.font_px, True, h.top_margin
        self.placeholder = f"Toggle heading {level}"

    def to_markdown(self, text, block, depth, number=1):
        return "#" * self.level + " " + text


# --- lists ---------------------------------------------------------------------
class Bullet(BlockType):
    key, label, icon = "bullet", "Bulleted list", "•"
    description = "Create a simple bulleted list."
    aliases = ("bullet", "ul", "list", "unordered")
    markdown = ("-", "*", "+")
    continues = True
    placeholder = "List"
    GLYPHS = ("•", "◦", "▪")

    def make_prefix(self, bw):
        lab = _PrefixLabel("•", self, bw)
        lab.setStyleSheet("font-size: 18px;")
        return lab

    def refresh(self, bw):
        depth = sum(1 for _ in bw.ancestors() if _.type_key == "bullet")
        bw.prefix.setText(self.GLYPHS[depth % 3])

    def to_markdown(self, text, block, depth, number=1):
        return "- " + text


class Numbered(BlockType):
    key, label, icon = "numbered", "Numbered list", "1."
    description = "Create a list with numbering."
    aliases = ("numbered", "ol", "ordered", "number")
    markdown = ("1.",)
    continues = True
    placeholder = "List"

    def make_prefix(self, bw):
        return _PrefixLabel("1.", self, bw)

    def to_markdown(self, text, block, depth, number=1):
        return f"{number}. " + text


class Todo(BlockType):
    key, label, icon = "todo", "To-do list", "☐"
    description = "Track tasks with a to-do list."
    aliases = ("todo", "task", "checkbox", "check")
    markdown = ("[]", "[ ]")
    continues = True
    placeholder = "To-do"

    def default_props(self):
        return {"checked": False}

    def make_prefix(self, bw):
        box = QCheckBox()
        box.setFixedSize(PREFIX_W, _line_h(self))
        box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        box.setChecked(bool(bw.props.get("checked")))
        box.toggled.connect(lambda v: bw.set_prop("checked", v))
        return box

    def refresh(self, bw):
        bw.prefix.blockSignals(True)
        bw.prefix.setChecked(bool(bw.props.get("checked")))
        bw.prefix.blockSignals(False)

    def to_markdown(self, text, block, depth, number=1):
        return ("- [x] " if block.get("props", {}).get("checked") else "- [ ] ") + text


# --- other text blocks --------------------------------------------------------------
class Quote(BlockType):
    key, label, icon = "quote", "Quote", "❝"
    description = "Capture a quote."
    aliases = ("quote", "blockquote", "citation")
    markdown = ('"', "|")
    font_px = 16
    placeholder = "Empty quote"

    def row_css(self, bw):
        return f"border-left: 3px solid {theme.text_color(bw.props.get('color'))}; border-radius: 0; padding-left: 8px;"

    def to_markdown(self, text, block, depth, number=1):
        return "> " + text.replace("\n", "\n> ")


class _EmojiButton(QToolButton):
    def __init__(self, bw, bt):
        super().__init__()
        self.bw = bw
        self.setFixedSize(PREFIX_W + 6, _line_h(bt) + 4)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setText(bw.props.get("emoji") or "💡")
        self.setStyleSheet("QToolButton{font-size:18px;padding:0;}")
        self.clicked.connect(self._pick)

    def _pick(self):
        from ..ui.editor.popups import EmojiPicker
        e = EmojiPicker.pick(self, allow_remove=False)
        if e:
            self.bw.set_prop("emoji", e)
            self.setText(e)


class Callout(BlockType):
    key, label, icon = "callout", "Callout", "💡"
    description = "Make writing stand out."
    aliases = ("callout", "note", "info", "warning", "tip")
    placeholder = "Callout"

    def default_props(self):
        return {"emoji": "💡"}

    def make_prefix(self, bw):
        return _EmojiButton(bw, self)

    def row_css(self, bw):
        bg = theme.bg_color(bw.props.get("bg")) or theme.t("hover")
        return f"background: {bg}; border-radius: 6px; padding: 8px 6px;"

    def to_markdown(self, text, block, depth, number=1):
        return f"> {block.get('props', {}).get('emoji', '💡')} " + text.replace("\n", "\n> ")


class Code(BlockType):
    key, label, icon = "code", "Code", "</>"
    description = "Capture a code snippet."
    aliases = ("code", "snippet", "pre", "script")
    markdown = ("```",)
    rich = False
    monospace = True
    font_px = 13
    can_have_children = False
    placeholder = "Code"

    def row_css(self, bw):
        return f"background: {theme.t('code_bg')}; border-radius: 6px; padding: 10px 4px;"

    def to_markdown(self, text, block, depth, number=1):
        return f"```{block.get('props', {}).get('language', '')}\n{text}\n```"


# --- non-text blocks ----------------------------------------------------------------
class Divider(BlockType):
    key, label, icon = "divider", "Divider", "—"
    description = "Visually divide blocks."
    aliases = ("divider", "hr", "line", "separator")
    markdown = ("---",)
    has_text = False
    can_have_children = False

    def make_body(self, bw):
        from ..ui.editor.block_widget import NonTextBody
        body = NonTextBody(bw)
        lay = QHBoxLayout(body)
        lay.setContentsMargins(0, 10, 0, 10)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {theme.t('border')};")
        lay.addWidget(line)
        return body

    def to_markdown(self, text, block, depth, number=1):
        return "---"


class _PageLinkBody:
    """Shared body for sub-page and link-to-page blocks."""

    @staticmethod
    def build(bw, arrow: bool):
        from ..ui.editor.block_widget import NonTextBody
        body = NonTextBody(bw, clickable=True)
        lay = QHBoxLayout(body)
        lay.setContentsMargins(2, 3, 2, 3)
        lab = QLabel()
        lab.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(lab)
        lay.addStretch(1)
        body.label = lab

        def refresh():
            pid = bw.props.get("page_id")
            page = bw.editor.ctx.repo.get_page(pid) if pid else None
            if not page or page["trashed"]:
                lab.setText(f"<span style='color:{theme.t('muted')}'>📄 <s>Deleted page</s></span>")
                return
            title = page["title"] or "Untitled"
            from html import escape
            icon = page["icon"] or "📄"
            pre = "↗ " if arrow else ""
            lab.setText(f"{icon} {pre}<span style='text-decoration:underline; "
                        f"color:{theme.text_color(bw.props.get('color'))}; font-weight:500'>{escape(title)}</span>")

        body.refresh = refresh
        body.activated.connect(lambda: bw.props.get("page_id") and bw.editor.open_page(bw.props["page_id"]))
        refresh()
        return body


class PageBlock(BlockType):
    key, label, icon = "page", "Page", "📄"
    description = "Embed a sub-page inside this page."
    aliases = ("page", "subpage", "sub-page", "new page")
    has_text = False
    can_have_children = False

    def make_body(self, bw):
        return _PageLinkBody.build(bw, arrow=False)

    def refresh(self, bw):
        bw.body.refresh()

    def to_markdown(self, text, block, depth, number=1):
        return f"[📄 sub-page](page:{block.get('props', {}).get('page_id', '')})"


class LinkToPage(PageBlock):
    key, label, icon = "link_to_page", "Link to page", "↗"
    description = "Link to an existing page."
    aliases = ("link", "link to page", "mention", "reference")

    def make_body(self, bw):
        return _PageLinkBody.build(bw, arrow=True)

    def to_markdown(self, text, block, depth, number=1):
        return f"[↗ link](page:{block.get('props', {}).get('page_id', '')})"


def register_builtin_blocks() -> None:
    levels = range(1, MAX_HEADING + 1)
    for bt in (Paragraph(), Toggle(),
               *(Heading(n) for n in levels), *(ToggleHeading(n) for n in levels),
               Bullet(), Numbered(), Todo(), Quote(), Callout(), Code(), Divider(),
               PageBlock(), LinkToPage()):
        registry.register(bt)
