# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_1_2_3 - Тест инициализации GeometryProcessor
Проверка импорта и создания экземпляра Fsm_1_2_8_GeometryProcessor
"""


class TestGeometryProcessor:
    """Тест инициализации GeometryProcessor"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger

    def run_all_tests(self):
        """Запуск теста GeometryProcessor"""
        self.logger.section("ТЕСТ 7.3.3: GeometryProcessor")

        self.logger.warning(">>> НАЧАЛО: ИМПОРТ Fsm_1_2_8_GeometryProcessor")

        try:
            # Импорт модуля
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_8_geometry_processor import Fsm_1_2_8_GeometryProcessor
            self.logger.success("✓ Импорт OK")

            # Создание экземпляра
            self.logger.warning(">>> СОЗДАНИЕ экземпляра GeometryProcessor")
            geometry_processor = Fsm_1_2_8_GeometryProcessor(self.iface)
            self.logger.success("✓ GeometryProcessor инициализирован УСПЕШНО")

            # Проверка методов
            has_process = hasattr(geometry_processor, 'process_geometry')
            has_buffer = hasattr(geometry_processor, 'create_buffer')
            self.logger.data("  Методы", f"process_geometry={has_process}, create_buffer={has_buffer}")

            self.logger.success("===== ТЕСТ 7.3.3 ПРОЙДЕН =====")

        except Exception as e:
            self.logger.fail(f"✗ ОШИБКА: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        # Итоговая сводка
        self.logger.summary()
