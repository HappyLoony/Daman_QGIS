"""
Msm_41_3: IsochroneBuilder - Генерация полигонов изохрон доступности.

Основной pipeline (Метод A):
  Dijkstra -> iso-pointcloud -> TIN interpolation -> GDAL contour -> polygons

Fallback pipeline (Метод B):
  native:servicearea -> buffer -> dissolve

Родительский менеджер: M_41_IsochroneTransportManager
"""

from __future__ import annotations

import os
import tempfile
from typing import Optional

import processing

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)
from qgis.analysis import (
    QgsGraph,
    QgsGraphAnalyzer,
    QgsInterpolator,
    QgsTinInterpolator,
    QgsGridFileWriter,
)
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.utils import log_info, log_warning, log_error

from .Msm_41_1_network_preparer import (
    GraphBuildResult,
    Msm_41_1_NetworkPreparer,
    _PreparedNetwork,
)
from .Msm_41_4_speed_profiles import IsochroneResult, SpeedProfile

__all__ = ['Msm_41_3_IsochroneBuilder']


class Msm_41_3_IsochroneBuilder:
    """Генерация полигонов изохрон доступности.

    Два метода:
    A) Dijkstra + TIN + GDAL contour (основной, качественные полигоны)
    B) native:servicearea + buffer + dissolve (fallback, грубые полигоны)
    """

    def __init__(self, network_preparer: Msm_41_1_NetworkPreparer) -> None:
        self._preparer = network_preparer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_isochrones(
        self,
        center: QgsPointXY,
        intervals: list[int],
        prepared: _PreparedNetwork,
        unit: str = 'time',
        cell_size: float = 15.0,
        method: str = 'auto',
    ) -> list[IsochroneResult]:
        """Построить изохроны доступности от точки.

        Args:
            center: Центральная точка (в CRS подготовленного слоя)
            intervals: Интервалы - секунды (unit='time') или метры (unit='distance')
            prepared: Подготовленная сеть из NetworkPreparer
            unit: 'time' или 'distance'
            cell_size: Размер ячейки растра TIN (метры, 10-25)
            method: 'auto', 'dijkstra_tin' (Метод A), 'servicearea_buffer' (Метод B)

        Returns:
            Список IsochroneResult (по одному на каждый interval)
        """
        if not intervals:
            return []

        intervals_sorted = sorted(intervals)
        max_interval = intervals_sorted[-1]

        log_info(
            f"Msm_41_3: Построение изохрон, центр=({center.x():.1f},{center.y():.1f}), "
            f"интервалы={intervals_sorted}, unit={unit}, method={method}"
        )

        # Выбор метода
        use_tin = method in ('auto', 'dijkstra_tin')

        if use_tin:
            try:
                return self._method_a_dijkstra_tin(
                    center=center,
                    intervals=intervals_sorted,
                    prepared=prepared,
                    unit=unit,
                    cell_size=cell_size,
                )
            except Exception as exc:
                if method == 'dijkstra_tin':
                    raise
                log_warning(
                    f"Msm_41_3: Метод A (Dijkstra+TIN) не удался: {exc}. "
                    f"Переключение на Метод B (servicearea+buffer)"
                )

        return self._method_b_servicearea_buffer(
            center=center,
            intervals=intervals_sorted,
            prepared=prepared,
            unit=unit,
        )

    # ------------------------------------------------------------------
    # Метод A: Dijkstra + TIN interpolation + GDAL contour
    # ------------------------------------------------------------------

    def _method_a_dijkstra_tin(
        self,
        center: QgsPointXY,
        intervals: list[int],
        prepared: _PreparedNetwork,
        unit: str,
        cell_size: float,
    ) -> list[IsochroneResult]:
        """Основной pipeline: Dijkstra -> pointcloud -> TIN -> contour."""
        max_interval = intervals[-1]
        cost_strategy = 'distance' if unit == 'distance' else 'speed'

        # 1. Построить граф с привязкой центральной точки
        graph_result = self._preparer.build_graph(
            prepared,
            additional_points=[center],
            cost_strategy=cost_strategy,
        )

        tied_center = graph_result.tied_points[0]
        start_id = graph_result.graph.findVertex(tied_center)

        # Entry cost (расстояние center -> ближайшая вершина)
        entry_cost = self._compute_entry_cost(
            center, tied_center, prepared.profile, unit
        )

        # Эффективный порог = max_interval - entry_cost
        effective_max = max_interval - entry_cost
        if effective_max <= 0:
            log_warning(
                f"Msm_41_3: Entry cost ({entry_cost:.1f}) >= max_interval ({max_interval}). "
                f"Точка слишком далеко от сети."
            )
            return [
                IsochroneResult(
                    geometry=QgsGeometry(),
                    interval=iv,
                    unit=unit,
                    area_sq_m=0.0,
                    profile=prepared.profile.name,
                    center=center,
                    entry_cost_s=entry_cost if unit == 'time' else 0.0,
                    method='dijkstra_tin',
                )
                for iv in intervals
            ]

        # 2. Dijkstra -> iso-pointcloud
        log_info("Msm_41_3: Шаг 1/4 - Dijkstra")
        (tree, costs) = QgsGraphAnalyzer.dijkstra(
            graph_result.graph, start_id, 0
        )

        iso_points = self._collect_iso_points(
            graph_result.graph, costs, effective_max
        )

        if len(iso_points) < 3:
            log_warning(
                f"Msm_41_3: Недостаточно точек для TIN ({len(iso_points)}). "
                f"Используется fallback."
            )
            return self._method_b_servicearea_buffer(
                center, intervals, prepared, unit
            )

        log_info(f"Msm_41_3: Собрано {len(iso_points)} вершин для pointcloud")

        # Добавить entry_cost к стоимости каждой точки
        if entry_cost > 0:
            iso_points = [
                (pt, cost + entry_cost) for pt, cost in iso_points
            ]

        # 3. Создать точечный слой
        log_info("Msm_41_3: Шаг 2/4 - TIN интерполяция")
        pointcloud_layer = self._create_pointcloud_layer(
            iso_points, prepared.crs
        )

        # 4. TIN interpolation -> cost raster
        extent = pointcloud_layer.extent()
        extent.grow(cell_size * 2)  # Расширить для краев

        raster_path = self._interpolate_to_raster(
            pointcloud_layer, extent, cell_size
        )

        if raster_path is None:
            log_warning("Msm_41_3: TIN интерполяция не удалась, fallback")
            return self._method_b_servicearea_buffer(
                center, intervals, prepared, unit
            )

        # 5. GDAL contour -> полигоны для каждого интервала
        log_info("Msm_41_3: Шаг 3/4 - GDAL contour")
        results: list[IsochroneResult] = []

        try:
            for interval in intervals:
                polygon = self._extract_contour_polygon(
                    raster_path, interval
                )

                # 6. Post-processing: clip по convex hull (TIN bug)
                if polygon and not polygon.isNull() and not polygon.isEmpty():
                    hull = self._compute_convex_hull(iso_points)
                    if hull and not hull.isNull():
                        polygon = polygon.intersection(hull)

                area = polygon.area() if polygon and not polygon.isEmpty() else 0.0

                results.append(IsochroneResult(
                    geometry=polygon if polygon else QgsGeometry(),
                    interval=interval,
                    unit=unit,
                    area_sq_m=area,
                    profile=prepared.profile.name,
                    center=center,
                    entry_cost_s=entry_cost if unit == 'time' else 0.0,
                    method='dijkstra_tin',
                ))
        finally:
            # Cleanup temp raster
            self._cleanup_temp_file(raster_path)

        log_info(
            f"Msm_41_3: Шаг 4/4 - Готово. "
            f"Построено {len(results)} изохрон"
        )
        return results

    # ------------------------------------------------------------------
    # Метод B: native:servicearea + buffer + dissolve (fallback)
    # ------------------------------------------------------------------

    def _method_b_servicearea_buffer(
        self,
        center: QgsPointXY,
        intervals: list[int],
        prepared: _PreparedNetwork,
        unit: str,
    ) -> list[IsochroneResult]:
        """Fallback pipeline: servicearea -> buffer -> dissolve."""
        log_info("Msm_41_3: Fallback - servicearea + buffer + dissolve")

        results: list[IsochroneResult] = []

        for interval in intervals:
            try:
                # Определить параметры
                if unit == 'distance':
                    strategy = 0  # shortest (по расстоянию)
                    travel_cost = float(interval)  # метры
                else:
                    strategy = 1  # fastest (по времени)
                    travel_cost = interval / 3600.0  # ЧАСЫ для processing.run

                # 1. Service area -> линии
                sa_result = processing.run("native:serviceareafrompoint", {
                    'INPUT': prepared.layer,
                    'STRATEGY': strategy,
                    'DIRECTION_FIELD': 'direction',
                    'VALUE_FORWARD': '1',
                    'VALUE_BACKWARD': '2',
                    'VALUE_BOTH': '0',
                    'DEFAULT_DIRECTION': 2,  # Both
                    'SPEED_FIELD': 'speed_kmh',
                    'DEFAULT_SPEED': prepared.profile.default_speed,
                    'START_POINT': f'{center.x()},{center.y()}',
                    'TRAVEL_COST': travel_cost,
                    'OUTPUT': 'memory:',
                })

                sa_layer: QgsVectorLayer = sa_result['OUTPUT']

                if sa_layer.featureCount() == 0:
                    results.append(IsochroneResult(
                        geometry=QgsGeometry(),
                        interval=interval,
                        unit=unit,
                        area_sq_m=0.0,
                        profile=prepared.profile.name,
                        center=center,
                        method='servicearea_buffer',
                    ))
                    continue

                # 2. Buffer (50м для грубого полигона)
                buffer_dist = 50.0
                buf_result = processing.run("native:buffer", {
                    'INPUT': sa_layer,
                    'DISTANCE': buffer_dist,
                    'SEGMENTS': 8,
                    'END_CAP_STYLE': 0,  # Round
                    'JOIN_STYLE': 0,     # Round
                    'DISSOLVE': True,
                    'OUTPUT': 'memory:',
                })

                buf_layer: QgsVectorLayer = buf_result['OUTPUT']

                # Собрать все полигоны в один
                combined = QgsGeometry()
                for feat in buf_layer.getFeatures():
                    geom = feat.geometry()
                    if not geom.isNull():
                        if combined.isNull() or combined.isEmpty():
                            combined = geom
                        else:
                            combined = combined.combine(geom)

                area = combined.area() if not combined.isEmpty() else 0.0

                results.append(IsochroneResult(
                    geometry=combined,
                    interval=interval,
                    unit=unit,
                    area_sq_m=area,
                    profile=prepared.profile.name,
                    center=center,
                    method='servicearea_buffer',
                ))

            except Exception as exc:
                log_error(
                    f"Msm_41_3 (fallback): Ошибка для interval={interval}: {exc}"
                )
                results.append(IsochroneResult(
                    geometry=QgsGeometry(),
                    interval=interval,
                    unit=unit,
                    area_sq_m=0.0,
                    profile=prepared.profile.name,
                    center=center,
                    method='servicearea_buffer',
                ))

        return results

    # ------------------------------------------------------------------
    # Pipeline helpers (Method A)
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_iso_points(
        graph: QgsGraph,
        costs: list[float],
        max_cost: float,
    ) -> list[tuple[QgsPointXY, float]]:
        """Собрать вершины графа с cost <= max_cost.

        Args:
            graph: QgsGraph
            costs: Результат Dijkstra (cost для каждой вершины)
            max_cost: Максимальная стоимость

        Returns:
            Список (point, cost) для достижимых вершин
        """
        points: list[tuple[QgsPointXY, float]] = []
        for i in range(graph.vertexCount()):
            cost = costs[i]
            if 0 <= cost <= max_cost:
                vertex = graph.vertex(i)
                points.append((vertex.point(), cost))
        return points

    @staticmethod
    def _create_pointcloud_layer(
        points_with_cost: list[tuple[QgsPointXY, float]],
        crs: QgsCoordinateReferenceSystem,
    ) -> QgsVectorLayer:
        """Создать memory point layer с полем cost."""
        uri = f"Point?crs={crs.authid()}"
        layer = QgsVectorLayer(uri, "iso_pointcloud", "memory")
        provider = layer.dataProvider()

        fields = QgsFields()
        fields.append(QgsField("cost", QMetaType.Type.Double))
        provider.addAttributes(fields)
        layer.updateFields()

        features: list[QgsFeature] = []
        for point, cost in points_with_cost:
            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(point))
            feat['cost'] = cost
            features.append(feat)

        provider.addFeatures(features)
        layer.updateExtents()

        return layer

    @staticmethod
    def _interpolate_to_raster(
        pointcloud_layer: QgsVectorLayer,
        extent: QgsRectangle,
        cell_size: float,
    ) -> Optional[str]:
        """TIN интерполяция pointcloud -> cost raster.

        Args:
            pointcloud_layer: Точечный слой с полем cost
            extent: Extent растра
            cell_size: Размер ячейки (метры)

        Returns:
            Путь к temp .tif файлу или None при ошибке
        """
        cost_field_idx = pointcloud_layer.fields().indexOf('cost')
        if cost_field_idx < 0:
            log_error("Msm_41_3: Поле 'cost' не найдено в pointcloud")
            return None

        # Параметры растра
        ncols = max(1, int((extent.width()) / cell_size))
        nrows = max(1, int((extent.height()) / cell_size))

        # Temp file
        temp_dir = tempfile.gettempdir()
        raster_path = os.path.join(temp_dir, "msm_41_3_cost_surface.tif")

        try:
            # QgsInterpolator.LayerData
            layer_data = QgsInterpolator.LayerData()
            layer_data.source = pointcloud_layer
            layer_data.valueSource = QgsInterpolator.ValueSource.ValueAttribute
            layer_data.interpolationAttribute = cost_field_idx
            layer_data.sourceType = QgsInterpolator.SourceType.SourcePoints

            # TIN interpolator
            tin = QgsTinInterpolator(
                [layer_data],
                QgsTinInterpolator.TinInterpolation.Linear,
            )

            # Grid writer
            writer = QgsGridFileWriter(
                tin, raster_path, extent, ncols, nrows
            )

            rc = writer.writeFile()
            if rc != 0:
                log_error(f"Msm_41_3: QgsGridFileWriter вернул код {rc}")
                return None

            if not os.path.exists(raster_path):
                log_error("Msm_41_3: Растр не создан")
                return None

            log_info(
                f"Msm_41_3: Cost raster создан: {ncols}x{nrows} ячеек, "
                f"cell_size={cell_size}м"
            )
            return raster_path

        except Exception as exc:
            log_error(f"Msm_41_3 (_interpolate_to_raster): {exc}")
            return None

    @staticmethod
    def _extract_contour_polygon(
        raster_path: str,
        max_value: float,
    ) -> Optional[QgsGeometry]:
        """Извлечь полигон для заданного порога из cost raster.

        Использует gdal:contour_polygon для создания контурных полигонов,
        затем выбирает полигоны с cost_max <= max_value.

        Args:
            raster_path: Путь к cost raster
            max_value: Максимальное значение cost (секунды или метры)

        Returns:
            QgsGeometry (Polygon/MultiPolygon) или None
        """
        try:
            # Используем interval = max_value чтобы получить контур на нужном уровне
            result = processing.run("gdal:contour_polygon", {
                'INPUT': raster_path,
                'BAND': 1,
                'INTERVAL': max_value,
                'CREATE_3D': False,
                'IGNORE_NODATA': True,
                'NODATA': None,
                'OFFSET': 0.0,
                'FIELD_NAME_MIN': 'cost_min',
                'FIELD_NAME_MAX': 'cost_max',
                'OUTPUT': 'memory:',
            })

            contour_layer: QgsVectorLayer = result['OUTPUT']

            if contour_layer.featureCount() == 0:
                return None

            # Собрать все полигоны с cost_min < max_value
            # (т.е. все зоны достижимые за данный интервал)
            combined = QgsGeometry()
            for feat in contour_layer.getFeatures():
                cost_min_val = feat['cost_min']
                if cost_min_val is not None and float(cost_min_val) < max_value:
                    geom = feat.geometry()
                    if not geom.isNull() and not geom.isEmpty():
                        if combined.isNull() or combined.isEmpty():
                            combined = geom
                        else:
                            combined = combined.combine(geom)

            return combined if not combined.isEmpty() else None

        except Exception as exc:
            log_error(f"Msm_41_3 (_extract_contour_polygon): {exc}")
            return None

    @staticmethod
    def _compute_convex_hull(
        iso_points: list[tuple[QgsPointXY, float]],
    ) -> Optional[QgsGeometry]:
        """Вычислить convex hull для iso-pointcloud.

        Используется для clip полигонов (TIN convex hull bug).
        """
        if len(iso_points) < 3:
            return None

        points = [pt for pt, _ in iso_points]
        multi = QgsGeometry.fromMultiPointXY(points)
        hull = multi.convexHull()
        return hull if not hull.isNull() else None

    @staticmethod
    def _compute_entry_cost(
        original: QgsPointXY,
        tied: QgsPointXY,
        profile: SpeedProfile,
        unit: str,
    ) -> float:
        """Вычислить entry cost (расстояние center -> ближайшая вершина).

        Returns:
            Cost в единицах unit (секунды для time, метры для distance)
        """
        dx = original.x() - tied.x()
        dy = original.y() - tied.y()
        distance_m = (dx * dx + dy * dy) ** 0.5

        if unit == 'distance':
            return distance_m

        # unit == 'time': конвертировать в секунды
        speed_kmh = profile.default_speed
        if speed_kmh <= 0:
            return 0.0
        speed_ms = speed_kmh * 1000.0 / 3600.0
        return distance_m / speed_ms

    @staticmethod
    def _cleanup_temp_file(path: str) -> None:
        """Удалить временный файл."""
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
