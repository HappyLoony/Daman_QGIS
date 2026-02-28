# -*- coding: utf-8 -*-
"""
F_4_1_PluginDiagnostics - Диагностика плагина Daman_QGIS

Координатор для диагностики плагина:
- Проверка и установка зависимостей (Python, шрифты, сертификаты)
- Комплексное тестирование модулей
- Сетевая диагностика и починка

Объединяет F_4_1 (зависимости) и F_4_2 (тестирование) в один инструмент.
"""

from typing import Dict

from qgis.PyQt.QtGui import QIcon

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.utils import log_info

from .submodules.Fsm_4_1_1_dependency_checker import DependencyChecker
from .submodules.Fsm_4_1_11_diagnostics_dialog import DiagnosticsDialog


class F_4_1_PluginDiagnostics(BaseTool):
    """Инструмент диагностики плагина"""

    # Этот инструмент НЕ требует лицензии (иначе невозможно установить зависимости)
    requires_license = False

    @property
    def name(self) -> str:
        """Имя инструмента"""
        return "4_1 Диагностика плагина"

    @property
    def icon(self) -> QIcon:
        """Иконка инструмента"""
        return QIcon(':/images/themes/default/mActionOptions.svg')

    @staticmethod
    def get_python_executable() -> str:
        """
        Находит правильный путь к python.exe в установке QGIS

        Returns:
            str: Путь к python.exe или sys.executable если не найден
        """
        from .submodules.Fsm_4_1_4_pip_installer import PipInstaller
        return PipInstaller.get_python_executable()

    @staticmethod
    def quick_check() -> bool:
        """
        Быстрая проверка зависимостей при запуске плагина.
        Записывает краткий результат в лог.

        Returns:
            bool: True если все зависимости установлены
        """
        return DependencyChecker.quick_check()

    # Делегация API DependencyChecker для доступа через координатор
    BUILTIN_DEPENDENCIES = DependencyChecker.BUILTIN_DEPENDENCIES

    @staticmethod
    def get_external_dependencies(include_optional: bool = True) -> Dict[str, Dict]:
        """
        Получить словарь внешних зависимостей из requirements.txt

        Args:
            include_optional: Включать опциональные зависимости

        Returns:
            dict: {имя_пакета: {version, optional, description}}
        """
        return DependencyChecker.get_external_dependencies(include_optional)

    @staticmethod
    def get_install_paths() -> Dict[str, str]:
        """
        Определение путей для установки библиотек

        Returns:
            dict: Словарь с путями установки
        """
        return DependencyChecker.get_install_paths()

    def run(self) -> None:
        """Запуск инструмента диагностики плагина"""
        log_info("F_4_1: Запущен инструмент диагностики плагина")
        python_exe = self.get_python_executable()
        log_info(f"F_4_1: Python для установки: {python_exe}")
        super().run()

    def create_dialog(self):
        """Создание диалога диагностики"""
        return DiagnosticsDialog(self.iface)
