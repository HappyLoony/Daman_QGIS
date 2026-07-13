# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_cleanup_contract — Тест контракта очистки слоёв (get_name() <-> Base_layers).

Покрытие (D-гибрид, план cleanup_contract_guard 2026-06-21):
- self-correcting whitelist: каждая функция из CLEANUP_NOOP_WHITELIST
  (легитимный no-op очистки) НЕ должна присутствовать в Base_layers.json как
  creating_function. Если whitelisted-функция начала регистрировать слои,
  её запись в whitelist устарела — M_10 продолжит тихо пропускать реальную
  очистку (function_name in whitelist -> log_info вместо log_warning) -> тест
  краснеет и сигналит, что запись пора убрать из whitelist.

Документирует контракт очистки:
  BaseTool.auto_cleanup_layers() -> get_name() -> M_10.cleanup_for_function()
  сверяет get_name() с creating_function в Base_layers.json точным ==.
  7 callers (verified grep 2026-06-21):
    Живые (get_name() есть в Base_layers): F_2_4, F_2_1, F_1_2, F_3_1
    No-op (get_name() в whitelist, слоёв не создают): F_1_3, F_2_3, Fsm_1_2_13_1

Runtime-страж рассинхрона get_name() <-> creating_function — в M_10
(log_warning для не-whitelisted пустого layers_to_remove). Этот тест — dev-time
проверка устаревания whitelist (то, что runtime-страж по дизайну молчит).

Сеть: использует Base_layers (BaseReferenceLoader). При offline -> skip, не fail
(fail/skip-дисциплина проекта).
"""

from typing import Any, Optional, Set

from Daman_QGIS.constants import CLEANUP_NOOP_WHITELIST


class TestCleanupContract:
    """Тест контракта очистки слоёв: self-correcting whitelist no-op функций."""

    def __init__(self, iface: Any, logger: Any) -> None:
        self.iface = iface
        self.logger = logger

    def run_all_tests(self) -> None:
        """Entry point для comprehensive runner."""
        self.logger.section("ТЕСТ M_10: контракт очистки слоёв (whitelist no-op)")

        try:
            self.test_01_whitelist_sanity()
            self.test_02_whitelist_not_in_base_layers()
        except Exception as e:
            self.logger.error(f"Критическая ошибка теста контракта очистки: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    def test_01_whitelist_sanity(self) -> None:
        """ТЕСТ 1: CLEANUP_NOOP_WHITELIST импортирован, непуст, состоит из строк."""
        self.logger.section("1. whitelist sanity")
        self.logger.check(
            isinstance(CLEANUP_NOOP_WHITELIST, frozenset) and len(CLEANUP_NOOP_WHITELIST) > 0,
            f"CLEANUP_NOOP_WHITELIST: {len(CLEANUP_NOOP_WHITELIST)} no-op функций",
            f"CLEANUP_NOOP_WHITELIST пуст или не frozenset: {type(CLEANUP_NOOP_WHITELIST)}",
        )
        self.logger.check(
            all(isinstance(name, str) and name for name in CLEANUP_NOOP_WHITELIST),
            "Все записи whitelist — непустые строки",
            f"В whitelist есть нестроковые/пустые записи: {CLEANUP_NOOP_WHITELIST}",
        )

    def test_02_whitelist_not_in_base_layers(self) -> None:
        """ТЕСТ 2: каждая whitelisted-функция НЕ создаёт слоёв в Base_layers (self-correcting).

        Если whitelisted get_name() появился среди creating_function — функция
        начала регистрировать слои, и её запись в whitelist устарела (M_10
        тихо пропускает её реальную очистку). Тест краснеет.
        """
        self.logger.section("2. whitelist not in Base_layers")

        creating_functions = self._load_creating_functions()
        if creating_functions is None:
            self.logger.skip("Base_layers недоступен (offline) — проверка устаревания whitelist пропущена")
            return

        for name in sorted(CLEANUP_NOOP_WHITELIST):
            self.logger.check(
                name not in creating_functions,
                f"'{name}' не создаёт слоёв (whitelist актуален)",
                f"'{name}' в whitelist, но присутствует в Base_layers как creating_function — "
                f"функция начала регистрировать слои, удалите её из CLEANUP_NOOP_WHITELIST",
            )

    def _load_creating_functions(self) -> Optional[Set[str]]:
        """Множество creating_function из Base_layers.json или None при offline/ошибке."""
        try:
            from Daman_QGIS.managers import LayerReferenceManager
            layers = LayerReferenceManager().get_base_layers()
        except Exception:
            return None
        if not layers:
            return None
        return {
            layer.get('creating_function')
            for layer in layers
            if layer.get('creating_function')
        }
