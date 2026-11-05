"""Core tests: run with  python3 -m unittest discover -s tests"""
import tempfile
import unittest
from pathlib import Path

from securewrity.core import crypto
from securewrity.core.accounts import AccountError, AccountManager
from securewrity.core.repo import Repo
from securewrity.core.seed import generate_passphrase, generate_seed_phrase, validate_seed_phrase

FAST_KDF = {"name": "scrypt", "n": 2 ** 10, "r": 8, "p": 1}
crypto.DEFAULT_KDF = FAST_KDF  # keep tests quick


class SeedTests(unittest.TestCase):
    def test_known_vector(self):
        # BIP39 test vector: all-zero entropy
        ok, _ = validate_seed_phrase("abandon " * 11 + "about")
        self.assertTrue(ok)
        ok, _ = validate_seed_phrase("abandon " * 12)
        self.assertFalse(ok)

    def test_generated_valid(self):
        for n in (12, 24):
            for _ in range(20):
                self.assertTrue(validate_seed_phrase(generate_seed_phrase(n))[0])

    def test_passphrase(self):
        self.assertEqual(len(generate_passphrase(6).split("-")), 6)


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mgr = AccountManager(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_guest_and_plain(self):
        g = self.mgr.ensure_guest()
        self.assertFalse(g.encrypted)
        store = self.mgr.open_unprotected(g)
        repo = Repo(store)
        pid = repo.create_page(title="Hello")
        store.close()
        repo = Repo(self.mgr.open_unprotected(g))
        self.assertEqual(repo.get_page(pid)["title"], "Hello")

    def test_password_and_seed_unlock(self):
        seed = generate_seed_phrase(12)
        acc, store = self.mgr.create_account(
            "alice", [("password", "correct horse!", ""), ("seed", seed, "Recovery")])
        repo = Repo(store)
        pid = repo.create_page(title="Secret plans")
        repo.save_blocks(pid, [{"type": "toggle_h1", "content": [{"t": "Top"}],
                                "props": {"collapsed": True},
                                "children": [{"type": "paragraph", "content": [{"t": "inside", "b": 1}]}]}])
        store.close()
        blob = (acc.directory / "data.securewrity").read_bytes()
        self.assertNotIn(b"Secret plans", blob)
        self.assertFalse((acc.directory / "data.db").exists())

        with self.assertRaises(AccountError):
            self.mgr.unlock(acc, "wrong password")
        for secret in ("correct horse!", "  " + seed.upper() + " "):
            repo = Repo(self.mgr.unlock(self.mgr.get("alice"), secret))
            self.assertEqual(repo.get_page(pid)["title"], "Secret plans")
            tree = repo.get_blocks(pid)
            self.assertEqual(tree[0]["children"][0]["content"][0]["t"], "inside")
            repo.store.close()

    def test_encrypt_later_then_decrypt(self):
        acc, store = self.mgr.create_account("bob", [])
        repo = Repo(store)
        pid = repo.create_page(title="Plain page")
        self.mgr.enable_encryption(acc, store, [("passphrase", "purple monkey dishwasher lamp", "")])
        repo.update_page(pid, title="Now encrypted")
        store.close()
        self.assertFalse((acc.directory / "data.db").exists())
        store = self.mgr.unlock(self.mgr.get("bob"), "purple monkey dishwasher lamp")
        repo = Repo(store)
        self.assertEqual(repo.get_page(pid)["title"], "Now encrypted")
        # change credential: add password, remove passphrase
        acc = self.mgr.get("bob")
        self.mgr.add_credential(acc, store, "password", "newpassword1")
        self.mgr.remove_credential(acc, acc.slots[0]["id"])
        with self.assertRaises(AccountError):
            self.mgr.unlock(self.mgr.get("bob"), "purple monkey dishwasher lamp")
        # remove encryption
        self.mgr.disable_encryption(acc, store)
        store.close()
        repo = Repo(self.mgr.open_unprotected(self.mgr.get("bob")))
        self.assertEqual(repo.get_page(pid)["title"], "Now encrypted")

    def test_validation(self):
        with self.assertRaises(AccountError):
            self.mgr.create_account("x", [("password", "short", "")])
        with self.assertRaises(AccountError):
            self.mgr.create_account("bad name!", [])
        with self.assertRaises(AccountError):
            self.mgr.create_account("y", [("seed", "abandon " * 12, "")])


class RepoTests(unittest.TestCase):
    def test_tree_search_backlinks_trash(self):
        with tempfile.TemporaryDirectory() as t:
            mgr = AccountManager(Path(t))
            _, store = mgr.create_account("c", [])
            r = Repo(store)
            a = r.create_page(title="Alpha")
            b = r.create_page(parent_id=a, title="Beta")
            c = r.create_page(parent_id=b, title="Gamma")
            r.save_blocks(c, [{"type": "paragraph", "content": [{"t": "see "}, {"t": "Alpha", "link": f"page:{a}"}]}])
            self.assertEqual([p["title"] for p in r.ancestors(c)], ["Alpha", "Beta"])
            self.assertEqual([p["id"] for p in r.backlinks(a)], [c])
            self.assertEqual(r.search("see")[0]["page"]["id"], c)
            r.move_page(a, c, 0)  # cycle -> ignored
            self.assertIsNone(r.get_page(a)["parent_id"])
            r.trash_page(b)
            self.assertTrue(r.get_page(c)["trashed"])
            r.restore_page(b)
            self.assertFalse(r.get_page(c)["trashed"])
            r.delete_page(a)
            self.assertIsNone(r.get_page(c))
            store.close()


if __name__ == "__main__":
    unittest.main()


class CrashSafetyTests(unittest.TestCase):
    """Simulate a crash at each step of saving an encrypted account."""

    def setUp(self):
        import os
        from securewrity.core.storage import Store
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.dek = os.urandom(32)
        self.Store = Store

    def tearDown(self):
        self.tmp.cleanup()

    def _save_version(self, text):
        s = self.Store(self.dir, "acct", self.dek).open()
        s.conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
        s.conn.execute("DELETE FROM t")
        s.conn.execute("INSERT INTO t VALUES (?)", (text,))
        s.close()

    def _read(self):
        s = self.Store(self.dir, "acct", self.dek).open()
        v = s.conn.execute("SELECT v FROM t").fetchone()[0]
        rec = s.recovered_from
        s.conn.close()
        return v, rec

    def test_normal_save_keeps_backup(self):
        self._save_version("one")
        self._save_version("two")
        self.assertEqual(self._read(), ("two", None))
        self.assertTrue((self.dir / "data.securewrity.bak").exists())
        self.assertFalse((self.dir / "data.securewrity.tmp").exists())

    def test_crash_after_tmp_written_before_rename(self):
        self._save_version("one")
        self._save_version("two")
        main = self.dir / "data.securewrity"
        # the old (pre-fix) failure window: main renamed away, new data still in .tmp
        main.rename(self.dir / "data.securewrity.tmp")
        self.assertEqual(self._read(), ("two", "data.securewrity.tmp"))

    def test_main_missing_uses_backup_never_blank(self):
        self._save_version("one")
        self._save_version("two")
        (self.dir / "data.securewrity").unlink()
        v, rec = self._read()
        self.assertEqual((v, rec), ("one", "data.securewrity.bak"))

    def test_damaged_main_uses_backup(self):
        self._save_version("one")
        self._save_version("two")
        main = self.dir / "data.securewrity"
        blob = bytearray(main.read_bytes())
        blob[-5] ^= 0xFF
        main.write_bytes(bytes(blob))
        self.assertEqual(self._read(), ("one", "data.securewrity.bak"))

    def test_half_written_tmp_is_ignored(self):
        self._save_version("one")
        (self.dir / "data.securewrity.tmp").write_bytes(b"SECUREWRITYv1\ngarbage")
        self.assertEqual(self._read(), ("one", None))

    def test_everything_damaged_raises(self):
        self._save_version("one")
        self._save_version("two")
        for name in ("data.securewrity", "data.securewrity.bak"):
            (self.dir / name).write_bytes(b"SECUREWRITYv1\nxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        with self.assertRaises(crypto.DecryptionError):
            self._read()


class MarkdownImportTests(unittest.TestCase):
    def setUp(self):
        from securewrity.core.markdown_import import parse_markdown
        self.parse = parse_markdown

    def test_toggle_heading_scope_and_nesting(self):
        t = self.parse("▶ ## A\ntext\n- one\n  - nested\n## B\nafter")
        self.assertEqual([b["type"] for b in t], ["toggle_h2", "h2", "paragraph"])
        self.assertEqual([b["type"] for b in t[0]["children"]], ["paragraph", "bullet"])
        self.assertEqual(t[0]["children"][1]["children"][0]["type"], "bullet")

    def test_notion_flavoured(self):
        t = self.parse('## Day {toggle="true" color="purple"}\n\t- <span color="red">rent</span>\n'
                       '<callout icon="⚠️">Careful</callout>')
        self.assertEqual(t[0]["type"], "toggle_h2")
        self.assertEqual(t[0]["props"]["color"], "purple")
        self.assertEqual(t[0]["children"][0]["content"], [{"t": "rent", "c": "red"}])
        self.assertEqual((t[1]["type"], t[1]["props"]["emoji"]), ("callout", "⚠️"))

    def test_inline_and_blocks(self):
        t = self.parse("**b** *i* `c` [l](https://x) ~~s~~\n- [x] done\n---\n```py\nx = 1\n```\n#### h")
        runs = t[0]["content"]
        self.assertEqual([r for r in runs if r["t"] == "b"][0]["b"], 1)
        self.assertEqual([r for r in runs if r["t"] == "l"][0]["link"], "https://x")
        self.assertEqual([b["type"] for b in t], ["paragraph", "todo", "divider", "code", "h4"])
        self.assertTrue(t[1]["props"]["checked"])
        self.assertEqual(t[3]["content"][0]["t"], "x = 1")

    def test_details_and_pastel_colors(self):
        t = self.parse('<details><summary>Hi</summary>\ninside\n</details>\n'
                       '<span color="pastel mint background">m</span>')
        self.assertEqual((t[0]["type"], t[0]["children"][0]["content"][0]["t"]), ("toggle", "inside"))
        self.assertEqual(t[1]["content"][0]["bg"], "mint")

    def test_escapes_and_plain_text(self):
        t = self.parse(r"price \*not italic\* and a_snake_case_name")
        self.assertEqual(t[0]["content"], [{"t": "price *not italic* and a_snake_case_name"}])

    def test_arrow_toggles_take_following_lines(self):
        t = self.parse("▶ One\n\nfirst\n\n▶ Two\n\nsecond\n")
        self.assertEqual([b["type"] for b in t], ["toggle", "toggle"])
        self.assertEqual(t[0]["children"][0]["content"][0]["t"], "first")
        self.assertEqual(t[1]["children"][0]["content"][0]["t"], "second")

    def test_toggles_in_a_row_stay_siblings(self):
        t = self.parse("# ▶ One\n\n## ▶ Two\n\n### ▶ Three\n\n> ▶ Plain")
        self.assertEqual([b["type"] for b in t], ["toggle_h1", "toggle_h2", "toggle_h3", "toggle"])
        self.assertTrue(all(not b["children"] for b in t))
        t = self.parse("## ▶ Big\nintro\n▶ small\ninside small")
        self.assertEqual([b["type"] for b in t], ["toggle_h2", "toggle"])
        self.assertEqual([c["content"][0]["t"] for c in t[0]["children"]], ["intro"])
        self.assertEqual([c["content"][0]["t"] for c in t[1]["children"]], ["inside small"])


class FolderImportTests(unittest.TestCase):
    """Folders and Notion export zips import as pages with sub-pages."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _, self.store = AccountManager(self.root / "data").create_account("imp", [])
        self.repo = Repo(self.store)
        hx = "0123456789abcdef0123456789abcdef"
        exp = self.root / "export"
        (exp / f"Trip {hx}").mkdir(parents=True)
        (exp / f"Trip {hx}.md").write_text(
            f"# Trip\n\nPlans below.\n\n[Day 1](Trip%20{hx}/Day%201%20{hx}.md)\n\n"
            f"See [the list](Trip%20{hx}/Packing%20{hx}.md) too.\n")
        (exp / f"Trip {hx}" / f"Day 1 {hx}.md").write_text("# Day 1\n\n- fly\n")
        (exp / f"Trip {hx}" / f"Packing {hx}.md").write_text("# Packing\n\n- [ ] socks\n")
        (exp / f"Trip {hx}" / "photo.png").write_bytes(b"x")
        self.exp = exp

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _check(self, tops):
        from securewrity.core.md_tree import import_paths  # noqa: F401
        self.assertEqual(len(tops), 1)
        trip = self.repo.get_page(tops[0])
        self.assertEqual(trip["title"], "Trip")
        kids = {p["title"]: p["id"] for p in self.repo.list_pages() if p["parent_id"] == trip["id"]}
        self.assertEqual(set(kids), {"Day 1", "Packing"})
        blocks = self.repo.get_blocks(trip["id"])
        self.assertEqual([b["type"] for b in blocks], ["paragraph", "page", "paragraph"])
        self.assertEqual(blocks[1]["props"]["page_id"], kids["Day 1"])
        link = [r for r in blocks[2]["content"] if r.get("link")][0]
        self.assertEqual(link["link"], f"page:{kids['Packing']}")
        self.assertEqual(self.repo.get_blocks(kids["Packing"])[0]["type"], "todo")

    def test_folder(self):
        from securewrity.core.md_tree import import_paths
        tops, count = import_paths(self.repo, [self.exp])
        self.assertEqual(count, 3)
        self._check(tops)

    def test_notion_zip_with_inner_zip(self):
        import shutil
        import zipfile
        from securewrity.core.md_tree import import_paths
        inner = self.root / "Part-1.zip"
        shutil.make_archive(str(inner.with_suffix("")), "zip", self.exp)
        outer = self.root / "Export.zip"
        with zipfile.ZipFile(outer, "w") as z:
            z.write(inner, "Part-1.zip")
        tops, count = import_paths(self.repo, [outer])
        self.assertEqual(count, 3)
        self._check(tops)

    def test_loose_notes_get_a_wrapper_page_and_import_under_a_parent(self):
        from securewrity.core.md_tree import import_paths
        notes = self.root / "Notes"
        notes.mkdir()
        (notes / "a.md").write_text("alpha")
        (notes / "b.md").write_text("beta")
        parent = self.repo.create_page(title="Inbox")
        tops, count = import_paths(self.repo, [notes], parent_id=parent)
        self.assertEqual(count, 3)
        wrapper = self.repo.get_page(tops[0])
        self.assertEqual((wrapper["title"], wrapper["parent_id"]), ("Notes", parent))
        kids = [p["title"] for p in self.repo.list_pages() if p["parent_id"] == wrapper["id"]]
        self.assertEqual(kids, ["a", "b"])
