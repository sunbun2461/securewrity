"""Images: the image block's body, plus turning pasted / dropped / picked images into blocks.

Images are stored inside the notes database (the `files` table), so on a protected account
they are encrypted with everything else. Big images are shrunk on the way in (to MAX_W wide)
because every save rewrites the whole database.

Ways in:  Ctrl+V a copied image or screenshot · drag image files (or an image from a browser)
onto the page · "/image" · Markdown / Notion import (images inside the zip or folder).
On the page: drag the right edge to resize · double-click for full size · right-click for
copy / save / reset size.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QSize, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (QApplication, QDialog, QFileDialog, QLabel, QMenu, QScrollArea,
                             QVBoxLayout)

from .. import theme
from .block_widget import NonTextBody

MAX_W = 2000                # px: wider images are scaled down when added
KEEP_BYTES = 4_000_000      # a file already in a normal format, this small and narrow is kept as-is
MAX_FILE_BYTES = 60_000_000
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
EDGE = 12                   # px at the right edge of an image that resize it
MIN_W = 48


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _encode(img: QImage) -> tuple[bytes, str]:
    """PNG (sharp text in screenshots, keeps transparency); JPEG if a photo makes PNG too big."""
    def save(fmt, quality=-1):
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, fmt, quality)
        return bytes(buf.data())
    png = save("PNG")
    if len(png) > 2_500_000 and not img.hasAlphaChannel():
        jpg = save("JPEG", 88)
        if len(jpg) < len(png):
            return jpg, "image/jpeg"
    return png, "image/png"


def prepare_image(source) -> tuple[bytes, str, int, int] | None:
    """bytes or QImage → (data, mime, width, height) ready to store, or None if it isn't an image."""
    data = None
    if isinstance(source, QImage):
        img = source
    else:
        data = bytes(source)
        if len(data) > MAX_FILE_BYTES:
            return None
        img = QImage()
        if not img.loadFromData(data):
            return None
    if img.isNull():
        return None
    mime = _sniff(data) if data else None
    if mime and img.width() <= MAX_W and len(data) <= KEEP_BYTES:
        return data, mime, img.width(), img.height()  # keep the original file untouched
    if img.width() > MAX_W:
        img = img.scaledToWidth(MAX_W, Qt.TransformationMode.SmoothTransformation)
    out, mime = _encode(img)
    return out, mime, img.width(), img.height()


def _looks_like_link(text: str) -> bool:
    t = text.strip()
    return bool(t) and "\n" not in t and " " not in t


def images_from_mime(mime) -> list:
    """Images in a paste or drop: local image files (bytes) or a copied picture (QImage)."""
    if mime is None:
        return []
    if mime.hasUrls():
        out = []
        for url in mime.urls():
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                try:
                    if p.suffix.lower() in IMAGE_SUFFIXES and p.is_file() and p.stat().st_size <= MAX_FILE_BYTES:
                        out.append(p.read_bytes())
                except OSError:
                    pass
        if out:
            return out
    # a copied picture; office apps also put a picture of copied *text* on the clipboard,
    # so when there is real text, the text wins
    if mime.hasImage() and (not mime.hasText() or _looks_like_link(mime.text())):
        img = mime.imageData()
        if isinstance(img, QImage) and not img.isNull():
            return [img]
    return []


def might_have_images(mime) -> bool:
    """Cheap check for drags (no file reading)."""
    if mime is None:
        return False
    if mime.hasUrls() and any(u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in IMAGE_SUFFIXES
                              for u in mime.urls()):
        return True
    return mime.hasImage() and (not mime.hasText() or _looks_like_link(mime.text()))


# --- the block body --------------------------------------------------------------------
class _ImageLabel(QLabel):
    def __init__(self, body: "ImageBody"):
        super().__init__()
        self.body = body
        self.setMouseTracking(True)
        self._resize_from: tuple[int, int] | None = None  # (press x, width at press)
        self._hover = False

    def _on_edge(self, pos: QPoint) -> bool:
        return self.pixmap() is not None and not self.pixmap().isNull() and pos.x() >= self.width() - EDGE

    def mousePressEvent(self, e):
        self.body.setFocus()
        if e.button() == Qt.MouseButton.LeftButton and self._on_edge(e.position().toPoint()):
            self._resize_from = (int(e.globalPosition().x()), self.width())
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._resize_from is not None:
            x0, w0 = self._resize_from
            self.body.fit(max(MIN_W, w0 + int(e.globalPosition().x()) - x0))
            return
        self.setCursor(Qt.CursorShape.SizeHorCursor if self._on_edge(e.position().toPoint())
                       else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, e):
        if self._resize_from is not None:
            self._resize_from = None
            self.body.bw.set_prop("width", self.width())
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.body.open_full()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.body.hasFocus() and self.pixmap() is not None and not self.pixmap().isNull():
            p = QPainter(self)
            pen = QColor(theme.t("accent"))
            p.setPen(pen)
            p.drawRect(0, 0, self.width() - 1, self.height() - 1)
            p.drawRect(1, 1, self.width() - 3, self.height() - 3)
            p.end()
        if (self._hover or self._resize_from is not None) and self.pixmap() is not None \
                and not self.pixmap().isNull():
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QColor(255, 255, 255, 200))
            p.setBrush(QColor(0, 0, 0, 140))
            h = min(48, self.height() - 8)
            p.drawRoundedRect(self.width() - 9, (self.height() - h) // 2, 6, h, 3, 3)
            p.end()


class ImageBody(NonTextBody):
    def __init__(self, bw):
        super().__init__(bw)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        self.label = _ImageLabel(self)
        self.label.setToolTip("Drag the right edge to resize · double-click for full size · right-click for more")
        lay.addWidget(self.label, 0, Qt.AlignmentFlag.AlignLeft)
        self.pix: QPixmap | None = None
        self._cache: tuple[int, QPixmap] | None = None
        self.load()

    def _style(self, focused: bool):
        """Selected = blue outline around the picture (not a gray band across the page)."""
        self.setStyleSheet("QFrame#NonText{background:transparent;}")
        if hasattr(self, "label"):
            self.label.update()

    def load(self):
        self.pix, self._cache = None, None
        fid = self.bw.props.get("file_id")
        f = self.bw.editor.ctx.repo.get_file(fid) if fid else None
        if f:
            pix = QPixmap()
            if pix.loadFromData(f["data"]):
                self.pix = pix
        if self.pix is None:
            self.label.setText("🖼  Image missing")
            self.label.setStyleSheet(f"color:{theme.t('muted')}; padding:6px;")
            self.label.setFixedSize(QSize(180, 32))
        else:
            self.fit()

    def natural_width(self) -> int:
        """Width the image is shown at by default: its real size (screenshots from a 2x screen
        show at the size they were on screen)."""
        return max(1, round(self.pix.width() / self.devicePixelRatioF())) if self.pix else 0

    def fit(self, width: int | None = None):
        if self.pix is None:
            return
        avail = max(MIN_W, self.width() - 4) if self.width() > 50 else 10_000
        want = width or self.bw.props.get("width") or self.natural_width()
        w = int(max(MIN_W, min(want, avail)))
        h = max(1, round(self.pix.height() * w / self.pix.width()))
        dpr = self.devicePixelRatioF()
        if self._cache is None or self._cache[0] != w:
            scaled = self.pix.scaled(QSize(round(w * dpr), round(h * dpr)),
                                     Qt.AspectRatioMode.IgnoreAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            self._cache = (w, scaled)
        self.label.setPixmap(self._cache[1])
        self.label.setFixedSize(w, h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()

    def mouseDoubleClickEvent(self, e):
        self.open_full()

    def contextMenuEvent(self, e):
        m = QMenu(self)
        self.add_menu_actions(m)
        m.addSeparator()
        blk = m.addMenu("Block")
        self.bw.editor.build_block_menu(self.bw, blk)
        m.exec(e.globalPos())

    def add_menu_actions(self, m: QMenu):
        has = self.pix is not None
        for label, fn in (("Open full size", self.open_full), ("Copy image", self.copy),
                          ("Save image as…", self.save_as), ("Reset size", self.reset_size)):
            a = m.addAction(label, fn)
            a.setEnabled(has and (label != "Reset size" or bool(self.bw.props.get("width"))))

    # --- actions -------------------------------------------------------------------
    def copy(self):
        if self.pix is not None:
            QApplication.clipboard().setPixmap(self.pix)
            self.bw.editor.ctx.window.notify("Image copied")

    def save_as(self):
        f = self.bw.editor.ctx.repo.get_file(self.bw.props.get("file_id") or "")
        if not f:
            return
        ext = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}.get(f["mime"], "png")
        path, _ = QFileDialog.getSaveFileName(self, "Save image", f"image.{ext}", f"Image (*.{ext})")
        if path:
            try:
                Path(path).write_bytes(f["data"])
            except OSError as err:
                self.bw.editor.ctx.window.notify(f"Couldn't save: {err.strerror or err}")

    def reset_size(self):
        self.bw.set_prop("width", None)

    def open_full(self):
        if self.pix is None:
            return
        dlg = QDialog(self.window())
        dlg.setWindowTitle("Image")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        area = QScrollArea()
        area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab = QLabel()
        lab.setPixmap(self.pix)
        area.setWidget(lab)
        lay.addWidget(area)
        screen = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        dlg.resize(min(self.pix.width() + 24, int(screen.width() * 0.9)),
                   min(self.pix.height() + 24, int(screen.height() * 0.9)))
        dlg.exec()
