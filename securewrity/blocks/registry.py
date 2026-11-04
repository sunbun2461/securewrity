"""Block type registry — the main extension point for new kinds of content.

To add a block type (in core or in a plugin), subclass BlockType and register it:

    class MyBlock(BlockType):
        key = "my_block"; label = "My block"; icon = "★"
    api.register_block_type(MyBlock())

The editor asks the block type for its prefix widget (bullet, checkbox, toggle
arrow ...), or for a full custom body widget when has_text is False. It shows
up automatically in the "/" menu and in "Turn into".
"""
from __future__ import annotations


class BlockType:
    key = "paragraph"
    label = "Text"
    description = ""
    icon = "¶"
    group = "Basic blocks"
    aliases: tuple[str, ...] = ()
    markdown: tuple[str, ...] = ()   # typing one of these then Space converts the block
    has_text = True                  # False => custom body via make_body()
    rich = True                      # inline formatting allowed
    toggle = False                   # has a collapse arrow that hides children
    continues = False                # Enter creates another block of this type
    can_have_children = True
    in_slash_menu = True
    font_px = 15
    bold = False
    italic = False
    monospace = False
    top_margin = 1
    placeholder = ""

    def default_props(self) -> dict:
        return {}

    # --- UI hooks (receive the BlockWidget) ---------------------------------
    def make_prefix(self, bw):
        """Return a QWidget shown left of the text (bullet, checkbox...) or None."""
        return None

    def make_body(self, bw):
        """For has_text=False: return the QWidget that forms the block's body."""
        return None

    def row_css(self, bw) -> str:
        """Extra stylesheet for the row frame (e.g. a quote's left border)."""
        return ""

    def refresh(self, bw) -> None:
        """Called after props or structure change (e.g. numbering, check state)."""

    # --- export -----------------------------------------------------------
    def to_markdown(self, text: str, block: dict, depth: int, number: int = 1) -> str:
        return text


class BlockRegistry:
    def __init__(self):
        self._types: dict[str, BlockType] = {}

    def register(self, bt: BlockType) -> None:
        self._types[bt.key] = bt

    def get(self, key: str) -> BlockType:
        return self._types.get(key) or self._types["paragraph"]

    def has(self, key: str) -> bool:
        return key in self._types

    def all(self) -> list[BlockType]:
        return list(self._types.values())

    def for_markdown(self, prefix: str) -> BlockType | None:
        for bt in self._types.values():
            if prefix in bt.markdown:
                return bt
        return None


registry = BlockRegistry()
