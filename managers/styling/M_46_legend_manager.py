# -*- coding: utf-8 -*-
"""
M_46: LegendManager — Централизованный менеджер условных обозначений.

Facade для 3 суб-менеджеров:
- Msm_46_2_space_calculator: legacy thin-wrapper (не используется в pipeline)
- Msm_46_3_layout_planner: детерминированный план (wrap/col/sym)
- Msm_46_4_placement_strategy: применение плана (dynamic/fixed_panel/outside)

С версии v0.4 (legend_layout_modes refactoring) AvailableSpace строится прямо
в facade методом `_build_space()` из явных полей Base_layout (legend_dynamic_*
для DYNAMIC, legend_panel_* для FIXED_PANEL). Маршрутизация по
`legend_layout_mode` из Excel — без эвристик neighbour-detection.

Сбор содержимого легенды — приватный метод `_collect_content()` внутри
самого M_46 (input pipe, не алгоритм).

Вызывается ПОСЛЕ update_legend и apply_main_map_extent, ДО adapt_legend
(extent_shifter).

Crash-first дебаг: plan_and_apply НЕ глотает исключения из суб-менеджеров.
Все ошибки _planner.plan / strategy.apply / _build_space всплывают наверх с
полным traceback. RuntimeError при невалидном legend_layout_mode, KeyError
при отсутствии обязательных legend_*_x/y/width_mm/height_max_mm/ref_point
полей. LegendResult(success=False, ...) возвращается ТОЛЬКО для штатных
ранних return (нет легенды / нет main_map / пустой content).

Используется: F_1_4 (Fsm_1_4_5), F_6_6 (F_6_6_master_plan), будущие F_5_*.
"""

from qgis.core import QgsPrintLayout

from Daman_QGIS.utils import log_info, log_warning
from .submodules.Msm_46_utils import find_legend, find_main_map
from .submodules.Msm_46_3_layout_planner import LayoutPlanner
from .submodules.Msm_46_4_placement_strategy import (
    OutsidePlacement,
    choose_strategy,
)
from .submodules.Msm_46_types import (
    AvailableSpace,
    LegendContent,
    LegendItem,
    LegendLayoutMode,
    LegendResult,
)

__all__ = ['LegendManager']


class LegendManager:
    """
    Координатор работы с условными обозначениями (легендой) макета печати.

    Pipeline:
    1. _collect_content (input pipe) — читает QgsLayoutItemLegend.model().
    2. routing по `legend_layout_mode` из Base_layout:
       - OUTSIDE   → OutsidePlacement.apply (early return, без planner).
       - DYNAMIC / FIXED_PANEL → _build_space → _planner.plan → strategy.apply.
    3. _build_space строит AvailableSpace из legend_dynamic_* / legend_panel_*
       с sanity assert (для DYNAMIC проверяет, что legend_right + gap не
       пересекает overview_left).

    SpaceCalculator (Msm_46_2) фактически не задействован в pipeline (legacy).
    """

    def __init__(self) -> None:
        """Инициализация суб-менеджеров."""
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
        Полный цикл обработки легенды: routing → space → plan → apply.

        Маршрутизация по legend_layout_mode из Base_layout:
        - dynamic / fixed_panel: pipeline collect → build_space → plan → strategy.apply
        - outside: stub strategy без plan'а (layout без блока легенды)

        Crash-first: исключения из суб-менеджеров НЕ ловятся (RuntimeError при
        отсутствии или невалидности legend_layout_mode, KeyError при отсутствии
        обязательных полей).

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

            Успешный случай: LegendResult(success=True, mode_applied=...)
            от strategy.apply().

        Raises:
            RuntimeError: некорректный legend_layout_mode, отсутствующий
                config_key, overlap dynamic-легенды с overview_map.
            KeyError: отсутствуют обязательные поля legend_*_x / y / width_mm
                / height_max_mm / ref_point в Base_layout.
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

        # Чтение config через provider (M_34)
        from .submodules.Msm_46_2_space_calculator import _default_config_provider
        config = _default_config_provider(config_key)
        if config is None:
            raise RuntimeError(
                f"M_46: config_key '{config_key}' не найден в Base_layout.json"
            )

        # Routing по legend_layout_mode (явный flag из Excel)
        mode = config.get('legend_layout_mode')
        if not LegendLayoutMode.is_valid(mode):
            raise RuntimeError(
                f"M_46: некорректный legend_layout_mode='{mode}' для "
                f"config_key='{config_key}' (допустимо: {LegendLayoutMode.ALL})"
            )
        log_info(f"M_46: режим {mode} для config_key={config_key}")

        # Outside — early return через stub strategy, без planner'а
        if mode == LegendLayoutMode.OUTSIDE:
            return OutsidePlacement().apply(layout, plan=None)

        # Dynamic / fixed_panel — общий pipeline
        space = self._build_space(config, mode)
        log_info(
            f"M_46: AvailableSpace {space.max_width_mm:.0f}x"
            f"{space.max_height_mm:.0f} мм для {mode} "
            f"(anchor {space.legend_anchor_x:.0f},"
            f"{space.legend_anchor_y:.0f}, ref={space.legend_ref_point})"
        )

        # Сбор содержимого
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

        strategy = choose_strategy(mode)
        result = strategy.apply(layout, plan)

        log_info(
            f"M_46: Применено mode={result.mode_applied}, "
            f"h={result.height_mm:.0f} мм, success={result.success}"
        )
        return result

    # =========================================================================
    # Приватные методы
    # =========================================================================

    def _build_space(self, config: dict, mode: str) -> AvailableSpace:
        """Построить AvailableSpace из явных полей Base_layout по режиму.

        Для dynamic — читает legend_dynamic_*. Для fixed_panel — legend_panel_*.
        Для outside — RuntimeError (outside перехватывается раньше в plan_and_apply).

        Sanity assert для dynamic режима: проверяет что legend_right + gap не
        пересекает overview_left. Защищает от silent breakage при изменении
        геометрии main/overview без обновления legend_dynamic_width_mm.
        Корректно для ref_point=1 (LowerLeft) — текущие A4_DPT макеты используют
        именно его.

        Args:
            config: словарь конфигурации макета из Base_layout.json
            mode: значение LegendLayoutMode (DYNAMIC / FIXED_PANEL)

        Returns:
            AvailableSpace с явными полями bbox легенды

        Raises:
            ValueError: при mode=OUTSIDE (вызов должен быть исключён facade-логикой)
                либо при неизвестном mode
            RuntimeError: при overlap dynamic-легенды с overview_map (sanity)
            KeyError: при отсутствии обязательных полей legend_*_x/y/
                width_mm/height_max_mm/ref_point
        """
        if mode == LegendLayoutMode.OUTSIDE:
            raise ValueError(
                "M_46._build_space: outside режим не имеет AvailableSpace "
                "(вызов должен быть исключён через early return в plan_and_apply)"
            )
        prefix_map = {
            LegendLayoutMode.DYNAMIC: 'legend_dynamic_',
            LegendLayoutMode.FIXED_PANEL: 'legend_panel_',
        }
        if mode not in prefix_map:
            raise ValueError(f"M_46._build_space: неизвестный mode='{mode}'")
        prefix = prefix_map[mode]
        anchor_x = float(config[f'{prefix}x'])
        anchor_y = float(config[f'{prefix}y'])
        width_mm = float(config[f'{prefix}width_mm'])
        height_max_mm = float(config[f'{prefix}height_max_mm'])
        ref_point = int(config[f'{prefix}ref_point'])

        # Sanity assert для dynamic: legend не должен пересекаться с overview_map
        # по геометрии. Только для ref_point=1 (LowerLeft) — anchor_x = legend_left.
        if mode == LegendLayoutMode.DYNAMIC and 'overview_map_x' in config:
            if ref_point == 1:
                legend_right = anchor_x + width_mm
                gap = float(config.get('legend_dynamic_overlay_gap_mm', 5))
                overview_x = float(config['overview_map_x'])
                overview_w = float(config.get('overview_map_width', 0))
                overview_ref = int(config.get('overview_map_ref_point', 3))
                # ref_point=3 (LowerRight) → overview_x = правый край
                # ref_point=1 (LowerLeft)  → overview_x = левый край
                if overview_ref == 3:
                    overview_left = overview_x - overview_w
                else:
                    overview_left = overview_x
                if legend_right + gap > overview_left:
                    raise RuntimeError(
                        f"M_46: legend_dynamic_width_mm={width_mm} приведёт к "
                        f"overlap с overview_map (legend_right={legend_right} + "
                        f"gap={gap} > overview_left={overview_left})"
                    )

        return AvailableSpace(
            max_width_mm=width_mm,
            max_height_mm=height_max_mm,
            legend_anchor_x=anchor_x,
            legend_anchor_y=anchor_y,
            legend_ref_point=ref_point,
        )

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
