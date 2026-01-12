# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_1_2_4 - Тест инициализации AtdLoader
Проверка импорта и создания экземпляра Fsm_1_2_5_AtdLoader
"""

from qgis.core import QgsProject


class TestAtdLoader:
    """Тест инициализации AtdLoader"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger

    def run_all_tests(self):
        """Запуск теста AtdLoader"""
        self.logger.section("ТЕСТ 7.3.4: AtdLoader (КРИТИЧЕН для _load_egrn_layers)")

        self.logger.warning(">>> НАЧАЛО: ИМПОРТ Fsm_1_2_5_AtdLoader")

        try:
            # Подготовка: нужен EgrnLoader и APIManager
            from Daman_QGIS.managers import APIManager
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_1_egrn_loader import Fsm_1_2_1_EgrnLoader

            api_manager = APIManager()
            egrn_loader = Fsm_1_2_1_EgrnLoader(self.iface, api_manager)

            self.logger.info("Зависимости подготовлены (EgrnLoader, APIManager)")

            # Импорт модуля
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_5_atd_loader import Fsm_1_2_5_AtdLoader
            self.logger.success("✓ Импорт OK")

            # Создание экземпляра
            self.logger.warning(">>> СОЗДАНИЕ экземпляра AtdLoader")
            atd_loader = Fsm_1_2_5_AtdLoader(self.iface, egrn_loader, api_manager)
            self.logger.success("✓ AtdLoader инициализирован УСПЕШНО")

            self.logger.success("===== ТЕСТ 7.3.4 ПРОЙДЕН =====")

        except Exception as e:
            self.logger.fail(f"✗ ОШИБКА: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        # Итоговая сводка
        self.logger.summary()
