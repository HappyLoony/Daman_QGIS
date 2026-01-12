# -*- coding: utf-8 -*-
"""
Модуль экспорта в DXF
Часть инструмента 0_5_Графика к запросу
"""

import os
from qgis.core import (
    QgsProject, QgsMessageLog, Qgis,
    QgsCoordinateReferenceSystem
)
from ..core.dxf_exporter import DxfExporter as BaseDxfExporter



class DxfExportWrapper:
    """Обертка для экспорта в DXF"""
    
    def __init__(self, iface):
        """Инициализация обертки
        
        Args:
            iface: Интерфейс QGIS
        """
        self.iface = iface
    def export_to_dxf(self, boundaries_layer, output_folder):
        """Экспорт слоя в DXF файлы

        Args:
            boundaries_layer: Слой с границами работ
            output_folder: Папка для сохранения файлов

        Returns:
            tuple: (success, error_msg)
        """
        # Получаем менеджер стилей
        from Daman_QGIS.managers import StyleManager
        from Daman_QGIS.utils import log_info
        style_manager = StyleManager()

        # Создаем экспортер
        exporter = BaseDxfExporter(self.iface, style_manager)

        # Получаем информацию о СК через экспортер
        crs_short_name, project_crs = exporter.get_project_crs_info()


        # Экспорт в СК проекта
        if crs_short_name:
            # Преобразуем название СК (например: "СК_63_5" -> "СК_63_5")
            crs_filename = crs_short_name.replace(' ', '_')
            dxf_project_filename = f"Границы работ_{crs_filename}.dxf"

            # Экспортируем с СК проекта (глобальная ширина = 1)
            success = exporter.export_layers(
                [boundaries_layer],
                output_folder,
                target_crs=project_crs,
                export_settings={'width': 1.0},
                output_path=os.path.join(output_folder, dxf_project_filename)
            )

            if success:
                log_info(f"DXF файл в СК проекта создан: {os.path.join(output_folder, dxf_project_filename)}")

        # Экспорт в WGS 84
        wgs84_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        dxf_wgs_filename = "Границы работ_WGS_84.dxf"

        # Экспортируем в WGS 84 (глобальная ширина = 0)
        success = exporter.export_layers(
            [boundaries_layer],
            output_folder,
            target_crs=wgs84_crs,
            export_settings={'width': 0},
            output_path=os.path.join(output_folder, dxf_wgs_filename)
        )

        if success:
            log_info(f"DXF файл в WGS 84 создан: {os.path.join(output_folder, dxf_wgs_filename)}")

        return True, None

