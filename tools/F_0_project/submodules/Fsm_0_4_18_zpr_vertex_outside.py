# -*- coding: utf-8 -*-
"""
Fsm_0_4_18: Whole-project детектор вершин полигонов ЗПР вне границ работ
(класс A феномена «спицы»).

КОНТЕКСТ (план F_0_4 «спицы» 2026-07-10, класс A):
Спица = узкий краевой фрагмент у стыка полигонов ЗПР. ПРИЧИНА: вершина
полигона ЗПР лежит ВНЕ границ работ L_1_1_1 (чаще всего точка стыка 2+
полигонов ЗПР, вынесенная наружу при округлении/оцифровке). ЗПР ⊆ границы
работ ВСЕГДА (свойство модели данных — границы работ жёсткий ограничитель).

Класс A ловит ПРИЧИНУ (вершина ЗПР вне границ) ДО нарезки, чтобы оператор
подвинул точку внутрь. Следствия той же причины ловят класс D (Т_-точка
вне границ, Fsm_0_4_17) и класс C (краевой sliver, Fsm_0_4_16). Три маркера
на одну спицу — НАМЕРЕННО (разные сущности: причина + 2 следствия), НЕ
дедупятся (решение владельца).

ИСТОЧНИК: полигональные слои ЗПР — group IN ("ЗПР","ЗПР_РЕК") по Base_layers
(L_1_12_* / L_1_13_*). Независимый сбор через get_reference_managers()
(как Fsm_0_4_17) — сбор класса C (Fsm_0_4_16) НЕ переиспользуется (OPT-001:
регресс-риск класса C дороже экономии дубля).

ЭТАЛОН: L_1_1_1_Границы_работ через общий get_workarea_geometry()
(_topology_geom_utils, тот же эталон что у класса D).

ПРАВИЛО: для КАЖДОЙ вершины КАЖДОГО кольца (exterior + holes) КАЖДОГО
полигона ЗПР: not workarea.intersects(vertex) → маркер. Строгий intersects
БЕЗ допуска (ловим микровылеты наружу, решение владельца) — intersects True
для точки внутри/на границе, False только для точки снаружи.

Тип ошибки: 'zpr_vertex_outside_workarea'. Индикатор, НЕ fixable.
Точка-маркер = сама вершина (M_9 не нужен, как класс D).
"""

from typing import List, Dict, Any

from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer, QgsGeometry
)

from Daman_QGIS.utils import log_info, log_warning, log_error
from .._topology_geom_utils import get_workarea_geometry


class Fsm_0_4_18_ZprVertexOutsideChecker:
    """Whole-project детектор вершин полигонов ЗПР вне L_1_1_1_Границы_работ.

    Собирает полигональные слои ЗПР проекта по маркеру Base_layers
    (group IN ЗПР/ЗПР_РЕК), грузит эталон границ работ один раз, проверяет
    каждую вершину каждого кольца каждого полигона на строгий intersects.
    """

    # Группы ЗПР-зон в Base_layers (L_1_12_* / L_1_13_*).
    ZPR_GROUPS = ("ЗПР", "ЗПР_РЕК")

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
            log_error(f"Fsm_0_4_18: не удалось загрузить Base_layers: {e}")

    def check(self) -> List[Dict[str, Any]]:
        """Whole-project проверка вершин ЗПР вне границ работ.

        Returns:
            Список ошибок типа 'zpr_vertex_outside_workarea'.
        """
        errors: List[Dict[str, Any]] = []

        workarea = get_workarea_geometry()
        if workarea is None:
            log_info(
                "Fsm_0_4_18: эталон L_1_1_1_Границы_работ отсутствует/пуст, "
                "класс A пропущен"
            )
            return errors

        zpr_layers = self._collect_zpr_polygon_layers()
        if not zpr_layers:
            log_info(
                "Fsm_0_4_18: полигональных слоёв ЗПР в проекте не найдено, "
                "класс A пропущен"
            )
            return errors

        for layer in zpr_layers:
            errors.extend(self._check_layer(layer, workarea))

        return errors

    def _collect_zpr_polygon_layers(self) -> List[QgsVectorLayer]:
        """Полигональные слои ЗПР проекта (group IN ЗПР/ЗПР_РЕК).

        Returns:
            Список валидных полигональных QgsVectorLayer групп ЗПР.
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
            if meta.get('group') not in self.ZPR_GROUPS:
                continue
            result.append(layer)
        log_info(
            f"Fsm_0_4_18: полигональных слоёв ЗПР для проверки: {len(result)}"
        )
        return result

    def _check_layer(
        self, layer: QgsVectorLayer, workarea: QgsGeometry
    ) -> List[Dict[str, Any]]:
        """Проверка вершин полигонов одного слоя ЗПР на попадание в границы.

        Обход: все части MultiPolygon → все кольца (exterior + holes) → все
        вершины. Замыкающая вершина кольца (дубликат первой) снимается через
        ring[:-1] (прецедент Fsm_1_1_3:393-395) — иначе двойной маркер на
        одной точке. Строгий intersects без допуска.

        Returns:
            Список ошибок 'zpr_vertex_outside_workarea' для вершин вне границ.
        """
        errors: List[Dict[str, Any]] = []
        outside_count = 0

        for feat in layer.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isNull() or geom.isEmpty():
                continue

            # Обход по СЫРОЙ геометрии БЕЗ makeValid (ISSUE-001 rev-code
            # реализации): makeValid спайкового полигона (isGeosValid==False —
            # а спица И ЕСТЬ самокасающийся/спайковый полигон) возвращает
            # GeometryCollection/LineString → asMultiPolygon()/asPolygon()
            # бросили бы TypeError → класс A аварийно выключался бы на всём
            # проекте, ровно на целевых данных. Для перебора вершин валидизация
            # НЕ нужна: вершины есть у любой геометрии, тип Polygon/MultiPolygon
            # на сырой сохраняется (эталон workarea валидизируется в util-loader).
            # Нормализация в список полигонов (все части MultiPolygon).
            if geom.isMultipart():
                polygons = geom.asMultiPolygon()
            else:
                polygon = geom.asPolygon()
                polygons = [polygon] if polygon else []

            # part_idx / ring_idx / vertex_idx — для различения вершин в
            # description (Analyst: индекс вершины в кольце).
            for part_idx, polygon in enumerate(polygons):
                # polygon = список колец: [0] exterior, [1:] holes.
                for ring_idx, ring in enumerate(polygon):
                    # Снимаем замыкающую вершину (дубликат первой).
                    if len(ring) > 1 and ring[0] == ring[-1]:
                        ring = ring[:-1]
                    for vertex_idx, point in enumerate(ring):
                        vertex_geom = QgsGeometry.fromPointXY(point)
                        # not intersects → вершина вне границ работ
                        # (строго, без допуска).
                        if workarea.intersects(vertex_geom):
                            continue
                        outside_count += 1
                        ring_ref = (
                            'внешнее кольцо' if ring_idx == 0
                            else f'внутреннее кольцо {ring_idx}'
                        )
                        errors.append({
                            'type': 'zpr_vertex_outside_workarea',
                            'geometry': vertex_geom,
                            'feature_id': feat.id(),
                            'part_index': part_idx,
                            'ring_index': ring_idx,
                            'vertex_index': vertex_idx,
                            'description': (
                                f'Вершина ЗПР вне границ работ: слой '
                                f'{layer.name()}, объект {feat.id()}, '
                                f'часть {part_idx}, {ring_ref}, '
                                f'вершина {vertex_idx}'
                            ),
                        })

        if outside_count > 0:
            log_warning(
                f"Fsm_0_4_18: слой '{layer.name()}' — вершин ЗПР вне границ "
                f"работ: {outside_count}"
            )
        return errors
