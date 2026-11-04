"""Account picker / unlock screen."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..core.accounts import AccountError
from ..core.crypto import DecryptionError
from .protection import ProtectionWizard, busy


class LoginWindow(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.c = controller
        self.setObjectName("LoginRoot")
        self.setWindowTitle(APP_NAME)
        self.resize(900, 640)

        outer = QVBoxLayout(self)
        outer.addStretch(1)
        h = QHBoxLayout()
        h.addStretch(1)
        card = QFrame()
        card.setObjectName("Card")
        card.setFixedWidth(440)
        h.addWidget(card)
        h.addStretch(1)
        outer.addLayout(h)
        outer.addStretch(2)

        v = QVBoxLayout(card)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(10)
        title = QLabel(f"📓  {APP_NAME}")
        title.setObjectName("H1")
        v.addWidget(title)
        sub = QLabel(f"Choose an account · v{__version__}")
        sub.setObjectName("Muted")
        v.addWidget(sub)

        self.list = QListWidget()
        self.list.setMinimumHeight(180)
        self.list.currentItemChanged.connect(self._selected)
        self.list.itemActivated.connect(lambda _: self.primary())
        v.addWidget(self.list)

        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret.setPlaceholderText("Password, passphrase or seed phrase")
        self.secret.returnPressed.connect(self.primary)
        v.addWidget(self.secret)
        self.show_cb = QPushButton("👁")
        self.show_cb.setObjectName("Flat")
        self.show_cb.setCheckable(True)
        self.show_cb.setFixedWidth(36)
        self.show_cb.toggled.connect(lambda on: self.secret.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        self.err = QLabel()
        self.err.setObjectName("Error")
        self.err.setWordWrap(True)
        v.addWidget(self.err)

        row = QHBoxLayout()
        row.addWidget(self.show_cb)
        row.addStretch(1)
        self.go = QPushButton("Open")
        self.go.setObjectName("Primary")
        self.go.clicked.connect(self.primary)
        row.addWidget(self.go)
        v.addLayout(row)

        bottom = QHBoxLayout()
        create = QPushButton("＋  Create account")
        create.setObjectName("SideButton")
        create.clicked.connect(self.create)
        bottom.addWidget(create)
        bottom.addStretch(1)
        delete = QPushButton("Delete…")
        delete.setObjectName("SideButton")
        delete.clicked.connect(self.delete)
        bottom.addWidget(delete)
        v.addLayout(bottom)
        self.refresh()

    def refresh(self, select: str | None = None):
        self.c.accounts.ensure_guest()
        select = select or self.c.config.get("last_user")
        self.list.clear()
        for acc in self.c.accounts.list_accounts():
            icon = "👤" if acc.is_guest else ("🔒" if acc.encrypted else "🔓")
            note = "  (no password)" if acc.is_guest else ("" if acc.encrypted else "  (not encrypted)")
            it = QListWidgetItem(f"{icon}   {acc.username}{note}")
            it.setData(Qt.ItemDataRole.UserRole, acc.username)
            self.list.addItem(it)
            if select and acc.username == select:
                self.list.setCurrentItem(it)
        if not self.list.currentItem() and self.list.count():
            self.list.setCurrentRow(0)

    def account(self):
        it = self.list.currentItem()
        return self.c.accounts.get(it.data(Qt.ItemDataRole.UserRole)) if it else None

    def _selected(self, *_):
        acc = self.account()
        enc = bool(acc and acc.encrypted)
        self.secret.setVisible(enc)
        self.show_cb.setVisible(enc)
        self.secret.clear()
        self.err.clear()
        self.go.setText("Unlock" if enc else "Open")
        if enc:
            self.secret.setFocus()

    def primary(self):
        acc = self.account()
        if not acc:
            return
        try:
            if acc.encrypted:
                if not self.secret.text():
                    self.secret.setFocus()
                    return
                with busy():
                    store = self.c.accounts.unlock(acc, self.secret.text())
            else:
                store = self.c.accounts.open_unprotected(acc)
        except (AccountError, DecryptionError) as e:
            self.err.setText(str(e))
            self.secret.selectAll()
            return
        self.secret.clear()
        self.c.on_unlocked(acc, store)

    def create(self):
        w = ProtectionWizard(self, mode="create",
                             existing_users=[a.username for a in self.c.accounts.list_accounts()])
        if not w.exec():
            return
        try:
            with busy():
                acc, store = self.c.accounts.create_account(w.username, w.credentials)
        except AccountError as e:
            QMessageBox.critical(self, "Could not create account", str(e))
            return
        self.refresh(acc.username)
        self.c.on_unlocked(acc, store, first_run=True)

    def delete(self):
        acc = self.account()
        if not acc:
            return
        if QMessageBox.warning(self, "Delete account",
                               f"Permanently delete “{acc.username}” and ALL of its pages?\nThis cannot be undone.",
                               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) \
                != QMessageBox.StandardButton.Yes:
            return
        if acc.encrypted:
            text, ok = QInputDialog.getText(self, "Confirm", "Enter a password / passphrase / seed phrase:",
                                            QLineEdit.EchoMode.Password)
            if not ok:
                return
            with busy():
                if not self.c.accounts.verify(acc, text):
                    QMessageBox.warning(self, "Incorrect", "That didn't match. Account not deleted.")
                    return
        else:
            text, ok = QInputDialog.getText(self, "Confirm", f"Type the username “{acc.username}” to confirm:")
            if not ok or text.strip() != acc.username:
                return
        self.c.accounts.delete_account(acc)
        self.refresh()
