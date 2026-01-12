# -*- coding: utf-8 -*-
"""
Модуль проверки дублей геометрий и вершин
Использует native:removeduplicatevertices и qgis:deleteduplicategeometries

ВАЖНО: При работе в background thread необходимо передавать QgsProcessingContext
созданный в main thread, так как processing.run() обращается к iface.mapCanvas()
"""

from typing import List, Dict, Any, Tuple, Optional
from qgis.core import (
    QgsVectorLayer, QgsGeometry, QgsProcessingContext, QgsProcessingFeedback
)
import processing
from Daman_QGIS.constants import COORDINATE_PRECISION
from Daman_QGIS.utils import log_info

class Fsm_0_4_2_DuplicatesChecker:
    """Проверка дублей геометрий и вершин"""

    # Допуск для дублей вершин (последовательных)
    # Используем половину COORDINATE_PRECISION (0.005м = 5мм) чтобы избежать
    # ложных срабатываний на границе из-за погрешности float.
    # Точки на расстоянии 1см друг от друга - это разные точки, не дубли.
    # Дубль - это когда точки практически совпадают (< 5мм).
    TOLERANCE = COORDINATE_PRECISION / 2  # 0.005м = 5мм

    # Допуск для близких точек (СТРОГИЙ режим)
    # Точки ближе 1 см (0.01м) считаются подозрительными - возможно несогласованные данные
    # Это НЕ дубли в классическом смысле, но могут указывать на проблемы в исходных данных
    CLOSE_POINTS_TOLERANCE = COORDINATE_PRECISION  # 0.01м = 1см

    def __init__(self, processing_context: Optional[QgsProcessingContext] = None):
        """
        Args:
            processing_context: QgsProcessingContext созданный в main thread
                               для thread-safe вызовов processing.run()
        """
        self.duplicate_geometries_found = 0
        self.duplicate_vertices_found = 0
        self.close_points_found = 0  # Близкие точки (< 1см)
        self.processing_context = processing_context
        self.feedback = QgsProcessingFeedback()

    def check(self, layer: QgsVectorLayer) -> Tuple[List[Dict], List[Dict], List[Dict]]:
        """
        Комплексная проверка дублей

        Returns:
            Tuple из (geometry_duplicates, vertex_duplicates, close_points)
        """
        geom_duplicates = self._check_duplicate_geometries(layer)
        vertex_duplicates = self._check_duplicate_vertices(layer)
        close_points = self._check_close_points(layer)

        return geom_duplicates, vertex_duplicates, close_points

    def _check_duplicate_geometries(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Проверка дублей полигонов через deleteduplicategeometries

        Returns:
            Список дублей геометрий
        """
        errors = []

        try:
            orig_count = layer.featureCount()

            # Используем context для thread-safe вызова
            result = processing.run(
                "qgis:deleteduplicategeometries",
                {'INPUT': layer, 'OUTPUT': 'memory:'},
                context=self.processing_context,
                feedback=self.feedback
            )

            unique_layer = result['OUTPUT']
            unique_count = unique_layer.featureCount()

            duplicates_count = orig_count - unique_count

            if duplicates_count > 0:
                log_info(f"Fsm_0_4_2: Найдено {duplicates_count} дублей геометрий")
                # Находим какие именно объекты дубли через подсчёт вхождений
                # ВАЖНО: используем WKB для точного сравнения геометрий
                geom_count = {}  # {wkb: [list of feature_ids]}

                for feature in layer.getFeatures():
                    geom = feature.geometry()
                    if geom:
                        wkb = geom.asWkb()
                        if wkb not in geom_count:
                            geom_count[wkb] = []
                        geom_count[wkb].append(feature.id())

                # Находим геометрии, которые встречаются больше 1 раза
                for wkb, fids in geom_count.items():
                    if len(fids) > 1:
                        # Помечаем ВСЕ копии как дубли (кроме первой для наглядности)
                        for fid in fids[1:]:  # Пропускаем первую копию
                            # Получаем геометрию из первой копии
                            first_feature = next(f for f in layer.getFeatures() if f.id() == fids[0])
                            geom = first_feature.geometry()

                            errors.append({
                                'type': 'duplicate_geometry',
                                'geometry': geom,
                                'feature_id': fid,
                                'feature_id2': fids[0],  # ID первой копии
                                'description': f'Полный дубль полигона (объекты {fid} и {fids[0]})',
                                'area': geom.area()
                            })

            self.duplicate_geometries_found = len(errors)
            return errors

        except Exception as e:
            # При ошибке (например, проблемы с полями) возвращаем пустой список
            log_info(f"Fsm_0_4_2: Проверка дублей геометрий пропущена: {str(e)}")
            self.duplicate_geometries_found = 0
            return []
    def _check_duplicate_vertices(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Проверка дублей вершин ВНУТРИ каждой геометрии отдельно.

        Дубль вершины = две последовательные вершины с одинаковыми координатами
        (в пределах TOLERANCE = 0.005м = 5мм).

        TOLERANCE уменьшен до 5мм чтобы избежать ложных срабатываний на границе
        из-за погрешности float. Точки на расстоянии 1см - разные точки.

        Returns:
            Список дублей вершин
        """
        errors = []

        try:
            from qgis.core import QgsWkbTypes, QgsPointXY

            for feature in layer.getFeatures():
                fid = feature.id()
                geom = feature.geometry()

                if not geom or geom.isEmpty():
                    continue

                # Получаем тип геометрии
                geom_type = geom.type()

                # Извлекаем вершины в зависимости от типа геометрии
                if geom_type == QgsWkbTypes.PolygonGeometry:
                    # Полигон: проверяем каждое кольцо
                    polygons = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]
                    for poly_idx, polygon in enumerate(polygons):
                        if not polygon:
                            continue
                        for ring_idx, ring in enumerate(polygon):
                            self._find_duplicate_vertices_in_ring(
                                ring, fid, poly_idx, ring_idx, errors
                            )

                elif geom_type == QgsWkbTypes.LineGeometry:
                    # Линия: проверяем каждую часть
                    lines = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
                    for line_idx, line in enumerate(lines):
                        if not line:
                            continue
                        self._find_duplicate_vertices_in_ring(
                            line, fid, line_idx, 0, errors
                        )

            self.duplicate_vertices_found = len(errors)

            if self.duplicate_vertices_found > 0:
                log_info(f"Fsm_0_4_2: Найдено {self.duplicate_vertices_found} дублей вершин")
            else:
                log_info(f"Fsm_0_4_2: Дубли вершин не обнаружены")

            return errors

        except Exception as e:
            log_info(f"Fsm_0_4_2: Проверка дублей вершин пропущена: {str(e)}")
            self.duplicate_vertices_found = 0
            return []

    def _find_duplicate_vertices_in_ring(
        self,
        vertices: list,
        feature_id: int,
        part_idx: int,
        ring_idx: int,
        errors: list
    ) -> None:
        """
        Поиск дублей вершин в одном кольце/линии.

        Дубль = две ПОСЛЕДОВАТЕЛЬНЫЕ вершины с расстоянием < TOLERANCE (5мм).

        Args:
            vertices: Список вершин (QgsPointXY)
            feature_id: ID объекта
            part_idx: Индекс части (для MultiPolygon/MultiLine)
            ring_idx: Индекс кольца (0=внешнее, 1+=дырки)
            errors: Список для добавления найденных ошибок
        """
        from qgis.core import QgsGeometry, QgsPointXY

        if len(vertices) < 2:
            return

        for i in range(len(vertices) - 1):
            p1 = vertices[i]
            p2 = vertices[i + 1]

            # Вычисляем расстояние между последовательными вершинами
            dx = p2.x() - p1.x()
            dy = p2.y() - p1.y()
            distance = (dx * dx + dy * dy) ** 0.5

            if distance < self.TOLERANCE:
                # Найден дубль
                errors.append({
                    'type': 'duplicate_vertex',
                    'geometry': QgsGeometry.fromPointXY(QgsPointXY(p2.x(), p2.y())),
                    'feature_id': feature_id,
                    'vertex_index': i + 1,
                    'description': f'Дубль вершины в объекте {feature_id} '
                                   f'(часть {part_idx}, кольцо {ring_idx}, индекс {i + 1})',
                    'coords': (p2.x(), p2.y()),
                    'distance': distance
                })

    def _check_close_points(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Проверка близких точек в контурах (СТРОГИЙ режим).

        Ищет пары точек которые находятся на расстоянии <= 1 см друг от друга,
        но НЕ являются последовательными вершинами (те уже проверены в _check_duplicate_vertices).

        Это выявляет проблемы несогласованных данных, когда точки из разных источников
        имеют микро-расхождения (например, 4927007.170 и 4927007.160).

        Returns:
            Список близких точек
        """
        errors = []

        try:
            from qgis.core import QgsWkbTypes, QgsPointXY, QgsGeometry

            for feature in layer.getFeatures():
                fid = feature.id()
                geom = feature.geometry()

                if not geom or geom.isEmpty():
                    continue

                geom_type = geom.type()

                if geom_type == QgsWkbTypes.PolygonGeometry:
                    polygons = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]
                    for poly_idx, polygon in enumerate(polygons):
                        if not polygon:
                            continue
                        for ring_idx, ring in enumerate(polygon):
                            self._find_close_points_in_ring(
                                ring, fid, poly_idx, ring_idx, errors
                            )

                elif geom_type == QgsWkbTypes.LineGeometry:
                    lines = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
                    for line_idx, line in enumerate(lines):
                        if not line:
                            continue
                        self._find_close_points_in_ring(
                            line, fid, line_idx, 0, errors
                        )

            self.close_points_found = len(errors)

            if self.close_points_found > 0:
                log_info(f"Fsm_0_4_2: Найдено {self.close_points_found} пар близких точек (< 1см)")

            return errors

        except Exception as e:
            log_info(f"Fsm_0_4_2: Проверка близких точек пропущена: {str(e)}")
            self.close_points_found = 0
            return []

    # Порог для переключения на R-Tree оптимизацию
    # При n < 100: O(n²) = 10000 операций - быстрее без индекса
    # При n >= 100: O(n²) = 10000+ операций - индекс окупается
    RTREE_THRESHOLD = 100

    def _find_close_points_in_ring(
        self,
        vertices: list,
        feature_id: int,
        part_idx: int,
        ring_idx: int,
        errors: list
    ) -> None:
        """
        Поиск близких (но не последовательных) точек в одном кольце/линии.

        Использует адаптивный алгоритм:
        - Для контуров < 100 вершин: O(n²) brute-force (быстрее без накладных расходов)
        - Для контуров >= 100 вершин: O(n log n) через QgsSpatialIndex

        Args:
            vertices: Список вершин (QgsPointXY)
            feature_id: ID объекта
            part_idx: Индекс части (для MultiPolygon/MultiLine)
            ring_idx: Индекс кольца (0=внешнее, 1+=дырки)
            errors: Список для добавления найденных ошибок
        """
        n = len(vertices)
        if n < 3:
            return

        # Адаптивный выбор алгоритма
        if n >= self.RTREE_THRESHOLD:
            self._find_close_points_rtree(
                vertices, feature_id, part_idx, ring_idx, errors
            )
        else:
            self._find_close_points_bruteforce(
                vertices, feature_id, part_idx, ring_idx, errors
            )

    def _find_close_points_bruteforce(
        self,
        vertices: list,
        feature_id: int,
        part_idx: int,
        ring_idx: int,
        errors: list
    ) -> None:
        """
        O(n²) brute-force поиск близких точек.
        Оптимален для небольших контуров (< 100 вершин).
        """
        from qgis.core import QgsGeometry, QgsPointXY

        n = len(vertices)

        # Проверяем все пары точек (i, j) где j > i + 1 (не последовательные)
        for i in range(n):
            for j in range(i + 2, n):
                # Для замкнутых колец: пропускаем пару (первая, последняя)
                if i == 0 and j == n - 1:
                    continue

                p1 = vertices[i]
                p2 = vertices[j]

                dx = abs(p2.x() - p1.x())
                dy = abs(p2.y() - p1.y())
                distance = (dx * dx + dy * dy) ** 0.5

                if distance <= self.CLOSE_POINTS_TOLERANCE:
                    errors.append({
                        'type': 'close_points',
                        'geometry': QgsGeometry.fromPointXY(QgsPointXY(p1.x(), p1.y())),
                        'feature_id': feature_id,
                        'vertex_index': i,
                        'vertex_index2': j,
                        'description': (
                            f'Близкие точки в объекте {feature_id}: '
                            f'вершины {i} и {j} на расстоянии {distance*100:.1f} мм '
                            f'(часть {part_idx}, кольцо {ring_idx})'
                        ),
                        'coords': (p1.x(), p1.y()),
                        'coords2': (p2.x(), p2.y()),
                        'distance': distance,
                        'dx': dx,
                        'dy': dy
                    })

    def _find_close_points_rtree(
        self,
        vertices: list,
        feature_id: int,
        part_idx: int,
        ring_idx: int,
        errors: list
    ) -> None:
        """
        O(n log n) поиск близких точек через QgsSpatialIndex.
        Оптимален для больших контуров (>= 100 вершин).
        """
        from qgis.core import QgsGeometry, QgsPointXY, QgsSpatialIndex, QgsFeature, QgsRectangle

        n = len(vertices)

        # Строим пространственный индекс
        spatial_index = QgsSpatialIndex()
        for i, point in enumerate(vertices):
            feat = QgsFeature(i)
            feat.setGeometry(QgsGeometry.fromPointXY(point))
            spatial_index.addFeature(feat)

        # Множество проверенных пар для дедупликации
        checked_pairs = set()

        # Для каждой вершины ищем соседей в bbox
        for i, p1 in enumerate(vertices):
            search_rect = QgsRectangle(
                p1.x() - self.CLOSE_POINTS_TOLERANCE,
                p1.y() - self.CLOSE_POINTS_TOLERANCE,
                p1.x() + self.CLOSE_POINTS_TOLERANCE,
                p1.y() + self.CLOSE_POINTS_TOLERANCE
            )

            candidate_ids = spatial_index.intersects(search_rect)

            for j in candidate_ids:
                # Пропускаем саму себя и последовательные вершины
                if j <= i + 1:
                    continue
                # Пропускаем пару (первая, последняя) для замкнутых колец
                if i == 0 and j == n - 1:
                    continue

                # Дедупликация
                pair_key = (min(i, j), max(i, j))
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)

                p2 = vertices[j]
                dx = abs(p2.x() - p1.x())
                dy = abs(p2.y() - p1.y())
                distance = (dx * dx + dy * dy) ** 0.5

                if distance <= self.CLOSE_POINTS_TOLERANCE:
                    errors.append({
                        'type': 'close_points',
                        'geometry': QgsGeometry.fromPointXY(QgsPointXY(p1.x(), p1.y())),
                        'feature_id': feature_id,
                        'vertex_index': i,
                        'vertex_index2': j,
                        'description': (
                            f'Близкие точки в объекте {feature_id}: '
                            f'вершины {i} и {j} на расстоянии {distance*100:.1f} мм '
                            f'(часть {part_idx}, кольцо {ring_idx})'
                        ),
                        'coords': (p1.x(), p1.y()),
                        'coords2': (p2.x(), p2.y()),
                        'distance': distance,
                        'dx': dx,
                        'dy': dy
                    })

    def get_errors_count(self) -> Tuple[int, int, int]:
        """Возвращает (geometry_duplicates, vertex_duplicates, close_points)"""
        return self.duplicate_geometries_found, self.duplicate_vertices_found, self.close_points_found
