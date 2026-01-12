# -*- coding: utf-8 -*-
"""
Модуль экспорта координат в Excel
Часть инструмента 0_5_Графика к запросу
Обертка над ExcelExporter из Tool_8
"""

import os
from qgis.core import (
    QgsProject, QgsMessageLog, Qgis,
    QgsCoordinateReferenceSystem
)
from ..core.excel_exporter import ExcelExporter as BaseExcelExporter
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error


class ExcelExporter:
    """Обертка для ExcelExporter из Tool_8 с сохранением специфичных имен файлов для Tool_0_5"""
    
    def __init__(self, iface):
        """Инициализация экспортера
        
        Args:
            iface: Интерфейс QGIS
        """
        self.iface = iface
        self.base_exporter = BaseExcelExporter(iface)
    def export_coordinates_to_excel(self, boundaries_layer, output_folder):
        """Экспорт координат из слоя границ в Excel файлы

        Args:
            boundaries_layer: Слой с границами работ
            output_folder: Папка для сохранения файлов

        Returns:
            tuple: (success, error_msg)
        """
        # Проверяем наличие xlsxwriter
        try:
            import xlsxwriter
        except RuntimeError:
            msg = ("Модуль xlsxwriter не установлен. Excel файлы не созданы. "
                   "Установите: pip install xlsxwriter")
            log_warning(msg)
            raise RuntimeError(msg)

        # Получаем короткое название СК для имени файла
        crs_short_name, _ = self.base_exporter.get_project_crs_info()

        # Создаем файл с координатами в СК проекта
        if crs_short_name:
            # Формируем имя файла для Tool_0_5
            filename_pattern = f"Приложение_2_Координаты {crs_short_name}"

            # Экспортируем через базовый экспортер без WGS84
            results1 = self.base_exporter.export_layers(
                [boundaries_layer],
                output_folder,
                filename_pattern=filename_pattern,
                create_wgs84=False  # Отключаем автоматическое создание WGS84
            )

            if not results1.get(boundaries_layer.name(), False):
                raise RuntimeError("Ошибка создания файла в СК проекта")
        else:
            log_warning("Fsm_1_4_2: Короткое название СК не задано. Файл с координатами в СК проекта не создан.")

        # Создаем файл с координатами в WGS 84 отдельным вызовом
        # Используем публичный API вместо приватного метода
        results2 = self.base_exporter.export_layers(
            [boundaries_layer],
            output_folder,
            filename_pattern="Приложение_3_Координаты WGS 84",
            create_wgs84=False,  # Отключаем автоматическое создание второго WGS84
            target_crs="EPSG:4326"  # Экспортируем сразу в WGS84
        )

        log_info(f"Fsm_1_4_2: Excel файлы с координатами созданы в {output_folder}")

        return True, None

