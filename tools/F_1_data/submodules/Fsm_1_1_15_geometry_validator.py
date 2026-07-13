# -*- coding: utf-8 -*-
"""
Fsm_1_1_15_GeometryValidator — превентивная валидация и авто-исправление
невалидной геометрии (hole-outside-shell и др. GEOS-невалидность) на входе
импорта TAB, ДО первой материализации слоя в GeoPackage.

КОНТЕКСТ (баг-триггер):
Малый контур многоконтурного ЗУ мерцает/исчезает по масштабу. Причина —
`POLYGON((shell),(контур2))` где второе кольцо полностью снаружи shell
(`shell.disjoint(ring2)=True`), `isGeosValid=False` (GEOS «hole lies outside
shell»). TAB-импортёр (OGR) грузит как есть. Правильная форма —
`MULTIPOLYGON(((shell)),((контур2)))`.

АРХИТЕКТУРА (план F_1_1, 17 ревизий + 15 adversarial-проходов + 2 QGIS-приёмки):
Вариант B — валидатор строит НОВЫЙ MultiPolygon memory-слой ДО первой
материализации (внутри Fsm_1_1_2 после CRS-set, перед save_to_gpkg). Тип
GPKG-слоя наследуется от wkbType() — memory-слой уже MultiPolygon → gpkg-слой
рождается MultiPolygon одной записью (без ре-материализации, без orphan-ghost).

per-feature-selective:
- Валидные фичи → verbatim-промоция в 1-частный MultiPolygon через
  convertToMultiType() (координатно-идентично, сохраняет Z/M и кривые). НЕ
  проходят через fixgeometries → НЕ реструктурируются. Их 0.01+unified_cw
  нормализацию делает downstream M_47.
- Невалидные фичи → native:fixgeometries METHOD=1 (Structure) на ПОДМНОЖЕСТВЕ
  невалидных (не raw makeValid — алгоритм несёт 4 защитных пост-шага, ключевой:
  GeometryCollection-выход фильтруется на исходный тип Polygon). Затем
  per-geometry снап M_6._round_geometry (ПОСТ-fix re-validation), merge обратно
  ПОЗИЦИОННЫЙ (zip 1:1, НЕ по fid).
- Unfixable (fixgeometries → MultiPolygon EMPTY на collapsed): детект по
  `isEmpty() OR not isGeosValid()` (НЕ isNull) → подставить ИСХОДНУЮ геометрию,
  промотированную convertToMultiType() + padding (fail-closed «перенести как
  есть», silent-drop guard).

fail-closed: непочиненная фича НЕ дропается молча; сбой построения → блокировать.
"""

from typing import Optional, Tuple, Dict, Any, List

import processing
from qgis.core import (
    Qgis,
    QgsFeature,
    QgsGeometry,
    QgsVectorLayer,
    QgsWkbTypes,
)

from Daman_QGIS.managers import CoordinatePrecisionManager as CPM
from Daman_QGIS.utils import log_info, log_warning, log_error


class Fsm_1_1_15_GeometryValidator:
    """Stateless валидатор геометрии на импорте (все методы @staticmethod).

    Публичный API: validate_and_fix_layer(layer) -> (QgsVectorLayer, dict).
    """

    @staticmethod
    def validate_and_fix_layer(layer: QgsVectorLayer) -> Tuple[QgsVectorLayer, Dict[str, Any]]:
        """Провалидировать и (при необходимости) исправить геометрию слоя.

        Args:
            layer: Исходный in-memory OGR-слой (до материализации в GPKG).

        Returns:
            (result_layer, stats). result_layer — исходный слой as-is (если
            полигональной невалидности нет), либо новый MultiPolygon memory-слой
            с исправленными невалидными и promoted валидными фичами.
            stats = {
                'checked': int,        # всего фич проверено (ручной подсчёт
                                       #   по getFeatures() в ОБЕИХ ветках —
                                       #   featureCount() может дать -1, FIX-5)
                'invalid': int,        # найдено GEOS-невалидных (без Z/M-skip)
                'fixed': int,          # реально стали валидными после fix
                'unfixable': int,      # остались невалидными (перенесены как есть)
                'zm_skipped': int,     # невалидные Z/M-фичи, НЕ гнались через fix
                                       #   (defensive skip, план §2/§6 исключает
                                       #   M/Z из fix; FIX-3)
                'area_delta': float,   # суммарная дельта площади |after - before|,
                                       #   ТОЛЬКО по успешно исправленным (fixed)
                                       #   фичам (FIX-6a)
            }

        Примечание (FIX-6): unfixable-фича записывается НЕВАЛИДНОЙ (осознанный
        fail-closed §5.4 — перенос «как есть» вместо silent-drop; визуальный баг
        мерцания на ней сохраняется, приемлемо по плану). Материализация
        MultiPolygon-выхода в GPKG (commitChanges/commitErrors, §4) вне unit-scope
        — верифицируется GUI-приёмкой владельца (§8 DoD).
        """
        stats: Dict[str, Any] = {
            'checked': 0,
            'invalid': 0,
            'fixed': 0,
            'unfixable': 0,
            'zm_skipped': 0,
            'area_delta': 0.0,
        }

        if layer is None or not layer.isValid():
            log_warning("Fsm_1_1_15: слой невалиден или None — пропуск валидации")
            return layer, stats

        # Фильтр: только полигональные слои. Точечные/линейные/буферные — as-is,
        # тип НЕ промотируется. checked — ручной подсчёт (FIX-5: featureCount()
        # может дать -1 на некоторых провайдерах).
        if layer.geometryType() != Qgis.GeometryType.Polygon:
            checked = 0
            for _feature in layer.getFeatures():
                checked += 1
            stats['checked'] = checked
            return layer, stats

        # D1-детект: per-feature isGeosValid() → множество fid невалидных.
        # Z/M-фичи среди невалидных исключаются из fix (FIX-3, defensive).
        # РАЦИОНАЛЕ (эмпирика QGIS 3.40.15 + rev-code Judge): Z-РАЗМЕРНОСТЬ
        # переживает весь fix-путь (fixgeometries/snappedToGrid/convertToMultiType
        # Z-safe — проверено). Реальная причина skip НЕ «потеря Z», а то, что
        # fixgeometries METHOD=1 (Structure) при разрешении самопересечений вводит
        # НОВЫЕ вершины с интерполированными/недостоверными Z-ЗНАЧЕНИЯМИ (для
        # hole-outside-shell новых вершин нет → Z точен; для bowtie/self-int → Z
        # сомнителен). Для кадастра честный skip лучше недостоверной высоты.
        # Фича НЕ теряется — переносится как есть (см. _build_fixed_layer). План §2/§6.
        invalid_fids = set()
        zm_skip_fids = set()
        checked = 0
        for feature in layer.getFeatures():
            checked += 1
            geom = feature.geometry()
            if geom is None or geom.isNull() or geom.isEmpty():
                continue
            if not geom.isGeosValid():
                wkb = geom.wkbType()
                if QgsWkbTypes.hasZ(wkb) or QgsWkbTypes.hasM(wkb):
                    # Невалидная Z/M-фича — defensive skip fix (паттерн M_47:148-152).
                    zm_skip_fids.add(feature.id())
                    log_warning(
                        f"Fsm_1_1_15: фича fid={feature.id()} слоя '{layer.name()}' "
                        f"имеет Z/M-координаты — исключена из fix (defensive, "
                        f"план §2/§6), перенесена как есть"
                    )
                else:
                    invalid_fids.add(feature.id())

        stats['checked'] = checked
        stats['invalid'] = len(invalid_fids)
        stats['zm_skipped'] = len(zm_skip_fids)

        # early-return ТОЛЬКО когда нет НИ fixable-, НИ Z/M-невалидных фич: слой
        # чист, не трогается, тип НЕ промотируется. Если есть Z/M-невалидные
        # (fix они не проходят), слой всё равно пересобирается — невалидная Z/M-
        # фича переносится как есть в консистентный MultiPolygon-выход.
        if not invalid_fids and not zm_skip_fids:
            return layer, stats

        log_info(
            f"Fsm_1_1_15: обнаружено {len(invalid_fids)} невалидных геометрий "
            f"(+ {len(zm_skip_fids)} Z/M-skip) из {checked} в слое "
            f"'{layer.name()}' — авто-исправление"
        )

        try:
            result_layer, build_stats = Fsm_1_1_15_GeometryValidator._build_fixed_layer(
                layer, invalid_fids, zm_skip_fids
            )
        except Exception as e:
            # fail-closed: сбой построения выходного слоя — блокировать,
            # НЕ возвращать частично-обработанный слой молча.
            log_error(f"Fsm_1_1_15: сбой исправления геометрии слоя '{layer.name()}': {e}")
            raise

        stats.update(build_stats)
        return result_layer, stats

    @staticmethod
    def _build_fixed_layer(
        layer: QgsVectorLayer,
        invalid_fids: set,
        zm_skip_fids: Optional[set] = None,
    ) -> Tuple[QgsVectorLayer, Dict[str, Any]]:
        """Построить MultiPolygon memory-слой: валидные promoted, невалидные fixed.

        Итерация по фичам источника В ИСХОДНОМ ПОРЯДКЕ (Q3). Z/M-невалидные
        (zm_skip_fids) переносятся как есть (convertToMultiType + padding, БЕЗ
        fix/snap — FIX-3 defensive, план §2/§6 исключает M/Z из fix).
        """
        if zm_skip_fids is None:
            zm_skip_fids = set()
        crs = layer.crs()

        # 1. Fix невалидного подмножества ЦЕЛИКОМ (одним processing.run на sub-слое)
        #    — 1-in-1-out, порядок сохраняется. Собираем позиционный список
        #    исходных невалидных фич и параллельный список fix-выходов.
        sub_layer = QgsVectorLayer(
            f"MultiPolygon?crs={crs.authid()}" if crs.authid() else "MultiPolygon",
            "_fsm_1_1_15_invalid_subset",
            "memory",
        )
        # FIX-1 (ISSUE-001): явный setCrs объектом CRS — authid() пуст для
        # кастомной МСК USER CRS → URI даёт слой без СК. setCrs надёжен.
        sub_layer.setCrs(crs)
        sub_provider = sub_layer.dataProvider()
        sub_provider.addAttributes(layer.fields())
        sub_layer.updateFields()

        # Позиционный список исходных невалидных (fixable) фич в порядке итерации.
        invalid_source_order: List[QgsFeature] = []
        for feature in layer.getFeatures():
            if feature.id() in invalid_fids:
                invalid_source_order.append(feature)

        fixed_geom_by_fid: Dict[int, QgsGeometry] = {}
        unfixable_fids = set()
        area_delta = 0.0

        # fixgeometries запускаем ТОЛЬКО при наличии fixable-подмножества
        # (пустой вход в processing бессмыслен; Z/M-only слой строим напрямую).
        if invalid_source_order:
            # Заполняем sub-слой невалидными фичами (padding атрибутов до target).
            sub_target_count = sub_layer.fields().count()
            sub_feats_to_add: List[QgsFeature] = []
            for src_feat in invalid_source_order:
                nf = QgsFeature(sub_layer.fields())
                nf.setGeometry(QgsGeometry(src_feat.geometry()))
                src_attrs = list(src_feat.attributes())
                padded = src_attrs + [None] * (sub_target_count - len(src_attrs))
                nf.setAttributes(padded)
                sub_feats_to_add.append(nf)
            if not sub_provider.addFeatures(sub_feats_to_add):
                raise RuntimeError("Fsm_1_1_15: не удалось наполнить sub-слой невалидных фич")
            sub_layer.updateExtents()

            # native:fixgeometries METHOD=1 (Structure). Алгоритм несёт 4 защитных
            # пост-шага (GeometryCollection→исходный тип), raw makeValid их теряет.
            fix_result = processing.run("native:fixgeometries", {
                'INPUT': sub_layer,
                'METHOD': 1,  # Structure
                'OUTPUT': 'memory:',
            })
            fixed_output = fix_result['OUTPUT']
            # processing теряет CRS на memory-выходе — восстанавливаем (как
            # create_buffer_layers).
            fixed_output.setCrs(crs)

            # Позиционный merge (C-1): i-я невалидная source-фича <- i-я fixed-фича.
            # НЕ по fid (processing-sink волен перенумеровать → латентный silent-баг).
            fixed_list: List[QgsFeature] = list(fixed_output.getFeatures())
            if len(fixed_list) != len(invalid_source_order):
                # 1-in-1-out инвариант fixgeometries нарушен — fail-closed.
                raise RuntimeError(
                    f"Fsm_1_1_15: fixgeometries вернул {len(fixed_list)} фич на "
                    f"{len(invalid_source_order)} входных (нарушен 1:1 инвариант)"
                )
        else:
            fixed_list = []

        # Карта fid источника -> исправленная+снапнутая геометрия (либо fallback).
        # Позиционный zip (C-1): пустые списки → цикл не исполняется (Z/M-only).
        for src_feat, fixed_feat in zip(invalid_source_order, fixed_list):
            src_geom = src_feat.geometry()
            src_area = src_geom.area() if src_geom is not None and not src_geom.isNull() else 0.0
            raw_fixed = fixed_feat.geometry()

            # C-1b guard: unfixable = isEmpty() OR not isGeosValid() (НЕ isNull —
            # fixgeometries на collapsed даёт MultiPolygon EMPTY, isNull=False).
            if raw_fixed is None or raw_fixed.isNull() or raw_fixed.isEmpty() \
                    or not raw_fixed.isGeosValid():
                # Перенести ИСХОДНУЮ геометрию как есть (fail-closed silent-drop
                # guard), промотированную в MultiPolygon (иначе Polygon в
                # MultiPolygon-слой не сохранится — §4). Снап НЕ применяем: фича
                # осталась невалидной — downstream M_47 нормализует, если ре-виндит.
                unfixable_fids.add(src_feat.id())
                fallback = QgsGeometry(src_geom) if src_geom is not None else QgsGeometry()
                if not fallback.isNull() and not fallback.isMultipart():
                    fallback.convertToMultiType()
                fixed_geom_by_fid[src_feat.id()] = fallback
                log_warning(
                    f"Fsm_1_1_15: фича fid={src_feat.id()} слоя '{layer.name()}' "
                    f"не восстановлена (fixgeometries вернул пустую/невалидную "
                    f"геометрию) — перенесена как есть"
                )
                continue

            # Успешно исправлена. Снап per-geometry через M_6._round_geometry —
            # ПОСТ-fix re-validation (snap + второй makeValid[Linework] +
            # CollectionExtract ловит snap-induced/остаточную невалидность).
            snapped = CPM._round_geometry(raw_fixed)
            if snapped is None or snapped.isNull() or snapped.isEmpty():
                # M_6-fallback вернул нечто пустое (не ожидается — _round_geometry
                # fail-closed возвращает валидный вход). Подстраховка: сырой fix.
                snapped = raw_fixed
            # Промоция к MultiPolygon (fixgeometries обычно даёт MultiPolygon уже,
            # но snap/CollectionExtract может вернуть single Polygon).
            if not snapped.isMultipart():
                snapped.convertToMultiType()

            fixed_geom_by_fid[src_feat.id()] = snapped
            area_delta += abs(snapped.area() - src_area)

        # 2. Построить выходной MultiPolygon memory-слой В ИСХОДНОМ ПОРЯДКЕ фич.
        out_layer = QgsVectorLayer(
            f"MultiPolygon?crs={crs.authid()}" if crs.authid() else "MultiPolygon",
            layer.name(),
            "memory",
        )
        # FIX-1 (ISSUE-002): явный setCrs объектом CRS — возвращаемый наружу
        # out_layer обязан иметь СК даже для кастомной МСК USER CRS (пустой
        # authid). Без этого save_to_gpkg получил бы слой без СК.
        out_layer.setCrs(crs)
        out_provider = out_layer.dataProvider()
        out_provider.addAttributes(layer.fields())
        out_layer.updateFields()
        out_target_count = out_layer.fields().count()

        out_feats: List[QgsFeature] = []
        for feature in layer.getFeatures():
            new_feat = QgsFeature(out_layer.fields())

            if feature.id() in invalid_fids:
                # Невалидная (fixable): исправленная (снапнутая) либо fallback.
                out_geom = fixed_geom_by_fid.get(feature.id())
                if out_geom is None:
                    # Не должно случиться (все invalid_fids в карте) — fail-closed.
                    raise RuntimeError(
                        f"Fsm_1_1_15: отсутствует fix-результат для fid={feature.id()}"
                    )
            elif feature.id() in zm_skip_fids:
                # Z/M-невалидная (FIX-3 defensive skip): перенести как есть, БЕЗ
                # fix/snap — план §2/§6 исключает M/Z из fix. Промоция в Multi
                # (convertToMultiType сохраняет Z/M) для консистентности слоя.
                src_geom = feature.geometry()
                out_geom = QgsGeometry(src_geom) if src_geom is not None else QgsGeometry()
                if not out_geom.isNull() and not out_geom.isMultipart():
                    out_geom.convertToMultiType()
            else:
                # Валидная: verbatim-промоция в 1-частный MultiPolygon
                # (convertToMultiType — координатно-идентично, сохраняет Z/M/кривые;
                # НЕ проходит через fixgeometries → НЕ реструктурируется).
                src_geom = feature.geometry()
                out_geom = QgsGeometry(src_geom) if src_geom is not None else QgsGeometry()
                if not out_geom.isNull() and not out_geom.isMultipart():
                    out_geom.convertToMultiType()

            new_feat.setGeometry(out_geom)

            # Padding атрибутов до target.fields().count() (контрмера
            # addFeature-silent-loss при setAttributes короче target).
            src_attrs = list(feature.attributes())
            padded = src_attrs + [None] * (out_target_count - len(src_attrs))
            new_feat.setAttributes(padded)
            out_feats.append(new_feat)

        if not out_provider.addFeatures(out_feats):
            raise RuntimeError("Fsm_1_1_15: не удалось наполнить выходной слой")
        out_layer.updateExtents()

        # Счётчик fixed = число фич из invalid_fids, ставших валидными
        # (invalid - unfixable). НЕ len(errors). Z/M-skip учитываются отдельно
        # (zm_skipped), НЕ в fixed/unfixable. area_delta — только по fixed (FIX-6a).
        build_stats = {
            'fixed': len(invalid_fids) - len(unfixable_fids),
            'unfixable': len(unfixable_fids),
            'zm_skipped': len(zm_skip_fids),
            'area_delta': area_delta,
        }

        log_info(
            f"Fsm_1_1_15: слой '{layer.name()}' — исправлено "
            f"{build_stats['fixed']}/{len(invalid_fids)}, "
            f"неисправимо {build_stats['unfixable']}, "
            f"Z/M-skip {build_stats['zm_skipped']}, "
            f"дельта площади {area_delta:.4f} м²"
        )

        return out_layer, build_stats
