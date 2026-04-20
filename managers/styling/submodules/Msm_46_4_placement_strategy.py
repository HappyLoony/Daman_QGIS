# -*- coding: utf-8 -*-
"""
Msm_46_4: PlacementStrategy — Применение LegendPlan к макету.

Strategy pattern:
- InlinePlacement — применяет план к QgsLayoutItemLegend на текущем листе
- OverflowPlacement — STUB v1 (OPT-4 consensus): логирует warning,
  делегирует InlinePlacement. Архитектурно готов под v2 Atlas (отдельный лист).

OPT-2 consensus: find_legend переиспользуется из Msm_46_utils,
не дублируется внутри ABC.

Используется: M_46_legend_manager.py
"""

from abc import ABC, abstractmethod
from typing import Optional

from qgis.core import QgsLayoutItemLegend, QgsPrintLayout

from Daman_QGIS.utils import log_info, log_warning
from .Msm_46_3_layout_planner import LayoutPlanner
from .Msm_46_types import LegendPlan, LegendResult, PlacementMode
from .Msm_46_utils import find_legend

MODULE_ID = "Msm_46_4"


class PlacementStrategy(ABC):
    """Абстрактная стратегия применения LegendPlan к макету."""

    @abstractmethod
    def apply(
        self,
        layout: QgsPrintLayout,
        plan: LegendPlan,
    ) -> LegendResult:
        """
        Применить план к легенде в layout.

        Args:
            layout: макет содержащий QgsLayoutItemLegend с id='legend'
            plan: план из Msm_46_3 LayoutPlanner

        Returns:
            LegendResult с success/warning.
        """
        raise NotImplementedError


class InlinePlacement(PlacementStrategy):
    """Размещение легенды на том же листе с адаптивными параметрами."""

    def apply(
        self,
        layout: QgsPrintLayout,
        plan: LegendPlan,
    ) -> LegendResult:
        """
        Применить wrap + column_count + symbol к QgsLayoutItemLegend.

        Raises:
            Ничего — возвращает LegendResult(success=False) при отсутствии legend.
        """
        legend = find_legend(layout)
        if legend is None:
            log_warning(
                f"{MODULE_ID} InlinePlacement: legend item не найден в layout"
            )
            return LegendResult(
                success=False,
                mode_applied=PlacementMode.INLINE,
                width_mm=0.0,
                height_mm=0.0,
                warning='Legend item не найден',
            )

        self._apply_wrap_to_titles(legend, plan.wrap_length)
        self._apply_legend_params(legend, plan)

        log_info(
            f"{MODULE_ID} InlinePlacement: col={plan.column_count}, "
            f"wrap={plan.wrap_length}, "
            f"sym={plan.symbol_width}x{plan.symbol_height}"
        )

        return LegendResult(
            success=True,
            mode_applied=PlacementMode.INLINE,
            width_mm=plan.predicted_width_mm,
            height_mm=plan.predicted_height_mm,
            warning=plan.reason,  # tight_inline_may_overflow_visually и пр.
        )

    # === Helpers ===

    @staticmethod
    def _apply_wrap_to_titles(
        legend: QgsLayoutItemLegend,
        wrap_length: int,
    ) -> None:
        """
        Применить wrap_text к title каждого слоя в модели легенды.

        Использует LayoutPlanner.wrap_text (staticmethod). Читает текущий
        title из customProperty 'legend/title-label', fallback на layer.name().
        """
        model = legend.model()
        if model is None:
            return
        root = model.rootGroup()
        if root is None:
            return

        for node in root.children():
            layer_obj = getattr(node, 'layer', None)
            if layer_obj is None:
                continue
            try:
                layer = layer_obj() if callable(layer_obj) else layer_obj
            except Exception:
                continue
            if layer is None:
                continue

            current_title = node.customProperty("legend/title-label")
            if not current_title:
                try:
                    current_title = layer.name()
                except Exception:
                    current_title = ""

            if not current_title:
                continue

            wrapped = LayoutPlanner.wrap_text(current_title, wrap_length)
            node.setCustomProperty("legend/title-label", wrapped)

    @staticmethod
    def _apply_legend_params(
        legend: QgsLayoutItemLegend,
        plan: LegendPlan,
    ) -> None:
        """Применить column_count, symbol_width, symbol_height и refresh."""
        legend.setColumnCount(int(plan.column_count))
        legend.setSymbolWidth(float(plan.symbol_width))
        legend.setSymbolHeight(float(plan.symbol_height))
        # adjustBoxSize пересчитывает размер с учётом новых параметров
        if hasattr(legend, 'adjustBoxSize'):
            legend.adjustBoxSize()
        if hasattr(legend, 'refresh'):
            legend.refresh()


class OverflowPlacement(PlacementStrategy):
    """
    [STUB v1]: Вывод легенды на отдельный лист.

    OPT-4 consensus: 25-строчный stub как architectural readiness для v2
    Atlas. Сейчас логирует warning и делегирует InlinePlacement с
    максимально уплотнённым планом (визуально может overflow).
    В v2: создать вторую страницу макета, перенести легенду туда.
    """

    def apply(
        self,
        layout: QgsPrintLayout,
        plan: LegendPlan,
    ) -> LegendResult:
        log_warning(
            f"{MODULE_ID} OverflowPlacement: stub, fallback to InlinePlacement"
        )
        inline_result = InlinePlacement().apply(layout, plan)
        return LegendResult(
            success=inline_result.success,
            mode_applied='overflow_fallback_inline',
            width_mm=inline_result.width_mm,
            height_mm=inline_result.height_mm,
            warning='OverflowPlacement stub: fallback to inline tight',
        )


def choose_strategy(mode: str) -> PlacementStrategy:
    """
    Выбор PlacementStrategy по mode из LegendPlan.

    Args:
        mode: 'inline' или 'overflow' (см. PlacementMode).

    Raises:
        ValueError с префиксом Msm_46_4 для unknown mode.
    """
    if mode == PlacementMode.INLINE:
        return InlinePlacement()
    if mode == PlacementMode.OVERFLOW:
        return OverflowPlacement()
    raise ValueError(
        f"{MODULE_ID}: неизвестный placement mode '{mode}' "
        f"(допустимо: {PlacementMode.ALL})"
    )
