# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_1_4 - Тест функции F_1_4_Графика к запросу
Проверка создания PDF схем с экспортом в Excel, DXF, TAB
"""

import os
import tempfile
import shutil


class TestF14:
    """Тесты для функции F_1_4_Графика к запросу"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.module = None
        self.test_dir = None

    def run_all_tests(self):
        """Запуск всех тестов F_1_4"""
        self.logger.section("ТЕСТ F_1_4: Графика к запросу")

        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f14_")
        self.logger.info(f"Временная директория: {self.test_dir}")

        try:
            self.test_01_init_module()
            self.test_02_check_submodules()
            self.test_03_excel_exporter()
            self.test_04_dxf_exporter()
            self.test_05_tab_exporter()
            self.test_06_layout_manager()
            self.test_07_integration()

        finally:
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    shutil.rmtree(self.test_dir)
                    self.logger.info("Временные файлы очищены")
                except Exception as e:
                    self.logger.warning(f"Не удалось удалить временные файлы: {str(e)}")

        self.logger.summary()

    def test_01_init_module(self):
        """ТЕСТ 1: Инициализация модуля F_1_4"""
        self.logger.section("1. Инициализация F_1_4_GraphicsRequest")

        try:
            from Daman_QGIS.tools.F_1_data.F_1_4_graphics_request import F_1_4_GraphicsRequest

            self.module = F_1_4_GraphicsRequest(self.iface)
            self.logger.success("Модуль F_1_4_GraphicsRequest загружен")

            self.logger.check(
                hasattr(self.module, 'run'),
                "Метод run существует",
                "Метод run отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, 'excel_exporter'),
                "ExcelExporter инициализирован",
                "ExcelExporter не инициализирован!"
            )

            self.logger.check(
                hasattr(self.module, 'dxf_exporter'),
                "DxfExporter инициализирован",
                "DxfExporter не инициализирован!"
            )

            self.logger.check(
                hasattr(self.module, 'tab_exporter'),
                "TabExporter инициализирован",
                "TabExporter не инициализирован!"
            )

            self.logger.check(
                hasattr(self.module, 'layout_manager'),
                "LayoutManager инициализирован",
                "LayoutManager не инициализирован!"
            )

            self.logger.check(
                hasattr(self.module, 'legend_creator'),
                "LegendCreator инициализирован",
                "LegendCreator не инициализирован!"
            )

            self.logger.check(
                hasattr(self.module, 'style_manager'),
                "StyleManager инициализирован",
                "StyleManager не инициализирован!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка инициализации: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
            self.module = None

    def test_02_check_submodules(self):
        """ТЕСТ 2: Проверка всех сабмодулей"""
        self.logger.section("2. Проверка сабмодулей")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        submodules = [
            ('excel_exporter', 'ExcelExporter'),
            ('dxf_exporter', 'DxfExportWrapper'),
            ('tab_exporter', 'TabExporter'),
            ('layout_manager', 'LayoutManager'),
            ('legend_creator', 'LegendLayersCreator'),
            ('style_manager', 'StyleManager')
        ]

        for attr_name, class_name in submodules:
            if hasattr(self.module, attr_name):
                submodule = getattr(self.module, attr_name)
                self.logger.success(f"{class_name} доступен")

                if submodule is not None:
                    self.logger.data(f"  Тип", type(submodule).__name__)
            else:
                self.logger.fail(f"{class_name} отсутствует!")

    def test_03_excel_exporter(self):
        """ТЕСТ 3: Тест ExcelExporter"""
        self.logger.section("3. Тест ExcelExporter")

        if not self.module or not hasattr(self.module, 'excel_exporter'):
            self.logger.fail("ExcelExporter недоступен")
            return

        try:
            exporter = self.module.excel_exporter

            required_methods = ['export_layer', 'create_workbook', 'save_workbook']
            for method in required_methods:
                if hasattr(exporter, method):
                    self.logger.success(f"Метод {method} существует")
                else:
                    self.logger.warning(f"Метод {method} отсутствует")

        except Exception as e:
            self.logger.error(f"Ошибка теста ExcelExporter: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_04_dxf_exporter(self):
        """ТЕСТ 4: Тест DXF экспорта"""
        self.logger.section("4. Тест DxfExportWrapper")

        if not self.module or not hasattr(self.module, 'dxf_exporter'):
            self.logger.fail("DxfExporter недоступен")
            return

        try:
            exporter = self.module.dxf_exporter

            required_methods = ['export_layer', 'prepare_layer', 'convert_to_dxf']
            for method in required_methods:
                if hasattr(exporter, method):
                    self.logger.success(f"Метод {method} существует")
                else:
                    self.logger.warning(f"Метод {method} отсутствует")

        except Exception as e:
            self.logger.error(f"Ошибка теста DXF: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_05_tab_exporter(self):
        """ТЕСТ 5: Тест TAB экспорта"""
        self.logger.section("5. Тест TabExporter")

        if not self.module or not hasattr(self.module, 'tab_exporter'):
            self.logger.fail("TabExporter недоступен")
            return

        try:
            exporter = self.module.tab_exporter

            required_methods = ['export_layer', 'write_tab', 'create_projection']
            for method in required_methods:
                if hasattr(exporter, method):
                    self.logger.success(f"Метод {method} существует")
                else:
                    self.logger.warning(f"Метод {method} отсутствует")

        except Exception as e:
            self.logger.error(f"Ошибка теста TAB: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_06_layout_manager(self):
        """ТЕСТ 6: Тест LayoutManager"""
        self.logger.section("6. Тест LayoutManager")

        if not self.module or not hasattr(self.module, 'layout_manager'):
            self.logger.fail("LayoutManager недоступен")
            return

        try:
            manager = self.module.layout_manager

            required_methods = ['create_layout', 'add_map', 'add_legend', 'export_pdf']
            for method in required_methods:
                if hasattr(manager, method):
                    self.logger.success(f"Метод {method} существует")
                else:
                    self.logger.warning(f"Метод {method} отсутствует")

        except Exception as e:
            self.logger.error(f"Ошибка теста LayoutManager: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_07_integration(self):
        """ТЕСТ 7: Интеграционный тест"""
        self.logger.section("7. Интеграционный тест всех модулей")

        if not self.module:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            all_submodules = [
                self.module.excel_exporter,
                self.module.dxf_exporter,
                self.module.tab_exporter,
                self.module.layout_manager,
                self.module.legend_creator,
                self.module.style_manager
            ]

            initialized_count = sum(1 for m in all_submodules if m is not None)
            total_count = len(all_submodules)

            self.logger.data("Инициализировано модулей", f"{initialized_count}/{total_count}")

            if initialized_count == total_count:
                self.logger.success("Все сабмодули инициализированы корректно")
            elif initialized_count > 0:
                self.logger.warning(f"Частичная инициализация: {initialized_count}/{total_count}")
            else:
                self.logger.fail("Ни один сабмодуль не инициализирован")

        except Exception as e:
            self.logger.error(f"Ошибка интеграционного теста: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
