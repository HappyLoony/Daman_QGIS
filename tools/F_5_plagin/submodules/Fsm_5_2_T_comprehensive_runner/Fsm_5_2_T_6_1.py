# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_6_1 - Тест функции F_6_1_Векторные слои
Проверка экспорта векторных слоёв в TAB с MapInfo стилями
"""


class TestF61:
    """Тесты для функции F_6_1_VectorExport"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.module = None

    def run_all_tests(self):
        """Запуск всех тестов F_6_1"""
        self.logger.section("ТЕСТ F_6_1: Экспорт векторных слоёв (TAB)")

        try:
            self.test_01_init_module()
            self.test_02_check_dependencies()
            self.test_03_mapinfo_translator()
            self.test_04_tab_exporter()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов F_6_1: {str(e)}")

        self.logger.summary()

    def test_01_init_module(self):
        """ТЕСТ 1: Инициализация модуля F_6_1"""
        self.logger.section("1. Инициализация F_6_1_VectorExport")

        try:
            from Daman_QGIS.tools.F_6_release.F_6_1_vector_export import F_6_1_VectorExport

            self.module = F_6_1_VectorExport(self.iface)
            self.logger.success("Модуль F_6_1_VectorExport загружен")

            # Проверяем наличие методов
            self.logger.check(
                hasattr(self.module, 'run'),
                "Метод run существует",
                "Метод run отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, '_export_layers_with_styles'),
                "Метод _export_layers_with_styles существует",
                "Метод _export_layers_with_styles отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, '_get_geometry_type_name'),
                "Метод _get_geometry_type_name существует",
                "Метод _get_geometry_type_name отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, '_show_results'),
                "Метод _show_results существует",
                "Метод _show_results отсутствует!"
            )

            # Проверяем свойство name
            if hasattr(self.module, 'name'):
                name = self.module.name
                self.logger.check(
                    "6_1" in name or "Вектор" in name,
                    f"Имя модуля корректное: '{name}'",
                    f"Имя модуля некорректное: '{name}'"
                )

        except Exception as e:
            self.logger.error(f"Ошибка инициализации: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
            self.module = None

    def test_02_check_dependencies(self):
        """ТЕСТ 2: Проверка зависимостей"""
        self.logger.section("2. Проверка зависимостей модуля")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            # Проверяем BaseTool
            from Daman_QGIS.core.base_tool import BaseTool
            self.logger.success("BaseTool доступен")

            # Проверяем utils
            from Daman_QGIS.utils import log_info, log_warning, log_error, log_success
            self.logger.success("utils (log_*) доступны")

            # Проверяем ExportDialog
            from Daman_QGIS.tools.F_1_data.ui.export_dialog import ExportDialog
            self.logger.success("ExportDialog доступен")

            # Проверяем TabExporter
            from Daman_QGIS.tools.F_1_data.core.tab_exporter import TabExporter
            self.logger.success("TabExporter доступен")

        except Exception as e:
            self.logger.error(f"Ошибка проверки зависимостей: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_03_mapinfo_translator(self):
        """ТЕСТ 3: Проверка MapInfo транслятора"""
        self.logger.section("3. Проверка Fsm_6_1_1_MapInfoTranslator")

        try:
            from Daman_QGIS.tools.F_6_release.submodules.Fsm_6_1_1_mapinfo_translator import Fsm_6_1_1_MapInfoTranslator

            translator = Fsm_6_1_1_MapInfoTranslator()
            self.logger.success("Fsm_6_1_1_MapInfoTranslator загружен")

            # Проверяем методы
            self.logger.check(
                hasattr(translator, 'get_style_for_layer'),
                "Метод get_style_for_layer существует",
                "Метод get_style_for_layer отсутствует!"
            )

            self.logger.check(
                hasattr(translator, 'parse_mapinfo_style'),
                "Метод parse_mapinfo_style существует",
                "Метод parse_mapinfo_style отсутствует!"
            )

            self.logger.check(
                hasattr(translator, 'convert_to_ogr_style'),
                "Метод convert_to_ogr_style существует",
                "Метод convert_to_ogr_style отсутствует!"
            )

        except Exception as e:
            self.logger.warning(f"MapInfoTranslator: ошибка - {str(e)[:100]}")

    def test_04_tab_exporter(self):
        """ТЕСТ 4: Проверка TabExporter"""
        self.logger.section("4. Проверка TabExporter")

        try:
            from Daman_QGIS.tools.F_1_data.core.tab_exporter import TabExporter

            exporter = TabExporter(self.iface)
            self.logger.success("TabExporter инициализирован")

            # Проверяем методы
            self.logger.check(
                hasattr(exporter, 'export_layers'),
                "Метод export_layers существует",
                "Метод export_layers отсутствует!"
            )

        except Exception as e:
            self.logger.warning(f"TabExporter: ошибка - {str(e)[:100]}")
