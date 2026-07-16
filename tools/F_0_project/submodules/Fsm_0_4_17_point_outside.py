# -*- coding: utf-8 -*-
"""
Fsm_0_4_17: Whole-project детектор точек нарезки вне границ работ (класс D).

КОНТЕКСТ (план F_0_4 2026-06-16, класс D):
Лаконичный прокси для «точка стыка полигонов ЗПР вышла за пределы ЗУ из-за
округления». Вместо анализа оснований границ работ — простое правило: точки
слоёв Т_* должны лежать внутри L_1_1_1_Границы_работ. Вылет наружу = ошибка
(порождает «спицу»). Строго, без допуска (вылеты субсантиметровые).

SCOPE: ВСЕ точечные Т_-слои (маркер: geometry_type точка + '_Т_' в full_name).
Эталон: L_1_1_1_Границы_работ (единственный, без буфера L_1_1_3).

АРХИТЕКТУРА (INV-2): все Т_-слои имеют topology_check=0 → в per-layer pipeline
НЕ попадают. Класс D реализуется в whole-project фазе (вместе с C/E), которая
сама собирает Т_-слои по маркеру независимо от topology_check.

Тип ошибки: 'point_outside_workarea'. Индикатор, НЕ fixable.
Точка-маркер = сама точка Т_ (M_9 не нужен, DEF-план).
"""

from typing import List, Dict, Any

from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer, QgsGeometry
)

from Daman_QGIS.utils import log_info, log_warning, log_error
from .._topology_geom_utils import get_workarea_geometry


class Fsm_0_4_17_PointOutsideChecker:
    """Whole-project детектор точек Т_-слоёв вне L_1_1_1_Границы_работ.

    Собирает все точечные Т_-слои проекта по маркеру, грузит эталон
    L_1_1_1_Границы_работ один раз, проверяет каждую точку на intersects.
    """

    # Маркер точечного слоя нарезки в full_name.
    POINT_MARKER = "_Т_"

    def __init__(self):
        """Инициализация: справочник Base_layers для маркеров слоёв."""
        from Daman_QGIS.managers import get_reference_managers
        ref_manager = get_reference_managers()
        self._layers_meta: Dict[str, Dict[str, Any]] = {}
        try:
            for layer_data in ref_manager.layer.get_base_layers():
                full_name = layer_data.get('full_name')
                if full_name:
                    self._layers_meta[full_name] = layer_data
        except Exception as e:
            log_error(f"Fsm_0_4_17: не удалось загрузить Base_layers: {e}")

    def check(self) -> List[Dict[str, Any]]:
        """Whole-project проверка точек нарезки вне границ работ.

        Returns:
            Список ошибок типа 'point_outside_workarea'.
        """
        errors: List[Dict[str, Any]] = []

        workarea = get_workarea_geometry()
        if workarea is None:
            log_info(
                "Fsm_0_4_17: эталон L_1_1_1_Границы_работ отсутствует/пуст, "
                "класс D пропущен"
            )
            return errors

        point_layers = self._collect_point_layers()
        if not point_layers:
            log_info(
                "Fsm_0_4_17: точечных Т_-слоёв в проекте не найдено, "
                "класс D пропущен"
            )
            return errors

        for layer in point_layers:
            errors.extend(self._check_layer(layer, workarea))

        return errors

    def _collect_point_layers(self) -> List[QgsVectorLayer]:
        """Точечные Т_-слои проекта (geometry_type точка + '_Т_' в имени).

        Returns:
            Список валидных точечных QgsVectorLayer.
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
            if layer.geometryType() != Qgis.GeometryType.Point:
                continue
            if self.POINT_MARKER not in layer.name():
                continue
            result.append(layer)
        log_info(
            f"Fsm_0_4_17: точечных Т_-слоёв для проверки: {len(result)}"
        )
        return result

    def _check_layer(
        self, layer: QgsVectorLayer, workarea: QgsGeometry
    ) -> List[Dict[str, Any]]:
        """Проверка точек одного слоя на попадание внутрь границ работ.

        Точки хранятся как MultiPoint — перебор отдельных точек через
        asMultiPoint() / asPoint() (конвенция CLAUDE.md).

        Returns:
            Список ошибок 'point_outside_workarea' для точек вне границ.
        """
        errors: List[Dict[str, Any]] = []
        outside_count = 0

        for feat in layer.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isNull() or geom.isEmpty():
                continue

            if geom.isMultipart():
                points = geom.asMultiPoint()
            else:
                pt = geom.asPoint()
                points = [pt] if pt is not None else []

            multipoint = len(points) > 1
            for i, point in enumerate(points):
                point_geom = QgsGeometry.fromPointXY(point)
                # not intersects → точка вне границ работ (строго, без допуска).
                if workarea.intersects(point_geom):
                    continue
                outside_count += 1
                # У MultiPoint-фичи N точек делят один feature_id — добавляем
                # индекс точки внутри фичи, чтобы различить какая вылетела
                # (ISSUE-002). Одиночная точка — без индекса.
                point_ref = f', точка {i}' if multipoint else ''
                errors.append({
                    'type': 'point_outside_workarea',
                    'geometry': point_geom,
                    'feature_id': feat.id(),
                    'point_index': i,
                    'description': (
                        f'Точка нарезки вне границ работ: слой {layer.name()}, '
                        f'объект {feat.id()}{point_ref}'
                    ),
                })

        if outside_count > 0:
            log_warning(
                f"Fsm_0_4_17: слой '{layer.name()}' — точек вне границ работ: "
                f"{outside_count}"
            )
        return errors
