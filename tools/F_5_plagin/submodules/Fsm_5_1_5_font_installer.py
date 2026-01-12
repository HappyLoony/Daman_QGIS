# -*- coding: utf-8 -*-
"""
Fsm_5_1_5_FontInstaller - Установка шрифтов в Windows

Устанавливает шрифты GOST и OpenSans в систему Windows
без требования прав администратора
"""

import sys
import os
import shutil
from typing import List, Tuple, Callable, Optional

from qgis.core import QgsMessageLog, Qgis


class FontInstaller:
    """Установка шрифтов в Windows"""

    def __init__(self, fonts_dir: str, fonts_list: List[str], progress_callback: Optional[Callable] = None):
        """
        Инициализация установщика шрифтов

        Args:
            fonts_dir: Путь к папке со шрифтами
            fonts_list: Список файлов шрифтов для установки
            progress_callback: Функция обратного вызова для отчета о прогрессе
        """
        self.fonts_dir = fonts_dir
        self.fonts_list = fonts_list
        self.progress_callback = progress_callback

    def emit_progress(self, message: str):
        """Отправить сообщение о прогрессе"""
        if self.progress_callback:
            self.progress_callback(message)
    def _try_user_folder(self, source_path: str, font_file: str) -> bool:
        """
        Попытка установки шрифта в пользовательскую папку (без прав админа)

        Args:
            source_path: Путь к файлу шрифта
            font_file: Имя файла шрифта

        Returns:
            bool: True если успешно установлен
        """
        import ctypes

        user_fonts_folder = os.path.join(
            os.environ.get('LOCALAPPDATA', ''),
            'Microsoft', 'Windows', 'Fonts'
        )

        if not user_fonts_folder or not os.environ.get('LOCALAPPDATA'):
            return False

        # Создаем папку если не существует
        os.makedirs(user_fonts_folder, exist_ok=True)
        dest_path = os.path.join(user_fonts_folder, font_file)

        if not os.path.exists(dest_path):
            shutil.copy2(source_path, dest_path)
            self.emit_progress(f"Копирован в пользовательскую папку: {font_file}")

        # Регистрируем шрифт
        gdi32 = ctypes.WinDLL('gdi32')
        result = gdi32.AddFontResourceW(dest_path)

        if result > 0:
            self.emit_progress(f"✓ Шрифт {font_file} установлен (пользовательская папка)")
            return True

        return False
    def _try_system_folder(self, source_path: str, font_file: str) -> bool:
        """
        Попытка установки шрифта в системную папку (требуются права админа)

        Args:
            source_path: Путь к файлу шрифта
            font_file: Имя файла шрифта

        Returns:
            bool: True если успешно установлен
        """
        import ctypes

        fonts_folder = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts')
        dest_path = os.path.join(fonts_folder, font_file)

        if not os.path.exists(dest_path):
            shutil.copy2(source_path, dest_path)
            self.emit_progress(f"Копирован в системную папку: {font_file}")

        # Регистрируем шрифт
        gdi32 = ctypes.WinDLL('gdi32')
        result = gdi32.AddFontResourceW(dest_path)

        if result > 0:
            self.emit_progress(f"✓ Шрифт {font_file} установлен (системная папка)")
            return True

        return False
    def _try_temp_registration(self, source_path: str, font_file: str) -> bool:
        """
        Временная регистрация шрифта из папки плагина (только для текущей сессии)

        Args:
            source_path: Путь к файлу шрифта
            font_file: Имя файла шрифта

        Returns:
            bool: True если успешно зарегистрирован
        """
        import ctypes

        # Регистрируем прямо из папки плагина
        gdi32 = ctypes.WinDLL('gdi32')
        result = gdi32.AddFontResourceW(source_path)

        if result > 0:
            self.emit_progress(f"✓ Шрифт {font_file} временно зарегистрирован для текущей сессии")
            self.emit_progress(f"  (потребуется установка после перезагрузки QGIS)")
            return True
        else:
            self.emit_progress(f"✗ Не удалось установить {font_file}")
            self.emit_progress(f"  Установите вручную с правами администратора")
            return False

    def install_font(self, font_file: str) -> Tuple[bool, str]:
        """
        Установка одного шрифта (пробует 3 варианта)

        Args:
            font_file: Имя файла шрифта

        Returns:
            tuple: (успешно, сообщение_об_ошибке)
        """
        source_path = os.path.join(self.fonts_dir, font_file)

        if not os.path.exists(source_path):
            error_msg = f"Файл шрифта не найден: {source_path}"
            self.emit_progress(f"✗ {error_msg}")
            return False, error_msg

        # Вариант 1: Пробуем пользовательскую папку шрифтов (без прав админа)
        if self._try_user_folder(source_path, font_file):
            return True, ""

        # Вариант 2: Если не удалось в пользовательскую, пробуем системную
        if self._try_system_folder(source_path, font_file):
            return True, ""

        # Вариант 3: Временная регистрация из папки плагина
        if self._try_temp_registration(source_path, font_file):
            return True, "Шрифт временно зарегистрирован"

        return False, f"Не удалось установить {font_file}"

    def install_all(self) -> Tuple[int, List[str]]:
        """
        Установка всех шрифтов

        Returns:
            tuple: (количество_установленных, список_ошибок)
        """
        if sys.platform != 'win32':
            self.emit_progress("⚠ Установка шрифтов доступна только для Windows")
            self.emit_progress("Установите шрифты вручную из папки data/fonts")
            return 0, ["Установка шрифтов доступна только для Windows"]

        self.emit_progress("\nУстановка шрифтов...")

        fonts_installed = 0
        errors = []

        for font_file in self.fonts_list:
            success, error_msg = self.install_font(font_file)
            if success:
                fonts_installed += 1
            else:
                if error_msg and "временно" not in error_msg:
                    errors.append(error_msg)

        # Оповещаем систему об изменении шрифтов
        if fonts_installed > 0:
            try:
                import ctypes
                user32 = ctypes.WinDLL('user32')
                HWND_BROADCAST = 0xFFFF
                WM_FONTCHANGE = 0x001D
                user32.SendMessageW(HWND_BROADCAST, WM_FONTCHANGE, 0, 0)
                self.emit_progress(f"Установлено шрифтов: {fonts_installed}")
            except Exception:
                pass

        return fonts_installed, errors
