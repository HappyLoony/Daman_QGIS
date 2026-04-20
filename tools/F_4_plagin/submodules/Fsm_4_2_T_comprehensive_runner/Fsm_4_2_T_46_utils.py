# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_46_utils - Тестирование shared helpers Msm_46_utils.

Тестирует:
- find_legend: возвращает legend при наличии / None при отсутствии / custom id
- find_main_map: возвращает map при наличии / None при отсутствии / custom id
- numpad_to_offset: 1=LowerLeft, 5=Center, 9=UpperRight, unknown → (0, 0)
"""

from typing import Any


class TestMsm46Utils:
    """Тесты Msm_46_utils: find_legend, find_main_map, numpad_to_offset."""

    def __init__(self, iface: Any, logger: Any) -> None:
        self.iface = iface
        self.logger = logger

    def run_all_tests(self) -> None:
        """Entry point для comprehensive runner."""
        self.logger.section("ТЕСТ Msm_46_utils: shared helpers")

        try:
            self.test_01_import()
            self.test_02_find_legend_returns_legend_when_present()
            self.test_03_find_legend_returns_none_when_absent()
            self.test_04_find_legend_respects_custom_id()
            self.test_05_find_main_map_returns_map_when_present()
            self.test_06_find_main_map_returns_none_when_absent()
            self.test_07_find_main_map_respects_custom_id()
            self.test_08_numpad_to_offset_top_left()
            self.test_09_numpad_to_offset_lower_left()
            self.test_10_numpad_to_offset_upper_right()
            self.test_11_numpad_to_offset_center()
            self.test_12_numpad_to_offset_middle_right()
            self.test_13_numpad_to_offset_unknown_ref_defaults_to_topleft()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов Msm_46_utils: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    # === Helpers ===

    def _new_layout(self):
        """Создать пустой QgsPrintLayout с initialized defaults."""
        from qgis.core import QgsPrintLayout, QgsProject
        layout = QgsPrintLayout(QgsProject.instance())
        layout.initializeDefaults()
        return layout

    # === Группа 1: Импорт ===

    def test_01_import(self) -> None:
        """ТЕСТ 1: Импорт Msm_46_utils."""
        self.logger.section("1. Импорт модуля")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_utils import (
                find_legend, find_main_map, numpad_to_offset
            )
            self.logger.check(
                callable(find_legend) and callable(find_main_map) and callable(numpad_to_offset),
                "Все helpers импортированы и callable",
                "Один из helpers недоступен"
            )
        except Exception as e:
            self.logger.fail(f"Ошибка импорта: {e}")

    # === Группа 2: find_legend ===

    def test_02_find_legend_returns_legend_when_present(self) -> None:
        """ТЕСТ 2: find_legend возвращает legend при наличии."""
        self.logger.section("2. find_legend: legend присутствует")
        try:
            from qgis.core import QgsLayoutItemLegend
            from Daman_QGIS.managers.styling.submodules.Msm_46_utils import find_legend

            layout = self._new_layout()
            legend = QgsLayoutItemLegend(layout)
            legend.setId('legend')
            layout.addLayoutItem(legend)

            found = find_legend(layout)
            self.logger.check(
                found is legend,
                "find_legend вернул корректный объект",
                f"Ожидался legend, получено {found}"
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_03_find_legend_returns_none_when_absent(self) -> None:
        """ТЕСТ 3: find_legend возвращает None при отсутствии."""
        self.logger.section("3. find_legend: legend отсутствует")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_utils import find_legend

            layout = self._new_layout()
            result = find_legend(layout)
            self.logger.check(
                result is None,
                "find_legend вернул None",
                f"Ожидался None, получено {result}"
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_04_find_legend_respects_custom_id(self) -> None:
        """ТЕСТ 4: find_legend учитывает custom item_id."""
        self.logger.section("4. find_legend: custom id")
        try:
            from qgis.core import QgsLayoutItemLegend
            from Daman_QGIS.managers.styling.submodules.Msm_46_utils import find_legend

            layout = self._new_layout()
            legend = QgsLayoutItemLegend(layout)
            legend.setId('custom_legend')
            layout.addLayoutItem(legend)

            default_result = find_legend(layout)
            custom_result = find_legend(layout, item_id='custom_legend')

            self.logger.check(
                default_result is None,
                "find_legend(layout) = None для custom id",
                f"Ожидался None, получено {default_result}"
            )
            self.logger.check(
                custom_result is legend,
                "find_legend(layout, item_id='custom_legend') вернул legend",
                f"Ожидался legend, получено {custom_result}"
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    # === Группа 3: find_main_map ===

    def test_05_find_main_map_returns_map_when_present(self) -> None:
        """ТЕСТ 5: find_main_map возвращает map при наличии."""
        self.logger.section("5. find_main_map: map присутствует")
        try:
            from qgis.core import QgsLayoutItemMap
            from Daman_QGIS.managers.styling.submodules.Msm_46_utils import find_main_map

            layout = self._new_layout()
            mmap = QgsLayoutItemMap(layout)
            mmap.setId('main_map')
            layout.addLayoutItem(mmap)

            found = find_main_map(layout)
            self.logger.check(
                found is mmap,
                "find_main_map вернул корректный объект",
                f"Ожидался main_map, получено {found}"
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_06_find_main_map_returns_none_when_absent(self) -> None:
        """ТЕСТ 6: find_main_map возвращает None при отсутствии."""
        self.logger.section("6. find_main_map: map отсутствует")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_utils import find_main_map

            layout = self._new_layout()
            result = find_main_map(layout)
            self.logger.check(
                result is None,
                "find_main_map вернул None",
                f"Ожидался None, получено {result}"
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_07_find_main_map_respects_custom_id(self) -> None:
        """ТЕСТ 7: find_main_map учитывает custom item_id."""
        self.logger.section("7. find_main_map: custom id")
        try:
            from qgis.core import QgsLayoutItemMap
            from Daman_QGIS.managers.styling.submodules.Msm_46_utils import find_main_map

            layout = self._new_layout()
            mmap = QgsLayoutItemMap(layout)
            mmap.setId('overview_map')
            layout.addLayoutItem(mmap)

            default_result = find_main_map(layout)
            custom_result = find_main_map(layout, item_id='overview_map')

            self.logger.check(
                default_result is None and custom_result is mmap,
                "find_main_map корректно обрабатывает custom id",
                f"default={default_result}, custom={custom_result}"
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    # === Группа 4: numpad_to_offset ===

    def test_08_numpad_to_offset_top_left(self) -> None:
        """ТЕСТ 8: numpad_to_offset(7) = (0, 0) (TopLeft)."""
        self.logger.section("8. numpad_to_offset: ref=7 TopLeft")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_utils import numpad_to_offset
            dx, dy = numpad_to_offset(ref_point=7, width=100, height=50)
            self.logger.check(
                dx == 0.0 and dy == 0.0,
                f"ref=7 → ({dx}, {dy}), ожидалось (0, 0)",
                f"Ожидалось (0, 0), получено ({dx}, {dy})"
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_09_numpad_to_offset_lower_left(self) -> None:
        """ТЕСТ 9: numpad_to_offset(1) = (0, -h) (LowerLeft)."""
        self.logger.section("9. numpad_to_offset: ref=1 LowerLeft")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_utils import numpad_to_offset
            dx, dy = numpad_to_offset(ref_point=1, width=100, height=50)
            self.logger.check(
                dx == 0.0 and dy == -50.0,
                f"ref=1 → ({dx}, {dy}), ожидалось (0, -50)",
                f"Ожидалось (0, -50), получено ({dx}, {dy})"
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_10_numpad_to_offset_upper_right(self) -> None:
        """ТЕСТ 10: numpad_to_offset(9) = (-w, 0) (UpperRight)."""
        self.logger.section("10. numpad_to_offset: ref=9 UpperRight")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_utils import numpad_to_offset
            dx, dy = numpad_to_offset(ref_point=9, width=100, height=50)
            self.logger.check(
                dx == -100.0 and dy == 0.0,
                f"ref=9 → ({dx}, {dy}), ожидалось (-100, 0)",
                f"Ожидалось (-100, 0), получено ({dx}, {dy})"
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_11_numpad_to_offset_center(self) -> None:
        """ТЕСТ 11: numpad_to_offset(5) = (-w/2, -h/2) (Center)."""
        self.logger.section("11. numpad_to_offset: ref=5 Center")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_utils import numpad_to_offset
            dx, dy = numpad_to_offset(ref_point=5, width=100, height=50)
            self.logger.check(
                dx == -50.0 and dy == -25.0,
                f"ref=5 → ({dx}, {dy}), ожидалось (-50, -25)",
                f"Ожидалось (-50, -25), получено ({dx}, {dy})"
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_12_numpad_to_offset_middle_right(self) -> None:
        """ТЕСТ 12: numpad_to_offset(6) = (-w, -h/2) (MiddleRight)."""
        self.logger.section("12. numpad_to_offset: ref=6 MiddleRight")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_utils import numpad_to_offset
            dx, dy = numpad_to_offset(ref_point=6, width=100, height=50)
            self.logger.check(
                dx == -100.0 and dy == -25.0,
                f"ref=6 → ({dx}, {dy}), ожидалось (-100, -25)",
                f"Ожидалось (-100, -25), получено ({dx}, {dy})"
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_13_numpad_to_offset_unknown_ref_defaults_to_topleft(self) -> None:
        """ТЕСТ 13: numpad_to_offset(99) = (0, 0) fallback без исключения."""
        self.logger.section("13. numpad_to_offset: unknown ref")
        try:
            from Daman_QGIS.managers.styling.submodules.Msm_46_utils import numpad_to_offset
            dx, dy = numpad_to_offset(ref_point=99, width=100, height=50)
            self.logger.check(
                dx == 0.0 and dy == 0.0,
                f"ref=99 → ({dx}, {dy}), fallback на TopLeft (0, 0)",
                f"Ожидалось (0, 0), получено ({dx}, {dy})"
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")
