# -*- coding: utf-8 -*-
"""
Msm_46_2: SpaceCalculator — Вычисление доступной области для легенды.

Из геометрии Base_layout (позиции overview_map, north_arrow, title_label,
appendix_label и т.д.) вычисляет max_width и max_height, доступные для
легенды. Учитывает ref_point каждого элемента (numpad 1-9).

config_provider (dependency injection для тестов): callable
`(config_key: str) -> dict | None`. В production — default provider
берёт через `registry.get('M_34').get_layout_config_by_key`.

legend_max_width НЕ хранится в Excel — вычисляется runtime из исходников
(legend_x, overview_map_x, overview_map_width, overlay_gap_mm). Data-driven
принцип: Excel = source для исходников, derived values = runtime.

OPT-3 consensus: numpad_to_offset переиспользуется из Msm_46_utils,
не дублируется.

Используется: M_46_legend_manager.py
"""

from typing import Any, Callable, Dict, Optional

from qgis.core import QgsPrintLayout

from Daman_QGIS.utils import log_info
from .Msm_46_types import AvailableSpace, SpaceBoundaries
from .Msm_46_utils import numpad_to_offset

MODULE_ID = "Msm_46_2"

# Ключи overlay-элементов в Base_layout для перебора
_OVERLAY_KEYS = (
    ('overview_map_x', 'overview_map_y',
     'overview_map_width', 'overview_map_height',
     'overview_map_ref_point'),
    ('north_arrow_x', 'north_arrow_y',
     'north_arrow_width', 'north_arrow_height',
     'north_arrow_ref_point'),
    ('title_label_x', 'title_label_y',
     'title_label_width', 'title_label_height',
     'title_label_ref_point'),
    ('appendix_label_x', 'appendix_label_y',
     'appendix_label_width', 'appendix_label_height',
     'appendix_label_ref_point'),
)


def _default_config_provider(config_key: str) -> Optional[Dict[str, Any]]:
    """Default provider: читает конфиг через M_34.get_layout_config_by_key."""
    from Daman_QGIS.managers import registry  # lazy: избегаем цикла при тестах
    layout_mgr = registry.get('M_34')
    if layout_mgr is None:
        return None
    return layout_mgr.get_layout_config_by_key(config_key)


class SpaceCalculator:
    """Расчёт доступной области для легенды из Base_layout config."""

    def __init__(
        self,
        config_provider: Optional[
            Callable[[str], Optional[Dict[str, Any]]]
        ] = None,
    ) -> None:
        """
        Args:
            config_provider: callable `(config_key) -> dict | None` для DI.
                Если None — используется default из M_34.
        """
        self._provider = config_provider or _default_config_provider

    def calculate(
        self,
        layout: QgsPrintLayout,
        config_key: str,
    ) -> AvailableSpace:
        """
        Вычислить AvailableSpace для легенды.

        Args:
            layout: Макет (не модифицируется, reserved для будущего расширения)
            config_key: Ключ Base_layout (например 'A4_landscape_DPT')

        Returns:
            AvailableSpace с max_width_mm, max_height_mm и anchor параметрами

        Raises:
            RuntimeError: config_key не найден в Base_layout.json
        """
        config = self._provider(config_key)
        if config is None:
            raise RuntimeError(
                f"{MODULE_ID}: config_key '{config_key}' не найден в Base_layout.json"
            )

        legend_x = float(config['legend_x'])
        legend_y = float(config['legend_y'])
        legend_ref = int(config['legend_ref_point'])
        gap = float(config.get('legend_overlay_gap_mm', 5))
        height_ratio = float(config.get('legend_max_height_ratio', 0.45))
        main_map_height = float(config['main_map_height'])

        # Y-диапазон легенды (ref_point=LowerLeft → bottom=legend_y)
        # По высоте легенда занимает до max_height_ratio * main_map_height вверх.
        # Для определения "overlay справа от легенды" нужно пересечение по Y.
        legend_bottom_y = legend_y
        legend_top_y = legend_y - main_map_height * height_ratio

        boundaries = self._compute_boundaries(
            config, legend_x, legend_top_y, legend_bottom_y
        )

        # max_width: ближайший overlay справа минус legend_x минус gap
        if boundaries.left_edge_right_neighbour_mm is not None:
            max_width = (
                boundaries.left_edge_right_neighbour_mm - legend_x - gap
            )
        else:
            page_width = float(config.get('page_width', 297))
            margin_right = float(config.get('margin_right_mm', 5))
            max_width = page_width - legend_x - margin_right

        max_height = main_map_height * height_ratio

        log_info(
            f"{MODULE_ID}: Доступно для легенды "
            f"{max_width:.0f}x{max_height:.0f} мм (config {config_key})"
        )

        return AvailableSpace(
            max_width_mm=max_width,
            max_height_mm=max_height,
            legend_anchor_x=legend_x,
            legend_anchor_y=legend_y,
            legend_ref_point=legend_ref,
        )

    def _compute_boundaries(
        self,
        config: Dict[str, Any],
        legend_x: float,
        legend_top_y: float,
        legend_bottom_y: float,
    ) -> SpaceBoundaries:
        """
        Собрать левую границу ближайшего overlay справа от legend_x.

        Overlay считается "справа от легенды" если:
        1. Его правая граница правее legend_x (left > legend_x)
        2. Его Y-диапазон пересекается с Y-диапазоном легенды
           (overlay_top < legend_bottom_y И overlay_bottom > legend_top_y)

        Второе условие исключает overlay'и сверху/снизу страницы
        (title_label, appendix_label, north_arrow в верхнем углу),
        которые не конкурируют с легендой по ширине.

        Из кандидатов берётся минимум левой границы — ближайший сосед,
        который ограничивает max_width.
        """
        right_candidates = []
        for x_key, y_key, w_key, h_key, ref_key in _OVERLAY_KEYS:
            bbox = self._item_bbox(
                config, x_key, y_key, w_key, h_key, ref_key
            )
            if bbox is None:
                continue
            # Условие 1: overlay справа от legend_x
            if bbox['left'] <= legend_x:
                continue
            # Условие 2: пересечение по Y с горизонтальной полосой легенды
            if bbox['top'] >= legend_bottom_y:
                continue
            if bbox['bottom'] <= legend_top_y:
                continue
            right_candidates.append(bbox['left'])

        nearest_right = min(right_candidates) if right_candidates else None

        return SpaceBoundaries(
            left_edge_right_neighbour_mm=nearest_right,
            top_edge_above_neighbour_mm=None,
            page_right_margin_mm=float(config.get('margin_right_mm', 5)),
            page_top_margin_mm=float(config.get('margin_top_mm', 5)),
        )

    def _item_bbox(
        self,
        config: Dict[str, Any],
        x_key: str,
        y_key: str,
        w_key: str,
        h_key: str,
        ref_key: str,
    ) -> Optional[Dict[str, float]]:
        """
        Вычислить bbox элемента в координатах страницы с учётом ref_point.

        Использует numpad_to_offset из Msm_46_utils (OPT-3 consensus).

        Returns:
            dict {'left', 'right', 'top', 'bottom'} в мм, либо None если
            ключи отсутствуют в config.
        """
        if x_key not in config or y_key not in config:
            return None
        if w_key not in config or h_key not in config:
            return None
        if ref_key not in config:
            return None

        x = float(config[x_key])
        y = float(config[y_key])
        w = float(config[w_key])
        h = float(config[h_key])
        ref = int(config[ref_key])

        # numpad_to_offset даёт (dx, dy) от anchor до top-left
        dx, dy = numpad_to_offset(ref, w, h)
        left = x + dx
        top = y + dy

        return {
            'left': left,
            'right': left + w,
            'top': top,
            'bottom': top + h,
        }
