# -*- coding: utf-8 -*-
"""
Fsm_2_1_7_NoChangeDetector - Детектор ЗУ без изменения геометрии

НАЗНАЧЕНИЕ:
    Автоматическое определение ЗУ, которые не требуют изменения геометрии
    при нарезке ЗПР. Классифицирует на Изменяемые и Без_Меж.

КРИТЕРИИ ЗУ БЕЗ ИЗМЕНЕНИЯ ГЕОМЕТРИИ:
    1. ЗУ полностью попадает в границы ОДНОЙ ЗПР
    2. ЗУ не пересекает другие ЗПР
    3. Все точки ЗУ на границе ЗПР совпадают с вершинами ЗПР
    4. Точки ЗУ внутри контура ЗПР игнорируются (общие границы смежных ЗУ)

КЛАССИФИКАЦИЯ (ТОЛЬКО ПО ВРИ):
    - Если ВРИ совпадает -> Без_Меж
    - Если ВРИ отличается -> Изменяемые
    - Если геометрия не полностью внутри ЗПР -> Раздел (нарезка)

    ВАЖНО: Категория (План_категория) НЕ сравнивается здесь!
    Она назначается позже через M_36 на основе пересечения с другими
    слоями (ООПТ, НП, Лесничество и т.д.)

ОСОБЕННОСТИ:
    - Геометрия сохраняется исходная (не нарезается)
    - Нет нумерации точек (геометрия не меняется)
    - Услов_КН = КН (сохраняется кадастровый номер)

ИСПОЛЬЗОВАНИЕ:
    Вызывается в Msm_26_4_CuttingEngine ПЕРЕД основной нарезкой.
"""

from typing import Dict, List, Tuple, Set, Optional, Any
from dataclasses import dataclass
from enum import Enum

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsSpatialIndex,
)

from Daman_QGIS.utils import log_info, log_warning, log_error, normalize_for_classification


class ZuClassification(Enum):
    """Классификация ЗУ по результату детекции"""
    RAZDEL = "razdel"           # Требует нарезки геометрии
    IZMENYAEMYE = "izmenyaemye"  # Без изменения геометрии, меняются атрибуты
    BEZ_MEZH = "bez_mezh"       # Без изменений вообще


@dataclass
class NoChangeDetectionResult:
    """Результат детекции для одного ЗУ"""
    zu_fid: int
    classification: ZuClassification
    reason: str
    zpr_fid: Optional[int] = None  # fid ЗПР в которую попадает ЗУ
    vri_matches: Optional[bool] = None  # Совпадает ли ВРИ
    category_matches: Optional[bool] = None  # Совпадает ли Категория


class Fsm_2_1_7_NoChangeDetector:
    """
    Детектор ЗУ без изменения геометрии

    Определяет ЗУ, которые полностью попадают в одну ЗПР
    и классифицирует их как Изменяемые или Без_Меж.
    """

    # Допуск для совпадения координат (кадастровая точность)
    TOLERANCE = 0.01  # м

    # Допуск для определения точки на границе
    BOUNDARY_TOLERANCE = 0.01  # м

    # Порог площади пересечения, ниже которого контакт считается касанием,
    # а не наложением: смежные ЗПР делят границу, и `intersects` на ней истинен
    AREA_TOLERANCE = 0.01  # кв. м

    def __init__(
        self,
        zpr_layer: QgsVectorLayer,
        zu_layer: QgsVectorLayer,
        vri_validator: Optional[Any] = None
    ):
        """
        Инициализация детектора

        Args:
            zpr_layer: Слой ЗПР
            zu_layer: Слой Выборка_ЗУ
            vri_validator: Опциональный валидатор ВРИ (Msm_21_1_ExistingVRIValidator)

        Raises:
            ValueError: CRS слоёв не совпадают — сравнение геометрий было бы
                        сравнением координат в разных системах
        """
        if zpr_layer.crs().authid() != zu_layer.crs().authid():
            raise ValueError(
                f"CRS слоёв не совпадают: ЗПР {zpr_layer.crs().authid()}, "
                f"Выборка_ЗУ {zu_layer.crs().authid()}. Детекция невозможна."
            )

        self.zpr_layer = zpr_layer
        self.zu_layer = zu_layer
        self.vri_validator = vri_validator

        # Пространственный индекс для быстрого поиска
        self._zpr_index: Optional[QgsSpatialIndex] = None
        self._zpr_features: Dict[int, QgsFeature] = {}

        # Кэш вершин ЗПР: пространственный индекс + координаты по id точки.
        # Индекс, а не множество округлённых координат: округление в бины даёт
        # разрыв на границе бина — две вершины в 0.2 мм друг от друга попадают
        # в разные бины и считаются несовпадающими
        self._zpr_vertex_index: Dict[int, QgsSpatialIndex] = {}
        self._zpr_vertex_points: Dict[int, Dict[int, QgsPointXY]] = {}
        self._zpr_boundary_cache: Dict[int, QgsGeometry] = {}

        self._build_spatial_index()

    def _build_spatial_index(self):
        """Построение пространственного индекса для слоя ЗПР"""
        self._zpr_index = QgsSpatialIndex()

        for feature in self.zpr_layer.getFeatures():
            geom = feature.geometry()
            if geom and not geom.isEmpty():
                self._zpr_index.addFeature(feature)
                self._zpr_features[feature.id()] = QgsFeature(feature)

                # Кэширование вершин в пространственный индекс
                index, points = self._build_vertex_index(geom)
                self._zpr_vertex_index[feature.id()] = index
                self._zpr_vertex_points[feature.id()] = points

                # Кэширование boundary
                boundary = geom.constGet().boundary()
                if boundary:
                    self._zpr_boundary_cache[feature.id()] = QgsGeometry(boundary.clone())

        log_info(f"Fsm_2_1_7: Индекс ЗПР построен ({len(self._zpr_features)} объектов)")

    def _build_vertex_index(
        self,
        geom: QgsGeometry
    ) -> Tuple[QgsSpatialIndex, Dict[int, QgsPointXY]]:
        """
        Построение пространственного индекса вершин геометрии

        Индекс вместо множества округлённых координат: округление в бины
        разрывает пару вершин, оказавшихся по разные стороны границы бина,
        даже если расстояние между ними доли миллиметра.

        Args:
            geom: Геометрия (полигон или мультиполигон)

        Returns:
            Tuple: индекс точек и словарь {id точки: координаты}
        """
        index = QgsSpatialIndex()
        points: Dict[int, QgsPointXY] = {}

        for idx, vertex in enumerate(geom.vertices()):
            point = QgsPointXY(vertex.x(), vertex.y())
            feature = QgsFeature(idx)
            feature.setGeometry(QgsGeometry.fromPointXY(point))
            index.addFeature(feature)
            points[idx] = point

        return index, points

    def _point_on_boundary(
        self,
        point: QgsPointXY,
        boundary_geom: QgsGeometry
    ) -> bool:
        """
        Проверка что точка находится на границе геометрии

        Args:
            point: Точка для проверки
            boundary_geom: Геометрия границы (линия)

        Returns:
            True если точка на границе (в пределах BOUNDARY_TOLERANCE)
        """
        point_geom = QgsGeometry.fromPointXY(point)
        distance = point_geom.distance(boundary_geom)
        return distance <= self.BOUNDARY_TOLERANCE

    def _vertex_matches_zpr(self, vertex: QgsPointXY, zpr_fid: int) -> bool:
        """
        Проверка совпадения вершины с вершинами ЗПР

        Критерий — истинное расстояние до ближайшей вершины ЗПР (как в
        `_point_on_boundary`), а не попадание в один бин округления.

        Args:
            vertex: Вершина для проверки
            zpr_fid: fid контура ЗПР, с вершинами которого сверяемся

        Returns:
            True если есть вершина ЗПР ближе TOLERANCE
        """
        index = self._zpr_vertex_index.get(zpr_fid)
        points = self._zpr_vertex_points.get(zpr_fid)
        if index is None or not points:
            return False

        nearest = index.nearestNeighbor(vertex, 1)
        if not nearest:
            return False

        candidate = points.get(nearest[0])
        if candidate is None:
            return False

        return vertex.distance(candidate) <= self.TOLERANCE

    def _get_zpr_vri(self, zpr_feature: QgsFeature) -> Optional[str]:
        """Получить ВРИ из ЗПР"""
        for field_name in ['ВРИ', 'VRI', 'vri']:
            if field_name in zpr_feature.fields().names():
                return zpr_feature[field_name]
        return None

    def _get_zu_vri(self, zu_feature: QgsFeature) -> Optional[str]:
        """Получить ВРИ из ЗУ"""
        for field_name in ['ВРИ', 'VRI', 'vri']:
            if field_name in zu_feature.fields().names():
                return zu_feature[field_name]
        return None

    def _compare_vri(self, zu_vri: Optional[str], zpr_vri: Optional[str]) -> bool:
        """
        Сравнение ВРИ с учётом различных форматов

        Args:
            zu_vri: ВРИ из ЗУ
            zpr_vri: ВРИ из ЗПР

        Returns:
            True если ВРИ эквивалентны
        """
        if not zu_vri or not zpr_vri:
            return False

        # Если есть валидатор - используем его
        if self.vri_validator:
            matches, _ = self.vri_validator.matches_zpr_vri(zu_vri, zpr_vri)
            return matches

        # Простое сравнение: обе стороны нормализуются, иначе невидимые символы
        # из внешних источников (nbsp, zero-width, тире) дают ложное «не равно»
        return (
            normalize_for_classification(str(zu_vri))
            == normalize_for_classification(str(zpr_vri))
        )

    def detect_single(self, zu_feature: QgsFeature) -> NoChangeDetectionResult:
        """
        Определить классификацию ЗУ

        Args:
            zu_feature: Feature земельного участка

        Returns:
            NoChangeDetectionResult с результатом детекции
        """
        zu_fid = zu_feature.id()
        zu_geom = zu_feature.geometry()

        if not zu_geom or zu_geom.isEmpty():
            return NoChangeDetectionResult(
                zu_fid=zu_fid,
                classification=ZuClassification.RAZDEL,
                reason="empty_geometry"
            )

        # 1. Найти все ЗПР, пересекающие ЗУ
        candidate_ids = self._zpr_index.intersects(zu_geom.boundingBox())
        intersecting_zprs = []

        for zpr_fid in candidate_ids:
            zpr_feature = self._zpr_features.get(zpr_fid)
            if zpr_feature:
                zpr_geom = zpr_feature.geometry()
                # Критерий — пересечение ПО ПЛОЩАДИ, а не касание: `intersects`
                # истинен и когда ЗУ лишь примыкает к соседней ЗПР по общей
                # границе, из-за чего ЗУ внутри одной зоны уходил в Раздел
                inter = zpr_geom.intersection(zu_geom)
                if not inter.isEmpty() and inter.area() > self.AREA_TOLERANCE:
                    intersecting_zprs.append(zpr_fid)

        # 2. Проверка: ЗУ должен пересекать ровно одну ЗПР
        if len(intersecting_zprs) == 0:
            return NoChangeDetectionResult(
                zu_fid=zu_fid,
                classification=ZuClassification.RAZDEL,
                reason="no_zpr_intersection"
            )

        if len(intersecting_zprs) > 1:
            return NoChangeDetectionResult(
                zu_fid=zu_fid,
                classification=ZuClassification.RAZDEL,
                reason=f"multiple_zpr_intersection:{len(intersecting_zprs)}"
            )

        zpr_fid = intersecting_zprs[0]
        zpr_feature = self._zpr_features[zpr_fid]
        zpr_geom = zpr_feature.geometry()

        # 3. Проверка: ЗУ должен полностью находиться внутри ЗПР
        if not zu_geom.within(zpr_geom):
            # Дополнительная проверка: может быть касание границ
            if not zpr_geom.contains(zu_geom):
                # Проверяем покрытие с допуском
                intersection = zu_geom.intersection(zpr_geom)
                if intersection.isEmpty():
                    return NoChangeDetectionResult(
                        zu_fid=zu_fid,
                        classification=ZuClassification.RAZDEL,
                        reason="not_within_zpr",
                        zpr_fid=zpr_fid
                    )

                # Площадь ЗУ, оставшаяся вне ЗПР. Порог абсолютный: относительная
                # доля масштабируется с площадью участка, и для ЗУ в 10 га допуск
                # 0.01% пропускал бы до 10 кв.м земли вне зоны размещения.
                outside_area = zu_geom.area() - intersection.area()
                if outside_area > self.AREA_TOLERANCE:
                    return NoChangeDetectionResult(
                        zu_fid=zu_fid,
                        classification=ZuClassification.RAZDEL,
                        reason=f"outside_zpr_area:{outside_area:.3f}",
                        zpr_fid=zpr_fid
                    )

        # 4. Проверка вершин ЗУ
        zpr_boundary = self._zpr_boundary_cache.get(zpr_fid)

        if not zpr_boundary:
            return NoChangeDetectionResult(
                zu_fid=zu_fid,
                classification=ZuClassification.RAZDEL,
                reason="no_zpr_boundary",
                zpr_fid=zpr_fid
            )

        # Проверяем каждую вершину ЗУ
        for vertex in zu_geom.vertices():
            point = QgsPointXY(vertex.x(), vertex.y())

            # Определяем тип точки
            on_boundary = self._point_on_boundary(point, zpr_boundary)

            if on_boundary:
                # Точка на границе ЗПР - должна совпадать с вершиной ЗПР
                if not self._vertex_matches_zpr(point, zpr_fid):
                    return NoChangeDetectionResult(
                        zu_fid=zu_fid,
                        classification=ZuClassification.RAZDEL,
                        reason=f"boundary_vertex_no_match:({point.x():.2f},{point.y():.2f})",
                        zpr_fid=zpr_fid
                    )
            # else: точка внутри ЗПР - игнорируем (общая граница смежных ЗУ)

        # 5. Геометрия подходит - теперь определяем Изм или Без_Меж
        # ВАЖНО: Классификация ТОЛЬКО по ВРИ!
        # Категория (План_категория) назначается позже через M_36 на основе
        # пересечения с другими слоями (ООПТ, НП, Лесничество и т.д.)
        zu_vri = self._get_zu_vri(zu_feature)
        zpr_vri = self._get_zpr_vri(zpr_feature)

        # Проверка на пустой ВРИ в ЗУ
        zu_vri_is_empty = not zu_vri or str(zu_vri).strip() in ('', '-', 'NULL', 'None')
        zpr_vri_is_empty = not zpr_vri or str(zpr_vri).strip() in ('', '-', 'NULL', 'None')

        if zu_vri_is_empty:
            if zpr_vri_is_empty:
                # Оба ВРИ пустые - нечего менять -> Без_Меж
                return NoChangeDetectionResult(
                    zu_fid=zu_fid,
                    classification=ZuClassification.BEZ_MEZH,
                    reason="zu_vri_empty_zpr_vri_empty",
                    zpr_fid=zpr_fid,
                    vri_matches=None,
                    category_matches=None
                )
            else:
                # ВРИ в ЗУ пустое, но ЗПР назначает ВРИ -> Изменяемые
                return NoChangeDetectionResult(
                    zu_fid=zu_fid,
                    classification=ZuClassification.IZMENYAEMYE,
                    reason=f"zu_vri_empty_zpr_has_vri({zpr_vri})",
                    zpr_fid=zpr_fid,
                    vri_matches=False,
                    category_matches=None
                )

        vri_matches = self._compare_vri(zu_vri, zpr_vri)

        if vri_matches:
            # ВРИ совпадает - Без_Меж
            return NoChangeDetectionResult(
                zu_fid=zu_fid,
                classification=ZuClassification.BEZ_MEZH,
                reason="vri_matches",
                zpr_fid=zpr_fid,
                vri_matches=True,
                category_matches=None  # Категория не сравнивается
            )
        else:
            # ВРИ отличается - Изменяемые
            return NoChangeDetectionResult(
                zu_fid=zu_fid,
                classification=ZuClassification.IZMENYAEMYE,
                reason=f"vri_differs({zu_vri}->{zpr_vri})",
                zpr_fid=zpr_fid,
                vri_matches=False,
                category_matches=None  # Категория не сравнивается
            )

    def detect_all(self) -> Tuple[List[NoChangeDetectionResult], Dict[str, int]]:
        """
        Определить классификацию для всех ЗУ

        Returns:
            Tuple[results, statistics]:
                - results: Список NoChangeDetectionResult для каждого ЗУ
                - statistics: Статистика детекции
        """
        results = []
        stats = {
            'total_zu': 0,
            'izmenyaemye': 0,
            'bez_mezh': 0,
            'razdel': 0,
            'reasons': {}
        }

        for zu_feature in self.zu_layer.getFeatures():
            stats['total_zu'] += 1

            result = self.detect_single(zu_feature)
            results.append(result)

            if result.classification == ZuClassification.IZMENYAEMYE:
                stats['izmenyaemye'] += 1
            elif result.classification == ZuClassification.BEZ_MEZH:
                stats['bez_mezh'] += 1
            else:
                stats['razdel'] += 1

            # Подсчёт причин
            reason_key = result.reason.split(':')[0].split(';')[0]  # Берём только тип причины
            stats['reasons'][reason_key] = stats['reasons'].get(reason_key, 0) + 1

        log_info(f"Fsm_2_1_7: Детекция завершена - "
                f"всего {stats['total_zu']}, "
                f"Изменяемые: {stats['izmenyaemye']}, "
                f"Без_Меж: {stats['bez_mezh']}, "
                f"Раздел: {stats['razdel']}")

        if stats['reasons']:
            reasons_str = ', '.join(f"{k}:{v}" for k, v in stats['reasons'].items())
            log_info(f"Fsm_2_1_7: Причины: {reasons_str}")

        return results, stats

    def get_izm_zu_with_zpr(self) -> List[Tuple[int, int]]:
        """
        Получить пары (zu_fid, zpr_fid) для Изменяемых

        Returns:
            Список кортежей (zu_fid, zpr_fid)
        """
        results, _ = self.detect_all()
        return [
            (r.zu_fid, r.zpr_fid)
            for r in results
            if r.classification == ZuClassification.IZMENYAEMYE and r.zpr_fid is not None
        ]

    def get_bez_mezh_zu_with_zpr(self) -> List[Tuple[int, int]]:
        """
        Получить пары (zu_fid, zpr_fid) для Без_Меж

        Returns:
            Список кортежей (zu_fid, zpr_fid)
        """
        results, _ = self.detect_all()
        return [
            (r.zu_fid, r.zpr_fid)
            for r in results
            if r.classification == ZuClassification.BEZ_MEZH and r.zpr_fid is not None
        ]

    def get_razdel_zu_ids(self) -> List[int]:
        """
        Получить список fid ЗУ для Раздела

        Returns:
            Список fid ЗУ которые требуют нарезку (Раздел)
        """
        results, _ = self.detect_all()
        return [r.zu_fid for r in results if r.classification == ZuClassification.RAZDEL]

    def get_no_change_zu_ids(self) -> List[int]:
        """
        Получить список fid ЗУ без изменения геометрии (Изм + Без_Меж)

        Returns:
            Список fid ЗУ
        """
        results, _ = self.detect_all()
        return [
            r.zu_fid for r in results
            if r.classification in (ZuClassification.IZMENYAEMYE, ZuClassification.BEZ_MEZH)
        ]
