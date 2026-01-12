# -*- coding: utf-8 -*-
"""
Fsm_1_1_4_3 - Извлечение геометрии из XML выписок

ВАЖНО: Координаты НЕ округляются (импортируем "как есть")!

АРХИТЕКТУРА:
- Проверка замыкания контуров: M_6_coordinate_precision.is_ring_closed()
- Стандартная проверка (без оптимизации) для выписок ОН

КРИТИЧЕСКИЕ ФИКСЫ:
- FIX (2025-11-18): Правильная обработка дыр (inner rings) в полигонах
  * Группировка spatial_elements по контурам
  * КРИТИЧНО: Автоматическое определение внешнего контура и дыр:
    1. Самый большой ring (по площади) = кандидат на внешний контур
    2. Проверка: все остальные rings полностью ВНУТРИ самого большого?
    3. Если ДА → создаём ОДИН полигон с дырами (outer + holes)
    4. Если НЕТ → создаём ОТДЕЛЬНЫЕ полигоны
  * Примеры:
    - 23:47:0000000:3436 (контур 3): большой ring + маленький ring внутри → полигон с дырой
    - 23:47:0000000:6588 (контур 1): большой ring + маленький ring внутри → полигон с дырой
  * НЕ зависит от порядка spatial_elements в XML (автоопределение по площади)
  * Использование QgsGeometry.contains() для проверки вложенности
  * Использование QgsPolygon.addInteriorRing() для топологии
  * forceCounterClockwise() для коррекции ориентации (OGC стандарт)
  * Паттерн из kd_kpt/kd_kpt_cleaned.py:827-833

- FIX: Для ЕЗ с большим количеством spatial_element используется unaryUnion
  * Обход лимита OGR на количество полигонов в MultiPolygon (>100 частей)

- FIX (2024-12): Поддержка M-координат (delta_geopoint)
  * delta_geopoint = погрешность геодезического измерения точки (метры)
  * Хранится в M-координате QgsPoint: QgsPoint(x, y, m=delta)
  * Типы геометрий: MultiPolygonM, MultiLineStringM, MultiPointM
  * 98% выписок содержат delta_geopoint
  * Позволяет анализировать точность межевания
"""

from typing import Dict
from qgis.core import (
    QgsGeometry, QgsPoint, QgsPointXY, QgsLineString, QgsPolygon,
    QgsMultiPolygon, QgsMultiLineString, QgsMultiPoint
)

from Daman_QGIS.managers.M_6_coordinate_precision import CoordinatePrecisionManager
from Daman_QGIS.utils import log_info, log_error, log_warning


def extract_geometry(geometry_root_element) -> Dict[str, QgsGeometry]:
    """
    Извлечение геометрии из XML элемента (БЕЗ ВАЛИДАЦИИ!)

    ВАЖНО: Геометрия импортируется "как есть" из XML.
    НЕТ валидации, НЕТ исправлений (как в оригинальном kd_on).

    ЛОГИКА:
    - Каждый spatial_element = отдельный полигон
    - Геометрия создаётся напрямую из точек БЕЗ проверок топологии

    Args:
        geometry_root_element: XML элемент с contours_location или contours

    Returns:
        Dict[geom_type, QgsGeometry]: Словарь геометрий по типам
    """
    if geometry_root_element is None:
        return {}

    all_polygons, all_lines, all_points = [], [], []

    # FIX: Группируем spatial_elements по контурам для правильной обработки дыр (inner rings)
    # ВАЖНО: Каждый <contour> может содержать несколько <spatial_element>:
    #   - Первый spatial_element = внешнее кольцо (outer ring)
    #   - Последующие = дыры (holes/inner rings)
    # Обработка по контурам гарантирует правильную топологию полигонов

    contours = geometry_root_element.findall('.//contour')

    # Если нет явных контуров, трактуем все spatial_elements как отдельные контуры
    if not contours:
        spatial_elements_flat = geometry_root_element.findall('.//spatial_element')
        if spatial_elements_flat:
            # Создаём "виртуальный" контур для каждого spatial_element
            for se in spatial_elements_flat:
                contours.append(se)

    for contour in contours:
        # Извлекаем все spatial_elements в контуре
        spatial_elements = contour.findall('.//spatial_element')
        if not spatial_elements:
            # Если контур - это сам spatial_element (виртуальный контур)
            spatial_elements = [contour] if contour.tag == 'spatial_element' else []

        rings = []
        lines_in_contour = []
        points_in_contour = []

        for spatial_element in spatial_elements:
            ring_points = []
            for ordinate in spatial_element.findall('.//ordinates/ordinate'):
                x_text = ordinate.findtext("x")
                y_text = ordinate.findtext("y")
                if x_text and y_text:
                    # ВАЖНО: НЕ округляем координаты из выписок!
                    # FIX: SWAP координат для российских МСК (X=North, Y=East в XML)
                    # QGIS ожидает (X=East, Y=North) → меняем местами

                    # FIX: Извлекаем delta_geopoint (погрешность точки) и сохраняем в M-координате
                    delta_text = ordinate.findtext("delta_geopoint")
                    delta = float(delta_text) if delta_text else 0.0
                    ring_points.append(QgsPoint(float(y_text), float(x_text), m=delta))

            if not ring_points:
                continue

            # Классифицируем геометрию по количеству точек
            if len(ring_points) == 1:
                points_in_contour.append(ring_points[0])
            elif len(ring_points) >= 4 and CoordinatePrecisionManager.is_ring_closed(ring_points):
                # Полигон (замкнутый контур) - собираем в rings
                rings.append(ring_points)
            else:
                # Линия (незамкнутый контур)
                lines_in_contour.append(ring_points)

        # Создаём полигон с дырами (если есть несколько колец)
        if rings:
            # КРИТИЧНО: Проверяем вложенность rings для определения топологии
            # - Если rings[1:] полностью ВНУТРИ rings[0] → первый=outer, остальные=holes
            # - Иначе → каждый ring = отдельный полигон

            if len(rings) == 1:
                # Один ring → простой полигон
                exterior_ring = QgsLineString(rings[0])
                polygon = QgsPolygon(exterior_ring)
                # ВАЖНО: forceCounterClockwise() устанавливает exterior CCW, interior CW
                polygon.forceCounterClockwise()
                all_polygons.append(polygon)

            else:
                # Несколько rings → определяем внешний контур и дыры
                # КРИТИЧНО: Внешний контур = ring с наибольшей площадью

                # Создаём временные геометрии и вычисляем площади
                ring_geoms = []
                for ring_points in rings:
                    ring_xy = [QgsPointXY(pt.x(), pt.y()) for pt in ring_points]
                    geom = QgsGeometry.fromPolygonXY([ring_xy])
                    area = geom.area()
                    ring_geoms.append((ring_points, geom, area))

                # Сортируем по площади (самый большой первый)
                ring_geoms.sort(key=lambda x: x[2], reverse=True)

                # Первый (самый большой) = кандидат на внешний контур
                outer_ring_points, outer_geom, _ = ring_geoms[0]
                potential_holes = ring_geoms[1:]

                # Проверяем, все ли остальные rings внутри самого большого
                all_contained = True
                for _, hole_geom, _ in potential_holes:
                    if not outer_geom.contains(hole_geom):
                        all_contained = False
                        break

                if all_contained:
                    # Все меньшие rings внутри большого → outer + holes
                    exterior_ring = QgsLineString(outer_ring_points)
                    polygon = QgsPolygon(exterior_ring)

                    for hole_points, _, _ in potential_holes:
                        interior_ring = QgsLineString(hole_points)
                        polygon.addInteriorRing(interior_ring)

                    # КРИТИЧНО: forceCounterClockwise() на QgsPolygon устанавливает:
                    # - exterior ring: counter-clockwise (OGC стандарт)
                    # - interior rings: clockwise (дыры)
                    polygon.forceCounterClockwise()

                    # DEBUG: Проверяем валидность полигона с дырами
                    test_geom = QgsGeometry(polygon.clone())
                    if hasattr(test_geom, 'isGeosValid') and not test_geom.isGeosValid():
                        log_warning(f"Fsm_1_1_4_3: Невалидный полигон после forceCounterClockwise(): exterior ring + {len(potential_holes)} holes")
                        if hasattr(test_geom, 'validateGeometry'):
                            errors = test_geom.validateGeometry()
                            for error in errors[:3]:  # Первые 3 ошибки
                                log_warning(f"  Ошибка валидации: {error.what()}")

                    all_polygons.append(polygon)

                else:
                    # НЕ все вложены → отдельные полигоны
                    for ring_points in rings:
                        ring = QgsLineString(ring_points)
                        polygon = QgsPolygon(ring)
                        polygon.forceCounterClockwise()
                        all_polygons.append(polygon)

        # Добавляем линии из контура
        if lines_in_contour:
            all_lines.extend(lines_in_contour)

        # Добавляем точки из контура
        if points_in_contour:
            all_points.extend(points_in_contour)

    # Формируем результат
    geometries = {}

    # ПОЛИГОНЫ - создаём ВСЕГДА как MultiPolygon (UNIFIED PATTERN)
    if all_polygons:
        try:
            # FIX: Используем QgsMultiPolygon напрямую, так как all_polygons уже содержит QgsPolygon объекты
            # (с правильной обработкой дыр через addInteriorRing)
            multi_polygon = QgsMultiPolygon()
            for polygon in all_polygons:
                multi_polygon.addGeometry(polygon.clone())

            geom = QgsGeometry(multi_polygon)

            # DEBUG: Проверяем валидность ДО unaryUnion
            if hasattr(geom, 'isGeosValid'):
                initial_valid = geom.isGeosValid()
                if not initial_valid:
                    log_warning(f"Fsm_1_1_4_3: MultiPolygon невалиден ДО unaryUnion ({len(all_polygons)} полигонов)")

            # FIX #1: Проверка количества частей (для обхода лимита OGR)
            if geom.isMultipart():
                num_parts = geom.constGet().numGeometries()

                # КРИТИЧНО: Если >100 частей → применяем unaryUnion() (обход лимита OGR)
                MAX_MULTIPOLYGON_PARTS = 100
                if num_parts > MAX_MULTIPOLYGON_PARTS:
                    log_info(f"Fsm_1_1_4_3: Применяем unaryUnion() для {num_parts} частей")

                    # Извлекаем все части MultiPolygon как отдельные геометрии
                    parts = []
                    for i in range(num_parts):
                        part_geom = QgsGeometry(geom.constGet().geometryN(i).clone())
                        parts.append(part_geom)

                    # Применяем unaryUnion к списку геометрий
                    geom = QgsGeometry.unaryUnion(parts)

                    if not geom or geom.isEmpty():
                        log_error(f"Fsm_1_1_4_3: unaryUnion вернул пустую геометрию ({num_parts} исходных частей)")

            # DEBUG: Финальная проверка валидности (логируем только проблемы)
            if hasattr(geom, 'isGeosValid'):
                final_valid = geom.isGeosValid()
                if not final_valid:
                    log_warning(f"Fsm_1_1_4_3: MultiPolygon НЕВАЛИДЕН (финальная проверка)")
                    if hasattr(geom, 'validateGeometry'):
                        errors = geom.validateGeometry()
                        log_warning(f"Fsm_1_1_4_3: Ошибок валидации: {len(errors)}")
                        for error in errors[:5]:  # Первые 5 ошибок
                            log_warning(f"  {error.what()}")

            # ВАЖНО: Импортируем "как есть" (координаты НЕ меняются)
            # FIX: Используем MultiPolygonM для хранения M-координат (delta_geopoint)
            geometries["MultiPolygonM"] = geom

        except Exception as e:
            log_error(f"Fsm_1_1_4_3: Ошибка создания MultiPolygon: {e}")
            import traceback
            log_error(f"Fsm_1_1_4_3: {traceback.format_exc()}")

    # ЛИНИИ
    # FIX: Используем MultiLineStringM для хранения M-координат (delta_geopoint)
    if all_lines:
        multi_line = QgsMultiLineString([QgsLineString(line) for line in all_lines])
        geometries["MultiLineStringM"] = QgsGeometry(multi_line)

    # ТОЧКИ
    # FIX: Используем MultiPointM для хранения M-координат (delta_geopoint)
    if all_points:
        geometries["MultiPointM"] = QgsGeometry(QgsMultiPoint(all_points))

    if not geometries:
        return {"NoGeometry": None}

    return geometries
