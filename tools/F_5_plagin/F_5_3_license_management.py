# -*- coding: utf-8 -*-
"""
F_5_3_LicenseManagement - Управление лицензией Daman_QGIS

Координатор для:
- Активации/деактивации лицензии
- Просмотра статуса лицензии
- Информации о Hardware ID
"""

from qgis.PyQt.QtGui import QIcon

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.utils import log_info

from .submodules.Fsm_5_3_1_license_dialog import LicenseDialog


class F_5_3_LicenseManagement(BaseTool):
    """Инструмент управления лицензией"""

    # Этот инструмент НЕ требует лицензии (иначе её невозможно активировать)
    requires_license = False

    @property
    def name(self) -> str:
        """Имя инструмента"""
        return "5_3 Управление лицензией"

    @property
    def icon(self) -> QIcon:
        """Иконка инструмента"""
        return QIcon(':/images/themes/default/mIconCertificate.svg')

    def run(self) -> None:
        """Запуск инструмента управления лицензией"""
        log_info("F_5_3: Запущен инструмент управления лицензией")

        # Очищаем кэш лицензий при каждом открытии диалога (для отладки)
        from Daman_QGIS.managers.submodules.Msm_29_3_license_validator import LicenseValidator
        LicenseValidator.clear_cache()
        log_info("F_5_3: Кэш лицензий очищен")

        super().run()

    def create_dialog(self):
        """Создание диалога управления лицензией"""
        return LicenseDialog(self.iface)
