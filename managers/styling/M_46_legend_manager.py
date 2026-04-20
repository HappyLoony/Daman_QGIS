# -*- coding: utf-8 -*-
"""
M_46: LegendManager — Централизованный менеджер условных обозначений.

Facade для 3 суб-менеджеров:
- Msm_46_2_space_calculator: расчёт доступной области
- Msm_46_3_layout_planner: детерминированный план (wrap/col/sym)
- Msm_46_4_placement_strategy: применение плана (inline/overflow)

Сбор содержимого легенды — приватный метод `_collect_content()` внутри
самого M_46 (input pipe, не алгоритм). OPT-1 adversarial review:
SRP не требует отдельного файла для операции, которая не является алгоритмом.

Вызывается ПОСЛЕ update_legend и apply_main_map_extent, ДО adapt_legend
(extent_shifter).

Crash-first дебаг: plan_and_apply НЕ глотает исключения из суб-менеджеров.
Все ошибки _calculator.calculate / _planner.plan / strategy.apply всплывают
наверх с полным traceback. LegendResult(success=False, ...) возвращается
ТОЛЬКО для штатных ранних return (нет легенды / нет main_map / пустой
content).

Используется: F_1_4 (Fsm_1_4_5), F_6_6 (F_6_6_master_plan), будущие F_5_*.
"""

from qgis.core import QgsPrintLayout

from Daman_QGIS.utils import log_info, log_warning
from .submodules.Msm_46_utils import find_legend, find_main_map
from .submodules.Msm_46_2_space_calculator import SpaceCalculator
from .submodules.Msm_46_3_layout_planner import LayoutPlanner
from .submodules.Msm_46_4_placement_strategy import choose_strategy
from .submodules.Msm_46_types import LegendContent, LegendItem, LegendResult

__all__ = ['LegendManager']


class LegendManager:
    """
    Координатор работы с условными обозначениями (легендой) макета печати.

    Собирает в единый pipeline 3 суб-менеджера:
    1. SpaceCalculator (Msm_46_2) — вычисляет доступное пространство
       для легенды на странице исходя из геометрии соседних элементов.
    2. LayoutPlanner (Msm_46_3) — подбирает параметры легенды
       (wrap_length, column_count, symbol_size) чтобы уместиться.
    3. PlacementStrategy (Msm_46_4) — применяет план к
       QgsLayoutItemLegend (inline) или к отдельному листу (overflow stub).

    Сбор содержимого — приватный input pipe `_collect_content`.
    """

    def __init__(self) -> None:
        """Инициализация суб-менеджеров."""
        self._calculator = SpaceCalculator()
        self._planner = LayoutPlanner()

    # =========================================================================
    # Публичный API
    # =========================================================================

    def plan_and_apply(
        self,
        layout: QgsPrintLayout,
        config_key: str,
    ) -> LegendResult:
        """
        Полный цикл обработки легенды: collect → calculate → plan → apply.

        Crash-first: исключения из _calculator / _planner / strategy НЕ
        ловятся — всплывают наверх с полным traceback.

        Args:
            layout: Макет с заполненной легендой (после update_legend).
            config_key: Ключ Base_layout ('A4_landscape_DPT', 'A3_landscape_MP'
                и т.д.).

        Returns:
            LegendResult.

            Штатные ранние return (log_warning + success=False):
              - mode_applied='no_legend' — QgsLayoutItemLegend (id='legend')
                не найден в макете
              - mode_applied='no_main_map' — QgsLayoutItemMap (id='main_map')
                не найден в макете
              - mode_applied='empty_content' — в модели легенды нет ни одного
                QgsLayerTreeLayer

            Успешный случай: LegendResult(success=True, mode_applied='inline'
            | 'overflow_fallback_inline', ...) от strategy.apply().

        Raises:
            Любые исключения из суб-менеджеров (RuntimeError из
            SpaceCalculator при unknown config_key, ValueError из
            choose_strategy и т.п.) — НЕ ловятся.
        """
        # Штатный guard 1: легенда должна существовать
        if find_legend(layout) is None:
            log_warning("M_46: легенда не найдена в макете")
            return LegendResult(
                success=False,
                mode_applied='no_legend',
                width_mm=0.0,
                height_mm=0.0,
                warning="QgsLayoutItemLegend с id='legend' не найден",
            )

        # Штатный guard 2: main_map должен существовать
        if find_main_map(layout) is None:
            log_warning("M_46: main_map не найден в макете")
            return LegendResult(
                success=False,
                mode_applied='no_main_map',
                width_mm=0.0,
                height_mm=0.0,
                warning="QgsLayoutItemMap с id='main_map' не найден",
            )

        # Штатный guard 3: пустая легенда — нечего планировать
        content = self._collect_content(layout)
        log_info(f"M_46: Собрано {content.count} пунктов легенды")
        if content.count == 0:
            log_warning("M_46: легенда пуста — пропуск planning")
            return LegendResult(
                success=False,
                mode_applied='empty_content',
                width_mm=0.0,
                height_mm=0.0,
                warning="LegendContent пуст (0 items)",
            )

        # Основной pipeline — crash-first, без try/except
        space = self._calculator.calculate(layout, config_key)

        plan = self._planner.plan(content, space, config_key)
        log_info(
            f"M_46: План mode={plan.mode}, col={plan.column_count}, "
            f"wrap={plan.wrap_length}, "
            f"h_pred={plan.predicted_height_mm:.0f} мм"
        )

        # OPT-7: Проброс predicted_height_mm в customProperty layout
        # для последующей валидации в Msm_34_2_extent_shifter.
        layout.setCustomProperty(
            'legend/predicted_height_mm', plan.predicted_height_mm
        )

        strategy = choose_strategy(plan.mode)
        result = strategy.apply(layout, plan)

        log_info(
            f"M_46: Применено mode={result.mode_applied}, "
            f"h={result.height_mm:.0f} мм, success={result.success}"
        )
        return result

    # =========================================================================
    # Приватные методы (input pipe)
    # =========================================================================

    def _collect_content(self, layout: QgsPrintLayout) -> LegendContent:
        """
        Input pipe: читает модель легенды, возвращает LegendContent с items.

        OPT-1 adversarial review: выделение в отдельный суб-менеджер
        (Msm_46_1) было бы overhead — 3 файла ради ~10 строк логики.
        Это не алгоритм, а чтение структуры макета.

        Title для каждого item берётся из customProperty 'legend/title-label'
        (если уже задан — например, после предыдущего wrap), fallback
        на layer.name().

        Контракт: вызывается ПОСЛЕ того как plan_and_apply проверил, что
        find_legend(layout) вернул не-None. Если легенды нет — вернёт
        LegendContent(items=[]) (не бросает), но сама эта ситуация
        не должна случаться при штатном вызове из plan_and_apply.

        Args:
            layout: Макет с QgsLayoutItemLegend (id='legend').

        Returns:
            LegendContent с items для всех QgsLayerTreeLayer в модели
            легенды. Пустая модель → LegendContent(items=[]).
        """
        legend = find_legend(layout)
        if legend is None:
            # Защитный путь: при штатном вызове из plan_and_apply
            # сюда не попадём (там guard выше). Оставлен ради
            # безопасности прямых вызовов из тестов.
            return LegendContent(items=[])

        model = legend.model()
        if model is None:
            return LegendContent(items=[])
        root = model.rootGroup()
        if root is None:
            return LegendContent(items=[])

        items = []
        for node in root.children():
            # QgsLayerTreeLayer имеет метод layer(); группы и прочие узлы — нет.
            # Crash-first: не глотаем ошибки чтения node.layer()/layer.name().
            layer_callable = getattr(node, 'layer', None)
            if layer_callable is None:
                continue
            layer = layer_callable() if callable(layer_callable) else layer_callable
            if layer is None:
                continue

            layer_name = layer.name()
            custom_title = node.customProperty("legend/title-label")
            title = custom_title if custom_title else layer_name

            items.append(LegendItem(layer_name=layer_name, title=title))

        return LegendContent(items=items)
