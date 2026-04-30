# -*- coding: utf-8 -*-
"""
M_43_FallbackToolbarManager - Управление резервными панелями инструментов

Резервные панели показываются когда:
- Лицензия не активирована (activation-only toolbar)
- Конфигурация не загрузилась (emergency toolbar)
- Лицензия отозвана сервером (revocation -> activation-only toolbar)
"""

from typing import Optional, Callable

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QToolBar, QToolButton, QMessageBox
from qgis.core import Qgis
from qgis.gui import QgisInterface

from Daman_QGIS.utils import log_info, log_error, log_warning


class FallbackToolbarManager:
    """Управление резервными панелями инструментов."""

    MODULE_ID = "M_43"

    def __init__(self, iface: QgisInterface) -> None:
        self.iface = iface
        self.toolbar: Optional[QToolBar] = None
        self._activation_only_mode: bool = False

        # Callbacks из main_plugin
        self._show_forced_activation: Optional[Callable[[], bool]] = None
        self._build_full_toolbar: Optional[Callable[[], None]] = None
        self._stop_heartbeat: Optional[Callable[[], None]] = None
        self._register_signal: Optional[Callable] = None
        self._init_telemetry: Optional[Callable[[], None]] = None

    def configure(
        self,
        show_forced_activation: Callable[[], bool],
        build_full_toolbar: Callable[[], None],
        stop_heartbeat: Callable[[], None],
        register_signal: Callable,
        init_telemetry: Callable[[], None],
    ) -> None:
        """Настройка callbacks из main_plugin.

        Args:
            show_forced_activation: Показ модального диалога активации
            build_full_toolbar: Построение полной панели инструментов
            stop_heartbeat: Остановка heartbeat таймера
            register_signal: Регистрация Qt сигнала для cleanup
            init_telemetry: Инициализация телеметрии
        """
        self._show_forced_activation = show_forced_activation
        self._build_full_toolbar = build_full_toolbar
        self._stop_heartbeat = stop_heartbeat
        self._register_signal = register_signal
        self._init_telemetry = init_telemetry

    @property
    def is_fallback_mode(self) -> bool:
        """Активен ли режим резервной панели."""
        return self._activation_only_mode

    # --- Public API ---

    def show_activation_only(self) -> None:
        """Показать минимальную панель с кнопкой активации лицензии."""
        from Daman_QGIS.constants import PLUGIN_NAME

        self._activation_only_mode = True

        self.toolbar = self.iface.addToolBar(PLUGIN_NAME)
        self.toolbar.setObjectName(PLUGIN_NAME)

        btn = QToolButton()
        btn.setText("  Активация лицензии Daman QGIS")
        btn.setIcon(QIcon(':/images/themes/default/mIconCertificate.svg'))
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        if self._register_signal:
            self._register_signal(btn.clicked, self._on_activation_button_clicked)

        self.toolbar.addWidget(btn)

        self.iface.messageBar().pushMessage(
            "Daman QGIS",
            "Для работы плагина необходимо активировать лицензию",
            level=Qgis.Warning, duration=0
        )

    def show_emergency(self, reason: str = "config") -> None:
        """Аварийная панель с диагностикой и управлением лицензией.

        Вызывается в двух сценариях:
        - reason="deps_install": первый запуск, отсутствуют Python-зависимости,
          фоновая установка запущена (main_plugin._start_background_dep_install).
          Отдельное сообщение не показываем — прогресс идёт через M_17 MessageBar.
        - reason="config" (default): Base_Functions.json не загрузился
          (нет JWT, сетевая ошибка, сервер недоступен). Показываем warning.

        Args:
            reason: Причина показа панели ("deps_install" или "config")
        """
        from Daman_QGIS.constants import PLUGIN_NAME

        self._activation_only_mode = True

        self.toolbar = self.iface.addToolBar(PLUGIN_NAME)
        self.toolbar.setObjectName(PLUGIN_NAME)

        # Кнопка F_4_1 -- Диагностика
        btn_diag = QToolButton()
        btn_diag.setText("  Диагностика плагина")
        btn_diag.setIcon(QIcon(':/images/themes/default/mActionOptions.svg'))
        btn_diag.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        if self._register_signal:
            self._register_signal(btn_diag.clicked, self._on_emergency_diagnostics)

        self.toolbar.addWidget(btn_diag)

        # Кнопка F_4_3 -- Управление лицензией
        btn_license = QToolButton()
        btn_license.setText("  Управление лицензией")
        btn_license.setIcon(QIcon(':/images/themes/default/mIconCertificate.svg'))
        btn_license.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        if self._register_signal:
            self._register_signal(btn_license.clicked, self._on_emergency_license)

        self.toolbar.addWidget(btn_license)

        # Телеметрия (лицензия уже есть)
        if self._init_telemetry:
            self._init_telemetry()

        if reason == "deps_install":
            # Фоновая установка запустит свой прогресс через M_17 MessageBar.
            # Здесь показываем вводное info, не warning (это ожидаемая ситуация
            # при первом запуске с vendored wheels).
            self.iface.messageBar().pushMessage(
                "Daman QGIS",
                "Первый запуск — устанавливаются Python-зависимости. "
                "Прогресс отображается ниже. По завершении перезапустите QGIS.",
                level=Qgis.Info, duration=0
            )
        else:
            self.iface.messageBar().pushMessage(
                "Daman QGIS",
                "Не удалось загрузить конфигурацию с сервера. "
                "Используйте 'Диагностика плагина' для установки зависимостей. "
                "После установки перезапустите QGIS.",
                level=Qgis.Warning, duration=0
            )

    def on_license_revoked(self) -> None:
        """Обработка отзыва лицензии сервером."""
        # 1. Остановить heartbeat
        if self._stop_heartbeat:
            self._stop_heartbeat()

        # 2. Очистить токены
        from Daman_QGIS.managers.infrastructure.submodules.Msm_29_4_token_manager import TokenManager
        TokenManager.get_instance().clear_tokens()

        # 2a. Сброс retry-history и UI-callback в AuthedRequestManager
        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_29_6_authed_request import (
                AuthedRequestManager,
            )
            AuthedRequestManager.reset_instance()
        except Exception as e:
            log_warning(f"M_43: AuthedRequestManager reset failed: {e}")

        # 3. Очистить кэш данных
        from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
        BaseReferenceLoader.clear_cache()

        # 4. Удалить текущую панель
        self._remove_toolbar()

        # 5. Показать панель активации
        self.show_activation_only()
        self.iface.messageBar().pushMessage(
            "Daman QGIS",
            "Лицензия деактивирована. Обратитесь к администратору.",
            level=Qgis.Warning, duration=0
        )

    def remove_toolbar(self) -> None:
        """Удалить текущую резервную панель (public)."""
        self._remove_toolbar()

    # --- Private ---

    def _remove_toolbar(self) -> None:
        """Удалить текущую панель инструментов."""
        if self.toolbar:
            main_window = self.iface.mainWindow()
            if main_window and hasattr(main_window, 'removeToolBar'):
                main_window.removeToolBar(self.toolbar)
            self.toolbar.deleteLater()
            self.toolbar = None

    def _on_activation_button_clicked(self) -> None:
        """Обработка клика на кнопку активации."""
        if not self._show_forced_activation:
            return

        activated = self._show_forced_activation()
        if activated:
            self._remove_toolbar()
            self.iface.messageBar().clearWidgets()
            self._activation_only_mode = False

            if self._build_full_toolbar:
                self._build_full_toolbar()

    def _on_emergency_diagnostics(self) -> None:
        """Запуск F_4_1 напрямую."""
        try:
            from Daman_QGIS.tools.F_4_plagin.submodules.Fsm_4_1_11_diagnostics_dialog import DiagnosticsDialog
            dialog = DiagnosticsDialog(self.iface)
            dialog.exec()
        except Exception as e:
            log_error(f"M_43: Failed to open diagnostics dialog: {e}")
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Daman QGIS",
                f"Не удалось открыть диагностику: {e}"
            )

    def _on_emergency_license(self) -> None:
        """Запуск F_4_3 напрямую."""
        try:
            from Daman_QGIS.tools.F_4_plagin.submodules.Fsm_4_3_1_license_dialog import LicenseDialog
            dialog = LicenseDialog(self.iface, self.iface.mainWindow())
            dialog.exec()
        except Exception as e:
            log_error(f"M_43: Failed to open license dialog: {e}")
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Daman QGIS",
                f"Не удалось открыть управление лицензией: {e}"
            )
