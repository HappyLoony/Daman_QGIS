# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_3_3 - Тест функции F_3_3_Корректировка
Проверка пересчёта атрибутов и точек после ручного редактирования нарезки
"""


class TestF33:
    """Тесты для F_3_3_Correction (корректировка нарезки)"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.module = None

    def run_all_tests(self):
        """Запуск всех тестов F_3_3"""
        self.logger.section("ТЕСТ F_3_3: Корректировка нарезки")

        try:
            self.test_01_init_module()
            self.test_02_check_dependencies()
            self.test_03_managers_availability()
            self.test_04_layer_pairs_config()
            self.test_05_work_type_delegation()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов F_3_3: {str(e)}")

        self.logger.summary()

    def test_01_init_module(self):
        """ТЕСТ 1: Инициализация модуля F_3_3_Correction"""
        self.logger.section("1. Инициализация F_3_3_Correction")

        try:
            from Daman_QGIS.tools.F_3_cutting.F_3_3_correction import F_3_3_Correction

            self.module = F_3_3_Correction(self.iface)
            self.logger.success("Модуль F_3_3_Correction загружен")

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
                hasattr(self.module, 'set_plugin_dir'),
                "Метод set_plugin_dir существует",
                "Метод set_plugin_dir отсутствует!"
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
                    "3_3" in name or "Корректировка" in name,
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
            from Daman_QGIS.constants import (
                COORDINATE_PRECISION,
                LAYER_CUTTING_OKS_RAZDEL, LAYER_CUTTING_OKS_NGS
            )
            self.logger.success("constants доступны")
            self.logger.data("COORDINATE_PRECISION", str(COORDINATE_PRECISION))

            # Проверяем utils
            from Daman_QGIS.utils import log_info, log_warning, log_error
            self.logger.success("utils (log_*) доступны")

            # Проверяем get_project_structure_manager
            from Daman_QGIS.managers import get_project_structure_manager
            self.logger.success("get_project_structure_manager доступен")

        except Exception as e:
            self.logger.error(f"Ошибка проверки зависимостей: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_03_managers_availability(self):
        """ТЕСТ 3: Проверка доступности менеджеров для корректировки"""
        self.logger.section("3. Проверка менеджеров")

        try:
            # M_22 WorkTypeAssignmentManager
            from Daman_QGIS.managers import WorkTypeAssignmentManager, LayerType
            self.logger.success("WorkTypeAssignmentManager доступен")

            # Проверяем методы M_22
            manager = WorkTypeAssignmentManager()
            self.logger.check(
                hasattr(manager, 'assign_work_type_basic'),
                "Метод assign_work_type_basic существует",
                "Метод assign_work_type_basic отсутствует!"
            )

            # M_11 PointNumberingManager
            from Daman_QGIS.managers import PointNumberingManager
            self.logger.success("PointNumberingManager доступен")

            # M_3 StyleManager
            from Daman_QGIS.managers import StyleManager
            self.logger.success("StyleManager доступен")

            # M_10 LabelManager
            from Daman_QGIS.managers import LabelManager
            self.logger.success("LabelManager доступен")

        except ImportError as e:
            self.logger.fail(f"Ошибка импорта менеджера: {str(e)}")
        except Exception as e:
            self.logger.error(f"Ошибка проверки менеджеров: {str(e)}")

    def test_04_layer_pairs_config(self):
        """ТЕСТ 4: Проверка конфигурации пар слоёв"""
        self.logger.section("4. Проверка конфигурации LAYER_PAIRS")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            # Проверяем наличие LAYER_PAIRS
            self.logger.check(
                hasattr(self.module, 'LAYER_PAIRS'),
                "LAYER_PAIRS существует",
                "LAYER_PAIRS отсутствует!"
            )

            if hasattr(self.module, 'LAYER_PAIRS'):
                pairs = self.module.LAYER_PAIRS
                self.logger.data("Количество пар", str(len(pairs)))

                # Проверяем структуру каждой пары
                for i, pair in enumerate(pairs):
                    self.logger.check(
                        len(pair) == 5,
                        f"Пара {i+1}: корректная структура (5 элементов)",
                        f"Пара {i+1}: некорректная структура ({len(pair)} элементов)"
                    )

            # Проверяем LAYER_ORDER
            self.logger.check(
                hasattr(self.module, 'LAYER_ORDER'),
                "LAYER_ORDER существует",
                "LAYER_ORDER отсутствует!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка проверки конфигурации: {str(e)}")

    def test_05_work_type_delegation(self):
        """ТЕСТ 5: Проверка делегирования Вид_Работ в M_22"""
        self.logger.section("5. Проверка делегирования в M_22")

        try:
            from Daman_QGIS.managers import WorkTypeAssignmentManager, LayerType

            manager = WorkTypeAssignmentManager()

            # Тестовые данные
            test_data = [
                {
                    'geometry': None,
                    'attributes': {
                        'ID': 1,
                        'План_ВРИ': 'Тестовый ВРИ',
                        'ВРИ': 'Существующий ВРИ'
                    }
                }
            ]

            # Вызываем assign_work_type_basic
            result = manager.assign_work_type_basic(test_data, LayerType.RAZDEL)

            self.logger.check(
                result is not None,
                "assign_work_type_basic вернул результат",
                "assign_work_type_basic вернул None!"
            )

            if result and len(result) > 0:
                attrs = result[0].get('attributes', {})
                self.logger.check(
                    'Вид_Работ' in attrs,
                    f"Поле Вид_Работ присвоено: '{attrs.get('Вид_Работ', '')[:50]}...'",
                    "Поле Вид_Работ не присвоено!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка проверки делегирования: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
