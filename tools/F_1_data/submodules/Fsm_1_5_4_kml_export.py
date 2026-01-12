# -*- coding: utf-8 -*-
"""
Сабмодуль экспорта в KML

Рефакторинг: Использует BaseExportSubmodule для устранения дублирования.
"""

from typing import Dict, Any, List

from .Fsm_1_5_0_base_export_submodule import BaseExportSubmodule
from ..core.kml_exporter import KMLExporter


class KMLExportSubmodule(BaseExportSubmodule):
    """Сабмодуль для экспорта в KML формат"""

    FORMAT_NAME = "KML"
    EXPORTER_CLASS = KMLExporter

    def __init__(self, iface):
        super().__init__(iface)

        # Параметры по умолчанию для KML
        self.default_params.update({
            'export_labels': True,
            'export_description': True,
        })

    def _get_dialog_options(self, export_params: Dict[str, Any]) -> List[tuple]:
        """Опции для диалога KML"""
        return [
            ("export_labels", "Экспортировать подписи", export_params['export_labels']),
            ("export_description", "Экспортировать описания", export_params['export_description']),
        ]

    def _get_exporter_params(self, export_params: Dict[str, Any]) -> Dict[str, Any]:
        """Параметры для KMLExporter"""
        return {
            'export_labels': export_params['export_labels'],
            'export_description': export_params['export_description'],
        }

    def _get_success_message(self, export_params: Dict[str, Any],
                             success_count: int, error_count: int,
                             output_folder: str) -> str:
        """Сообщение с примечанием о WGS-84"""
        message = super()._get_success_message(
            export_params, success_count, error_count, output_folder
        )
        message += "\n\nВнимание: KML файлы всегда экспортируются в WGS-84"
        return message
