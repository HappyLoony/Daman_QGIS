# -*- coding: utf-8 -*-
"""
Модуль проверки топологии точечных объектов
Проверяет: дубликаты точек, близость точек (proximity)

Основан на алгоритмах из плагина KAT Overlap (GPLv3)
Адаптирован для Daman_QGIS
"""

from typing import List, Dict, Any, Tuple, Optional
from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
    QgsWkbTypes, QgsSpatialIndex, QgsRectangle
)
from Daman_QGIS.constants import COORDINATE_PRECISION
from Daman_QGIS.utils import log_info, log_warning


class Fsm_0_4_9_PointChecker:
    """
    Проверка топологии точечных объектов

    Типы проверок:
    - duplicate_point: точные дубликаты точек (расстояние = 0)
    - proximity: близкие точки (расстояние < порога)
    """

    # Порог расстояния для proximity check (метры)
    # По умолчанию 1 метр - точки ближе считаются потенциальными дублями
    DEFAULT_PROXIMITY_THRESHOLD = 1.0

    # Минимальное расстояние для регистрации proximity
    # (меньше этого - считается дубликатом, а не proximity)
    MIN_PROXIMITY_DISTANCE = COORDINATE_PRECISION  # 0.01 м

    def __init__(self, proximity_threshold: Optional[float] = None):
        """
        Args:
            proximity_threshold: Порог расстояния для proximity check (метры)
        """
        self.proximity_threshold = proximity_threshold or self.DEFAULT_PROXIMITY_THRESHOLD
        self.duplicates_found = 0
        self.proximity_issues_found = 0

    def set_proximity_threshold(self, threshold: float):
        """Установка порога расстояния для proximity check"""
        self.proximity_threshold = threshold

    def check(self, layer: QgsVectorLayer) -> Tuple[List[Dict], List[Dict]]:
        """
        Комплексная проверка точечного слоя

        Args:
            layer: Точечный слой для проверки

        Returns:
            Tuple из (duplicates, proximity_issues)
        """
        log_info(f"Fsm_0_4_9: Запуск проверки точечной топологии для слоя '{layer.name()}'")

        # Проверяем тип геометрии
        if layer.geometryType() != QgsWkbTypes.PointGeometry:
            log_warning(f"Fsm_0_4_9: Слой '{layer.name()}' не является точечным, проверка пропущена")
            return [], []

        # Фильтрация по topology_check выполняется в F_0_4._get_vector_layers()
        # Слои характерных точек (Le_*_Т_*) должны иметь topology_check=0 в Base_layers.json

        duplicates, proximity = self._check_proximity(layer)

        log_info(f"Fsm_0_4_9: Результаты - дубликатов: {len(duplicates)}, "
                 f"близких точек: {len(proximity)}")

        return duplicates, proximity

    def _check_proximity(self, layer: QgsVectorLayer) -> Tuple[List[Dict], List[Dict]]:
        """
        Проверка близости точек через spatial index

        Находит:
        - duplicates: точки на расстоянии < MIN_PROXIMITY_DISTANCE (практически совпадают)
        - proximity: точки на расстоянии MIN_PROXIMITY_DISTANCE <= d <= proximity_threshold

        Returns:
            Tuple из (duplicates, proximity_issues)
        """
        duplicates = []
        proximity_issues = []

        log_info(f"Fsm_0_4_9: Проверка близости точек (порог: {self.proximity_threshold} м)...")

        # Строим spatial index
        index = QgsSpatialIndex()
        features_dict = {}

        for feat in layer.getFeatures():
            if feat.hasGeometry() and not feat.geometry().isEmpty():
                index.addFeature(feat)
                features_dict[feat.id()] = feat

        # Проверяем каждую точку
        processed_pairs = set()

        for fid, feat_a in features_dict.items():
            geom_a = feat_a.geometry()

            # Получаем точку
            if geom_a.isMultipart():
                point_a = geom_a.asMultiPoint()[0] if geom_a.asMultiPoint() else None
            else:
                point_a = geom_a.asPoint()

            if not point_a:
                continue

            # Ищем в буфере вокруг точки
            search_rect = QgsRectangle(
                point_a.x() - self.proximity_threshold,
                point_a.y() - self.proximity_threshold,
                point_a.x() + self.proximity_threshold,
                point_a.y() + self.proximity_threshold
            )

            candidate_ids = index.intersects(search_rect)

            for cid in candidate_ids:
                if cid <= fid:
                    continue

                pair_key = tuple(sorted([fid, cid]))
                if pair_key in processed_pairs:
                    continue
                processed_pairs.add(pair_key)

                feat_b = features_dict.get(cid)
                if not feat_b:
                    continue

                geom_b = feat_b.geometry()

                # Получаем вторую точку
                if geom_b.isMultipart():
                    point_b = geom_b.asMultiPoint()[0] if geom_b.asMultiPoint() else None
                else:
                    point_b = geom_b.asPoint()

                if not point_b:
                    continue

                try:
                    # Вычисляем расстояние
                    distance = point_a.distance(point_b)

                    if distance < self.MIN_PROXIMITY_DISTANCE:
                        # Это дубликат (расстояние практически 0)
                        line_geom = QgsGeometry.fromPolylineXY([point_a, point_b])

                        duplicates.append({
                            'type': 'duplicate_point',
                            'geometry': QgsGeometry.fromPointXY(point_a),
                            'feature_id': fid,
                            'feature_id2': cid,
                            'description': f'Дубликат точки (объекты {fid} и {cid}), '
                                          f'расстояние {distance:.6f} м',
                            'distance': distance,
                            'coords_a': (point_a.x(), point_a.y()),
                            'coords_b': (point_b.x(), point_b.y())
                        })

                    elif distance <= self.proximity_threshold:
                        # Это proximity issue (близкие, но не дубликаты)
                        # Геометрия - линия между точками для визуализации
                        line_geom = QgsGeometry.fromPolylineXY([point_a, point_b])
                        midpoint = QgsPointXY(
                            (point_a.x() + point_b.x()) / 2,
                            (point_a.y() + point_b.y()) / 2
                        )

                        proximity_issues.append({
                            'type': 'point_proximity',
                            'geometry': QgsGeometry.fromPointXY(midpoint),
                            'feature_id': fid,
                            'feature_id2': cid,
                            'description': f'Близкие точки (объекты {fid} и {cid}), '
                                          f'расстояние {distance:.4f} м',
                            'distance': distance,
                            'coords_a': (point_a.x(), point_a.y()),
                            'coords_b': (point_b.x(), point_b.y())
                        })

                except Exception as e:
                    log_warning(f"Fsm_0_4_9: Ошибка расчета расстояния для {fid}/{cid}: {e}")
                    continue

        self.duplicates_found = len(duplicates)
        self.proximity_issues_found = len(proximity_issues)

        if duplicates:
            log_info(f"Fsm_0_4_9: Найдено {len(duplicates)} дубликатов точек")
        if proximity_issues:
            log_info(f"Fsm_0_4_9: Найдено {len(proximity_issues)} близких точек")

        return duplicates, proximity_issues

    def get_errors_count(self) -> Tuple[int, int]:
        """
        Возвращает количество найденных ошибок

        Returns:
            Tuple (duplicates, proximity_issues)
        """
        return self.duplicates_found, self.proximity_issues_found
