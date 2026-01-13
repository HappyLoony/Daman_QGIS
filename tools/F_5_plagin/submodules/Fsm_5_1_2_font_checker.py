# -*- coding: utf-8 -*-
"""
Fsm_5_1_2_FontChecker - Проверка установленных шрифтов

Проверяет наличие требуемых шрифтов GOST и OpenSans в системе
"""

import sys
import os
from typing import Dict, Any, Set, List

from qgis.core import Qgis
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error


class FontChecker:
    """Проверка установленных шрифтов"""

    @staticmethod
    def get_plugin_fonts_dir() -> str:
        """
        Получить путь к папке со шрифтами плагина

        Returns:
            str: Путь к папке fonts
        """
        plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        fonts_dir = os.path.join(plugin_dir, 'data', 'fonts')
        return fonts_dir

    @staticmethod
    def get_required_fonts() -> List[str]:
        """
        Получить список требуемых шрифтов из папки плагина

        Returns:
            list: Список файлов шрифтов
        """
        fonts_dir = FontChecker.get_plugin_fonts_dir()
        required_fonts = []

        log_info(f"Fsm_5_1_2: Путь к шрифтам: {fonts_dir}")

        if os.path.exists(fonts_dir):
            for file in os.listdir(fonts_dir):
                if file.endswith(('.ttf', '.otf')):
                    required_fonts.append(file)
            log_info(f"Fsm_5_1_2: Найдено {len(required_fonts)} файлов шрифтов для проверки")
        else:
            log_warning(f"Fsm_5_1_2: Папка шрифтов не существует: {fonts_dir}")

        return required_fonts

    @staticmethod
    def get_system_fonts() -> Set[str]:
        """
        Получить список установленных системных шрифтов (только Windows)

        Returns:
            set: Множество имен файлов шрифтов (в lowercase)
        """
        system_fonts = set()

        if sys.platform == 'win32':
            font_paths = [
                os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts'),
                os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Windows', 'Fonts')
            ]

            for font_path in font_paths:
                if font_path and os.path.exists(font_path):
                    try:
                        for file in os.listdir(font_path):
                            if file.endswith(('.ttf', '.otf')):
                                system_fonts.add(file.lower())
                    except Exception:
                        pass

        log_info(f"Fsm_5_1_2: Найдено {len(system_fonts)} установленных системных шрифтов")

        return system_fonts

    @staticmethod
    def is_font_installed(font_file: str, system_fonts: Set[str]) -> bool:
        """
        Проверить установлен ли шрифт в системе

        Args:
            font_file: Имя файла шрифта
            system_fonts: Множество установленных шрифтов

        Returns:
            bool: True если шрифт установлен
        """
        return font_file.lower() in system_fonts

    @staticmethod
    def check_fonts() -> Dict[str, Any]:
        """
        Проверка установленных шрифтов из папки resources/styles/fonts

        Returns:
            dict: Информация о шрифтах
                - all_fonts_installed: bool
                - missing_fonts: list
                - installed_fonts: list
        """
        font_info = {
            'all_fonts_installed': True,
            'missing_fonts': [],
            'installed_fonts': []
        }

        # Получаем требуемые и системные шрифты
        required_fonts = FontChecker.get_required_fonts()
        system_fonts = FontChecker.get_system_fonts()

        # Проверяем каждый требуемый шрифт
        for font_file in required_fonts:
            if FontChecker.is_font_installed(font_file, system_fonts):
                font_info['installed_fonts'].append(font_file)
            else:
                font_info['missing_fonts'].append(font_file)
                font_info['all_fonts_installed'] = False

        log_info(f"Fsm_5_1_2: Установлено {len(font_info['installed_fonts'])}, "
                 f"отсутствует {len(font_info['missing_fonts'])} шрифтов")

        return font_info
