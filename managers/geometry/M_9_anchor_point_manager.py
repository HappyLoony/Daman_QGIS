# -*- coding: utf-8 -*-
"""
M_9_AnchorPointManager — единая точка вычисления представительной точки
(точки привязки) геометрии: точки ВНУТРИ полигона / на линии.

НАЗНАЧЕНИЕ:
Централизует расчёт «точки привязки» для потребителей, которым нужна точка
внутри фигуры (маркеры ошибок 0_4, подписи подложек, DXF-выноски, зонды
категории/геокодирования). Наивный `centroid()` для вогнутых полигонов и
мультиполигонов кладёт точку ВНЕ фигуры (на проекте «Сапун» — 2.89% объектов);
`pointOnSurface` / `poleOfInaccessibility` дают точку внутри гарантированно.

STATELESS:
Класс не имеет instance state — оба public-метода объявлены как
`@staticmethod`. M_X = класс по convention auto-registration
(`managers/geometry/__init__.py` через `_domain_loader`, keyword `Manager`),
но методы статические. Callsite:
`AnchorPointManager.anchor_point(geom, "surface")`.

КОНТРАКТ «БЕЗ FALLBACK» (закон проекта, CLAUDE.md §Философия):
Менеджер выбирает ОДИН метод по типу/стратегии и возвращает точку. Невалид /
пусто / неподдерживаемый тип / ВЫРОЖДЕННЫЙ вход → `None` (это «нет валидного
входа», не fallback-кейс). Цепочки `pole → surface → centroid → bbox`
ЗАПРЕЩЕНЫ. `makeValid` НЕ встраивается (скрытое преобразование) — остаётся у
потребителя.

ДЕТЕКТ ВЫРОЖДЕННЫХ (ЦЕНТРАЛИЗОВАН в M_9, ключевое решение плана):
- surface: `geom.area() <= 0` → `None` (нативный pointOnSurface на zero-area
  даёт точку с contains=False; M_9 ОБЯЗАН вернуть None);
- pole: radius НЕ finite ИЛИ `<= 0` → `None` (вырожденный полигон даёт
  poleOfInaccessibility radius=1.8e308 overflow).
Единая проверка вместо `area>0`-guard в каждом потребителе.

ОБЛАСТЬ ПРИМЕНЕНИЯ:
- Polygon / MultiPolygon: на крупнейшей по площади части.
  strategy "surface" — pointOnSurface (дёшево, batch; маркеры ошибок);
  strategy "pole"    — poleOfInaccessibility(precision) (визуальный центр).
- Line / MultiLine: середина по длине interpolate(length/2) на длиннейшей
  части (strategy игнорируется).
- Point / MultiPoint / GeometryCollection / невалид / пусто → `None`.

MULTIPART:
Перебор по конвенции — `asMultiPolygon()` / `asMultiPolyline()` (CLAUDE.md),
НЕ `asGeometryCollection()`. Часть с макс. `area()` (полигон) / макс. длиной
(линия). Единый внутренний помощник `_largest_part`.

PRECISION:
`precision` = допуск остановки итераций polylabel (НЕ координатная точность).
Единая гребёнка = COORDINATE_PRECISION (0.01 м). Замер «Сапуна»: pole(1.0)
застревает в локальном кармане (расхождение с pole(0.01) avg=15 м, max=2033 м);
цена x2.43 build-time принята владельцем.
"""

import math
from typing import List, Optional, Tuple

from qgis.core import (
    Qgis,
    QgsGeometry,
    QgsPointXY,
)

from Daman_QGIS.constants import COORDINATE_PRECISION
from Daman_QGIS.utils import log_error

__all__ = ['AnchorPointManager']


class AnchorPointManager:
    """Stateless менеджер представительной точки (точки привязки) геометрии.

    Polygon/MultiPolygon → точка ВНУТРИ (surface/pole), Line/MultiLine →
    середина по длине. Вырожденный / невалидный / неподдерживаемый вход →
    `None` (контракт «без fallback», CLAUDE.md §Философия).

    M_X = класс по convention auto-registration (keyword `Manager`), методы —
    `@staticmethod`. Callsite: `AnchorPointManager.anchor_point(geom)`.
    """

    # --- Public API ---

    @staticmethod
    def anchor_point(geom: QgsGeometry, strategy: str = "surface",
                     precision: float = COORDINATE_PRECISION) -> Optional[QgsPointXY]:
        """Точка привязки геометрии — по типу.

        Polygon/MultiPolygon: на крупнейшей по площади части.
          strategy "surface" — pointOnSurface (дёшево, batch). precision НЕ
            применяется.
          strategy "pole"    — poleOfInaccessibility(precision) (визуальный
            центр; подписи, DXF).
        Line/MultiLine: середина по длине interpolate(length/2) на длиннейшей
        части. strategy игнорируется.

        Args:
            geom: входная геометрия (Polygon/MultiPolygon/Line/MultiLine).
            strategy: "surface" (по умолчанию) или "pole". Прочее → "surface".
            precision: допуск поиска полюса (НЕ координатная точность), по
                умолчанию COORDINATE_PRECISION (0.01 м).

        Returns:
            QgsPointXY либо None (БЕЗ fallback):
            - невалидная/пустая геометрия;
            - неподдерживаемый тип (Point/коллекция);
            - вырожденный полигон (area() <= 0).
        """
        if geom is None or geom.isNull() or geom.isEmpty():
            return None

        try:
            geom_type = geom.type()

            if geom_type == Qgis.GeometryType.Polygon:
                part = AnchorPointManager._largest_polygon_part(geom)
                if part is None:
                    return None
                # Детект вырожденных (surface): zero-area внутренности нет.
                if part.area() <= 0:
                    return None
                if strategy == "pole":
                    pt = AnchorPointManager._pole_point(part, precision)
                    return pt
                return AnchorPointManager._surface_point(part)

            if geom_type == Qgis.GeometryType.Line:
                return AnchorPointManager._line_midpoint(geom)

            # Point / коллекция / неизвестный тип — вне scope.
            return None

        except Exception as e:
            log_error(f"M_9 (anchor_point): ошибка вычисления точки привязки: {e}")
            return None

    @staticmethod
    def pole_with_radius(geom: QgsGeometry,
                         precision: float = COORDINATE_PRECISION
                         ) -> Optional[Tuple[QgsPointXY, float]]:
        """Полюс недоступности + радиус вписанной окружности.

        Polygon/MultiPolygon на крупнейшей части. radius = distance из
        poleOfInaccessibility (радиус максимальной вписанной окружности).
        Отдельный метод, чтобы НЕ менять тип возврата anchor_point.

        Args:
            geom: входная геометрия (Polygon/MultiPolygon).
            precision: допуск поиска полюса, по умолчанию COORDINATE_PRECISION.

        Returns:
            (QgsPointXY, radius) либо None:
            - не полигон / пусто / невалид;
            - вырожден: radius НЕ finite или <= 0.
        """
        if geom is None or geom.isNull() or geom.isEmpty():
            return None

        try:
            if geom.type() != Qgis.GeometryType.Polygon:
                return None

            part = AnchorPointManager._largest_polygon_part(geom)
            if part is None:
                return None
            # Детект вырожденных (как в anchor_point surface): zero-area полигон
            # даёт poleOfInaccessibility radius = DBL_MAX (1.8e308) — КОНЕЧНОЕ
            # число, isfinite его пропускает; ловим по площади ДО вызова.
            if part.area() <= 0:
                return None

            pole_geom, radius = part.poleOfInaccessibility(precision)
            if pole_geom is None or pole_geom.isNull() or pole_geom.isEmpty():
                return None
            # Подстраховка: неположительный / нечисловой радиус.
            if not math.isfinite(radius) or radius <= 0:
                return None

            return (pole_geom.asPoint(), radius)

        except Exception as e:
            log_error(f"M_9 (pole_with_radius): ошибка вычисления полюса: {e}")
            return None

    # --- Internal helpers ---

    @staticmethod
    def _largest_polygon_part(geom: QgsGeometry) -> Optional[QgsGeometry]:
        """Крупнейшая по площади полигональная часть как single-part geometry.

        Single-part полигон возвращается как есть. Для MultiPolygon перебор по
        `asMultiPolygon()` (НЕ asGeometryCollection — конвенция CLAUDE.md),
        выбор части с макс. `area()`.

        Returns:
            QgsGeometry (single Polygon) либо None при отсутствии частей.
        """
        if not geom.isMultipart():
            return geom

        rings_list = geom.asMultiPolygon()
        if not rings_list:
            return None

        best_geom: Optional[QgsGeometry] = None
        best_area = -1.0
        for rings in rings_list:
            if not rings:
                continue
            candidate = QgsGeometry.fromPolygonXY(rings)
            if candidate is None or candidate.isEmpty():
                continue
            area = candidate.area()
            if area > best_area:
                best_area = area
                best_geom = candidate

        return best_geom

    @staticmethod
    def _largest_line_part(geom: QgsGeometry) -> Optional[QgsGeometry]:
        """Длиннейшая линейная часть как single-part geometry.

        Single-part линия возвращается как есть. Для MultiLine перебор по
        `asMultiPolyline()`, выбор части с макс. длиной.

        Returns:
            QgsGeometry (single LineString) либо None при отсутствии частей.
        """
        if not geom.isMultipart():
            return geom

        lines = geom.asMultiPolyline()
        if not lines:
            return None

        best_geom: Optional[QgsGeometry] = None
        best_length = -1.0
        for line in lines:
            if not line or len(line) < 2:
                continue
            candidate = QgsGeometry.fromPolylineXY(line)
            if candidate is None or candidate.isEmpty():
                continue
            length = candidate.length()
            if length > best_length:
                best_length = length
                best_geom = candidate

        return best_geom

    @staticmethod
    def _surface_point(part: QgsGeometry) -> Optional[QgsPointXY]:
        """pointOnSurface крупнейшей части (точка гарантированно внутри).

        Returns:
            QgsPointXY либо None если pointOnSurface не дал валидной точки.
        """
        pt_geom = part.pointOnSurface()
        if pt_geom is None or pt_geom.isNull() or pt_geom.isEmpty():
            return None
        return pt_geom.asPoint()

    @staticmethod
    def _pole_point(part: QgsGeometry, precision: float) -> Optional[QgsPointXY]:
        """poleOfInaccessibility крупнейшей части (визуальный центр).

        Вырожденный полигон даёт overflow radius (1.8e308) — детект как None.

        Returns:
            QgsPointXY либо None если полюс вырожден / невалиден.
        """
        pole_geom, radius = part.poleOfInaccessibility(precision)
        if pole_geom is None or pole_geom.isNull() or pole_geom.isEmpty():
            return None
        if not math.isfinite(radius) or radius <= 0:
            return None
        return pole_geom.asPoint()

    @staticmethod
    def _line_midpoint(geom: QgsGeometry) -> Optional[QgsPointXY]:
        """Середина по длине длиннейшей линейной части (interpolate(length/2)).

        Returns:
            QgsPointXY либо None если длина нулевая / interpolate не дал точки.
        """
        part = AnchorPointManager._largest_line_part(geom)
        if part is None:
            return None

        length = part.length()
        if not math.isfinite(length) or length <= 0:
            return None

        mid_geom = part.interpolate(length / 2.0)
        if mid_geom is None or mid_geom.isNull() or mid_geom.isEmpty():
            return None
        return mid_geom.asPoint()
