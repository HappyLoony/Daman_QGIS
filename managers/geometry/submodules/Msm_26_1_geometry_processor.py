# -*- coding: utf-8 -*-
"""
Msm_26_1 - Геометрические операции для нарезки ЗПР

АРХИТЕКТУРА: thin wrapper над GEOS OverlayNG snap-rounding
============================================================

Все overlay операции (intersection / difference / unaryUnion) передают
QgsGeometryParameters(gridSize=0.001) в native QGIS API. GEOS 3.9+
встроенно делает robust snap-rounding noding:
  1. Все vertices обоих входов снапятся к grid (1 мм)
  2. Snap-rounding noder обрабатывает edges/nodes
  3. OverlayNG строит топологически robust результат
  4. Все output vertices гарантированно ∈ grid

Это **deterministic** поведение: на одинаковых входах всегда одинаковый
выход, без floating-point noise.

ВЫБОР gridSize=0.001 (1 мм)
============================================================
- < 1 мм → floating-point noise (vertices off by ε)
- 1 мм → cadastral noise threshold (real precision DXF ≈ 1мм)
- 1 см → cadastral precision (Приказ Росреестра), но gridSize=0.01
  слишком агрессивный — съедает реальные mini-gap'ы ЗУ↔ЗПР (реестровые
  ошибки, которые оператор должен видеть для коррекции через F_2_3)
Эмпирический sweep 2026-05-22 на проекте Сапун подтвердил 0.001 как
sweet spot (см. план migrаtion ниже).

ИСТОРИЯ: до 2026-05-22 был custom workaround
============================================================
До migration этот модуль содержал:
- `_snap_to_grid(geom)` — manual snap к COORDINATE_PRECISION=0.01 после
  каждой overlay операции, с area-based exception (MIN_VALID_AREA=0.10)
  для degenerate cases
- `MIN_VALID_AREA = 0.10` — порог "артефакт vs значимое"
- `clip_to_boundary(geom, boundary)` — post-clip к оригинальной ЗПР для
  защиты от overflow артефактов (добавлен 2026-05-21)
Этот стек был костылём из 3 слоёв вокруг проблемы которую GEOS OverlayNG
уже решает встроенно (см. план migrаtion).

ЕСЛИ ПОЯВИЛАСЬ РЕГРЕССИЯ → НЕ восстанавливайте старые workarounds:
- НЕ добавлять manual snap (`snappedToGrid`) ВНУТРИ overlay методов
  (intersection/difference/create_union) — это вернёт удалённый _snap_to_grid
- НЕ добавлять `MIN_VALID_AREA` filter — GEOS сам отбрасывает degenerate
- НЕ добавлять post-clip к original boundary (gridSize garantee'ит
  overflow ≤ 0.5 мм, в пределах cadastral noise)
- НЕ менять gridSize на 0.01 — потеряете реестровые ошибки

ИСКЛЮЧЕНИЕ: `snap_to_cadastral_precision` — это ОДИН финальный snap к 0.01м
на готовой output геометрии, ВНЕ overlay методов, вызывается в caller
(Msm_26_4 после _cut_by_overlays) для нормализации к кадастровой точности
из CLAUDE.md. Это не регрессия — это разные слои ответственности:
gridSize=0.001 даёт робастность overlay; snap_to_cadastral_precision даёт
точность выходных данных.

Вместо этого: diagnose через сравнение с проектом Сапун (Phase 4 plan).
Полная карта: `documentation/plans/2026-05-22-geometry-processor-gridsize-refactor.md`

Документация GEOS OverlayNG: https://libgeos.org/doxygen/classgeos_1_1operation_1_1overlayng_1_1OverlayNG.html

МЕТОДЫ
============================================================
- intersection — пересечение ЗПР с ЗУ (snap-rounding)
- difference — разность ЗПР минус ЗУ (snap-rounding)
- create_union — unaryUnion слоя (snap-rounding)
- need_additional_cut — pre-check нужна ли overlay-нарезка
- extract_polygons — split MultiPolygon на отдельные части
- resolve_pinch_points — обработка self-touching boundary
- validate_and_fix — makeValid wrapper
"""

from typing import List, Optional, Tuple

from qgis.core import (
    QgsGeometry,
    QgsVectorLayer,
    QgsFeature,
    QgsGeometryParameters,
)

from Daman_QGIS.utils import log_info, log_warning
from Daman_QGIS.constants import COORDINATE_PRECISION

# GEOS OverlayNG snap-rounding precision (м).
# Передаётся в QgsGeometryParameters.setGridSize для intersection/difference/
# unaryUnion. Все output vertices гарантированно на этом grid.
#
# 0.001 = 1 мм. См. module docstring (раздел "ВЫБОР gridSize") для обоснования.
# НЕ менять без полного re-sweep'а на не-Сапун проектах.
GEOS_GRID_SIZE = 0.001  # м


class Msm_26_1_GeometryProcessor:
    """Процессор геометрических операций для нарезки"""

    def __init__(self) -> None:
        """Инициализация процессора"""
        self.precision = COORDINATE_PRECISION

    def _make_params(self) -> QgsGeometryParameters:
        """QgsGeometryParameters со snap-rounding precision.

        Используется во всех overlay методах. Не создавать новый Params
        inline — всегда через этот helper, чтобы gridSize был
        single source of truth.

        Сам объект QgsGeometryParameters быстрый (POD-like wrapper),
        создание per-call негативно на performance не влияет.
        """
        params = QgsGeometryParameters()
        params.setGridSize(GEOS_GRID_SIZE)
        return params

    def intersection(self, geom1: QgsGeometry, geom2: QgsGeometry) -> QgsGeometry:
        """Пересечение двух геометрий со снап-роундингом GEOS.

        Использует QgsGeometryParameters(gridSize=GEOS_GRID_SIZE) для
        deterministic результата: GEOS OverlayNG сам обрабатывает
        floating-point noise и degenerate cases. Результат гарантированно
        ⊆ обоих входов и snap'нут к gridSize.

        Args:
            geom1: Первая геометрия (ЗПР)
            geom2: Вторая геометрия (ЗУ)

        Returns:
            QgsGeometry: Результат пересечения (валидный, snap'нутый к gridSize).
            Пустой если входы пусты или результат degenerate под precision.
        """
        if geom1.isEmpty() or geom2.isEmpty():
            return QgsGeometry()

        result = geom1.intersection(geom2, self._make_params())

        if result.isEmpty():
            return QgsGeometry()

        # makeValid как safety net (snap-rounding обычно даёт valid, но
        # на сложных входах может потребоваться cleanup).
        if not result.isGeosValid():
            result = result.makeValid()

        return result

    def difference(self, geom1: QgsGeometry, geom2: QgsGeometry) -> QgsGeometry:
        """Разность двух геометрий со снап-роундингом GEOS.

        difference(ЗПР, union(ЗУ)) → НГС. GEOS OverlayNG автоматически
        обрабатывает sub-precision slivers и floating-point noise.

        Args:
            geom1: Исходная геометрия (ЗПР)
            geom2: Вычитаемая геометрия (union всех ЗУ)

        Returns:
            QgsGeometry: Результат разности (валидный, ⊆ geom1).
            Sub-mm slivers и floating-point noise удалены автоматически.
        """
        if geom1.isEmpty():
            return QgsGeometry()

        if geom2.isEmpty():
            return QgsGeometry(geom1)  # копия без изменений

        result = geom1.difference(geom2, self._make_params())

        if result.isEmpty():
            return QgsGeometry()

        if not result.isGeosValid():
            result = result.makeValid()

        return result

    def create_union(self, layer: QgsVectorLayer) -> QgsGeometry:
        """Создание union геометрии всех объектов слоя со снап-роундингом.

        Args:
            layer: Векторный слой

        Returns:
            QgsGeometry: Объединённая геометрия (валидная, snap'нутая к gridSize).
        """
        if not layer or layer.featureCount() == 0:
            return QgsGeometry()

        geometries = []
        for feature in layer.getFeatures():
            geom = feature.geometry()
            if geom and not geom.isEmpty():
                if not geom.isGeosValid():
                    geom = geom.makeValid()
                    if geom.isEmpty():
                        continue
                geometries.append(geom)

        if not geometries:
            return QgsGeometry()

        result = QgsGeometry.unaryUnion(geometries, self._make_params())

        if not result.isEmpty() and not result.isGeosValid():
            result = result.makeValid()

        log_info(f"Msm_26_1: Создан union из {len(geometries)} геометрий")
        return result

    def need_additional_cut(self, fragment: QgsGeometry, boundary: QgsGeometry) -> bool:
        """Определение необходимости дополнительной нарезки

        Не нужно резать если:
        - Фрагмент не пересекается с границей
        - Фрагмент полностью внутри границы

        Нужно резать если:
        - Частичное пересечение (часть внутри, часть снаружи)

        Args:
            fragment: Геометрия фрагмента
            boundary: Геометрия границы (overlay)

        Returns:
            bool: True если нужно резать
        """
        if fragment.isEmpty() or boundary.isEmpty():
            return False

        intersection = fragment.intersection(boundary)

        # Не пересекается - не режем
        if intersection.isEmpty():
            return False

        # Полностью внутри - не режем, только помечаем
        # Проверка через сравнение площадей с погрешностью
        fragment_area = fragment.area()
        intersection_area = intersection.area()

        # Если площадь пересечения равна площади фрагмента (с погрешностью) - полностью внутри
        if fragment_area > 0 and abs(fragment_area - intersection_area) / fragment_area < 0.001:
            return False

        # Частичное пересечение - режем
        return True

    def cut_by_boundaries(
        self,
        features: List[Tuple[QgsGeometry, dict]],
        boundary_layer: QgsVectorLayer,
        boundary_field: str
    ) -> List[Tuple[QgsGeometry, dict, Optional[str]]]:
        """Нарезка списка геометрий по границам слоя

        Args:
            features: Список кортежей (геометрия, атрибуты)
            boundary_layer: Слой границ
            boundary_field: Имя поля для атрибута наложения

        Returns:
            List: Список кортежей (геометрия, атрибуты, значение_наложения)
        """
        if not boundary_layer or boundary_layer.featureCount() == 0:
            # Нет границ - возвращаем как есть с None для overlay
            return [(geom, attrs, None) for geom, attrs in features]

        boundary_union = self.create_union(boundary_layer)
        if boundary_union.isEmpty():
            return [(geom, attrs, None) for geom, attrs in features]

        result = []

        for geom, attrs in features:
            if geom.isEmpty():
                continue

            if not self.need_additional_cut(geom, boundary_union):
                # Не режем - определяем находится ли внутри
                intersection = geom.intersection(boundary_union)
                if not intersection.isEmpty():
                    result.append((geom, attrs, "-"))
                else:
                    result.append((geom, attrs, None))
            else:
                # Режем на две части
                inside = self.intersection(geom, boundary_union)
                outside = self.difference(geom, boundary_union)

                if not inside.isEmpty():
                    result.append((inside, attrs.copy(), "-"))

                if not outside.isEmpty():
                    result.append((outside, attrs.copy(), None))

        log_info(f"Msm_26_1: Нарезка по {boundary_field}: "
                f"было {len(features)}, стало {len(result)} объектов")
        return result

    def extract_polygons(
        self,
        geom: QgsGeometry,
        min_area: float = 0.0001
    ) -> List[QgsGeometry]:
        """Извлечение отдельных полигонов из геометрии

        Нормализация Multi* типов в список отдельных геометрий.
        Фильтрует мелкие артефакты после геометрических операций.

        Args:
            geom: Исходная геометрия (может быть Multi*)
            min_area: Минимальная площадь полигона (м2), по умолчанию 0.0001

        Returns:
            List[QgsGeometry]: Список отдельных полигонов (валидных)
        """
        if geom.isEmpty():
            return []

        result = []
        filtered_count = 0
        invalid_count = 0

        # Определяем тип геометрии
        geom_type = geom.type()
        wkb_type = geom.wkbType()

        # Проверка на GeometryCollection (может возникнуть после makeValid/snap)
        # wkbType 7 = GeometryCollection
        if wkb_type == 7:
            # Извлекаем все части из GeometryCollection
            for i in range(geom.constGet().numGeometries()):
                part = QgsGeometry(geom.constGet().geometryN(i).clone())
                if part.type() == 2:  # Polygon
                    area = part.area()
                    if area >= min_area:
                        if not part.isGeosValid():
                            part = part.makeValid()
                        if not part.isEmpty():
                            result.append(part)
                    else:
                        filtered_count += 1
            return result

        # Для полигонов
        if geom_type == 2:  # Polygon
            if geom.isMultipart():
                # MultiPolygon -> список полигонов
                multi = geom.asMultiPolygon()
                total_parts = len(multi)
                total_area = geom.area()

                # Fallback: если asMultiPolygon() вернул 0 частей при площади > 0
                if total_parts == 0 and total_area > 0:
                    try:
                        single_poly = geom.asPolygon()
                        if single_poly:
                            single_geom = QgsGeometry.fromPolygonXY(single_poly)
                            if not single_geom.isEmpty() and single_geom.area() >= min_area:
                                if not single_geom.isGeosValid():
                                    single_geom = single_geom.makeValid()
                                if not single_geom.isEmpty():
                                    result.append(single_geom)
                                    return result
                    except Exception:
                        pass

                for polygon in multi:
                    single_geom = QgsGeometry.fromPolygonXY(polygon)
                    if single_geom.isEmpty():
                        invalid_count += 1
                        continue
                    area = single_geom.area()
                    if area < min_area:
                        filtered_count += 1
                        continue
                    if not single_geom.isGeosValid():
                        single_geom = single_geom.makeValid()
                        if single_geom.isEmpty():
                            invalid_count += 1
                            continue
                    result.append(single_geom)
            else:
                # SinglePolygon
                area = geom.area()
                if area >= min_area:
                    valid_geom = geom
                    if not geom.isGeosValid():
                        valid_geom = geom.makeValid()
                    if not valid_geom.isEmpty():
                        result.append(valid_geom)
                    else:
                        filtered_count += 1
                else:
                    filtered_count += 1

        return result

    def resolve_pinch_points(self, geom: QgsGeometry) -> QgsGeometry:
        """Разрешение пиковых узлов в полигоне

        Если hole касается exterior ring в одной вершине (pinch point),
        вершины hole (без touch_pt) вставляются в exterior вместо touch_pt,
        hole удаляется. Exterior обходит бывший hole по его границам.

        Типичная ситуация: ЗУ полностью внутри ЗПР, одна вершина ЗУ
        на границе ЗПР. НГС = ЗПР - ЗУ получает hole, касающийся exterior.

        Args:
            geom: Полигон (single или multi)

        Returns:
            QgsGeometry: Полигон без pinch points. Если resolve невозможен
            или результат невалиден — возвращает оригинал.
        """
        if geom.isEmpty():
            return geom

        if geom.isMultipart():
            parts = geom.asMultiPolygon()
            resolved_parts = []
            any_resolved = False
            for part in parts:
                single = QgsGeometry.fromPolygonXY(part)
                resolved = self._resolve_single_polygon_pinch(single)
                if resolved != single:
                    any_resolved = True
                resolved_parts.append(resolved.asPolygon())
            if not any_resolved:
                return geom
            result = QgsGeometry.fromMultiPolygonXY(resolved_parts)
        else:
            result = self._resolve_single_polygon_pinch(geom)
            if result == geom:
                return geom

        if result.isGeosValid():
            return result
        log_warning("Msm_26_1: resolve_pinch_points создал невалидную геометрию, откат")
        return geom

    def _resolve_single_polygon_pinch(self, geom: QgsGeometry) -> QgsGeometry:
        """Resolve pinch points для single polygon

        Args:
            geom: Single polygon

        Returns:
            QgsGeometry: Polygon без pinch points
        """
        poly = geom.asPolygon()
        if not poly:
            return geom

        exterior = poly[0]
        holes = poly[1:]

        if not holes:
            return geom

        # Половина кадастровой точности (0.01м)
        TOLERANCE = 0.005

        # Индекс координат exterior (без closing point)
        ext_coords = {}
        for i, p in enumerate(exterior[:-1]):
            key = (round(p.x(), 3), round(p.y(), 3))
            ext_coords[key] = i

        remaining_holes = []
        modified = False

        for hole in holes:
            # Найти вершины hole, совпадающие с exterior
            touches = []
            for hi, hp in enumerate(hole[:-1]):
                key = (round(hp.x(), 3), round(hp.y(), 3))
                if key in ext_coords:
                    touches.append((hi, ext_coords[key]))

            if len(touches) == 1:
                hole_touch_idx, ext_touch_idx = touches[0]

                # Вершины hole без touch_pt, в исходном порядке
                hole_vertices = [hole[i] for i in range(len(hole) - 1)
                                 if i != hole_touch_idx]

                if not hole_vertices:
                    continue

                # Вставляем в exterior ВМЕСТО touch_pt
                exterior = exterior[:ext_touch_idx] + hole_vertices + exterior[ext_touch_idx + 1:]

                # Обновляем индекс после модификации exterior
                ext_coords = {}
                for i, p in enumerate(exterior[:-1]):
                    key = (round(p.x(), 3), round(p.y(), 3))
                    ext_coords[key] = i

                modified = True
                log_info(f"Msm_26_1: Pinch point resolved — hole ({len(hole)-1} вершин) "
                        f"влит в exterior, touch_pt удалён")
            else:
                remaining_holes.append(hole)

        if not modified:
            return geom

        new_poly = [exterior] + remaining_holes
        return QgsGeometry.fromPolygonXY(new_poly)

    def validate_and_fix(self, geom: QgsGeometry) -> QgsGeometry:
        """Валидация и исправление геометрии

        Args:
            geom: Исходная геометрия

        Returns:
            QgsGeometry: Валидная геометрия
        """
        if geom.isEmpty():
            return geom

        if not geom.isGeosValid():
            fixed = geom.makeValid()
            if fixed.isEmpty():
                log_warning("Msm_26_1: Не удалось исправить невалидную геометрию")
                return QgsGeometry()
            return fixed

        return geom

    def snap_to_cadastral_precision(self, geom: QgsGeometry) -> QgsGeometry:
        """Финальный snap к кадастровой точности COORDINATE_PRECISION=0.01м.

        ОТЛИЧИЕ от убранного `_snap_to_grid` (history раздел в module docstring):
        - Старый _snap_to_grid: вызывался ПОСЛЕ КАЖДОГО intersection/difference
          внутри overlay операций + имел area-based filter (MIN_VALID_AREA=0.10)
          + требовал clip_to_boundary post-clip. Костыль из 3 слоёв.
        - Этот метод: ОДИН вызов на ФИНАЛЬНОЙ геометрии (после всех overlay)
          в caller (Msm_26_4 после _cut_by_overlays). Без area filter, без
          post-clip. Просто rounding выходных vertices к кадастровой точности.

        ЗАЧЕМ: Output из intersection/difference (gridSize=0.001) на 1мм grid.
        CLAUDE.md требует «ТОЧНОСТЬ КООРДИНАТ: 0.01м» для всех координат в
        GeoPackage. Этот метод нормализует output к 0.01м для соответствия.

        Спорные точки (наш кейс T с 8.2мм/9.5мм vertex расхождениями) сохраняются:
        snap к 0.01м не сольёт точки которые на 8-9мм друг от друга — они
        округлятся к разным cell'ам на 1см grid. F_0_4 их по-прежнему ловит
        как «Близкие точки между объектами», оператор правит через F_2_3.

        Защита от degenerate: если snap делает геометрию невалидной/пустой —
        откат к оригиналу (1мм vertices лучше чем broken geometry).

        Args:
            geom: Финальная геометрия после всех overlay операций (1мм grid).

        Returns:
            QgsGeometry: Геометрия на 0.01м grid. Откат к оригиналу при degenerate.
        """
        if geom.isEmpty():
            return geom

        snapped = geom.snappedToGrid(COORDINATE_PRECISION, COORDINATE_PRECISION)

        if snapped.isEmpty():
            return geom

        if not snapped.isGeosValid():
            fixed = snapped.makeValid()
            if fixed.isEmpty():
                return geom
            snapped = fixed

        return snapped
