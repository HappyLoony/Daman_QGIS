# -*- coding: utf-8 -*-
"""
Сабмодуль экспорта в GeoJSON

Рефакторинг: Использует BaseExportSubmodule для устранения дублирования.
"""

from typing import Dict, Any, List

from .Fsm_1_5_0_base_export_submodule import BaseExportSubmodule
from ..core.geojson_exporter import GeoJSONExporter


class GeoJSONExportSubmodule(BaseExportSubmodule):
    """Сабмодуль для экспорта в GeoJSON формат"""

    FORMAT_NAME = "GeoJSON"
    EXPORTER_CLASS = GeoJSONExporter

    def __init__(self, iface):
        super().__init__(iface)

        # Параметры по умолчанию для GeoJSON
        self.default_params.update({
            'create_wgs84': True,
            'include_style': True,
            'precision': 8,
        })

    def _get_dialog_options(self, export_params: Dict[str, Any]) -> List[tuple]:
        """Опции для диалога GeoJSON"""
        return [
            ("create_wgs84", "Создать версию в WGS-84", export_params['create_wgs84']),
            ("include_style", "Включить стили в properties", export_params['include_style']),
        ]

    def _get_exporter_params(self, export_params: Dict[str, Any]) -> Dict[str, Any]:
        """Параметры для GeoJSONExporter"""
        return {
            'create_wgs84': export_params['create_wgs84'],
            'include_style': export_params['include_style'],
            'precision': export_params['precision'],
        }
