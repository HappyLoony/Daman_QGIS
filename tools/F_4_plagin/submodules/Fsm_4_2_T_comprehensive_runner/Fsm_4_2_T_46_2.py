# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_46_2 — Тесты Msm_46_2_SpaceCalculator (legacy thin-wrapper).

После рефакторинга legend_layout_modes (v0.4) `SpaceCalculator.calculate`
делегирует на `LegendManager._build_space(config, mode)`. Ширина/высота
берутся напрямую из config (`legend_dynamic_width_mm` /
`legend_panel_width_mm`) — старая формула neighbour-detection
(nearest_right_left_edge - legend_x - gap) удалена из production.

Соответственно тесты формулы (test_02..05, test_07..09 в исходной версии)
устарели и удалены. Производственный код M_46 не использует класс
SpaceCalculator (только функцию `_default_config_provider`), wrapper
сохранён для backward-compat внешних потребителей.

Покрытие (минимальное, регрессионное):
- test_01: импорт класса и AvailableSpace
- test_06: RuntimeError при unknown config_key (provider lambda k: None) —
  проверка контракта error-handling в legacy wrapper.
"""

from typing import Any


class TestMsm462:
    """Тесты Msm_46_2 SpaceCalculator (legacy thin-wrapper)."""

    def __init__(self, iface: Any, logger: Any) -> None:
        self.iface = iface
        self.logger = logger

    def run_all_tests(self) -> None:
        """Entry point для comprehensive runner."""
        self.logger.section("ТЕСТ Msm_46_2: SpaceCalculator")

        try:
            self.test_01_import()
            self.test_06_raises_on_unknown_config_key()
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

    # === Группа 2: Контракт error-handling ===

    def test_06_raises_on_unknown_config_key(self) -> None:
        """ТЕСТ 6: config_provider → None → RuntimeError с префиксом Msm_46_2.

        Проверка контракта legacy wrapper: при отсутствии config (provider
        вернул None) calculate должен бросать RuntimeError с понятным
        сообщением, содержащим префикс модуля и неизвестный key.
        """
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
