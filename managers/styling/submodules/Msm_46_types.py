# -*- coding: utf-8 -*-
"""
Msm_46_types: Value objects для M_46 LegendManager.

Immutable dataclasses используемые в content collection, space calculation,
layout planning и placement strategy. Выделены в отдельный модуль для
избежания циклических импортов между субами (Msm_46_2, Msm_46_3, Msm_46_4)
и координатором M_46.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class LegendItem:
    """Один слой в легенде: имя слоя и отображаемое название."""
    layer_name: str
    title: str


@dataclass(frozen=True)
class LegendContent:
    """Содержимое легенды (результат M_46._collect_content)."""
    items: List[LegendItem] = field(default_factory=list)

    @property
    def count(self) -> int:
        """Количество элементов легенды."""
        return len(self.items)


@dataclass(frozen=True)
class AvailableSpace:
    """Доступная область для легенды (результат Msm_46_2.calculate)."""
    max_width_mm: float
    max_height_mm: float
    legend_anchor_x: float
    legend_anchor_y: float
    legend_ref_point: int


@dataclass(frozen=True)
class SpaceBoundaries:
    """
    Геометрические границы соседних overlay-элементов относительно legend_anchor.

    Промежуточный результат расчёта позиций overview_map / north_arrow /
    title_label внутри Msm_46_2. Используется для передачи геометрии между
    этапами calculate() до формирования финального AvailableSpace.

    None в поле означает "нет соответствующего соседа" (fallback на page margin).
    """
    left_edge_right_neighbour_mm: Optional[float] = None
    top_edge_above_neighbour_mm: Optional[float] = None
    page_right_margin_mm: Optional[float] = None
    page_top_margin_mm: Optional[float] = None


@dataclass(frozen=True)
class LegendPlan:
    """План размещения легенды (результат Msm_46_3.plan)."""
    mode: str  # 'inline' | 'overflow' — см. PlacementMode
    wrap_length: int
    column_count: int
    symbol_width: float
    symbol_height: float
    predicted_width_mm: float
    predicted_height_mm: float
    reason: Optional[str] = None


@dataclass(frozen=True)
class LegendResult:
    """Результат применения плана (возврат M_46.plan_and_apply)."""
    success: bool
    mode_applied: str
    width_mm: float
    height_mm: float
    warning: Optional[str] = None


class PlacementMode:
    """
    Строковые константы режимов размещения легенды.

    Используются в LegendPlan.mode и Base_layout поле legend_placement_mode.
    Класс без dataclass — контейнер enum-like констант (проект использует
    строки для совместимости с Base_layout JSON, не IntEnum/StrEnum).
    """
    INLINE = 'inline'
    OVERFLOW = 'overflow'

    ALL: Tuple[str, ...] = (INLINE, OVERFLOW)

    @classmethod
    def is_valid(cls, mode: str) -> bool:
        """Проверить что mode — поддерживаемый режим размещения."""
        return mode in cls.ALL
