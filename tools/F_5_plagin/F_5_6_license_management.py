# -*- coding: utf-8 -*-
"""
F_5_6_LicenseManagement - Управление лицензией Daman_QGIS

Координатор для:
- Активации/деактивации лицензии
- Просмотра статуса лицензии
- Информации о Hardware ID
"""

from qgis.PyQt.QtGui import QIcon

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.utils import log_info

from .submodules.Fsm_5_6_1_license_dialog import LicenseDialog


class F_5_6_LicenseManagement(BaseTool):
    """Инструмент управления лицензией"""

    @property
    def name(self) -> str:
        """Имя инструмента"""
        return "5_6 Управление лицензией"

    @property
    def icon(self) -> QIcon:
        """Иконка инструмента"""
        return QIcon(':/images/themes/default/mIconCertificate.svg')

    def run(self) -> None:
        """Запуск инструмента управления лицензией"""
        log_info("F_5_6: Запущен инструмент управления лицензией")
        super().run()

    def create_dialog(self):
        """Создание диалога управления лицензией"""
        return LicenseDialog(self.iface)
