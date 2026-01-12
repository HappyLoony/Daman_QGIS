# -*- coding: utf-8 -*-
"""
Сабмодуль экспорта в TAB (MapInfo)

Рефакторинг: Использует BaseExportSubmodule для устранения дублирования.
"""

from typing import Dict, Any, List

from .Fsm_1_5_0_base_export_submodule import BaseExportSubmodule
from ..core.tab_exporter import TabExporter


class TabExportSubmodule(BaseExportSubmodule):
    """Сабмодуль для экспорта в TAB формат"""

    FORMAT_NAME = "TAB (MapInfo)"
    EXPORTER_CLASS = TabExporter

    def __init__(self, iface):
        super().__init__(iface)

        # Параметры по умолчанию для TAB
        self.default_params.update({
            'create_wgs84': True,
            'use_non_earth': True,
            'clean_temp_files': True,
        })

    def _get_dialog_options(self, export_params: Dict[str, Any]) -> List[tuple]:
        """Опции для диалога TAB (пока не добавляем в диалог)"""
        # TAB экспорт не имеет дополнительных опций в диалоге
        return []

    def _get_exporter_params(self, export_params: Dict[str, Any]) -> Dict[str, Any]:
        """Параметры для TabExporter"""
        return {
            'create_wgs84': export_params['create_wgs84'],
            'use_non_earth': export_params['use_non_earth'],
            'clean_temp_files': export_params['clean_temp_files'],
        }
