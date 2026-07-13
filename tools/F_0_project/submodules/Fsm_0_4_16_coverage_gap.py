# -*- coding: utf-8 -*-
"""
Fsm_0_4_16: Whole-project детектор зазоров покрытия нарезки (класс C) и
многоконтурных образуемых ЗУ (класс E).

КОНТЕКСТ (план F_0_4 2026-06-16, INV-3 / класс C / класс E):
Зазор покрытия — МЕЖСЛОЙНЫЙ феномен: если просуммировать все полигоны нарезки
одного типа внутри зоны планируемого размещения (ЗПР) этого типа, оставшиеся
дырки = ошибки. Внутрислойный envelope-diff (бывший метод 2 Fsm_0_4_14) давал
ложные срабатывания и вынесен сюда.

Класс C — «Зазор покрытия нарезки» (тип 'coverage_gap'):
  Для каждого типа ЗПР: difference(ЗПР-зона типа, unaryUnion(полигоны нарезки
  этого типа)). Остаток внутри зоны работ = зазоры.

Класс E — «Многоконтурный образуемый ЗУ» (тип 'multipart_geometry'):
  Полигон слоя нарезки ОБРАЗУЮЩЕГО подтипа (Раздел/НГС/ПС) с numGeometries() > 1.
  Исключены Изм / Без_Меж (легитимно многоконтурны).

АРХИТЕКТУРА (INV-2): запускается СИНХРОННОЙ whole-project фазой из
F_0_4._check_async_completion (после сбора per-layer результатов), НЕ как
async-task с layer_id. union/difference/intersects — чистый PyQGIS, thread-safe
sequential не требуется.

МАРКЕР ТОЧКИ (M_9): точка внутри зазора/полигона-нарушителя через
AnchorPointManager.anchor_point(geom, "surface"). На None → skip + log_warning.

ФИЛЬТР ОПЕРАНДОВ (INV-3, Base_layers 2026-06-21):
  Нарезка: section=="Нарезка" AND geometry_type содержит "Polygon"
           AND group NOT IN ("Изъятие", "КЛ").
  Тип ЗПР — по суффиксу full_name после "_ЗПР_".
"""

from typing import List, Dict, Any, Optional, Set, Tuple

from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer, QgsGeometry, QgsPointXY
)

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers.geometry import AnchorPointManager


class Fsm_0_4_16_CoverageGapChecker:
    """Whole-project детектор зазоров покрытия нарезки (C) и многоконтурности (E).

    Собирает слои нарезки и ЗПР-зоны из проекта по маркерам Base_layers,
    строит union нарезки по типу, вычитает из ЗПР → зазоры (класс C);
    отдельно проверяет образующие подтипы на многоконтурность (класс E).
    """

    # Минимальная площадь зазора для отсечения шума float-арифметики (м²).
    # Наследовано из Fsm_0_4_14 (INV-5). MAX-порог намеренно НЕ вводится.
    MIN_GAP_AREA = 0.0001

    # Секция слоёв нарезки в Base_layers.
    SECTION_NAREZKA = "Нарезка"

    # Группы, исключаемые из набора операндов union (INV-3, N1).
    EXCLUDED_GROUPS = ("Изъятие", "КЛ")

    # Образующие подтипы для класса E (последний индекс sublayer, N3):
    # _1=Раздел, _2=НГС, _4=ПС. Исключены _3=Без_Меж, _5=Изм.
    GENERATING_SUBTYPE_SUFFIXES = ("_1", "_2", "_4")

    # Маркер разделителя типа в full_name ЗПР-зоны и слоя нарезки.
    ZPR_MARKER = "_ЗПР_"

    def __init__(self):
        """Инициализация: справочник Base_layers для маркеров слоёв."""
        from Daman_QGIS.managers import get_reference_managers
        ref_manager = get_reference_managers()
        # full_name -> layer_data dict из Base_layers.json
        self._layers_meta: Dict[str, Dict[str, Any]] = {}
        try:
            for layer_data in ref_manager.layer.get_base_layers():
                full_name = layer_data.get('full_name')
                if full_name:
                    self._layers_meta[full_name] = layer_data
        except Exception as e:
            log_error(f"Fsm_0_4_16: не удалось загрузить Base_layers: {e}")

    def check(
        self,
        invalid_edges_global: Optional[QgsGeometry] = None
    ) -> List[Dict[str, Any]]:
        """Whole-project проверка зазоров покрытия (C) и многоконтурности (E).

        Args:
            invalid_edges_global: unaryUnion всех edge_geometry из per-layer
                класса A (coverage_invalid_edge) по слоям нарезки (INV-4).
                gap-полигон, чья boundary пересекает эти edges, пропускается
                (A = primary). None → дедуп не применяется.

        Returns:
            Список ошибок типов 'coverage_gap' (C) и 'multipart_geometry' (E).
        """
        errors: List[Dict[str, Any]] = []

        # Собираем полигональные слои нарезки проекта (операнды union).
        narezka_layers = self._collect_narezka_polygon_layers()
        if not narezka_layers:
            log_info(
                "Fsm_0_4_16: полигональных слоёв нарезки в проекте не найдено, "
                "пропуск классов C/E"
            )
            return errors

        # Класс C: зазоры покрытия по типам ЗПР. Изолированный try: аномалия
        # одного типа ЗПР не должна обнулять класс E (многоконтурность).
        try:
            errors.extend(
                self._check_coverage_gaps(narezka_layers, invalid_edges_global)
            )
        except Exception as e:
            log_error(f"Fsm_0_4_16: Ошибка класса C (зазоры покрытия): {e}")

        # Класс E: многоконтурность образующих подтипов. Изолированный try:
        # падение E не должно терять уже собранные зазоры класса C.
        try:
            errors.extend(self._check_multipart(narezka_layers))
        except Exception as e:
            log_error(f"Fsm_0_4_16: Ошибка класса E (многоконтурность): {e}")

        return errors

    # --- Сбор слоёв ---

    def _collect_narezka_polygon_layers(self) -> List[QgsVectorLayer]:
        """Полигональные слои нарезки проекта (section=='Нарезка', Polygon,
        group NOT IN Изъятие/КЛ).

        Returns:
            Список QgsVectorLayer, присутствующих в проекте и валидных.
        """
        result: List[QgsVectorLayer] = []
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            try:
                if not layer.isValid():
                    continue
            except RuntimeError:
                continue
            if layer.geometryType() != Qgis.GeometryType.Polygon:
                continue
            meta = self._layers_meta.get(layer.name())
            if meta is None:
                continue
            if meta.get('section') != self.SECTION_NAREZKA:
                continue
            if meta.get('group') in self.EXCLUDED_GROUPS:
                continue
            result.append(layer)
        log_info(
            f"Fsm_0_4_16: полигональных слоёв нарезки для проверки: {len(result)}"
        )
        return result

    def _collect_zpr_zones(self) -> Dict[str, QgsVectorLayer]:
        """ЗПР-зоны проекта, keyed по типу (суффикс full_name после '_ЗПР_').

        Returns:
            {тип: слой} (например {'ПО': L_1_12_2_ЗПР_ПО, 'РЕК_АД': ...}).
        """
        zones: Dict[str, QgsVectorLayer] = {}
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            try:
                if not layer.isValid():
                    continue
            except RuntimeError:
                continue
            meta = self._layers_meta.get(layer.name())
            if meta is None:
                continue
            group = meta.get('group')
            # ЗПР-зоны: group 'ЗПР' (L_1_12_*) или 'ЗПР_РЕК' (L_1_13_*).
            if group not in ("ЗПР", "ЗПР_РЕК"):
                continue
            zpr_type = self._extract_zpr_type(layer.name())
            if zpr_type:
                zones[zpr_type] = layer
        return zones

    @classmethod
    def _extract_zpr_type(cls, full_name: str) -> Optional[str]:
        """Тип ЗПР из full_name по суффиксу после '_ЗПР_'.

        'L_1_12_2_ЗПР_ПО'            -> 'ПО'
        'L_1_13_1_ЗПР_РЕК_АД'        -> 'РЕК_АД'
        'Le_2_1_2_2_НГС_ЗПР_ПО'      -> 'ПО'
        'Le_2_2_2_2_НГС_ЗПР_СЕТИ_ПО' -> 'СЕТИ_ПО'

        Returns:
            Строка типа либо None если маркер не найден.
        """
        idx = full_name.find(cls.ZPR_MARKER)
        if idx < 0:
            return None
        suffix = full_name[idx + len(cls.ZPR_MARKER):]
        return suffix if suffix else None

    # --- Класс C: зазоры покрытия ---

    def _check_coverage_gaps(
        self,
        narezka_layers: List[QgsVectorLayer],
        invalid_edges_global: Optional[QgsGeometry]
    ) -> List[Dict[str, Any]]:
        """Класс C: difference(ЗПР типа, union нарезки типа) → зазоры.

        Args:
            narezka_layers: полигональные слои нарезки проекта.
            invalid_edges_global: union edges класса A для дедупа A↔C.

        Returns:
            Список ошибок типа 'coverage_gap'.
        """
        errors: List[Dict[str, Any]] = []

        zpr_zones = self._collect_zpr_zones()
        if not zpr_zones:
            log_info("Fsm_0_4_16: ЗПР-зон в проекте не найдено, класс C пропущен")
            return errors

        # Группируем полигоны нарезки по типу ЗПР (суффикс full_name).
        # Этапность (Le_2_7_3_* Итог, tc=0) относится к типу ОКС (план Q3).
        geoms_by_type: Dict[str, List[QgsGeometry]] = {}
        # Все типы операндов, встреченные в проекте (для диагностики
        # рассогласования операнды↔ЗПР-зоны, ISSUE-003).
        operand_types: Set[str] = set()
        for layer in narezka_layers:
            zpr_type = self._narezka_layer_zpr_type(layer.name())
            if not zpr_type:
                continue
            operand_types.add(zpr_type)
            if zpr_type not in zpr_zones:
                # Нет соответствующей ЗПР-зоны в проекте — тип зазоров этого
                # типа не будет проверен. Диагностируем, чтобы пропуск не был
                # немым (ISSUE-003, случай а: операнды есть, зоны нет).
                log_warning(
                    f"Fsm_0_4_16: собраны операнды нарезки типа '{zpr_type}' "
                    f"(слой '{layer.name()}'), но ЗПР-зоны типа '{zpr_type}' "
                    "в проекте нет — зазоры этого типа не проверяются"
                )
                continue
            geoms = self._extract_valid_geometries(layer)
            if geoms:
                geoms_by_type.setdefault(zpr_type, []).extend(geoms)

        for zpr_type, zpr_layer in zpr_zones.items():
            operands = geoms_by_type.get(zpr_type)
            if not operands:
                # ЗПР-зона есть, но операндов нарезки этого типа нет — зазоры
                # для этого типа не проверяются. Диагностируем (ISSUE-003,
                # случай б: зона есть, операндов нет).
                if zpr_type not in operand_types:
                    log_warning(
                        f"Fsm_0_4_16: ЗПР-зона типа '{zpr_type}' "
                        f"(слой '{zpr_layer.name()}') присутствует, но операндов "
                        "нарезки этого типа в проекте нет — зазоры не проверяются"
                    )
                continue
            errors.extend(
                self._gaps_for_type(
                    zpr_type, zpr_layer, operands, invalid_edges_global
                )
            )

        return errors

    def _narezka_layer_zpr_type(self, full_name: str) -> Optional[str]:
        """Тип ЗПР для слоя нарезки.

        Обычные слои нарезки несут '_ЗПР_<ТИП>' в full_name. Слои этапности
        (Итог, group 'Этапность', имена вида Le_2_7_3_1_Раздел_Итог) относятся
        к типу ОКС (план Q3, ЗПР_ОКС).

        Returns:
            Тип ЗПР либо None.
        """
        meta = self._layers_meta.get(full_name)
        if meta is not None and meta.get('group') == "Этапность":
            # Только слой Итог (tc=0) участвует; этапы 1/2 покрыты дедупом A↔C.
            # Все образующие подтипы этапности → ЗПР_ОКС.
            # Матч по каноническим полям Base_layers (layer=='Итог',
            # sublayer оканчивается на 'Итог': 'Раздел_Итог'/'НГС_Итог'/...),
            # НЕ по подстроке в full_name (ISSUE-001: 'Итог' в описательной
            # части имени вне этапности дал бы ложный ОКС-операнд).
            if self._is_stage_total(meta):
                return "ОКС"
            return None
        return self._extract_zpr_type(full_name)

    @staticmethod
    def _is_stage_total(meta: Dict[str, Any]) -> bool:
        """Слой этапности — итоговый (group 'Этапность', слой Итог).

        Канонический признак: поле layer == 'Итог' ИЛИ sublayer оканчивается
        на 'Итог' (endswith-якорь на конце имени, не подстрока).

        Returns:
            True для итогового слоя этапности, False иначе.
        """
        layer_name = meta.get('layer')
        if isinstance(layer_name, str) and layer_name == "Итог":
            return True
        sublayer = meta.get('sublayer')
        if isinstance(sublayer, str) and sublayer.endswith("Итог"):
            return True
        return False

    def _gaps_for_type(
        self,
        zpr_type: str,
        zpr_layer: QgsVectorLayer,
        operands: List[QgsGeometry],
        invalid_edges_global: Optional[QgsGeometry]
    ) -> List[Dict[str, Any]]:
        """Зазоры для одного типа: difference(ЗПР, union операндов).

        Returns:
            Список ошибок 'coverage_gap' для данного типа.
        """
        errors: List[Dict[str, Any]] = []

        zpr_geom = self._collect_layer_union(zpr_layer)
        if zpr_geom is None or zpr_geom.isEmpty():
            log_warning(
                f"Fsm_0_4_16: ЗПР-зона '{zpr_layer.name()}' пуста/невалидна, "
                f"тип {zpr_type} пропущен"
            )
            return errors

        union_geom = QgsGeometry.unaryUnion(operands)
        if union_geom is None or union_geom.isEmpty():
            log_warning(
                f"Fsm_0_4_16: union нарезки типа {zpr_type} пуст, пропуск"
            )
            return errors
        if not union_geom.isGeosValid():
            union_geom = union_geom.makeValid()
            if union_geom is None or union_geom.isEmpty():
                log_warning(
                    f"Fsm_0_4_16: union нарезки типа {zpr_type} невалиден "
                    "после makeValid, пропуск"
                )
                return errors

        gap_space = zpr_geom.difference(union_geom)
        if gap_space is None or gap_space.isEmpty():
            log_info(
                f"Fsm_0_4_16: тип {zpr_type} — зазоров покрытия нет "
                "(полное покрытие ЗПР)"
            )
            return errors

        # Разбиваем на отдельные фрагменты-зазоры.
        if gap_space.isMultipart():
            gap_polygons = gap_space.asGeometryCollection()
        else:
            gap_polygons = [gap_space]

        skipped_small = 0
        skipped_dedup = 0

        for gap_geom in gap_polygons:
            if gap_geom is None or gap_geom.isNull() or gap_geom.isEmpty():
                continue
            if gap_geom.type() != Qgis.GeometryType.Polygon:
                continue

            area = gap_geom.area()
            if area < self.MIN_GAP_AREA:
                skipped_small += 1
                continue

            # Дедуп A↔C (INV-4): boundary зазора пересекает edges класса A → skip.
            if (invalid_edges_global is not None
                    and not invalid_edges_global.isEmpty()):
                boundary_abstract = gap_geom.constGet().boundary()
                if boundary_abstract is not None:
                    gap_boundary = QgsGeometry(boundary_abstract.clone())
                    if gap_boundary.intersects(invalid_edges_global):
                        skipped_dedup += 1
                        continue
                else:
                    # boundary не извлеклась — дедуп для этого зазора
                    # пропускается (fail-open: показываем зазор C, не теряем
                    # его). Логируем, чтобы пропуск дедупа не был немым
                    # (ISSUE-004: возможен двойной маркер A+C на этом месте).
                    log_warning(
                        f"Fsm_0_4_16: не удалось извлечь boundary зазора для "
                        f"дедупа A↔C (тип {zpr_type}, площадь {area:.4f} м2), "
                        "зазор показан без дедупа"
                    )

            # Точка-маркер ВНУТРИ зазора через M_9.
            anchor = AnchorPointManager.anchor_point(gap_geom, "surface")
            if anchor is None:
                log_warning(
                    f"Fsm_0_4_16: точка привязки зазора не получена "
                    f"(тип {zpr_type}, площадь {area:.4f} м2), маркер пропущен"
                )
                continue

            errors.append({
                'type': 'coverage_gap',
                'geometry': QgsGeometry.fromPointXY(anchor),
                'feature_id': -1,
                'description': (
                    f'Зазор покрытия нарезки: тип {zpr_type}, '
                    f'площадь {area:.4f} м2'
                ),
                'area': round(area, 4),
                'zpr_type': zpr_type,
            })

        if skipped_small > 0:
            log_info(
                f"Fsm_0_4_16: тип {zpr_type} — пропущено {skipped_small} "
                f"микро-зазоров (< {self.MIN_GAP_AREA} м2)"
            )
        if skipped_dedup > 0:
            log_info(
                f"Fsm_0_4_16: тип {zpr_type} — пропущено {skipped_dedup} "
                "зазоров (дедуп с классом A)"
            )

        return errors

    # --- Класс E: многоконтурность ---

    def _check_multipart(
        self, narezka_layers: List[QgsVectorLayer]
    ) -> List[Dict[str, Any]]:
        """Класс E: полигон образующего подтипа с numGeometries() > 1.

        Образующие подтипы: Раздел (_1), НГС (_2), ПС (_4). Исключены Без_Меж
        (_3), Изм (_5) — легитимно многоконтурны.

        Returns:
            Список ошибок типа 'multipart_geometry'.
        """
        errors: List[Dict[str, Any]] = []

        for layer in narezka_layers:
            if not self._is_generating_subtype(layer.name()):
                continue

            for feat in layer.getFeatures():
                geom = feat.geometry()
                if geom is None or geom.isNull() or geom.isEmpty():
                    continue

                abstract = geom.constGet()
                if abstract is None:
                    continue
                try:
                    num_parts = abstract.numGeometries()
                except Exception:
                    continue
                if num_parts <= 1:
                    continue

                # Точка-маркер на полигоне-нарушителе через M_9.
                anchor = AnchorPointManager.anchor_point(geom, "surface")
                if anchor is None:
                    log_warning(
                        f"Fsm_0_4_16: точка привязки многоконтурного не получена "
                        f"(слой '{layer.name()}', fid {feat.id()}), маркер пропущен"
                    )
                    continue

                errors.append({
                    'type': 'multipart_geometry',
                    'geometry': QgsGeometry.fromPointXY(anchor),
                    'feature_id': feat.id(),
                    'description': (
                        f'Многоконтурный образуемый ЗУ: слой {layer.name()}, '
                        f'объект {feat.id()}, контуров {num_parts}'
                    ),
                    'num_geometries': num_parts,
                })

        return errors

    def _is_generating_subtype(self, full_name: str) -> bool:
        """Слой относится к образующим подтипам (Раздел/НГС/ПС) по последнему
        индексу sublayer.

        Проверяет sublayer_num из Base_layers (последний индекс: 1/2/4) с
        fallback на разбор full_name, если поле отсутствует.

        Returns:
            True для образующих подтипов, False иначе (в т.ч. этапность —
            у неё многоконтурность контролируется иначе, вне scope E).
        """
        meta = self._layers_meta.get(full_name)
        # Этапность в scope E не входит (не образующие ЗУ подтипы напрямую).
        if meta is not None and meta.get('group') == "Этапность":
            return False
        sublayer_num = None
        if meta is not None:
            sublayer_num = meta.get('sublayer_num')
        if sublayer_num is not None:
            return str(sublayer_num) in ("1", "2", "4")
        # Fallback: предпоследний токен full_name перед описательной частью
        # ненадёжен; при отсутствии метаданных пропускаем (safe-default).
        return False

    # --- Геометрические помощники ---

    @staticmethod
    def _extract_valid_geometries(
        layer: QgsVectorLayer
    ) -> List[QgsGeometry]:
        """Валидные геометрии слоя (makeValid для невалидных, наследовано из
        Fsm_0_4_14 стр.225-230).

        Returns:
            Список QgsGeometry (копии), пустые/вырожденные отброшены.
        """
        geoms: List[QgsGeometry] = []
        for feat in layer.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isNull() or geom.isEmpty():
                continue
            if not geom.isGeosValid():
                geom = geom.makeValid()
                if geom is None or geom.isEmpty():
                    continue
            geoms.append(QgsGeometry(geom))
        return geoms

    def _collect_layer_union(
        self, layer: QgsVectorLayer
    ) -> Optional[QgsGeometry]:
        """unaryUnion всех валидных геометрий слоя.

        Returns:
            QgsGeometry union либо None если валидных геометрий нет.
        """
        geoms = self._extract_valid_geometries(layer)
        if not geoms:
            return None
        union_geom = QgsGeometry.unaryUnion(geoms)
        if union_geom is None or union_geom.isEmpty():
            return None
        if not union_geom.isGeosValid():
            union_geom = union_geom.makeValid()
            if union_geom is None or union_geom.isEmpty():
                return None
        return union_geom
