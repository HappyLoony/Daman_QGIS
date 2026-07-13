# -*- coding: utf-8 -*-
"""
Fsm_4_1_2_FontChecker - Проверка установленных шрифтов

Проверяет наличие требуемых шрифтов канона M_49 в системе:
GOST 2.304 (чертёжный), Avenir Next W1G (мастер-план),
IBM Plex Sans (интерфейс плагина).
Источник списка — _font_canon.required_font_files()
"""

import sys
import os
from typing import Dict, Any, Set, List, Tuple

from qgis.core import Qgis
from Daman_QGIS.constants import PLUGIN_NAME, PLUGIN_DIR
from Daman_QGIS.managers.styling import _font_canon
from Daman_QGIS.utils import log_info, log_warning, log_error


class FontChecker:
    """Проверка установленных шрифтов"""

    # Назначение ролей канона для пользовательских отчётов
    # (единая формулировка Fsm_4_1_7 и Fsm_4_1_11)
    ROLE_PURPOSES: Dict[_font_canon.FontRole, str] = {
        _font_canon.FontRole.DRAWING: 'для DXF/AutoCAD',
        _font_canon.FontRole.MASTERPLAN: 'для мастер-плана',
        _font_canon.FontRole.PLUGIN_UI: 'для интерфейса плагина',
    }

    @staticmethod
    def get_plugin_fonts_dir() -> str:
        """
        Получить путь к папке со шрифтами плагина

        Returns:
            str: Путь к папке fonts
        """
        # Используем PLUGIN_DIR из constants.py - надёжный способ определения корня
        return os.path.join(PLUGIN_DIR, 'data', 'fonts')

    @staticmethod
    def get_required_fonts() -> List[str]:
        """
        Получить канон-список требуемых шрифтов (M_49 / _font_canon)

        Замена сканирования data/fonts целиком: проверяются и ставятся
        ТОЛЬКО файлы канона (без легаси из папки)

        Returns:
            list: Список файлов шрифтов
        """
        required_fonts = _font_canon.required_font_files()
        log_info(f"Fsm_4_1_2: Канон-список шрифтов: {len(required_fonts)} файлов")
        return required_fonts

    @staticmethod
    def group_missing_by_role(missing_fonts: List[str]) -> List[Tuple[int, str, str]]:
        """
        Сгруппировать отсутствующие шрифты по ролям канона M_49

        Единый источник формулировки для отчётов Fsm_4_1_7 (HTML)
        и Fsm_4_1_11 (plain text) — исключает рассинхрон

        Args:
            missing_fonts: Имена файлов отсутствующих шрифтов

        Returns:
            list: Кортежи (количество, семейство, назначение) для ролей
                с хотя бы одним отсутствующим файлом
        """
        missing_lower = {f.lower() for f in missing_fonts}
        groups: List[Tuple[int, str, str]] = []
        for role, files in _font_canon.FONT_FILES.items():
            count = sum(1 for f in files if f.lower() in missing_lower)
            if count > 0:
                purpose = FontChecker.ROLE_PURPOSES.get(role, '')
                groups.append((count, _font_canon.get_family(role), purpose))
        return groups

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

        log_info(f"Fsm_4_1_2: Найдено {len(system_fonts)} установленных системных шрифтов")

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
        Проверка установленных шрифтов по канон-списку M_49

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

        log_info(f"Fsm_4_1_2: Установлено {len(font_info['installed_fonts'])}, "
                 f"отсутствует {len(font_info['missing_fonts'])} шрифтов")

        return font_info
