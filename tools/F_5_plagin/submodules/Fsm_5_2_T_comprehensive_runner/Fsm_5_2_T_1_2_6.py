# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_1_2_6 - Тест инициализации ParentLayerManager
Проверка импорта и создания экземпляра Fsm_1_2_7_ParentLayerManager
"""

from qgis.core import QgsProject


class TestParentLayerManager:
    """Тест инициализации ParentLayerManager"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger

    def run_all_tests(self):
        """Запуск теста ParentLayerManager"""
        self.logger.section("ТЕСТ 7.3.6: ParentLayerManager")

        self.logger.warning(">>> НАЧАЛО: ИМПОРТ Fsm_1_2_7_ParentLayerManager")

        try:
            # Подготовка LayerManager
            from Daman_QGIS.managers import LayerManager

            layer_manager = LayerManager(self.iface)

            self.logger.info("LayerManager подготовлен")

            # Импорт модуля
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_7_parent_layer_manager import Fsm_1_2_7_ParentLayerManager
            self.logger.success("✓ Импорт OK")

            # Создание экземпляра
            self.logger.warning(">>> СОЗДАНИЕ экземпляра ParentLayerManager")
            parent_layer_manager = Fsm_1_2_7_ParentLayerManager(self.iface, layer_manager)
            self.logger.success("✓ ParentLayerManager инициализирован УСПЕШНО")

            self.logger.success("===== ТЕСТ 7.3.6 ПРОЙДЕН =====")

        except Exception as e:
            self.logger.fail(f"✗ ОШИБКА: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        # Итоговая сводка
        self.logger.summary()
