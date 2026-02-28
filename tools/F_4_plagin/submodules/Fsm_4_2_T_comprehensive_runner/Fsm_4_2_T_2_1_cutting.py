# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_3_1_cutting - Тест функции F_2_1_Нарезка ЗПР
Проверка нарезки контуров ЗПР по границам существующих ЗУ
"""


class TestF31Cutting:
    """Тесты для F_2_1_NarezkaZpr (нарезка ЗПР)"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.module = None

    def run_all_tests(self):
        """Запуск всех тестов F_2_1 Нарезка"""
        self.logger.section("ТЕСТ F_2_1: Нарезка ЗПР")

        try:
            self.test_01_init_module()
            self.test_02_check_dependencies()
            self.test_03_submodules_availability()
            self.test_04_managers_availability()
            self.test_05_constants_availability()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов F_2_1_Cutting: {str(e)}")

        self.logger.summary()

    def test_01_init_module(self):
        """ТЕСТ 1: Инициализация модуля F_2_1_NarezkaZPR"""
        self.logger.section("1. Инициализация F_2_1_NarezkaZPR")

        try:
            from Daman_QGIS.tools.F_2_cutting.F_2_1_narezka_zpr import F_2_1_NarezkaZPR

            self.module = F_2_1_NarezkaZPR(self.iface)
            self.logger.success("Модуль F_2_1_NarezkaZPR загружен")

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
                    "3_1" in name or "Нарезка" in name,
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
                LAYER_CUTTING_OKS_RAZDEL, LAYER_CUTTING_OKS_NGS,
                LAYER_CUTTING_PO_RAZDEL, LAYER_CUTTING_PO_NGS,
                LAYER_CUTTING_VO_RAZDEL, LAYER_CUTTING_VO_NGS
            )
            self.logger.success("constants (LAYER_CUTTING_*) доступны")

            # Проверяем utils
            from Daman_QGIS.utils import log_info, log_warning, log_error
            self.logger.success("utils (log_*) доступны")

        except Exception as e:
            self.logger.error(f"Ошибка проверки зависимостей: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_03_submodules_availability(self):
        """ТЕСТ 3: Проверка доступности субмодулей F_2_1"""
        self.logger.section("3. Проверка субмодулей F_2_1")

        submodules = [
            ('Fsm_2_1_3_layer_creator', 'Fsm_2_1_3_LayerCreator'),
            ('Fsm_2_1_5_kk_matcher', 'Fsm_2_1_5_KKMatcher'),
            ('Fsm_2_1_6_point_layer_creator', 'Fsm_2_1_6_PointLayerCreator'),
        ]

        # Msm_26_* субмодули (каноническая реализация в managers/geometry/)
        msm_submodules = [
            ('Msm_26_1_geometry_processor', 'Msm_26_1_GeometryProcessor'),
            ('Msm_26_2_attribute_mapper', 'Msm_26_2_AttributeMapper'),
            ('Msm_26_4_cutting_engine', 'Msm_26_4_CuttingEngine'),
        ]

        for module_file, class_name in submodules:
            try:
                module = __import__(
                    f'Daman_QGIS.tools.F_2_cutting.submodules.{module_file}',
                    fromlist=[class_name]
                )
                if hasattr(module, class_name):
                    self.logger.success(f"{class_name} доступен")
                else:
                    self.logger.warning(f"{class_name} не найден в модуле")
            except Exception as e:
                self.logger.fail(f"{class_name}: ошибка импорта - {str(e)[:50]}")

        for module_file, class_name in msm_submodules:
            try:
                module = __import__(
                    f'Daman_QGIS.managers.geometry.submodules.{module_file}',
                    fromlist=[class_name]
                )
                if hasattr(module, class_name):
                    self.logger.success(f"{class_name} доступен")
                else:
                    self.logger.warning(f"{class_name} не найден в модуле")
            except Exception as e:
                self.logger.fail(f"{class_name}: ошибка импорта - {str(e)[:50]}")

    def test_04_managers_availability(self):
        """ТЕСТ 4: Проверка доступности менеджеров для нарезки"""
        self.logger.section("4. Проверка менеджеров")

        try:
            # M_22 WorkTypeAssignmentManager
            from Daman_QGIS.managers import WorkTypeAssignmentManager, LayerType
            self.logger.success("WorkTypeAssignmentManager доступен")

            # Проверяем enum LayerType
            self.logger.check(
                hasattr(LayerType, 'RAZDEL'),
                "LayerType.RAZDEL существует",
                "LayerType.RAZDEL отсутствует!"
            )
            self.logger.check(
                hasattr(LayerType, 'NGS'),
                "LayerType.NGS существует",
                "LayerType.NGS отсутствует!"
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

    def test_05_constants_availability(self):
        """ТЕСТ 5: Проверка констант слоёв нарезки"""
        self.logger.section("5. Проверка констант слоёв")

        try:
            from Daman_QGIS.constants import (
                # Полигональные слои
                LAYER_CUTTING_OKS_RAZDEL, LAYER_CUTTING_OKS_NGS,
                LAYER_CUTTING_PO_RAZDEL, LAYER_CUTTING_PO_NGS,
                LAYER_CUTTING_VO_RAZDEL, LAYER_CUTTING_VO_NGS,
                # Точечные слои
                LAYER_CUTTING_POINTS_OKS_RAZDEL, LAYER_CUTTING_POINTS_OKS_NGS,
                LAYER_CUTTING_POINTS_PO_RAZDEL, LAYER_CUTTING_POINTS_PO_NGS,
                LAYER_CUTTING_POINTS_VO_RAZDEL, LAYER_CUTTING_POINTS_VO_NGS,
            )

            self.logger.success("Константы полигональных слоёв доступны")
            self.logger.success("Константы точечных слоёв доступны")

            # Проверяем формат констант (Le_2_ для дополнительных слоёв или L_2_ для основных)
            self.logger.check(
                "L_2_" in LAYER_CUTTING_OKS_RAZDEL or "Le_2_" in LAYER_CUTTING_OKS_RAZDEL,
                f"Формат LAYER_CUTTING_OKS_RAZDEL корректный: '{LAYER_CUTTING_OKS_RAZDEL}'",
                f"Формат LAYER_CUTTING_OKS_RAZDEL некорректный: '{LAYER_CUTTING_OKS_RAZDEL}'"
            )

        except ImportError as e:
            self.logger.fail(f"Константы недоступны: {str(e)}")
        except Exception as e:
            self.logger.error(f"Ошибка проверки констант: {str(e)}")
