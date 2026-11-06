"""Data access for pages, blocks and settings.

Block content is stored as JSON "rich text runs":
    [{"t": "Hello ", "b": 1}, {"t": "world", "c": "red", "link": "page:abc123"}]
Keys: t=text b=bold i=italic u=underline s=strike code=inline code
      c=text color name  bg=background color name  link=URL or "page:<id>"

Block props (JSON dict) hold per-type data: color, bg, checked, collapsed,
page_id (for sub-page / link blocks), emoji (callout), language (code), ...
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid

from .storage import Store

SCHEMA_VERSION = 2

MIGRATIONS = {
    1: """
    CREATE TABLE pages (
        id TEXT PRIMARY KEY,
        parent_id TEXT REFERENCES pages(id) ON DELETE CASCADE,
        title TEXT NOT NULL DEFAULT '',
        icon TEXT NOT NULL DEFAULT '',
        position REAL NOT NULL DEFAULT 0,
        favorite INTEGER NOT NULL DEFAULT 0,
        trashed INTEGER NOT NULL DEFAULT 0,
        props TEXT NOT NULL DEFAULT '{}',
        created REAL NOT NULL,
        updated REAL NOT NULL
    );
    CREATE INDEX idx_pages_parent ON pages(parent_id);
    CREATE TABLE blocks (
        id TEXT PRIMARY KEY,
        page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
        parent_id TEXT,
        position REAL NOT NULL,
        type TEXT NOT NULL,
        content TEXT NOT NULL DEFAULT '[]',
        text TEXT NOT NULL DEFAULT '',
        props TEXT NOT NULL DEFAULT '{}',
        created REAL NOT NULL,
        updated REAL NOT NULL
    );
    CREATE INDEX idx_blocks_page ON blocks(page_id);
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """,
    # images (and later other attachments) live inside the database, so protected
    # accounts keep them encrypted together with the notes
    2: """
    CREATE TABLE files (
        id TEXT PRIMARY KEY,
        mime TEXT NOT NULL,
        data BLOB NOT NULL,
        width INTEGER NOT NULL DEFAULT 0,
        height INTEGER NOT NULL DEFAULT 0,
        created REAL NOT NULL
    );
    """,
}


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def runs_to_text(runs: list[dict]) -> str:
    return "".join(r.get("t", "") for r in runs or [])


class Repo:
    def __init__(self, store: Store):
        self.store = store
        self.migrate()

    @property
    def db(self) -> sqlite3.Connection:
        return self.store.conn

    def commit(self) -> None:
        self.store.save()

    # --- schema ------------------------------------------------------------
    def migrate(self) -> None:
        v = self.db.execute("PRAGMA user_version").fetchone()[0]
        for target in sorted(MIGRATIONS):
            if target > v:
                self.db.executescript(MIGRATIONS[target])
                self.db.execute(f"PRAGMA user_version = {target}")
        self.db.commit()
        if v < SCHEMA_VERSION:
            self.commit()

    # --- settings ----------------------------------------------------------
    def get_setting(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value) -> None:
        self.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                        (key, json.dumps(value)))
        self.commit()

    # --- pages -------------------------------------------------------------
    def _page(self, row) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        d["props"] = json.loads(d.get("props") or "{}")
        return d

    def list_pages(self, trashed: bool = False) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM pages WHERE trashed=? ORDER BY position, created", (int(trashed),))
        return [self._page(r) for r in rows]

    def get_page(self, page_id: str) -> dict | None:
        return self._page(self.db.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone())

    def children(self, parent_id: str | None) -> list[dict]:
        if parent_id is None:
            rows = self.db.execute("SELECT * FROM pages WHERE parent_id IS NULL AND trashed=0 ORDER BY position")
        else:
            rows = self.db.execute("SELECT * FROM pages WHERE parent_id=? AND trashed=0 ORDER BY position", (parent_id,))
        return [self._page(r) for r in rows]

    def ancestors(self, page_id: str) -> list[dict]:
        out, seen = [], set()
        p = self.get_page(page_id)
        while p and p["parent_id"] and p["parent_id"] not in seen:
            seen.add(p["parent_id"])
            p = self.get_page(p["parent_id"])
            if p:
                out.insert(0, p)
        return out

    def create_page(self, parent_id: str | None = None, title: str = "", icon: str = "",
                    commit: bool = True) -> str:
        pid = new_id()
        now = time.time()
        pos = self.db.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM pages WHERE parent_id IS ?", (parent_id,)).fetchone()[0]
        self.db.execute(
            "INSERT INTO pages(id, parent_id, title, icon, position, created, updated) VALUES (?,?,?,?,?,?,?)",
            (pid, parent_id, title, icon, pos, now, now))
        if commit:
            self.commit()
        return pid

    def update_page(self, page_id: str, **fields) -> None:
        allowed = {"title", "icon", "favorite", "props", "parent_id", "position"}
        sets, vals = [], []
        for k, v in fields.items():
            if k not in allowed:
                raise KeyError(k)
            if k == "props":
                v = json.dumps(v)
            sets.append(f"{k}=?")
            vals.append(v)
        sets.append("updated=?")
        vals += [time.time(), page_id]
        self.db.execute(f"UPDATE pages SET {', '.join(sets)} WHERE id=?", vals)
        self.commit()

    def descendants(self, page_id: str) -> list[str]:
        rows = self.db.execute("""
            WITH RECURSIVE sub(id) AS (
              SELECT id FROM pages WHERE parent_id=?
              UNION ALL SELECT p.id FROM pages p JOIN sub ON p.parent_id=sub.id)
            SELECT id FROM sub""", (page_id,))
        return [r[0] for r in rows]

    def move_page(self, page_id: str, new_parent: str | None, position: float) -> None:
        if new_parent == page_id or new_parent in self.descendants(page_id):
            return  # can't move into itself
        self.db.execute("UPDATE pages SET parent_id=?, position=?, updated=? WHERE id=?",
                        (new_parent, position, time.time(), page_id))

    def trash_page(self, page_id: str) -> None:
        ids = [page_id] + self.descendants(page_id)
        self.db.executemany("UPDATE pages SET trashed=1 WHERE id=?", [(i,) for i in ids])
        self.commit()

    def restore_page(self, page_id: str) -> None:
        ids = [page_id] + self.descendants(page_id)
        self.db.executemany("UPDATE pages SET trashed=0 WHERE id=?", [(i,) for i in ids])
        p = self.get_page(page_id)
        if p and p["parent_id"]:
            parent = self.get_page(p["parent_id"])
            if not parent or parent["trashed"]:
                self.db.execute("UPDATE pages SET parent_id=NULL WHERE id=?", (page_id,))
        self.commit()

    def delete_page(self, page_id: str) -> None:
        self.db.execute("DELETE FROM pages WHERE id=?", (page_id,))  # cascades
        self.commit()

    def trashed_roots(self) -> list[dict]:
        rows = self.db.execute("""
            SELECT c.* FROM pages c LEFT JOIN pages p ON c.parent_id = p.id
            WHERE c.trashed=1 AND (p.id IS NULL OR p.trashed=0) ORDER BY c.updated DESC""")
        return [self._page(r) for r in rows]

    # --- files (images) ------------------------------------------------------
    def add_file(self, data: bytes, mime: str, width: int = 0, height: int = 0) -> str:
        """Store a file and return its id. Not committed: the block that uses it is saved next."""
        fid = new_id()
        self.db.execute("INSERT INTO files(id, mime, data, width, height, created) VALUES (?,?,?,?,?,?)",
                        (fid, mime, sqlite3.Binary(data), width, height, time.time()))
        return fid

    def get_file(self, file_id: str) -> dict | None:
        r = self.db.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        return {"id": r["id"], "mime": r["mime"], "data": bytes(r["data"]),
                "width": r["width"], "height": r["height"]} if r else None

    def purge_unused_files(self) -> int:
        """Delete files no block refers to any more (pages in the Trash still count).
        Run at unlock only, so undo within a session can always bring an image back."""
        cur = self.db.execute("""
            DELETE FROM files WHERE id NOT IN (
                SELECT json_extract(props, '$.file_id') FROM blocks
                WHERE json_extract(props, '$.file_id') IS NOT NULL)""")
        if cur.rowcount:
            self.commit()
        return cur.rowcount

    # --- blocks ------------------------------------------------------------
    def get_blocks(self, page_id: str) -> list[dict]:
        """Return the page's blocks as a tree: each block has 'children'."""
        rows = self.db.execute(
            "SELECT * FROM blocks WHERE page_id=? ORDER BY position", (page_id,)).fetchall()
        nodes = {}
        for r in rows:
            nodes[r["id"]] = {
                "id": r["id"], "type": r["type"], "parent_id": r["parent_id"],
                "content": json.loads(r["content"]), "props": json.loads(r["props"]),
                "children": [],
            }
        roots = []
        for r in rows:
            n = nodes[r["id"]]
            parent = nodes.get(n["parent_id"]) if n["parent_id"] else None
            (parent["children"] if parent else roots).append(n)
        return roots

    def save_blocks(self, page_id: str, tree: list[dict], commit: bool = True) -> None:
        """Replace all blocks of a page with the given tree."""
        now = time.time()
        rows = []

        def walk(nodes, parent):
            for i, n in enumerate(nodes):
                bid = n.get("id") or new_id()
                rows.append((bid, page_id, parent, float(i), n["type"],
                             json.dumps(n.get("content") or [], ensure_ascii=False),
                             runs_to_text(n.get("content")),
                             json.dumps(n.get("props") or {}, ensure_ascii=False), now, now))
                walk(n.get("children") or [], bid)

        walk(tree, None)
        with self.db:
            self.db.execute("DELETE FROM blocks WHERE page_id=?", (page_id,))
            self.db.executemany(
                "INSERT INTO blocks(id, page_id, parent_id, position, type, content, text, props, created, updated)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            self.db.execute("UPDATE pages SET updated=? WHERE id=?", (now, page_id))
        if commit:
            self.commit()

    # --- search & links ----------------------------------------------------
    def search(self, query: str, limit: int = 50) -> list[dict]:
        """Return pages matching by title or content: [{page, snippet}]"""
        q = f"%{query}%"
        out, seen = [], set()
        for r in self.db.execute(
                "SELECT * FROM pages WHERE trashed=0 AND title LIKE ? ORDER BY updated DESC LIMIT ?", (q, limit)):
            seen.add(r["id"])
            out.append({"page": self._page(r), "snippet": ""})
        for r in self.db.execute("""
                SELECT p.*, b.text AS btext FROM blocks b JOIN pages p ON p.id=b.page_id
                WHERE p.trashed=0 AND b.text LIKE ? ORDER BY p.updated DESC LIMIT ?""", (q, limit)):
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            text = r["btext"]
            i = text.lower().find(query.lower())
            snippet = text[max(0, i - 30): i + len(query) + 50].replace("\n", " ")
            out.append({"page": self._page(r), "snippet": snippet})
        return out[:limit]

    def backlinks(self, page_id: str) -> list[dict]:
        rows = self.db.execute("""
            SELECT DISTINCT p.* FROM blocks b JOIN pages p ON p.id=b.page_id
            WHERE p.trashed=0 AND p.id != ?
              AND (b.content LIKE ? OR (b.type='link_to_page' AND b.props LIKE ?))""",
                               (page_id, f'%"page:{page_id}"%', f'%"page_id": "{page_id}"%'))
        return [self._page(r) for r in rows]
