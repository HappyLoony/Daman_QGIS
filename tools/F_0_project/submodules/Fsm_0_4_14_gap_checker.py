# -*- coding: utf-8 -*-
"""
Fsm_0_4_14: Анализ покрытия (зазоры) - обнаружение пустот между полигонами

Алгоритм негативного пространства (Negative Space / Inverse Polygon):
1. Объединение всех геометрий слоя (unaryUnion)
2. Построение envelope = bbox + 20% буфер
3. Вычитание: envelope.difference(union) = негативное пространство
4. Разбиение на отдельные полигоны и классификация: internal / external
5. Анализ spike-углов на границе union (exterior + interior rings)

Типы ошибок:
- 'gap': зазор покрытия (пустота между полигонами)
- 'gap_spike': пиковый узел на границе union (острый угол = разрыв покрытия)

Опциональная проверка, по умолчанию ВЫКЛЮЧЕНА (ресурсоемкая операция).
Включается через checkbox в диалоге F_0_4.
"""

import math
from typing import List, Dict, Any, Tuple, Optional

from qgis.core import (
    Qgis, QgsVectorLayer, QgsGeometry, QgsPointXY,
    QgsWkbTypes, QgsRectangle
)

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.constants import COORDINATE_PRECISION


class Fsm_0_4_14_GapChecker:
    """
    Анализ покрытия территории - обнаружение зазоров между полигонами.

    Метод негативного пространства: envelope минус union всех геометрий.
    Оставшиеся внутренние полигоны = зазоры (пустоты между объектами).
    Дополнительно: spike-анализ на границе union для обнаружения разрывов.
    """

    # Максимальная площадь зазора для обнаружения (м2)
    # Зазоры > этого порога считаются намеренными (отступы, резервные территории)
    DEFAULT_MAX_GAP_AREA = 100.0

    # Минимальная площадь для отсечения шума от float-арифметики
    MIN_GAP_AREA = COORDINATE_PRECISION  # 0.01 м2

    # Буферный коэффициент для envelope (20% от максимального размера bbox)
    ENVELOPE_BUFFER_RATIO = 0.2

    # Порог spike-угла для границы union (градусы)
    # Шире чем у Fsm_0_4_3 (1 градус), т.к. union boundary менее точна
    DEFAULT_SPIKE_THRESHOLD = 5.0

    def __init__(self,
                 max_gap_area: Optional[float] = None,
                 spike_angle_threshold: Optional[float] = None):
        """
        Инициализация checker'а

        Args:
            max_gap_area: Макс. площадь зазора (м2). По умолчанию 100.0
            spike_angle_threshold: Порог spike-угла (градусы). По умолчанию 5.0
        """
        self.max_gap_area = (
            max_gap_area if max_gap_area is not None
            else self.DEFAULT_MAX_GAP_AREA
        )
        self.spike_angle_threshold = (
            spike_angle_threshold or self.DEFAULT_SPIKE_THRESHOLD
        )
        self.gaps_found = 0
        self.spikes_found = 0

    def check(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Анализ покрытия слоя: поиск зазоров и spike-узлов на union boundary.

        Args:
            layer: Полигональный слой для проверки

        Returns:
            Список ошибок (type='gap' и type='gap_spike')
        """
        errors: List[Dict[str, Any]] = []

        # 1. Проверка типа геометрии
        if layer.geometryType() != Qgis.GeometryType.Polygon:
            log_info(
                f"Fsm_0_4_14: Слой '{layer.name()}' не полигональный, пропуск"
            )
            return errors

        feature_count = layer.featureCount()
        if feature_count < 2:
            log_info(
                f"Fsm_0_4_14: Слой '{layer.name()}' содержит < 2 объектов, "
                "анализ покрытия невозможен"
            )
            return errors

        log_info(
            f"Fsm_0_4_14: Анализ покрытия для '{layer.name()}' "
            f"({feature_count} объектов)"
        )
        log_info(
            f"Fsm_0_4_14: Параметры: max_gap_area={self.max_gap_area}, "
            f"spike_threshold={self.spike_angle_threshold}"
        )

        try:
            # 2. Построение негативного пространства
            union_geom, envelope_geom = self._build_union_and_envelope(layer)
            if union_geom is None or envelope_geom is None:
                return errors

            negative_space = envelope_geom.difference(union_geom)
            if negative_space is None or negative_space.isEmpty():
                log_info(
                    "Fsm_0_4_14: Негативное пространство пустое "
                    "(полное покрытие без зазоров)"
                )
                # Все равно проверяем spikes на union boundary
                spike_errors = self._check_union_spikes(union_geom)
                errors.extend(spike_errors)
                self.spikes_found = len(spike_errors)
                return errors

            # 3. Классификация зазоров
            gap_errors = self._classify_gaps(negative_space, envelope_geom)
            errors.extend(gap_errors)
            self.gaps_found = len(gap_errors)

            # 4. Анализ spike-углов на union boundary
            spike_errors = self._check_union_spikes(union_geom)
            errors.extend(spike_errors)
            self.spikes_found = len(spike_errors)

        except Exception as e:
            log_error(f"Fsm_0_4_14: Ошибка анализа покрытия: {e}")

        # 5. Итоговое логирование
        if self.gaps_found > 0:
            log_warning(
                f"Fsm_0_4_14: Найдено {self.gaps_found} зазоров"
            )
        else:
            log_info("Fsm_0_4_14: Зазоры не обнаружены")

        if self.spikes_found > 0:
            log_warning(
                f"Fsm_0_4_14: Найдено {self.spikes_found} "
                "spike-узлов на union boundary"
            )
        else:
            log_info(
                "Fsm_0_4_14: Spike-узлы на union boundary не обнаружены"
            )

        return errors

    def _build_union_and_envelope(
        self, layer: QgsVectorLayer
    ) -> Tuple[Optional[QgsGeometry], Optional[QgsGeometry]]:
        """
        Объединение всех геометрий слоя и построение envelope.

        Args:
            layer: Полигональный слой

        Returns:
            (union_geom, envelope_geom) или (None, None) при ошибке
        """
        geometries = []
        invalid_count = 0

        for feature in layer.getFeatures():
            geom = feature.geometry()
            if not geom or geom.isEmpty():
                continue

            # Валидация геометрии перед union
            if not geom.isGeosValid():
                geom = geom.makeValid()
                if not geom or geom.isEmpty():
                    invalid_count += 1
                    continue

            geometries.append(geom)

        if invalid_count > 0:
            log_warning(
                f"Fsm_0_4_14: Пропущено {invalid_count} "
                "невалидных геометрий"
            )

        if len(geometries) < 2:
            log_info(
                "Fsm_0_4_14: Недостаточно валидных геометрий "
                "для анализа покрытия"
            )
            return None, None

        log_info(
            f"Fsm_0_4_14: Объединение {len(geometries)} геометрий..."
        )

        # Объединение всех геометрий
        union_geom = QgsGeometry.unaryUnion(geometries)

        if union_geom is None or union_geom.isEmpty():
            log_warning(
                "Fsm_0_4_14: unaryUnion вернул пустой результат"
            )
            return None, None

        # Валидация union
        if not union_geom.isGeosValid():
            union_geom = union_geom.makeValid()

        log_info(
            f"Fsm_0_4_14: Union успешен, "
            f"площадь: {union_geom.area():.2f} м2"
        )

        # Построение envelope с буфером
        bbox = union_geom.boundingBox()
        max_dim = max(bbox.width(), bbox.height())
        buffer_dist = max_dim * self.ENVELOPE_BUFFER_RATIO

        buffered_rect = bbox.buffered(buffer_dist)
        envelope_geom = QgsGeometry.fromRect(buffered_rect)

        log_info(
            f"Fsm_0_4_14: Envelope построен "
            f"(буфер {buffer_dist:.2f} м)"
        )

        return union_geom, envelope_geom

    def _classify_gaps(
        self,
        negative_space: QgsGeometry,
        envelope_geom: QgsGeometry
    ) -> List[Dict[str, Any]]:
        """
        Разбиение негативного пространства на отдельные зазоры
        и классификация по типу (internal/external) и площади.

        Args:
            negative_space: Результат envelope.difference(union)
            envelope_geom: Геометрия envelope для определения external/internal

        Returns:
            Список ошибок type='gap'
        """
        errors: List[Dict[str, Any]] = []

        # Граница envelope для определения external зазоров
        envelope_boundary = envelope_geom.boundary()

        # Разбиваем multipart на отдельные полигоны
        if negative_space.isMultipart():
            gap_polygons = negative_space.asGeometryCollection()
        else:
            gap_polygons = [negative_space]

        log_info(
            f"Fsm_0_4_14: Найдено {len(gap_polygons)} "
            "фрагментов негативного пространства"
        )

        skipped_small = 0
        skipped_large = 0
        skipped_external = 0

        for gap_geom in gap_polygons:
            if gap_geom is None or gap_geom.isEmpty():
                continue

            # Только полигоны
            if gap_geom.type() != Qgis.GeometryType.Polygon:
                continue

            area = gap_geom.area()

            # Отсечение шума float-арифметики
            if area < self.MIN_GAP_AREA:
                skipped_small += 1
                continue

            # Отсечение крупных намеренных пустот
            if area > self.max_gap_area:
                skipped_large += 1
                continue

            # Определение типа: internal или external
            # External = касается границы envelope (пространство за пределами объектов)
            is_external = gap_geom.intersects(envelope_boundary)

            if is_external:
                skipped_external += 1
                continue

            # Определение severity по площади
            severity = self._get_gap_severity(area)

            # Точка для визуализации - центроид зазора
            centroid = gap_geom.centroid()
            if centroid is None or centroid.isEmpty():
                centroid = gap_geom.pointOnSurface()

            error_geom = centroid if centroid and not centroid.isEmpty() else gap_geom

            errors.append({
                'type': 'gap',
                'geometry': error_geom,
                'feature_id': -1,  # Зазор не принадлежит конкретному объекту
                'description': (
                    f'Зазор покрытия: площадь {area:.4f} м2 '
                    f'(внутренний, {severity})'
                ),
                'area': round(area, 4),
                'gap_type': 'internal',
                'severity': severity
            })

        # Логирование статистики
        if skipped_small > 0:
            log_info(
                f"Fsm_0_4_14: Пропущено {skipped_small} "
                f"микро-зазоров (< {self.MIN_GAP_AREA} м2)"
            )
        if skipped_large > 0:
            log_info(
                f"Fsm_0_4_14: Пропущено {skipped_large} "
                f"крупных пустот (> {self.max_gap_area} м2)"
            )
        if skipped_external > 0:
            log_info(
                f"Fsm_0_4_14: Пропущено {skipped_external} "
                "внешних зазоров (за пределами покрытия)"
            )

        return errors

    @staticmethod
    def _get_gap_severity(area: float) -> str:
        """
        Определение серьезности зазора по площади.

        Args:
            area: Площадь зазора в м2

        Returns:
            Строка серьезности на русском языке
        """
        if area < 1.0:
            return 'критический'
        elif area < 10.0:
            return 'предупреждение'
        else:
            return 'информация'

    def _check_union_spikes(
        self, union_geom: QgsGeometry
    ) -> List[Dict[str, Any]]:
        """
        Анализ spike-углов на границе union (exterior + interior rings).

        Острые углы на union boundary указывают на зазоры/разрывы
        между объектами (линейные зазоры, не площадные).

        Args:
            union_geom: Объединенная геометрия слоя

        Returns:
            Список ошибок type='gap_spike'
        """
        errors: List[Dict[str, Any]] = []

        # Извлекаем полигоны из union (может быть MultiPolygon)
        if union_geom.isMultipart():
            polygons = union_geom.asMultiPolygon()
        else:
            polygons = [union_geom.asPolygon()]

        total_rings = 0
        total_vertices = 0

        for poly_idx, polygon in enumerate(polygons):
            if not polygon:
                continue

            for ring_idx, ring in enumerate(polygon):
                # Минимум 3 вершины + замыкающая = 4 точки
                if not ring or len(ring) < 4:
                    continue

                total_rings += 1
                ring_type = 'внешнее' if ring_idx == 0 else 'внутреннее'
                vertices = [QgsPointXY(pt) for pt in ring]
                n = len(vertices)
                total_vertices += n

                # Проверяем углы в кольце
                # Последняя точка = первая (замыкающая), пропускаем её
                for i in range(n - 1):
                    prev_idx = (i - 1) % (n - 1)
                    next_idx = (i + 1) % (n - 1)

                    p1 = vertices[prev_idx]
                    p2 = vertices[i]
                    p3 = vertices[next_idx]

                    # Пропускаем совпадающие точки
                    if p1 == p2 or p2 == p3 or p1 == p3:
                        continue

                    angle = self._calculate_angle(p1, p2, p3)

                    if angle <= self.spike_angle_threshold:
                        errors.append({
                            'type': 'gap_spike',
                            'geometry': QgsGeometry.fromPointXY(p2),
                            'feature_id': -1,
                            'description': (
                                f'Пиковый узел покрытия: '
                                f'угол {angle:.4f} град. '
                                f'({ring_type} кольцо, '
                                f'полигон {poly_idx})'
                            ),
                            'angle': round(angle, 4),
                            'ring_type': ring_type,
                            'polygon_index': poly_idx,
                            'vertex_index': i
                        })

        log_info(
            f"Fsm_0_4_14: Проверено {total_rings} колец, "
            f"{total_vertices} вершин на union boundary"
        )

        return errors

    @staticmethod
    def _calculate_angle(
        p1: QgsPointXY, p2: QgsPointXY, p3: QgsPointXY
    ) -> float:
        """
        Вычисление острого угла в вершине p2.

        Паттерн из Fsm_0_4_3_TopologyErrorsChecker._calculate_angle().

        Args:
            p1, p2, p3: Три последовательные точки контура

        Returns:
            Острый угол в градусах (минимальное расстояние до 0 или 360)
        """
        v1_x = p1.x() - p2.x()
        v1_y = p1.y() - p2.y()
        v2_x = p3.x() - p2.x()
        v2_y = p3.y() - p2.y()

        angle1 = math.atan2(v1_y, v1_x)
        angle2 = math.atan2(v2_y, v2_x)

        angle_diff = angle2 - angle1
        angle_deg = math.degrees(angle_diff)

        if angle_deg < 0:
            angle_deg += 360

        return min(angle_deg, 360.0 - angle_deg)

    def get_gap_count(self) -> int:
        """Возвращает количество найденных зазоров"""
        return self.gaps_found

    def get_spike_count(self) -> int:
        """Возвращает количество найденных spike-узлов"""
        return self.spikes_found
