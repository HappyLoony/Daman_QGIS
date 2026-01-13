# -*- coding: utf-8 -*-
"""
M_31_UpdateManager - Менеджер обновлений плагина.

Отвечает за:
- Проверку обновлений при запуске плагина
- Показ уведомления о доступном обновлении
- Переход на страницу скачивания

Зависимости:
- Msm_31_1_UpdateChecker - проверка через plugins.xml
"""

from typing import Optional
import webbrowser

from qgis.PyQt.QtCore import QSettings, QTimer
from qgis.PyQt.QtWidgets import QMessageBox, QPushButton
from qgis.core import Qgis
from qgis.gui import QgisInterface

from .submodules.Msm_31_1_update_checker import UpdateChecker, UpdateInfo
from ..utils import log_info, log_warning
from ..constants import (
    PLUGIN_NAME,
    UPDATE_CHECK_INTERVAL_DAYS,
    UPDATE_GITHUB_RELEASES_URL
)


# Синглтон
_update_manager_instance: Optional['UpdateManager'] = None


def get_update_manager() -> 'UpdateManager':
    """Получить экземпляр UpdateManager (синглтон)."""
    global _update_manager_instance
    if _update_manager_instance is None:
        _update_manager_instance = UpdateManager()
    return _update_manager_instance


class UpdateManager:
    """Менеджер обновлений плагина."""

    MODULE_ID = "M_31"
    SETTINGS_KEY = "Daman_QGIS/last_update_check"
    SETTINGS_SKIP_VERSION = "Daman_QGIS/skip_version"

    def __init__(self):
        self.iface: Optional[QgisInterface] = None
        self.checker = UpdateChecker(check_beta=False)  # Проверяем stable
        self._last_update_info: Optional[UpdateInfo] = None

    def set_iface(self, iface: QgisInterface) -> None:
        """Установить интерфейс QGIS."""
        self.iface = iface

    def check_on_startup(self, delay_ms: int = 5000) -> None:
        """
        Запланировать проверку обновлений после запуска.

        Args:
            delay_ms: Задержка перед проверкой (мс)
        """
        if not self._should_check():
            log_info(f"{self.MODULE_ID}: Проверка обновлений отложена (интервал не истек)")
            return

        # Отложенная проверка чтобы не замедлять запуск
        QTimer.singleShot(delay_ms, self._do_check)

    def _should_check(self) -> bool:
        """Проверить, нужно ли выполнять проверку обновлений."""
        from datetime import datetime, timedelta

        settings = QSettings()
        last_check_str = settings.value(self.SETTINGS_KEY, "")

        if not last_check_str:
            return True

        try:
            last_check = datetime.fromisoformat(last_check_str)
            interval = timedelta(days=UPDATE_CHECK_INTERVAL_DAYS)
            return datetime.now() - last_check > interval
        except (ValueError, TypeError):
            return True

    def _do_check(self) -> None:
        """Выполнить проверку обновлений."""
        from datetime import datetime

        log_info(f"{self.MODULE_ID}: Начало проверки обновлений")

        # Запоминаем время проверки
        settings = QSettings()
        settings.setValue(self.SETTINGS_KEY, datetime.now().isoformat())

        # Проверяем
        update_info = self.checker.check_for_updates()
        self._last_update_info = update_info

        if update_info.available:
            # Проверяем, не пропущена ли эта версия
            skip_version = settings.value(self.SETTINGS_SKIP_VERSION, "")
            if skip_version == update_info.latest_version:
                log_info(f"{self.MODULE_ID}: Версия {skip_version} пропущена пользователем")
                return

            self._show_update_notification(update_info)

    def _show_update_notification(self, update_info: UpdateInfo) -> None:
        """Показать уведомление о доступном обновлении."""
        if not self.iface:
            return

        channel = "beta" if update_info.is_beta else "stable"

        # Показываем в message bar
        self.iface.messageBar().pushMessage(
            PLUGIN_NAME,
            f"Доступна новая версия {update_info.latest_version} ({channel})",
            level=Qgis.Info,
            duration=10
        )

        log_info(
            f"{self.MODULE_ID}: Показано уведомление об обновлении "
            f"{update_info.current_version} -> {update_info.latest_version}"
        )

    def show_update_dialog(self) -> None:
        """Показать диалог обновления (можно вызвать вручную)."""
        if not self._last_update_info or not self._last_update_info.available:
            # Принудительная проверка
            update_info = self.checker.check_for_updates()
            self._last_update_info = update_info
        else:
            update_info = self._last_update_info

        if not update_info.available:
            QMessageBox.information(
                None,
                "Обновления",
                f"Установлена последняя версия: {update_info.current_version}"
            )
            return

        # Диалог с кнопками
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("Доступно обновление")
        msg.setText(
            f"Доступна новая версия плагина Daman QGIS!\n\n"
            f"Текущая версия: {update_info.current_version}\n"
            f"Новая версия: {update_info.latest_version}"
        )

        btn_download = msg.addButton("Скачать", QMessageBox.AcceptRole)
        btn_skip = msg.addButton("Пропустить эту версию", QMessageBox.RejectRole)
        btn_later = msg.addButton("Напомнить позже", QMessageBox.NoRole)

        msg.exec_()

        clicked = msg.clickedButton()

        if clicked == btn_download:
            self._open_download_page(update_info)
        elif clicked == btn_skip:
            self._skip_version(update_info.latest_version)

    def _open_download_page(self, update_info: UpdateInfo) -> None:
        """Открыть страницу скачивания."""
        url = update_info.download_url or UPDATE_GITHUB_RELEASES_URL
        log_info(f"{self.MODULE_ID}: Открытие страницы загрузки: {url}")
        webbrowser.open(url)

    def _skip_version(self, version: str) -> None:
        """Пропустить указанную версию."""
        settings = QSettings()
        settings.setValue(self.SETTINGS_SKIP_VERSION, version)
        log_info(f"{self.MODULE_ID}: Версия {version} добавлена в пропущенные")

    def force_check(self) -> Optional[UpdateInfo]:
        """Принудительная проверка обновлений."""
        update_info = self.checker.check_for_updates()
        self._last_update_info = update_info
        return update_info

    @property
    def last_update_info(self) -> Optional[UpdateInfo]:
        """Последняя информация об обновлении."""
        return self._last_update_info
