# -*- coding: utf-8 -*-
"""
Субмодуль подсчёта пересечений линий АД и ЖД в границах работ
Выполняет обрезку линий по границам и подсчёт точек пересечения
"""

from typing import Dict, List, Tuple, Optional
from qgis.core import (
    QgsProject, QgsGeometry, QgsFeature,
    QgsVectorLayer, QgsWkbTypes, QgsPoint,
    QgsSpatialIndex, QgsFeatureRequest
)
from Daman_QGIS.utils import log_info, log_warning, log_error
import processing


class IntersectionsCalculator:
    """Калькулятор пересечений линий дорог и железных дорог"""

    def __init__(self, iface):
        """Инициализация калькулятора"""
        self.iface = iface
        self.project = QgsProject.instance()

    def calculate_intersections(self, boundaries_layer) -> Dict[str, int]:
        """
        Подсчёт пересечений линий в границах работ

        Алгоритм:
        1. Обрезка линий L_1_4_1 (АД) по границам L_1_1_1
        2. Обрезка линий L_1_4_2 (ЖД) по границам L_1_1_1
        3. Подсчёт пересечений:
           - АД и АД (включая самопересечения)
           - АД и ЖД
           - ЖД и ЖД (включая самопересечения)

        Args:
            boundaries_layer: Слой с границами работ (L_1_1_1)

        Returns:
            dict: {
                'road_road': количество пересечений АД-АД,
                'road_railway': количество пересечений АД-ЖД,
                'railway_railway': количество пересечений ЖД-ЖД
            }
        """
        results = {
            'road_road': 0,
            'road_railway': 0,
            'railway_railway': 0
        }

        if not boundaries_layer or not boundaries_layer.isValid():
            log_warning("Fsm_1_3_7: Недействительный слой границ")
            return results

        log_info("Fsm_1_3_7: Начало подсчёта пересечений линий")

        # Получаем объединённую геометрию границ
        boundaries_geom = self._get_boundaries_geometry(boundaries_layer)
        if not boundaries_geom:
            log_warning("Fsm_1_3_7: Не удалось получить геометрию границ")
            return results

        # Получаем слои АД и ЖД
        # ВАЖНО: OSM слои разделены на подслои (_line и _poly)
        # Для пересечений нужны только линейные слои
        road_layer = self._get_osm_road_layer()
        railway_layer = self._get_osm_railway_layer()

        if not road_layer and not railway_layer:
            log_warning("Fsm_1_3_7: Слои OSM АД и ЖД не найдены")
            return results

        # Обрезаем линии по границам
        clipped_roads = []
        clipped_railways = []

        if road_layer:
            clipped_roads = self._clip_lines_by_boundary(road_layer, boundaries_geom)
            log_info(f"Fsm_1_3_7: Обрезано линий АД ({road_layer.name()}): {len(clipped_roads)}")
        else:
            log_warning("Fsm_1_3_7: Слой OSM АД не найден, пересечения с АД = 0")

        if railway_layer:
            clipped_railways = self._clip_lines_by_boundary(railway_layer, boundaries_geom)
            log_info(f"Fsm_1_3_7: Обрезано линий ЖД ({railway_layer.name()}): {len(clipped_railways)}")
        else:
            log_warning("Fsm_1_3_7: Слой OSM ЖД не найден, пересечения с ЖД = 0")

        # Подсчитываем пересечения
        if clipped_roads:
            # АД и АД
            road_road_count = self._count_line_intersections(clipped_roads, clipped_roads)
            results['road_road'] = road_road_count
            log_info(f"Fsm_1_3_7: Пересечений АД-АД: {road_road_count}")

        if clipped_roads and clipped_railways:
            # АД и ЖД
            road_railway_count = self._count_line_intersections(clipped_roads, clipped_railways)
            results['road_railway'] = road_railway_count
            log_info(f"Fsm_1_3_7: Пересечений АД-ЖД: {road_railway_count}")

        if clipped_railways:
            # ЖД и ЖД
            railway_railway_count = self._count_line_intersections(clipped_railways, clipped_railways)
            results['railway_railway'] = railway_railway_count
            log_info(f"Fsm_1_3_7: Пересечений ЖД-ЖД: {railway_railway_count}")

        total = results['road_road'] + results['road_railway'] + results['railway_railway']
        log_info(f"Fsm_1_3_7: Всего пересечений: {total}")

        return results

    def _get_boundaries_geometry(self, boundaries_layer) -> Optional[QgsGeometry]:
        """
        Получение объединённой геометрии границ

        Args:
            boundaries_layer: Слой границ

        Returns:
            QgsGeometry: Объединённая геометрия или None
        """
        try:
            geometries = []

            for feature in boundaries_layer.getFeatures():
                if feature.hasGeometry():
                    geom = feature.geometry()
                    if geom and not geom.isNull():
                        geometries.append(geom)

            if geometries:
                # Объединяем все геометрии
                united = QgsGeometry.unaryUnion(geometries)
                if united and not united.isNull():
                    return united

            return None

        except Exception as e:
            log_error(f"Fsm_1_3_7: Ошибка получения геометрии границ - {str(e)}")
            return None

    def _get_layer_by_name(self, layer_name: str):
        """
        Получение слоя по имени

        Args:
            layer_name: Имя слоя

        Returns:
            QgsVectorLayer: Найденный слой или None
        """
        for layer in self.project.mapLayers().values():
            if layer.name() == layer_name:
                return layer

        return None

    def _get_osm_road_layer(self):
        """
        Получение линейного слоя OSM автодорог

        Ищет в порядке приоритета:
        1. Le_1_4_1_1_OSM_АД_line (подслой линий после обработки F_1_2)
        2. L_1_4_1_OSM_АД (родительский слой, если не был разделён)

        Returns:
            QgsVectorLayer: Найденный линейный слой или None
        """
        # Сначала ищем линейный подслой
        line_layer = self._get_layer_by_name('Le_1_4_1_1_OSM_АД_line')
        if line_layer and line_layer.isValid():
            geom_type = line_layer.geometryType()
            if geom_type == 1:  # LineString
                log_info(f"Fsm_1_3_7: Найден линейный слой АД: Le_1_4_1_1_OSM_АД_line")
                return line_layer

        # Затем ищем родительский слой
        parent_layer = self._get_layer_by_name('L_1_4_1_OSM_АД')
        if parent_layer and parent_layer.isValid():
            geom_type = parent_layer.geometryType()
            if geom_type == 1:  # LineString
                log_info(f"Fsm_1_3_7: Найден родительский линейный слой АД: L_1_4_1_OSM_АД")
                return parent_layer

        log_warning("Fsm_1_3_7: Линейный слой OSM АД не найден")
        return None

    def _get_osm_railway_layer(self):
        """
        Получение линейного слоя OSM железных дорог

        Ищет в порядке приоритета:
        1. Le_1_4_2_1_OSM_ЖД_line (подслой линий после обработки F_1_2)
        2. L_1_4_2_OSM_ЖД (родительский слой, если не был разделён)

        Returns:
            QgsVectorLayer: Найденный линейный слой или None
        """
        # Сначала ищем линейный подслой
        line_layer = self._get_layer_by_name('Le_1_4_2_1_OSM_ЖД_line')
        if line_layer and line_layer.isValid():
            geom_type = line_layer.geometryType()
            if geom_type == 1:  # LineString
                log_info(f"Fsm_1_3_7: Найден линейный слой ЖД: Le_1_4_2_1_OSM_ЖД_line")
                return line_layer

        # Затем ищем родительский слой
        parent_layer = self._get_layer_by_name('L_1_4_2_OSM_ЖД')
        if parent_layer and parent_layer.isValid():
            geom_type = parent_layer.geometryType()
            if geom_type == 1:  # LineString
                log_info(f"Fsm_1_3_7: Найден родительский линейный слой ЖД: L_1_4_2_OSM_ЖД")
                return parent_layer

        log_info("Fsm_1_3_7: Линейный слой OSM ЖД не найден (возможно нет данных в области)")
        return None

    def _clip_lines_by_boundary(self, line_layer, boundary_geom) -> List[QgsGeometry]:
        """
        Обрезка линий по границам

        Args:
            line_layer: Слой с линиями
            boundary_geom: Геометрия границ

        Returns:
            list: Список обрезанных геометрий линий
        """
        clipped_geometries = []

        try:
            if not line_layer or not line_layer.isValid():
                return clipped_geometries

            # Получаем bbox границ для предварительной фильтрации
            bbox = boundary_geom.boundingBox()

            # Создаём запрос с фильтрацией по bbox
            request = QgsFeatureRequest()
            request.setFilterRect(bbox)

            for feature in line_layer.getFeatures(request):
                if feature.hasGeometry():
                    geom = feature.geometry()
                    if geom and not geom.isNull():
                        # Проверяем пересечение с границами
                        if geom.intersects(boundary_geom):
                            # Обрезаем линию по границам
                            clipped = geom.intersection(boundary_geom)

                            if clipped and not clipped.isNull():
                                # Обрабатываем результат обрезки
                                # Может получиться MultiLineString или LineString
                                geom_type = clipped.wkbType()

                                if QgsWkbTypes.geometryType(geom_type) == QgsWkbTypes.LineGeometry:
                                    # Если MultiLineString, разбиваем на части
                                    # МИГРАЦИЯ LINESTRING → MULTILINESTRING: упрощённый паттерн
                                    parts = clipped.asMultiPolyline() if clipped.isMultipart() else [clipped.asPolyline()]
                                    for part in parts:
                                        if len(part) >= 2:  # Минимум 2 точки для линии
                                            line_geom = QgsGeometry.fromPolylineXY(part)
                                            clipped_geometries.append(line_geom)

            return clipped_geometries

        except Exception as e:
            log_error(f"Fsm_1_3_7: Ошибка обрезки линий {line_layer.name()} - {str(e)}")
            return clipped_geometries

    def _count_line_intersections(self, geometries_a: List[QgsGeometry],
                                  geometries_b: List[QgsGeometry]) -> int:
        """
        Подсчёт точек пересечения между двумя наборами линий

        Каждая точка касания/пересечения считается отдельно.
        Если линия A пересекает линию B в 2-х местах - это 2 пересечения.
        Самопересечения одной линии также считаются.

        Args:
            geometries_a: Первый набор линий
            geometries_b: Второй набор линий

        Returns:
            int: Количество точек пересечения
        """
        total_intersections = 0

        try:
            same_set = (geometries_a is geometries_b)

            for i, geom_a in enumerate(geometries_a):
                for j, geom_b in enumerate(geometries_b):
                    # Если это один и тот же набор, избегаем дублирования
                    if same_set and j <= i:
                        continue

                    # Проверяем касание/пересечение
                    if geom_a.touches(geom_b) or geom_a.intersects(geom_b):
                        # Получаем геометрию пересечения
                        intersection = geom_a.intersection(geom_b)

                        if intersection and not intersection.isNull():
                            # Подсчитываем точки пересечения
                            points_count = self._count_intersection_points(intersection)
                            total_intersections += points_count

            # Для одного и того же набора также считаем самопересечения каждой линии
            if same_set:
                for geom in geometries_a:
                    self_intersections = self._count_self_intersections(geom)
                    total_intersections += self_intersections

            return total_intersections

        except Exception as e:
            log_error(f"Fsm_1_3_7: Ошибка подсчёта пересечений - {str(e)}")
            return total_intersections

    def _count_intersection_points(self, intersection_geom: QgsGeometry) -> int:
        """
        Подсчёт количества точек в геометрии пересечения

        Args:
            intersection_geom: Геометрия пересечения (может быть Point, MultiPoint, LineString и т.д.)

        Returns:
            int: Количество точек
        """
        try:
            geom_type = intersection_geom.wkbType()
            geometry_type = QgsWkbTypes.geometryType(geom_type)

            if geometry_type == QgsWkbTypes.PointGeometry:
                # Точка или MultiPoint
                if intersection_geom.isMultipart():
                    return len(intersection_geom.asMultiPoint())
                else:
                    return 1
            elif geometry_type == QgsWkbTypes.LineGeometry:
                # Если получилась линия - это наложение, считаем как 1 пересечение
                # (линии идут параллельно на каком-то участке)
                return 1
            else:
                # Для других типов (полигон и т.д.) считаем как 1
                return 1

        except Exception as e:
            log_warning(f"Fsm_1_3_7: Ошибка подсчёта точек пересечения - {str(e)}")
            return 0

    def _count_self_intersections(self, geom: QgsGeometry) -> int:
        """
        Подсчёт самопересечений одной линии (петли, восьмёрки)

        Args:
            geom: Геометрия линии

        Returns:
            int: Количество точек самопересечения
        """
        try:
            # Проверяем является ли геометрия простой (simple)
            # Непростая геометрия содержит самопересечения
            if geom.isSimple():
                return 0

            # Для непростых геометрий нужно найти точки самопересечения
            # Используем алгоритм: разбиваем линию на сегменты и ищем пересечения
            # МИГРАЦИЯ LINESTRING → MULTILINESTRING: упрощённый паттерн
            polyline = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]

            self_intersection_count = 0

            for line_part in polyline:
                # Создаём сегменты
                segments = []
                for i in range(len(line_part) - 1):
                    p1 = line_part[i]
                    p2 = line_part[i + 1]
                    segment = QgsGeometry.fromPolylineXY([p1, p2])
                    segments.append(segment)

                # Проверяем пересечения между сегментами
                for i, seg_a in enumerate(segments):
                    for j, seg_b in enumerate(segments):
                        # Пропускаем соседние сегменты (они всегда касаются в вершине)
                        if abs(i - j) <= 1:
                            continue

                        if seg_a.intersects(seg_b):
                            intersection = seg_a.intersection(seg_b)
                            if intersection and not intersection.isNull():
                                points = self._count_intersection_points(intersection)
                                self_intersection_count += points

            # Делим на 2, так как каждое пересечение подсчитали дважды (A∩B и B∩A)
            return self_intersection_count // 2

        except Exception as e:
            log_warning(f"Fsm_1_3_7: Ошибка подсчёта самопересечений - {str(e)}")
            return 0
