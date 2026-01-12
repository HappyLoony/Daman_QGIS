# -*- coding: utf-8 -*-
"""
Сабмодуль экспорта в Shapefile

Рефакторинг: Использует BaseExportSubmodule для устранения дублирования.
"""

from typing import Dict, Any, List
from qgis.PyQt.QtWidgets import QMessageBox

from .Fsm_1_5_0_base_export_submodule import BaseExportSubmodule
from ..core.shapefile_exporter import ShapefileExporter


class ShapefileExportSubmodule(BaseExportSubmodule):
    """Сабмодуль для экспорта в Shapefile формат"""

    FORMAT_NAME = "Shapefile"
    EXPORTER_CLASS = ShapefileExporter

    def __init__(self, iface):
        super().__init__(iface)

        # Параметры по умолчанию для Shapefile
        self.default_params.update({
            'create_wgs84': True,
            'export_style': True,
            'truncate_fields': True,
            'encoding': 'UTF-8',
        })

    def _get_dialog_options(self, export_params: Dict[str, Any]) -> List[tuple]:
        """Опции для диалога Shapefile"""
        return [
            ("create_wgs84", "Создать версию в WGS-84", export_params['create_wgs84']),
            ("export_style", "Экспортировать стиль (.qml и .sld)", export_params['export_style']),
            ("truncate_fields", "Обрезать имена полей до 10 символов", export_params['truncate_fields']),
        ]

    def _show_pre_export_warning(self, export_params: Dict[str, Any]) -> bool:
        """Предупреждение об ограничениях Shapefile"""
        QMessageBox.information(
            self.iface.mainWindow(),
            "Ограничения Shapefile",
            "Внимание! Формат Shapefile имеет ограничения:\n"
            "- Имена полей максимум 10 символов\n"
            "- Один тип геометрии на файл\n"
            "- Нет поддержки NULL в числовых полях\n"
            "- Максимальный размер файла 2 ГБ\n\n"
            "Стили будут экспортированы в отдельные файлы .qml и .sld"
        )
        return True

    def _get_exporter_params(self, export_params: Dict[str, Any]) -> Dict[str, Any]:
        """Параметры для ShapefileExporter"""
        return {
            'create_wgs84': export_params['create_wgs84'],
            'export_style': export_params['export_style'],
            'truncate_fields': export_params['truncate_fields'],
            'encoding': export_params['encoding'],
        }

    def _get_success_message(self, export_params: Dict[str, Any],
                             success_count: int, error_count: int,
                             output_folder: str) -> str:
        """Сообщение с примечанием о стилях"""
        message = super()._get_success_message(
            export_params, success_count, error_count, output_folder
        )
        if export_params.get('export_style'):
            message += "\n\nСтили сохранены в файлах .qml и .sld"
        return message
