# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_46_4 — Тесты Msm_46_4_PlacementStrategy.

Покрытие:
- Импорт модуля (PlacementStrategy ABC, DynamicPlacement, OutsidePlacement, choose_strategy)
- ABC не инстанцируется напрямую
- choose_strategy('dynamic') → DynamicPlacement
- choose_strategy('outside') → OutsidePlacement
- choose_strategy unknown → ValueError с префиксом Msm_46_4
- DynamicPlacement.apply применяет column_count, symbol_width/height
- DynamicPlacement.apply применяет wrap к title через customProperty
- DynamicPlacement.apply без legend → success=False, warning
- OutsidePlacement.apply (smoke) → stub: success=False, mode_applied='outside_stub'
"""

from typing import Any


class TestMsm464:
    """Тесты Msm_46_4 PlacementStrategy (DynamicPlacement + OutsidePlacement stub)."""

    def __init__(self, iface: Any, logger: Any) -> None:
        self.iface = iface
        self.logger = logger

    def run_all_tests(self) -> None:
        """Entry point для comprehensive runner."""
        self.logger.section("ТЕСТ Msm_46_4: PlacementStrategy")

        try:
            self.test_01_import()
            self.test_02_abc_not_instantiable()
            self.test_03_choose_strategy_inline()
            self.test_04_choose_strategy_overflow()
            self.test_05_choose_strategy_unknown_raises()
            self.test_06_inline_applies_column_and_symbol()
            self.test_07_inline_applies_wrap_to_title()
            self.test_08_inline_missing_legend_returns_failure()
            self.test_09_overflow_stub_smoke()
        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов Msm_46_4: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    # === Helpers ===

    def _new_layout(self):
        from qgis.core import QgsPrintLayout, QgsProject
        layout = QgsPrintLayout(QgsProject.instance())
        layout.initializeDefaults()
        return layout

    def _layout_with_legend_and_layer(self, title: str):
        """
        Создать layout с QgsLayoutItemLegend, содержащей одну memory layer.

        Returns: (layout, legend, layer) для последующей очистки.
        """
        from qgis.core import (
            QgsLayoutItemLegend, QgsProject, QgsVectorLayer,
        )
        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326", "test_layer_T46_4", "memory"
        )
        QgsProject.instance().addMapLayer(layer)

        layout = self._new_layout()
        legend = QgsLayoutItemLegend(layout)
        legend.setId('legend')
        legend.setAutoUpdateModel(False)

        model = legend.model()
        root = model.rootGroup()
        root.removeAllChildren()
        node = root.addLayer(layer)
        node.setCustomProperty("legend/title-label", title)
        layout.addLayoutItem(legend)

        return layout, legend, layer

    def _make_plan(
        self,
        mode: str = 'dynamic',
        wrap_length: int = 30,
        column_count: int = 2,
        symbol_width: float = 12.0,
        symbol_height: float = 4.0,
        reason=None,
    ):
        from Daman_QGIS.managers.styling.submodules.Msm_46_types import LegendPlan
        return LegendPlan(
            mode=mode,
            wrap_length=wrap_length,
            column_count=column_count,
            symbol_width=symbol_width,
            symbol_height=symbol_height,
            predicted_width_mm=100.0,
            predicted_height_mm=50.0,
            width_mm=130.0,
            height_max_mm=80.0,
            reason=reason,
        )

    # === Группа 1: Импорт + ABC ===

    def test_01_import(self) -> None:
        """ТЕСТ 1: Импорт PlacementStrategy, DynamicPlacement, OutsidePlacement, choose_strategy."""
        self.logger.section("1. Импорт модуля")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_4_placement_strategy import (
                PlacementStrategy, DynamicPlacement, OutsidePlacement, choose_strategy,
            )
            self.logger.check(
                all([
                    PlacementStrategy is not None,
                    callable(DynamicPlacement),
                    callable(OutsidePlacement),
                    callable(choose_strategy),
                ]),
                "Все сущности импортированы",
                "Один из импортов провалился",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка импорта: {e}")

    def test_02_abc_not_instantiable(self) -> None:
        """ТЕСТ 2: PlacementStrategy (ABC) нельзя инстанцировать напрямую."""
        self.logger.section("2. ABC PlacementStrategy")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_4_placement_strategy import (
                PlacementStrategy,
            )
            raised = False
            try:
                PlacementStrategy()
            except TypeError:
                raised = True
            self.logger.check(
                raised,
                "PlacementStrategy() → TypeError (ABC не инстанцируется)",
                "ABC инстанцировался без исключения",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    # === Группа 2: choose_strategy ===

    def test_03_choose_strategy_inline(self) -> None:
        """ТЕСТ 3: choose_strategy('dynamic') → DynamicPlacement."""
        self.logger.section("3. choose_strategy dynamic")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_4_placement_strategy import (
                choose_strategy, DynamicPlacement,
            )
            s = choose_strategy('dynamic')
            self.logger.check(
                isinstance(s, DynamicPlacement),
                f"choose_strategy('dynamic') → {type(s).__name__}",
                f"Ожидался DynamicPlacement, получено {type(s).__name__}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_04_choose_strategy_overflow(self) -> None:
        """ТЕСТ 4: choose_strategy('outside') → OutsidePlacement."""
        self.logger.section("4. choose_strategy outside")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_4_placement_strategy import (
                choose_strategy, OutsidePlacement,
            )
            s = choose_strategy('outside')
            self.logger.check(
                isinstance(s, OutsidePlacement),
                f"choose_strategy('outside') → {type(s).__name__}",
                f"Ожидался OutsidePlacement, получено {type(s).__name__}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_05_choose_strategy_unknown_raises(self) -> None:
        """ТЕСТ 5: choose_strategy('unknown') → ValueError с Msm_46_4."""
        self.logger.section("5. choose_strategy unknown")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_4_placement_strategy import (
                choose_strategy,
            )
            raised = False
            msg = ""
            try:
                choose_strategy('unknown_mode')
            except ValueError as e:
                raised = True
                msg = str(e)
            self.logger.check(
                raised and 'Msm_46_4' in msg,
                f"ValueError с префиксом: {msg}",
                f"Исключение не брошено/без префикса: raised={raised}, msg={msg}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    # === Группа 3: DynamicPlacement.apply ===

    def test_06_inline_applies_column_and_symbol(self) -> None:
        """ТЕСТ 6: DynamicPlacement.apply применяет columnCount, symbolWidth/Height."""
        self.logger.section("6. DynamicPlacement: column/symbol")
        try:
            from qgis.core import QgsProject
            from Daman_QGIS.managers.styling.submodules.Msm_46_4_placement_strategy import (
                DynamicPlacement,
            )
            layout, legend, layer = self._layout_with_legend_and_layer("Слой")
            try:
                plan = self._make_plan(
                    column_count=2, symbol_width=12, symbol_height=4,
                )
                result = DynamicPlacement().apply(layout, plan)
                self.logger.check(
                    result.success is True,
                    f"LegendResult.success={result.success}",
                    f"Ожидался success=True, получено {result.success} ({result.warning})",
                )
                self.logger.check(
                    legend.columnCount() == 2
                    and abs(legend.symbolWidth() - 12) < 0.1
                    and abs(legend.symbolHeight() - 4) < 0.1,
                    f"col={legend.columnCount()}, sym="
                    f"{legend.symbolWidth()}x{legend.symbolHeight()}",
                    f"Параметры не применены: col={legend.columnCount()}, "
                    f"w={legend.symbolWidth()}, h={legend.symbolHeight()}",
                )
            finally:
                QgsProject.instance().removeMapLayer(layer.id())
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_07_inline_applies_wrap_to_title(self) -> None:
        """ТЕСТ 7: DynamicPlacement.apply оборачивает длинный title через \\n."""
        self.logger.section("7. DynamicPlacement: wrap title")
        try:
            from qgis.core import QgsProject
            from Daman_QGIS.managers.styling.submodules.Msm_46_4_placement_strategy import (
                DynamicPlacement,
            )
            long_title = (
                "Очень длинное название слоя границ земельных участков "
                "для проверки переноса"
            )
            layout, legend, layer = self._layout_with_legend_and_layer(long_title)
            try:
                plan = self._make_plan(wrap_length=20)
                DynamicPlacement().apply(layout, plan)

                # Проверяем что title был обёрнут
                wrapped_found = False
                for node in legend.model().rootGroup().children():
                    layer_attr = getattr(node, 'layer', None)
                    if layer_attr is None:
                        continue
                    lobj = layer_attr() if callable(layer_attr) else layer_attr
                    if lobj is None:
                        continue
                    wrapped = node.customProperty("legend/title-label")
                    if isinstance(wrapped, str) and '\n' in wrapped:
                        wrapped_found = True
                        break
                self.logger.check(
                    wrapped_found,
                    "Title обёрнут через \\n",
                    "Title не был обёрнут (customProperty без \\n)",
                )
            finally:
                QgsProject.instance().removeMapLayer(layer.id())
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_08_inline_missing_legend_returns_failure(self) -> None:
        """ТЕСТ 8: DynamicPlacement.apply без legend → LegendResult(success=False)."""
        self.logger.section("8. DynamicPlacement: нет legend")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_4_placement_strategy import (
                DynamicPlacement,
            )
            empty_layout = self._new_layout()
            plan = self._make_plan()
            result = DynamicPlacement().apply(empty_layout, plan)
            self.logger.check(
                result.success is False and result.warning is not None,
                f"success={result.success}, warning={result.warning}",
                f"Ожидался success=False с warning, получено {result}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    # === Группа 4: OutsidePlacement smoke ===

    def test_09_overflow_stub_smoke(self) -> None:
        """ТЕСТ 9: OutsidePlacement.apply — stub: success=False, mode_applied='outside_stub'."""
        self.logger.section("9. OutsidePlacement: stub smoke")
        try:
            from qgis.core import QgsProject
            from Daman_QGIS.managers.styling.submodules.Msm_46_4_placement_strategy import (
                OutsidePlacement,
            )
            layout, legend, layer = self._layout_with_legend_and_layer("Слой 1")
            try:
                plan = self._make_plan(mode='outside', reason='test_outside')
                result = OutsidePlacement().apply(layout, plan)
                self.logger.check(
                    result.success is False
                    and result.mode_applied == 'outside_stub',
                    f"mode_applied={result.mode_applied}, success={result.success}",
                    f"OutsidePlacement stub не отработал: {result}",
                )
                self.logger.check(
                    result.warning is not None
                    and 'stub' in result.warning.lower(),
                    f"warning содержит 'stub': {result.warning}",
                    f"warning без 'stub': {result.warning}",
                )
            finally:
                QgsProject.instance().removeMapLayer(layer.id())
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")
