# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_1_2_2 - Тест инициализации QuickOSMLoader
Проверка импорта и создания экземпляра Fsm_1_2_3_QuickOSMLoader
"""

from qgis.core import QgsProject


class TestQuickOSMLoader:
    """Тест инициализации QuickOSMLoader"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger

    def run_all_tests(self):
        """Запуск теста QuickOSMLoader"""
        self.logger.section("ТЕСТ 7.3.2: QuickOSMLoader")

        self.logger.warning(">>> НАЧАЛО: ИМПОРТ Fsm_1_2_3_QuickOSMLoader")

        try:
            # Подготовка менеджеров
            from Daman_QGIS.managers import APIManager, ProjectManager, LayerManager
            import os

            project = QgsProject.instance()
            project_path = project.absolutePath()

            if not project_path:
                self.logger.fail("Проект не открыт")
                return

            plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            project_manager = ProjectManager(self.iface, plugin_dir)
            project_manager.init_from_native_project()
            layer_manager = LayerManager(self.iface)
            api_manager = APIManager()

            self.logger.info("Менеджеры подготовлены")

            # Импорт модуля
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_3_quickosm_loader import Fsm_1_2_3_QuickOSMLoader
            self.logger.success("✓ Импорт OK")

            # Создание экземпляра
            self.logger.warning(">>> СОЗДАНИЕ экземпляра QuickOSMLoader")
            quickosm_loader = Fsm_1_2_3_QuickOSMLoader(self.iface, layer_manager, project_manager, api_manager)
            self.logger.success("✓ QuickOSMLoader инициализирован УСПЕШНО")

            # Проверка методов
            has_load = hasattr(quickosm_loader, 'load_osm_layers')
            self.logger.data("  Методы", f"load_osm_layers={has_load}")

            self.logger.success("===== ТЕСТ 7.3.2 ПРОЙДЕН =====")

        except Exception as e:
            self.logger.fail(f"✗ ОШИБКА: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        # Итоговая сводка
        self.logger.summary()
