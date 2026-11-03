"""Wizard for choosing protection (none / password / passphrase / seed phrase),
plus the Security dialog for managing an account's encryption."""
from __future__ import annotations

import random
import time

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame,
                             QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMessageBox, QPushButton, QRadioButton,
                             QStackedWidget, QVBoxLayout, QWidget)

from ..core.accounts import USERNAME_RE, AccountError, validate_credential
from ..core.seed import generate_passphrase, generate_seed_phrase, normalize_phrase, password_strength

DESCRIPTIONS = {
    "none": "No encryption. Fastest to open, but anyone who can read your home folder can read your notes.",
    "password": "Encrypt everything with a password (AES-256-GCM, scrypt key derivation).",
    "passphrase": "Encrypt with a multi-word passphrase — long, memorable and very strong. "
                  "Folio can generate one for you.",
    "seed": "Folio generates a 12 or 24-word seed phrase. That phrase is the only key — "
            "write it down and keep it safe.",
}


class busy:
    """Context manager: wait cursor during slow key derivation."""

    def __enter__(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()

    def __exit__(self, *a):
        QApplication.restoreOverrideCursor()


class ProtectionWizard(QDialog):
    """mode: 'create' (new account), 'encrypt' (protect an existing account),
    'add' (add one more credential), or 'replace:<type>' (change a credential)."""

    def __init__(self, parent=None, mode="create", existing_users=()):
        super().__init__(parent)
        self.mode = mode
        self.existing = {u.lower() for u in existing_users}
        self.username = ""
        self.credentials: list[tuple[str, str, str]] = []
        self.seed = ""
        self.setWindowTitle({"create": "Create account", "encrypt": "Encrypt this account",
                             "add": "Add a way to unlock"}.get(mode, "Change credential"))
        self.setMinimumWidth(560)

        lay = QVBoxLayout(self)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.err = QLabel()
        self.err.setObjectName("Error")
        self.err.setWordWrap(True)
        lay.addWidget(self.err)
        nav = QHBoxLayout()
        nav.addStretch(1)
        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(self.back)
        self.next_btn = QPushButton("Next")
        self.next_btn.setObjectName("Primary")
        self.next_btn.setDefault(True)
        self.next_btn.clicked.connect(self.next)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        nav.addWidget(cancel)
        nav.addWidget(self.back_btn)
        nav.addWidget(self.next_btn)
        lay.addLayout(nav)

        self.pages = {"choose": self._page_choose(), "secret": self._page_secret(),
                      "seed": self._page_seed(), "confirm": self._page_confirm()}
        for w in self.pages.values():
            self.stack.addWidget(w)
        self.step = 0
        if mode.startswith("replace:"):
            kind = mode.split(":", 1)[1]
            self.radios[kind].setChecked(True)
            self.step = 1
        self._go()

    # --- pages ---------------------------------------------------------------
    def _page_choose(self):
        w = QWidget()
        v = QVBoxLayout(w)
        if self.mode == "create":
            title = QLabel("Create a new account")
            title.setObjectName("H1")
            v.addWidget(title)
            v.addWidget(QLabel("Username"))
            self.user_edit = QLineEdit()
            self.user_edit.setPlaceholderText("e.g. thomas")
            v.addWidget(self.user_edit)
            v.addSpacing(10)
        v.addWidget(QLabel("<b>How should this account be protected?</b>"))
        self.group = QButtonGroup(self)
        self.radios = {}
        options = [("password", "🔑  Password"), ("passphrase", "📝  Passphrase"), ("seed", "🌱  Seed phrase")]
        if self.mode == "create":
            options.insert(0, ("none", "🔓  None (no encryption)"))
        for key, label in options:
            r = QRadioButton(label)
            self.radios[key] = r
            self.group.addButton(r)
            d = QLabel(DESCRIPTIONS[key])
            d.setObjectName("Muted")
            d.setWordWrap(True)
            d.setContentsMargins(28, 0, 0, 6)
            v.addWidget(r)
            v.addWidget(d)
            r.toggled.connect(self._choice_changed)
        self.recovery = QCheckBox("Also create a recovery seed phrase (recommended) — unlocks the account "
                                  "if you forget your password")
        self.recovery.setChecked(True)
        if self.mode in ("create", "encrypt"):
            v.addSpacing(6)
            v.addWidget(self.recovery)
        else:
            self.recovery.setChecked(False)
        (self.radios.get("password") if self.mode != "create" else self.radios["none"]).setChecked(True)
        v.addStretch(1)
        return w

    def _page_secret(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.secret_title = QLabel()
        self.secret_title.setObjectName("H1")
        v.addWidget(self.secret_title)
        self.secret_hint = QLabel()
        self.secret_hint.setObjectName("Muted")
        self.secret_hint.setWordWrap(True)
        v.addWidget(self.secret_hint)
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret.textChanged.connect(self._strength)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm.setPlaceholderText("Confirm")
        v.addWidget(self.secret)
        v.addWidget(self.confirm)
        row = QHBoxLayout()
        self.show_cb = QCheckBox("Show")
        self.show_cb.toggled.connect(self._toggle_show)
        row.addWidget(self.show_cb)
        self.gen_btn = QPushButton("🎲  Generate passphrase")
        self.gen_btn.clicked.connect(self._generate_pp)
        row.addWidget(self.gen_btn)
        row.addStretch(1)
        self.strength = QLabel()
        row.addWidget(self.strength)
        v.addLayout(row)
        warn = QLabel("⚠  There is no “forgot password”. Without this (or a recovery seed phrase) "
                      "your notes cannot be recovered.")
        warn.setWordWrap(True)
        warn.setObjectName("Muted")
        v.addSpacing(8)
        v.addWidget(warn)
        v.addStretch(1)
        return w

    def _page_seed(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.seed_title = QLabel("Your seed phrase")
        self.seed_title.setObjectName("H1")
        v.addWidget(self.seed_title)
        hint = QLabel("Write these words down <b>in order</b> and store them somewhere safe and offline. "
                      "Anyone with these words can open this account.")
        hint.setWordWrap(True)
        v.addWidget(hint)
        row = QHBoxLayout()
        self.seed_len = QComboBox()
        self.seed_len.addItems(["12 words", "24 words"])
        self.seed_len.currentIndexChanged.connect(self._new_seed)
        row.addWidget(self.seed_len)
        regen = QPushButton("↻  New phrase")
        regen.clicked.connect(self._new_seed)
        row.addWidget(regen)
        copy = QPushButton("Copy")
        copy.setToolTip("Copies to the clipboard — clear it afterwards!")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.seed))
        row.addWidget(copy)
        row.addStretch(1)
        v.addLayout(row)
        self.seed_frame = QFrame()
        self.seed_frame.setObjectName("Card")
        self.seed_grid = QGridLayout(self.seed_frame)
        v.addWidget(self.seed_frame)
        self.wrote = QCheckBox("I have written down my seed phrase")
        v.addWidget(self.wrote)
        v.addStretch(1)
        self._new_seed()
        return w

    def _page_confirm(self):
        w = QWidget()
        v = QVBoxLayout(w)
        t = QLabel("Confirm your seed phrase")
        t.setObjectName("H1")
        v.addWidget(t)
        v.addWidget(QLabel("Enter the requested words to prove you saved the phrase."))
        self.confirm_grid = QGridLayout()
        v.addLayout(self.confirm_grid)
        self.confirm_edits = []
        v.addStretch(1)
        return w

    # --- behaviour -----------------------------------------------------------
    def choice(self) -> str:
        for k, r in self.radios.items():
            if r.isChecked():
                return k
        return "none"

    def _choice_changed(self):
        c = self.choice()
        self.recovery.setEnabled(c in ("password", "passphrase"))

    def flow(self) -> list[str]:
        c = self.choice()
        if c == "none":
            return ["choose"]
        if c == "seed":
            return ["choose", "seed", "confirm"]
        steps = ["choose", "secret"]
        if self.recovery.isChecked() and self.recovery.isEnabled() and self.mode in ("create", "encrypt"):
            steps += ["seed", "confirm"]
        return steps

    def _go(self):
        steps = self.flow()
        self.step = max(0, min(self.step, len(steps) - 1))
        name = steps[self.step]
        if name == "secret":
            c = self.choice()
            self.secret_title.setText("Choose a password" if c == "password" else "Choose a passphrase")
            self.secret_hint.setText("At least 8 characters. Longer is better." if c == "password" else
                                     "At least 4 words. Use the generator for a strong random one.")
            self.secret.setPlaceholderText("Password" if c == "password" else "e.g. orbit-velvet-candle-harbor-mango-tribe")
            self.gen_btn.setVisible(c == "passphrase")
        if name == "seed":
            self.seed_title.setText("Your recovery seed phrase" if self.choice() != "seed" else "Your seed phrase")
        if name == "confirm":
            self._build_confirm()
        self.stack.setCurrentWidget(self.pages[name])
        self.back_btn.setEnabled(self.step > 0 and not self.mode.startswith("replace:"))
        last = self.step == len(steps) - 1
        self.next_btn.setText(("Create account" if self.mode == "create" else "Finish") if last else "Next")
        self.err.setText("")

    def back(self):
        self.step -= 1
        self._go()

    def next(self):
        steps = self.flow()
        name = steps[self.step]
        err = self._validate(name)
        if err:
            self.err.setText(err)
            return
        if self.step == len(steps) - 1:
            self._finish()
            return
        self.step += 1
        self._go()

    def _validate(self, name) -> str | None:
        if name == "choose" and self.mode == "create":
            u = self.user_edit.text().strip()
            if not USERNAME_RE.match(u):
                return "Username: 1-32 letters, digits, '.', '_' or '-' (no spaces)."
            if u.lower() in self.existing or u.lower() == "guest":
                return "That username is taken."
        if name == "secret":
            if self.secret.text() != self.confirm.text():
                return "The two entries don't match."
            return validate_credential(self.choice(), self.secret.text())
        if name == "seed" and not self.wrote.isChecked():
            return "Please confirm you have written the phrase down."
        if name == "confirm":
            words = self.seed.split()
            for idx, edit in self.confirm_edits:
                if normalize_phrase(edit.text()) != words[idx]:
                    return f"Word #{idx + 1} is not correct."
        return None

    def _finish(self):
        if self.mode == "create":
            self.username = self.user_edit.text().strip()
        creds = []
        c = self.choice()
        stamp = time.strftime("%Y-%m-%d")
        if c in ("password", "passphrase"):
            creds.append((c, self.secret.text(), f"{c.capitalize()} ({stamp})"))
        if "seed" in self.flow():
            label = "Seed phrase" if c == "seed" else "Recovery seed phrase"
            creds.append(("seed", self.seed, f"{label} ({stamp})"))
        self.credentials = creds
        self.accept()

    def _toggle_show(self, on):
        mode = QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
        self.secret.setEchoMode(mode)
        self.confirm.setEchoMode(mode)

    def _generate_pp(self):
        pp = generate_passphrase(6)
        self.secret.setText(pp)
        self.confirm.setText(pp)
        self.show_cb.setChecked(True)

    def _strength(self, text):
        score, label = password_strength(text)
        colors = ["#E5534B", "#E5534B", "#CA9849", "#529E72", "#529E72"]
        self.strength.setText(f"<span style='color:{colors[score]}'>{label}</span>" if text else "")

    def _new_seed(self, *_):
        n = 24 if self.seed_len.currentIndex() == 1 else 12
        self.seed = generate_seed_phrase(n)
        while self.seed_grid.count():
            self.seed_grid.takeAt(0).widget().deleteLater()
        mono = QFont("Monospace")
        mono.setPixelSize(15)
        cols = 3 if n == 12 else 4
        rows = (n + cols - 1) // cols
        for i, wd in enumerate(self.seed.split()):
            lab = QLabel(f"<span style='color:gray'>{i + 1:>2}.</span> <b>{wd}</b>")
            lab.setFont(mono)
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.seed_grid.addWidget(lab, i % rows, i // rows)
        if hasattr(self, "wrote"):
            self.wrote.setChecked(False)

    def _build_confirm(self):
        while self.confirm_grid.count():
            self.confirm_grid.takeAt(0).widget().deleteLater()
        words = self.seed.split()
        picks = sorted(random.SystemRandom().sample(range(len(words)), 3))
        self.confirm_edits = []
        for r, idx in enumerate(picks):
            self.confirm_grid.addWidget(QLabel(f"Word #{idx + 1}"), r, 0)
            e = QLineEdit()
            self.confirm_grid.addWidget(e, r, 1)
            self.confirm_edits.append((idx, e))


class SecurityDialog(QDialog):
    """Shows encryption status; encrypt now, add/replace/remove credentials, decrypt."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Security & encryption")
        self.setMinimumWidth(560)
        self.lay = QVBoxLayout(self)
        self.render()

    def render(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                _clear_layout(it.layout())
        acc, store = self.ctx.account, self.ctx.store
        if acc.is_guest:
            self.lay.addWidget(QLabel("<h2>🔓 Guest account</h2>"))
            m = QLabel("The Guest account is never encrypted. Create a user account from the login "
                       "screen (or Lock → Create account) to protect your notes. "
                       "Tip: you can move pages between accounts with Markdown export.")
            m.setWordWrap(True)
            self.lay.addWidget(m)
        elif not store.encrypted:
            self.lay.addWidget(QLabel("<h2>🔓 Not encrypted</h2>"))
            m = QLabel("Your notes are stored as a plain SQLite file:<br><code>%s</code>" % store.plain_path)
            m.setWordWrap(True)
            m.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.lay.addWidget(m)
            b = QPushButton("🔒  Encrypt now…")
            b.setObjectName("Primary")
            b.clicked.connect(self.encrypt_now)
            self.lay.addWidget(b)
        else:
            self.lay.addWidget(QLabel("<h2>🔒 Encrypted</h2>"))
            m = QLabel("AES-256-GCM, keys derived with scrypt. The database only exists decrypted "
                       f"in memory while unlocked.<br><code>{store.enc_path}</code>")
            m.setWordWrap(True)
            m.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.lay.addWidget(m)
            self.lay.addWidget(QLabel("<b>Ways to unlock this account</b>"))
            self.slots = QListWidget()
            icons = {"password": "🔑", "passphrase": "📝", "seed": "🌱"}
            for s in acc.slots:
                it = QListWidgetItem(f"{icons.get(s['type'], '•')}  {s.get('label', s['type'])}")
                it.setData(Qt.ItemDataRole.UserRole, s)
                self.slots.addItem(it)
            self.slots.setMaximumHeight(140)
            self.lay.addWidget(self.slots)
            row = QHBoxLayout()
            for text, fn in (("Add…", self.add), ("Replace selected…", self.replace), ("Remove selected", self.remove)):
                b = QPushButton(text)
                b.clicked.connect(fn)
                row.addWidget(b)
            row.addStretch(1)
            self.lay.addLayout(row)
            self.lay.addSpacing(10)
            d = QPushButton("Remove encryption…")
            d.setObjectName("Danger")
            d.clicked.connect(self.decrypt)
            self.lay.addWidget(d)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        self.lay.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)

    def _verify(self, prompt="Enter a current password, passphrase or seed phrase to continue:") -> bool:
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "Confirm it's you", prompt, QLineEdit.EchoMode.Password)
        if not ok:
            return False
        with busy():
            good = self.ctx.controller.accounts.verify(self.ctx.account, text)
        if not good:
            QMessageBox.warning(self, "Incorrect", "That didn't match any credential.")
        return good

    def encrypt_now(self):
        w = ProtectionWizard(self, mode="encrypt")
        if not w.exec():
            return
        self.ctx.window.editor.save_now()
        try:
            with busy():
                self.ctx.controller.accounts.enable_encryption(self.ctx.account, self.ctx.store, w.credentials)
        except AccountError as e:
            QMessageBox.critical(self, "Error", str(e))
            return
        self.ctx.window.setup_autolock()
        QMessageBox.information(self, "Encrypted", "Your account is now encrypted. "
                                "The unencrypted file was overwritten and deleted.")
        self.render()

    def add(self):
        w = ProtectionWizard(self, mode="add")
        if not w.exec():
            return
        try:
            with busy():
                for ctype, secret, label in w.credentials:
                    self.ctx.controller.accounts.add_credential(self.ctx.account, self.ctx.store, ctype, secret, label)
        except AccountError as e:
            QMessageBox.critical(self, "Error", str(e))
        self.render()

    def _selected(self):
        it = self.slots.currentItem() if hasattr(self, "slots") else None
        if not it:
            QMessageBox.information(self, "Select", "Select a credential in the list first.")
            return None
        return it.data(Qt.ItemDataRole.UserRole)

    def replace(self):
        slot = self._selected()
        if not slot or not self._verify():
            return
        w = ProtectionWizard(self, mode=f"replace:{slot['type']}")
        if not w.exec():
            return
        mgr = self.ctx.controller.accounts
        try:
            with busy():
                for ctype, secret, label in w.credentials:
                    mgr.add_credential(self.ctx.account, self.ctx.store, ctype, secret, label)
                mgr.remove_credential(self.ctx.account, slot["id"])
        except AccountError as e:
            QMessageBox.critical(self, "Error", str(e))
        self.render()

    def remove(self):
        slot = self._selected()
        if not slot:
            return
        if len(self.ctx.account.slots) <= 1:
            QMessageBox.information(self, "Last credential",
                                    "This is the only way to unlock the account. Add another first, "
                                    "or use “Remove encryption”.")
            return
        if not self._verify():
            return
        self.ctx.controller.accounts.remove_credential(self.ctx.account, slot["id"])
        self.render()

    def decrypt(self):
        if QMessageBox.warning(self, "Remove encryption",
                               "Your notes will be stored unencrypted on disk. Continue?",
                               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) \
                != QMessageBox.StandardButton.Yes:
            return
        if not self._verify():
            return
        self.ctx.window.editor.save_now()
        with busy():
            self.ctx.controller.accounts.disable_encryption(self.ctx.account, self.ctx.store)
        self.ctx.window.setup_autolock()
        self.render()


def _clear_layout(layout):
    while layout.count():
        it = layout.takeAt(0)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            _clear_layout(it.layout())
