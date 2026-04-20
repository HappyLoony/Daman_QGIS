# -*- coding: utf-8 -*-
"""
Msm_46_utils: Shared helpers для работы с layout items.

Выделены в отдельный модуль для устранения дублирования find_legend /
find_main_map, которое воспроизводилось в ~4 местах (Msm_34_2,
M_46-субменеджеры, Fsm_1_4_5, Fsm_6_6_2).

numpad_to_offset — арифметический хелпер для конвертации numpad-нотации
ref_point (1-9) в смещение (dx, dy) от anchor до top-left. Другой домен
чем Msm_34_1._REF_POINTS (Qt enum для element anchoring) — не объединяется
(Chesterton's Fence, OPT-3 partial).
"""

from typing import Optional, Tuple

from qgis.core import QgsPrintLayout, QgsLayoutItemLegend, QgsLayoutItemMap


def find_legend(
    layout: QgsPrintLayout,
    item_id: str = 'legend',
) -> Optional[QgsLayoutItemLegend]:
    """
    Найти QgsLayoutItemLegend в layout по id.

    Args:
        layout: макет печати QGIS
        item_id: id элемента легенды (default 'legend' — стандарт проекта)

    Returns:
        QgsLayoutItemLegend с указанным id, либо None если не найден.
    """
    for item in layout.items():
        if isinstance(item, QgsLayoutItemLegend) and item.id() == item_id:
            return item
    return None


def find_main_map(
    layout: QgsPrintLayout,
    item_id: str = 'main_map',
) -> Optional[QgsLayoutItemMap]:
    """
    Найти QgsLayoutItemMap в layout по id.

    Args:
        layout: макет печати QGIS
        item_id: id элемента карты (default 'main_map' — стандарт проекта)

    Returns:
        QgsLayoutItemMap с указанным id, либо None если не найден.
    """
    for item in layout.items():
        if isinstance(item, QgsLayoutItemMap) and item.id() == item_id:
            return item
    return None


def numpad_to_offset(
    ref_point: int,
    width: float,
    height: float,
) -> Tuple[float, float]:
    """
    Смещение (dx, dy) от anchor до top-left для numpad ref point 1-9.

    Numpad convention (совпадает с Base_layout):
        7=TopLeft    8=TopCenter    9=TopRight
        4=MiddleLeft 5=Center       6=MiddleRight
        1=BottomLeft 2=BottomCenter 3=BottomRight

    Возвращает offset, который нужно прибавить к anchor (x, y) чтобы получить
    координаты top-left элемента шириной width и высотой height.

    Args:
        ref_point: numpad-нотация 1-9
        width: ширина элемента в мм
        height: высота элемента в мм

    Returns:
        Tuple (dx, dy) в мм. Unknown ref_point → (0, 0) без исключения
        (fallback на TopLeft для отказоустойчивости).
    """
    factors = {
        7: (0.0, 0.0), 8: (0.5, 0.0), 9: (1.0, 0.0),
        4: (0.0, 0.5), 5: (0.5, 0.5), 6: (1.0, 0.5),
        1: (0.0, 1.0), 2: (0.5, 1.0), 3: (1.0, 1.0),
    }
    fx, fy = factors.get(ref_point, (0.0, 0.0))
    return (-fx * width, -fy * height)
