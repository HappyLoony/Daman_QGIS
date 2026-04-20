# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_34_2 - Интеграционный тест Msm_34_2 ExtentShifter.

Ответственность ExtentShifter (после Task 7 рефакторинга M_46):
- Измерить фактическую геометрию легенды после применения плана M_46
  (measurement pass через exportToImage).
- Сдвинуть экстент main_map так, чтобы safe_fraction площади оставалась
  свободной от overlay легенды (территория сверху, подложка снизу).

НЕ входит в ответственность ExtentShifter (вынесено в M_46 / Msm_46_3):
- Цикл по column_count (1 -> 2 -> 3)
- Подбор symbol_size (fallback 10x3.5)
- Вычисление ширины легенды (Msm_46_2 SpaceCalculator)

Характеризационный инвариант (Risk-6 Stabilizer):
    safe_fraction = (map_height - legend_height) / map_height
    safe_fraction = clamp(safe_fraction, 0.3, 0.95)

Покрытие:
- Импорт ExtentShifter из Msm_34_2_extent_shifter
- Отсутствие legend -> log_warning + return False (нет crash)
- Отсутствие main_map -> log_warning + return False (нет crash)
- В упрощённом классе нет атрибутов MAX_COLUMNS / REDUCED_SYMBOL_*
  (guard против возврата удалённой логики)
"""

from typing import Any


class TestFsm4234_2:
    """Интеграционный тест Msm_34_2 ExtentShifter (упрощённый после M_46)."""

    def __init__(self, iface: Any, logger: Any) -> None:
        self.iface = iface
        self.logger = logger

    def run_all_tests(self) -> None:
        """Entry point для comprehensive runner."""
        self.logger.section("ТЕСТ Msm_34_2: ExtentShifter (shift extent only)")

        try:
            self.test_01_import()
            self.test_02_no_legend_returns_false()
            self.test_03_no_main_map_returns_false()
            self.test_04_no_column_count_loop_attrs()
            self.test_05_safe_fraction_invariant()
        except Exception as e:
            self.logger.error(
                f"Критическая ошибка тестов Msm_34_2: {str(e)}"
            )
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    # === Helpers ===

    def _new_layout(self):
        """Пустой QgsPrintLayout с initialized defaults."""
        from qgis.core import QgsPrintLayout, QgsProject
        layout = QgsPrintLayout(QgsProject.instance())
        layout.initializeDefaults()
        return layout

    def _add_main_map(self, layout):
        """Добавить QgsLayoutItemMap с id='main_map'."""
        from qgis.core import QgsLayoutItemMap
        mmap = QgsLayoutItemMap(layout)
        mmap.setId('main_map')
        layout.addLayoutItem(mmap)
        return mmap

    def _add_legend(self, layout):
        """Добавить QgsLayoutItemLegend с id='legend' (пустой)."""
        from qgis.core import QgsLayoutItemLegend
        legend = QgsLayoutItemLegend(layout)
        legend.setId('legend')
        legend.setAutoUpdateModel(False)
        legend.model().rootGroup().removeAllChildren()
        layout.addLayoutItem(legend)
        return legend

    # === Тесты ===

    def test_01_import(self) -> None:
        """ТЕСТ 1: Импорт ExtentShifter из Msm_34_2_extent_shifter."""
        self.logger.section("1. Импорт ExtentShifter")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_34_2_extent_shifter import (
                ExtentShifter,
            )
            shifter = ExtentShifter()
            has_api = hasattr(shifter, 'shift_extent_for_legend') and callable(
                shifter.shift_extent_for_legend
            )
            self.logger.check(
                has_api,
                "ExtentShifter импортирован, shift_extent_for_legend доступен",
                "Импорт/атрибуты провалились",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка импорта: {e}")

    def test_02_no_legend_returns_false(self) -> None:
        """ТЕСТ 2: Нет QgsLayoutItemLegend -> return False (не crash)."""
        self.logger.section("2. Missing legend -> False")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_34_2_extent_shifter import (
                ExtentShifter,
            )

            layout = self._new_layout()
            self._add_main_map(layout)
            # Легенда НЕ добавлена

            shifter = ExtentShifter()
            result = shifter.shift_extent_for_legend(layout)

            self.logger.check(
                result is False,
                "shift_extent_for_legend вернул False для layout без legend",
                f"Ожидался False, получен {result}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_03_no_main_map_returns_false(self) -> None:
        """ТЕСТ 3: Нет QgsLayoutItemMap id='main_map' -> return False."""
        self.logger.section("3. Missing main_map -> False")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_34_2_extent_shifter import (
                ExtentShifter,
            )

            layout = self._new_layout()
            # main_map НЕ добавлен
            self._add_legend(layout)

            shifter = ExtentShifter()
            result = shifter.shift_extent_for_legend(layout)

            self.logger.check(
                result is False,
                "shift_extent_for_legend вернул False для layout без main_map",
                f"Ожидался False, получен {result}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_04_no_column_count_loop_attrs(self) -> None:
        """
        ТЕСТ 4: Guard против возврата удалённой логики.

        После Task 7 в ExtentShifter НЕ должно быть констант column_count
        цикла и symbol_size fallback — они вынесены в Msm_46_3.
        """
        self.logger.section("4. No column_count/symbol_size leftovers")
        try:
            from Daman_QGIS.managers.styling.submodules import (
                Msm_34_2_extent_shifter as mod,
            )

            removed_attrs = [
                'MAX_COLUMNS',
                'REDUCED_SYMBOL_WIDTH',
                'REDUCED_SYMBOL_HEIGHT',
                'DEFAULT_SYMBOL_WIDTH',
                'DEFAULT_SYMBOL_HEIGHT',
            ]
            cls = getattr(mod, 'ExtentShifter', None)
            leftovers = [
                a for a in removed_attrs
                if cls is not None and hasattr(cls, a)
            ]

            self.logger.check(
                cls is not None and not leftovers,
                "ExtentShifter не содержит column_count/symbol_size констант",
                f"Обнаружены удалённые атрибуты: {leftovers}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_05_safe_fraction_invariant(self) -> None:
        """
        ТЕСТ 5: Характеризационный инвариант safe_fraction.

        safe_fraction = (map_height - legend_height) / map_height,
        clamp в [0.3, 0.95]. Проверяем формулу изолированно
        (без вызова QGIS pipeline).
        """
        self.logger.section("5. safe_fraction invariant")
        try:
            cases = [
                # (map_h, leg_h, expected_safe_fraction)
                (200.0, 20.0, 0.90),   # 180/200 = 0.9
                (200.0, 50.0, 0.75),   # 150/200 = 0.75
                (200.0, 190.0, 0.30),  # 10/200 = 0.05 -> clamp 0.3
                (200.0, 0.0, 0.95),    # 200/200 = 1.0 -> clamp 0.95
                (100.0, 50.0, 0.50),   # ровно 0.5
            ]

            def compute(map_h: float, leg_h: float) -> float:
                raw = (map_h - leg_h) / map_h
                return max(0.3, min(raw, 0.95))

            mismatches = []
            for map_h, leg_h, expected in cases:
                got = compute(map_h, leg_h)
                if abs(got - expected) > 1e-6:
                    mismatches.append(
                        f"map={map_h}, leg={leg_h}: "
                        f"expected={expected}, got={got}"
                    )

            self.logger.check(
                not mismatches,
                f"safe_fraction формула корректна на {len(cases)} кейсах",
                f"Несовпадения: {mismatches}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")
