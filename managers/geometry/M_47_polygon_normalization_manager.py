# -*- coding: utf-8 -*-
"""
M_47_PolygonNormalizationManager — единая физическая нормализация
полигональных геометрий: каждое кольцо приводится к обходу по часовой
стрелке (CW в мат. СК QGIS) с началом в СЗ-точке (ближайшей к bbox
NW-углу = min_east, max_north).

ОТЛИЧИЕ ОТ M_20:
- M_20 — виртуальная нумерация (атрибут «Точки» + точечный слой Т_*),
  исходная полигональная геометрия НЕ модифицируется.
- M_47 — физическая нормализация (modify gpkg), порядок vertex_idx
  становится согласован с порядком в Excel/DXF/TAB перечнях и
  в QGIS Vertex Editor.

ИДЕМПОТЕНТНОСТЬ:
Повторный вызов normalize_layer / normalize_geometry даёт идентичную
геометрию (нет coordinate drift). Идемпотентность достигается через
`equals()` short-circuit (FIX-5) на per-feature уровне. Поэтому
безопасно вызывать в КАЖДОЙ точке создания/модификации полигонального
слоя.

STATELESS:
Класс не имеет instance state — оба public-метода объявлены как
`@staticmethod`. Layer-id кэш не используется (FIX-OPT-5 debate
2026-05-30): memory-provider guard отсекает SplitByFeatureModifier до
любого кэш-check, а cross-callsite шаринг невозможен по convention
плана (fresh instance per callsite). Singleton + M_1 hook не нужен.

ПРИМЕНЯЕМОСТЬ:
- Polygon / MultiPolygon (точки и линии пропускаются)
- Vector layers с editing capability (memory-слои и read-only WFS
  пропускаются с warning)
- Слои не в edit-mode (если уже редактируются — пропуск с warning,
  чтобы не смешать чужие правки)

КОНВЕНЦИЯ:
- Каждое кольцо после нормализации: CW в мат.СК (signed_area_2 < 0)
- v0 = ближайшая к (min_x, max_y) точка
- Замыкающая точка добавляется автоматически (QGIS требует замкнутости)
"""

from typing import Optional
from qgis.core import (
    Qgis,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
    QgsWkbTypes,
)

from Daman_QGIS.utils import log_info, log_warning, log_error
from . import _ring_utils

__all__ = ['PolygonNormalizationManager']


class PolygonNormalizationManager:
    """Stateless менеджер физической нормализации полигональных геометрий.

    Конвенция:
    - exterior: CW в мат.СК, старт с NW
    - hole: CW в мат.СК, старт с NW (единый стандарт, не П/0592)

    Stateless by design (FIX-OPT-5 debate 2026-05-30): нет кэша,
    нет per-session state. Идемпотентность через `equals()` short-circuit
    (FIX-5) на per-feature уровне, не через layer-id кэш. M_X = класс
    по convention auto-registration (`managers/geometry/__init__.py`
    через `_domain_loader`), но методы — `@staticmethod`. Callsite:
    `PolygonNormalizationManager.normalize_layer(layer)`.
    """

    # --- Public API ---

    @staticmethod
    def normalize_layer(layer: QgsVectorLayer) -> int:
        """Нормализовать все полигональные feature слоя in-place в .gpkg.

        Идемпотентно (через `equals()` short-circuit). Безопасно
        вызывать многократно.

        Args:
            layer: Полигональный QgsVectorLayer.

        Returns:
            Количество фич, чья геометрия была изменена (для уже
            нормализованных = 0). Возвращает 0 при пропуске
            (memory provider, edit conflict, не polygon).
        """
        if not layer or not layer.isValid():
            return 0
        if layer.geometryType() != Qgis.GeometryType.Polygon:
            return 0

        # Memory-слои не пишутся в .gpkg (split_feature и любые temp).
        provider = layer.dataProvider()
        if provider is not None and provider.name() == 'memory':
            return 0

        # Edit conflict guard (FIX-rev2-16: strict, без isModified-релакса).
        # QGIS edit-session layer-global, не nested — unconditional
        # commitChanges() ниже коммитнул бы pending правки caller'а.
        # Callers (F_1_1 и др.) обязаны commit'ить ДО вызова M_47.
        if layer.isEditable():
            log_warning(
                f"M_47: Слой {layer.name()} в edit-mode — нормализация "
                f"пропущена (избежать неявного коммита чужой edit session)"
            )
            return 0

        if not layer.startEditing():
            log_warning(
                f"M_47: Не удалось начать редактирование {layer.name()} — "
                f"нормализация пропущена"
            )
            return 0

        modified = 0
        skipped_zm = 0
        try:
            for feature in layer.getFeatures():
                geom = feature.geometry()
                if not geom or geom.isEmpty():
                    continue
                # Z/M guard (FIX-6): silent data loss недопустим.
                wkb = geom.wkbType()
                if QgsWkbTypes.hasZ(wkb) or QgsWkbTypes.hasM(wkb):
                    skipped_zm += 1
                    continue
                if geom.type() != Qgis.GeometryType.Polygon:
                    continue

                new_geom = PolygonNormalizationManager.normalize_geometry(geom)
                if new_geom is None or new_geom.isEmpty():
                    continue

                # Idempotency at write level (FIX-5): пропустить changeGeometry
                # если geom уже нормализована. Устраняет write amplification,
                # undo-stack pollution, projectChanged cascade на no-op рерунах.
                #
                # OPT-rev2-15: QGIS 3.40 — `equals(const QgsGeometry &)`
                # стабильный API (НЕ deprecated overload). Идемпотентность
                # гарантирована для bit-identical случая. Если будущий рефакторинг
                # `normalize_geometry` нарушит bit-identity на no-op повторе —
                # допустимый патч: `new_geom.isFuzzyEqual(geom, 1e-9)` (для МСК
                # coords ~10^5-10^7 epsilon 1e-9 безопасен) или
                # `new_geom.asWkb() == geom.asWkb()`.
                if new_geom.equals(geom):
                    continue

                if not layer.changeGeometry(feature.id(), new_geom):
                    log_warning(
                        f"M_47: changeGeometry неуспешно для fid="
                        f"{feature.id()} в слое {layer.name()}"
                    )
                    continue
                modified += 1

            if skipped_zm > 0:
                log_warning(
                    f"M_47: в слое {layer.name()} пропущено {skipped_zm} фич "
                    f"с Z/M координатами (нормализация 3D полигонов out of "
                    f"scope, см. план FIX-6)"
                )

            if not layer.commitChanges():
                log_error(
                    f"M_47: commitChanges не удался для {layer.name()} — откат"
                )
                layer.rollBack()
                return 0
        except Exception as e:
            log_error(f"M_47: Ошибка нормализации {layer.name()}: {e}")
            try:
                layer.rollBack()
            except Exception:
                pass
            return 0

        log_info(
            f"M_47: Нормализовано CW+NW {modified} фич в слое {layer.name()}"
        )
        return modified

    @staticmethod
    def normalize_geometry(geom: QgsGeometry) -> Optional[QgsGeometry]:
        """Нормализовать одну полигональную геометрию.

        Pure function (без побочных эффектов). Каждое кольцо приводится
        к CW-обходу на карте и ротируется так, чтобы v0 = ближайшая к СЗ.

        Args:
            geom: Polygon или MultiPolygon geometry.

        Returns:
            Новый QgsGeometry с нормализованными кольцами, либо None
            если входная геометрия не полигональная, пустая или Z/M.
        """
        if geom is None or geom.isEmpty():
            return None
        if geom.type() != Qgis.GeometryType.Polygon:
            return None
        # Z/M guard (FIX-6): asPolygon/fromPolygonXY теряют Z/M (XY-only API).
        # None = «пропустить» для вызывающего, не «нечего нормализовать».
        wkb = geom.wkbType()
        if QgsWkbTypes.hasZ(wkb) or QgsWkbTypes.hasM(wkb):
            return None

        is_multi = geom.isMultipart()
        polygons = geom.asMultiPolygon() if is_multi else [geom.asPolygon()]

        new_polygons = []
        for polygon in polygons:
            if not polygon:
                new_polygons.append(polygon)
                continue

            new_rings = []
            for ring in polygon:
                # Минимум 3 уникальные вершины + замыкающая = 4 элемента
                if not ring or len(ring) < 4:
                    new_rings.append(ring)
                    continue

                # Снять замыкающую (если есть)
                had_close = (ring[0] == ring[-1])
                work = list(ring[:-1]) if had_close else list(ring)

                # Шаг 1: реверс на CW если кольцо CCW на карте (_ring_utils, FIX-1)
                work_tuples = [(p.x(), p.y()) for p in work]
                if not _ring_utils.is_clockwise(work_tuples):
                    work = list(reversed(work))
                    work_tuples = [(p.x(), p.y()) for p in work]

                # Шаг 2: ротация к СЗ точке (_ring_utils, FIX-1)
                nw_idx = _ring_utils.find_nw_point_index(work_tuples)
                if nw_idx > 0:
                    work = work[nw_idx:] + work[:nw_idx]

                # Замкнуть обратно (QGIS требует замкнутости колец)
                work.append(QgsPointXY(work[0].x(), work[0].y()))
                new_rings.append(work)

            new_polygons.append(new_rings)

        if is_multi:
            return QgsGeometry.fromMultiPolygonXY(new_polygons)
        else:
            return QgsGeometry.fromPolygonXY(new_polygons[0])
