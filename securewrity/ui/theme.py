"""Themes and the Notion-style named color palette.

Blocks and inline text store color *names* ("red", "blue_bg", ...), never hex,
so switching between dark and light keeps everything readable.
"""
from __future__ import annotations

REGULAR_COLORS = ["gray", "brown", "orange", "yellow", "green", "teal", "blue", "purple", "pink", "red"]
PASTEL_COLORS = ["rose", "peach", "butter", "lime", "mint", "aqua", "sky", "periwinkle", "lavender", "coral"]
COLOR_NAMES = ["default"] + REGULAR_COLORS + PASTEL_COLORS


def color_label(name: str) -> str:
    """Human name for a stored color name: 'red' -> 'Red', 'mint' -> 'Pastel mint'."""
    if name in PASTEL_COLORS:
        return f"Pastel {name}"
    return name.capitalize()


#                regular colors: dark text, dark bg, light text, light bg
_REGULAR = {
    "gray":   ("#9B9B9B", "#2F2F2F", "#787774", "#F1F1EF"),
    "brown":  ("#BA856F", "#4A3228", "#9F6B53", "#F4EEEE"),
    "orange": ("#C77D48", "#5C3B23", "#D9730D", "#FBECDD"),
    "yellow": ("#CA9849", "#564328", "#CB912F", "#FBF3DB"),
    "green":  ("#529E72", "#243D30", "#448361", "#EDF3EC"),
    "teal":   ("#4AA3A0", "#1F4140", "#2E8A86", "#E4F3F2"),
    "blue":   ("#5E87C9", "#143A4E", "#337EA9", "#E7F3F8"),
    "purple": ("#9D68D3", "#3C2D49", "#9065B0", "#F4F0F7"),
    "pink":   ("#D15796", "#4E2C3C", "#C14C8A", "#F9EEF3"),
    "red":    ("#DF5452", "#522E2A", "#D44C47", "#FDEBEC"),
}
# pastels: soft and light on the dark theme; deeper text tones so they stay readable on white
_PASTEL = {
    "rose":       ("#F4B6C2", "#E8A3B1", "#D97A92", "#FDE2E8"),
    "peach":      ("#F8C8A8", "#EBB591", "#DB8B5C", "#FFE5D4"),
    "butter":     ("#F3E3A1", "#E6D48A", "#B89B2E", "#FFF6C7"),
    "lime":       ("#D4EDA0", "#C3DE8C", "#7FA33A", "#EEF8D5"),
    "mint":       ("#B5EAD7", "#9FD9C3", "#3FA37E", "#DDF5EA"),
    "aqua":       ("#A8E6E2", "#93D4CF", "#2E9E99", "#DAF4F2"),
    "sky":        ("#A9D3F5", "#93C0E6", "#4A90C8", "#DDEEFB"),
    "periwinkle": ("#B9C3F5", "#A6B0EA", "#6676D6", "#E2E6FC"),
    "lavender":   ("#D3BDF3", "#C0A8E6", "#9B7AD6", "#EDE3FB"),
    "coral":      ("#F7A8A0", "#EA958C", "#E0705F", "#FFDCD6"),
}
_ALL = {**_REGULAR, **_PASTEL}

THEMES = {
    "dark": {
        "bg": "#191919", "sidebar": "#202020", "text": "#D4D4D4", "muted": "#7F7F7F",
        "hover": "#2C2C2C", "selected": "#2F3437", "border": "#2F2F2F", "accent": "#2383E2",
        "code_bg": "#252525", "input": "#262626", "danger": "#E5534B", "link": "#9CC4F0",
        "text_colors": {k: v[0] for k, v in _ALL.items()},
        "bg_colors": {k: v[1] for k, v in _ALL.items()},
    },
    "light": {
        "bg": "#FFFFFF", "sidebar": "#F7F7F5", "text": "#37352F", "muted": "#91918E",
        "hover": "#EFEFED", "selected": "#E8E8E6", "border": "#E9E9E7", "accent": "#2383E2",
        "code_bg": "#F7F6F3", "input": "#FFFFFF", "danger": "#D44C47", "link": "#2069B0",
        "text_colors": {k: v[2] for k, v in _ALL.items()},
        "bg_colors": {k: v[3] for k, v in _ALL.items()},
    },
}

_current = "dark"


def set_theme(name: str) -> None:
    global _current
    _current = name if name in THEMES else "dark"


def name() -> str:
    return _current


def t(key: str) -> str:
    return THEMES[_current][key]


def text_color(name: str | None) -> str:
    if not name or name == "default":
        return t("text")
    return THEMES[_current]["text_colors"].get(name, t("text"))


def bg_color(name: str | None) -> str | None:
    if not name or name == "default":
        return None
    return THEMES[_current]["bg_colors"].get(name)


DARK_INK = "#1F1F1F"


def is_light(hex_color: str | None) -> bool:
    if not hex_color or not hex_color.startswith("#") or len(hex_color) != 7:
        return False
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return (0.299 * r + 0.587 * g + 0.114 * b) > 150


def readable_text(color: str | None, bg: str | None) -> str:
    """Text color for a block or run: the chosen color, else the theme text color,
    switched to dark ink when sitting on a light background (pastels on the dark theme)."""
    if color and color != "default":
        return text_color(color)
    if is_light(bg_color(bg)) and not is_light(t("bg")):
        return DARK_INK
    return t("text")


def stylesheet() -> str:
    c = THEMES[_current]
    return f"""
    QWidget {{ color: {c['text']}; font-size: 14px; }}
    QMainWindow, QDialog, #EditorRoot, #EditorCanvas, QScrollArea, #LoginRoot {{ background: {c['bg']}; }}
    #Sidebar, #Sidebar QTreeWidget {{ background: {c['sidebar']}; border: none; }}
    #Sidebar QTreeWidget::item {{ padding: 3px 2px; border-radius: 4px; }}
    #Sidebar QTreeWidget::item:hover {{ background: {c['hover']}; }}
    #Sidebar QTreeWidget::item:selected {{ background: {c['selected']}; color: {c['text']}; }}
    #SidebarHeader, #SectionLabel {{ color: {c['muted']}; font-size: 12px; font-weight: 600; }}
    QToolButton, QPushButton#Flat {{ background: transparent; border: none; border-radius: 4px; padding: 4px 6px; }}
    QToolButton:hover, QPushButton#Flat:hover {{ background: {c['hover']}; }}
    QToolButton#DragHandle {{ color: {c['muted']}; padding: 0; font-size: 11px; }}
    QPushButton#SideButton {{ text-align: left; background: transparent; border: none; border-radius: 4px;
        padding: 5px 8px; color: {c['muted']}; }}
    QPushButton#SideButton:hover {{ background: {c['hover']}; color: {c['text']}; }}
    QPushButton {{ background: {c['input']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 6px 14px; }}
    QPushButton:hover {{ background: {c['hover']}; }}
    QPushButton#Primary {{ background: {c['accent']}; color: white; border: none; }}
    QPushButton#Primary:hover {{ background: #1B6FC4; }}
    QPushButton#Primary:disabled {{ background: {c['border']}; color: {c['muted']}; }}
    QPushButton#Danger {{ color: {c['danger']}; }}
    QLineEdit, QPlainTextEdit#Input, QSpinBox, QComboBox {{ background: {c['input']}; border: 1px solid {c['border']};
        border-radius: 6px; padding: 6px 8px; selection-background-color: {c['accent']}; }}
    QLineEdit:focus, QPlainTextEdit#Input:focus {{ border: 1px solid {c['accent']}; }}
    QLineEdit#Title {{ background: transparent; border: none; font-size: 34px; font-weight: 700; padding: 0; }}
    QTextEdit#BlockText {{ background: transparent; border: none; selection-background-color: {c['accent']}; }}
    QListWidget {{ background: {c['input']}; border: 1px solid {c['border']}; border-radius: 6px; outline: none; }}
    QListWidget::item {{ padding: 6px; border-radius: 4px; }}
    QListWidget::item:selected {{ background: {c['selected']}; color: {c['text']}; }}
    QListWidget::item:hover {{ background: {c['hover']}; }}
    QMenu {{ background: {c['sidebar']}; border: 1px solid {c['border']}; padding: 4px; border-radius: 6px; }}
    QMenu::item {{ padding: 5px 24px 5px 10px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {c['hover']}; }}
    QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 6px; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; }}
    QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QSplitter::handle {{ background: {c['border']}; }}
    QLabel#Muted {{ color: {c['muted']}; }}
    QLabel#H1 {{ font-size: 26px; font-weight: 700; }}
    QLabel#Error {{ color: {c['danger']}; }}
    QFrame#Card {{ background: {c['sidebar']}; border: 1px solid {c['border']}; border-radius: 10px; }}
    QFrame#Popup {{ background: {c['sidebar']}; border: 1px solid {c['border']}; border-radius: 8px; }}
    QCheckBox, QRadioButton {{ spacing: 8px; }}
    QToolTip {{ background: {c['sidebar']}; color: {c['text']}; border: 1px solid {c['border']}; }}
    """
