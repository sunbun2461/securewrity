"""Core tests: run with  python3 -m unittest discover -s tests"""
import tempfile
import unittest
from pathlib import Path

from folio.core import crypto
from folio.core.accounts import AccountError, AccountManager
from folio.core.repo import Repo
from folio.core.seed import generate_passphrase, generate_seed_phrase, validate_seed_phrase

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
        blob = (acc.directory / "data.folio").read_bytes()
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
