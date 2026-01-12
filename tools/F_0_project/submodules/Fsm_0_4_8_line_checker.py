# -*- coding: utf-8 -*-
"""
Модуль проверки топологии линейных объектов
Проверяет: самопересечения, наложения линий, висячие концы (dangles)

Основан на алгоритмах из плагина KAT Overlap (GPLv3)
Адаптирован для Daman_QGIS
"""

from typing import List, Dict, Any, Tuple, Optional
from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
    QgsWkbTypes, QgsSpatialIndex, QgsRectangle
)
from Daman_QGIS.utils import log_info, log_warning
from Daman_QGIS.managers.M_6_coordinate_precision import CoordinatePrecisionManager as CPM
from Daman_QGIS.constants import COORDINATE_PRECISION


class Fsm_0_4_8_LineChecker:
    """
    Проверка топологии линейных объектов

    Типы проверок:
    - self_intersection: линия пересекает саму себя
    - line_overlap: линии имеют общие сегменты
    - dangle: висячий конец линии (не подключен к другим линиям)
    """

    # Минимальная длина наложения для регистрации ошибки (метры)
    MIN_OVERLAP_LENGTH = COORDINATE_PRECISION  # 0.01 м

    # Точность округления координат для поиска dangles (знаки после запятой)
    DANGLE_PRECISION = 3

    def __init__(self):
        self.self_intersections_found = 0
        self.overlaps_found = 0
        self.dangles_found = 0

    def check(self, layer: QgsVectorLayer) -> Tuple[List[Dict], List[Dict], List[Dict]]:
        """
        Комплексная проверка линейного слоя

        Args:
            layer: Линейный слой для проверки

        Returns:
            Tuple из (self_intersections, overlaps, dangles)
        """
        log_info(f"Fsm_0_4_8: Запуск проверки линейной топологии для слоя '{layer.name()}'")

        # Проверяем тип геометрии
        if layer.geometryType() != QgsWkbTypes.LineGeometry:
            log_warning(f"Fsm_0_4_8: Слой '{layer.name()}' не является линейным, проверка пропущена")
            return [], [], []

        self_ints = self._check_self_intersections(layer)
        overlaps = self._check_overlaps(layer)
        dangles = self._check_dangles(layer)

        log_info(f"Fsm_0_4_8: Результаты - самопересечений: {len(self_ints)}, "
                 f"наложений: {len(overlaps)}, висячих концов: {len(dangles)}")

        return self_ints, overlaps, dangles

    def _check_self_intersections(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Проверка самопересечений линий через isSimple()

        Линия считается самопересекающейся если isSimple() возвращает False

        Returns:
            Список самопересечений
        """
        errors = []
        log_info(f"Fsm_0_4_8: Проверка самопересечений линий...")

        for feature in layer.getFeatures():
            geom = feature.geometry()
            if not geom or geom.isEmpty():
                continue

            try:
                # isSimple() возвращает False если линия пересекает саму себя
                if not geom.isSimple():
                    # Находим точки пересечения
                    intersection_points = []

                    # Извлекаем линии (UNIFIED PATTERN для Multi*)
                    lines = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]

                    for line in lines:
                        self._find_self_intersections(line, intersection_points)

                    # Создаем геометрию для отображения ошибки
                    if intersection_points:
                        error_geom = QgsGeometry.fromPointXY(intersection_points[0])
                    else:
                        # Fallback: центроид
                        error_geom = geom.centroid()
                        if not error_geom or error_geom.isEmpty():
                            bbox = geom.boundingBox()
                            error_geom = QgsGeometry.fromPointXY(bbox.center())

                    errors.append({
                        'type': 'line_self_intersection',
                        'geometry': error_geom,
                        'feature_id': feature.id(),
                        'description': f'Самопересечение линии (объект {feature.id()}, '
                                      f'{len(intersection_points)} точек пересечения)',
                        'intersection_count': len(intersection_points)
                    })

            except Exception as e:
                log_warning(f"Fsm_0_4_8: Ошибка проверки самопересечения для {feature.id()}: {e}")
                continue

        self.self_intersections_found = len(errors)

        if errors:
            log_info(f"Fsm_0_4_8: Найдено {len(errors)} самопересекающихся линий")

        return errors

    def _find_self_intersections(self, line: List, intersections: List):
        """
        Поиск точек самопересечения в линии

        Args:
            line: Список точек линии
            intersections: Список для добавления найденных пересечений
        """
        if len(line) < 4:
            return

        # Проверяем каждую пару несмежных сегментов
        for i in range(len(line) - 1):
            for j in range(i + 2, len(line) - 1):
                # Пропускаем смежные сегменты
                if j == i + 1:
                    continue

                p1, p2 = line[i], line[i + 1]
                p3, p4 = line[j], line[j + 1]

                intersection = self._segment_intersection(p1, p2, p3, p4)
                if intersection:
                    intersections.append(intersection)

    def _segment_intersection(self, p1, p2, p3, p4) -> Optional[QgsPointXY]:
        """
        Поиск точки пересечения двух отрезков

        Returns:
            QgsPointXY если отрезки пересекаются, None иначе
        """
        x1, y1 = p1.x(), p1.y()
        x2, y2 = p2.x(), p2.y()
        x3, y3 = p3.x(), p3.y()
        x4, y4 = p4.x(), p4.y()

        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) < 1e-10:
            return None  # Параллельные отрезки

        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom

        # Проверяем что пересечение внутри обоих отрезков (0 < t < 1 и 0 < u < 1)
        if 0 < t < 1 and 0 < u < 1:
            ix = x1 + t * (x2 - x1)
            iy = y1 + t * (y2 - y1)
            return QgsPointXY(ix, iy)

        return None

    def _check_overlaps(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Проверка наложений линий (общие сегменты)

        Использует spatial index и overlaps() для OGC-совместимости

        Returns:
            Список наложений
        """
        errors = []
        log_info(f"Fsm_0_4_8: Проверка наложений линий...")

        # Строим spatial index
        index = QgsSpatialIndex()
        features_dict = {}

        for feat in layer.getFeatures():
            if feat.hasGeometry() and not feat.geometry().isEmpty():
                index.addFeature(feat)
                features_dict[feat.id()] = feat

        # Проверяем пары
        processed_pairs = set()

        for fid, feat_a in features_dict.items():
            geom_a = feat_a.geometry()
            bbox = geom_a.boundingBox()

            candidate_ids = index.intersects(bbox)

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

                try:
                    # overlaps() - OGC метод для определения наложения
                    if geom_a.overlaps(geom_b):
                        intersection = geom_a.intersection(geom_b)

                        if intersection and not intersection.isEmpty():
                            # Проверяем что пересечение линейное (не точечное)
                            if intersection.type() != QgsWkbTypes.LineGeometry:
                                continue

                            length = intersection.length()
                            if length < self.MIN_OVERLAP_LENGTH:
                                continue

                            # Геометрия для отображения - центроид пересечения
                            error_geom = intersection.centroid()
                            if not error_geom or error_geom.isEmpty():
                                error_geom = intersection

                            errors.append({
                                'type': 'line_overlap',
                                'geometry': error_geom,
                                'feature_id': fid,
                                'feature_id2': cid,
                                'description': f'Наложение линий (объекты {fid} и {cid}), длина {length:.4f} м',
                                'overlap_length': length
                            })

                except Exception as e:
                    log_warning(f"Fsm_0_4_8: Ошибка проверки наложения для {fid}/{cid}: {e}")
                    continue

        self.overlaps_found = len(errors)

        if errors:
            log_info(f"Fsm_0_4_8: Найдено {len(errors)} наложений линий")

        return errors

    def _check_dangles(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Проверка висячих концов (dangles)

        Dangle - это конец линии, который не соединен с другими линиями.
        Для сетей (дороги, трубопроводы) это часто ошибка.

        Returns:
            Список висячих концов
        """
        errors = []
        log_info(f"Fsm_0_4_8: Проверка висячих концов линий...")

        # Собираем все endpoints
        # endpoints = {(x, y): [(feat_id, 'start'/'end', point), ...]}
        endpoints = {}

        for feat in layer.getFeatures():
            geom = feat.geometry()
            if not geom or geom.isEmpty():
                continue

            try:
                # UNIFIED PATTERN для Multi*
                lines = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]

                for line in lines:
                    if line:
                        self._add_endpoints(endpoints, feat.id(), line)

            except Exception as e:
                log_warning(f"Fsm_0_4_8: Ошибка извлечения endpoints для {feat.id()}: {e}")
                continue

        # Находим dangles (endpoints с только одним подключением)
        # Используем set для избежания дубликатов по (feat_id, pos)
        reported_dangles = set()

        for coord, connections in endpoints.items():
            if len(connections) == 1:
                feat_id, pos, point = connections[0]

                # Избегаем дубликатов по (feat_id, endpoint_type)
                dangle_key = (feat_id, pos)
                if dangle_key in reported_dangles:
                    continue
                reported_dangles.add(dangle_key)

                point_geom = QgsGeometry.fromPointXY(point)

                pos_ru = 'начало' if pos == 'start' else 'конец'
                errors.append({
                    'type': 'dangle',
                    'geometry': point_geom,
                    'feature_id': feat_id,
                    'description': f'Висячий конец линии (объект {feat_id}, {pos_ru})',
                    'endpoint_type': pos,
                    'coords': (point.x(), point.y())
                })

        self.dangles_found = len(errors)

        if errors:
            log_info(f"Fsm_0_4_8: Найдено {len(errors)} висячих концов")

        return errors

    def _add_endpoints(self, endpoints: Dict, feat_id: int, line: List):
        """
        Добавление endpoints линии в словарь

        Args:
            endpoints: Словарь endpoints
            feat_id: ID объекта
            line: Список точек линии
        """
        if not line:
            return

        # Округляем координаты для корректного сравнения
        # Используем CPM с DANGLE_PRECISION (3 знака = 1мм) для более точной группировки endpoints
        start = CPM.round_coordinates(line[0].x(), line[0].y(), self.DANGLE_PRECISION)
        end = CPM.round_coordinates(line[-1].x(), line[-1].y(), self.DANGLE_PRECISION)

        # Добавляем начальную точку
        if start not in endpoints:
            endpoints[start] = []
        endpoints[start].append((feat_id, 'start', QgsPointXY(line[0])))

        # Добавляем конечную точку
        if end not in endpoints:
            endpoints[end] = []
        endpoints[end].append((feat_id, 'end', QgsPointXY(line[-1])))

    def get_errors_count(self) -> Tuple[int, int, int]:
        """
        Возвращает количество найденных ошибок

        Returns:
            Tuple (self_intersections, overlaps, dangles)
        """
        return self.self_intersections_found, self.overlaps_found, self.dangles_found
