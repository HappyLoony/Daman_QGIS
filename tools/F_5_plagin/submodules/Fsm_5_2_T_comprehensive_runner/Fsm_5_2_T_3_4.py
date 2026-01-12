# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_3_4 - Тест функции F_3_4_Этапность
Проверка формирования этапов кадастровых работ (1 этап, 2 этап, итог)
"""


class TestF34:
    """Тесты для F_3_4_Staging (этапность)"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.module = None

    def run_all_tests(self):
        """Запуск всех тестов F_3_4"""
        self.logger.section("ТЕСТ F_3_4: Этапность")

        try:
            self.test_01_init_module()
            self.test_02_check_dependencies()
            self.test_03_managers_availability()
            self.test_04_layer_mapping_config()
            self.test_05_stage_types()
            self.test_06_work_type_stage2()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов F_3_4: {str(e)}")

        self.logger.summary()

    def test_01_init_module(self):
        """ТЕСТ 1: Инициализация модуля F_3_4_Staging"""
        self.logger.section("1. Инициализация F_3_4_Staging")

        try:
            from Daman_QGIS.tools.F_3_cutting.F_3_4_staging import F_3_4_Staging

            self.module = F_3_4_Staging(self.iface)
            self.logger.success("Модуль F_3_4_Staging загружен")

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
                    "3_4" in name or "Этапность" in name,
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

            # Проверяем constants этапности
            from Daman_QGIS.constants import (
                LAYER_STAGING_1_RAZDEL, LAYER_STAGING_1_NGS,
                LAYER_STAGING_2_RAZDEL, LAYER_STAGING_2_NGS,
                LAYER_STAGING_FINAL_RAZDEL, LAYER_STAGING_FINAL_NGS,
                LAYER_ZPR_OKS
            )
            self.logger.success("constants (LAYER_STAGING_*) доступны")

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
        """ТЕСТ 3: Проверка доступности менеджеров для этапности"""
        self.logger.section("3. Проверка менеджеров")

        try:
            # M_22 WorkTypeAssignmentManager с StageType
            from Daman_QGIS.managers import (
                WorkTypeAssignmentManager, LayerType, StageType
            )
            self.logger.success("WorkTypeAssignmentManager доступен")
            self.logger.success("StageType доступен")

            # M_21 VRIAssignmentManager
            from Daman_QGIS.managers import VRIAssignmentManager
            self.logger.success("VRIAssignmentManager доступен")

            # M_11 PointNumberingManager
            from Daman_QGIS.managers import PointNumberingManager
            self.logger.success("PointNumberingManager доступен")

            # M_13 DataCleanupManager
            from Daman_QGIS.managers import DataCleanupManager
            self.logger.success("DataCleanupManager доступен")

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

    def test_04_layer_mapping_config(self):
        """ТЕСТ 4: Проверка конфигурации маппинга слоёв"""
        self.logger.section("4. Проверка LAYER_MAPPING")

        if not self.module:
            self.logger.fail("Модуль не инициализирован, пропускаем тест")
            return

        try:
            # Проверяем наличие LAYER_MAPPING
            self.logger.check(
                hasattr(self.module, 'LAYER_MAPPING'),
                "LAYER_MAPPING существует",
                "LAYER_MAPPING отсутствует!"
            )

            if hasattr(self.module, 'LAYER_MAPPING'):
                mapping = self.module.LAYER_MAPPING
                self.logger.data("Количество маппингов", str(len(mapping)))

                # Проверяем структуру (9 элементов на маппинг)
                for i, item in enumerate(mapping):
                    self.logger.check(
                        len(item) == 9,
                        f"Маппинг {i+1}: корректная структура (9 элементов)",
                        f"Маппинг {i+1}: некорректная структура ({len(item)} элементов)"
                    )

            # Проверяем ZPR_MATCH_THRESHOLD
            self.logger.check(
                hasattr(self.module, 'ZPR_MATCH_THRESHOLD'),
                "ZPR_MATCH_THRESHOLD существует",
                "ZPR_MATCH_THRESHOLD отсутствует!"
            )

            if hasattr(self.module, 'ZPR_MATCH_THRESHOLD'):
                threshold = self.module.ZPR_MATCH_THRESHOLD
                self.logger.data("ZPR_MATCH_THRESHOLD", f"{threshold:.0%}")

        except Exception as e:
            self.logger.error(f"Ошибка проверки конфигурации: {str(e)}")

    def test_05_stage_types(self):
        """ТЕСТ 5: Проверка enum StageType"""
        self.logger.section("5. Проверка StageType")

        try:
            from Daman_QGIS.managers import StageType

            # Проверяем наличие всех типов этапов
            self.logger.check(
                hasattr(StageType, 'STAGE_1'),
                "StageType.STAGE_1 существует",
                "StageType.STAGE_1 отсутствует!"
            )

            self.logger.check(
                hasattr(StageType, 'STAGE_2'),
                "StageType.STAGE_2 существует",
                "StageType.STAGE_2 отсутствует!"
            )

            self.logger.check(
                hasattr(StageType, 'FINAL'),
                "StageType.FINAL существует",
                "StageType.FINAL отсутствует!"
            )

            # Выводим значения
            self.logger.data("STAGE_1", StageType.STAGE_1.value)
            self.logger.data("STAGE_2", StageType.STAGE_2.value)
            self.logger.data("FINAL", StageType.FINAL.value)

        except Exception as e:
            self.logger.error(f"Ошибка проверки StageType: {str(e)}")

    def test_06_work_type_stage2(self):
        """ТЕСТ 6: Проверка assign_work_type_stage2 (делегирование M_22 -> M_21)"""
        self.logger.section("6. Проверка assign_work_type_stage2")

        try:
            from Daman_QGIS.managers import WorkTypeAssignmentManager, LayerType

            manager = WorkTypeAssignmentManager()

            # Проверяем наличие метода
            self.logger.check(
                hasattr(manager, 'assign_work_type_stage2'),
                "Метод assign_work_type_stage2 существует",
                "Метод assign_work_type_stage2 отсутствует!"
            )

            # Тестовые данные для 2 этапа (объединение)
            test_data = [
                {
                    'geometry': None,
                    'attributes': {
                        'ID': 5,
                        'План_ВРИ': 'Тестовый ВРИ',
                        'Состав_контуров': '100, 101, 102'
                    },
                    'merged_contours': '100, 101, 102',
                    'zpr_id': 5
                }
            ]

            # Вызываем assign_work_type_stage2
            result = manager.assign_work_type_stage2(test_data, LayerType.RAZDEL)

            self.logger.check(
                result is not None,
                "assign_work_type_stage2 вернул результат",
                "assign_work_type_stage2 вернул None!"
            )

            if result and len(result) > 0:
                attrs = result[0].get('attributes', {})
                work_type = attrs.get('Вид_Работ', '')

                self.logger.check(
                    'Вид_Работ' in attrs,
                    f"Поле Вид_Работ присвоено",
                    "Поле Вид_Работ не присвоено!"
                )

                # Для 2 этапа Вид_Работ должен содержать "объединения"
                self.logger.check(
                    'объединени' in work_type.lower(),
                    f"Вид_Работ содержит 'объединения': '{work_type[:60]}...'",
                    f"Вид_Работ не содержит 'объединения': '{work_type[:60]}...'"
                )

        except Exception as e:
            self.logger.error(f"Ошибка проверки stage2: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
