# -*- coding: utf-8 -*-
"""
EulaDialog - Диалог лицензионного соглашения (EULA).

Показывается при первом запуске плагина.
Пользователь должен принять условия для продолжения работы.
Согласие сохраняется в QgsSettings.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QTextEdit, QCheckBox, QPushButton, QLabel
)


class EulaDialog(QDialog):
    """Модальный диалог лицензионного соглашения."""

    def __init__(self, eula_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Daman QGIS -- Лицензионное соглашение")
        self.setMinimumSize(600, 500)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
        )

        self._accepted = False
        self._setup_ui(eula_text)

    def _setup_ui(self, eula_text: str) -> None:
        """Создание элементов интерфейса."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Заголовок
        header = QLabel("Пожалуйста, ознакомьтесь с условиями использования:")
        header.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(header)

        # Текст EULA
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(eula_text)
        layout.addWidget(text_edit)

        # Чекбокс принятия
        self._checkbox = QCheckBox("Я прочитал(а) и принимаю условия лицензионного соглашения")
        self._checkbox.stateChanged.connect(self._on_checkbox_changed)
        layout.addWidget(self._checkbox)

        # Кнопки
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self._btn_accept = QPushButton("Принять")
        self._btn_accept.setEnabled(False)
        self._btn_accept.setMinimumWidth(120)
        self._btn_accept.clicked.connect(self._on_accept)
        button_layout.addWidget(self._btn_accept)

        self._btn_reject = QPushButton("Отказаться")
        self._btn_reject.setMinimumWidth(120)
        self._btn_reject.clicked.connect(self._on_reject)
        button_layout.addWidget(self._btn_reject)

        layout.addLayout(button_layout)

    def _on_checkbox_changed(self, state: int) -> None:
        """Активация кнопки 'Принять' при установке чекбокса."""
        self._btn_accept.setEnabled(state == Qt.CheckState.Checked)

    def _on_accept(self) -> None:
        """Пользователь принял EULA."""
        self._accepted = True
        self.accept()

    def _on_reject(self) -> None:
        """Пользователь отказался от EULA."""
        self._accepted = False
        self.reject()

    def is_accepted(self) -> bool:
        """Было ли принято соглашение."""
        return self._accepted
