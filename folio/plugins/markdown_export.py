"""Bundled plugin: export pages (and all their sub-pages) to Markdown files."""
import re
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog

from folio.blocks.registry import registry

PLUGIN = {"name": "Markdown export", "version": "1.0",
          "description": "Export a page tree or the whole workspace to .md files."}


def runs_to_md(runs, titles=None):
    titles = titles or {}
    out = []
    for r in runs or []:
        t = r.get("t", "")
        if not t:
            continue
        if r.get("code"):
            t = f"`{t}`"
        if r.get("b"):
            t = f"**{t}**"
        if r.get("i"):
            t = f"*{t}*"
        if r.get("s"):
            t = f"~~{t}~~"
        if r.get("link"):
            link = r["link"]
            if link.startswith("page:"):
                link = _safe(titles.get(link[5:], "Untitled")).replace(" ", "%20") + ".md"
            t = f"[{t}]({link})"
        out.append(t)
    return "".join(out)


def blocks_to_md(blocks, depth=0, titles=None):
    lines, number = [], 0
    for b in blocks:
        bt = registry.get(b["type"])
        number = number + 1 if b["type"] == "numbered" else 0
        text = runs_to_md(b.get("content"), titles)
        md = bt.to_markdown(text, b, depth, number)
        indent = "    " * depth
        lines.append("\n".join(indent + line for line in md.split("\n")))
        if b.get("children"):
            nest = b["type"] in ("bullet", "numbered", "todo", "toggle")
            lines.append(blocks_to_md(b["children"], depth + 1 if nest else depth, titles))
        if b["type"] == "toggle":
            lines.append(indent + "</details>")
    return "\n\n".join(l for l in lines if l is not None) if depth == 0 else "\n".join(lines)


def _safe(name):
    return re.sub(r"[^\w\- ]+", "", name).strip() or "Untitled"


def export_tree(repo, page_id, folder: Path):
    p = repo.get_page(page_id)
    titles = {q["id"]: q["title"] for q in repo.list_pages()}
    body = (f"# {p['icon'] + ' ' if p['icon'] else ''}{p['title'] or 'Untitled'}\n\n"
            + blocks_to_md(repo.get_blocks(page_id), titles=titles))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{_safe(p['title'])}.md").write_text(body + "\n", encoding="utf-8")
    for k in repo.children(page_id):
        export_tree(repo, k["id"], folder / _safe(p["title"]))


def register(api):
    def export_page(page_id):
        api.window.editor.save_now()
        d = QFileDialog.getExistingDirectory(api.window, "Export to folder")
        if d:
            export_tree(api.repo, page_id, Path(d))
            api.notify(f"Exported to {d}")

    def export_all():
        api.window.editor.save_now()
        d = QFileDialog.getExistingDirectory(api.window, "Export all pages to folder")
        if d:
            for p in api.repo.children(None):
                export_tree(api.repo, p["id"], Path(d))
            api.notify(f"Exported workspace to {d}")

    api.add_page_command("⇩  Export to Markdown…", export_page)
    api.add_command("Export all pages to Markdown…", export_all)
