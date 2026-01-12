# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_2_3 - Тест функции F_2_3_Заливки
Проверка распределения по категориям земель и правам
"""


class TestF23:
    """Тесты для функции F_2_3_Fills"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.module = None

    def run_all_tests(self):
        """Запуск всех тестов F_2_3"""
        self.logger.section("ТЕСТ F_2_3: Заливки (категории и права)")

        try:
            self.test_01_init_module()
            self.test_02_check_dependencies()
            self.test_03_submodules_availability()
            self.test_04_source_layer()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов F_2_3: {str(e)}")

        self.logger.summary()

    def test_01_init_module(self):
        """ТЕСТ 1: Инициализация модуля F_2_3"""
        self.logger.section("1. Инициализация F_2_3_Fills")

        try:
            from Daman_QGIS.tools.F_2_processing.F_2_3_fills import F_2_3_Fills

            self.module = F_2_3_Fills(self.iface)
            self.logger.success("Модуль F_2_3_Fills загружен")

            # Проверяем наличие методов
            self.logger.check(
                hasattr(self.module, 'run'),
                "Метод run существует",
                "Метод run отсутствует!"
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

            # F_2_3 использует M_25 FillsManager для работы со слоями
            # Проверяем что get_fills_manager доступен
            try:
                from Daman_QGIS.managers import get_fills_manager
                self.logger.success("get_fills_manager доступен для F_2_3")
            except ImportError:
                self.logger.fail("get_fills_manager недоступен!")

            # Проверяем имя модуля
            if hasattr(self.module, 'get_name'):
                name = self.module.get_name()
                self.logger.check(
                    "2_3" in name or "Заливки" in name,
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

            # Проверяем constants
            from Daman_QGIS.constants import MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION, MESSAGE_WARNING_DURATION
            self.logger.success("constants доступны")

            # Проверяем utils
            from Daman_QGIS.utils import log_info, log_warning, log_error
            self.logger.success("utils (log_*) доступны")

        except Exception as e:
            self.logger.error(f"Ошибка проверки зависимостей: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_03_submodules_availability(self):
        """ТЕСТ 3: Проверка доступности субмодулей"""
        self.logger.section("3. Проверка субмодулей F_2_3")

        submodules = [
            ('Fsm_2_3_1_land_categories', 'Fsm_2_3_1_LandCategories'),
            ('Fsm_2_3_2_rights', 'Fsm_2_3_2_Rights'),
        ]

        for module_file, class_name in submodules:
            try:
                module = __import__(
                    f'Daman_QGIS.tools.F_2_processing.submodules.{module_file}',
                    fromlist=[class_name]
                )
                if hasattr(module, class_name):
                    self.logger.success(f"{class_name} доступен")
                else:
                    self.logger.warning(f"{class_name} не найден в модуле")
            except Exception as e:
                self.logger.warning(f"{class_name}: ошибка импорта - {str(e)[:50]}")

    def test_04_source_layer(self):
        """ТЕСТ 4: Проверка исходного слоя через M_25"""
        self.logger.section("4. Проверка исходного слоя через FillsManager")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            # F_2_3 использует M_25 FillsManager для проверки данных
            from Daman_QGIS.managers import get_fills_manager

            fills_manager = get_fills_manager(self.iface)
            availability = fills_manager.check_data_availability()

            if availability.get('can_fill'):
                self.logger.success(
                    f"Исходный слой найден: {availability.get('source_count', 0)} объектов"
                )
            else:
                # Это нормально в тестовой среде
                self.logger.warning("Исходный слой не найден (требуется выполнить F_2_1)")

        except Exception as e:
            self.logger.warning(f"Не удалось проверить исходный слой: {str(e)[:100]}")
