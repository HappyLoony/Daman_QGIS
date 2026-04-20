# -*- coding: utf-8 -*-
"""
Msm_46_3: LayoutPlanner — Детерминированный подбор параметров легенды.

Алгоритм (без рендера QGIS, через QFontMetrics):
1. col=1 с максимально широким wrap
2. col=2, col=3 при необходимости
3. reduced symbols при необходимости
4. mode='overflow' если не fits (только если placement_mode='overflow'),
   иначе 'inline' + reason='tight_inline_may_overflow_visually'

wrap_text — перенос Fsm_1_4_5.wrap_legend_text, но max_length вычисляется
из available width (НЕ хардкод 100): `int(text_width / char_width_mm)`.

_predict_height — OPT-6 simplified: total / col_count. Полный greedy fill
simulation deferred до v2 (trigger: `legend/predict_mismatch_count` >10%).

Используется: M_46_legend_manager.py
"""

from typing import Any, Callable, Dict, List, Optional

from qgis.PyQt.QtGui import QFont, QFontMetrics

from Daman_QGIS.utils import log_info, log_warning
from .Msm_46_types import (
    AvailableSpace,
    LegendContent,
    LegendPlan,
    PlacementMode,
)

MODULE_ID = "Msm_46_3"

# Default symbol size (ГОСТ-совместимые значения)
DEFAULT_SYMBOL_WIDTH = 15.0
DEFAULT_SYMBOL_HEIGHT = 5.0
MAX_COLUMNS = 3

# Оценочный коэффициент: line_height_mm ≈ font_size_pt * LINE_HEIGHT_MM_PER_PT
# 14pt ≈ 5.6 мм с учётом QGIS legend internal padding
LINE_HEIGHT_MM_PER_PT = 0.4
LEGEND_TITLE_HEIGHT_MM = 7.0  # "Условные обозначения:" заголовок
LEGEND_PADDING_MM = 3.0       # отступ внутри рамки легенды
INTER_ITEM_SPACING_MM = 2.0   # межстрочный интервал между items
DEFAULT_CHAR_WIDTH_MM = 2.5   # fallback для 14pt GOST 2.304
DEFAULT_FONT_SIZE_PT = 14


def _default_config_provider(config_key: str) -> Optional[Dict[str, Any]]:
    """Default provider: читает конфиг через M_34.get_layout_config_by_key."""
    from Daman_QGIS.managers import registry  # lazy
    layout_mgr = registry.get('M_34')
    if layout_mgr is None:
        return None
    return layout_mgr.get_layout_config_by_key(config_key)


class LayoutPlanner:
    """Детерминированный планнер параметров легенды."""

    def __init__(
        self,
        config_provider: Optional[
            Callable[[str], Optional[Dict[str, Any]]]
        ] = None,
    ) -> None:
        """
        Args:
            config_provider: DI callable `(config_key) -> dict | None`.
                Если None — default provider через M_34.
        """
        self._provider = config_provider or _default_config_provider

    @staticmethod
    def wrap_text(text: str, max_length: int) -> str:
        """
        Разбить text на строки через \\n, длина каждой <= max_length символов.

        Разбивает по словам. Слово длиннее max_length остаётся на своей строке
        как есть (не режется посимвольно).

        Перенос из Fsm_1_4_5.wrap_legend_text, но max_length — параметр
        (вычисляется из available width), не хардкод 100.

        Args:
            text: исходный текст
            max_length: максимальная длина строки в символах (>= 1)

        Returns:
            text с \\n разделителями между строками.
        """
        if not text:
            return text
        if max_length <= 0 or len(text) <= max_length:
            return text

        words = text.split()
        lines: List[str] = []
        current: List[str] = []
        current_len = 0

        for word in words:
            word_len = len(word)
            separator = 1 if current else 0
            if current_len + separator + word_len > max_length:
                if current:
                    lines.append(' '.join(current))
                    current = [word]
                    current_len = word_len
                else:
                    # слово само длиннее max_length — оставляем как есть
                    lines.append(word)
                    current = []
                    current_len = 0
            else:
                current.append(word)
                current_len += separator + word_len

        if current:
            lines.append(' '.join(current))

        return '\n'.join(lines)

    def plan(
        self,
        content: LegendContent,
        space: AvailableSpace,
        config_key: str,
    ) -> LegendPlan:
        """
        Подобрать параметры легенды: wrap_length, column_count, symbol_size.

        Args:
            content: результат M_46._collect_content (input pipe)
            space: результат Msm_46_2.calculate
            config_key: ключ Base_layout (для font, placement_mode, min_*)

        Returns:
            LegendPlan с mode='inline' если fits, иначе mode согласно
            placement_mode из config (inline tight либо overflow).

        Raises:
            RuntimeError: config_key не найден
        """
        config = self._provider(config_key)
        if config is None:
            raise RuntimeError(
                f"{MODULE_ID}: config_key '{config_key}' не найден"
            )

        placement_mode = str(
            config.get('legend_placement_mode', PlacementMode.INLINE)
        )
        min_sym_w = float(config.get('legend_min_symbol_width', 10))
        min_sym_h = float(config.get('legend_min_symbol_height', 3.5))
        min_wrap = int(config.get('legend_min_wrap_length', 40))
        font_family = str(config.get('font_family', 'GOST 2.304'))
        font_size_pt = int(config.get('font_size_pt', DEFAULT_FONT_SIZE_PT))

        char_width_mm = self._estimate_char_width_mm(font_family, font_size_pt)
        line_height_mm = font_size_pt * LINE_HEIGHT_MM_PER_PT

        # Пустой content — тривиальный план
        if content.count == 0:
            return LegendPlan(
                mode=PlacementMode.INLINE,
                wrap_length=min_wrap,
                column_count=1,
                symbol_width=DEFAULT_SYMBOL_WIDTH,
                symbol_height=DEFAULT_SYMBOL_HEIGHT,
                predicted_width_mm=0.0,
                predicted_height_mm=(
                    LEGEND_TITLE_HEIGHT_MM + 2 * LEGEND_PADDING_MM
                ),
                reason=None,
            )

        # Порядок попыток (предпочтения):
        # 1. col=1 default symbols
        # 2. col=2 default symbols
        # 3. col=3 default symbols
        # 4. col=3 reduced symbols (min_sym_w, min_sym_h)
        candidates = [
            (1, DEFAULT_SYMBOL_WIDTH, DEFAULT_SYMBOL_HEIGHT),
            (2, DEFAULT_SYMBOL_WIDTH, DEFAULT_SYMBOL_HEIGHT),
            (MAX_COLUMNS, DEFAULT_SYMBOL_WIDTH, DEFAULT_SYMBOL_HEIGHT),
            (MAX_COLUMNS, min_sym_w, min_sym_h),
        ]

        last_prediction = None
        for col, sym_w, sym_h in candidates:
            col_width = space.max_width_mm / col
            text_width = col_width - sym_w - LEGEND_PADDING_MM * 2
            if text_width <= 0:
                continue

            wrap_length = max(min_wrap, int(text_width / char_width_mm))
            predicted_h = self._predict_height(
                content, wrap_length, col, sym_h, line_height_mm
            )
            predicted_w = space.max_width_mm

            last_prediction = (
                col, sym_w, sym_h, wrap_length, predicted_w, predicted_h,
            )

            if predicted_h <= space.max_height_mm:
                log_info(
                    f"{MODULE_ID}: План col={col}, wrap={wrap_length}, "
                    f"sym={sym_w}x{sym_h}, "
                    f"h={predicted_h:.0f}/{space.max_height_mm:.0f} мм"
                )
                return LegendPlan(
                    mode=PlacementMode.INLINE,
                    wrap_length=wrap_length,
                    column_count=col,
                    symbol_width=sym_w,
                    symbol_height=sym_h,
                    predicted_width_mm=predicted_w,
                    predicted_height_mm=predicted_h,
                    reason=None,
                )

        # Не fits ни в одном кандидате — fallback
        if last_prediction is None:
            # Экстремальный случай: space.max_width_mm слишком мал для любого col
            log_warning(
                f"{MODULE_ID}: max_width={space.max_width_mm:.1f} мм недостаточно "
                f"для минимального symbol+padding. Fallback min_wrap."
            )
            return LegendPlan(
                mode=PlacementMode.INLINE,
                wrap_length=min_wrap,
                column_count=1,
                symbol_width=min_sym_w,
                symbol_height=min_sym_h,
                predicted_width_mm=space.max_width_mm,
                predicted_height_mm=space.max_height_mm,
                reason='space_too_narrow_for_any_column',
            )

        col, sym_w, sym_h, wrap_length, predicted_w, predicted_h = last_prediction

        if placement_mode == PlacementMode.OVERFLOW:
            log_warning(
                f"{MODULE_ID}: Легенда не fits inline "
                f"(h={predicted_h:.0f}>{space.max_height_mm:.0f} мм) → mode=overflow"
            )
            return LegendPlan(
                mode=PlacementMode.OVERFLOW,
                wrap_length=wrap_length,
                column_count=col,
                symbol_width=sym_w,
                symbol_height=sym_h,
                predicted_width_mm=predicted_w,
                predicted_height_mm=predicted_h,
                reason=(
                    f'overflow_h_{predicted_h:.0f}_vs_'
                    f'{space.max_height_mm:.0f}'
                ),
            )

        # mode=inline, но не fits — возвращаем максимально уплотнённый план
        log_warning(
            f"{MODULE_ID}: Легенда не fits, placement_mode=inline — "
            f"возврат tight plan, возможен визуальный overflow"
        )
        return LegendPlan(
            mode=PlacementMode.INLINE,
            wrap_length=wrap_length,
            column_count=col,
            symbol_width=sym_w,
            symbol_height=sym_h,
            predicted_width_mm=predicted_w,
            predicted_height_mm=predicted_h,
            reason='tight_inline_may_overflow_visually',
        )

    # === Private helpers ===

    @staticmethod
    def _estimate_char_width_mm(font_family: str, font_size_pt: int) -> float:
        """
        Оценить ширину типичного русского символа в мм через QFontMetrics.

        Использует horizontalAdvance('а') с конверсией px → mm через DPI.
        Fallback на DEFAULT_CHAR_WIDTH_MM при невалидном DPI.
        """
        try:
            font = QFont(font_family, font_size_pt)
            fm = QFontMetrics(font)
            advance_px = float(fm.horizontalAdvance("а"))

            # fontDpi() добавлен в Qt 5.15+. Для раннего Qt — fallback.
            dpi = None
            if hasattr(fm, 'fontDpi'):
                try:
                    dpi = float(fm.fontDpi())
                except Exception:
                    dpi = None

            if dpi and dpi > 0 and advance_px > 0:
                # px → inch → mm
                return advance_px / dpi * 25.4
        except Exception as e:
            log_warning(
                f"{MODULE_ID}: QFontMetrics error '{e}', "
                f"fallback char_width={DEFAULT_CHAR_WIDTH_MM} мм"
            )

        return DEFAULT_CHAR_WIDTH_MM

    def _predict_height(
        self,
        content: LegendContent,
        wrap_length: int,
        col_count: int,
        symbol_height: float,
        line_height_mm: float,
    ) -> float:
        """
        Предсказать суммарную высоту легенды в мм.

        Для каждого item: строк после wrap → max(symbol_height, lines*line_height).
        Сумма делится на col_count + title + paddings.

        OPT-6 simplified: assumes roughly equal item heights. Полный
        greedy fill simulation по колонкам deferred до v2. Trigger
        для v2: счётчик `legend/predict_mismatch_count` в customProperty
        (Msm_34_2) систематически растёт (>10% запусков за 2 недели).
        """
        total_item_heights = 0.0
        for item in content.items:
            wrapped = LayoutPlanner.wrap_text(item.title, wrap_length)
            line_count = wrapped.count('\n') + 1
            item_height = max(symbol_height, line_count * line_height_mm)
            total_item_heights += item_height + INTER_ITEM_SPACING_MM

        if col_count <= 0:
            col_count = 1
        per_column_height = total_item_heights / col_count
        return (
            per_column_height + LEGEND_TITLE_HEIGHT_MM + 2 * LEGEND_PADDING_MM
        )
