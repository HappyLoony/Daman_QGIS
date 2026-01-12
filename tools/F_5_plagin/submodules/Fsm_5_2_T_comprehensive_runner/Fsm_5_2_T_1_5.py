# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_1_5 - Тест функции F_1_5_Универсальный экспорт
Проверка экспорта в различные форматы (DXF, Excel, GeoJSON, KML, KMZ, Shapefile, TAB)
"""

import os
import tempfile
import shutil


class TestF15:
    """Тесты для функции F_1_5_Универсальный экспорт"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.module = None
        self.test_dir = None

    def run_all_tests(self):
        """Запуск всех тестов F_1_5"""
        self.logger.section("ТЕСТ F_1_5: Универсальный экспорт")

        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f15_")
        self.logger.info(f"Временная директория: {self.test_dir}")

        try:
            self.test_01_init_module()
            self.test_02_check_format_modules()
            self.test_03_format_names()
            self.test_04_submodules_availability()
            self.test_05_export_formats()

        finally:
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    shutil.rmtree(self.test_dir)
                    self.logger.info("Временные файлы очищены")
                except Exception as e:
                    self.logger.warning(f"Не удалось удалить временные файлы: {str(e)}")

        self.logger.summary()

    def test_01_init_module(self):
        """ТЕСТ 1: Инициализация модуля F_1_5"""
        self.logger.section("1. Инициализация F_1_5_UniversalExport")

        try:
            from Daman_QGIS.tools.F_1_data.F_1_5_universal_export import F_1_5_UniversalExport

            self.module = F_1_5_UniversalExport(self.iface)
            self.logger.success("Модуль F_1_5_UniversalExport загружен")

            self.logger.check(
                hasattr(self.module, 'run'),
                "Метод run существует",
                "Метод run отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, 'export_batch'),
                "Метод export_batch существует",
                "Метод export_batch отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, 'export_single_format'),
                "Метод export_single_format существует",
                "Метод export_single_format отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, 'FORMAT_MODULES'),
                "Словарь FORMAT_MODULES существует",
                "FORMAT_MODULES отсутствует!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка инициализации: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
            self.module = None

    def test_02_check_format_modules(self):
        """ТЕСТ 2: Проверка модулей форматов"""
        self.logger.section("2. Проверка FORMAT_MODULES")

        if not self.module or not hasattr(self.module, 'FORMAT_MODULES'):
            self.logger.fail("FORMAT_MODULES недоступен")
            return

        try:
            formats = self.module.FORMAT_MODULES
            self.logger.data("Количество форматов", str(len(formats)))

            # Примечание: excel и excel_list перенесены в F_6_3
            expected_formats = ['dxf', 'geojson', 'kml', 'kmz', 'shapefile', 'tab', 'excel_table']

            for fmt in expected_formats:
                if fmt in formats:
                    self.logger.success(f"Формат {fmt} поддерживается")
                else:
                    self.logger.fail(f"Формат {fmt} отсутствует!")

            for fmt, module_class in formats.items():
                if module_class is not None:
                    self.logger.success(f"  {fmt}: {module_class.__name__}")
                else:
                    self.logger.warning(f"  {fmt}: None (не реализован)")

        except Exception as e:
            self.logger.error(f"Ошибка проверки форматов: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_03_format_names(self):
        """ТЕСТ 3: Проверка имен форматов"""
        self.logger.section("3. Проверка FORMAT_NAMES")

        if not self.module or not hasattr(self.module, 'FORMAT_NAMES'):
            self.logger.fail("FORMAT_NAMES недоступен")
            return

        try:
            names = self.module.FORMAT_NAMES
            self.logger.data("Количество имен", str(len(names)))

            # Примечание: excel и excel_list перенесены в F_6_3
            expected_names = {
                'dxf': 'DXF (AutoCAD)',
                'geojson': 'GeoJSON',
                'kml': 'KML (Google Earth)',
                'kmz': 'KMZ (сжатый KML)',
                'shapefile': 'Shapefile (ESRI)',
                'tab': 'TAB (MapInfo)',
                'excel_table': 'Excel (таблица атрибутов)'
            }

            for fmt, expected_name in expected_names.items():
                if fmt in names:
                    actual_name = names[fmt]
                    if actual_name == expected_name:
                        self.logger.success(f"{fmt}: '{actual_name}'")
                    else:
                        self.logger.warning(f"{fmt}: '{actual_name}' (ожидалось '{expected_name}')")
                else:
                    self.logger.fail(f"Имя для формата {fmt} отсутствует!")

        except Exception as e:
            self.logger.error(f"Ошибка проверки имен: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_04_submodules_availability(self):
        """ТЕСТ 4: Проверка доступности сабмодулей"""
        self.logger.section("4. Проверка доступности сабмодулей")

        # Примечание: ExcelExportSubmodule и ExcelListExportSubmodule перенесены в F_6_3
        submodules = [
            'DxfExportSubmodule',
            'GeoJSONExportSubmodule',
            'KMLExportSubmodule',
            'KMZExportSubmodule',
            'ShapefileExportSubmodule',
            'TabExportSubmodule',
            'ExcelTableExportSubmodule'
        ]

        for submodule_name in submodules:
            try:
                from Daman_QGIS.tools.F_1_data import submodules
                if hasattr(submodules, submodule_name):
                    self.logger.success(f"{submodule_name} доступен")
                else:
                    self.logger.warning(f"{submodule_name} недоступен")
            except Exception as e:
                self.logger.warning(f"{submodule_name}: ошибка импорта - {str(e)[:50]}")

    def test_05_export_formats(self):
        """ТЕСТ 5: Тест каждого формата экспорта"""
        self.logger.section("5. Тест форматов экспорта")

        if not self.module:
            self.logger.fail("Модуль не инициализирован")
            return

        # Примечание: excel и excel_list перенесены в F_6_3
        test_formats = ['dxf', 'geojson', 'kml', 'kmz', 'shapefile', 'tab', 'excel_table']

        for fmt in test_formats:
            try:
                if fmt in self.module.FORMAT_MODULES:
                    module_class = self.module.FORMAT_MODULES[fmt]

                    if module_class is not None:
                        instance = module_class(self.iface)
                        self.logger.success(f"Формат {fmt}: модуль инициализирован")

                        required_methods = ['export', 'prepare_layer', 'validate']
                        has_methods = []
                        for method in required_methods:
                            if hasattr(instance, method):
                                has_methods.append(method)

                        if has_methods:
                            self.logger.data(f"  Методы {fmt}", ", ".join(has_methods))
                    else:
                        self.logger.warning(f"Формат {fmt}: модуль не реализован (None)")
                else:
                    self.logger.fail(f"Формат {fmt}: отсутствует в FORMAT_MODULES")

            except Exception as e:
                self.logger.warning(f"Формат {fmt}: ошибка - {str(e)[:100]}")
