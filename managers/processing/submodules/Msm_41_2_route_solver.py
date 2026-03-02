"""
Msm_41_2: RouteSolver - Вычисление кратчайших маршрутов.

Два режима:
A) Single route через processing.run (native:shortestpathpointtopoint)
B) Batch routes через shared QgsGraph + Dijkstra (граф строится 1 раз)

Родительский менеджер: M_41_IsochroneTransportManager
"""

from __future__ import annotations

from typing import Optional

import processing

from qgis.core import (
    QgsDistanceArea,
    QgsFeatureRequest,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)
from qgis.analysis import QgsGraph, QgsGraphAnalyzer

from Daman_QGIS.utils import log_info, log_warning, log_error

from .Msm_41_1_network_preparer import (
    GraphBuildResult,
    Msm_41_1_NetworkPreparer,
    _PreparedNetwork,
)
from .Msm_41_4_speed_profiles import RouteResult, SpeedProfile

__all__ = ['Msm_41_2_RouteSolver']


class Msm_41_2_RouteSolver:
    """Вычисление кратчайших маршрутов через сеть дорог."""

    def __init__(self, network_preparer: Msm_41_1_NetworkPreparer) -> None:
        self._preparer = network_preparer

    # ------------------------------------------------------------------
    # A) Single route (processing.run)
    # ------------------------------------------------------------------

    def single_route(
        self,
        origin: QgsPointXY,
        destination: QgsPointXY,
        prepared: _PreparedNetwork,
    ) -> RouteResult:
        """Кратчайший маршрут A -> B через processing.run.

        Подходит для одноразового вызова (1 маршрут).
        Для batch используйте batch_routes().

        Args:
            origin: Начальная точка (в CRS подготовленного слоя)
            destination: Конечная точка (в CRS подготовленного слоя)
            prepared: Подготовленная сеть из NetworkPreparer

        Returns:
            RouteResult
        """
        log_info(
            f"Msm_41_2: Single route "
            f"({origin.x():.1f},{origin.y():.1f}) -> "
            f"({destination.x():.1f},{destination.y():.1f})"
        )

        try:
            result = processing.run("native:shortestpathpointtopoint", {
                'INPUT': prepared.layer,
                'STRATEGY': 1,  # Fastest (по времени)
                'DIRECTION_FIELD': 'direction',
                'VALUE_FORWARD': '1',
                'VALUE_BACKWARD': '2',
                'VALUE_BOTH': '0',
                'DEFAULT_DIRECTION': 2,  # Both
                'SPEED_FIELD': 'speed_kmh',
                'DEFAULT_SPEED': prepared.profile.default_speed,
                'START_POINT': f'{origin.x()},{origin.y()}',
                'END_POINT': f'{destination.x()},{destination.y()}',
                'OUTPUT': 'memory:',
            })
        except Exception as exc:
            log_error(f"Msm_41_2 (single_route): {exc}")
            return RouteResult(
                geometry=QgsGeometry(),
                distance_m=0.0,
                duration_s=0.0,
                profile=prepared.profile.name,
                origin=origin,
                destination=destination,
                success=False,
                error_message=str(exc),
            )

        output_layer: QgsVectorLayer = result['OUTPUT']

        if output_layer.featureCount() == 0:
            log_warning("Msm_41_2: Маршрут не найден (нет связности сети)")
            return RouteResult(
                geometry=QgsGeometry(),
                distance_m=0.0,
                duration_s=0.0,
                profile=prepared.profile.name,
                origin=origin,
                destination=destination,
                success=False,
                error_message="Маршрут не найден: точки не связаны по сети",
            )

        feat = next(output_layer.getFeatures())
        geom = feat.geometry()

        # native:shortestpathpointtopoint возвращает cost в ЧАСАХ (STRATEGY=1)
        cost_hours = feat['cost'] if 'cost' in feat.fields().names() else 0.0
        duration_s = cost_hours * 3600.0
        distance_m = geom.length() if geom and not geom.isNull() else 0.0

        log_info(
            f"Msm_41_2: Маршрут найден: {distance_m:.0f}м, "
            f"{duration_s:.0f}с ({duration_s / 60:.1f} мин)"
        )

        return RouteResult(
            geometry=geom,
            distance_m=distance_m,
            duration_s=duration_s,
            profile=prepared.profile.name,
            origin=origin,
            destination=destination,
        )

    # ------------------------------------------------------------------
    # B) Batch routes (shared graph + Dijkstra)
    # ------------------------------------------------------------------

    def batch_routes(
        self,
        origin: QgsPointXY,
        destinations: list[QgsPointXY],
        graph_result: GraphBuildResult,
        profile: SpeedProfile,
    ) -> list[RouteResult]:
        """Маршруты от одной точки ко множеству целей через shared graph.

        Граф строится 1 раз, Dijkstra запускается 1 раз от origin,
        маршруты извлекаются для каждого destination.

        Args:
            origin: Начальная точка (должна быть в tied_points[0])
            destinations: Конечные точки (tied_points[1:])
            graph_result: Результат build_graph() с привязанными точками
            profile: Профиль скоростей

        Returns:
            Список RouteResult (по одному на каждый destination)
        """
        graph = graph_result.graph
        tied = graph_result.tied_points

        if len(tied) < 2:
            log_error("Msm_41_2 (batch_routes): Недостаточно привязанных точек")
            return []

        # Origin = tied_points[0], destinations = tied_points[1:]
        start_id = graph.findVertex(tied[0])

        log_info(
            f"Msm_41_2: Batch routes от вершины {start_id} "
            f"к {len(destinations)} целям"
        )

        # Dijkstra из origin (один раз)
        (tree, costs) = QgsGraphAnalyzer.dijkstra(graph, start_id, 0)

        # Entry cost (origin -> graph vertex)
        entry_cost_s = self._compute_entry_cost(
            origin, tied[0], profile.default_speed
        )

        results: list[RouteResult] = []
        for i, dest_point in enumerate(destinations):
            tied_dest = tied[i + 1]  # +1 потому что origin = tied[0]
            end_id = graph.findVertex(tied_dest)

            # Exit cost (graph vertex -> destination)
            exit_cost_s = self._compute_entry_cost(
                dest_point, tied_dest, profile.default_speed
            )

            if tree[end_id] == -1:
                # Недостижимо
                results.append(RouteResult(
                    geometry=QgsGeometry(),
                    distance_m=0.0,
                    duration_s=0.0,
                    profile=profile.name,
                    origin=origin,
                    destination=dest_point,
                    entry_cost_s=entry_cost_s,
                    exit_cost_s=exit_cost_s,
                    success=False,
                    error_message="Точка недостижима по сети",
                ))
                continue

            # Извлечь маршрут из дерева Dijkstra
            route_geom = self._extract_route(graph, tree, start_id, end_id)
            dijkstra_cost_s = costs[end_id]
            total_duration_s = entry_cost_s + dijkstra_cost_s + exit_cost_s
            distance_m = route_geom.length() if route_geom else 0.0

            results.append(RouteResult(
                geometry=route_geom if route_geom else QgsGeometry(),
                distance_m=distance_m,
                duration_s=total_duration_s,
                profile=profile.name,
                origin=origin,
                destination=dest_point,
                entry_cost_s=entry_cost_s,
                exit_cost_s=exit_cost_s,
            ))

        found = sum(1 for r in results if r.success)
        log_info(f"Msm_41_2: Batch routes: {found}/{len(results)} найдено")
        return results

    # ------------------------------------------------------------------
    # C) Route to boundary exit (ГОЧС evacuation)
    # ------------------------------------------------------------------

    def route_to_boundary(
        self,
        origin_vertex_id: int,
        graph: QgsGraph,
        tree: list[int],
        costs: list[float],
        boundary: QgsGeometry,
        profile: SpeedProfile,
        origin: QgsPointXY,
        entry_cost_s: float = 0.0,
    ) -> RouteResult:
        """Кратчайший маршрут от точки до выхода за пределы boundary.

        Линейный скан O(V) по результатам Dijkstra: ищет ближайшую
        по стоимости вершину графа, лежащую ВНЕ полигона boundary.

        Args:
            origin_vertex_id: ID стартовой вершины в графе
            graph: QgsGraph (построенный)
            tree: Дерево Dijkstra (результат dijkstra_from_point)
            costs: Стоимости Dijkstra
            boundary: Полигон зоны опасности (Polygon/MultiPolygon)
            profile: Профиль скоростей
            origin: Оригинальная точка пользователя (для RouteResult)
            entry_cost_s: Стоимость привязки origin к графу

        Returns:
            RouteResult с маршрутом до ближайшей точки выхода
        """
        # Edge case: origin уже вне boundary
        origin_geom = QgsGeometry.fromPointXY(origin)
        if not boundary.contains(origin_geom):
            log_info("Msm_41_2: Origin уже за пределами зоны")
            return RouteResult(
                geometry=QgsGeometry(),
                distance_m=0.0,
                duration_s=0.0,
                profile=profile.name,
                origin=origin,
                destination=origin,
            )

        vertex_count = graph.vertexCount()
        best_cost = float('inf')
        best_vertex_id = -1

        log_info(
            f"Msm_41_2: route_to_boundary, скан {vertex_count} вершин"
        )

        for vid in range(vertex_count):
            cost = costs[vid]
            # Пропуск недостижимых и дорогих
            if cost < 0 or cost >= best_cost:
                continue
            point = graph.vertex(vid).point()
            point_geom = QgsGeometry.fromPointXY(point)
            if not boundary.contains(point_geom):
                best_cost = cost
                best_vertex_id = vid

        if best_vertex_id == -1:
            log_warning(
                "Msm_41_2: Не найден выход за пределы зоны по сети"
            )
            return RouteResult(
                geometry=QgsGeometry(),
                distance_m=0.0,
                duration_s=0.0,
                profile=profile.name,
                origin=origin,
                destination=origin,
                success=False,
                error_message="Выход за пределы зоны не найден по дорожной сети",
            )

        route_geom = self._extract_route(
            graph, tree, origin_vertex_id, best_vertex_id
        )
        exit_point = graph.vertex(best_vertex_id).point()
        distance_m = route_geom.length() if route_geom else 0.0
        total_duration_s = entry_cost_s + best_cost

        log_info(
            f"Msm_41_2: Выход найден: {distance_m:.0f}м, "
            f"{total_duration_s:.0f}с ({total_duration_s / 60:.1f} мин)"
        )

        return RouteResult(
            geometry=route_geom if route_geom else QgsGeometry(),
            distance_m=distance_m,
            duration_s=total_duration_s,
            profile=profile.name,
            origin=origin,
            destination=exit_point,
            entry_cost_s=entry_cost_s,
        )

    # ------------------------------------------------------------------
    # D) Low-level Dijkstra API
    # ------------------------------------------------------------------

    def dijkstra_from_point(
        self,
        graph: QgsGraph,
        start_vertex_id: int,
    ) -> tuple[list[int], list[float]]:
        """Запуск Dijkstra из вершины (низкоуровневый API).

        Args:
            graph: QgsGraph
            start_vertex_id: ID стартовой вершины

        Returns:
            (tree, costs) - дерево кратчайших путей и стоимости
        """
        return QgsGraphAnalyzer.dijkstra(graph, start_vertex_id, 0)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_route(
        graph: QgsGraph,
        tree: list[int],
        start_id: int,
        end_id: int,
    ) -> Optional[QgsGeometry]:
        """Восстановить LineString маршрута из дерева Dijkstra.

        Обход tree[] от destination к source с инверсией.

        Args:
            graph: QgsGraph
            tree: Дерево кратчайших путей (результат dijkstra)
            start_id: ID стартовой вершины
            end_id: ID конечной вершины

        Returns:
            QgsGeometry(LineString) или None если недостижимо
        """
        if tree[end_id] == -1:
            return None

        route_points: list[QgsPointXY] = [graph.vertex(end_id).point()]
        current = end_id

        # Безопасность: ограничение итераций
        max_iterations = graph.vertexCount() + 1
        iteration = 0

        while current != start_id:
            iteration += 1
            if iteration > max_iterations:
                log_error(
                    "Msm_41_2 (_extract_route): "
                    "Превышен лимит итераций при обходе дерева"
                )
                return None

            edge_id = tree[current]
            if edge_id == -1:
                return None

            edge = graph.edge(edge_id)
            current = edge.fromVertex()
            route_points.append(graph.vertex(current).point())

        route_points.reverse()
        return QgsGeometry.fromPolylineXY(route_points)

    @staticmethod
    def _compute_entry_cost(
        original: QgsPointXY,
        tied: QgsPointXY,
        default_speed_kmh: float,
    ) -> float:
        """Вычислить entry/exit cost (расстояние от точки до сети).

        Args:
            original: Оригинальная точка пользователя
            tied: Привязанная к графу точка
            default_speed_kmh: Скорость для расчета времени

        Returns:
            Стоимость в секундах
        """
        if default_speed_kmh <= 0:
            return 0.0

        dist = QgsDistanceArea()
        try:
            distance_m = dist.measureLine(original, tied)
        except Exception:
            # Fallback: планиметрическая дистанция
            dx = original.x() - tied.x()
            dy = original.y() - tied.y()
            distance_m = (dx * dx + dy * dy) ** 0.5

        speed_ms = default_speed_kmh * 1000.0 / 3600.0
        return distance_m / speed_ms if speed_ms > 0 else 0.0
