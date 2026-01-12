# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_1_2_0 - Тест инициализации EgrnLoader
Проверка импорта и создания экземпляра Fsm_1_2_1_EgrnLoader
"""


class TestEgrnLoader:
    """Тест инициализации EgrnLoader"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger

    def run_all_tests(self):
        """Запуск теста EgrnLoader"""
        self.logger.section("ТЕСТ 7.3.1: EgrnLoader (БАЗОВЫЙ)")

        self.logger.warning(">>> НАЧАЛО: ИМПОРТ Fsm_1_2_1_EgrnLoader")

        try:
            # Подготовка APIManager
            from Daman_QGIS.managers import APIManager

            api_manager = APIManager()
            self.logger.info("APIManager подготовлен")

            # Импорт модуля
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_1_egrn_loader import Fsm_1_2_1_EgrnLoader
            self.logger.success("✓ Импорт OK")

            # Создание экземпляра
            self.logger.warning(">>> СОЗДАНИЕ экземпляра EgrnLoader")
            egrn_loader = Fsm_1_2_1_EgrnLoader(self.iface, api_manager)
            self.logger.success("✓ EgrnLoader инициализирован УСПЕШНО")

            # Проверка методов
            has_load = hasattr(egrn_loader, 'load_egrn_layers')
            has_cache = hasattr(egrn_loader, 'clear_cache')
            self.logger.data("  Методы", f"load_egrn_layers={has_load}, clear_cache={has_cache}")

            self.logger.success("===== ТЕСТ 7.3.1 ПРОЙДЕН =====")

        except Exception as e:
            self.logger.fail(f"✗ ОШИБКА: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        # Итоговая сводка
        self.logger.summary()
