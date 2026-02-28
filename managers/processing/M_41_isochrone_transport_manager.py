"""
M_41: IsochroneTransportManager - Универсальный менеджер транспортной
и пешей доступности.

Три основных функции:
1. shortest_route()      - кратчайший маршрут A -> B
2. isochrone()           - зона доступности от точки (Этап 2)
3. batch_isochrones()    - зоны доступности от множества точек (Этап 4)

Субмодули:
- Msm_41_1_NetworkPreparer  - подготовка сети (speed, direction, CRS)
- Msm_41_2_RouteSolver      - кратчайшие маршруты (single + batch)
- Msm_41_3_IsochroneBuilder - изохроны (Dijkstra+TIN / servicearea fallback)
- Msm_41_4_SpeedProfiles    - профили скоростей + пресеты
- Msm_41_5_ResultLayerWriter - экспорт в GPKG / memory layers + стили

Домен: processing (аналитические вычисления над данными)
"""

from __future__ import annotations

import os
from typing import Callable, Optional

import processing

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QObject, pyqtSignal

from Daman_QGIS.constants import LAYER_OSM_ROADS_LINE
from Daman_QGIS.utils import log_info, log_warning, log_error, log_success

from .submodules.Msm_41_1_network_preparer import (
    GraphBuildResult,
    Msm_41_1_NetworkPreparer,
    _PreparedNetwork,
)
from .submodules.Msm_41_2_route_solver import Msm_41_2_RouteSolver
from .submodules.Msm_41_3_isochrone_builder import Msm_41_3_IsochroneBuilder
from .submodules.Msm_41_4_speed_profiles import (
    BUILTIN_PROFILES,
    REGULATORY_PRESETS,
    IsochroneResult,
    Msm_41_4_SpeedProfiles,
    RouteResult,
    SpeedProfile,
)
from .submodules.Msm_41_5_result_layer_writer import Msm_41_5_ResultLayerWriter
from .submodules.Msm_41_6_batch_isochrone_task import (
    BatchDijkstraOutput,
    Msm_41_6_BatchIsochroneTask,
    _DijkstraTinResult,
)

__all__ = ['IsochroneTransportManager']


class IsochroneTransportManager(QObject):
    """M_41: Универсальный менеджер транспортной и пешей доступности.

    Facade, делегирующий работу субмодулям Msm_41_1..5.
    Все публичные методы валидируют входные данные.
    """

    # --- Сигналы ---
    route_calculated = pyqtSignal(object)       # RouteResult
    isochrone_generated = pyqtSignal(object)     # IsochroneResult
    batch_completed = pyqtSignal(object)         # QgsVectorLayer (результат batch)
    progress_updated = pyqtSignal(int, int)      # current, total

    def __init__(self, iface=None) -> None:
        super().__init__()
        self._iface = iface

        # Субмодули
        self._profiles = Msm_41_4_SpeedProfiles()
        self._preparer = Msm_41_1_NetworkPreparer()
        self._route_solver = Msm_41_2_RouteSolver(self._preparer)
        self._isochrone_builder = Msm_41_3_IsochroneBuilder(self._preparer)
        self._result_writer = Msm_41_5_ResultLayerWriter()

        # Текущее состояние
        self._last_prepared: Optional[_PreparedNetwork] = None
        self._last_graph: Optional[GraphBuildResult] = None

        log_info("M_41: IsochroneTransportManager инициализирован")

    # ==================================================================
    # Маршруты
    # ==================================================================

    def shortest_route(
        self,
        origin: QgsPointXY,
        destination: QgsPointXY,
        profile: str = 'drive',
        road_layer: Optional[QgsVectorLayer] = None,
    ) -> RouteResult:
        """Кратчайший маршрут между двумя точками.

        Args:
            origin: Начальная точка
            destination: Конечная точка
            profile: 'walk', 'drive', 'fire_truck' или custom
            road_layer: Слой дорог (None = Le_1_4_1_1_OSM_АД_line)

        Returns:
            RouteResult с геометрией, расстоянием, временем
        """
        log_info(f"M_41: shortest_route, профиль='{profile}'")

        # Валидация
        layer = self._resolve_road_layer(road_layer)
        self._validate_road_layer(layer)
        self._validate_point_in_extent(origin, layer)
        self._validate_point_in_extent(destination, layer)
        speed_profile = self._profiles.get_profile(profile)

        # Подготовка сети
        project_crs = self._get_project_crs()
        prepared = self._preparer.prepare_network(
            road_layer=layer,
            profile=speed_profile,
            project_crs=project_crs,
        )

        # Трансформация точек в CRS сети (если нужно)
        origin_t = self._transform_point(origin, layer.crs(), prepared.crs)
        dest_t = self._transform_point(destination, layer.crs(), prepared.crs)

        # Вычисление маршрута
        result = self._route_solver.single_route(origin_t, dest_t, prepared)

        if result.success:
            self.route_calculated.emit(result)
            log_success(
                f"M_41: Маршрут найден: {result.distance_m:.0f}м, "
                f"{result.duration_s / 60:.1f} мин"
            )

        return result

    def routes_from_point_to_layer(
        self,
        origin: QgsPointXY,
        destinations: QgsVectorLayer,
        profile: str = 'drive',
        road_layer: Optional[QgsVectorLayer] = None,
    ) -> list[RouteResult]:
        """Маршруты от одной точки ко всем точкам слоя.

        Использует shared graph (граф строится 1 раз).

        Args:
            origin: Начальная точка
            destinations: Точечный слой целей
            profile: Профиль скоростей
            road_layer: Слой дорог (None = default OSM)

        Returns:
            Список RouteResult
        """
        log_info(
            f"M_41: routes_from_point_to_layer, "
            f"профиль='{profile}', целей={destinations.featureCount()}"
        )

        # Валидация
        layer = self._resolve_road_layer(road_layer)
        self._validate_road_layer(layer)
        self._validate_point_in_extent(origin, layer)
        speed_profile = self._profiles.get_profile(profile)

        # Собрать точки назначения
        dest_points: list[QgsPointXY] = []
        for feat in destinations.getFeatures():
            if feat.hasGeometry() and not feat.geometry().isNull():
                dest_points.append(feat.geometry().asPoint())

        if not dest_points:
            log_warning("M_41: Слой целей пуст или без геометрий")
            return []

        # Подготовка сети
        project_crs = self._get_project_crs()
        prepared = self._preparer.prepare_network(
            road_layer=layer,
            profile=speed_profile,
            project_crs=project_crs,
        )

        # Трансформация точек
        origin_t = self._transform_point(origin, layer.crs(), prepared.crs)
        dests_t = [
            self._transform_point(p, destinations.crs(), prepared.crs)
            for p in dest_points
        ]

        # Построить граф со всеми точками
        all_points = [origin_t] + dests_t
        graph_result = self._preparer.build_graph(prepared, all_points)

        # Batch маршруты через Dijkstra
        results = self._route_solver.batch_routes(
            origin=origin_t,
            destinations=dests_t,
            graph_result=graph_result,
            profile=speed_profile,
        )

        found = sum(1 for r in results if r.success)
        log_success(f"M_41: Найдено {found}/{len(results)} маршрутов")

        return results

    # ==================================================================
    # Изохроны
    # ==================================================================

    def isochrone(
        self,
        center: QgsPointXY,
        intervals: list[int],
        profile: str = 'walk',
        unit: str = 'time',
        road_layer: Optional[QgsVectorLayer] = None,
        cell_size: float = 15.0,
        method: str = 'auto',
    ) -> list[IsochroneResult]:
        """Изохроны доступности от одной точки.

        Args:
            center: Центральная точка
            intervals: [300, 600, 900] секунды или [500, 1000] метры
            profile: 'walk', 'drive', 'fire_truck'
            unit: 'time' (секунды) или 'distance' (метры)
            road_layer: Слой дорог (None = Le_1_4_1_1_OSM_АД_line)
            cell_size: Размер ячейки TIN растра (10-25м)
            method: 'auto', 'dijkstra_tin', 'servicearea_buffer'

        Returns:
            Список IsochroneResult (по одному на каждый interval)
        """
        log_info(
            f"M_41: isochrone, профиль='{profile}', "
            f"intervals={intervals}, unit={unit}"
        )

        # Валидация
        layer = self._resolve_road_layer(road_layer)
        self._validate_road_layer(layer)
        self._validate_point_in_extent(center, layer)
        speed_profile = self._profiles.get_profile(profile)

        if unit not in ('time', 'distance'):
            raise ValueError(f"M_41: unit должен быть 'time' или 'distance', получен '{unit}'")

        # Подготовка сети
        project_crs = self._get_project_crs()
        prepared = self._preparer.prepare_network(
            road_layer=layer,
            profile=speed_profile,
            project_crs=project_crs,
        )

        # Трансформация центра в CRS сети
        center_t = self._transform_point(center, layer.crs(), prepared.crs)

        # Построение изохрон
        results = self._isochrone_builder.build_isochrones(
            center=center_t,
            intervals=intervals,
            prepared=prepared,
            unit=unit,
            cell_size=cell_size,
            method=method,
        )

        for result in results:
            if result.geometry and not result.geometry.isEmpty():
                self.isochrone_generated.emit(result)

        successful = sum(
            1 for r in results
            if r.geometry and not r.geometry.isEmpty()
        )
        log_success(
            f"M_41: Построено {successful}/{len(results)} изохрон "
            f"(метод: {results[0].method if results else 'N/A'})"
        )

        return results

    def batch_isochrones(
        self,
        points_layer: QgsVectorLayer,
        intervals: list[int],
        profile: str = 'walk',
        unit: str = 'time',
        road_layer: Optional[QgsVectorLayer] = None,
        max_points: int = 50,
        cell_size: float = 15.0,
        gpkg_path: Optional[str] = None,
        layer_name: str = 'batch_isochrones',
        simplify_for_qfield: bool = False,
        on_completed: Optional[Callable[[QgsVectorLayer], None]] = None,
        on_failed: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Изохроны от всех точек слоя (async через M_17).

        Двухфазный pipeline:
          Phase 1 (background): Dijkstra + TIN для каждой точки
          Phase 2 (main thread callback): GDAL contour + clip + GPKG

        Args:
            points_layer: Точечный слой центров
            intervals: [300, 600, 900] секунды или [500, 1000] метры
            profile: 'walk', 'drive', 'fire_truck'
            unit: 'time' (секунды) или 'distance' (метры)
            road_layer: Слой дорог (None = default OSM)
            max_points: Лимит точек (предупреждение при превышении)
            cell_size: Размер ячейки TIN растра (10-25м)
            gpkg_path: Путь к GPKG (None = memory layer)
            layer_name: Имя результирующего слоя
            simplify_for_qfield: Упростить для QField
            on_completed: Callback при завершении (QgsVectorLayer)
            on_failed: Callback при ошибке (str)

        Returns:
            task_id (str) для отслеживания/отмены через M_17

        Raises:
            ValueError: Невалидные входные данные
        """
        log_info(
            f"M_41: batch_isochrones, профиль='{profile}', "
            f"intervals={intervals}, unit={unit}"
        )

        # Валидация
        layer = self._resolve_road_layer(road_layer)
        self._validate_road_layer(layer)
        speed_profile = self._profiles.get_profile(profile)

        if unit not in ('time', 'distance'):
            raise ValueError(
                f"M_41: unit должен быть 'time' или 'distance', получен '{unit}'"
            )

        # Собрать центральные точки
        centers: list[QgsPointXY] = []
        for feat in points_layer.getFeatures():
            if feat.hasGeometry() and not feat.geometry().isNull():
                centers.append(feat.geometry().asPoint())

        if not centers:
            raise ValueError("M_41: Слой точек пуст или без геометрий")

        # Лимит
        if len(centers) > max_points:
            log_warning(
                f"M_41: Количество точек ({len(centers)}) превышает лимит "
                f"({max_points}). Обрезано до {max_points}."
            )
            centers = centers[:max_points]

        log_info(f"M_41: Batch: {len(centers)} точек")

        # Подготовка сети (главный поток)
        project_crs = self._get_project_crs()
        prepared = self._preparer.prepare_network(
            road_layer=layer,
            profile=speed_profile,
            project_crs=project_crs,
        )

        # Трансформация точек в CRS сети
        centers_t = [
            self._transform_point(c, points_layer.crs(), prepared.crs)
            for c in centers
        ]

        # CRITICAL: Копирование данных для thread safety
        features_copy = list(prepared.layer.getFeatures())
        fields_copy = prepared.layer.fields()
        crs_authid = prepared.crs.authid()
        cost_strategy = 'distance' if unit == 'distance' else 'speed'

        # Создать задачу
        task = Msm_41_6_BatchIsochroneTask(
            features=features_copy,
            fields=fields_copy,
            crs_authid=crs_authid,
            centers=centers_t,
            intervals=intervals,
            unit=unit,
            profile_name=speed_profile.name,
            default_speed=speed_profile.default_speed,
            is_walk=(speed_profile.name == 'walk'),
            cost_strategy=cost_strategy,
            cell_size=cell_size,
        )

        # Сохранить контекст для Phase 2
        self._batch_context = {
            'gpkg_path': gpkg_path,
            'layer_name': layer_name,
            'simplify_for_qfield': simplify_for_qfield,
            'on_completed': on_completed,
            'on_failed': on_failed,
            'profile_name': speed_profile.name,
        }

        # Запуск через M_17
        from Daman_QGIS.managers import registry

        async_manager = registry.get('M_17')
        task_id = async_manager.run(
            task,
            show_progress=True,
            on_completed=self._on_batch_phase1_completed,
            on_failed=self._on_batch_failed,
        )

        log_info(f"M_41: Batch задача запущена: {task_id}")
        return task_id

    def isochrone_from_preset(
        self,
        center: QgsPointXY,
        preset_name: str,
        road_layer: Optional[QgsVectorLayer] = None,
        cell_size: float = 15.0,
        method: str = 'auto',
    ) -> list[IsochroneResult]:
        """Изохроны по нормативному пресету.

        Args:
            center: Центральная точка
            preset_name: Имя пресета из REGULATORY_PRESETS
                (kindergarten_300m, school_500m, fire_urban_10min и др.)
            road_layer: Слой дорог (None = default)
            cell_size: Размер ячейки TIN
            method: Метод построения

        Returns:
            Список IsochroneResult
        """
        # get_preset() raises ValueError if not found
        preset = self._profiles.get_preset(preset_name)

        return self.isochrone(
            center=center,
            intervals=preset['intervals'],
            profile=preset['profile'],
            unit=preset['unit'],
            road_layer=road_layer,
            cell_size=cell_size,
            method=method,
        )

    # ------------------------------------------------------------------
    # Batch Phase 2 (main thread callbacks)
    # ------------------------------------------------------------------

    def _on_batch_phase1_completed(self, output: BatchDijkstraOutput) -> None:
        """Phase 2: GDAL contour + clip + сохранение (главный поток).

        Вызывается из M_17 в главном потоке после завершения фоновой задачи.
        """
        ctx = self._batch_context
        all_isochrones: list[IsochroneResult] = []

        log_info(
            f"M_41: Batch Phase 2: contour extraction для "
            f"{output.successful}/{output.total_points} точек"
        )

        for result in output.results:
            if result.error is not None:
                log_warning(
                    f"M_41: Пропуск точки ({result.center.x():.0f},"
                    f"{result.center.y():.0f}): {result.error}"
                )
                continue

            if result.raster_path is None:
                continue

            try:
                # GDAL contour для каждого интервала (processing.run, главный поток)
                from .submodules.Msm_41_3_isochrone_builder import (
                    Msm_41_3_IsochroneBuilder,
                )

                for interval in result.intervals:
                    polygon = Msm_41_3_IsochroneBuilder._extract_contour_polygon(
                        result.raster_path, interval
                    )

                    # Clip по convex hull
                    if (
                        polygon
                        and not polygon.isNull()
                        and not polygon.isEmpty()
                        and result.convex_hull
                        and not result.convex_hull.isNull()
                    ):
                        polygon = polygon.intersection(result.convex_hull)

                    area = polygon.area() if polygon and not polygon.isEmpty() else 0.0

                    all_isochrones.append(IsochroneResult(
                        geometry=polygon if polygon else QgsGeometry(),
                        interval=interval,
                        unit=result.unit,
                        area_sq_m=area,
                        profile=result.profile_name,
                        center=result.center,
                        entry_cost_s=result.entry_cost if result.unit == 'time' else 0.0,
                        method='dijkstra_tin',
                    ))

            except Exception as exc:
                log_error(f"M_41: Ошибка contour для точки: {exc}")

            finally:
                # Cleanup temp raster
                self._cleanup_temp_file(result.raster_path)

        # Сохранение
        result_layer: Optional[QgsVectorLayer] = None
        if all_isochrones:
            crs = self._get_project_crs()
            result_layer = self._result_writer.save_isochrones_to_layer(
                isochrones=all_isochrones,
                layer_name=ctx['layer_name'],
                crs=crs,
                gpkg_path=ctx['gpkg_path'],
                add_to_project=True,
                simplify_for_qfield=ctx['simplify_for_qfield'],
            )

        valid = sum(
            1 for r in all_isochrones
            if r.geometry and not r.geometry.isEmpty()
        )
        log_success(
            f"M_41: Batch завершен: {valid} изохрон "
            f"от {output.total_points} точек"
        )

        # Emit signal
        if result_layer:
            self.batch_completed.emit(result_layer)

        # User callback
        user_cb = ctx.get('on_completed')
        if user_cb and result_layer:
            user_cb(result_layer)

    def _on_batch_failed(self, error_msg: str) -> None:
        """Callback при ошибке batch задачи."""
        log_error(f"M_41: Batch ошибка: {error_msg}")

        ctx = self._batch_context
        user_cb = ctx.get('on_failed')
        if user_cb:
            user_cb(error_msg)

    @staticmethod
    def _cleanup_temp_file(path: Optional[str]) -> None:
        """Удалить временный файл."""
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    # ==================================================================
    # Сохранение результатов (Msm_41_5)
    # ==================================================================

    def save_routes_to_layer(
        self,
        routes: list[RouteResult],
        layer_name: str = 'routes',
        gpkg_path: Optional[str] = None,
        add_to_project: bool = True,
    ) -> Optional[QgsVectorLayer]:
        """Сохранить маршруты как слой (memory или GPKG).

        Args:
            routes: Список RouteResult от shortest_route / routes_from_point_to_layer
            layer_name: Имя слоя
            gpkg_path: Путь к GPKG (None = memory layer)
            add_to_project: Добавить слой в текущий проект

        Returns:
            QgsVectorLayer или None при ошибке
        """
        crs = self._get_project_crs()
        return self._result_writer.save_routes_to_layer(
            routes=routes,
            layer_name=layer_name,
            crs=crs,
            gpkg_path=gpkg_path,
            add_to_project=add_to_project,
        )

    def save_isochrones_to_layer(
        self,
        isochrones: list[IsochroneResult],
        layer_name: str = 'isochrones',
        gpkg_path: Optional[str] = None,
        add_to_project: bool = True,
        simplify_for_qfield: bool = False,
    ) -> Optional[QgsVectorLayer]:
        """Сохранить изохроны как слой (memory или GPKG).

        Args:
            isochrones: Список IsochroneResult от isochrone()
            layer_name: Имя слоя
            gpkg_path: Путь к GPKG (None = memory layer)
            add_to_project: Добавить слой в текущий проект
            simplify_for_qfield: Упростить геометрии для QField (Douglas-Peucker 10м)

        Returns:
            QgsVectorLayer или None при ошибке
        """
        crs = self._get_project_crs()
        return self._result_writer.save_isochrones_to_layer(
            isochrones=isochrones,
            layer_name=layer_name,
            crs=crs,
            gpkg_path=gpkg_path,
            add_to_project=add_to_project,
            simplify_for_qfield=simplify_for_qfield,
        )

    # ==================================================================
    # Утилиты
    # ==================================================================

    def get_available_profiles(self) -> dict[str, SpeedProfile]:
        """Список доступных профилей скоростей."""
        return self._profiles.get_all_profiles()

    def get_available_presets(self) -> dict[str, dict]:
        """Список нормативных пресетов."""
        return self._profiles.get_all_presets()

    def get_active_backend(self) -> str:
        """Текущий бэкенд анализа."""
        return 'local'  # Этап 5: ORS API

    def invalidate_cache(self) -> None:
        """Очистить кэш подготовленных сетей и графов."""
        self._preparer.invalidate_cache()
        self._last_prepared = None
        self._last_graph = None
        log_info("M_41: Кэш очищен")

    # ==================================================================
    # Валидация входных данных
    # ==================================================================

    def _resolve_road_layer(
        self,
        road_layer: Optional[QgsVectorLayer],
    ) -> QgsVectorLayer:
        """Определить слой дорог: переданный или default OSM."""
        if road_layer is not None:
            return road_layer

        # Поиск дефолтного слоя OSM в проекте
        project = QgsProject.instance()
        for layer in project.mapLayers().values():
            if layer.name() == LAYER_OSM_ROADS_LINE:
                log_info(f"M_41: Используется дефолтный слой '{layer.name()}'")
                return layer

        raise ValueError(
            f"M_41: Слой дорог не задан и дефолтный '{LAYER_OSM_ROADS_LINE}' "
            f"не найден в проекте. Загрузите OSM дороги через F_1_2."
        )

    @staticmethod
    def _validate_road_layer(road_layer: QgsVectorLayer) -> None:
        """Проверка валидности слоя дорог."""
        if not road_layer.isValid():
            raise ValueError(
                f"M_41: Слой '{road_layer.name()}' невалиден"
            )
        if road_layer.featureCount() == 0:
            raise ValueError(
                f"M_41: Слой '{road_layer.name()}' пуст"
            )
        geom_type = road_layer.geometryType()
        if geom_type != QgsWkbTypes.GeometryType.LineGeometry:
            raise ValueError(
                f"M_41: Ожидается LineString слой, получен "
                f"{QgsWkbTypes.geometryDisplayString(geom_type)}"
            )

    @staticmethod
    def _validate_point_in_extent(
        point: QgsPointXY,
        layer: QgsVectorLayer,
        tolerance: float = 1000.0,
    ) -> None:
        """Проверка что точка в пределах досягаемости слоя."""
        extent = layer.extent()
        buffered = QgsRectangle(extent)
        buffered.grow(tolerance)
        if not buffered.contains(point):
            raise ValueError(
                f"M_41: Точка ({point.x():.1f}, {point.y():.1f}) "
                f"за пределами слоя дорог (>={tolerance}м от границы)"
            )

    @staticmethod
    def _get_project_crs() -> QgsCoordinateReferenceSystem:
        """CRS текущего проекта."""
        crs = QgsProject.instance().crs()
        if not crs.isValid():
            log_warning("M_41: CRS проекта невалидна, используется EPSG:3857")
            return QgsCoordinateReferenceSystem("EPSG:3857")
        return crs

    @staticmethod
    def _transform_point(
        point: QgsPointXY,
        source_crs: QgsCoordinateReferenceSystem,
        target_crs: QgsCoordinateReferenceSystem,
    ) -> QgsPointXY:
        """Трансформация точки между CRS."""
        if source_crs == target_crs:
            return point

        from qgis.core import QgsCoordinateTransform
        transform = QgsCoordinateTransform(
            source_crs, target_crs, QgsProject.instance()
        )
        return transform.transform(point)
