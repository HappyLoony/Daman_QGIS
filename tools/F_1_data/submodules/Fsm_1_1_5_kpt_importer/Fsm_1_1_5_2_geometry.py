# -*- coding: utf-8 -*-
"""
Fsm_1_1_5_2: Извлечение геометрий из КПТ

Извлечение геометрий из XML элементов КПТ.
Поддерживает MultiPolygon, MultiLineString, MultiPoint с M-координатами.

Ключевые особенности:
- Поддержка contours и spatial_elements
- M-координаты (delta_geopoint) для точности измерений
- Корректный SWAP координат X/Y для российских МСК
- CLOSURE_TOLERANCE = 0.01м для определения замкнутости
"""

from typing import Dict, List, Optional, Any

from qgis.core import (
    QgsGeometry, QgsPoint, QgsLineString, QgsPolygon,
    QgsMultiPolygon, QgsMultiLineString, QgsMultiPoint
)

from Daman_QGIS.utils import log_warning

# Допуск замкнутости контура (метры)
CLOSURE_TOLERANCE = 0.01


def extract_geometry(record) -> Dict[str, Optional[QgsGeometry]]:
    """
    Извлечение геометрий из XML записи КПТ

    Args:
        record: XML элемент записи (land_record, build_record, etc.)

    Returns:
        Dict с геометриями по типам:
        - "MultiPolygon": QgsGeometry или None
        - "MultiLineString": QgsGeometry или None
        - "MultiPoint": QgsGeometry или None
        - "NoGeometry": None (если нет геометрии)
    """
    all_polygons: List[QgsPolygon] = []
    all_lines: List[QgsLineString] = []
    all_points: List[QgsPoint] = []
    has_geometry = False

    # Ищем contours
    contours = record.findall('.//contour')
    if not contours:
        # Если contours нет, ищем spatial_elements напрямую
        spatial_elements_flat = record.findall('.//spatial_element')
        if spatial_elements_flat:
            # Создаем виртуальный contour
            try:
                from lxml import etree as ET
                dummy_contour = ET.Element("dummy_contour")
                for se in spatial_elements_flat:
                    dummy_contour.append(se)
                contours = [dummy_contour]
            except ImportError:
                pass

    for contour in contours:
        spatial_elements = contour.findall('.//spatial_element')
        if not spatial_elements:
            continue

        rings: List[List[QgsPoint]] = []
        lines_in_contour: List[List[QgsPoint]] = []
        points_in_contour: List[QgsPoint] = []

        for spatial_element in spatial_elements:
            ring_points: List[QgsPoint] = []

            for ordinate in spatial_element.findall('.//ordinate'):
                try:
                    # SWAP координат: X=North, Y=East в XML → X=East, Y=North в QGIS
                    x_text = ordinate.findtext("x")
                    y_text = ordinate.findtext("y")

                    if not x_text or not y_text:
                        continue

                    y = float(x_text)  # XML X → QGIS Y (North)
                    x = float(y_text)  # XML Y → QGIS X (East)

                    # M-координата (delta_geopoint = точность измерения)
                    delta_str = ordinate.findtext("delta_geopoint")
                    m_val = float(delta_str) if delta_str else 0.0

                    ring_points.append(QgsPoint(x, y, m=m_val))
                    has_geometry = True

                except (TypeError, ValueError):
                    pass

            if not ring_points:
                continue

            # Классификация геометрии
            if len(ring_points) == 1:
                # Точка
                points_in_contour.append(ring_points[0])
            elif len(ring_points) >= 4 and _is_ring_closed(ring_points):
                # Замкнутый контур (полигон)
                rings.append(ring_points)
            else:
                # Линия
                lines_in_contour.append(ring_points)

        # Собираем полигон из колец
        if rings:
            exterior_ring = QgsLineString(rings[0])
            polygon = QgsPolygon(exterior_ring)

            # Добавляем внутренние кольца (дырки)
            for interior_points in rings[1:]:
                interior_ring = QgsLineString(interior_points)
                polygon.addInteriorRing(interior_ring)

            all_polygons.append(polygon)

        # Линии
        if lines_in_contour:
            for line_points in lines_in_contour:
                all_lines.append(QgsLineString(line_points))

        # Точки
        if points_in_contour:
            all_points.extend(points_in_contour)

    # Формируем результат
    geometries: Dict[str, Optional[QgsGeometry]] = {}

    if all_polygons:
        geometries["MultiPolygon"] = QgsGeometry(QgsMultiPolygon(all_polygons))

    if all_lines:
        geometries["MultiLineString"] = QgsGeometry(QgsMultiLineString(all_lines))

    if all_points:
        geometries["MultiPoint"] = QgsGeometry(QgsMultiPoint(all_points))

    if not has_geometry:
        geometries["NoGeometry"] = None

    return geometries


def _is_ring_closed(points: List[QgsPoint]) -> bool:
    """
    Проверка замкнутости контура

    Args:
        points: Список точек контура

    Returns:
        True если контур замкнут (первая и последняя точки совпадают с допуском)
    """
    if len(points) < 2:
        return False

    start_point = points[0]
    end_point = points[-1]

    dist_sq = (start_point.x() - end_point.x())**2 + (start_point.y() - end_point.y())**2
    return dist_sq < (CLOSURE_TOLERANCE ** 2)
