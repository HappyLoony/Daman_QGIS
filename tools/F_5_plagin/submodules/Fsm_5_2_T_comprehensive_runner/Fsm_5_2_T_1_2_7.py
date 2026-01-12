# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_1_2_7 - Тест инициализации ZouitLoader
Проверка импорта и создания экземпляра Fsm_1_2_9_ZouitLoader
"""

from qgis.core import QgsProject


class TestZouitLoader:
    """Тест инициализации ZouitLoader"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger

    def run_all_tests(self):
        """Запуск теста ZouitLoader"""
        self.logger.section("ТЕСТ 7.3.7: ZouitLoader")

        self.logger.warning(">>> НАЧАЛО: ИМПОРТ Fsm_1_2_9_ZouitLoader")

        try:
            # Подготовка зависимостей (нужны EgrnLoader, LayerManager, GeometryProcessor, APIManager)
            from Daman_QGIS.managers import APIManager, LayerManager
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_1_egrn_loader import Fsm_1_2_1_EgrnLoader
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_8_geometry_processor import Fsm_1_2_8_GeometryProcessor

            api_manager = APIManager()
            layer_manager = LayerManager(self.iface)
            egrn_loader = Fsm_1_2_1_EgrnLoader(self.iface, api_manager)
            geometry_processor = Fsm_1_2_8_GeometryProcessor(self.iface)

            self.logger.info("Зависимости подготовлены (EgrnLoader, LayerManager, GeometryProcessor, APIManager)")

            # Импорт модуля
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_9_zouit_loader import Fsm_1_2_9_ZouitLoader
            self.logger.success("✓ Импорт OK")

            # Создание экземпляра
            self.logger.warning(">>> СОЗДАНИЕ экземпляра ZouitLoader")
            zouit_loader = Fsm_1_2_9_ZouitLoader(self.iface, egrn_loader, layer_manager, geometry_processor, api_manager)
            self.logger.success("✓ ZouitLoader инициализирован УСПЕШНО")

            # Проверка метода
            has_load = hasattr(zouit_loader, 'load_zouit_layers_final')
            self.logger.data("  Методы", f"load_zouit_layers_final={has_load}")

            self.logger.success("===== ТЕСТ 7.3.7 ПРОЙДЕН =====")

        except Exception as e:
            self.logger.fail(f"✗ ОШИБКА: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        # Итоговая сводка
        self.logger.summary()
