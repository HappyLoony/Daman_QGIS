# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_1_3 - Тест функции F_1_3_Бюджет
Проверка расчёта выборки для бюджета (async через M_17)
"""


class TestF13:
    """Тесты для функции F_1_3_BudgetSelection"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.module = None

    def run_all_tests(self):
        """Запуск всех тестов F_1_3"""
        self.logger.section("ТЕСТ F_1_3: Выборка для бюджета")

        try:
            self.test_01_init_module()
            self.test_02_check_dependencies()
            self.test_03_submodules_availability()
            self.test_04_async_manager()
            self.test_05_budget_folder()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов F_1_3: {str(e)}")

        self.logger.summary()

    def test_01_init_module(self):
        """ТЕСТ 1: Инициализация модуля F_1_3"""
        self.logger.section("1. Инициализация F_1_3_BudgetSelection")

        try:
            from Daman_QGIS.tools.F_1_data.F_1_3_budget_selection import F_1_3_BudgetSelection

            self.module = F_1_3_BudgetSelection(self.iface)
            self.logger.success("Модуль F_1_3_BudgetSelection загружен")

            # Проверяем наличие методов
            self.logger.check(
                hasattr(self.module, 'run'),
                "Метод run существует",
                "Метод run отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, 'set_project_manager'),
                "Метод set_project_manager существует",
                "Метод set_project_manager отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, 'set_layer_manager'),
                "Метод set_layer_manager существует",
                "Метод set_layer_manager отсутствует!"
            )

            self.logger.check(
                hasattr(self.module, 'get_name'),
                "Метод get_name существует",
                "Метод get_name отсутствует!"
            )

            # Проверяем имя модуля
            if hasattr(self.module, 'get_name'):
                name = self.module.get_name()
                self.logger.check(
                    "1_3" in name or "Бюджет" in name,
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
            # Проверяем ProjectManager
            from Daman_QGIS.managers import ProjectManager
            self.logger.success("ProjectManager доступен")

            # Проверяем LayerManager
            from Daman_QGIS.managers import LayerManager
            self.logger.success("LayerManager доступен")

            # Проверяем AsyncTaskManager (M_17)
            from Daman_QGIS.managers import get_async_manager
            self.logger.success("get_async_manager доступен")

            # Проверяем ProjectStructureManager (M_19)
            from Daman_QGIS.managers import get_project_structure_manager, FolderType
            self.logger.success("get_project_structure_manager доступен")

            # Проверяем ReferenceManagers
            from Daman_QGIS.managers import get_reference_managers
            self.logger.success("get_reference_managers доступен")

        except Exception as e:
            self.logger.error(f"Ошибка проверки зависимостей: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_03_submodules_availability(self):
        """ТЕСТ 3: Проверка доступности субмодулей"""
        self.logger.section("3. Проверка субмодулей F_1_3")

        submodules = [
            ('Fsm_1_3_0_budget_task', 'Fsm_1_3_0_BudgetTask'),
            ('Fsm_1_3_1_boundaries_processor', 'BoundariesProcessor'),
            ('Fsm_1_3_2_vector_loader', 'VectorLoader'),
            ('Fsm_1_3_3_forest_loader', 'ForestLoader'),
            ('Fsm_1_3_4_spatial_analyzer', 'SpatialAnalyzer'),
            ('Fsm_1_3_5_results_dialog', 'BudgetSelectionResultsDialog'),
            ('Fsm_1_3_7_intersections_calculator', 'IntersectionsCalculator'),
        ]

        for module_file, class_name in submodules:
            try:
                module = __import__(
                    f'Daman_QGIS.tools.F_1_data.submodules.{module_file}',
                    fromlist=[class_name]
                )
                if hasattr(module, class_name):
                    self.logger.success(f"{class_name} доступен")
                else:
                    self.logger.warning(f"{class_name} не найден в модуле")
            except Exception as e:
                self.logger.warning(f"{class_name}: ошибка импорта - {str(e)[:50]}")

    def test_04_async_manager(self):
        """ТЕСТ 4: Проверка AsyncTaskManager (M_17)"""
        self.logger.section("4. Проверка M_17 AsyncTaskManager")

        try:
            from Daman_QGIS.managers import get_async_manager

            manager = get_async_manager(self.iface)
            self.logger.success("AsyncTaskManager инициализирован")

            # Проверяем методы менеджера
            self.logger.check(
                hasattr(manager, 'run'),
                "Метод run существует",
                "Метод run отсутствует!"
            )

            self.logger.check(
                hasattr(manager, 'get_active_count'),
                "Метод get_active_count существует",
                "Метод get_active_count отсутствует!"
            )

            # Проверяем количество активных задач
            active_count = manager.get_active_count()
            self.logger.info(f"Активных задач: {active_count}")

        except Exception as e:
            self.logger.error(f"Ошибка проверки AsyncTaskManager: {str(e)}")

    def test_05_budget_folder(self):
        """ТЕСТ 5: Проверка определения папки бюджета"""
        self.logger.section("5. Проверка метода _get_budget_folder")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            # Проверяем наличие метода
            self.logger.check(
                hasattr(self.module, '_get_budget_folder'),
                "Метод _get_budget_folder существует",
                "Метод _get_budget_folder отсутствует!"
            )

            # Пробуем вызвать метод
            budget_folder = self.module._get_budget_folder()

            if budget_folder:
                self.logger.success(f"Папка бюджета: {budget_folder}")
            else:
                # Это нормально если проект не открыт
                self.logger.warning("Папка бюджета не определена (проект не открыт)")

        except Exception as e:
            self.logger.warning(f"Не удалось получить папку бюджета: {str(e)[:100]}")
