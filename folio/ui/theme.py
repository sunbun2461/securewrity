"""Themes and the Notion-style named color palette.

Blocks and inline text store color *names* ("red", "blue_bg", ...), never hex,
so switching between dark and light keeps everything readable.
"""
from __future__ import annotations

COLOR_NAMES = ["default", "gray", "brown", "orange", "yellow", "green", "blue", "purple", "pink", "red"]

THEMES = {
    "dark": {
        "bg": "#191919", "sidebar": "#202020", "text": "#D4D4D4", "muted": "#7F7F7F",
        "hover": "#2C2C2C", "selected": "#2F3437", "border": "#2F2F2F", "accent": "#2383E2",
        "code_bg": "#252525", "input": "#262626", "danger": "#E5534B", "link": "#9CC4F0",
        "text_colors": {
            "gray": "#9B9B9B", "brown": "#BA856F", "orange": "#C77D48", "yellow": "#CA9849",
            "green": "#529E72", "blue": "#5E87C9", "purple": "#9D68D3", "pink": "#D15796", "red": "#DF5452"},
        "bg_colors": {
            "gray": "#2F2F2F", "brown": "#4A3228", "orange": "#5C3B23", "yellow": "#564328",
            "green": "#243D30", "blue": "#143A4E", "purple": "#3C2D49", "pink": "#4E2C3C", "red": "#522E2A"},
    },
    "light": {
        "bg": "#FFFFFF", "sidebar": "#F7F7F5", "text": "#37352F", "muted": "#91918E",
        "hover": "#EFEFED", "selected": "#E8E8E6", "border": "#E9E9E7", "accent": "#2383E2",
        "code_bg": "#F7F6F3", "input": "#FFFFFF", "danger": "#D44C47", "link": "#2069B0",
        "text_colors": {
            "gray": "#787774", "brown": "#9F6B53", "orange": "#D9730D", "yellow": "#CB912F",
            "green": "#448361", "blue": "#337EA9", "purple": "#9065B0", "pink": "#C14C8A", "red": "#D44C47"},
        "bg_colors": {
            "gray": "#F1F1EF", "brown": "#F4EEEE", "orange": "#FBECDD", "yellow": "#FBF3DB",
            "green": "#EDF3EC", "blue": "#E7F3F8", "purple": "#F4F0F7", "pink": "#F9EEF3", "red": "#FDEBEC"},
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
