# -*- coding: utf-8 -*-
"""
Fsm_1_2_12_AuthPreDialog - Пре-диалог авторизации перед загрузкой Web карт

Показывается перед запуском F_1_2. Позволяет пользователю:
- Увидеть статус авторизации НСПД
- Войти через Госуслуги (открывает Msm_40_1 browser dialog)
- Выйти из сессии НСПД
- Начать загрузку (с авторизацией или без)

Зависимости:
- M_40_NspdAuthManager (через registry)
"""

from typing import Optional, Any

from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGroupBox
)
from qgis.PyQt.QtCore import Qt

from Daman_QGIS.managers import registry
from Daman_QGIS.utils import log_info
from Daman_QGIS.core.base_responsive_dialog import BaseResponsiveDialog


class Fsm_1_2_12_AuthPreDialog(BaseResponsiveDialog):
    """Пре-диалог авторизации НСПД перед загрузкой Web карт.

    Компактный диалог с информацией о статусе авторизации
    и кнопками управления.
    """

    SIZING_MODE = 'content'
    MAX_WIDTH = 500
    MAX_HEIGHT = 400

    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]

        self.setWindowTitle("Загрузка Web карт")
        self.setFixedWidth(450)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowContextHelpButtonHint  # type: ignore[operator]
        )

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Создание интерфейса."""
        layout = QVBoxLayout(self)

        # Группа авторизации
        auth_group = QGroupBox("Авторизация НСПД")
        auth_layout = QHBoxLayout()

        self._status_label = QLabel()
        self._status_label.setMinimumWidth(150)
        auth_layout.addWidget(self._status_label)

        auth_layout.addStretch()

        self._login_btn = QPushButton()
        self._login_btn.setMinimumWidth(130)
        self._login_btn.clicked.connect(self._do_login)
        auth_layout.addWidget(self._login_btn)

        auth_group.setLayout(auth_layout)
        layout.addWidget(auth_group)

        # Информация
        info_label = QLabel(
            "Без авторизации некоторые слои\n"
            "(красные линии МИНСТРОЙ, линии отступа) будут недоступны."
        )
        info_label.setStyleSheet("color: #666; font-size: 9pt; padding: 4px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Кнопки
        btn_layout = QHBoxLayout()

        load_btn = QPushButton("Начать загрузку")
        load_btn.setMinimumWidth(140)
        load_btn.setDefault(True)
        load_btn.clicked.connect(self.accept)
        btn_layout.addWidget(load_btn)

        cancel_btn = QPushButton("Отмена")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        # Обновить статус
        self._update_status()

    def _update_status(self) -> None:
        """Обновление отображения статуса авторизации."""
        try:
            nspd_auth = registry.get('M_40')
        except Exception:
            nspd_auth = None

        if nspd_auth and nspd_auth.is_available() and nspd_auth.is_authenticated():
            self._status_label.setText("Авторизован")
            self._status_label.setStyleSheet(
                "color: green; font-weight: bold; font-size: 10pt;"
            )
            self._login_btn.setText("Выйти")
        elif nspd_auth and nspd_auth.is_available():
            self._status_label.setText("Не авторизован")
            self._status_label.setStyleSheet(
                "color: gray; font-size: 10pt;"
            )
            self._login_btn.setText("Войти в НСПД")
        else:
            self._status_label.setText("Недоступно")
            self._status_label.setStyleSheet(
                "color: orange; font-size: 10pt;"
            )
            self._login_btn.setText("Войти в НСПД")
            self._login_btn.setEnabled(False)

    def _do_login(self) -> None:
        """Обработка клика по кнопке авторизации."""
        try:
            nspd_auth = registry.get('M_40')
        except Exception:
            return

        if not nspd_auth or not nspd_auth.is_available():
            return

        if nspd_auth.is_authenticated():
            nspd_auth.logout()
            log_info("Fsm_1_2_12: Пользователь вышел из НСПД")
        else:
            nspd_auth.login(self)
            log_info("Fsm_1_2_12: Попытка авторизации НСПД")

        self._update_status()
