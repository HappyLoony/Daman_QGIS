# -*- coding: utf-8 -*-
"""
Msm_46_4: PlacementStrategy — Применение LegendPlan к макету.

Strategy pattern (3 режима LegendLayoutMode):
- DynamicPlacement   — адаптивная вставка на текущем листе (рамка, auto-size)
- FixedPanelPlacement — фиксированная панель вне main_map (без рамки, clamp по высоте)
- OutsidePlacement    — STUB v1: легенда на отдельном листе (план v2 Atlas)

OPT-2 consensus: find_legend переиспользуется из Msm_46_utils,
не дублируется внутри ABC.

# TODO QGIS 3.44+: после апгрейда LTR _apply_wrap_to_titles можно удалить
# и заменить на legend.setAutoWrapLength(plan.text_width_mm) — нативный
# pixel-wrap рендера. Planner и его pixel-based wrap_text всё равно нужны
# для оценки высоты (compaction уровни требуют предсказания строк/высоты).

Используется: M_46_legend_manager.py
"""

from abc import ABC, abstractmethod

from qgis.core import (
    QgsLayoutItemLegend,
    QgsPrintLayout,
)
from qgis.PyQt.QtGui import QFont, QFontMetricsF  # QFont для fallback в _apply_wrap_to_titles

from Daman_QGIS.utils import log_info, log_warning
from .Msm_46_3_layout_planner import LayoutPlanner
from .Msm_46_types import LegendLayoutMode, LegendPlan, LegendResult
from .Msm_46_utils import apply_letter_spacing_to_font, find_legend

MODULE_ID = "Msm_46_4"

# Progressive compaction scale для FixedPanelPlacement при overflow по высоте.
# Iterative try-fit: применяем уровень → измеряем → если fits, стоп. Иначе следующий.
# Если все уровни не fit → hard clamp с crop.
#
# Каждый уровень — tuple (name, symbol_top_mm, symbol_label_top_mm, line_spacing_mm).
# Default QGIS: Symbol Top=2.5, SymbolLabel Top=2.0, lineSpacing=1.0.
# Минимум читаемости (cartographic): Symbol Top ~1.0, lineSpacing ~0.15.
#
# Letter-spacing 4-й уровень был добавлен в попытке (Fix C), но setTextFormat
# на текущем шрифте легенды повреждал рендер (текст разбивался посимвольно).
# Откатан до выяснения корня. До решения — только spacing-уплотнение.
COMPACTION_LEVELS = (
    # Принцип: Symbol Top (inter-item gap) должен быть >= 4× lineSpacing
    # (intra-item gap), иначе визуально пункты сливаются с переносами строк
    # внутри пункта (QGIS добавляет неявный bottom-padding для multiline).
    #
    # Уровень 1: Light — мягкое уменьшение, breathing room сохранён.
    ('light',  2.0, 1.0, 0.5),
    # Уровень 2: Medium — заметное уплотнение.
    ('medium', 1.5, 0.5, 0.3),
    # Уровень 3: Tight — максимально допустимое уплотнение.
    ('tight',  1.0, 0.3, 0.15),
)


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

    # === Helpers (общие для DynamicPlacement и FixedPanelPlacement) ===

    @staticmethod
    def _apply_wrap_to_titles(
        legend: QgsLayoutItemLegend,
        text_width_mm: float,
    ) -> None:
        """
        Применить wrap_text к title каждого слоя в модели легенды.

        Pixel-based: измеряет реальную ширину строки через QFontMetricsF на
        шрифте SymbolLabel легенды (font берётся из QgsLegendStyle.SymbolLabel
        textFormat). Читает текущий title из customProperty 'legend/title-label',
        fallback на layer.name().

        # TODO QGIS 3.44+: на новом LTR можно удалить эту функцию и заменить
        # на legend.setAutoWrapLength(text_width_mm) — нативный pixel-wrap
        # рендера. Planner всё равно нужен для оценки высоты.
        """
        from qgis.core import QgsLegendStyle
        model = legend.model()
        if model is None:
            return
        root = model.rootGroup()
        if root is None:
            return

        # Шрифт SymbolLabel — тот же, которым QGIS рендерит подписи в легенде.
        # font_metrics на этом шрифте даёт точные measure для wrap_text.
        try:
            label_font = legend.style(QgsLegendStyle.SymbolLabel).textFormat().font()
        except Exception:
            label_font = QFont()
        font_metrics = QFontMetricsF(label_font)

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

            wrapped = LayoutPlanner.wrap_text(
                current_title, text_width_mm, font_metrics
            )
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

    @staticmethod
    def _apply_line_spacing(
        legend: QgsLayoutItemLegend,
        extra_spacing_mm: float,
    ) -> None:
        """Установить межстрочный интервал для text-стилей легенды.

        Замена deprecated `QgsLayoutItemLegend.setLineSpacing(extra_mm)`.
        Под капотом старая функция делала
        `style.textFormat().setLineHeight(font_height_mm + extra_mm, Mm)`
        для каждого text-стиля. Эта реализация делает то же самое явно через
        non-deprecated API.

        extra_spacing_mm — дополнительный inter-line gap в мм (поверх
        font height). 0 = без extra, типичные значения для compaction
        0.15-0.5 мм.

        Применяется к Title/Group/Subgroup/SymbolLabel — Symbol style
        не трогаем (служебный, не текстовый).
        """
        from qgis.core import QgsUnitTypes, QgsLegendStyle  # lazy
        # Читаем актуальный font size легенды (SymbolLabel — показатель основного текста)
        symlabel_style = legend.style(QgsLegendStyle.SymbolLabel)
        font_size_pt = symlabel_style.textFormat().font().pointSizeF()
        if font_size_pt <= 0:
            font_size_pt = 14.0  # fallback: текущий стандарт config
        # 1pt = 1/72 inch = 0.3528 mm (Qt-стандарт)
        font_height_mm = font_size_pt * 0.3528
        line_height_mm = font_height_mm + extra_spacing_mm

        for style_name in ('Title', 'Group', 'Subgroup', 'SymbolLabel'):
            style_enum = getattr(QgsLegendStyle, style_name, None)
            if style_enum is None:
                continue
            style_ref = legend.rstyle(style_enum)
            text_format = style_ref.textFormat()
            text_format.setLineHeight(line_height_mm)
            text_format.setLineHeightUnit(QgsUnitTypes.RenderMillimeters)
            style_ref.setTextFormat(text_format)

    @staticmethod
    def _apply_letter_spacing(
        legend: QgsLayoutItemLegend,
        letter_spacing_pt: float,
    ) -> None:
        """Применить letter-spacing к font во всех text-стилях легенды.

        Использует shared `apply_letter_spacing_to_font` из Msm_46_utils —
        тот же helper применяется в Msm_34_1 для font'ов label-элементов
        (title/appendix/organization). Единое поведение для всей схемы.

        Применяется к Title/Group/Subgroup/SymbolLabel — main_map/title
        документа не затрагиваются.
        """
        from qgis.core import QgsLegendStyle  # lazy
        for style_name in ('Title', 'Group', 'Subgroup', 'SymbolLabel'):
            style_enum = getattr(QgsLegendStyle, style_name, None)
            if style_enum is None:
                continue
            style_ref = legend.rstyle(style_enum)
            text_format = style_ref.textFormat()
            font = text_format.font()
            apply_letter_spacing_to_font(font, letter_spacing_pt)
            text_format.setFont(font)
            style_ref.setTextFormat(text_format)


class DynamicPlacement(PlacementStrategy):
    """Адаптивное размещение легенды на том же листе с рамкой и auto-size.

    Семантика:
    - Рамка включена (setFrameEnabled(True)), как у обычного inline блока.
    - Auto-size высоты через setResizeToContents(True): легенда растёт под
      содержимое, planner отвечал за подбор wrap/col/symbol.
    - Symmetry с FixedPanelPlacement: frame ownership живёт здесь, не в
      Msm_34_1.
    """

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
                f"{MODULE_ID} DynamicPlacement: legend item не найден в layout"
            )
            return LegendResult(
                success=False,
                mode_applied=LegendLayoutMode.DYNAMIC,
                width_mm=0.0,
                height_mm=0.0,
                warning='Legend item не найден',
            )

        # Letter-spacing применяется ПЕРВЫМ — до wrap, чтобы _apply_wrap_to_titles
        # читал legend.style().textFormat().font() с уже applied letter-spacing
        # и QFontMetricsF давал корректные measurements (буквы плотнее → больше
        # chars в строке → меньше переносов).
        self._apply_letter_spacing(legend, plan.letter_spacing_pt)
        self._apply_wrap_to_titles(legend, plan.text_width_mm)
        self._apply_legend_params(legend, plan)

        # Frame ownership живёт в strategy (не в Msm_34_1) — symmetry с
        # FixedPanelPlacement, который выключает рамку.
        legend.setFrameEnabled(True)
        legend.setResizeToContents(True)

        log_info(
            f"{MODULE_ID} DynamicPlacement: col={plan.column_count}, "
            f"wrap={plan.wrap_length}, "
            f"sym={plan.symbol_width}x{plan.symbol_height}, frame=True"
        )

        return LegendResult(
            success=True,
            mode_applied=LegendLayoutMode.DYNAMIC,
            width_mm=plan.predicted_width_mm,
            height_mm=plan.predicted_height_mm,
            warning=plan.reason,  # tight_inline_may_overflow_visually и пр.
        )


class FixedPanelPlacement(PlacementStrategy):
    """Размещение легенды в фиксированной полосе вне main_map (для F_5_4 master plan).

    Семантика:
    - Координаты, ширина, потолок высоты заданы явно в Base_layout (legend_panel_*).
    - Без рамки (setFrameEnabled(False)).
    - Auto-size высоты через setResizeToContents(True), но при overflow сверх
      height_max_mm — clamp через attemptResize (content cropped, preferable to
      overlap с overview_map).
    - Без сдвига extent main_map (Msm_34_2 делает skip для panel mode).
    """

    def apply(
        self,
        layout: QgsPrintLayout,
        plan: LegendPlan,
    ) -> LegendResult:
        """Применить план для fixed_panel режима."""
        legend = find_legend(layout)
        if legend is None:
            log_warning(
                f"{MODULE_ID} FixedPanelPlacement: legend item не найден"
            )
            return LegendResult(
                success=False,
                mode_applied=LegendLayoutMode.FIXED_PANEL,
                width_mm=0.0,
                height_mm=0.0,
                warning='Legend item не найден',
            )

        # Letter-spacing применяется ПЕРВЫМ — до wrap, чтобы _apply_wrap_to_titles
        # читал legend.style().textFormat().font() с уже applied letter-spacing
        # и QFontMetricsF давал корректные measurements (буквы плотнее → больше
        # chars в строке → меньше переносов).
        self._apply_letter_spacing(legend, plan.letter_spacing_pt)
        self._apply_wrap_to_titles(legend, plan.text_width_mm)
        self._apply_legend_params(legend, plan)

        legend.setFrameEnabled(False)
        legend.setResizeToContents(True)
        if hasattr(legend, 'adjustBoxSize'):
            legend.adjustBoxSize()

        log_info(
            f"{MODULE_ID} FixedPanelPlacement: col={plan.column_count}, "
            f"wrap={plan.wrap_length}, sym={plan.symbol_width}x{plan.symbol_height}, "
            f"frame=False"
        )

        # Initial measurement после adjustBoxSize() с default spacing.
        # КРИТИЧНО: sizeWithUnits() возвращает 0×0 до первого paint pass.
        # Forced render через exportToImage в tmp PNG триггерит paint pipeline
        # → sizeWithUnits возвращает реальные мм. Тот же приём что в Msm_34_2.
        self._force_paint_pass(layout)
        final_w = legend.sizeWithUnits().width()
        final_h = legend.sizeWithUnits().height()
        log_info(
            f"{MODULE_ID} FixedPanelPlacement: измерение после adjustBoxSize "
            f"{final_w:.1f}x{final_h:.1f} мм (target {plan.width_mm:.0f}x{plan.height_max_mm:.0f})"
        )

        # Step 1: Progressive compaction try-fit.
        # Iteratively применяем уровни Light → Medium → Tight → XTight. На
        # каждом шаге adjustBoxSize() и re-measure. Если fits на любом уровне
        # — стоп. Если все уровни не fit — переходим к hard clamp.
        applied_compaction_level = None
        if final_h > plan.height_max_mm:
            from qgis.core import QgsLegendStyle  # lazy
            overflow_ratio = (final_h - plan.height_max_mm) / plan.height_max_mm * 100
            log_info(
                f"{MODULE_ID} FixedPanelPlacement: высота overflow "
                f"{final_h:.1f} > {plan.height_max_mm:.0f} мм "
                f"(+{overflow_ratio:.0f}%) — progressive compaction try-fit"
            )
            for level_name, sym_top, label_top, line_sp in COMPACTION_LEVELS:
                legend.rstyle(QgsLegendStyle.Symbol).setMargin(
                    QgsLegendStyle.Top, sym_top
                )
                legend.rstyle(QgsLegendStyle.SymbolLabel).setMargin(
                    QgsLegendStyle.Top, label_top
                )
                # Замена deprecated legend.setLineSpacing(line_sp) →
                # textFormat().setLineHeight(...) per text style. См.
                # _apply_line_spacing для деталей.
                self._apply_line_spacing(legend, line_sp)
                if hasattr(legend, 'adjustBoxSize'):
                    legend.adjustBoxSize()
                final_w = legend.sizeWithUnits().width()
                final_h = legend.sizeWithUnits().height()
                # Defensive: если adjustBoxSize не обновил измерения после
                # paint invalidate — re-trigger paint pipeline.
                if final_h <= 0 or final_w <= 0:
                    self._force_paint_pass(layout)
                    final_w = legend.sizeWithUnits().width()
                    final_h = legend.sizeWithUnits().height()
                if final_h <= plan.height_max_mm:
                    applied_compaction_level = level_name
                    log_info(
                        f"{MODULE_ID} FixedPanelPlacement: уровень '{level_name}' "
                        f"(Sym Top {sym_top}, Label Top {label_top}, "
                        f"lineSp {line_sp}) — "
                        f"fits {final_w:.1f}x{final_h:.1f} мм"
                    )
                    break
                log_info(
                    f"{MODULE_ID} FixedPanelPlacement: уровень '{level_name}' "
                    f"не помогает ({final_h:.1f} > {plan.height_max_mm:.0f}) — пробуем дальше"
                )
            if applied_compaction_level is None:
                log_warning(
                    f"{MODULE_ID} FixedPanelPlacement: все уровни compaction исчерпаны "
                    f"({final_h:.1f} > {plan.height_max_mm:.0f}) — переход к hard clamp"
                )

        # Step 2: Force-resize width до plan.width_mm для consistency между
        # макетами мастер-плана. Защита: если final_h <= 0 (paint pass не
        # дал валидных measurements) — skip, иначе attemptResize(W, 0)
        # схлопнул бы легенду в нулевую высоту → character-wrap рендер.
        from qgis.core import Qgis, QgsLayoutSize  # lazy
        if final_h > 0 and abs(final_w - plan.width_mm) > 0.5:
            log_info(
                f"{MODULE_ID} FixedPanelPlacement: force-resize width "
                f"{final_w:.1f} → {plan.width_mm:.0f} мм (consistency)"
            )
            legend.setResizeToContents(False)
            legend.attemptResize(QgsLayoutSize(
                plan.width_mm, final_h, Qgis.LayoutUnit.Millimeters
            ))
            final_w = plan.width_mm
        elif final_h <= 0:
            log_warning(
                f"{MODULE_ID} FixedPanelPlacement: skip force-resize — "
                f"final_h={final_h:.1f} (paint pass invalid)"
            )

        # Step 3: Hard clamp по высоте если всё ещё overflow (compaction
        # исчерпан). Width уже зафиксирован Step 2.
        if final_h > plan.height_max_mm:
            new_h = plan.height_max_mm
            log_warning(
                f"{MODULE_ID} FixedPanelPlacement: clamp height "
                f"{final_h:.1f} → {new_h:.1f} мм "
                f"(target h_max={plan.height_max_mm:.0f}). "
                f"Content за пределами bbox обрезается."
            )
            legend.setResizeToContents(False)
            legend.attemptResize(QgsLayoutSize(
                plan.width_mm, new_h, Qgis.LayoutUnit.Millimeters
            ))

        if hasattr(legend, 'refresh'):
            legend.refresh()

        return LegendResult(
            success=True,
            mode_applied=LegendLayoutMode.FIXED_PANEL,
            width_mm=plan.predicted_width_mm,
            height_mm=plan.predicted_height_mm,
        )

    @staticmethod
    def _force_paint_pass(layout: QgsPrintLayout) -> None:
        """Триггерит paint pipeline через экспорт в tmp PNG (72 DPI).

        После adjustBoxSize() метод sizeWithUnits() возвращает 0×0 до первого
        paint pass. exportToImage запускает полный paint cycle, после чего
        sizeWithUnits() возвращает реальные мм. Тот же приём используется в
        Msm_34_2.shift_extent_for_legend для извлечения фактических размеров
        легенды до клика пользователя.

        Args:
            layout: layout для рендера в paint pipeline
        """
        import os
        import tempfile
        from qgis.core import QgsLayoutExporter
        try:
            exporter = QgsLayoutExporter(layout)
            tmp_path = os.path.join(
                tempfile.gettempdir(), '_legend_panel_measure.png'
            )
            settings = QgsLayoutExporter.ImageExportSettings()
            settings.dpi = 72  # минимальный DPI для скорости
            exporter.exportToImage(tmp_path, settings)
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        except Exception as e:
            log_warning(
                f"{MODULE_ID} FixedPanelPlacement._force_paint_pass: "
                f"не удалось запустить paint pass — {e}"
            )


class OutsidePlacement(PlacementStrategy):
    """[STUB v1]: Вывод легенды на отдельный лист (Atlas v2).

    Текущая реализация: log warning + LegendResult(success=False).
    Layout остаётся без блока легенды. PDF выйдет без легенды.

    В v2: создать вторую страницу макета, перенести легенду туда.
    """

    def apply(
        self,
        layout: QgsPrintLayout,
        plan: LegendPlan,
    ) -> LegendResult:
        log_warning(
            f"{MODULE_ID} OutsidePlacement: STUB — outside режим не реализован "
            f"(план v2). Layout остаётся без блока легенды."
        )
        return LegendResult(
            success=False,
            mode_applied='outside_stub',
            width_mm=0.0,
            height_mm=0.0,
            warning='OutsidePlacement stub — реализация v2',
        )


def choose_strategy(mode: str) -> PlacementStrategy:
    """Выбор PlacementStrategy по mode (LegendLayoutMode)."""
    if mode == LegendLayoutMode.DYNAMIC:
        return DynamicPlacement()
    if mode == LegendLayoutMode.FIXED_PANEL:
        return FixedPanelPlacement()
    if mode == LegendLayoutMode.OUTSIDE:
        return OutsidePlacement()
    raise ValueError(
        f"{MODULE_ID}: неизвестный legend_layout_mode '{mode}' "
        f"(допустимо: {LegendLayoutMode.ALL})"
    )
