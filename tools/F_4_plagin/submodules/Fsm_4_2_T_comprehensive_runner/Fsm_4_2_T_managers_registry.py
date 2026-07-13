# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_managers_registry — Тесты логики сверки реестра менеджеров.

Покрытие (Часть B плана 2026-06-13-managers-registry-discipline):
- Чистая функция Msm_4_14._compare_registry(actual, documented, files_on_disk):
  - missing: менеджер в коде, но не в Base_managers
  - phantom: запись в Base_managers, но нет в коде
  - normalize id: documented собирается из manager_id="1" -> "M_1"
  - GUARD documented=None (offline / битый источник) -> НЕ «47 missing»,
    только not_registered-часть (локальная)
  - not_registered: файл M_*.py на диске есть, но менеджер не зарегистрирован
  - both empty -> пусто
  - числовая сортировка id ('M_10' после 'M_2', не лексикографически)

Сетью и QGIS-registry НЕ пользуется — тестирует только чистую логику сверки.
"""

from typing import Any, List, Optional


class TestManagersRegistry:
    """Тесты чистой логики сверки реестра менеджеров (_compare_registry)."""

    def __init__(self, iface: Any, logger: Any) -> None:
        self.iface = iface
        self.logger = logger

    def run_all_tests(self) -> None:
        """Entry point для comprehensive runner."""
        self.logger.section("ТЕСТ Msm_4_14: сверка реестра менеджеров")

        try:
            self.test_01_import()
            self.test_02_missing()
            self.test_03_phantom()
            self.test_04_normalize_id()
            self.test_05_guard_none()
            self.test_06_guard_empty()
            self.test_07_not_registered()
            self.test_08_both_empty()
            self.test_09_numeric_sort()
        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов реестра менеджеров: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    # === Группа 1: Импорт ===

    def test_01_import(self) -> None:
        """ТЕСТ 1: Импорт _compare_registry и validate_manager_registry."""
        self.logger.section("1. Импорт")
        try:
            from Daman_QGIS.managers.reference.submodules import (
                Msm_4_14_data_validation_manager as mod,
            )

            has_compare = hasattr(mod, '_compare_registry')
            has_method = hasattr(mod.DataValidationManager, 'validate_manager_registry')
            self.logger.check(
                has_compare and has_method,
                "_compare_registry + DataValidationManager.validate_manager_registry на месте",
                f"Отсутствует API: _compare_registry={has_compare}, "
                f"validate_manager_registry={has_method}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка импорта: {e}")

    # === Группа 2: Сверка с Base_managers ===

    def test_02_missing(self) -> None:
        """ТЕСТ 2: missing — менеджер в коде, но НЕ в Base_managers."""
        self.logger.section("2. missing")
        try:
            warnings = self._compare(
                actual={'M_1', 'M_36'},
                documented={'M_1'},
                files_on_disk={'M_1', 'M_36'},
            )
            joined = " | ".join(warnings)
            self.logger.check(
                any("M_36" in w and "НЕ в Base_managers" in w for w in warnings),
                f"missing найдено: {joined}",
                f"Ожидался варнинг про M_36 missing, получено: {joined}",
            )
            # M_1 задокументирован и зарегистрирован — не должен попасть в missing.
            self.logger.check(
                not any("M_1" in w and "НЕ в Base_managers" in w for w in warnings),
                "M_1 (документирован) не в missing",
                f"M_1 ошибочно попал в missing: {joined}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_03_phantom(self) -> None:
        """ТЕСТ 3: phantom — запись в Base_managers, но НЕТ в коде."""
        self.logger.section("3. phantom")
        try:
            warnings = self._compare(
                actual={'M_1'},
                documented={'M_1', 'M_99'},
                files_on_disk={'M_1'},
            )
            joined = " | ".join(warnings)
            self.logger.check(
                any("M_99" in w and "в коде НЕТ" in w for w in warnings),
                f"phantom найдено: {joined}",
                f"Ожидался варнинг про M_99 phantom, получено: {joined}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_04_normalize_id(self) -> None:
        """ТЕСТ 4: нормализация id — manager_id='1' -> 'M_1' совпадает с registry."""
        self.logger.section("4. normalize id")
        try:
            # Эмулируем сборку documented как в validate_manager_registry:
            # documented = {f"M_{r['manager_id']}" for r in base_managers}
            base_managers = [{'manager_id': '1'}, {'manager_id': '36'}]
            documented = {f"M_{r['manager_id']}" for r in base_managers}

            warnings = self._compare(
                actual={'M_1', 'M_36'},
                documented=documented,
                files_on_disk={'M_1', 'M_36'},
            )
            self.logger.check(
                warnings == [],
                "manager_id='1'/'36' -> 'M_1'/'M_36' совпали с registry (нет варнингов)",
                f"Ожидалось пусто (полное совпадение), получено: {warnings}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    # === Группа 3: GUARD недоступного Base_managers ===

    def test_05_guard_none(self) -> None:
        """ТЕСТ 5: documented=None (offline) -> НЕ «47 missing», только not_registered."""
        self.logger.section("5. GUARD None")
        try:
            # actual=files (всё зарегистрировано) -> not_registered пуст -> warnings пуст.
            warnings = self._compare(
                actual={'M_1', 'M_2', 'M_36'},
                documented=None,
                files_on_disk={'M_1', 'M_2', 'M_36'},
            )
            self.logger.check(
                warnings == [],
                "documented=None -> нет варнингов про Base_managers (нет ложных missing)",
                f"Ожидалось пусто (GUARD None), получено: {warnings}",
            )
            # Явная проверка: нет ни одного варнинга про Base_managers.
            self.logger.check(
                not any("Base_managers" in w or "в коде НЕТ" in w for w in warnings),
                "documented=None -> ни missing, ни phantom не считаются",
                f"При None ошибочно посчитана сверка с Base_managers: {warnings}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_06_guard_empty(self) -> None:
        """ТЕСТ 6: семантика [] обрабатывается на уровне метода (== None для _compare).

        В validate_manager_registry GUARD `if not base_managers` ловит и None, и [];
        в обоих случаях в _compare передаётся documented=None. Здесь подтверждаем,
        что documented=None при наличии not_registered даёт ТОЛЬКО not_registered-часть.
        """
        self.logger.section("6. GUARD пустой источник")
        try:
            warnings = self._compare(
                actual={'M_1'},
                documented=None,        # эквивалент base_managers=[] после GUARD
                files_on_disk={'M_1', 'M_50'},
            )
            joined = " | ".join(warnings)
            # not_registered должен сработать (M_50 на диске, не зарегистрирован).
            self.logger.check(
                any("M_50" in w and "НЕ зарегистрирован" in w for w in warnings),
                f"При пустом источнике not_registered работает: {joined}",
                f"Ожидался not_registered про M_50, получено: {joined}",
            )
            # И при этом никакой сверки с Base_managers.
            self.logger.check(
                not any("Base_managers" in w or "в коде НЕТ" in w for w in warnings),
                "При пустом источнике сверка с Base_managers пропущена",
                f"Ошибочно посчитана сверка с Base_managers: {joined}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    # === Группа 4: not_registered (локально, всегда) ===

    def test_07_not_registered(self) -> None:
        """ТЕСТ 7: not_registered — файл M_*.py на диске, но менеджер не в registry."""
        self.logger.section("7. not_registered")
        try:
            warnings = self._compare(
                actual={'M_1'},
                documented={'M_1'},
                files_on_disk={'M_1', 'M_50'},
            )
            joined = " | ".join(warnings)
            self.logger.check(
                any("M_50" in w and "НЕ зарегистрирован" in w for w in warnings),
                f"not_registered найдено: {joined}",
                f"Ожидался варнинг про M_50 not_registered, получено: {joined}",
            )
            # M_1 зарегистрирован — не в not_registered.
            self.logger.check(
                not any("M_1" in w and "НЕ зарегистрирован" in w for w in warnings),
                "M_1 (зарегистрирован) не в not_registered",
                f"M_1 ошибочно в not_registered: {joined}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    # === Группа 5: edge cases ===

    def test_08_both_empty(self) -> None:
        """ТЕСТ 8: всё совпадает (документировано+зарегистрировано) -> пусто."""
        self.logger.section("8. both empty")
        try:
            warnings = self._compare(
                actual={'M_1', 'M_2'},
                documented={'M_1', 'M_2'},
                files_on_disk={'M_1', 'M_2'},
            )
            self.logger.check(
                warnings == [],
                "Полное совпадение -> нет варнингов",
                f"Ожидалось пусто, получено: {warnings}",
            )
            # Пустые наборы тоже -> пусто.
            warnings_empty = self._compare(
                actual=set(),
                documented=set(),
                files_on_disk=set(),
            )
            self.logger.check(
                warnings_empty == [],
                "Все наборы пусты -> нет варнингов",
                f"Ожидалось пусто на пустых наборах, получено: {warnings_empty}",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    def test_09_numeric_sort(self) -> None:
        """ТЕСТ 9: id сортируются по числу ('M_10' после 'M_2', не лексикографически)."""
        self.logger.section("9. numeric sort")
        try:
            warnings = self._compare(
                actual={'M_2', 'M_10'},
                documented=set(),
                files_on_disk={'M_2', 'M_10'},
            )
            # M_2 и M_10 missing (в коде, не в Base_managers). Порядок: M_2, M_10.
            missing_w = next((w for w in warnings if "НЕ в Base_managers" in w), "")
            idx_2 = missing_w.find("M_2")
            idx_10 = missing_w.find("M_10")
            self.logger.check(
                idx_2 != -1 and idx_10 != -1 and idx_2 < idx_10,
                f"Числовая сортировка: M_2 раньше M_10 ('{missing_w}')",
                f"Ожидалось M_2 раньше M_10, получено: '{missing_w}'",
            )
        except Exception as e:
            self.logger.fail(f"Ошибка: {e}")

    # === helper ===

    def _compare(
        self,
        actual: set,
        documented: Optional[set],
        files_on_disk: set,
    ) -> List[str]:
        from Daman_QGIS.managers.reference.submodules.Msm_4_14_data_validation_manager import (
            _compare_registry,
        )
        return _compare_registry(actual, documented, files_on_disk)
