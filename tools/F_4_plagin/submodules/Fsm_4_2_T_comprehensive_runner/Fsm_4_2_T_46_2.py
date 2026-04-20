# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_46_2 — Тесты Msm_46_2_SpaceCalculator.

OPT-5 (adversarial consensus): тесты через СИНТЕТИЧЕСКИЙ config dict
(dependency injection via config_provider), НЕ читают Base_layout.json
через registry. Проверяют ФОРМУЛУ
`max_width = nearest_right_left_edge - legend_x - gap`, не конкретные
числа из Excel (числа = "начальное приближение", будут калиброваться).

Покрытие:
- Импорт модуля
- Формула width при наличии overlay справа
- Fallback на page_width при отсутствии overlay справа
- Overlay слева от legend игнорируется
- max_height = main_map_height * height_ratio
- RuntimeError при unknown config_key
- Учёт ref_point для overlay bbox
- _item_bbox возвращает None при отсутствии ключей
"""

from typing import Any


class TestMsm462:
    """Тесты Msm_46_2 SpaceCalculator (синтетический config, формульная проверка)."""

    def __init__(self, iface: Any, logger: Any) -> None:
        self.iface = iface
        self.logger = logger

    def run_all_tests(self) -> None:
        """Entry point для comprehensive runner."""
        self.logger.section("ТЕСТ Msm_46_2: SpaceCalculator")

        try:
            self.test_01_import()
            self.test_02_formula_width_with_overview_right()
            self.test_03_no_overview_uses_page_margin()
            self.test_04_overview_left_of_legend_ignored()
            self.test_05_max_height_formula()
            self.test_06_raises_on_unknown_config_key()
            self.test_07_ref_point_affects_bbox()
            self.test_08_item_bbox_none_when_keys_missing()
            self.test_09_nearest_right_overlay_wins()
        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов Msm_46_2: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    # === Helpers ===

    def _empty_layout(self):
        """Создать пустой QgsPrintLayout с initialized defaults."""
        from qgis.core import QgsPrintLayout, QgsProject
        layout = QgsPrintLayout(QgsProject.instance())
        layout.initializeDefaults()
        return layout

    # === Группа 1: Импорт ===

    def test_01_import(self) -> None:
        """ТЕСТ 1: Импорт Msm_46_2_SpaceCalculator."""
        self.logger.section("1. Импорт модуля")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_2_space_calculator import (
                SpaceCalculator,
            )
            from Daman_QGIS.managers.styling.submodules.Msm_46_types import (
                AvailableSpace,
            )
            self.logger.check(
                callable(SpaceCalculator) and AvailableSpace is not None,
                "SpaceCalculator и AvailableSpace импортированы",
                "Импорт провалился",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка импорта: {e}")

    # === Группа 2: Формула ширины ===

    def test_02_formula_width_with_overview_right(self) -> None:
        """ТЕСТ 2: max_width = overview_left_edge - legend_x - gap."""
        self.logger.section("2. Формула width при overlay справа")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_2_space_calculator import (
                SpaceCalculator,
            )
            from Daman_QGIS.managers.styling.submodules.Msm_46_types import (
                AvailableSpace,
            )

            synthetic = {
                'legend_x': 20, 'legend_y': 205, 'legend_ref_point': 1,
                'overview_map_x': 200, 'overview_map_y': 205,
                'overview_map_width': 50, 'overview_map_height': 50,
                'overview_map_ref_point': 3,  # LowerRight → top-left=(150,155)
                'legend_overlay_gap_mm': 5,
                'main_map_height': 100,
                'legend_max_height_ratio': 0.45,
            }
            calc = SpaceCalculator(config_provider=lambda k: synthetic)
            space = calc.calculate(self._empty_layout(), 'synthetic_A4')

            expected_w = (
                synthetic['overview_map_x']
                - synthetic['overview_map_width']
                - synthetic['legend_x']
                - synthetic['legend_overlay_gap_mm']
            )
            self.logger.check(
                isinstance(space, AvailableSpace),
                "calculate вернул AvailableSpace",
                f"Ожидался AvailableSpace, получено {type(space)}",
            )
            self.logger.check(
                abs(space.max_width_mm - expected_w) < 0.001,
                f"max_width={space.max_width_mm:.2f}, ожидалось {expected_w:.2f}",
                f"Формула width нарушена: {space.max_width_mm:.2f} != {expected_w:.2f}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_03_no_overview_uses_page_margin(self) -> None:
        """ТЕСТ 3: Нет overlay справа → max_width = page_width - legend_x - margin."""
        self.logger.section("3. Fallback на page_width без overlay")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_2_space_calculator import (
                SpaceCalculator,
            )

            synthetic = {
                'legend_x': 20, 'legend_y': 205, 'legend_ref_point': 1,
                'page_width': 297, 'margin_right_mm': 10,
                'main_map_height': 170,
                'legend_max_height_ratio': 0.45,
            }
            calc = SpaceCalculator(config_provider=lambda k: synthetic)
            space = calc.calculate(self._empty_layout(), 'synthetic_no_overview')

            expected = 297 - 20 - 10
            self.logger.check(
                abs(space.max_width_mm - expected) < 0.001,
                f"max_width={space.max_width_mm:.2f} = page_width-legend_x-margin={expected}",
                f"Fallback формула нарушена: {space.max_width_mm} != {expected}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_04_overview_left_of_legend_ignored(self) -> None:
        """ТЕСТ 4: Overlay слева от legend не участвует в расчёте max_width."""
        self.logger.section("4. Overlay слева игнорируется")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_2_space_calculator import (
                SpaceCalculator,
            )

            synthetic = {
                'legend_x': 100, 'legend_y': 205, 'legend_ref_point': 1,
                'overview_map_x': 40, 'overview_map_y': 205,
                'overview_map_width': 30, 'overview_map_height': 30,
                'overview_map_ref_point': 3,  # LowerRight → top-left=(10,175), right=40
                'page_width': 297, 'margin_right_mm': 5,
                'legend_overlay_gap_mm': 5,
                'main_map_height': 100,
                'legend_max_height_ratio': 0.45,
            }
            calc = SpaceCalculator(config_provider=lambda k: synthetic)
            space = calc.calculate(self._empty_layout(), 'synthetic_left_overlay')

            # overview right=40 < legend_x=100 → игнорируется
            expected = 297 - 100 - 5
            self.logger.check(
                abs(space.max_width_mm - expected) < 0.001,
                f"Overlay слева игнорирован, max_width={space.max_width_mm:.2f}",
                f"Overlay слева НЕ был проигнорирован: {space.max_width_mm} != {expected}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    # === Группа 3: Формула высоты ===

    def test_05_max_height_formula(self) -> None:
        """ТЕСТ 5: max_height = main_map_height * height_ratio."""
        self.logger.section("5. Формула height")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_2_space_calculator import (
                SpaceCalculator,
            )

            synthetic = {
                'legend_x': 20, 'legend_y': 205, 'legend_ref_point': 1,
                'page_width': 297, 'margin_right_mm': 5,
                'main_map_height': 150,
                'legend_max_height_ratio': 0.4,
            }
            calc = SpaceCalculator(config_provider=lambda k: synthetic)
            space = calc.calculate(self._empty_layout(), 'synthetic_height')

            expected = 150 * 0.4
            self.logger.check(
                abs(space.max_height_mm - expected) < 0.001,
                f"max_height={space.max_height_mm:.2f} = 150*0.4={expected}",
                f"Формула height нарушена: {space.max_height_mm} != {expected}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    # === Группа 4: Ошибки ===

    def test_06_raises_on_unknown_config_key(self) -> None:
        """ТЕСТ 6: config_provider → None → RuntimeError с префиксом Msm_46_2."""
        self.logger.section("6. RuntimeError на unknown config_key")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_2_space_calculator import (
                SpaceCalculator,
            )

            calc = SpaceCalculator(config_provider=lambda k: None)
            raised = False
            msg = ""
            try:
                calc.calculate(self._empty_layout(), 'A2_unknown')
            except RuntimeError as e:
                raised = True
                msg = str(e)
            self.logger.check(
                raised and 'Msm_46_2' in msg and 'A2_unknown' in msg,
                f"RuntimeError с корректным сообщением: {msg}",
                f"Исключение не брошено/некорректно: raised={raised}, msg={msg}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    # === Группа 5: ref_point ===

    def test_07_ref_point_affects_bbox(self) -> None:
        """ТЕСТ 7: ref_point=7 (TopLeft) vs ref_point=3 (LowerRight) → разные bbox."""
        self.logger.section("7. ref_point влияет на bbox")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_2_space_calculator import (
                SpaceCalculator,
            )

            # ref_point=7 (TopLeft): top-left = (x, y) = (200, 205), right=250
            config_topleft = {
                'legend_x': 20, 'legend_y': 205, 'legend_ref_point': 1,
                'overview_map_x': 200, 'overview_map_y': 205,
                'overview_map_width': 50, 'overview_map_height': 50,
                'overview_map_ref_point': 7,  # TopLeft
                'legend_overlay_gap_mm': 5,
                'main_map_height': 100,
                'legend_max_height_ratio': 0.45,
            }
            calc = SpaceCalculator(config_provider=lambda k: config_topleft)
            space_tl = calc.calculate(self._empty_layout(), 'tl')
            # nearest_right = 200 (left edge), max_width = 200-20-5 = 175
            expected_tl = 200 - 20 - 5

            # ref_point=3 (LowerRight): top-left = (150, 155), left=150
            config_lr = dict(config_topleft)
            config_lr['overview_map_ref_point'] = 3
            calc2 = SpaceCalculator(config_provider=lambda k: config_lr)
            space_lr = calc2.calculate(self._empty_layout(), 'lr')
            # nearest_right = 150, max_width = 150-20-5 = 125
            expected_lr = 150 - 20 - 5

            self.logger.check(
                abs(space_tl.max_width_mm - expected_tl) < 0.001
                and abs(space_lr.max_width_mm - expected_lr) < 0.001
                and space_tl.max_width_mm != space_lr.max_width_mm,
                f"ref=7 → {space_tl.max_width_mm:.1f}, ref=3 → {space_lr.max_width_mm:.1f}",
                f"ref_point не влияет или формула неверна: "
                f"tl={space_tl.max_width_mm} (exp {expected_tl}), "
                f"lr={space_lr.max_width_mm} (exp {expected_lr})",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_08_item_bbox_none_when_keys_missing(self) -> None:
        """ТЕСТ 8: Отсутствующие overlay ключи не ломают расчёт."""
        self.logger.section("8. Missing keys → overlay игнорируется")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_2_space_calculator import (
                SpaceCalculator,
            )

            # Только legend + page_width, без overlay
            synthetic = {
                'legend_x': 20, 'legend_y': 205, 'legend_ref_point': 1,
                'page_width': 420, 'margin_right_mm': 10,
                'main_map_height': 100,
                'legend_max_height_ratio': 0.45,
                # overview_map_* и прочие НЕ заданы
            }
            calc = SpaceCalculator(config_provider=lambda k: synthetic)
            space = calc.calculate(self._empty_layout(), 'synthetic_minimal')

            expected = 420 - 20 - 10
            self.logger.check(
                abs(space.max_width_mm - expected) < 0.001,
                f"Отсутствующие overlay keys не сломали расчёт ({space.max_width_mm:.1f})",
                f"Missing keys сломали расчёт: {space.max_width_mm} != {expected}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_09_nearest_right_overlay_wins(self) -> None:
        """ТЕСТ 9: Из нескольких overlay справа выбирается ближайший (min left)."""
        self.logger.section("9. Выбор ближайшего overlay справа")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_2_space_calculator import (
                SpaceCalculator,
            )

            # overview справа с left=150, north_arrow справа с left=120
            # → nearest_right = 120 (меньше = ближе)
            synthetic = {
                'legend_x': 20, 'legend_y': 205, 'legend_ref_point': 1,
                'overview_map_x': 150, 'overview_map_y': 205,
                'overview_map_width': 40, 'overview_map_height': 40,
                'overview_map_ref_point': 7,  # TopLeft → left=150
                'north_arrow_x': 120, 'north_arrow_y': 205,
                'north_arrow_width': 20, 'north_arrow_height': 20,
                'north_arrow_ref_point': 7,  # TopLeft → left=120
                'legend_overlay_gap_mm': 5,
                'main_map_height': 100,
                'legend_max_height_ratio': 0.45,
            }
            calc = SpaceCalculator(config_provider=lambda k: synthetic)
            space = calc.calculate(self._empty_layout(), 'synthetic_multi_right')

            # nearest = 120, max_width = 120-20-5 = 95
            expected = 120 - 20 - 5
            self.logger.check(
                abs(space.max_width_mm - expected) < 0.001,
                f"Ближайший overlay (north_arrow) выбран, max_width={space.max_width_mm:.1f}",
                f"Неправильный overlay: {space.max_width_mm} != {expected}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")
