"""
Msm_41_6: BatchIsochroneTask - Фоновая задача для batch-построения изохрон.

Двухфазный pipeline:
  Phase 1 (background, execute()): Dijkstra + TIN для каждой точки
  Phase 2 (main thread, on_completed): GDAL contour + clip + сохранение

Thread safety:
  - Все данные копируются на главном потоке ДО запуска задачи
  - Memory layer создается в фоновом потоке из скопированных features
  - processing.run() НЕ вызывается в execute()

Родительский менеджер: M_41_IsochroneTransportManager
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from typing import Optional

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsRectangle,
    QgsVectorLayer,
)
from qgis.analysis import (
    QgsGraph,
    QgsGraphAnalyzer,
    QgsGraphBuilder,
    QgsInterpolator,
    QgsNetworkDistanceStrategy,
    QgsNetworkSpeedStrategy,
    QgsTinInterpolator,
    QgsGridFileWriter,
    QgsVectorLayerDirector,
)
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers.infrastructure.submodules.Msm_17_1_base_task import (
    BaseAsyncTask,
)

__all__ = ['Msm_41_6_BatchIsochroneTask']

# Фактор конвертации км/ч -> cost в секундах
_SPEED_FACTOR = 1000.0 / 3600.0


# ---------------------------------------------------------------------------
# Intermediate result (background -> main thread)
# ---------------------------------------------------------------------------

@dataclass
class _DijkstraTinResult:
    """Промежуточный результат фоновой фазы для одной точки."""
    center: QgsPointXY
    intervals: list[int]
    unit: str
    profile_name: str
    raster_path: Optional[str]    # temp .tif (None при ошибке)
    convex_hull: Optional[QgsGeometry]
    entry_cost: float
    point_count: int              # количество вершин в pointcloud
    error: Optional[str] = None   # сообщение об ошибке


@dataclass
class BatchDijkstraOutput:
    """Полный результат фоновой фазы (передается в on_completed)."""
    results: list[_DijkstraTinResult]
    crs_authid: str
    total_points: int
    successful: int


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------

class Msm_41_6_BatchIsochroneTask(BaseAsyncTask):
    """Фоновая задача: Dijkstra + TIN для нескольких центральных точек.

    Phase 1 (execute, background thread):
      - Создать memory layer из скопированных features
      - Построить граф (один раз)
      - Для каждой точки: Dijkstra -> pointcloud -> TIN raster
      - Вернуть BatchDijkstraOutput

    Phase 2 (on_completed callback, main thread):
      - Для каждого raster: gdal:contour_polygon -> clip -> IsochroneResult
      - Сохранить через Msm_41_5
    """

    def __init__(
        self,
        features: list[QgsFeature],
        fields: QgsFields,
        crs_authid: str,
        centers: list[QgsPointXY],
        intervals: list[int],
        unit: str,
        profile_name: str,
        default_speed: float,
        is_walk: bool,
        cost_strategy: str,
        cell_size: float = 15.0,
    ) -> None:
        """Инициализация (главный поток, все данные копируются).

        Args:
            features: Скопированные QgsFeature из подготовленного слоя
            fields: Схема полей подготовленного слоя
            crs_authid: CRS authid (строка, не QObject)
            centers: Центральные точки для изохрон
            intervals: Интервалы (секунды или метры)
            unit: 'time' или 'distance'
            profile_name: Имя профиля скоростей
            default_speed: Дефолтная скорость (км/ч)
            is_walk: True для пешеходного профиля (direction игнорируется)
            cost_strategy: 'speed' или 'distance'
            cell_size: Размер ячейки TIN растра (метры)
        """
        super().__init__(
            f"Batch изохроны: {len(centers)} точек",
            can_cancel=True,
        )

        # Все данные скопированы на главном потоке
        self._features = features
        self._fields = fields
        self._crs_authid = crs_authid
        self._centers = list(centers)
        self._intervals = sorted(intervals)
        self._unit = unit
        self._profile_name = profile_name
        self._default_speed = default_speed
        self._is_walk = is_walk
        self._cost_strategy = cost_strategy
        self._cell_size = cell_size

    def execute(self) -> BatchDijkstraOutput:
        """Фоновая фаза: граф + Dijkstra + TIN для всех точек."""
        total = len(self._centers)
        results: list[_DijkstraTinResult] = []
        successful = 0

        log_info(
            f"Msm_41_6: Начало batch обработки: {total} точек, "
            f"интервалы={self._intervals}, unit={self._unit}"
        )

        # 1. Создать memory layer из скопированных features
        crs = QgsCoordinateReferenceSystem(self._crs_authid)
        mem_layer = self._create_memory_layer(crs)

        if mem_layer.featureCount() == 0:
            log_error("Msm_41_6: Memory layer пуст после копирования features")
            return BatchDijkstraOutput(
                results=[], crs_authid=self._crs_authid,
                total_points=total, successful=0,
            )

        log_info(
            f"Msm_41_6: Memory layer создан: {mem_layer.featureCount()} features"
        )

        # 2. Построить граф (один раз для всех точек)
        graph, tied_points = self._build_graph(mem_layer, crs)

        if graph is None:
            log_error("Msm_41_6: Не удалось построить граф")
            return BatchDijkstraOutput(
                results=[], crs_authid=self._crs_authid,
                total_points=total, successful=0,
            )

        log_info(
            f"Msm_41_6: Граф построен: {graph.vertexCount()} вершин, "
            f"{graph.edgeCount()} ребер"
        )

        # 3. Для каждой точки: Dijkstra + TIN
        max_interval = self._intervals[-1]

        for idx, center in enumerate(self._centers):
            if self.is_cancelled():
                log_info("Msm_41_6: Задача отменена пользователем")
                break

            percent = int((idx / total) * 100)
            self.report_progress(
                percent,
                f"Точка {idx + 1}/{total}",
            )

            result = self._process_single_center(
                center=center,
                tied_point=tied_points[idx],
                graph=graph,
                max_interval=max_interval,
                crs=crs,
                idx=idx,
            )
            results.append(result)

            if result.error is None:
                successful += 1

        self.report_progress(100, f"Готово: {successful}/{total}")

        log_info(
            f"Msm_41_6: Фоновая фаза завершена: "
            f"{successful}/{total} успешных"
        )

        return BatchDijkstraOutput(
            results=results,
            crs_authid=self._crs_authid,
            total_points=total,
            successful=successful,
        )

    # ------------------------------------------------------------------
    # Internal: memory layer + graph
    # ------------------------------------------------------------------

    def _create_memory_layer(
        self,
        crs: QgsCoordinateReferenceSystem,
    ) -> QgsVectorLayer:
        """Создать memory layer из скопированных features."""
        uri = f"LineString?crs={crs.authid()}"
        layer = QgsVectorLayer(uri, "batch_network", "memory")
        provider = layer.dataProvider()

        provider.addAttributes(self._fields)
        layer.updateFields()
        provider.addFeatures(self._features)
        layer.updateExtents()

        return layer

    def _build_graph(
        self,
        layer: QgsVectorLayer,
        crs: QgsCoordinateReferenceSystem,
    ) -> tuple[Optional[QgsGraph], list[QgsPointXY]]:
        """Построить граф с привязкой всех центральных точек."""
        try:
            # Direction field
            if self._is_walk:
                direction_field_idx = -1
            else:
                direction_field_idx = layer.fields().indexOf('direction')

            # Director
            director = QgsVectorLayerDirector(
                layer,
                direction_field_idx,
                '1', '2', '0',
                QgsVectorLayerDirector.Direction.DirectionBoth,
            )

            # Strategy
            if self._cost_strategy == 'distance':
                strategy = QgsNetworkDistanceStrategy()
            else:
                speed_field_idx = layer.fields().indexOf('speed_kmh')
                strategy = QgsNetworkSpeedStrategy(
                    speed_field_idx,
                    self._default_speed,
                    _SPEED_FACTOR,
                )
            director.addStrategy(strategy)

            # Build
            builder = QgsGraphBuilder(crs, True, 0.0)
            tied_points = director.makeGraph(builder, self._centers)
            graph = builder.graph()

            return graph, tied_points

        except Exception as exc:
            log_error(f"Msm_41_6 (_build_graph): {exc}")
            return None, []

    # ------------------------------------------------------------------
    # Internal: single center processing
    # ------------------------------------------------------------------

    def _process_single_center(
        self,
        center: QgsPointXY,
        tied_point: QgsPointXY,
        graph: QgsGraph,
        max_interval: int,
        crs: QgsCoordinateReferenceSystem,
        idx: int,
    ) -> _DijkstraTinResult:
        """Dijkstra + TIN для одной точки."""
        try:
            # Entry cost
            entry_cost = self._compute_entry_cost(center, tied_point)

            effective_max = max_interval - entry_cost
            if effective_max <= 0:
                return _DijkstraTinResult(
                    center=center,
                    intervals=self._intervals,
                    unit=self._unit,
                    profile_name=self._profile_name,
                    raster_path=None,
                    convex_hull=None,
                    entry_cost=entry_cost,
                    point_count=0,
                    error=f"Entry cost ({entry_cost:.1f}) >= max_interval ({max_interval})",
                )

            # Dijkstra
            start_id = graph.findVertex(tied_point)
            (tree, costs) = QgsGraphAnalyzer.dijkstra(graph, start_id, 0)

            # Collect iso-points
            iso_points: list[tuple[QgsPointXY, float]] = []
            for i in range(graph.vertexCount()):
                cost = costs[i]
                if 0 <= cost <= effective_max:
                    vertex = graph.vertex(i)
                    iso_points.append((vertex.point(), cost))

            if len(iso_points) < 3:
                return _DijkstraTinResult(
                    center=center,
                    intervals=self._intervals,
                    unit=self._unit,
                    profile_name=self._profile_name,
                    raster_path=None,
                    convex_hull=None,
                    entry_cost=entry_cost,
                    point_count=len(iso_points),
                    error=f"Недостаточно точек для TIN ({len(iso_points)})",
                )

            # Add entry_cost
            if entry_cost > 0:
                iso_points = [
                    (pt, cost + entry_cost) for pt, cost in iso_points
                ]

            # Convex hull
            hull_points = [pt for pt, _ in iso_points]
            hull_geom = QgsGeometry.fromMultiPointXY(hull_points).convexHull()
            convex_hull = hull_geom if not hull_geom.isNull() else None

            # Pointcloud layer
            pointcloud = self._create_pointcloud_layer(iso_points, crs)

            # TIN interpolation -> raster
            extent = pointcloud.extent()
            extent.grow(self._cell_size * 2)

            raster_path = self._interpolate_to_raster(
                pointcloud, extent, self._cell_size, idx
            )

            return _DijkstraTinResult(
                center=center,
                intervals=self._intervals,
                unit=self._unit,
                profile_name=self._profile_name,
                raster_path=raster_path,
                convex_hull=convex_hull,
                entry_cost=entry_cost,
                point_count=len(iso_points),
            )

        except Exception as exc:
            log_error(f"Msm_41_6: Ошибка для точки {idx}: {exc}")
            return _DijkstraTinResult(
                center=center,
                intervals=self._intervals,
                unit=self._unit,
                profile_name=self._profile_name,
                raster_path=None,
                convex_hull=None,
                entry_cost=0.0,
                point_count=0,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Helpers (thread-safe, no processing.run)
    # ------------------------------------------------------------------

    def _compute_entry_cost(
        self,
        original: QgsPointXY,
        tied: QgsPointXY,
    ) -> float:
        """Entry cost в единицах unit."""
        dx = original.x() - tied.x()
        dy = original.y() - tied.y()
        distance_m = (dx * dx + dy * dy) ** 0.5

        if self._unit == 'distance':
            return distance_m

        speed_kmh = self._default_speed
        if speed_kmh <= 0:
            return 0.0
        speed_ms = speed_kmh * _SPEED_FACTOR
        return distance_m / speed_ms

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
        idx: int,
    ) -> Optional[str]:
        """TIN интерполяция -> cost raster (.tif)."""
        cost_field_idx = pointcloud_layer.fields().indexOf('cost')
        if cost_field_idx < 0:
            return None

        ncols = max(1, int(extent.width() / cell_size))
        nrows = max(1, int(extent.height() / cell_size))

        temp_dir = tempfile.gettempdir()
        raster_path = os.path.join(
            temp_dir, f"msm_41_6_batch_{idx}.tif"
        )

        try:
            layer_data = QgsInterpolator.LayerData()
            layer_data.source = pointcloud_layer
            layer_data.valueSource = QgsInterpolator.ValueSource.ValueAttribute
            layer_data.interpolationAttribute = cost_field_idx
            layer_data.sourceType = QgsInterpolator.SourceType.SourcePoints

            tin = QgsTinInterpolator(
                [layer_data],
                QgsTinInterpolator.TinInterpolation.Linear,
            )

            writer = QgsGridFileWriter(
                tin, raster_path, extent, ncols, nrows
            )

            rc = writer.writeFile()
            if rc != 0:
                log_error(f"Msm_41_6: QgsGridFileWriter вернул код {rc} для точки {idx}")
                return None

            if not os.path.exists(raster_path):
                return None

            return raster_path

        except Exception as exc:
            log_error(f"Msm_41_6 (_interpolate_to_raster): {exc}")
            return None
