# -*- coding: utf-8 -*-
"""
F_5_1_CheckDependencies - Проверка и установка зависимостей плагина Daman_QGIS

Координатор для проверки и автоматической установки зависимостей:
- Python библиотек
- Шрифтов GOST и OpenSans
- Корневых сертификатов Минцифры РФ

Без требования прав администратора.
"""

from typing import Dict

from qgis.PyQt.QtGui import QIcon
from qgis.core import Qgis

# Импорт базового класса
from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error

# Импорт субмодулей
from .submodules.Fsm_5_1_1_dependency_checker import DependencyChecker
from .submodules.Fsm_5_1_7_dependency_dialog import DependencyCheckDialog


class F_5_1_CheckDependencies(BaseTool):
    """Инструмент проверки и установки зависимостей"""

    # Ссылки на методы/константы из DependencyChecker для обратной совместимости
    BUILTIN_DEPENDENCIES = DependencyChecker.BUILTIN_DEPENDENCIES

    @classmethod
    def get_external_dependencies(cls) -> Dict:
        """Получить внешние зависимости из requirements.txt"""
        return DependencyChecker.get_external_dependencies()

    @property
    def name(self) -> str:
        """Имя инструмента"""
        return "5_1 Проверка зависимостей"

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
        from .submodules.Fsm_5_1_4_pip_installer import PipInstaller
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

    @staticmethod
    def get_install_paths() -> Dict[str, str]:
        """
        Определение путей для установки библиотек

        Returns:
            dict: Словарь с путями установки
        """
        return DependencyChecker.get_install_paths()

    def run(self) -> None:
        """Запуск инструмента проверки зависимостей"""
        log_info("F_5_1: Запущен инструмент проверки зависимостей")
        # Получаем Python еще раз при запуске GUI
        python_exe = self.get_python_executable()
        log_info(f"F_5_1: Python для установки: {python_exe}")
        # Вызываем родительский метод
        super().run()

    def create_dialog(self):
        """Создание диалога проверки зависимостей"""
        return DependencyCheckDialog(self.iface)
