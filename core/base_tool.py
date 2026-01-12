# -*- coding: utf-8 -*-
"""
Base class for plugin tools
"""
from typing import Optional, Any
import os
from qgis.PyQt.QtGui import QIcon
from Daman_QGIS.managers import LayerCleanupManager
from qgis.core import QgsProject, Qgis
from Daman_QGIS.constants import MESSAGE_INFO_DURATION
from Daman_QGIS.managers import get_project_structure_manager
from Daman_QGIS.utils import log_error

class BaseTool:
    """Базовый класс для инструментов плагина"""

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
        if not self.dialog:
            self.dialog = self.create_dialog()

        # Показать диалог
        self.dialog.show()
        # Поднять окно наверх
        self.dialog.raise_()
        # Активировать окно
        self.dialog.activateWindow()
        
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
        structure_manager = get_project_structure_manager()
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
