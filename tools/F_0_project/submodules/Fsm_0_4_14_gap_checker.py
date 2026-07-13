# -*- coding: utf-8 -*-
"""
Fsm_0_4_14: Анализ покрытия — per-layer детектор проблем coverage

ДВА КОМПЛЕМЕНТАРНЫХ МЕТОДА (per-layer):

1. **GEOS CoverageValidator** (primary, GEOS >= 3.12)
   QgsGeometry.validateCoverage(gap_width) возвращает MULTILINESTRING invalid edges
   для каждого polygon где shared edges не совпадают (junction problems, sliver gaps).
   Индустриальный стандарт (PostGIS ST_CoverageInvalidEdges, ArcGIS "Must not have gaps").
   Тип ошибки: 'coverage_invalid_edge'

3. **Union spike-check** (для пиковых узлов)
   Острые углы на boundary union'а одного слоя. Spike-точки которые лежат на
   invalid edges из (1) — отфильтровываются (это та же junction problem).
   Тип ошибки: 'gap_spike'

ИСТОРИЯ (INV-1, план F_0_4 2026-06-16): метод 2 (envelope-difference, тип 'gap')
ВЫНЕСЕН из этого per-layer чекера в whole-project класс C (Fsm_0_4_16,
тип 'coverage_gap'). Причина: зазор покрытия — межслойный феномен (по сумме всех
образуемых нарезки внутри ЗПР), внутрислойный envelope-diff давал ложные
срабатывания. `_build_union_and_envelope` СОХРАНЁН — метод 3 (gap_spike) зависит
от того же union одного слоя (spike одного слоя != spike whole-project union).

ДЕДУПЛИКАЦИЯ:
Validator (1) — primary. Метод (3) фильтрует свои находки если они пространственно
совпадают с invalid edges из (1). Итог: 2 непересекающихся набора ошибок,
оператор видит каждую проблему ровно один раз.

Встроен в pipeline F_0_4 — выполняется всегда вместе с остальными checker'ами.
"""

import math
from typing import List, Dict, Any, Tuple, Optional

from qgis.core import (
    Qgis, QgsVectorLayer, QgsGeometry, QgsPointXY,
    QgsWkbTypes, QgsRectangle, QgsSpatialIndex, QgsFeature
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

    # Минимальная площадь зазора для отсечения шума float-арифметики (м²)
    # 0.0001 м² = 1 мм² — ловим даже micro-gaps в junction points (было 0.01 —
    # пропускало micro-gaps в junction). MAX_GAP_AREA-фильтр УДАЛЁН НАМЕРЕННО
    # (скрывал реальные крупные пустоты) — НЕ возвращать. gap-check встроен в
    # pipeline F_0_4 без checkbox (enable_gap_check удалён) — выполняется всегда.
    MIN_GAP_AREA = 0.0001

    # Буферный коэффициент для envelope (20% от максимального размера bbox)
    ENVELOPE_BUFFER_RATIO = 0.2

    # Порог spike-угла для границы union (градусы)
    # 1° соответствует Fsm_0_4_3 — не ловим легитимные треугольные участки
    DEFAULT_SPIKE_THRESHOLD = 1.0

    # Максимальная ширина зазора для GEOS CoverageValidator (м)
    # Зазоры шире этой ширины считаются "намеренными" (улицы, проезды) и игнорируются.
    # 1.0 м — типичный sliver-порог для кадастровых данных.
    DEFAULT_GAP_WIDTH = 1.0

    # Допуск пространственной близости для дедупликации (м)
    # gap polygon / spike point считаются "тем же местом" что invalid edge
    # если расстояние < этой величины
    DEDUP_TOLERANCE = COORDINATE_PRECISION  # 0.01 м

    def __init__(self,
                 gap_width: Optional[float] = None,
                 spike_angle_threshold: Optional[float] = None):
        """
        Инициализация checker'а

        Args:
            gap_width: Макс. ширина зазора для GEOS Validator (м). По умолчанию 1.0
            spike_angle_threshold: Порог spike-угла (градусы). По умолчанию 1.0
        """
        self.gap_width = gap_width if gap_width is not None else self.DEFAULT_GAP_WIDTH
        self.spike_angle_threshold = (
            spike_angle_threshold or self.DEFAULT_SPIKE_THRESHOLD
        )
        self.coverage_invalid_edges_found = 0
        self.spikes_found = 0

    def check(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Анализ покрытия слоя: invalid edges + spike-узлы на union boundary.

        Args:
            layer: Полигональный слой для проверки

        Returns:
            Список ошибок (type='coverage_invalid_edge' и type='gap_spike')
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
            f"Fsm_0_4_14: Параметры: gap_width={self.gap_width}м, "
            f"spike_threshold={self.spike_angle_threshold}°"
        )

        # Spatial index features для маппинга edges/gaps/spikes к feature_id.
        feature_index, feature_map = self._build_feature_index(layer)

        # МЕТОД 1 (PRIMARY): GEOS CoverageValidator
        # Находит junction problems и sliver gaps через invalid edges на границах.
        coverage_errors, invalid_edges_union = self._check_coverage_validator(
            layer, feature_map
        )
        errors.extend(coverage_errors)
        self.coverage_invalid_edges_found = len(coverage_errors)

        # 2. Построение union для МЕТОДА 3 (spike-анализ одного слоя).
        # envelope больше не используется для метода 2 (вынесен в класс C),
        # но _build_union_and_envelope СОХРАНЁН — union нужен для spike.
        union_geom, _envelope_geom = self._build_union_and_envelope(layer)
        if union_geom is None:
            self._log_summary()
            return errors

        if union_geom.type() != Qgis.GeometryType.Polygon:
            log_warning(
                f"Fsm_0_4_14: Union вернул не-полигональную геометрию "
                f"({union_geom.wkbType()}), spike-анализ невозможен"
            )
            self._log_summary()
            return errors

        # МЕТОД 3: spike-углы на union boundary
        # (дедуп: фильтруем точки лежащие на invalid edges)
        spike_errors = self._check_union_spikes(
            union_geom, feature_index, feature_map,
            invalid_edges_union=invalid_edges_union
        )
        errors.extend(spike_errors)
        self.spikes_found = len(spike_errors)

        self._log_summary()
        return errors

    def _log_summary(self) -> None:
        """Логирование итоговой статистики по 2 методам (per-layer)."""
        if self.coverage_invalid_edges_found > 0:
            log_warning(
                f"Fsm_0_4_14: Coverage invalid edges: "
                f"{self.coverage_invalid_edges_found}"
            )
        if self.spikes_found > 0:
            log_warning(
                f"Fsm_0_4_14: Spike-узлы (вне junction): {self.spikes_found}"
            )
        if (self.coverage_invalid_edges_found == 0 and
                self.spikes_found == 0):
            log_info("Fsm_0_4_14: Проблем покрытия не обнаружено")

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

    def _check_coverage_validator(
        self,
        layer: QgsVectorLayer,
        feature_map: Dict[int, QgsFeature]
    ) -> Tuple[List[Dict[str, Any]], Optional[QgsGeometry]]:
        """МЕТОД 1: GEOS CoverageValidator.

        Использует QgsGeometry.validateCoverage(gap_width) — индустриальный
        стандарт (GEOS >= 3.12, PostGIS ST_CoverageInvalidEdges, ArcGIS).

        Возвращает invalid edges per polygon — MULTILINESTRING на shared
        boundaries где edges не совпадают (junction problems, sliver gaps).

        ГОЧА (НЕ откатывать на processing-алгоритм): processing-wrapper
        `native:coveragevalidate` СЛОМАН в QGIS 3.40 LTR (verified MCP,
        май 2026) — IS_VALID работает, но output INVALID_EDGES всегда
        пустой (0 features) даже на synthetic-тесте с known-зазорами. Поэтому
        используется ПРЯМОЙ PyQGIS API `QgsGeometry.validateCoverage`, а не
        `processing.run('native:coveragevalidate')`. Не «оптимизировать»
        обратно на processing.

        Семантика gap_width = МАКСИМАЛЬНАЯ ширина детектируемого зазора:
        зазоры шире считаются «намеренными» (улицы/проезды) и игнорируются;
        кадастровый sliver-порог = 1.0 м (DEFAULT_GAP_WIDTH).

        graceful degradation: на GEOS 3.11 validateCoverage бросает
        QgsNotSupportedException → try/except ниже ловит, метод тихо
        отключается (методы 2/3 остаются). Метод доступен с QGIS 3.36.

        Задел: GEOS 3.14 (авг 2025) добавил GEOSCoverageClean (auto-snap
        малых зазоров + align shared edges) — в QGIS 3.40 ещё нет, ждать
        QGIS 3.46+/4.0 как Stage 2 fix для 'coverage_invalid_edge'. Соседние
        coverage-API: simplifyCoverageVW (Visvalingam-Whyatt с сохранением
        shared edges), unionCoverage (быстрее unaryUnion на valid coverage).

        Returns:
            (errors, invalid_edges_union):
                errors — список ошибок типа 'coverage_invalid_edge'
                invalid_edges_union — объединённая геометрия всех invalid edges
                                     для дедупликации в МЕТОДЕ 2 и 3 (или None)
        """
        errors: List[Dict[str, Any]] = []

        # Собираем features в нужном порядке для маппинга result[i] → fid
        fids_ordered: List[int] = []
        geometries: List[QgsGeometry] = []
        for feat in layer.getFeatures():
            geom = feat.geometry()
            if not geom or geom.isEmpty():
                continue
            if not geom.isGeosValid():
                geom = geom.makeValid()
                if geom.isEmpty():
                    continue
            fids_ordered.append(feat.id())
            geometries.append(geom)

        if len(geometries) < 2:
            return errors, None

        collection = QgsGeometry.collectGeometry(geometries)
        if collection.isEmpty():
            return errors, None

        try:
            result_enum, invalid_edges = collection.validateCoverage(self.gap_width)
        except Exception as e:
            log_warning(
                f"Fsm_0_4_14: CoverageValidator недоступен (нужен GEOS >= 3.12): {e}"
            )
            return errors, None

        if result_enum == Qgis.CoverageValidityResult.Valid:
            log_info("Fsm_0_4_14: CoverageValidator: покрытие валидно")
            return errors, None

        if invalid_edges is None or invalid_edges.isEmpty():
            log_info("Fsm_0_4_14: CoverageValidator: invalid но edges пусты")
            return errors, None

        # invalid_edges — GeometryCollection того же размера что input
        # Каждый элемент = MULTILINESTRING/LINESTRING (invalid edges feature[i]) или EMPTY
        edge_geoms: List[QgsGeometry] = []
        n_parts = invalid_edges.constGet().numGeometries()
        for i in range(n_parts):
            part = QgsGeometry(invalid_edges.constGet().geometryN(i).clone())
            if part.isEmpty() or i >= len(fids_ordered):
                continue
            fid = fids_ordered[i]
            edge_geoms.append(part)
            # Сырая линия invalid edges — координатор (Fsm_0_4_5:571)
            # централизует точку привязки через M_9 (midpoint линии).
            length = part.length()
            errors.append({
                'type': 'coverage_invalid_edge',
                'geometry': part,
                'edge_geometry': part,
                'feature_id': fid,
                'description': (
                    f'Несовпадение границ покрытия: объект {fid}, '
                    f'длина проблемных рёбер {length:.3f} м '
                    f'(gap_width={self.gap_width}м)'
                ),
                'length': round(length, 4),
            })

        # Объединяем все invalid edges для последующего дедупа в Методе 2/3
        invalid_edges_union: Optional[QgsGeometry] = None
        if edge_geoms:
            invalid_edges_union = QgsGeometry.unaryUnion(edge_geoms)

        if errors:
            log_info(
                f"Fsm_0_4_14: CoverageValidator нашёл {len(errors)} "
                f"полигонов с invalid edges"
            )

        return errors, invalid_edges_union

    @staticmethod
    def _build_feature_index(
        layer: QgsVectorLayer
    ) -> Tuple[QgsSpatialIndex, Dict[int, QgsFeature]]:
        """Spatial index features слоя для маппинга union→feature_id.

        Используется в _check_union_spikes чтобы привязать spike-ошибку к
        конкретному feature, а не оставлять feature_id=-1.
        """
        index = QgsSpatialIndex()
        feature_map: Dict[int, QgsFeature] = {}
        for feat in layer.getFeatures():
            if feat.hasGeometry() and not feat.geometry().isEmpty():
                index.addFeature(feat)
                feature_map[feat.id()] = feat
        return index, feature_map

    @staticmethod
    def _find_feature_at_point(
        point: QgsPointXY,
        index: QgsSpatialIndex,
        feature_map: Dict[int, QgsFeature],
        tolerance: float = COORDINATE_PRECISION
    ) -> int:
        """Найти fid feature к границе/нутру которого относится точка.

        Поиск через bbox tolerance + точное вычисление distance к геометрии.
        Возвращает -1 только если ни один feature не найден (теоретически
        не должно происходить для vertex'ов union'а).
        """
        search_rect = QgsRectangle(
            point.x() - tolerance, point.y() - tolerance,
            point.x() + tolerance, point.y() + tolerance
        )
        candidate_ids = index.intersects(search_rect)
        point_geom = QgsGeometry.fromPointXY(point)
        best_fid = -1
        best_distance = float('inf')
        for fid in candidate_ids:
            feat = feature_map.get(fid)
            if not feat:
                continue
            d = feat.geometry().distance(point_geom)
            if d < best_distance:
                best_distance = d
                best_fid = fid
        return best_fid if best_distance <= tolerance else -1

    def _check_union_spikes(
        self,
        union_geom: QgsGeometry,
        feature_index: QgsSpatialIndex,
        feature_map: Dict[int, QgsFeature],
        invalid_edges_union: Optional[QgsGeometry] = None
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
                        spike_point = QgsGeometry.fromPointXY(p2)

                        # ДЕДУП: если spike-точка лежит на invalid edge
                        # из CoverageValidator — пропускаем (та же junction problem)
                        if (invalid_edges_union is not None
                                and not invalid_edges_union.isEmpty()
                                and spike_point.distance(invalid_edges_union)
                                <= self.DEDUP_TOLERANCE):
                            continue

                        # Привязка к конкретному feature
                        spike_fid = self._find_feature_at_point(
                            p2, feature_index, feature_map
                        )
                        errors.append({
                            'type': 'gap_spike',
                            'geometry': spike_point,
                            'feature_id': spike_fid,
                            'description': (
                                f'Пиковый узел покрытия: '
                                f'угол {angle:.4f} град. '
                                f'(объект {spike_fid}, '
                                f'{ring_type} кольцо, '
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

    def get_coverage_invalid_edges_count(self) -> int:
        """Возвращает количество invalid edges из CoverageValidator"""
        return self.coverage_invalid_edges_found

    def get_spike_count(self) -> int:
        """Возвращает количество найденных spike-узлов (после дедупа)"""
        return self.spikes_found
