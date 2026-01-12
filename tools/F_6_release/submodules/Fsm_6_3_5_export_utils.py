# -*- coding: utf-8 -*-
"""
Fsm_6_3_5 - Утилиты экспорта документов

Вспомогательные функции для экспорта документов:
- Формирование имён файлов
- Конвертация индексов в буквы колонок Excel
- Извлечение координат из геометрии
- Работа с метаданными проекта
"""

import os
import sqlite3
import re
from typing import Dict, Any, List, Optional, Tuple, Union
from datetime import datetime

from qgis.core import (
    QgsVectorLayer, QgsGeometry, QgsWkbTypes, QgsProject,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY
)

from Daman_QGIS.managers import CoordinatePrecisionManager as CPM, get_project_structure_manager
from Daman_QGIS.constants import PRECISION_DECIMALS, PRECISION_DECIMALS_WGS84
from Daman_QGIS.utils import log_warning, log_debug


class ExportUtils:
    """Утилиты для экспорта документов"""

    # Недопустимые символы в именах файлов Windows
    INVALID_FILENAME_CHARS = r'[<>:"/\\|?*]'

    @staticmethod
    def get_output_filename(
        layer_name: str,
        doc_type: str,
        prefix: str = '',
        suffix: str = '',
        extension: str = 'xlsx'
    ) -> str:
        """
        Формирует безопасное имя файла для документа

        Args:
            layer_name: Имя слоя
            doc_type: Тип документа ('coordinate_list', 'attribute_list', ...)
            prefix: Префикс файла
            suffix: Суффикс файла
            extension: Расширение файла

        Returns:
            str: Безопасное имя файла
        """
        # Санитизируем имя слоя
        safe_name = ExportUtils.sanitize_filename(layer_name)

        # Формируем имя по типу документа
        type_names = {
            'coordinate_list': 'Координаты',
            'attribute_list': 'Ведомость',
            'cadnum_list': 'Перечень_КН',
            'custom': 'Документ',
        }

        type_name = type_names.get(doc_type, 'Документ')

        # Собираем имя файла
        parts = [p for p in [prefix, type_name, safe_name, suffix] if p]
        filename = '_'.join(parts)

        return f"{filename}.{extension}"

    @staticmethod
    def sanitize_filename(name: str) -> str:
        """
        Очистить строку для использования в имени файла

        Args:
            name: Исходная строка

        Returns:
            str: Безопасное имя файла
        """
        if not name:
            return 'unnamed'

        # Заменяем недопустимые символы на подчёркивания
        safe = re.sub(ExportUtils.INVALID_FILENAME_CHARS, '_', name)

        # Убираем множественные подчёркивания
        safe = re.sub(r'_+', '_', safe)

        # Убираем подчёркивания в начале и конце
        safe = safe.strip('_')

        # Ограничиваем длину
        if len(safe) > 200:
            safe = safe[:200]

        return safe or 'unnamed'

    @staticmethod
    def get_column_letter(index: int) -> str:
        """
        Конвертирует индекс колонки (0-based) в букву Excel

        Args:
            index: Индекс колонки (0 = A, 1 = B, ...)

        Returns:
            str: Буква колонки (A, B, ..., Z, AA, AB, ...)

        Examples:
            >>> get_column_letter(0)
            'A'
            >>> get_column_letter(25)
            'Z'
            >>> get_column_letter(26)
            'AA'
        """
        result = ''
        index += 1  # Excel использует 1-based индексацию

        while index > 0:
            index, remainder = divmod(index - 1, 26)
            result = chr(65 + remainder) + result

        return result

    @staticmethod
    def get_column_index(letter: str) -> int:
        """
        Конвертирует букву колонки Excel в индекс (0-based)

        Args:
            letter: Буква колонки (A, B, ..., AA, ...)

        Returns:
            int: Индекс колонки (0-based)
        """
        result = 0
        for char in letter.upper():
            result = result * 26 + (ord(char) - ord('A') + 1)
        return result - 1

    @staticmethod
    def extract_coordinates(
        geometry: QgsGeometry,
        precision: int = PRECISION_DECIMALS,
        remove_duplicates: bool = True
    ) -> List[Tuple[float, float]]:
        """
        Извлекает координаты из геометрии

        Args:
            geometry: Геометрия QGIS
            precision: Точность округления
            remove_duplicates: Удалять дублирующиеся точки

        Returns:
            Список кортежей [(x, y), ...]
        """
        if not geometry or geometry.isEmpty():
            return []

        coords = []
        seen = set()

        geom_type = geometry.type()

        if geom_type == QgsWkbTypes.PointGeometry:
            if geometry.isMultipart():
                points = geometry.asMultiPoint()
            else:
                points = [geometry.asPoint()]

            for pt in points:
                x, y = CPM.round_coordinates(pt.x(), pt.y(), precision)
                key = (x, y)
                if not remove_duplicates or key not in seen:
                    coords.append((x, y))
                    seen.add(key)

        elif geom_type == QgsWkbTypes.LineGeometry:
            if geometry.isMultipart():
                lines = geometry.asMultiPolyline()
            else:
                lines = [geometry.asPolyline()]

            for line in lines:
                for pt in line:
                    x, y = CPM.round_coordinates(pt.x(), pt.y(), precision)
                    key = (x, y)
                    if not remove_duplicates or key not in seen:
                        coords.append((x, y))
                        seen.add(key)

        elif geom_type == QgsWkbTypes.PolygonGeometry:
            if geometry.isMultipart():
                polygons = geometry.asMultiPolygon()
            else:
                polygons = [geometry.asPolygon()]

            for polygon in polygons:
                for ring in polygon:
                    # Убираем замыкающую точку (первая == последняя)
                    points = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
                    for pt in points:
                        x, y = CPM.round_coordinates(pt.x(), pt.y(), precision)
                        key = (x, y)
                        if not remove_duplicates or key not in seen:
                            coords.append((x, y))
                            seen.add(key)

        return coords

    @staticmethod
    def extract_polygon_contours(
        geometry: QgsGeometry,
        precision: int = PRECISION_DECIMALS
    ) -> List[Dict[str, Any]]:
        """
        Извлекает контуры полигона с разделением на внешние и внутренние (дыры)

        Args:
            geometry: Геометрия полигона
            precision: Точность округления

        Returns:
            Список контуров [{'type': 'exterior'|'hole', 'coordinates': [(x, y), ...], 'area': float}, ...]
        """
        if not geometry or geometry.type() != QgsWkbTypes.PolygonGeometry:
            return []

        contours = []

        if geometry.isMultipart():
            polygons = geometry.asMultiPolygon()
        else:
            polygons = [geometry.asPolygon()]

        for poly_idx, polygon in enumerate(polygons):
            if not polygon:
                continue

            # Внешний контур
            exterior = polygon[0]
            points = exterior[:-1] if len(exterior) > 1 and exterior[0] == exterior[-1] else exterior
            coords = [CPM.round_coordinates(pt.x(), pt.y(), precision) for pt in points]

            contours.append({
                'type': 'exterior',
                'coordinates': coords,
                'area': geometry.area() if poly_idx == 0 else 0
            })

            # Внутренние контуры (дыры)
            for hole in polygon[1:]:
                hole_points = hole[:-1] if len(hole) > 1 and hole[0] == hole[-1] else hole
                hole_coords = [CPM.round_coordinates(pt.x(), pt.y(), precision) for pt in hole_points]

                contours.append({
                    'type': 'hole',
                    'coordinates': hole_coords,
                    'area': 0
                })

        return contours

    @staticmethod
    def transform_coordinates(
        coords: List[Tuple[float, float]],
        source_crs: QgsCoordinateReferenceSystem,
        target_crs: QgsCoordinateReferenceSystem,
        precision: int = PRECISION_DECIMALS
    ) -> List[Tuple[float, float]]:
        """
        Трансформирует список координат из одной СК в другую

        Args:
            coords: Список координат [(x, y), ...]
            source_crs: Исходная СК
            target_crs: Целевая СК
            precision: Точность округления результата

        Returns:
            Список трансформированных координат
        """
        if source_crs == target_crs:
            return coords

        transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())

        transformed = []
        for x, y in coords:
            point = QgsPointXY(x, y)
            transformed_point = transform.transform(point)
            tx, ty = CPM.round_coordinates(
                transformed_point.x(),
                transformed_point.y(),
                precision
            )
            transformed.append((tx, ty))

        return transformed

    @staticmethod
    def get_project_metadata() -> Dict[str, Any]:
        """
        Получить метаданные проекта из GeoPackage

        Returns:
            Словарь метаданных {key: value, ...}
        """
        try:
            structure_manager = get_project_structure_manager()
            project_path = QgsProject.instance().homePath()

            if project_path:
                structure_manager.project_root = project_path

            gpkg_path = structure_manager.get_gpkg_path(create=False)

            if not gpkg_path or not os.path.exists(gpkg_path):
                return {}

            conn = sqlite3.connect(gpkg_path)
            cursor = conn.cursor()

            cursor.execute("SELECT key, value FROM project_metadata")
            rows = cursor.fetchall()

            metadata = {}
            for key, value in rows:
                metadata[key] = value

            conn.close()
            return metadata

        except Exception as e:
            log_warning(f"Fsm_6_3_5: Ошибка чтения метаданных: {str(e)}")
            return {}

    @staticmethod
    def format_area(area_sqm: float, unit: str = 'sqm') -> str:
        """
        Форматирует площадь с единицами измерения

        Args:
            area_sqm: Площадь в квадратных метрах
            unit: Единица измерения ('sqm', 'ha', 'auto')

        Returns:
            str: Отформатированная площадь
        """
        if unit == 'ha' or (unit == 'auto' and area_sqm >= 10000):
            return f"{area_sqm / 10000:.4f} га"
        else:
            return f"{area_sqm:.2f} кв.м"

    @staticmethod
    def get_timestamp_suffix() -> str:
        """
        Получить суффикс с датой/временем для имени файла

        Returns:
            str: Суффикс формата YYYYMMDD_HHMMSS
        """
        return datetime.now().strftime('%Y%m%d_%H%M%S')

    @staticmethod
    def get_date_suffix() -> str:
        """
        Получить суффикс с датой для имени файла

        Returns:
            str: Суффикс формата YYYY_MM_DD
        """
        return datetime.now().strftime('%Y_%m_%d')

    @staticmethod
    def ensure_folder_exists(folder_path: str) -> bool:
        """
        Создать папку если она не существует

        Args:
            folder_path: Путь к папке

        Returns:
            bool: True если папка существует или создана успешно
        """
        try:
            os.makedirs(folder_path, exist_ok=True)
            return True
        except Exception as e:
            log_warning(f"Fsm_6_3_5: Ошибка создания папки {folder_path}: {str(e)}")
            return False

    @staticmethod
    def swap_xy_for_geodetic(
        coords: List[Tuple[float, float]],
        is_geodetic: bool = True
    ) -> List[Tuple[float, float]]:
        """
        Меняет местами X и Y для геодезических координат

        В геодезии X - это север (широта), Y - это восток (долгота).
        В математике и QGIS X - это восток, Y - это север.

        Args:
            coords: Список координат [(x, y), ...]
            is_geodetic: True для геодезического порядка (Y, X)

        Returns:
            Список координат с переставленными X и Y
        """
        if is_geodetic:
            return [(y, x) for x, y in coords]
        return coords
