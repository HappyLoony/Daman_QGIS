# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_33_1 - Тесты для Msm_33_1 HLU_DataProcessor

Тестирует:
- Инициализацию процессора
- Получение слоёв ЗПР
- Группировку по муниципальным округам
- Подготовку таблиц 1-6
- Форматирование данных
"""

from typing import Dict, List, Any


class TestMsm331:
    """Тесты для Msm_33_1 HLU_DataProcessor"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.processor = None

    def run_all_tests(self):
        """Запуск всех тестов Msm_33_1"""
        self.logger.section("ТЕСТ Msm_33_1: HLU_DataProcessor")

        try:
            # Тесты инициализации
            self.test_01_init_processor()
            self.test_02_check_constants()

            # Тесты статических методов форматирования
            self.test_03_format_area()
            self.test_04_format_area_zapas()

            # Тесты работы со слоями (без реального QGIS проекта)
            self.test_05_get_layer_none()
            self.test_06_zpr_layer_names()

            # Тесты подготовки контекста (структура)
            self.test_07_context_structure()
            self.test_08_rayon_context_structure()

            # Тесты LE4 (лесные слои)
            self.test_09_le4_layers_count()
            self.test_10_le4_zpr_types()
            self.test_11_determine_le4_zpr_type()

            # Тесты таблиц (заглушки)
            self.test_12_table_methods_exist()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов: {str(e)}")

        # Итоговая сводка
        self.logger.summary()

    def test_01_init_processor(self):
        """ТЕСТ 1: Инициализация процессора"""
        self.logger.section("1. Инициализация HLU_DataProcessor")

        try:
            from Daman_QGIS.managers import HLU_DataProcessor

            # Инициализация без менеджеров
            self.processor = HLU_DataProcessor()
            self.logger.success("HLU_DataProcessor создан без параметров")

            # Проверяем атрибуты
            self.logger.check(
                hasattr(self.processor, 'project_manager'),
                "Атрибут project_manager существует",
                "Атрибут project_manager отсутствует!"
            )

            self.logger.check(
                hasattr(self.processor, 'layer_manager'),
                "Атрибут layer_manager существует",
                "Атрибут layer_manager отсутствует!"
            )

            # Инициализация с менеджерами (mock)
            processor2 = HLU_DataProcessor(
                project_manager="mock_pm",
                layer_manager="mock_lm"
            )
            self.logger.check(
                processor2.project_manager == "mock_pm",
                "project_manager принят корректно",
                "project_manager не установлен!"
            )

            self.logger.success("Инициализация HLU_DataProcessor работает")

        except Exception as e:
            self.logger.error(f"Ошибка инициализации: {str(e)}")

    def test_02_check_constants(self):
        """ТЕСТ 2: Проверка констант"""
        self.logger.section("2. Проверка констант ZPR_LAYERS")

        try:
            from Daman_QGIS.managers import (
                ZPR_LAYERS,
                ZPR_FULL_NAMES,
                MO_LAYER_NAME
            )

            # Проверяем количество слоёв ЗПР
            self.logger.check(
                len(ZPR_LAYERS) == 7,
                f"ZPR_LAYERS содержит 7 элементов: {len(ZPR_LAYERS)}",
                f"ZPR_LAYERS содержит {len(ZPR_LAYERS)} элементов, ожидалось 7"
            )

            # Проверяем конкретные слои
            expected_layers = [
                "L_1_12_1_ЗПР_ОКС",
                "L_1_12_2_ЗПР_ПО",
                "L_1_12_3_ЗПР_ВО",
                "L_1_13_1_ЗПР_РЕК_АД",
                "L_1_13_2_ЗПР_СЕТИ_ПО",
                "L_1_13_3_ЗПР_СЕТИ_ВО",
                "L_1_13_4_ЗПР_НЭ"
            ]

            for layer in expected_layers:
                self.logger.check(
                    layer in ZPR_LAYERS,
                    f"Слой {layer} присутствует",
                    f"Слой {layer} отсутствует!"
                )

            # Проверяем полные названия
            self.logger.check(
                len(ZPR_FULL_NAMES) == 7,
                f"ZPR_FULL_NAMES содержит 7 элементов",
                f"ZPR_FULL_NAMES содержит {len(ZPR_FULL_NAMES)} элементов"
            )

            # Проверяем слой МО
            self.logger.check(
                MO_LAYER_NAME == "Le_1_2_3_12_АТД_МО_poly",
                f"MO_LAYER_NAME корректен: {MO_LAYER_NAME}",
                f"MO_LAYER_NAME некорректен: {MO_LAYER_NAME}"
            )

            self.logger.success("Константы ZPR корректны")

        except Exception as e:
            self.logger.error(f"Ошибка проверки констант: {str(e)}")

    def test_03_format_area(self):
        """ТЕСТ 3: Статический метод _format_area"""
        self.logger.section("3. Форматирование площади _format_area()")

        try:
            from Daman_QGIS.managers import HLU_DataProcessor

            # Стандартный случай
            result = HLU_DataProcessor._format_area(0.0231)
            self.logger.check(
                result == "0,0231",
                f"_format_area(0.0231) = '{result}'",
                f"Ожидалось '0,0231', получено '{result}'"
            )

            # Разное количество знаков
            result2 = HLU_DataProcessor._format_area(1.5, decimals=2)
            self.logger.check(
                result2 == "1,50",
                f"_format_area(1.5, decimals=2) = '{result2}'",
                f"Ожидалось '1,50', получено '{result2}'"
            )

            # None значение
            result3 = HLU_DataProcessor._format_area(None)
            self.logger.check(
                result3 == "-",
                f"_format_area(None) = '{result3}'",
                f"Ожидалось '-', получено '{result3}'"
            )

            self.logger.success("_format_area() работает корректно")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_04_format_area_zapas(self):
        """ТЕСТ 4: Статический метод _format_area_zapas"""
        self.logger.section("4. Форматирование _format_area_zapas()")

        try:
            from Daman_QGIS.managers import HLU_DataProcessor

            # Стандартный случай
            result = HLU_DataProcessor._format_area_zapas(0.0231, 15)
            self.logger.check(
                result == "0,0231 / 15",
                f"_format_area_zapas(0.0231, 15) = '{result}'",
                f"Ожидалось '0,0231 / 15', получено '{result}'"
            )

            # None площадь
            result2 = HLU_DataProcessor._format_area_zapas(None, 15)
            self.logger.check(
                result2 == "-",
                f"_format_area_zapas(None, 15) = '{result2}'",
                f"Ожидалось '-', получено '{result2}'"
            )

            # Нулевая площадь
            result3 = HLU_DataProcessor._format_area_zapas(0, 15)
            self.logger.check(
                result3 == "-",
                f"_format_area_zapas(0, 15) = '{result3}'",
                f"Ожидалось '-', получено '{result3}'"
            )

            self.logger.success("_format_area_zapas() работает корректно")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_05_get_layer_none(self):
        """ТЕСТ 5: get_layer без проекта"""
        self.logger.section("5. get_layer() без открытого проекта")

        try:
            # Без layer_manager - ищет в QgsProject
            result = self.processor.get_layer("Несуществующий_слой")

            self.logger.check(
                result is None,
                "get_layer() возвращает None для несуществующего слоя",
                f"get_layer() вернул {result}"
            )

            self.logger.success("get_layer() корректно обрабатывает отсутствующий слой")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_06_zpr_layer_names(self):
        """ТЕСТ 6: Проверка имён слоёв ЗПР"""
        self.logger.section("6. Проверка формата имён слоёв ЗПР")

        try:
            from Daman_QGIS.managers import ZPR_LAYERS

            # Все слои должны начинаться с L_2_
            for layer in ZPR_LAYERS:
                self.logger.check(
                    layer.startswith("L_1_1"),
                    f"Слой {layer} начинается с L_1_1",
                    f"Слой {layer} имеет неверный префикс!"
                )

            # Площадные ЗПР (L_1_12_*) vs линейные ЗПР (L_1_13_*)
            zpr_basic = [l for l in ZPR_LAYERS if l.startswith("L_1_12_")]
            zpr_rek = [l for l in ZPR_LAYERS if l.startswith("L_1_13_")]

            self.logger.check(
                len(zpr_basic) == 3,
                f"3 площадных слоя ЗПР (L_1_12_*): {zpr_basic}",
                f"Неверное количество площадных слоёв: {len(zpr_basic)}"
            )

            self.logger.check(
                len(zpr_rek) == 4,
                f"4 линейных слоя ЗПР (L_1_13_*): {zpr_rek}",
                f"Неверное количество линейных слоёв: {len(zpr_rek)}"
            )

            self.logger.success("Имена слоёв ЗПР соответствуют конвенции")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_07_context_structure(self):
        """ТЕСТ 7: Структура основного контекста"""
        self.logger.section("7. Структура prepare_full_context()")

        try:
            # Вызываем без слоёв - должен вернуть пустую структуру
            context = self.processor.prepare_full_context()

            self.logger.check(
                isinstance(context, dict),
                "prepare_full_context() возвращает dict",
                f"Неверный тип: {type(context)}"
            )

            # Проверяем обязательные ключи
            required_keys = ["prilozhenie_nomer", "nazvanie_dokumenta", "rayony"]
            for key in required_keys:
                self.logger.check(
                    key in context,
                    f"Ключ '{key}' присутствует в контексте",
                    f"Ключ '{key}' отсутствует!"
                )

            # rayony должен быть списком
            self.logger.check(
                isinstance(context.get("rayony"), list),
                "rayony является списком",
                f"rayony имеет тип {type(context.get('rayony'))}"
            )

            self.logger.success("Структура контекста корректна")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_08_rayon_context_structure(self):
        """ТЕСТ 8: Структура контекста района"""
        self.logger.section("8. Структура _prepare_rayon_context()")

        try:
            # Вызываем с пустым списком features
            rayon = self.processor._prepare_rayon_context("Тестовый район", [])

            self.logger.check(
                isinstance(rayon, dict),
                "_prepare_rayon_context() возвращает dict",
                f"Неверный тип: {type(rayon)}"
            )

            # Проверяем обязательные ключи
            required_keys = [
                "nazvanie",
                "table1_groups",
                "table2_vidy",
                "table3",
                "table4_rows",
                "table5_rows",
                "table6_rows",
                "table6_itogo_ploshad",
                "ozu_est",
                "ozu_types"
            ]

            for key in required_keys:
                self.logger.check(
                    key in rayon,
                    f"Ключ '{key}' присутствует в контексте района",
                    f"Ключ '{key}' отсутствует!"
                )

            # nazvanie должен быть равен переданному
            self.logger.check(
                rayon.get("nazvanie") == "Тестовый район",
                f"nazvanie = '{rayon.get('nazvanie')}'",
                f"nazvanie некорректен: {rayon.get('nazvanie')}"
            )

            self.logger.success("Структура контекста района корректна")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_09_le4_layers_count(self):
        """ТЕСТ 9: Проверка LE4_LAYERS (28 слоёв)"""
        self.logger.section("9. LE4_LAYERS количество и структура")

        try:
            from Daman_QGIS.managers.export.submodules.Msm_33_1_hlu_processor import (
                LE4_LAYERS,
            )

            le4 = LE4_LAYERS

            self.logger.check(
                len(le4) == 28,
                f"LE4_LAYERS: 28 слоёв",
                f"LE4_LAYERS: ожидалось 28, получено {len(le4)}"
            )

            # Стандартные Le_3_2_*
            le4_2 = [l for l in le4 if l.startswith("Le_3_2_")]
            self.logger.check(
                len(le4_2) == 12,
                f"Le_3_2_* (стандартные): 12",
                f"Le_3_2_*: {len(le4_2)}"
            )

            # РЕК Le_3_3_*
            le4_3 = [l for l in le4 if l.startswith("Le_3_3_")]
            self.logger.check(
                len(le4_3) == 16,
                f"Le_3_3_* (РЕК): 16",
                f"Le_3_3_*: {len(le4_3)}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_10_le4_zpr_types(self):
        """ТЕСТ 10: Проверка LE4_ZPR_TYPES (7 типов)"""
        self.logger.section("10. LE4_ZPR_TYPES")

        try:
            from Daman_QGIS.managers.export.submodules.Msm_33_1_hlu_processor import (
                LE4_ZPR_TYPES,
            )

            types = LE4_ZPR_TYPES

            self.logger.check(
                len(types) == 7,
                f"LE4_ZPR_TYPES: 7 типов",
                f"LE4_ZPR_TYPES: ожидалось 7, получено {len(types)}"
            )

            expected_keys = ["ОКС", "ПО", "ВО", "РЕК_АД", "СЕТИ_ПО", "СЕТИ_ВО", "НЭ"]
            for key in expected_keys:
                self.logger.check(
                    key in types,
                    f"Тип '{key}' присутствует",
                    f"Тип '{key}' отсутствует!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_11_determine_le4_zpr_type(self):
        """ТЕСТ 11: _determine_le4_zpr_type - определение типа ЗПР"""
        self.logger.section("11. _determine_le4_zpr_type()")

        try:
            from Daman_QGIS.managers.export.submodules.Msm_33_1_hlu_processor import (
                HLU_DataProcessor,
            )

            test_cases = [
                # Стандартные Le_3_2_*
                ("Le_3_2_1_1_Раздел_ЗПР_ОКС", "ОКС"),
                ("Le_3_2_2_3_Без_меж_ЗПР_ПО", "ПО"),
                ("Le_3_2_3_4_ПС_ЗПР_ВО", "ВО"),
                # РЕК Le_3_3_* (приоритет перед стандартными)
                ("Le_3_3_1_1_Раздел_ЗПР_РЕК_АД", "РЕК_АД"),
                ("Le_3_3_2_1_Раздел_ЗПР_СЕТИ_ПО", "СЕТИ_ПО"),
                ("Le_3_3_3_1_Раздел_ЗПР_СЕТИ_ВО", "СЕТИ_ВО"),
                ("Le_3_3_4_1_Раздел_ЗПР_НЭ", "НЭ"),
            ]

            for layer_name, expected_type in test_cases:
                result = HLU_DataProcessor._determine_le4_zpr_type(layer_name)
                self.logger.check(
                    result == expected_type,
                    f"{layer_name} -> '{result}'",
                    f"{layer_name}: ожидалось '{expected_type}', получено '{result}'!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_12_table_methods_exist(self):
        """ТЕСТ 12: Проверка методов подготовки таблиц"""
        self.logger.section("12. Проверка методов таблиц")

        try:
            # Методы для таблиц 1-6
            table_methods = [
                "_prepare_table1",
                "_prepare_table2",
                "_prepare_table3",
                "_prepare_table4",
                "_prepare_table5",
                "_prepare_table6",
                "_prepare_ozu"
            ]

            for method in table_methods:
                self.logger.check(
                    hasattr(self.processor, method),
                    f"Метод {method}() существует",
                    f"Метод {method}() отсутствует!"
                )

            # Вспомогательные методы
            helper_methods = [
                "get_layer",
                "get_zpr_layers",
                "get_mo_layer",
                "extract_forest_features",
                "group_by_municipality"
            ]

            for method in helper_methods:
                self.logger.check(
                    hasattr(self.processor, method),
                    f"Метод {method}() существует",
                    f"Метод {method}() отсутствует!"
                )

            self.logger.success("Все методы таблиц присутствуют")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")


def run_tests(iface, logger):
    """Точка входа для запуска тестов"""
    test = TestMsm331(iface, logger)
    test.run_all_tests()
    return test
