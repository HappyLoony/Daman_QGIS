# -*- coding: utf-8 -*-
"""
Msm_26_1 - Геометрические операции для нарезки ЗПР

АРХИТЕКТУРА: thin wrapper над GEOS OverlayNG snap-rounding
============================================================

Все overlay операции (intersection / difference / unaryUnion) передают
QgsGeometryParameters(gridSize=0.01) в native QGIS API. GEOS 3.9+
встроенно делает robust snap-rounding noding:
  1. Все vertices обоих входов снапятся к grid (1 см = кадастровая точность)
  2. Snap-rounding noder обрабатывает edges/nodes
  3. OverlayNG строит топологически robust результат
  4. Все output vertices гарантированно ∈ grid (сразу на cadastral precision)

Это **deterministic** поведение: на одинаковых входах всегда одинаковый
выход, без floating-point noise.

ВЫБОР gridSize=0.01 (1 см)
============================================================
- < 1 мм → floating-point noise (vertices off by ε)
- 1 мм → промежуточная точность, оставляет sliver-spikes 0–3.6 мм
  на стыках 3+ ЗУ под углом к ЗПР (vertex ЗУ_6 и computed-точка
  пересечения ЗПР с гранью ЗУ_12/ЗУ_15 не сливаются, образуя
  выживающий sliver внутри Раздела — баг 199/205/206 на Сапуне 2026-05-28)
- 1 см → cadastral precision (Приказ Росреестра). Эмпирически (Сапун,
  2026-05-28) даёт строго лучший результат:
  · 0 sliver-spikes внутри Раздела (vs 3 при 0.001)
  · 0 НГС за ЗПР (overflow), 0 Раздел за ЗПР
  · 100% vertices snapped к 0.01 (vs 89% при 0.001)
  · mini-gap'ы ЗУ↔ЗПР НЕ съедаются — сохраняются как sliver-НГС
    вне Раздела (3 шт. 0.16–0.71 м² на Сапуне), валидные индикаторы
    реестровой неточности

ИСТОРИЯ
============================================================
- 2026-05-22: custom workaround (`_snap_to_grid` + `MIN_VALID_AREA=0.10`
  + `clip_to_boundary`) заменён на GEOS OverlayNG snap-rounding (gridSize=0.001).
- 2026-05-28: gridSize переведён с 0.001 на 0.01 (см. раздел "ВЫБОР").
  Удалён `snap_to_cadastral_precision` — стал no-op, gridSize=0.01 даёт
  точность 0.01 на выходе сразу.

ЕСЛИ ПОЯВИЛАСЬ РЕГРЕССИЯ → НЕ восстанавливайте старые workarounds:
- НЕ добавлять manual snap (`snappedToGrid`) ВНУТРИ overlay методов —
  это вернёт удалённый _snap_to_grid
- НЕ добавлять `MIN_VALID_AREA` filter — GEOS сам отбрасывает degenerate
- НЕ добавлять post-clip к original boundary (gridSize гарантирует
  overflow = 0)
- НЕ возвращать gridSize=0.001 — на Сапуне даёт sliver-spikes внутри Раздела

СВОЙСТВО CONTAINMENT (GEOS OverlayNG, best-practice):
- output ⊆ snapped(input1) ∩ snapped(input2), но НЕ обязательно ⊆ original input
  (vertices смещаются на ≤ 0.5×gridSize). Overflow worst-case = 0.5×gridSize.
  На gridSize=0.01 это 5 мм — в пределах кадастрового шума.
- gridSize применять для multi-geometry overlay / floating-point noise (DXF) /
  multiway junctions (3+ границы в точке) / когда нужна deterministic топология.
  НЕ применять когда нужна EXACT original precision или для single-geometry
  transforms (rotate/translate — precision не релевантна).
НЕ ПУТАТЬ с:
- `QgsGeometry.snappedToGrid()` — post-process snap ОДНОЙ геометрии, без overlay
  logic; не замена gridSize в overlay.
- `processing.run("native:snappointstogrid")` — алгоритм для точечных слоёв,
  другая абстракция.
Требует GEOS 3.9+ (OverlayNG); в QGIS 3.40 — GEOS 3.14, OK.

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

# GEOS OverlayNG snap-rounding precision (м).
# Передаётся в QgsGeometryParameters.setGridSize для intersection/difference/
# unaryUnion. Все output vertices гарантированно на этом grid.
#
# 0.01 = 1 см = кадастровая точность (Приказ Росреестра, CLAUDE.md).
# См. module docstring (раздел "ВЫБОР gridSize") для обоснования.
# НЕ менять без полного re-sweep'а на не-Сапун проектах.
GEOS_GRID_SIZE = 0.01  # м


class Msm_26_1_GeometryProcessor:
    """Процессор геометрических операций для нарезки"""

    def __init__(self) -> None:
        """Инициализация процессора"""

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

