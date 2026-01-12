# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_1_2_5 - Тест инициализации RasterLoader
Проверка импорта и создания экземпляра Fsm_1_2_6_RasterLoader
"""

from qgis.core import QgsProject


class TestRasterLoader:
    """Тест инициализации RasterLoader"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger

    def run_all_tests(self):
        """Запуск теста RasterLoader"""
        self.logger.section("ТЕСТ 7.3.5: RasterLoader")

        self.logger.warning(">>> НАЧАЛО: ИМПОРТ Fsm_1_2_6_RasterLoader")

        try:
            # Подготовка менеджеров
            from Daman_QGIS.managers import APIManager, LayerManager

            layer_manager = LayerManager(self.iface)
            api_manager = APIManager()

            self.logger.info("Менеджеры подготовлены (LayerManager, APIManager)")

            # Импорт модуля
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_6_raster_loader import Fsm_1_2_6_RasterLoader
            self.logger.success("✓ Импорт OK")

            # Создание экземпляра
            self.logger.warning(">>> СОЗДАНИЕ экземпляра RasterLoader")
            raster_loader = Fsm_1_2_6_RasterLoader(self.iface, layer_manager, api_manager)
            self.logger.success("✓ RasterLoader инициализирован УСПЕШНО")

            # Проверка методов
            has_google = hasattr(raster_loader, 'add_google_satellite')
            has_nspd = hasattr(raster_loader, 'add_nspd_base_layer')
            has_cos = hasattr(raster_loader, 'add_cos_layer')
            self.logger.data("  Методы", f"google={has_google}, nspd={has_nspd}, cos={has_cos}")

            self.logger.success("===== ТЕСТ 7.3.5 ПРОЙДЕН =====")

        except Exception as e:
            self.logger.fail(f"✗ ОШИБКА: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        # Итоговая сводка
        self.logger.summary()
