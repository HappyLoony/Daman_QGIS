# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_6_3 - Тест функции F_6_3_Перечни и ведомости
Проверка экспорта документов в Excel по шаблонам
"""

import os


class TestF63:
    """Тесты для функции F_6_3_DocumentExport"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.module = None

    def run_all_tests(self):
        """Запуск всех тестов F_6_3"""
        self.logger.section("ТЕСТ F_6_3: Экспорт документов (Excel)")

        try:
            self.test_01_init_module()
            self.test_02_check_dependencies()
            self.test_03_submodules_availability()
            self.test_04_doc_types()
            self.test_05_output_folder()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов F_6_3: {str(e)}")

        self.logger.summary()

    def test_01_init_module(self):
        """ТЕСТ 1: Инициализация модуля F_6_3"""
        self.logger.section("1. Инициализация F_6_3_DocumentExport")

        try:
            from Daman_QGIS.tools.F_6_release.F_6_3_document_export import F_6_3_DocumentExport

            self.module = F_6_3_DocumentExport(self.iface)
            self.logger.success("Модуль F_6_3_DocumentExport загружен")

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
                hasattr(self.module, '_export_documents'),
                "Метод _export_documents существует",
                "Метод _export_documents отсутствует!"
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
                    "6_3" in name or "Перечн" in name or "ведомост" in name.lower(),
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

            # Проверяем ReferenceManagers
            from Daman_QGIS.managers import get_reference_managers
            self.logger.success("get_reference_managers доступен")

            # Проверяем ProjectStructureManager
            from Daman_QGIS.managers import get_project_structure_manager, FolderType
            self.logger.success("get_project_structure_manager доступен")

            # Проверяем utils
            from Daman_QGIS.utils import log_info, log_warning, log_error, log_success
            self.logger.success("utils (log_*) доступны")

            # Проверяем xlsxwriter (внешняя зависимость)
            try:
                import xlsxwriter
                self.logger.success("xlsxwriter доступен")
            except ImportError:
                self.logger.warning("xlsxwriter не установлен (используйте F_5_1)")

        except Exception as e:
            self.logger.error(f"Ошибка проверки зависимостей: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_03_submodules_availability(self):
        """ТЕСТ 3: Проверка доступности субмодулей"""
        self.logger.section("3. Проверка субмодулей F_6_3")

        submodules = [
            ('Fsm_6_3_1_coordinate_list', 'Fsm_6_3_1_CoordinateList'),
            ('Fsm_6_3_2_attribute_list', 'Fsm_6_3_2_AttributeList'),
        ]

        for module_file, class_name in submodules:
            try:
                module = __import__(
                    f'Daman_QGIS.tools.F_6_release.submodules.{module_file}',
                    fromlist=[class_name]
                )
                if hasattr(module, class_name):
                    self.logger.success(f"{class_name} доступен")
                else:
                    self.logger.warning(f"{class_name} не найден в модуле")
            except Exception as e:
                self.logger.warning(f"{class_name}: ошибка импорта - {str(e)[:50]}")

    def test_04_doc_types(self):
        """ТЕСТ 4: Проверка типов документов"""
        self.logger.section("4. Проверка DOC_TYPES")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            # Проверяем наличие DOC_TYPES
            self.logger.check(
                hasattr(self.module, 'DOC_TYPES'),
                "DOC_TYPES существует",
                "DOC_TYPES отсутствует!"
            )

            if hasattr(self.module, 'DOC_TYPES'):
                doc_types = self.module.DOC_TYPES
                self.logger.info(f"Типов документов: {len(doc_types)}")

                for key, value in doc_types.items():
                    self.logger.data(f"  - {key}:", value)

                # Проверяем обязательные типы
                expected_types = ['coordinate_list', 'attribute_list']
                for doc_type in expected_types:
                    self.logger.check(
                        doc_type in doc_types,
                        f"Тип '{doc_type}' определён",
                        f"Тип '{doc_type}' отсутствует!"
                    )

        except Exception as e:
            self.logger.error(f"Ошибка проверки DOC_TYPES: {str(e)}")

    def test_05_output_folder(self):
        """ТЕСТ 5: Проверка определения папки для экспорта"""
        self.logger.section("5. Проверка определения папки экспорта")

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
