# -*- coding: utf-8 -*-
"""
Общие геометрические помощники whole-project фазы F_0_4.

Модуль-хелпер для чекеров топологии, НЕ импортирует чекеры (зависит только
от qgis.core + Daman_QGIS.utils) — избегает импортного цикла между
Fsm_0_4_17 (класс D) и Fsm_0_4_18 (класс A), которые оба используют общую
загрузку эталона границ работ (план F_0_4 «спицы» 2026-07-10, NEW-1).

Место расположения (NEW-1 / OPT-002): util-модуль в F_0_project/ (НЕ в
submodules/, НЕ экспорт из чекера) — экспорт из Fsm_0_4_17 ввёл бы ребро
связности Fsm_0_4_18 → Fsm_0_4_17 (чекер зависит от чекера), нарушая
развязку whole-project-чекеров.

Файл именуется с ведущим подчёркиванием (`_topology_geom_utils.py`) —
динамический __init__.py F_0_project матчит только `F_X_Y_*.py`, поэтому
этот модуль в авто-импорт не попадает (и не должен).
"""

from typing import List, Optional

from qgis.core import QgsProject, QgsVectorLayer, QgsGeometry

from Daman_QGIS.utils import log_info


# Имя эталонного слоя границ работ.
WORKAREA_LAYER = "L_1_1_1_Границы_работ"


def get_workarea_geometry() -> Optional[QgsGeometry]:
    """Union геометрий эталонного слоя L_1_1_1_Границы_работ.

    Общий эталон whole-project фазы F_0_4: класс D (точки нарезки вне границ,
    Fsm_0_4_17) и класс A (вершины ЗПР вне границ, Fsm_0_4_18) сверяют свои
    геометрии против одной и той же union-геометрии границ работ.

    Поведение (guard'ы наследованы дословно из прежнего
    Fsm_0_4_17._get_workarea_geometry, регресс класса D):
      - слой невалиден (isValid False или RuntimeError на удалённом слое) → None;
      - null/empty геометрии фич пропускаются;
      - невалидные геометрии чинятся через makeValid, вырожденные после — skip;
      - unaryUnion всех валидных геометрий, makeValid на невалидном union;
      - пустой набор / пустой union → None.

    Returns:
        QgsGeometry (валидная) либо None если слой отсутствует/пуст/невалиден.
    """
    for layer in QgsProject.instance().mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        if layer.name() != WORKAREA_LAYER:
            continue
        try:
            if not layer.isValid():
                return None
        except RuntimeError:
            return None

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

    return None
