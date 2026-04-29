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
    """
    План размещения легенды (результат Msm_46_3.plan).

    Поля width_mm и height_max_mm пробрасываются из AvailableSpace в planner
    и используются strategy-классами Msm_46_4 (особенно FixedPanelPlacement,
    которому нужны явные размеры панели для clamp-resize при overflow).

    text_width_mm — фактическая ширина text-area (за вычетом symbol_width и
    внутренних margin'ов), используется для pixel-based wrap в стратегиях.
    """
    mode: str  # см. LegendLayoutMode (DYNAMIC | FIXED_PANEL | OUTSIDE)
    wrap_length: int
    column_count: int
    symbol_width: float
    symbol_height: float
    predicted_width_mm: float
    predicted_height_mm: float
    width_mm: float           # max ширина из AvailableSpace (пробрасывается planner-ом)
    height_max_mm: float      # max высота из AvailableSpace
    text_width_mm: float = 0.0  # ширина text-area (для pixel-based wrap_text в стратегиях)
    # Letter-spacing в pt (AbsoluteSpacing). 0 = default. <0 = compress букв.
    # Применяется к Title/Group/Subgroup/SymbolLabel в strategy через QFont.
    # ВАЖНО: AbsoluteSpacing, НЕ PercentageSpacing — последний ломает QGIS
    # legend renderer (character-wraps текст).
    letter_spacing_pt: float = 0.0
    reason: Optional[str] = None


@dataclass(frozen=True)
class LegendResult:
    """Результат применения плана (возврат M_46.plan_and_apply)."""
    success: bool
    mode_applied: str
    width_mm: float
    height_mm: float
    warning: Optional[str] = None


class LegendLayoutMode:
    """Режимы размещения легенды (Base_layout.legend_layout_mode).

    Используется в LegendPlan.mode и для маршрутизации в M_46.plan_and_apply.
    Класс без dataclass — контейнер enum-like констант (проект использует
    строки для совместимости с Base_layout JSON, не IntEnum/StrEnum).
    """
    DYNAMIC = 'dynamic'
    FIXED_PANEL = 'fixed_panel'
    OUTSIDE = 'outside'

    ALL: Tuple[str, ...] = (DYNAMIC, FIXED_PANEL, OUTSIDE)

    @classmethod
    def is_valid(cls, mode: str) -> bool:
        """Проверить что mode — поддерживаемый режим размещения."""
        return mode in cls.ALL
