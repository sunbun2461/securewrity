"""Import Markdown files, folders and Notion export .zip files as pages with sub-pages.

Layout rules (they match a Notion "Markdown & CSV" export, and plain folders of notes):

* every ``.md`` / ``.markdown`` file becomes a page;
* a folder next to a file with the same name holds that page's sub-pages
  (``Trip.md`` + ``Trip/Day 1.md`` → "Day 1" is a sub-page of "Trip");
* a folder with no matching file becomes a page named after the folder;
* an image on a line of its own (``![](Trip/photo.png)``) becomes an image block when the file
  is inside what was imported (Notion puts them there); other images stay as links;
* links between the imported files (``[Day 1](Trip/Day%201.md)``) become page links,
  and a line that is only a link to one of the page's own sub-pages becomes a sub-page block.

Pure Python, no Qt.
"""
from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote

from .markdown_import import parse_markdown

MD_SUFFIXES = {".md", ".markdown"}
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
              ".webp": "image/webp", ".bmp": "image/bmp"}
MAX_IMAGE_BYTES = 30_000_000
MAX_PAGES = 5000
_NOTION_ID = re.compile(r"\s+[0-9a-f]{32}$", re.I)


def clean_title(name: str) -> str:
    """'Trip ideas 1a2b…(32 hex)' → 'Trip ideas'."""
    return _NOTION_ID.sub("", name).strip() or "Untitled"


def blocks_and_title(text: str, fallback: str) -> tuple[list[dict], str]:
    """Parse a file; a leading '# Title' becomes the page title instead of a block."""
    blocks = parse_markdown(text)
    title = clean_title(fallback)
    if blocks and blocks[0]["type"] in ("h1", "toggle_h1") and not blocks[0]["children"]:
        title = "".join(r["t"] for r in blocks.pop(0)["content"]).strip() or title
    return blocks, title


class _Importer:
    def __init__(self, repo, dry_run: bool = False, image_hook=None):
        self.repo = repo
        # image_hook(bytes) -> (bytes, mime, width, height) or None: lets the app shrink / check images
        self.image_hook = image_hook
        self.roots: list[Path] = []   # images are only read from inside what was imported
        self.images: dict[Path, str | None] = {}  # image file → stored file id (None = unusable)
        self.dry_run = dry_run  # count what would be made, touch nothing
        self.seen_dirs: set[Path] = set()
        self.by_path: dict[Path, str] = {}           # resolved .md path → page id
        self.pending: list[tuple[str, Path, list[dict]]] = []  # (page id, file, blocks)
        self.count = 0

    def _new_page(self, parent_id, title):
        self.count += 1
        if self.count > MAX_PAGES:
            raise ValueError(f"more than {MAX_PAGES} pages; pick a smaller folder")
        if self.dry_run:
            return f"dry{self.count}"
        return self.repo.create_page(parent_id, title, commit=False)

    def file(self, path: Path, parent_id):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        if self.dry_run:
            pid = self._new_page(parent_id, path.stem)
            self.pending.append((pid, path, []))
            return pid
        blocks, title = blocks_and_title(text, path.stem)
        pid = self._new_page(parent_id, title)
        self.by_path[path.resolve()] = pid
        self.pending.append((pid, path, blocks))
        return pid

    def folder_contents(self, folder: Path, parent_id):
        real = folder.resolve()
        if real in self.seen_dirs:  # a folder shortcut pointing back up would loop forever
            return
        self.seen_dirs.add(real)
        entries = sorted(_entries(folder), key=lambda p: p.name.lower())
        files = [p for p in entries if p.is_file() and p.suffix.lower() in MD_SUFFIXES]
        dirs = {p.name: p for p in entries if p.is_dir()}
        for f in files:
            pid = self.file(f, parent_id)
            sub = dirs.pop(f.stem, None)
            if pid and sub:
                self.folder_contents(sub, pid)
        for d in dirs.values():
            if _has_markdown(d):
                self.folder_contents(d, self._new_page(parent_id, clean_title(d.name)))

    def finish(self):
        """Second pass: now every page exists, point links at pages and save the blocks."""
        if self.dry_run:
            return
        for pid, path, blocks in self.pending:
            self._fix_links(blocks, path.parent, pid)
            self.repo.save_blocks(pid, blocks, commit=False)

    def _target(self, link: str, base: Path):
        if not link or re.match(r"^[a-z][a-z0-9+.-]*:", link, re.I):
            return None  # http:, page:, mailto: … left alone
        p = unquote(link.split("#", 1)[0])
        if Path(p).suffix.lower() not in MD_SUFFIXES:
            return None
        try:
            return self.by_path.get((base / p).resolve())
        except OSError:
            return None

    def _image_file(self, run: dict, base: Path) -> str | None:
        """Store the image a Markdown image points at; its file id, or None if it can't be used."""
        link = run.get("link") or ""
        if not run.get("img") or re.match(r"^[a-z][a-z0-9+.-]*:", link, re.I):
            return None  # web images aren't downloaded
        try:
            path = (base / unquote(link.split("#", 1)[0].split("?", 1)[0])).resolve()
        except (OSError, ValueError):
            return None
        if path in self.images:
            return self.images[path]
        fid = None
        mime = IMAGE_MIME.get(path.suffix.lower())
        try:
            if (mime and any(path.is_relative_to(r) for r in self.roots) and path.is_file()
                    and path.stat().st_size <= MAX_IMAGE_BYTES):
                data, w, h = path.read_bytes(), 0, 0
                if self.image_hook is not None:
                    res = self.image_hook(data)
                    data, mime, w, h = res if res else (None, None, 0, 0)
                if data:
                    fid = self.repo.add_file(data, mime, w, h)
        except OSError:
            fid = None
        self.images[path] = fid
        return fid

    def _fix_links(self, blocks, base, page_id):
        out = []
        for b in blocks:
            runs = [r for r in b["content"] if r["t"].strip()]
            if b["type"] == "paragraph" and not b["children"] and runs and all(r.get("img") for r in runs):
                fids = [self._image_file(r, base) for r in runs]
                if all(fids):
                    out += [{"type": "image", "content": [], "props": {"file_id": f}, "children": []} for f in fids]
                    continue
            for r in b["content"]:
                r.pop("img", None)
            out.append(b)
        blocks[:] = out
        for i, b in enumerate(blocks):
            runs = [r for r in b["content"] if r["t"].strip()]
            if b["type"] in ("paragraph", "bullet") and not b["children"] and len(runs) == 1:
                target = self._target(runs[0].get("link", ""), base)
                if target and self.repo.get_page(target)["parent_id"] == page_id:
                    blocks[i] = {"type": "page", "content": [], "props": {"page_id": target}, "children": []}
                    continue
            for r in b["content"]:
                target = self._target(r.get("link", ""), base)
                if target:
                    r["link"] = f"page:{target}"
            self._fix_links(b["children"], base, page_id)


def _entries(folder: Path):
    """Folder contents, skipping hidden files, macOS zip junk and symlinks (which can loop)."""
    try:
        return [p for p in folder.iterdir()
                if not p.name.startswith((".", "__MACOSX")) and not p.is_symlink()]
    except OSError:
        return []


def _has_markdown(folder: Path, depth: int = 0) -> bool:
    if depth > 40:
        return False
    for p in _entries(folder):
        if p.is_dir():
            if _has_markdown(p, depth + 1):
                return True
        elif p.suffix.lower() in MD_SUFFIXES:
            return True
    return False


def _extract_zip(path: Path, into: Path):
    """Extract, including the zips-inside-a-zip Notion makes for big exports."""
    with zipfile.ZipFile(path) as z:
        z.extractall(into)  # extractall drops '..' and absolute parts, so nothing escapes `into`
    for inner in sorted(into.rglob("*.zip")):
        dest = inner.with_suffix("")
        dest.mkdir(exist_ok=True)
        with zipfile.ZipFile(inner) as z:
            z.extractall(dest)
        inner.unlink()


def count_pages(paths) -> int:
    """How many pages import_paths would create (to warn before a huge import)."""
    return import_paths(None, paths, dry_run=True)[1]


def import_paths(repo, paths, parent_id: str | None = None, dry_run: bool = False,
                 image_hook=None) -> tuple[list[str], int]:
    """Import .md files, folders and .zip exports under `parent_id` (None = top level).

    Returns (ids of the new top pages, total pages created). One save at the end.
    Raises ValueError past MAX_PAGES so a wrong pick (like your home folder) can't run away.
    """
    imp = _Importer(repo, dry_run, image_hook)
    tops: list[str] = []
    with tempfile.TemporaryDirectory(prefix="securewrity-import-") as tmp:
        for i, raw in enumerate(paths):
            path = Path(raw)
            if path.suffix.lower() == ".zip":
                folder = Path(tmp) / str(i)
                folder.mkdir()
                _extract_zip(path, folder)
                imp.roots.append(folder.resolve())
                tops += _import_folder(imp, folder, path.stem, parent_id)
            elif path.is_dir():
                imp.roots.append(path.resolve())
                tops += _import_folder(imp, path, path.name, parent_id)
            elif path.is_file():
                imp.roots.append(path.parent.resolve())
                pid = imp.file(path, parent_id)
                if pid:
                    tops.append(pid)
                    sub = path.with_suffix("")
                    if sub.is_dir():  # "Trip.md" picked with a "Trip/" folder beside it
                        imp.folder_contents(sub, pid)
        imp.finish()  # files in the temp folder are read before it is removed
    if not dry_run:
        repo.commit()
    return tops, imp.count


def _import_folder(imp: _Importer, folder: Path, name: str, parent_id) -> list[str]:
    """A folder holding one top page (a typical Notion export) imports as that page;
    a folder of several notes is wrapped in a page named after the folder."""
    items = _entries(folder)
    md = [p for p in items if p.is_file() and p.suffix.lower() in MD_SUFFIXES]
    dirs = [p for p in items if p.is_dir() and _has_markdown(p)]
    if len(md) == 1 and all(d.name == md[0].stem for d in dirs):
        before = len(imp.pending)
        imp.folder_contents(folder, parent_id)
        return [imp.pending[before][0]] if len(imp.pending) > before else []
    if not md and len(dirs) == 1:
        return _import_folder(imp, dirs[0], dirs[0].name, parent_id)
    if not md and not dirs:
        return []
    top = imp._new_page(parent_id, clean_title(name))
    imp.folder_contents(folder, top)
    return [top]
