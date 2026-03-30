# -*- coding: utf-8 -*-
"""
Base class for plugin tools
"""
from typing import Optional, Any
import os
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QMessageBox
from Daman_QGIS.managers import LayerCleanupManager
from qgis.core import QgsProject, Qgis
from Daman_QGIS.constants import MESSAGE_INFO_DURATION
from Daman_QGIS.managers import registry
from Daman_QGIS.utils import log_error, log_warning

class BaseTool:
    """Базовый класс для инструментов плагина"""

    # Флаг: требуется ли лицензия для этого инструмента
    # Переопределите в False для F_4_1 (зависимости) и F_4_3 (управление лицензией)
    requires_license = True

    def __init__(self, iface: Any) -> None:
        """Инициализация инструмента

        :param iface: Интерфейс QGIS
        :type iface: QgsInterface
        """
        self.iface = iface
        self.dialog = None
        self.cleanup_manager = LayerCleanupManager()

    @property
    def icon(self) -> QIcon:
        """Иконка инструмента"""
        # Стандартная иконка, может быть переопределена
        return QIcon(':/images/themes/default/mActionOptions.svg')
        
    def run(self) -> None:
        """Запуск инструмента"""
        # Проверка лицензии
        if self.requires_license and not self._check_license_access():
            return

        if not self.dialog:
            self.dialog = self.create_dialog()

        # Показать диалог
        self.dialog.show()
        # Поднять окно наверх
        self.dialog.raise_()
        # Активировать окно
        self.dialog.activateWindow()

    def _check_license_access(self) -> bool:
        """
        Проверка доступа по лицензии.

        Returns:
            True если доступ разрешён, False если заблокирован
        """
        try:
            license_manager = registry.get('M_29')

            if not license_manager.check_access():
                # Лицензия не активна - показываем диалог
                log_warning("BaseTool: License check failed, access denied")
                self._show_license_required_dialog()
                return False

            # Проверка уровня доступа к конкретной функции
            required = getattr(self, 'required_access', 'qgis')
            if not license_manager.has_access(required):
                log_warning(f"BaseTool: Недостаточный уровень доступа: {required}")
                return False

            return True

        except Exception as e:
            # FAIL-CLOSED: при ошибке проверки - блокируем доступ (OWASP Fail Securely)
            log_error(f"BaseTool: License check error: {e}")
            return False

    def _show_license_required_dialog(self):
        """Показать диалог о необходимости лицензии."""
        reply = QMessageBox.warning(
            None,
            "Требуется лицензия",
            "Для использования этой функции требуется активная лицензия.\n\n"
            "Активируйте лицензию через меню:\n"
            "Daman QGIS -> Плагин -> Управление лицензией",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Open,
            QMessageBox.StandardButton.Open
        )

        if reply == QMessageBox.StandardButton.Open:
            self._open_license_dialog()

    def _open_license_dialog(self):
        """Открыть диалог управления лицензией."""
        try:
            from Daman_QGIS.tools.F_4_plagin.F_4_3_license_management import F_4_3_LicenseManagement
            license_tool = F_4_3_LicenseManagement(self.iface)
            license_tool.run()
        except Exception as e:
            log_error(f"BaseTool: Failed to open license dialog: {e}")

    def create_dialog(self) -> Any:
        """Создание диалога инструмента

        Должен быть переопределен в наследниках
        """
        raise NotImplementedError("Необходимо реализовать create_dialog()")

    def auto_cleanup_layers(self) -> None:
        """Автоматическая очистка слоев перед выполнением функции

        Вызывайте этот метод в начале run() каждой функции, которая создает слои.
        Функция автоматически определит свое имя через get_name() и удалит
        существующие слои согласно Base_layers.json
        """
        if hasattr(self, 'get_name'):
            function_name = self.get_name()
            if function_name:
                self.cleanup_manager.cleanup_for_function(function_name)

    def get_name(self) -> Optional[str]:
        """Получить имя функции для использования в cleanup

        Должен быть переопределен в наследниках, которые создают слои.
        Возвращает имя функции в формате из Base_layers.json
        (например, "F_1_2_Загрузка Web карт", "F_2_2_Категории ЗУ")

        Returns:
            str: Имя функции
        """
        return None

    def check_project_opened(self) -> bool:
        """
        Проверка, что проект плагина открыт и валиден

        Returns:
            bool: True если проект открыт и содержит project.gpkg
        """
        project_path = QgsProject.instance().absolutePath()
        if not project_path:
            error_msg = "Сначала откройте или создайте проект через инструменты плагина"
            log_error(f"BaseTool: {error_msg}")
            self.iface.messageBar().pushMessage(
                "Ошибка",
                error_msg,
                level=Qgis.Critical,
                duration=MESSAGE_INFO_DURATION
            )
            return False

        # Используем M_19 для получения пути к GPKG
        structure_manager = registry.get('M_19')
        structure_manager.project_root = project_path
        gpkg_path = structure_manager.get_gpkg_path(create=False)

        if not gpkg_path or not os.path.exists(gpkg_path):
            error_msg = f"Не найден project.gpkg в {project_path}. Откройте проект через '0_2 Открыть проект'"
            log_error(f"BaseTool: {error_msg}")
            self.iface.messageBar().pushMessage(
                "Ошибка",
                "Не найден project.gpkg. Откройте проект через '0_2 Открыть проект'",
                level=Qgis.Critical,
                duration=MESSAGE_INFO_DURATION
            )
            return False

        return True
