# -*- coding: utf-8 -*-
"""
F_6_4: Выборка файлов по списку.

Копирование/перемещение файлов из папки по заданному списку имён
с фильтрацией по расширениям. Поддержка масок * и ? (fnmatch).

Wizard из 4 шагов:
1. Выбор папки
2. Ввод списка имён + live preview
3. Настройки операции (расширения, режим copy/move)
4. Выполнение + отчёт
"""

from typing import Optional

from Daman_QGIS.utils import log_info
from Daman_QGIS.core.base_tool import BaseTool

from .submodules.Fsm_6_4_1_dialog import Fsm_6_4_1_Dialog


class F_6_4_FileSelector(BaseTool):
    """Выборка файлов по списку с копированием/перемещением."""

    def __init__(self, iface):
        super().__init__(iface)
        self.dialog: Optional[Fsm_6_4_1_Dialog] = None

    def run(self) -> None:
        """Запуск функции."""
        if self.requires_license and not self._check_license_access():
            return

        log_info("F_6_4: Запуск функции Выборка файлов по списку")

        self.dialog = Fsm_6_4_1_Dialog(self.iface.mainWindow())
        self.dialog.exec()
