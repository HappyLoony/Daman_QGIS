# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_4_1 - Тесты для F_3_1_LesZPR (Нарезка ЗПР по лесным выделам)

Тестирует:
- Инициализацию модуля и зависимости
- LAYER_MAPPING: корректность маппинга Le_2_* -> Le_3_*
- Валидацию полей лесного слоя через Fsm_3_1_2_AttributeMapper
- Логику поиска слоёв Le_2_* и лесных выделов
- Обработку пустых/отсутствующих слоёв
"""

import tempfile
import os
import shutil

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
    QgsField, QgsProject
)
from qgis.PyQt.QtCore import QMetaType


class TestF41:
    """Тесты для F_3_1_LesZPR - Нарезка ЗПР по лесным выделам"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.module = None
        self.test_dir = None

    def run_all_tests(self):
        """Запуск всех тестов F_3_1"""
        self.logger.section("ТЕСТ F_3_1: Нарезка ЗПР по лесным выделам")
        self.test_dir = tempfile.mkdtemp(prefix="qgis_test_f41_")

        try:
            # Инициализация
            self.test_01_init_module()
            self.test_02_check_methods()
            self.test_03_layer_mapping()

            # Субмодули
            self.test_04_attribute_mapper_init()
            self.test_05_attribute_mapper_fields()
            self.test_06_forest_cutter_init()

            # Валидация
            self.test_07_validate_forest_fields()
            self.test_08_get_le3_layers_empty()
            self.test_09_get_forest_layer_missing()

            # Константы
            self.test_10_constants_imported()

        except Exception as e:
            self.logger.error(f"Критическая ошибка: {e}")

        finally:
            if self.test_dir and os.path.exists(self.test_dir):
                try:
                    shutil.rmtree(self.test_dir)
                except Exception:
                    pass

        self.logger.summary()

    # --- Инициализация ---

    def test_01_init_module(self):
        """ТЕСТ 1: Инициализация F_3_1_LesZPR"""
        self.logger.section("1. Инициализация F_3_1_LesZPR")
        try:
            from Daman_QGIS.tools.F_3_hlu.F_3_1_les_zpr import F_3_1_LesZPR
            self.module = F_3_1_LesZPR(self.iface)

            self.logger.check(
                self.module is not None,
                "F_3_1_LesZPR создан",
                "F_3_1_LesZPR не создан!"
            )

            self.logger.check(
                hasattr(self.module, 'LAYER_MAPPING'),
                "LAYER_MAPPING существует",
                "LAYER_MAPPING отсутствует!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")
            self.module = None

    def test_02_check_methods(self):
        """ТЕСТ 2: Проверка методов модуля"""
        self.logger.section("2. Проверка методов")
        if not self.module:
            self.logger.skip("Модуль не инициализирован")
            return

        methods = [
            'run',
            'set_plugin_dir',
            'set_layer_manager',
            'set_project_manager',
            'get_name',
            '_get_forest_layer',
            '_get_le3_layers',
            '_validate_forest_fields',
            '_get_gpkg_path',
            '_execute_cutting',
        ]

        for method in methods:
            self.logger.check(
                hasattr(self.module, method),
                f"Метод {method}() существует",
                f"Метод {method}() отсутствует!"
            )

    def test_03_layer_mapping(self):
        """ТЕСТ 3: Проверка LAYER_MAPPING"""
        self.logger.section("3. LAYER_MAPPING")
        if not self.module:
            self.logger.skip("Модуль не инициализирован")
            return

        try:
            mapping = self.module.LAYER_MAPPING

            # Должно быть 28 маппингов (12 стандартных + 16 РЕК)
            self.logger.check(
                len(mapping) == 28,
                f"28 маппингов Le_2_* -> Le_3_*",
                f"Ожидалось 28, получено {len(mapping)}"
            )

            # Проверяем что все ключи начинаются с Le_2_
            le3_keys = [k for k in mapping.keys() if k.startswith('Le_2_')]
            self.logger.check(
                len(le3_keys) == 28,
                "Все ключи начинаются с Le_2_",
                f"Не все ключи Le_2_: {len(le3_keys)}/28"
            )

            # Проверяем что все значения начинаются с Le_3_
            le4_values = [v for v in mapping.values() if v.startswith('Le_3_')]
            self.logger.check(
                len(le4_values) == 28,
                "Все значения начинаются с Le_3_",
                f"Не все значения Le_3_: {len(le4_values)}/28"
            )

            # Проверяем стандартные категории Le_2_1_* (4 типа x 3 группы = 12)
            le3_1_count = sum(1 for k in mapping.keys() if k.startswith('Le_2_1_'))
            self.logger.check(
                le3_1_count == 12,
                f"Le_2_1_* (стандартные): 12 слоёв",
                f"Le_2_1_*: {le3_1_count} слоёв!"
            )

            # Проверяем РЕК категории Le_2_2_* (4 типа x 4 группы = 16)
            le3_2_count = sum(1 for k in mapping.keys() if k.startswith('Le_2_2_'))
            self.logger.check(
                le3_2_count == 16,
                f"Le_2_2_* (РЕК): 16 слоёв",
                f"Le_2_2_*: {le3_2_count} слоёв!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- Субмодули ---

    def test_04_attribute_mapper_init(self):
        """ТЕСТ 4: Инициализация Fsm_3_1_2_AttributeMapper"""
        self.logger.section("4. AttributeMapper инициализация")
        try:
            from Daman_QGIS.tools.F_3_hlu.submodules import Fsm_3_1_2_AttributeMapper
            mapper = Fsm_3_1_2_AttributeMapper()

            self.logger.check(
                mapper is not None,
                "Fsm_3_1_2_AttributeMapper создан",
                "Fsm_3_1_2_AttributeMapper не создан!"
            )

            self.logger.check(
                hasattr(mapper, 'validate_forest_layer_fields'),
                "Метод validate_forest_layer_fields() существует",
                "Метод validate_forest_layer_fields() отсутствует!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_05_attribute_mapper_fields(self):
        """ТЕСТ 5: AttributeMapper - обязательные поля"""
        self.logger.section("5. AttributeMapper поля")
        try:
            from Daman_QGIS.tools.F_3_hlu.submodules import Fsm_3_1_2_AttributeMapper
            mapper = Fsm_3_1_2_AttributeMapper()

            # Проверяем что есть список обязательных полей
            if hasattr(mapper, 'REQUIRED_FOREST_FIELDS'):
                fields = mapper.REQUIRED_FOREST_FIELDS
                self.logger.check(
                    len(fields) > 0,
                    f"REQUIRED_FOREST_FIELDS: {len(fields)} полей",
                    "REQUIRED_FOREST_FIELDS пустой!"
                )

                # Проверяем типичные поля
                expected = ['Лесничество', 'Номер_квартала', 'Номер_выдела']
                for f in expected:
                    self.logger.check(
                        f in fields,
                        f"Поле '{f}' в списке обязательных",
                        f"Поле '{f}' отсутствует!"
                    )
            else:
                self.logger.warning("REQUIRED_FOREST_FIELDS не определён")

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_06_forest_cutter_init(self):
        """ТЕСТ 6: Инициализация Fsm_3_1_1_ForestCutter"""
        self.logger.section("6. ForestCutter инициализация")
        try:
            from Daman_QGIS.tools.F_3_hlu.submodules import Fsm_3_1_1_ForestCutter

            # ForestCutter требует gpkg_path
            test_gpkg = os.path.join(self.test_dir, "test.gpkg")
            cutter = Fsm_3_1_1_ForestCutter(test_gpkg)

            self.logger.check(
                cutter is not None,
                "Fsm_3_1_1_ForestCutter создан",
                "Fsm_3_1_1_ForestCutter не создан!"
            )

            self.logger.check(
                hasattr(cutter, 'process_layer'),
                "Метод process_layer() существует",
                "Метод process_layer() отсутствует!"
            )

            self.logger.check(
                hasattr(cutter, 'clear_cache'),
                "Метод clear_cache() существует",
                "Метод clear_cache() отсутствует!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- Валидация ---

    def test_07_validate_forest_fields(self):
        """ТЕСТ 7: Валидация полей лесного слоя"""
        self.logger.section("7. Валидация полей лесного слоя")
        try:
            from Daman_QGIS.tools.F_3_hlu.submodules import Fsm_3_1_2_AttributeMapper
            mapper = Fsm_3_1_2_AttributeMapper()

            # Пустой список полей
            is_valid, missing = mapper.validate_forest_layer_fields([])
            self.logger.check(
                not is_valid,
                "Пустой список -> невалидно",
                "Пустой список -> валидно (ошибка)!"
            )
            self.logger.check(
                len(missing) > 0,
                f"Отсутствуют {len(missing)} полей",
                "Список missing пуст!"
            )

            # Полный список полей
            if hasattr(mapper, 'REQUIRED_FOREST_FIELDS'):
                full_fields = list(mapper.REQUIRED_FOREST_FIELDS)
                is_valid2, missing2 = mapper.validate_forest_layer_fields(full_fields)
                self.logger.check(
                    is_valid2,
                    "Полный список -> валидно",
                    f"Полный список -> невалидно, missing: {missing2}"
                )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_08_get_le3_layers_empty(self):
        """ТЕСТ 8: Получение слоёв Le_2_* (пустой проект)"""
        self.logger.section("8. Получение Le_2_* слоёв (пустой проект)")
        if not self.module:
            self.logger.skip("Модуль не инициализирован")
            return

        try:
            # В пустом проекте не должно быть Le_2_* слоёв
            result = self.module._get_le3_layers()

            self.logger.check(
                isinstance(result, dict),
                "Результат - словарь",
                f"Результат не словарь: {type(result)}"
            )

            # В тестовом окружении скорее всего пустой результат
            self.logger.info(f"Найдено слоёв Le_2_*: {len(result)}")

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_09_get_forest_layer_missing(self):
        """ТЕСТ 9: Получение слоя лесных выделов (отсутствует)"""
        self.logger.section("9. Получение слоя лесных выделов (отсутствует)")
        if not self.module:
            self.logger.skip("Модуль не инициализирован")
            return

        try:
            # В тестовом окружении слой отсутствует
            # Метод показывает QMessageBox, поэтому просто проверяем вызов
            # без фактического выполнения (чтобы не блокировать UI)

            from Daman_QGIS.constants import LAYER_FOREST_VYDELY
            layers = QgsProject.instance().mapLayersByName(LAYER_FOREST_VYDELY)

            self.logger.check(
                len(layers) == 0,
                f"Слой {LAYER_FOREST_VYDELY} отсутствует (ожидаемо)",
                f"Слой {LAYER_FOREST_VYDELY} найден (неожиданно)"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- Константы ---

    def test_10_constants_imported(self):
        """ТЕСТ 10: Импорт констант слоёв"""
        self.logger.section("10. Константы слоёв")
        try:
            from Daman_QGIS.constants import (
                LAYER_FOREST_VYDELY,
                LAYER_CUTTING_OKS_RAZDEL,
                LAYER_FOREST_STD_OKS_RAZDEL,
            )

            self.logger.check(
                LAYER_FOREST_VYDELY == "Le_3_1_1_1_Лес_Ред_Выделы",
                f"LAYER_FOREST_VYDELY = '{LAYER_FOREST_VYDELY}'",
                f"LAYER_FOREST_VYDELY неожиданное значение: '{LAYER_FOREST_VYDELY}'"
            )

            self.logger.check(
                'Le_2_' in LAYER_CUTTING_OKS_RAZDEL,
                f"LAYER_CUTTING_OKS_RAZDEL содержит Le_2_",
                f"LAYER_CUTTING_OKS_RAZDEL: '{LAYER_CUTTING_OKS_RAZDEL}'"
            )

            self.logger.check(
                'Le_3_2_' in LAYER_FOREST_STD_OKS_RAZDEL,
                f"LAYER_FOREST_STD_OKS_RAZDEL содержит Le_3_2_",
                f"LAYER_FOREST_STD_OKS_RAZDEL: '{LAYER_FOREST_STD_OKS_RAZDEL}'"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")


def run_tests(iface, logger):
    """Точка входа для запуска тестов"""
    test = TestF41(iface, logger)
    test.run_all_tests()
    return test
