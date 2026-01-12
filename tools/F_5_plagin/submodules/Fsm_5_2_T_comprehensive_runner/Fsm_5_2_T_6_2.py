# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_6_2 - Тест функции F_6_2_Подложки
Проверка экспорта подложек в DXF по шаблонам
"""

import os


class TestF62:
    """Тесты для функции F_6_2_BackgroundExport"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.module = None

    def run_all_tests(self):
        """Запуск всех тестов F_6_2"""
        self.logger.section("ТЕСТ F_6_2: Экспорт подложек (DXF)")

        try:
            self.test_01_init_module()
            self.test_02_check_dependencies()
            self.test_03_background_templates()
            self.test_04_output_folder()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов F_6_2: {str(e)}")

        self.logger.summary()

    def test_01_init_module(self):
        """ТЕСТ 1: Инициализация модуля F_6_2"""
        self.logger.section("1. Инициализация F_6_2_BackgroundExport")

        try:
            from Daman_QGIS.tools.F_6_release.F_6_2_background_export import F_6_2_BackgroundExport

            self.module = F_6_2_BackgroundExport(self.iface)
            self.logger.success("Модуль F_6_2_BackgroundExport загружен")

            # Проверяем наличие методов
            self.logger.check(
                hasattr(self.module, 'run'),
                "Метод run существует",
                "Метод run отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, '_get_output_folder'),
                "Метод _get_output_folder существует",
                "Метод _get_output_folder отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, '_load_background_templates'),
                "Метод _load_background_templates существует",
                "Метод _load_background_templates отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, '_export_backgrounds'),
                "Метод _export_backgrounds существует",
                "Метод _export_backgrounds отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, '_export_single_background'),
                "Метод _export_single_background существует",
                "Метод _export_single_background отсутствует!"
            )

            # Проверяем свойство name
            if hasattr(self.module, 'name'):
                name = self.module.name
                self.logger.check(
                    "6_2" in name or "Подложк" in name,
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

            # Проверяем DxfExporter
            from Daman_QGIS.tools.F_1_data.core.dxf_exporter import DxfExporter
            self.logger.success("DxfExporter доступен")

            # Проверяем ReferenceManagers
            from Daman_QGIS.managers import get_reference_managers
            self.logger.success("get_reference_managers доступен")

            # Проверяем ProjectStructureManager
            from Daman_QGIS.managers import get_project_structure_manager, FolderType
            self.logger.success("get_project_structure_manager доступен")

            # Проверяем StyleManager
            from Daman_QGIS.managers import StyleManager
            self.logger.success("StyleManager доступен")

            # Проверяем utils
            from Daman_QGIS.utils import log_info, log_warning, log_error, log_success
            self.logger.success("utils (log_*) доступны")

        except Exception as e:
            self.logger.error(f"Ошибка проверки зависимостей: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_03_background_templates(self):
        """ТЕСТ 3: Проверка загрузки шаблонов подложек"""
        self.logger.section("3. Проверка шаблонов подложек")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            templates = self.module._load_background_templates()
            self.logger.info(f"Загружено шаблонов подложек: {len(templates)}")

            if templates:
                for template in templates[:5]:  # Показываем первые 5
                    name = template.get('name', 'Unknown')
                    layers_count = len(template.get('layers', []))
                    self.logger.data(f"  -", f"{name} ({layers_count} слоёв)")

                self.logger.success("Шаблоны подложек загружены")
            else:
                self.logger.warning("Шаблоны подложек не найдены в Base_drawings_background.json")

        except Exception as e:
            self.logger.warning(f"Не удалось загрузить шаблоны: {str(e)[:100]}")

    def test_04_output_folder(self):
        """ТЕСТ 4: Проверка определения папки для экспорта"""
        self.logger.section("4. Проверка определения папки экспорта")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            output_folder = self.module._get_output_folder()

            if output_folder:
                self.logger.success(f"Папка экспорта: {output_folder}")

                # Проверяем что путь нормализован
                normalized = os.path.normpath(output_folder)
                self.logger.check(
                    output_folder == normalized,
                    "Путь нормализован",
                    f"Путь не нормализован: {output_folder}"
                )
            else:
                self.logger.warning("Папка экспорта не определена (проект не сохранён)")

        except Exception as e:
            self.logger.warning(f"Не удалось определить папку: {str(e)[:100]}")
