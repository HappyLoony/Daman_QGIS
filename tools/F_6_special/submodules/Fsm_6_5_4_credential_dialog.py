# -*- coding: utf-8 -*-
"""
Fsm_6_5_4: Диалог ввода credentials администратора сети.

Используется для получения прав на принудительное закрытие файлов
на сетевой шаре через NetFileEnum / NetFileClose.
"""

import ctypes
from typing import Optional, Tuple

from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from Daman_QGIS.utils import log_info


class Fsm_6_5_4_CredentialDialog(QDialog):
    """Диалог ввода логина и пароля администратора."""

    def __init__(self, server_name: str, parent: Optional[QDialog] = None):
        super().__init__(parent)
        self.setWindowTitle("Учётные данные администратора")
        self.setMinimumWidth(380)

        self._server = server_name
        self._result: Optional[Tuple[str, str, str]] = None

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        info_label = QLabel(
            f"Для принудительного закрытия файлов на сервере "
            f"<b>{server_name}</b> требуются права администратора."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        form = QFormLayout()
        form.setSpacing(6)

        self._edt_username = QLineEdit()
        self._edt_username.setPlaceholderText("DOMAIN\\admin или admin@domain")
        form.addRow("Логин:", self._edt_username)

        self._edt_password = QLineEdit()
        self._edt_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._edt_password.setPlaceholderText("Пароль администратора")
        form.addRow("Пароль:", self._edt_password)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        """Валидация и парсинг credentials."""
        raw_user = self._edt_username.text().strip()
        raw_pass = self._edt_password.text()

        if not raw_user or not raw_pass:
            return

        # Парсинг формата: DOMAIN\user или user@domain
        domain = ""
        username = raw_user

        if "\\" in raw_user:
            parts = raw_user.split("\\", 1)
            domain = parts[0]
            username = parts[1]
        elif "@" in raw_user:
            parts = raw_user.split("@", 1)
            username = parts[0]
            domain = parts[1]

        self._result = (username, domain, raw_pass)
        log_info(
            f"Fsm_6_5_4: Credentials accepted for {domain}\\{username}"
        )
        self.accept()

    def get_credentials(self) -> Optional[Tuple[str, str, str]]:
        """Вернуть (username, domain, password) или None."""
        return self._result

    def _clear_password(self) -> None:
        """Очистить пароль из памяти (best effort)."""
        self._edt_password.clear()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._clear_password()
        super().closeEvent(event)
