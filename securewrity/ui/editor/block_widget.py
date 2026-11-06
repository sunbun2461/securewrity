"""A single block in the page editor: handle + prefix + body, and nested children."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetrics, QTextCursor
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QSizePolicy, QTextEdit,
                             QToolButton, QVBoxLayout, QWidget)

from ...blocks.registry import registry
from ...core.repo import new_id
from .. import theme
from . import richtext
from .dragdrop import DragHandle

HANDLE_W = 20
CHILD_INDENT = 26


class BlockTextEdit(QTextEdit):
    """Auto-growing, frameless rich text editor for one block."""

    def __init__(self, bw: "BlockWidget"):
        super().__init__()
        self.bw = bw
        self.setObjectName("BlockText")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setAcceptRichText(False)
        self.setTabChangesFocus(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().setDocumentMargin(2)
        self.viewport().setMouseTracking(True)
        self.document().documentLayout().documentSizeChanged.connect(lambda _: self.fit())
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

    def fit(self):
        fm = QFontMetrics(self.font())
        h = max(int(self.document().size().height()) + 2, fm.lineSpacing() + 6)
        if self.height() != h:
            self.setFixedHeight(h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()

    # --- input ---------------------------------------------------------------
    def keyPressEvent(self, e):
        mods = e.modifiers()
        if (e.key() == Qt.Key.Key_V and mods & Qt.KeyboardModifier.ControlModifier
                and mods & Qt.KeyboardModifier.ShiftModifier):
            self._paste_plain = True  # Ctrl+Shift+V: paste as plain text, no Markdown conversion
            try:
                self.paste()
            finally:
                self._paste_plain = False
            return
        if not self.bw.editor.handle_key(self.bw, e):
            super().keyPressEvent(e)
            self.bw.editor.after_key(self.bw, e)

    def canInsertFromMimeData(self, source):
        from .images import might_have_images
        return might_have_images(source) or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        blocks = self.bw.editor.blocks_from_mime(source)
        if blocks:  # blocks copied inside Securewrity paste back exactly
            self.bw.editor.insert_parsed(self.bw, blocks)
            return
        from .images import images_from_mime
        images = images_from_mime(source)
        if images:  # a copied picture / screenshot, or copied image files
            self.bw.editor.paste_images(self.bw, images)
            return
        html = source.html() if source.hasHtml() else ""
        self.bw.editor.handle_paste(self.bw, source.text(), html, plain=getattr(self, "_paste_plain", False))

    # mouse: a press on a selected block may start dragging the selection; dragging out of
    # this block while highlighting text switches to selecting whole blocks
    _sel_press = None
    _ranging = False
    _left_down = False

    # images dragged in from other apps go in as image blocks (text drags work as usual)
    def dragEnterEvent(self, e):
        if not self.bw.editor.image_drop_event(e, self.viewport()):
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if not self.bw.editor.image_drop_event(e, self.viewport()):
            super().dragMoveEvent(e)

    def dragLeaveEvent(self, e):
        self.bw.editor.image_drop_event(e, self.viewport())
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        if not self.bw.editor.image_drop_event(e, self.viewport()):
            super().dropEvent(e)

    def mousePressEvent(self, e):
        ed = self.bw.editor
        self._ranging = False
        if e.button() == Qt.MouseButton.LeftButton:
            self._left_down = True
        if e.button() == Qt.MouseButton.LeftButton and ed.is_in_selection(self.bw):
            self._sel_press = e.position().toPoint()
            return
        self._sel_press = None
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        ed = self.bw.editor
        if ed.is_dragging():
            ed.drag_move(e.globalPosition().toPoint())
            return
        if self._sel_press is not None:
            if (e.position().toPoint() - self._sel_press).manhattanLength() >= QApplication.startDragDistance():
                self._sel_press = None
                ed.start_drag(self.bw, e.globalPosition().toPoint())
            return
        # only while the button pressed here is still down: QTextEdit's autoscroll timer sends
        # made-up "left button held" moves, which must never keep a block highlight going
        held = self._left_down
        if not held:
            self._ranging = False
        if held and e.buttons() & Qt.MouseButton.LeftButton:
            y = e.position().y()
            if self._ranging or y < -4 or y > self.viewport().height() + 4:
                self._ranging = True
                ed.select_range(self.bw, ed.block_at(e.globalPosition().toPoint()))
                return
        anchor = self.anchorAt(e.pos())
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if anchor else Qt.CursorShape.IBeamCursor)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._left_down = False
        if self.bw.editor.is_dragging():
            self._sel_press = None
            self.bw.editor.finish_drag(e.globalPosition().toPoint())
            return
        if self._sel_press is not None:  # a plain click on a selected block: back to typing there
            pos, self._sel_press = self._sel_press, None
            self.bw.editor.clear_selection()
            self.setFocus()
            self.setTextCursor(self.cursorForPosition(pos))
            return
        if self._ranging:
            self._ranging = False
            super().mouseReleaseEvent(e)  # lets QTextEdit stop its selection and autoscroll timer
            c = self.textCursor()
            c.clearSelection()
            self.setTextCursor(c)
            return
        super().mouseReleaseEvent(e)
        anchor = self.anchorAt(e.pos())
        if anchor and e.button() == Qt.MouseButton.LeftButton and not self.textCursor().hasSelection():
            self.bw.editor.open_link(anchor)
        self.bw.editor.update_inline_toolbar(self.bw)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        # a mouse press on a highlighted block may be the start of dragging the highlight:
        # keep it; the release decides (plain click → stop highlighting, drag → move them)
        keep = e.reason() == Qt.FocusReason.MouseFocusReason and self.bw.editor.is_in_selection(self.bw)
        self.bw.on_focus(True, keep_selection=keep)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.bw.on_focus(False)

    def contextMenuEvent(self, e):
        menu = self.createStandardContextMenu()
        self.bw.editor.extend_context_menu(self.bw, menu)
        menu.exec(e.globalPos())


class NonTextBody(QFrame):
    """Focusable body for blocks without text (divider, page links, plugin blocks)."""
    activated = pyqtSignal()

    def __init__(self, bw: "BlockWidget", clickable: bool = False):
        super().__init__()
        self.bw = bw
        self.clickable = clickable
        self.setObjectName("NonText")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._style(False)

    def _style(self, focused: bool):
        bg = theme.t("selected") if focused else "transparent"
        self.setStyleSheet(f"QFrame#NonText{{background:{bg}; border-radius:4px;}}"
                           f"QFrame#NonText:hover{{background:{theme.t('hover')};}}")

    def mousePressEvent(self, e):
        self.setFocus()

    def mouseReleaseEvent(self, e):
        if self.clickable and e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.pos()):
            self.activated.emit()

    def focusInEvent(self, e):
        self._style(True)
        self.bw.editor.current = self.bw
        self.bw.editor.clear_selection()

    def focusOutEvent(self, e):
        self._style(False)

    def keyPressEvent(self, e):
        self.bw.editor.handle_nontext_key(self.bw, e)


class BlockWidget(QWidget):
    def __init__(self, editor, data: dict, parent_block: "BlockWidget | None" = None):
        super().__init__()
        self.editor = editor
        self.parent_block = parent_block
        self.id = data.get("id") or new_id()
        self.type_key = data.get("type", "paragraph")
        self.btype = registry.get(self.type_key)
        if not registry.has(self.type_key):
            # unknown type (plugin removed?) — keep its key so data isn't lost
            self.btype = registry.get("paragraph")
        self.props = {**self.btype.default_props(), **(data.get("props") or {})}
        self.children: list[BlockWidget] = []
        self.text: BlockTextEdit | None = None
        self.body: QWidget | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.row = QFrame()
        self.row.setObjectName("Row")
        self.row.installEventFilter(self)
        row = QHBoxLayout(self.row)
        row.setContentsMargins(0, self.btype.top_margin, 0, 1)
        row.setSpacing(2)

        self.selected = False
        self.handle = DragHandle(self)
        self.handle.setText("⋮⋮")
        self.handle.setFixedWidth(HANDLE_W)
        self.handle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.handle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.handle.setToolTip("Drag to move · click for the block menu · Shift+click to select")
        self.handle.setObjectName("DragHandle")  # styled by the app stylesheet (per-widget styles are slow)
        sp = self.handle.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        self.handle.setSizePolicy(sp)
        self.handle.hide()
        row.addWidget(self.handle, 0, Qt.AlignmentFlag.AlignTop)

        self.prefix = self.btype.make_prefix(self)
        if self.prefix is not None:
            row.addWidget(self.prefix, 0, Qt.AlignmentFlag.AlignTop)

        if self.btype.has_text:
            self.text = BlockTextEdit(self)
            self._apply_font()
            richtext.load_runs(self.text.document(), data.get("content") or [], plain=not self.btype.rich)
            self.text.textChanged.connect(self._on_text_changed)
            self.text.selectionChanged.connect(lambda: editor.update_inline_toolbar(self))
            row.addWidget(self.text, 1)
        else:
            self.body = self.btype.make_body(self) or NonTextBody(self)
            row.addWidget(self.body, 1)
        outer.addWidget(self.row)

        self.child_box = QWidget()
        self.child_layout = QVBoxLayout(self.child_box)
        self.child_layout.setContentsMargins(CHILD_INDENT, 0, 0, 0)
        self.child_layout.setSpacing(0)
        outer.addWidget(self.child_box)

        self.empty_hint = None  # only toggles need one (a block's type never changes in place)
        if self.btype.toggle:
            self.empty_hint = QLabel("Empty toggle. Click or press Enter to add content.")
            self.empty_hint.setObjectName("Muted")
            self.empty_hint.setContentsMargins(CHILD_INDENT + HANDLE_W + 4, 2, 0, 4)
            self.empty_hint.setCursor(Qt.CursorShape.PointingHandCursor)
            self.empty_hint.mousePressEvent = lambda e: editor.add_first_child(self)
            outer.addWidget(self.empty_hint)

        for c in data.get("children") or []:
            child = BlockWidget(editor, c, self)
            self.children.append(child)
            self.child_layout.addWidget(child)

        self.apply_style()
        self.update_collapsed()

    # --- hover handle ---------------------------------------------------------
    def eventFilter(self, obj, ev):
        if obj is self.row:
            if ev.type() == QEvent.Type.Enter:
                self.handle.show()
            elif ev.type() == QEvent.Type.Leave and not self.editor.is_dragging():
                self.handle.hide()  # (never mid-drag: hiding it would drop the mouse grab)
        return False

    # --- appearance -------------------------------------------------------------
    def _apply_font(self):
        f = QFont(self.editor.base_font())
        if self.btype.monospace:
            f = QFont("Monospace")
            f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPixelSize(self.btype.font_px)
        if self.btype.bold:
            f.setWeight(QFont.Weight.Bold)
        f.setItalic(self.btype.italic)
        f.setStrikeOut(bool(self.type_key == "todo" and self.props.get("checked")))
        self.text.setFont(f)
        self.text.document().setDefaultFont(f)
        self.text.fit()

    def apply_style(self):
        color = theme.readable_text(self.props.get("color"), self.props.get("bg"))
        if self.type_key == "todo" and self.props.get("checked"):
            color = theme.t("muted")
        bg = theme.bg_color(self.props.get("bg"))
        if self.selected:
            bg = "rgba(35, 131, 226, 0.28)"  # translucent accent: reads on both themes and over colors
        css = f"background:{bg};border-radius:4px;" if bg else ""
        css += self.btype.row_css(self)
        self.row.setStyleSheet(f"QFrame#Row{{{css}}}")
        if self.text:
            # font must go in the stylesheet: the app-wide QSS font-size beats setFont()
            bt = self.btype
            family = "font-family: monospace;" if bt.monospace else ""
            self.text.setStyleSheet(
                f"QTextEdit{{color:{color}; background:transparent; border:none; font-size:{bt.font_px}px;"
                f" font-weight:{700 if bt.bold else 400}; {family}"
                f" selection-background-color:{theme.t('accent')};}}")
            self._apply_font()
        if self.prefix is not None and isinstance(self.prefix, QLabel):
            self.prefix.setStyleSheet(self.prefix.styleSheet().split(";color")[0] + f";color:{color}")
        self.btype.refresh(self)

    def set_selected(self, on: bool):
        if self.selected != on:
            self.selected = on
            self.apply_style()

    def on_focus(self, focused: bool, keep_selection: bool = False):
        if focused and self.parent() is not None:  # ignore late focus events of removed blocks
            self.editor.current = self
            if not keep_selection:
                self.editor.clear_selection()
        if self.text:
            ph = self.btype.placeholder if (focused or self.type_key != "paragraph") else ""
            self.text.setPlaceholderText(ph)
        if not focused:
            self.editor.on_block_blur(self)

    # --- data -----------------------------------------------------------------------
    def runs(self) -> list[dict]:
        if not self.text:
            return []
        runs = richtext.runs_from_document(self.text.document())
        if not self.btype.rich:
            runs = [{"t": richtext.plain_text(runs)}] if runs else []
        return runs

    def plain(self) -> str:
        return self.text.toPlainText() if self.text else ""

    def set_runs(self, runs: list[dict]):
        if self.text:
            self.text.blockSignals(True)
            richtext.load_runs(self.text.document(), runs, plain=not self.btype.rich)
            self.text.blockSignals(False)
            self.editor.changed()

    def to_data(self) -> dict:
        return {"id": self.id, "type": self.type_key, "content": self.runs(),
                "props": dict(self.props), "children": [c.to_data() for c in self.children]}

    def set_prop(self, key, value):
        self.editor.before_structure_change()
        if value is None:
            self.props.pop(key, None)
        else:
            self.props[key] = value
        self.apply_style()
        self.editor.changed()

    def _on_text_changed(self):
        self.editor.changed()
        self.editor.on_text_changed(self)

    # --- tree helpers ----------------------------------------------------------------
    def ancestors(self):
        p = self.parent_block
        while p:
            yield p
            p = p.parent_block

    def is_collapsed(self) -> bool:
        return bool(self.btype.toggle and self.props.get("collapsed"))

    def toggle_collapsed(self):
        self.props["collapsed"] = not self.props.get("collapsed")
        self.update_collapsed()
        self.editor.changed()

    def update_collapsed(self):
        collapsed = self.is_collapsed()
        self.child_box.setVisible(not collapsed and bool(self.children))
        if self.empty_hint is not None:
            self.empty_hint.setVisible(not collapsed and not self.children)
        self.btype.refresh(self)

    def cursor_pos(self) -> int:
        return self.text.textCursor().position() if self.text else 0

    def set_cursor(self, pos):
        if not self.text:
            return
        c = self.text.textCursor()
        if pos == "end":
            c.movePosition(QTextCursor.MoveOperation.End)
        elif pos == "start":
            c.movePosition(QTextCursor.MoveOperation.Start)
        else:
            c.setPosition(max(0, min(int(pos), len(self.text.toPlainText()))))
        self.text.setTextCursor(c)
