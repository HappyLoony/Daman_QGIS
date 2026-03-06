# -*- coding: utf-8 -*-
"""
F_6_3: Список файлов в папке.

Сканирование выбранной папки с отображением содержимого (имя, размер, тип, дата)
и экспортом списка файлов в clipboard или TXT-файл.

Использует QFileSystemModel для потокового сканирования и отображения.
"""

from typing import Optional

from Daman_QGIS.utils import log_info
from Daman_QGIS.core.base_tool import BaseTool

from .submodules.Fsm_6_3_1_dialog import Fsm_6_3_1_Dialog


class F_6_3_FileLister(BaseTool):
    """Список файлов в папке с экспортом в clipboard/TXT."""

    def __init__(self, iface):
        super().__init__(iface)
        self.dialog: Optional[Fsm_6_3_1_Dialog] = None

    def run(self) -> None:
        """Запуск функции."""
        if self.requires_license and not self._check_license_access():
            return

        log_info("F_6_3: Запуск функции Список файлов в папке")

        self.dialog = Fsm_6_3_1_Dialog(self.iface.mainWindow())
        self.dialog.exec()
