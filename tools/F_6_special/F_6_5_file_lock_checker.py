# -*- coding: utf-8 -*-
"""
F_6_5: Проверка блокировок файлов.

Сканирование выбранной папки на наличие заблокированных файлов
(lock-маркеры AutoCAD/Office/LibreOffice + exclusive open test).
Отображение таблицы: файл, пользователь, компьютер, программа.
"""

from typing import Optional

from Daman_QGIS.utils import log_info
from Daman_QGIS.core.base_tool import BaseTool

from .submodules.Fsm_6_5_1_dialog import Fsm_6_5_1_Dialog


class F_6_5_FileLockChecker(BaseTool):
    """Проверка блокировок файлов в папке."""

    def __init__(self, iface):
        super().__init__(iface)
        self.dialog: Optional[Fsm_6_5_1_Dialog] = None

    def run(self) -> None:
        """Запуск функции."""
        if self.requires_license and not self._check_license_access():
            return

        log_info("F_6_5: Запуск функции Проверка блокировок файлов")

        self.dialog = Fsm_6_5_1_Dialog(self.iface.mainWindow())
        self.dialog.exec()
