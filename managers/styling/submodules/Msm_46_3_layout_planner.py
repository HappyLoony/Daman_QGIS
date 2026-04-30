# -*- coding: utf-8 -*-
"""
Msm_46_3: LayoutPlanner — Детерминированный подбор параметров легенды.

Алгоритм (без рендера QGIS, через QFontMetrics):
1. col=1 с максимально широким wrap
2. col=2, col=3 при необходимости
3. reduced symbols при необходимости
4. tight plan + reason='tight_inline_may_overflow_visually' если не fits

OUTSIDE-routing перехвачен в M_46.facade (early return ДО вызова planner),
поэтому planner работает только в DYNAMIC / FIXED_PANEL контексте. Поле
`LegendPlan.mode` для логов всегда DYNAMIC ("planner-internal"); реальную
strategy выбирает M_46.facade через choose_strategy(legend_layout_mode).

wrap_text — pixel-based перенос через QFontMetricsF.horizontalAdvance().
Жадный wrap по словам с реальным измерением ширины строки в мм. Точнее
char-count приближения (учитывает разную ширину глифов: цифры/латиница
~2.5 мм, кириллица ~2.8-2.9 мм для Avenir Next 14pt).

# TODO QGIS 3.44+: после апгрейда LTR можно использовать встроенный
# legend.setAutoWrapLength(text_width_mm) для рендера и удалить
# _apply_wrap_to_titles в Msm_46_4. Planner и его pixel-based wrap_text
# всё равно нужны — нативный setAutoWrapLength рендерит, но не предсказывает
# сколько строк выйдет (нужно для column_count и compaction).

_predict_height — OPT-6 simplified: total / col_count. Полный greedy fill
simulation deferred до v2 (trigger: `legend/predict_mismatch_count` >10%).

Используется: M_46_legend_manager.py
"""

from typing import Any, Callable, Dict, List, Optional

from qgis.PyQt.QtGui import QFont, QFontMetricsF

from Daman_QGIS.utils import log_info, log_warning
from .Msm_46_types import (
    AvailableSpace,
    LegendContent,
    LegendLayoutMode,
    LegendPlan,
)
from .Msm_46_utils import (
    apply_letter_spacing_to_font,
    parse_letter_spacing_pt,
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
# LEGEND_PADDING_MM — "буфер" между symbol и текстом + правый край.
# Реальные QGIS отступы: boxSpace=2 (с каждой стороны), label_margin_left=5
# (между symbol и label) → суммарно 4-7 мм. Берём 2.0 как min consensus —
# даёт liberalнее text_width, легенда чуть шире, но строки на грани (~79 мм)
# реалистично помещаются. При overflow Msm_46_4.FixedPanelPlacement clamp'ит.
LEGEND_PADDING_MM = 2.0
INTER_ITEM_SPACING_MM = 2.0   # межстрочный интервал между items
DEFAULT_FONT_SIZE_PT = 14

# Конверсия pixel → mm для QFontMetricsF (Qt logical DPI = 96).
# QFontMetricsF.horizontalAdvance возвращает в pixels. Шрифт в pt — абсолютная
# единица (1pt = 0.353 мм), но Qt считает metrics в device pixels на screen DPI.
# При экспорте в PDF QGIS использует те же metrics — соотношение сохраняется.
PX_TO_MM = 25.4 / 96.0


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
    def wrap_text(
        text: str,
        max_width_mm: float,
        font_metrics: QFontMetricsF,
    ) -> str:
        """
        Разбить text на строки через \\n, ширина каждой <= max_width_mm.

        Pixel-based wrap через QFontMetricsF.horizontalAdvance() — точная ширина
        в pixels конвертируется в мм через PX_TO_MM. Жадный wrap по словам.
        Слово шире max_width_mm остаётся на отдельной строке как есть
        (не режется посимвольно).

        Точнее char-count приближения: учитывает разную ширину глифов кириллицы
        (~2.8-2.9 мм для 14pt) и латиницы/цифр (~2.5 мм).

        Args:
            text: исходный текст
            max_width_mm: максимальная ширина строки в мм (> 0)
            font_metrics: QFontMetricsF на актуальном шрифте легенды

        Returns:
            text с \\n разделителями между строками.
        """
        if not text:
            return text

        def width_mm(s: str) -> float:
            return font_metrics.horizontalAdvance(s) * PX_TO_MM

        if max_width_mm <= 0 or width_mm(text) <= max_width_mm:
            return text

        words = text.split()
        lines: List[str] = []
        current: List[str] = []

        for word in words:
            candidate = ' '.join(current + [word]) if current else word
            if width_mm(candidate) > max_width_mm:
                if current:
                    lines.append(' '.join(current))
                    current = [word]
                else:
                    # слово само шире max_width_mm — оставляем как есть
                    lines.append(word)
                    current = []
            else:
                current.append(word)

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
            config_key: ключ Base_layout (для font, min_symbol_*)

        Returns:
            LegendPlan с mode=DYNAMIC ("planner-internal" значение для логов).
            При не-fit возвращает максимально уплотнённый план с
            reason='tight_inline_may_overflow_visually'.

        Raises:
            RuntimeError: config_key не найден
        """
        config = self._provider(config_key)
        if config is None:
            raise RuntimeError(
                f"{MODULE_ID}: config_key '{config_key}' не найден"
            )

        # Routing по legend_layout_mode выполняется в M_46.plan_and_apply
        # (OUTSIDE — early return до вызова planner). Здесь planner работает
        # только в DYNAMIC / FIXED_PANEL контексте; для логов в LegendPlan.mode
        # пишется DYNAMIC как "planner-internal" значение (выбор strategy
        # делает M_46.facade через choose_strategy(mode), а не через plan.mode).
        min_sym_w = float(config.get('legend_min_symbol_width', 10))
        min_sym_h = float(config.get('legend_min_symbol_height', 3.5))
        font_family = str(config.get('font_family', 'GOST 2.304'))
        font_size_pt = int(config.get('font_size_pt', DEFAULT_FONT_SIZE_PT))
        # letter_spacing_pt: AbsoluteSpacing в pt — глобальный параметр макета
        # (page-level). Парсинг + apply через shared helpers Msm_46_utils
        # (единое поведение для legend и labels — Msm_34_1 использует те же).
        letter_spacing_pt = parse_letter_spacing_pt(config)

        # QFontMetricsF на актуальном шрифте С letter-spacing — для точного
        # pixel-based wrap. Если letter_spacing_pt < 0, буквы плотнее, в строку
        # помещается больше chars → wrap_text/predict_height точнее.
        font = QFont(font_family, font_size_pt)
        if letter_spacing_pt != 0.0:
            apply_letter_spacing_to_font(font, letter_spacing_pt)
        font_metrics = QFontMetricsF(font)
        line_height_mm = font_size_pt * LINE_HEIGHT_MM_PER_PT

        # Самое длинное слово в content (в мм через QFontMetricsF) — defines
        # minimum text_width per col. wrap_text не дробит слова: если слово
        # шире text_width, candidate реально займёт ширину max_word_mm в каждой
        # колонке, что превышает col_width. Пропускаем такой candidate.
        max_word_mm = 0.0
        max_word_text = ""
        if content.items:
            for item in content.items:
                if not item.title:
                    continue
                for word in item.title.split():
                    w_mm = font_metrics.horizontalAdvance(word) * PX_TO_MM
                    if w_mm > max_word_mm:
                        max_word_mm = w_mm
                        max_word_text = word
        log_info(
            f"{MODULE_ID}: font={font_family} {font_size_pt}pt "
            f"letter_sp={letter_spacing_pt:+.1f}pt, "
            f"line_height={line_height_mm:.2f} мм, "
            f"max_word='{max_word_text}' ({max_word_mm:.1f} мм)"
        )

        # Пустой content — тривиальный план. wrap_length=0 (wrap не
        # применяется при отсутствии items; значение чисто для контракта
        # LegendPlan).
        if content.count == 0:
            return LegendPlan(
                mode=LegendLayoutMode.DYNAMIC,
                wrap_length=0,
                column_count=1,
                symbol_width=DEFAULT_SYMBOL_WIDTH,
                symbol_height=DEFAULT_SYMBOL_HEIGHT,
                predicted_width_mm=0.0,
                predicted_height_mm=(
                    LEGEND_TITLE_HEIGHT_MM + 2 * LEGEND_PADDING_MM
                ),
                width_mm=space.max_width_mm,
                height_max_mm=space.max_height_mm,
                text_width_mm=0.0,
                letter_spacing_pt=letter_spacing_pt,
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

            # Длинное слово не помещается в text_width в pixel-based терминах.
            if max_word_mm > text_width:
                log_info(
                    f"{MODULE_ID}: candidate col={col}, sym={sym_w}x{sym_h} skip — "
                    f"max_word '{max_word_text}' ({max_word_mm:.1f} мм) "
                    f"> text_width ({text_width:.1f} мм)"
                )
                continue

            # wrap_length для логов и LegendPlan (int approx). Реальный wrap в
            # стратегиях делается через wrap_text(text, text_width, font_metrics)
            # — pixel-based, не использует это число.
            avg_char_mm = font_metrics.averageCharWidth() * PX_TO_MM
            wrap_length = int(text_width / avg_char_mm) if avg_char_mm > 0 else 1
            log_info(
                f"{MODULE_ID}: candidate col={col}, sym={sym_w}x{sym_h}, "
                f"text_width={text_width:.1f} мм, ~wrap_chars={wrap_length}"
            )
            predicted_h = self._predict_height(
                content, text_width, font_metrics, col, sym_h, line_height_mm
            )
            predicted_w = space.max_width_mm

            last_prediction = (
                col, sym_w, sym_h, wrap_length, text_width,
                predicted_w, predicted_h,
            )

            if predicted_h <= space.max_height_mm:
                log_info(
                    f"{MODULE_ID}: План col={col}, wrap~={wrap_length}ch, "
                    f"text_w={text_width:.1f} мм, sym={sym_w}x{sym_h}, "
                    f"h={predicted_h:.0f}/{space.max_height_mm:.0f} мм"
                )
                return LegendPlan(
                    mode=LegendLayoutMode.DYNAMIC,
                    wrap_length=wrap_length,
                    column_count=col,
                    symbol_width=sym_w,
                    symbol_height=sym_h,
                    predicted_width_mm=predicted_w,
                    predicted_height_mm=predicted_h,
                    width_mm=space.max_width_mm,
                    height_max_mm=space.max_height_mm,
                    text_width_mm=text_width,
                    letter_spacing_pt=letter_spacing_pt,
                    reason=None,
                )

        # Не fits ни в одном кандидате — fallback
        if last_prediction is None:
            # Экстремальный случай: space.max_width_mm слишком мал для любого col.
            # wrap_length=1 — деградированный fallback (1 символ на строку),
            # содержимое почти наверняка визуально сломается, но это лучше чем
            # 0/отрицательное значение в LegendPlan.
            log_warning(
                f"{MODULE_ID}: max_width={space.max_width_mm:.1f} мм недостаточно "
                f"для минимального symbol+padding. Деградированный fallback."
            )
            return LegendPlan(
                mode=LegendLayoutMode.DYNAMIC,
                wrap_length=1,
                column_count=1,
                symbol_width=min_sym_w,
                symbol_height=min_sym_h,
                predicted_width_mm=space.max_width_mm,
                predicted_height_mm=space.max_height_mm,
                width_mm=space.max_width_mm,
                height_max_mm=space.max_height_mm,
                text_width_mm=max(
                    space.max_width_mm - min_sym_w - LEGEND_PADDING_MM * 2,
                    1.0,
                ),
                letter_spacing_pt=letter_spacing_pt,
                reason='space_too_narrow_for_any_column',
            )

        (col, sym_w, sym_h, wrap_length, text_width,
         predicted_w, predicted_h) = last_prediction

        # Не fits ни в одном кандидате — возвращаем максимально уплотнённый
        # план. Routing OUTSIDE происходит в M_46.facade ДО вызова planner,
        # поэтому здесь mode плана всегда DYNAMIC ("planner-internal").
        # Strategy выбирается в M_46.facade через choose_strategy(mode из
        # config), не через plan.mode.
        log_info(
            f"{MODULE_ID}: Легенда не fits — возврат tight plan, "
            f"возможен визуальный overflow"
        )
        return LegendPlan(
            mode=LegendLayoutMode.DYNAMIC,
            wrap_length=wrap_length,
            column_count=col,
            symbol_width=sym_w,
            symbol_height=sym_h,
            predicted_width_mm=predicted_w,
            predicted_height_mm=predicted_h,
            width_mm=space.max_width_mm,
            height_max_mm=space.max_height_mm,
            text_width_mm=text_width,
            letter_spacing_pt=letter_spacing_pt,
            reason='tight_inline_may_overflow_visually',
        )

    # === Private helpers ===

    def _predict_height(
        self,
        content: LegendContent,
        text_width_mm: float,
        font_metrics: QFontMetricsF,
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
            wrapped = LayoutPlanner.wrap_text(
                item.title, text_width_mm, font_metrics
            )
            line_count = wrapped.count('\n') + 1
            item_height = max(symbol_height, line_count * line_height_mm)
            total_item_heights += item_height + INTER_ITEM_SPACING_MM

        if col_count <= 0:
            col_count = 1
        per_column_height = total_item_heights / col_count
        return (
            per_column_height + LEGEND_TITLE_HEIGHT_MM + 2 * LEGEND_PADDING_MM
        )
