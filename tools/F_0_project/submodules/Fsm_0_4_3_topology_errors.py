# -*- coding: utf-8 -*-
"""
Модуль проверки топологических ошибок: наложения и острые углы
Использует spatial index и QgsGeometry методы
"""

import math
from typing import List, Dict, Any, Tuple
from qgis.core import (
    QgsVectorLayer, QgsGeometry,
    QgsPointXY, QgsSpatialIndex, QgsFeatureRequest, QgsRectangle,
    QgsWkbTypes, QgsGeometryUtils
)
from Daman_QGIS.utils import log_info, log_warning
from Daman_QGIS.managers.M_6_coordinate_precision import CoordinatePrecisionManager as CPM
from Daman_QGIS.constants import COORDINATE_PRECISION

class Fsm_0_4_3_TopologyErrorsChecker:
    """Проверка наложений и острых углов"""

    # Минимальная площадь наложения (м²)
    # Наложения меньше этого порога = артефакты округления координат (СКП 0.10м)
    MIN_OVERLAP_AREA = COORDINATE_PRECISION  # 0.01 м²

    # Spike (пиковый узел) - вершина где контур делает ОСТРЫЙ V-образный поворот
    #
    # Определение: ОСТРЫЙ внутренний угол полигона (близко к 0° или 360°)
    # - Прямая линия: внутренний угол ≈ 180° → НЕ spike
    # - Острый поворот: внутренний угол ≈ 0° или 360° → SPIKE!
    #
    # Визуальные примеры:
    # 1. Прямая линия: (0,0) → (1,0) → (2,0)
    #    Внутренний угол = 180° → min(180, 360-180) = 180° → НЕ spike ✓
    #
    # 2. V-образный spike: (178979.13, 482013.16) → (178979.60, 482002.35) → (178979.12, 482013.16)
    #    Контур идёт к точке и возвращается почти обратно
    #    Внутренний угол ≈ 0.05° → min(0.05, 360-0.05) = 0.05° → SPIKE! ✓
    #
    # Для кадастровых работ такие вершины критичны - создают излишние изломы контура
    SPIKE_ANGLE_THRESHOLD = 1.0  # градусы (острый угол ≤ 1° = spike)

    def __init__(self):
        self.overlaps_found = 0
        self.spikes_found = 0

    def check(self, layer: QgsVectorLayer) -> Tuple[List[Dict], List[Dict]]:
        """
        Комплексная проверка топологических ошибок

        Returns:
            Tuple из (overlaps, spikes)
        """
        log_info(f"Fsm_0_4_3: Запуск проверки наложений и spike углов для слоя '{layer.name()}'")

        overlaps = self._check_overlaps(layer)
        spikes = self._check_spikes(layer)

        log_info(f"Fsm_0_4_3: Результаты - наложений: {len(overlaps)}, spike углов: {len(spikes)}")
        return overlaps, spikes

    def _check_overlaps(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Проверка наложений через spatial index

        Returns:
            Список наложений
        """
        errors = []
        filtered_count = 0
        log_info(f"Fsm_0_4_3: Начало проверки наложений для слоя '{layer.name()}'")

        # Создаем пространственный индекс для оптимизации
        index = QgsSpatialIndex(layer.getFeatures())

        features = {f.id(): f for f in layer.getFeatures()}
        checked_pairs = set()

        for fid, feature in features.items():
            geom = feature.geometry()
            if not geom or geom.isEmpty():
                continue

            # Находим потенциально пересекающиеся объекты через индекс
            bbox = geom.boundingBox()
            candidate_ids = index.intersects(bbox)

            for candidate_id in candidate_ids:
                if candidate_id == fid:
                    continue

                # Проверяем что пара еще не проверена
                pair = tuple(sorted([fid, candidate_id]))
                if pair in checked_pairs:
                    continue
                checked_pairs.add(pair)

                candidate_geom = features[candidate_id].geometry()
                if not candidate_geom or candidate_geom.isEmpty():
                    continue

                # Проверяем пересечение
                if geom.intersects(candidate_geom):
                    # Проверяем что это не просто касание
                    if geom.overlaps(candidate_geom) or geom.within(candidate_geom) or candidate_geom.within(geom):
                        # Получаем геометрию пересечения
                        intersection = geom.intersection(candidate_geom)

                        if intersection and not intersection.isEmpty():
                            # Для полигонов берем только площадные пересечения
                            if intersection.type() == QgsWkbTypes.PolygonGeometry:
                                area = intersection.area()

                                # Фильтрация микро-наложений (артефакты округления)
                                if area < self.MIN_OVERLAP_AREA:
                                    filtered_count += 1
                                    continue

                                errors.append({
                                    'type': 'overlap',
                                    'geometry': intersection,
                                    'feature_id': fid,
                                    'feature_id2': candidate_id,
                                    'description': f'Наложение полигонов (объекты {fid} и {candidate_id}), площадь {area:.4f} кв.м',
                                    'area': area
                                })

        self.overlaps_found = len(errors)

        if filtered_count > 0:
            log_info(f"Fsm_0_4_3: Отфильтровано {filtered_count} микро-наложений (< {self.MIN_OVERLAP_AREA} м²)")

        if self.overlaps_found > 0:
            log_info(f"Fsm_0_4_3: Найдено {self.overlaps_found} наложений")
        else:
            log_info(f"Fsm_0_4_3: Наложения не обнаружены")

        return errors

    def _check_spikes(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Проверка острых углов через извлечение вершин и анализ углов
        Работает только для полигональных слоев

        Returns:
            Список острых углов
        """
        errors = []
        log_info(f"Fsm_0_4_3: Начало проверки spike углов для слоя '{layer.name()}'")

        # Проверяем что слой полигональный
        if layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            log_info(f"Fsm_0_4_3: Слой '{layer.name()}' не является полигональным, проверка острых углов пропущена")
            self.spikes_found = 0
            return errors

        try:
            # Обрабатываем каждый feature и каждый полигон отдельно
            # ВАЖНО: Для MultiPolygon проверяем spike ВНУТРИ каждой части,
            # а не между разными частями (иначе будут ложные срабатывания)

            total_features = 0
            total_vertices = 0
            angles_checked = 0

            # Для защиты от дубликатов (может быть несколько частей MultiPolygon)
            processed_spikes = set()  # (fid, x, y, angle) для уникальности

            for feature in layer.getFeatures():
                fid = feature.id()
                geom = feature.geometry()

                if not geom or geom.isEmpty():
                    continue

                total_features += 1

                # Извлекаем полигоны из MultiPolygon (UNIFIED PATTERN)
                polygons = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]

                # Обрабатываем каждый полигон ОТДЕЛЬНО
                for polygon_idx, polygon in enumerate(polygons):
                    if not polygon:
                        continue

                    # Внешнее кольцо полигона (не проверяем holes)
                    outer_ring = polygon[0]
                    vertices = []

                    for i, point in enumerate(outer_ring):
                        vertices.append({
                            'index': i,
                            'point': QgsPointXY(point),
                            'polygon_idx': polygon_idx  # Для MultiPolygon
                        })

                    total_vertices += len(vertices)

                    # Проверяем spike вершины ВНУТРИ этого полигона
                    for i, vertex_info in enumerate(vertices):
                        # ВАЖНО: Пропускаем последнюю вершину (замыкающую)
                        # В PyQGIS полигоны хранятся с дублирующей первую точкой:
                        # [(0,0), (10,0), (10,10), (0,10), (0,0)]
                        #   ^                               ^
                        #   |_______________________________|
                        # Последняя вершина = первая → angle всегда 0°
                        if i == len(vertices) - 1:
                            continue

                        if len(vertices) < 3:
                            continue  # Нужно минимум 3 вершины для проверки угла

                        # Берем 3 последовательные точки
                        prev_idx = (i - 1) % len(vertices)
                        next_idx = (i + 1) % len(vertices)

                        p1 = vertices[prev_idx]['point']
                        p2 = vertex_info['point']
                        p3 = vertices[next_idx]['point']

                        # ВАЖНО: Проверяем что все 3 точки разные
                        # Из-за замыкающей вершины p1 может совпадать с p2 (для i=0)
                        # или p2 может совпадать с p3 (для i=len-2)
                        if p1 == p2 or p2 == p3 or p1 == p3:
                            continue  # Пропускаем вершины с совпадающими соседями

                        angle = self._calculate_angle(p1, p2, p3)
                        angles_checked += 1  # Инкрементируем счётчик проверенных углов

                        # Проверяем порог (spike = острый угол ≤ 1°)
                        if angle <= self.SPIKE_ANGLE_THRESHOLD:
                            # Защита от дубликатов: проверяем координаты + angle
                            # Используем CPM для математического округления координат
                            rounded_coords = CPM.round_point_tuple(p2)
                            spike_key = (fid, rounded_coords[0], rounded_coords[1], round(angle, 4))

                            if spike_key not in processed_spikes:
                                processed_spikes.add(spike_key)
                                errors.append({
                                    'type': 'spike',
                                    'geometry': QgsGeometry.fromPointXY(p2),
                                    'feature_id': fid,
                                    'vertex_index': vertex_info['index'],
                                    'description': f'Острый угол {angle:.4f} град. (объект {fid}, вершина {vertex_info["index"]})',
                                    'angle': angle
                                })

            # Итоговая статистика
            log_info(f"Fsm_0_4_3: Обработано {total_features} объектов, {total_vertices} вершин, проверено {angles_checked} углов")

            self.spikes_found = len(errors)
            if self.spikes_found > 0:
                log_info(f"Fsm_0_4_3: ✓ Найдено {self.spikes_found} spike вершин (острый угол ≤ {self.SPIKE_ANGLE_THRESHOLD}°)")
            else:
                log_info(f"Fsm_0_4_3: Spike вершины не обнаружены")
            return errors

        except Exception as e:
            # При ошибке возвращаем то что успели найти
            log_warning(f"Fsm_0_4_3: Check spike angles: {str(e)}")
            self.spikes_found = len(errors)
            return errors

    def _calculate_angle(self, p1: QgsPointXY, p2: QgsPointXY, p3: QgsPointXY) -> float:
        """
        Вычисление ОСТРОГО внутреннего угла в вершине p2

        Spike - это вершина где контур делает V-образный выступ (острый угол).

        Геометрия:
        - Прямая линия: внутренний угол ≈ 180° → НЕ spike
        - Острый поворот: внутренний угол ≈ 0° или 360° → SPIKE!

        Примеры:
        1. Прямая линия: (0,0) → (1,0) → (2,0)
           angle = 180° → min(180, 180) = 180° → НЕ spike ✓

        2. V-образный spike: A → B → C где B делает микро-отклонение
           Контур почти возвращается в исходную точку
           angle ≈ 0° → min(0, 360) = 0° → SPIKE! ✓

        Args:
            p1, p2, p3: Три последовательные точки контура (p2 - проверяемая вершина)

        Returns:
            Острый угол (минимальное расстояние до 0° или 360°)
            Чем меньше значение - тем острее spike
        """
        # Вектор от p2 к p1
        v1_x = p1.x() - p2.x()
        v1_y = p1.y() - p2.y()

        # Вектор от p2 к p3
        v2_x = p3.x() - p2.x()
        v2_y = p3.y() - p2.y()

        # Угол каждого вектора относительно оси X
        angle1 = math.atan2(v1_y, v1_x)
        angle2 = math.atan2(v2_y, v2_x)

        # Внутренний угол полигона в точке p2 (поворот от v1 к v2)
        angle_diff = angle2 - angle1
        angle_deg = math.degrees(angle_diff)

        # Нормализуем в диапазон 0-360°
        if angle_deg < 0:
            angle_deg += 360

        # Spike = ОСТРЫЙ угол (близко к 0° или 360°)
        # Вычисляем минимальное расстояние до 0° или 360°
        spike_angle = min(angle_deg, 360.0 - angle_deg)

        # DEBUG: Логируем детали вычисления для анализа
        if spike_angle <= self.SPIKE_ANGLE_THRESHOLD:
            log_info(f"Fsm_0_4_3: DEBUG spike: p2=({p2.x():.2f},{p2.y():.2f}), "
                     f"внутр.угол={angle_deg:.2f}°, острый={spike_angle:.4f}°")

        return spike_angle

    def get_errors_count(self) -> Tuple[int, int]:
        """Возвращает (overlaps, spikes)"""
        return self.overlaps_found, self.spikes_found
