# -*- coding: utf-8 -*-
"""
Msm_46_utils: Shared helpers для работы с layout items.

Выделены в отдельный модуль для устранения дублирования find_legend /
find_main_map, которое воспроизводилось в ~4 местах (Msm_34_2,
M_46-субменеджеры, Fsm_1_4_5, Fsm_5_4_2).

numpad_to_offset — арифметический хелпер для конвертации numpad-нотации
ref_point (1-9) в смещение (dx, dy) от anchor до top-left. Другой домен
чем Msm_34_1._REF_POINTS (Qt enum для element anchoring) — не объединяется
(Chesterton's Fence, OPT-3 partial).
"""

from typing import Any, Dict, List, Optional, Tuple

from qgis.core import QgsPrintLayout, QgsLayoutItemLegend, QgsLayoutItemMap
from qgis.PyQt.QtGui import QFont


def parse_letter_spacing_pt(params: Dict[str, Any]) -> float:
    """Извлечь page-level `letter_spacing_pt` из Base_layout params.

    Принимает '-' / '' / None → 0.0 (default, no extra spacing).
    Безопасно к ошибкам конвертации: при ValueError/TypeError возвращает 0.0.

    Используется в Msm_46_3 (planner — для font_metrics в wrap_text)
    и Msm_34_1 (layout_builder — для font'ов label-элементов). Обеспечивает
    единое чтение глобального параметра letter-spacing.
    """
    raw = params.get('letter_spacing_pt')
    if raw is None or raw in ('', '-'):
        return 0.0
    try:
        return float(raw)
    except (ValueError, TypeError):
        return 0.0


def apply_letter_spacing_to_font(font: QFont, letter_spacing_pt: float) -> None:
    """Применить letter-spacing (pt) к QFont (in-place).

    ВАЖНО: используется ТОЛЬКО QFont.AbsoluteSpacing. PercentageSpacing
    ломает QGIS legend renderer — даже значение 100% (Qt-семантически
    no-op) приводит к character-wrap всего текста через layout.
    AbsoluteSpacing 0 — Qt-default, безопасный no-op.

    letter_spacing_pt:
    -  0.0  → AbsoluteSpacing 0 (default, no extra spacing)
    - <0.0  → compress букв (например -1.0 = -1pt после каждой буквы)
    - >0.0  → expand букв (редко нужно)

    Вызывают: Msm_34_1 (для font label'ов) и Msm_46_4 (для font'ов
    QgsLegendStyle стилей легенды).
    """
    font.setLetterSpacing(QFont.AbsoluteSpacing, letter_spacing_pt)


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


def is_layer_hidden_from_print(layer_name: str) -> bool:
    """
    Проверить, помечен ли слой как "скрыт от печати" (not_print=1 в Base_layers).

    Аналог логики DxfExporter (layer_info.get('not_print') == 1), применимый
    к темам макетов и легендам. Используется в F_1_4 (Fsm_1_4_5), F_5_4
    (F_5_4_master_plan, Fsm_5_4_2) для исключения таких слоёв из
    main_map / overview_map / легенды.

    Источник истины — Base_layers.json через M_10 (layers_db). Если слоя нет
    в Base_layers (OSM/динамические подложки и т.п.) — считаем не скрытым
    (разрешён к печати), это нормальная ситуация.

    Args:
        layer_name: Полное имя слоя (например 'Le_1_2_8_11_Ген_План_Рекреац').

    Returns:
        True если в Base_layers найдена запись с full_name == layer_name и
        not_print == 1. Иначе False (включая случай, когда M_10 не
        зарегистрирован или слоя нет в Base_layers).
    """
    # Импорт лениво чтобы избежать циклов (registry -> styling -> registry)
    from Daman_QGIS.managers import registry
    m10 = registry.get('M_10')
    if m10 is None:
        return False
    layers_db = getattr(m10, 'layers_db', None)
    if not layers_db:
        return False
    for entry in layers_db:
        if entry.get('full_name') == layer_name:
            value = entry.get('not_print', 0)
            try:
                return int(str(value).strip() or 0) == 1
            except (ValueError, TypeError):
                return False
    return False


def filter_print_visible(
    layer_names: List[str],
) -> Tuple[List[str], List[str]]:
    """
    Отфильтровать список имён слоёв, оставив только разрешённые к печати.

    Применяется к спискам слоёв для тем макетов (main_map, overview_map) и
    легенд. Слои с not_print=1 из Base_layers исключаются. Порядок visible
    сохраняется.

    Args:
        layer_names: Список полных имён слоёв (в любом порядке).

    Returns:
        Tuple (visible, hidden):
            visible — имена, разрешённые к печати (сохранён исходный порядок).
            hidden  — имена, помеченные not_print=1 (для логирования вызывающей
            стороной).
    """
    visible: List[str] = []
    hidden: List[str] = []
    for name in layer_names:
        if is_layer_hidden_from_print(name):
            hidden.append(name)
        else:
            visible.append(name)
    return visible, hidden
