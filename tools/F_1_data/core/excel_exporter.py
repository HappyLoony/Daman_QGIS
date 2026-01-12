# -*- coding: utf-8 -*-
"""
Экспортер координат в Excel формат
"""

import os
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from collections import OrderedDict

from qgis.core import (
    QgsVectorLayer, QgsProject, QgsMessageLog, Qgis,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsWkbTypes, QgsGeometry
)

from .base_exporter import BaseExporter

from Daman_QGIS.constants import PLUGIN_NAME, PRECISION_DECIMALS, PRECISION_DECIMALS_WGS84
from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers import CoordinatePrecisionManager as CPM

try:
    import xlsxwriter
    xlsxwriter_available = True
except RuntimeError:
    xlsxwriter_available = False
    log_warning(
        "Библиотека xlsxwriter не установлена. Экспорт в Excel недоступен."
    )


class ExcelExporter(BaseExporter):
    """Экспортер координат в Excel"""
    
    def __init__(self, iface=None):
        """Инициализация экспортера Excel"""
        super().__init__(iface)
        
        # Дополнительные параметры для Excel
        self.default_params.update({
            'coordinate_precision': 2,  # Точность координат (знаков после запятой)
            'create_wgs84': True,  # Создавать ли файл в WGS-84
            'add_headers': True,  # Добавлять заголовки
            'add_area': False,  # НЕ добавлять площадь для полигонов по умолчанию
            'add_length': True,  # Добавлять длину для линий
            'style_headers': True,  # Стилизовать заголовки
        })
    
    def export_layers(self, 
                     layers: List[QgsVectorLayer],
                     output_folder: str,
                     **params) -> Dict[str, bool]:
        """
        Экспорт слоев в Excel файлы
        
        Args:
            layers: Список слоев для экспорта
            output_folder: Папка назначения
            **params: Параметры экспорта
            
        Returns:
            Словарь {layer_name: success}
        """
        if not xlsxwriter_available:
            self.message.emit("Библиотека xlsxwriter не установлена")
            return {layer.name(): False for layer in layers}
        
        # Объединяем параметры
        export_params = self.merge_params(**params)
        
        # Сохраняем последнюю папку
        self.set_last_export_folder(output_folder)
        
        results = {}
        total_layers = len(layers)
        
        for idx, layer in enumerate(layers):
            if not isinstance(layer, QgsVectorLayer):
                results[layer.name()] = False
                continue
            
            # Прогресс
            progress = int((idx + 1) * 100 / total_layers)
            self.progress.emit(progress)
            
            # Экспортируем слой
            success = self._export_layer(layer, output_folder, export_params)
            results[layer.name()] = success
            
            if success:
                self.message.emit(f"Экспортирован: {layer.name()}")
            else:
                self.message.emit(f"Ошибка экспорта: {layer.name()}")
        
        return results
    def _export_layer(self,
                     layer: QgsVectorLayer,
                     output_folder: str,
                     params: Dict[str, Any]) -> bool:
        """
        Экспорт одного слоя в Excel

        Args:
            layer: Слой для экспорта
            output_folder: Папка назначения
            params: Параметры экспорта

        Returns:
            True если успешно
        """
        # Получаем информацию о СК
        crs_short_name, project_crs = self.get_project_crs_info()

        # Определяем целевую СК (может быть передана через параметры)
        target_crs_param = params.get('target_crs')
        if target_crs_param:
            if isinstance(target_crs_param, str):
                target_crs = QgsCoordinateReferenceSystem(target_crs_param)
            else:
                target_crs = target_crs_param
        else:
            target_crs = project_crs

        # Форматируем имя файла
        # Если не передан шаблон, используем стандартный формат: название_СК
        if params.get('filename_pattern'):
            filename = self.format_filename(
                layer,
                params.get('filename_pattern') or None,
                extension='xlsx'
            )
        else:
            # Стандартный формат: [название слоя]_[СК]
            layer_name = layer.name()
            # Убираем недопустимые символы для имени файла
            safe_name = "".join(c if c.isalnum() or c in "_- " else "_" for c in layer_name)

            # Получаем название СК для имени файла
            filename = f"{safe_name}_{crs_short_name}" if crs_short_name else safe_name

        # Полный путь к файлу
        filepath = os.path.join(output_folder, f"{filename}.xlsx")

        # Экспортируем в целевую СК
        self._create_excel_file(
            layer,
            filepath,
            target_crs,
            params
        )

        # Экспортируем в WGS-84 если нужно
        if params.get('create_wgs84', True):
            wgs84_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            # Формат для WGS-84: [название слоя]_WGS-84
            if params.get('filename_pattern'):
                # Если есть шаблон, просто добавляем _WGS84
                wgs84_filename = f"{filename}_WGS84.xlsx"
            else:
                # Стандартный формат
                layer_name = layer.name()
                safe_name = "".join(c if c.isalnum() or c in "_- " else "_" for c in layer_name)
                wgs84_filename = f"{safe_name}_WGS-84.xlsx"
            wgs84_filepath = os.path.join(output_folder, wgs84_filename)

            self._create_excel_file(
                layer,
                wgs84_filepath,
                wgs84_crs,
                params
            )

        return True
    def _create_excel_file(self,
                          layer: QgsVectorLayer,
                          filepath: str,
                          target_crs: QgsCoordinateReferenceSystem,
                          params: Dict[str, Any]):
        """
        Создание Excel файла с координатами используя xlsxwriter
        Стиль полностью соответствует инструменту 0_5

        Args:
            layer: Слой для экспорта
            filepath: Путь к файлу
            target_crs: Целевая система координат
            params: Параметры экспорта
        """
        workbook = None
        import xlsxwriter

        # Создаем книгу Excel
        workbook = xlsxwriter.Workbook(filepath)
        worksheet = workbook.add_worksheet('Координаты')

        # ВАЖНО: Определяем is_wgs84 ДО определения precision
        is_wgs84 = target_crs.authid() == "EPSG:4326"

        # Настройки точности (автоматически 6 для WGS84, 2 для остальных)
        if 'coordinate_precision' not in params:
            # Автоматический выбор precision в зависимости от СК
            precision = PRECISION_DECIMALS_WGS84 if is_wgs84 else PRECISION_DECIMALS
        else:
            # Пользователь явно задал precision - используем его
            precision = params['coordinate_precision']

        # Создаем трансформацию СК если нужно
        transform = None
        if layer.crs() != target_crs:
            transform = QgsCoordinateTransform(
                layer.crs(),
                target_crs,
                QgsProject.instance()
            )

        # Собираем координаты с ПРАВИЛЬНЫМ precision
        coordinates_data = self._collect_coordinates(layer, transform, precision)

        if not coordinates_data:
            # Пустой слой
            worksheet.write(0, 0, "Нет данных для экспорта")
            workbook.close()
            return

        # Получаем короткое название СК для заголовка
        crs_short_name, _ = self.get_project_crs_info()
        if crs_short_name and not is_wgs84:
            # Преобразуем название СК (например: "СК 63_5" -> "СК 63 зона 5")
            crs_display_name = crs_short_name.replace('_', ' зона ')
        else:
            crs_display_name = "WGS 84" if is_wgs84 else target_crs.description()

        # Форматы точно как в 0_5 (Times New Roman 14pt)
        header_format = workbook.add_format({
            'bold': True,
            'font_name': 'Times New Roman',
            'font_size': 14,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True
        })

        col_header_format = workbook.add_format({
            'bold': True,
            'font_name': 'Times New Roman',
            'font_size': 14,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1
        })

        data_format = workbook.add_format({
            'font_name': 'Times New Roman',
            'font_size': 14,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1
        })

        number_format = workbook.add_format({
            'font_name': 'Times New Roman',
            'font_size': 14,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'num_format': '0.00'
        })

        # Заголовок с объединением ячеек (как в 0_5)
        worksheet.merge_range('A1:C1',
                             f"Ведомость координат поворотных точек {crs_display_name}",
                             header_format)  # type: ignore[call-arg]
        worksheet.set_row(0, 40)  # Высота первой строки

        # Заголовки столбцов
        if is_wgs84:
            # Для WGS84 используем N и E
            worksheet.write('A2', '№', col_header_format)  # type: ignore[arg-type]
            worksheet.write('B2', 'N', col_header_format)  # type: ignore[arg-type]  # Широта
            worksheet.write('C2', 'E', col_header_format)  # type: ignore[arg-type]  # Долгота
        else:
            # Для СК проекта
            worksheet.write('A2', '№', col_header_format)  # type: ignore[arg-type]
            worksheet.write('B2', 'X', col_header_format)  # type: ignore[arg-type]
            worksheet.write('C2', 'Y', col_header_format)  # type: ignore[arg-type]

        # Данные
        row_num = 2
        for row_data in coordinates_data:
            # Проверяем на пустую строку (как в 0_5 между контурами)
            if isinstance(row_data, dict) and row_data.get('empty'):
                # Если есть комментарий для внутреннего контура, добавляем его
                if row_data.get('comment'):
                    worksheet.merge_range(row_num, 0, row_num, 2, row_data['comment'], data_format)  # type: ignore[index]
                row_num += 1
                continue

            # Трансформируем координаты поточечно при выводе
            x_coord = row_data[2]  # Исходная X
            y_coord = row_data[3]  # Исходная Y

            if transform:
                # Трансформируем точку в целевую СК
                from qgis.core import QgsPointXY
                point = QgsPointXY(x_coord, y_coord)
                transformed_point = transform.transform(point)
                x_coord = transformed_point.x()
                y_coord = transformed_point.y()

            if is_wgs84:
                # Для WGS84 выводим с 6 знаками после запятой
                worksheet.write(row_num, 0, row_data[1], data_format)  # № точки
                # Широта (Y) и Долгота (X) с 6 знаками
                worksheet.write(row_num, 1, f"{y_coord:.6f}", data_format)  # N (широта = Y)
                worksheet.write(row_num, 2, f"{x_coord:.6f}", data_format)  # E (долгота = X)
            else:
                # Для СК проекта - в колонку X записываем Y, в колонку Y записываем X (как в 0_5!)
                worksheet.write(row_num, 0, row_data[1], data_format)  # № точки
                worksheet.write(row_num, 1, CPM.round_coordinate(y_coord), number_format)  # В столбец X пишем Y!
                worksheet.write(row_num, 2, CPM.round_coordinate(x_coord), number_format)  # В столбец Y пишем X!
            row_num += 1

        # Добавляем площадь если нужно и если это полигоны
        if params.get('add_area', False) and layer.geometryType() == QgsWkbTypes.PolygonGeometry:
            # Пустая строка перед площадью
            row_num += 1

            # Вычисляем площадь на плоскости
            total_area = 0
            for feature in layer.getFeatures():
                if feature.hasGeometry():
                    geom = feature.geometry()
                    # Если нужна трансформация, трансформируем геометрию
                    if transform:
                        geom = QgsGeometry(geom)  # Создаем копию
                        geom.transform(transform)
                    total_area += geom.area()

            # Конвертируем в гектары
            area_ha = total_area / 10000.0

            # Объединяем ячейки и добавляем площадь
            worksheet.merge_range(
                row_num, 0, row_num, 2,
                f"Площадь: {area_ha:.4f} га",
                data_format
            )

        # Фиксированная ширина столбцов (как в 0_5)
        worksheet.set_column('A:A', 16)  # type: ignore[arg-type]
        worksheet.set_column('B:B', 16)  # type: ignore[arg-type]
        worksheet.set_column('C:C', 16)  # type: ignore[arg-type]


        # Закрываем книгу
        workbook.close()
        workbook = None  # Помечаем как закрытую

        log_info(
            f"Excel файл успешно создан: {filepath}"
        )
    def _process_point(self, point, unique_points: dict, point_number: int, precision: int) -> int:
        """Обработка одной точки - добавление в уникальные если нужно"""
        key = CPM.round_point_tuple(point, precision)
        if key not in unique_points:
            unique_points[key] = point_number
            point_number += 1
        return point_number

    def _process_points_list(self, points, unique_points: dict, point_number: int, precision: int) -> Tuple[List, int]:
        """Обработка списка точек контура"""
        contour_points = []
        for point in points:
            point_number = self._process_point(point, unique_points, point_number, precision)
            contour_points.append(point)
        return contour_points, point_number

    def _extract_line_contours(self, geom, unique_points: dict, point_number: int, precision: int) -> Tuple[List, int]:
        """Извлечение контуров из линейной геометрии"""
        contours = []
        # МИГРАЦИЯ LINESTRING → MULTILINESTRING: упрощённый паттерн
        lines = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
        for line_points in lines:
            contour_points, point_number = self._process_points_list(line_points, unique_points, point_number, precision)
            if contour_points:
                contours.append(('exterior', contour_points))
        return contours, point_number

    def _extract_polygon_contours(self, geom, unique_points: dict, point_number: int, precision: int) -> Tuple[List, int]:
        """Извлечение контуров из полигональной геометрии"""
        contours = []
        polygons = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]

        for polygon in polygons:
            if not polygon:
                continue

            # Внешний контур
            ring = polygon[0]
            contour_points, point_number = self._process_points_list(ring, unique_points, point_number, precision)
            if contour_points:
                contours.append(('exterior', contour_points))

            # Внутренние контуры (дырки)
            for hole in polygon[1:]:
                hole_points, point_number = self._process_points_list(hole, unique_points, point_number, precision)
                if hole_points:
                    contours.append(('hole', hole_points))

        return contours, point_number

    def _build_coordinates_table(self, all_contours, unique_points: dict, precision: int) -> List[List]:
        """Построение итоговой таблицы координат"""
        coordinates_data = []

        for idx, (contour_type, contour_points) in enumerate(all_contours):
            for point in contour_points:
                key = CPM.round_point_tuple(point, precision)
                point_num = unique_points.get(key, 0)

                x_coord = CPM.round_coordinate(point.x(), precision)
                y_coord = CPM.round_coordinate(point.y(), precision)
                coordinates_data.append([point_num, str(point_num), x_coord, y_coord])
            
            # Добавляем пустую строку между контурами (кроме последнего)
            if idx < len(all_contours) - 1:
                coordinates_data.append({'empty': True})

        return coordinates_data

    def _collect_coordinates(self,
                            layer: QgsVectorLayer,
                            transform: Optional[QgsCoordinateTransform],
                            precision: int) -> List[List]:
        """Сбор координат из слоя. Трансформация НЕ применяется здесь."""
        unique_points = {}
        point_number = 1
        all_contours = []

        # Проход по всем объектам слоя
        for feature in layer.getFeatures():
            geom = feature.geometry()
            if not geom or geom.isEmpty():
                continue

            # Обработка в зависимости от типа геометрии
            if geom.type() == QgsWkbTypes.LineGeometry:
                contours, point_number = self._extract_line_contours(geom, unique_points, point_number, precision)
                all_contours.extend(contours)

            elif geom.type() == QgsWkbTypes.PolygonGeometry:
                contours, point_number = self._extract_polygon_contours(geom, unique_points, point_number, precision)
                all_contours.extend(contours)

        # Построение итоговой таблицы
        return self._build_coordinates_table(all_contours, unique_points, precision)

    def _get_headers(self, 
                    layer: QgsVectorLayer,
                    crs: QgsCoordinateReferenceSystem,
                    params: Dict[str, Any]) -> List[List]:
        """Получение заголовков для Excel файла"""
        headers = []
        
        # Название слоя
        headers.append([f"Слой: {layer.name()}"])
        
        # Система координат
        crs_name = crs.description() or crs.authid()
        headers.append([f"Система координат: {crs_name}"])
        
        # Дата экспорта
        date_str = datetime.now().strftime("%d.%m.%Y %H:%M")
        headers.append([f"Дата экспорта: {date_str}"])
        
        # Количество объектов
        headers.append([f"Количество объектов: {layer.featureCount()}"])
        
        return headers
    
    def _get_table_headers(self, geom_type: int) -> List:
        """Получение заголовков таблицы координат"""
        # В стиле 0_5 используется только 3 колонки
        return ["№", "X", "Y"]
    
    def _get_summary(self,
                    layer: QgsVectorLayer,
                    coordinates_data: List[List],
                    params: Dict[str, Any]) -> List[List]:
        """Получение итоговой информации"""
        summary = []
        geom_type = layer.geometryType()
        
        if geom_type == QgsWkbTypes.PolygonGeometry and params.get('add_area', True):
            # Вычисляем площадь
            total_area = 0
            for feature in layer.getFeatures():
                if feature.hasGeometry():
                    total_area += feature.geometry().area()
            
            summary.append([f"Общая площадь: {total_area:.2f} м²"])
            summary.append([f"Общая площадь: {total_area/10000:.4f} га"])
        
        elif geom_type == QgsWkbTypes.LineGeometry and params.get('add_length', True):
            # Вычисляем длину
            total_length = 0
            for feature in layer.getFeatures():
                if feature.hasGeometry():
                    total_length += feature.geometry().length()
            
            summary.append([f"Общая длина: {total_length:.2f} м"])
            summary.append([f"Общая длина: {total_length/1000:.3f} км"])
        
        # Количество точек
        if coordinates_data:
            summary.append([f"Количество точек: {len(coordinates_data)}"])
        
        return summary

