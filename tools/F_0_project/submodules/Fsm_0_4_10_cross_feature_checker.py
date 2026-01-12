# -*- coding: utf-8 -*-
"""
Модуль проверки близких точек между разными объектами (cross-feature)

Проверяет вершины на общих границах между соседними полигонами/линиями.
Использует QgsSpatialIndex для оптимизации поиска соседей.

Типичная проблема: точки на общей границе имеют микро-расхождения
(например, 4927007.170 vs 4927007.160) из-за разных источников данных.
"""

from typing import List, Dict, Any, Tuple, Set, Optional
from qgis.core import (
    QgsVectorLayer, QgsGeometry, QgsPointXY, QgsProject,
    QgsSpatialIndex, QgsFeatureRequest, QgsWkbTypes, QgsRectangle
)
from Daman_QGIS.constants import COORDINATE_PRECISION
from Daman_QGIS.utils import log_info, log_warning


class Fsm_0_4_10_CrossFeatureChecker:
    """
    Проверка близких точек между разными объектами слоя.

    Находит пары вершин из разных features, которые находятся
    на расстоянии <= TOLERANCE друг от друга, но НЕ совпадают.

    ВАЖНО: Совпадающие точки (расстояние < COINCIDENT_TOLERANCE) -
    это общие вершины смежных полигонов, они НЕ являются ошибкой.
    """

    # Допуск для совпадающих точек (общие вершины смежных полигонов)
    # При точности проектирования 0.01м и округлённых координатах,
    # совпадающие точки имеют расстояние СТРОГО 0 (или ~1e-15 из-за float).
    # Используем 1e-9м как безопасный порог для float погрешности.
    COINCIDENT_TOLERANCE = 1e-9  # 1 нанометр - погрешность float

    # Допуск для поиска близких точек между объектами
    # При округлении до 0.01м, минимальное ненулевое расстояние = 0.01м.
    # Ищем точки которые отличаются на 1 шаг округления (0.01м),
    # но не на 2 шага (0.02м). Используем 1.5 * точность.
    SEARCH_TOLERANCE = COORDINATE_PRECISION * 1.5  # 0.015м = 15мм

    def __init__(self):
        """Инициализация checker'а"""
        self.cross_feature_close_points = 0
        self._point_layer: Optional[QgsVectorLayer] = None
        self._point_index: Optional[Dict[Tuple[float, float], int]] = None

    def check(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Проверка близких точек между разными объектами.

        Алгоритм:
        1. Извлекаем все вершины всех объектов с их feature_id
        2. Строим пространственный индекс по вершинам
        3. Для каждой вершины ищем соседей в пределах TOLERANCE
        4. Фильтруем пары из разных features

        Args:
            layer: Проверяемый слой

        Returns:
            Список ошибок cross_feature_close_points
        """
        errors = []

        try:
            geom_type = layer.geometryType()

            if geom_type not in (QgsWkbTypes.PolygonGeometry, QgsWkbTypes.LineGeometry):
                log_info("Fsm_0_4_10: Cross-feature проверка только для полигонов и линий")
                return []

            # Ищем точечный слой для получения ID точек
            self._point_layer = self._find_point_layer(layer.name())
            if self._point_layer:
                self._point_index = self._build_point_index(self._point_layer)
            else:
                self._point_index = None

            # Собираем все вершины с метаданными
            all_vertices = self._extract_all_vertices(layer)

            if not all_vertices:
                return []

            log_info(f"Fsm_0_4_10: Извлечено {len(all_vertices)} вершин для cross-feature проверки")

            # Строим пространственный индекс
            spatial_index, vertex_map = self._build_vertex_index(all_vertices)

            # Ищем близкие пары между разными объектами
            errors = self._find_cross_feature_close_points(
                all_vertices, spatial_index, vertex_map
            )

            self.cross_feature_close_points = len(errors)

            if self.cross_feature_close_points > 0:
                log_warning(
                    f"Fsm_0_4_10: Найдено {self.cross_feature_close_points} "
                    f"близких точек между объектами (расхождение {self.COINCIDENT_TOLERANCE*1000:.0f}-{self.SEARCH_TOLERANCE*1000:.0f} мм)"
                )
            else:
                log_info("Fsm_0_4_10: Близких точек между объектами не обнаружено")

            return errors

        except Exception as e:
            log_warning(f"Fsm_0_4_10: Ошибка cross-feature проверки: {str(e)}")
            return []

    def _extract_all_vertices(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Извлечение всех вершин из слоя с метаданными.

        Returns:
            Список словарей: [{
                'point': QgsPointXY,
                'feature_id': int,
                'vertex_index': int,
                'part_idx': int,
                'ring_idx': int
            }, ...]
        """
        vertices = []
        geom_type = layer.geometryType()

        for feature in layer.getFeatures():
            fid = feature.id()
            geom = feature.geometry()

            if not geom or geom.isEmpty():
                continue

            if geom_type == QgsWkbTypes.PolygonGeometry:
                polygons = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]
                for part_idx, polygon in enumerate(polygons):
                    if not polygon:
                        continue
                    for ring_idx, ring in enumerate(polygon):
                        for v_idx, point in enumerate(ring):
                            vertices.append({
                                'point': point,
                                'feature_id': fid,
                                'vertex_index': v_idx,
                                'part_idx': part_idx,
                                'ring_idx': ring_idx
                            })

            elif geom_type == QgsWkbTypes.LineGeometry:
                lines = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
                for part_idx, line in enumerate(lines):
                    if not line:
                        continue
                    for v_idx, point in enumerate(line):
                        vertices.append({
                            'point': point,
                            'feature_id': fid,
                            'vertex_index': v_idx,
                            'part_idx': part_idx,
                            'ring_idx': 0
                        })

        return vertices

    def _build_vertex_index(
        self,
        vertices: List[Dict[str, Any]]
    ) -> Tuple[QgsSpatialIndex, Dict[int, int]]:
        """
        Построение пространственного индекса по вершинам.

        Используем QgsSpatialIndex с точечными геометриями.
        Каждой вершине присваиваем уникальный ID для индекса.

        Returns:
            (QgsSpatialIndex, {index_id: vertex_list_index})
        """
        from qgis.core import QgsFeature

        spatial_index = QgsSpatialIndex()
        vertex_map = {}  # index_id -> index in vertices list

        for i, vertex_data in enumerate(vertices):
            point = vertex_data['point']

            # Создаём feature для индекса
            feat = QgsFeature(i)
            feat.setGeometry(QgsGeometry.fromPointXY(point))

            spatial_index.addFeature(feat)
            vertex_map[i] = i

        return spatial_index, vertex_map

    def _find_cross_feature_close_points(
        self,
        vertices: List[Dict[str, Any]],
        spatial_index: QgsSpatialIndex,
        vertex_map: Dict[int, int]
    ) -> List[Dict[str, Any]]:
        """
        Поиск близких точек между разными объектами.

        Для каждой вершины ищем соседей в пределах TOLERANCE,
        фильтруем те, что принадлежат другим features.

        ВАЖНО: Если точка A из объекта 1 близка к точке B из объекта 2,
        но точка B также существует в объекте 1 (общая вершина смежных полигонов),
        это НЕ является ошибкой - точки A и B обе принадлежат одному контуру.

        Returns:
            Список ошибок
        """
        errors = []
        checked_pairs: Set[Tuple[int, int, int, int]] = set()  # (fid1, v_idx1, fid2, v_idx2)
        coincident_count = 0  # Счётчик совпадающих точек (общие вершины)
        shared_vertex_skip_count = 0  # Счётчик пропущенных из-за общих вершин

        # Строим индекс координат -> set(feature_ids) для проверки общих вершин
        coord_to_features: Dict[Tuple[float, float], Set[int]] = {}
        for vertex_data in vertices:
            pt = vertex_data['point']
            key = (round(pt.x(), 6), round(pt.y(), 6))
            if key not in coord_to_features:
                coord_to_features[key] = set()
            coord_to_features[key].add(vertex_data['feature_id'])

        for i, vertex_data in enumerate(vertices):
            point = vertex_data['point']
            fid = vertex_data['feature_id']

            # Создаём bbox для поиска соседей
            search_rect = QgsRectangle(
                point.x() - self.SEARCH_TOLERANCE,
                point.y() - self.SEARCH_TOLERANCE,
                point.x() + self.SEARCH_TOLERANCE,
                point.y() + self.SEARCH_TOLERANCE
            )

            # Ищем кандидатов в индексе
            candidate_ids = spatial_index.intersects(search_rect)

            for cand_id in candidate_ids:
                if cand_id == i:
                    continue  # Пропускаем саму себя

                cand_idx = vertex_map[cand_id]
                cand_data = vertices[cand_idx]
                cand_fid = cand_data['feature_id']

                # Проверяем только пары из РАЗНЫХ features
                if cand_fid == fid:
                    continue

                cand_point = cand_data['point']

                # Точное вычисление расстояния
                dx = point.x() - cand_point.x()
                dy = point.y() - cand_point.y()
                distance = (dx * dx + dy * dy) ** 0.5

                if distance > self.SEARCH_TOLERANCE:
                    continue

                # ВАЖНО: Совпадающие точки (расстояние ~0 при округлённых координатах) -
                # это общие вершины смежных полигонов, они НЕ являются ошибкой топологии
                if distance < self.COINCIDENT_TOLERANCE:
                    coincident_count += 1
                    continue

                # Проверяем, является ли cand_point общей вершиной обоих объектов
                # Если да - значит point и cand_point обе принадлежат одному контуру (fid),
                # просто cand_point также используется соседним полигоном (cand_fid)
                cand_key = (round(cand_point.x(), 6), round(cand_point.y(), 6))
                cand_features = coord_to_features.get(cand_key, set())
                if fid in cand_features:
                    # cand_point существует и в объекте fid - это общая вершина,
                    # а point - соседняя вершина того же контура
                    shared_vertex_skip_count += 1
                    continue

                # Аналогично проверяем point - если она общая вершина
                point_key = (round(point.x(), 6), round(point.y(), 6))
                point_features = coord_to_features.get(point_key, set())
                if cand_fid in point_features:
                    # point существует и в объекте cand_fid - это общая вершина
                    shared_vertex_skip_count += 1
                    continue

                # Создаём нормализованный ключ пары для дедупликации
                v_idx1 = vertex_data['vertex_index']
                v_idx2 = cand_data['vertex_index']

                if fid < cand_fid:
                    pair_key = (fid, v_idx1, cand_fid, v_idx2)
                else:
                    pair_key = (cand_fid, v_idx2, fid, v_idx1)

                if pair_key in checked_pairs:
                    continue

                checked_pairs.add(pair_key)

                # Пытаемся получить ID точек из точечного слоя
                point_id1 = self._get_point_id(point.x(), point.y())
                point_id2 = self._get_point_id(cand_point.x(), cand_point.y())

                # Формируем описание с ID точек или номерами вершин
                if point_id1 is not None and point_id2 is not None:
                    vertex_desc = f'(ID точек: {point_id1} и {point_id2})'
                else:
                    vertex_desc = f'(вершины {v_idx1} и {v_idx2})'

                # Добавляем ошибку
                errors.append({
                    'type': 'cross_feature_close_points',
                    'geometry': QgsGeometry.fromPointXY(point),
                    'feature_id': fid,
                    'feature_id2': cand_fid,
                    'vertex_index': v_idx1,
                    'vertex_index2': v_idx2,
                    'point_id': point_id1,
                    'point_id2': point_id2,
                    'description': (
                        f'Близкие точки между объектами {fid} и {cand_fid}, '
                        f'расстояние {distance*1000:.1f} мм '
                        f'{vertex_desc}'
                    ),
                    'coords': (point.x(), point.y()),
                    'coords2': (cand_point.x(), cand_point.y()),
                    'distance': distance
                })

        # Логируем совпадающие точки (общие вершины - это норма)
        if coincident_count > 0:
            log_info(
                f"Fsm_0_4_10: Пропущено {coincident_count} совпадающих точек "
                f"(общие вершины смежных полигонов)"
            )

        # Логируем пропущенные из-за соседства с общими вершинами
        if shared_vertex_skip_count > 0:
            log_info(
                f"Fsm_0_4_10: Пропущено {shared_vertex_skip_count} пар точек "
                f"(соседние с общими вершинами смежных полигонов)"
            )

        return errors

    def get_errors_count(self) -> int:
        """Возвращает количество найденных cross-feature близких точек"""
        return self.cross_feature_close_points

    def _find_point_layer(self, polygon_layer_name: str) -> Optional[QgsVectorLayer]:
        """
        Поиск точечного слоя с префиксом "Т_" для полигонального слоя.

        Точечные слои имеют структуру:
        - Le_3_1_1_1_Раздел_ЗПР_ОКС -> Le_3_5_1_1_Т_Раздел_ЗПР_ОКС
        - Le_3_1_2_1_Раздел_ЗПР_ПО -> Le_3_5_2_1_Т_Раздел_ЗПР_ПО

        Args:
            polygon_layer_name: Имя полигонального слоя

        Returns:
            QgsVectorLayer или None если не найден
        """
        # Извлекаем суффикс (Раздел_ЗПР_ОКС, НГС_ЗПР_ПО и т.д.)
        # Пытаемся найти слой с "Т_" + суффикс
        parts = polygon_layer_name.split('_')
        if len(parts) < 5:
            return None

        # Ищем часть после "Le_3_1_X_Y_" -> берём всё после 5-го элемента
        suffix = '_'.join(parts[5:]) if len(parts) > 5 else ''
        if not suffix:
            return None

        # Ищем слой с "Т_" в имени и тем же суффиксом
        project = QgsProject.instance()
        for layer in project.mapLayers().values():
            layer_name = layer.name()
            if '_Т_' in layer_name and suffix in layer_name:
                if isinstance(layer, QgsVectorLayer) and layer.isValid():
                    log_info(f"Fsm_0_4_10: Найден точечный слой '{layer_name}' для '{polygon_layer_name}'")
                    return layer

        return None

    def _build_point_index(self, point_layer: QgsVectorLayer) -> Dict[Tuple[float, float], int]:
        """
        Построение индекса координат -> ID точки из точечного слоя.

        Args:
            point_layer: Точечный слой с полем ID

        Returns:
            Dict: {(x, y): point_id}
        """
        index = {}

        if not point_layer or not point_layer.isValid():
            return index

        # Проверяем наличие поля ID
        field_names = [f.name() for f in point_layer.fields()]
        if 'ID' not in field_names:
            log_warning("Fsm_0_4_10: Поле 'ID' не найдено в точечном слое")
            return index

        for feature in point_layer.getFeatures():
            geom = feature.geometry()
            if not geom or geom.isEmpty():
                continue

            point_id = feature['ID']
            if point_id is None:
                continue

            # Для MultiPoint берём первую точку
            if geom.isMultipart():
                points = geom.asMultiPoint()
                if points:
                    pt = points[0]
                    # Округляем координаты для индексации
                    key = (round(pt.x(), 6), round(pt.y(), 6))
                    index[key] = point_id
            else:
                pt = geom.asPoint()
                key = (round(pt.x(), 6), round(pt.y(), 6))
                index[key] = point_id

        log_info(f"Fsm_0_4_10: Построен индекс точек ({len(index)} записей)")
        return index

    def _get_point_id(self, x: float, y: float) -> Optional[int]:
        """
        Получить ID точки по координатам.

        Args:
            x: X координата
            y: Y координата

        Returns:
            ID точки или None
        """
        if not self._point_index:
            return None

        key = (round(x, 6), round(y, 6))
        return self._point_index.get(key)
