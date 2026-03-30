# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_13 - Тестирование M_13 DataCleanupManager

Тестирует:
- Импорт модуля, структура субменеджеров
- sanitize_attribute_value() - очистка значений атрибутов
- sanitize_filename() - очистка имен файлов для Windows
- normalize_null_value() - нормализация NULL значений
- normalize_rights_order() - переупорядочивание прав
- deduplicate_encumbrances_and_tenants() - дедупликация пар
- simplify_rent_individuals() - упрощение арендаторов-физлиц
- capitalize_field() - капитализация полей
- parse_field() / join_field() - парсинг и сборка
- remove_line_breaks() / normalize_separators() - строковые утилиты
- FieldCleanup - проверка и удаление пустых полей
- DataValidator - валидация метаданных
- finalize_layer() - end-to-end обработка слоя
"""

from typing import Any, Optional


class TestDataCleanupManager:
    """Тесты M_13 DataCleanupManager"""

    def __init__(self, iface: Any, logger: Any) -> None:
        self.iface = iface
        self.logger = logger
        self.manager = None

    def run_all_tests(self) -> None:
        """Запуск всех тестов M_13"""
        self.logger.section("ТЕСТ M_13: DataCleanupManager")

        try:
            # Группа 1: Импорт и структура
            self.test_01_import_module()
            self.test_02_submanager_structure()

            # Группа 2: StringSanitizer (Msm_13_1)
            self.test_03_sanitize_attribute_value_semicolons()
            self.test_04_sanitize_attribute_value_empty_inputs()
            self.test_05_sanitize_filename_forbidden_chars()
            self.test_06_sanitize_filename_reserved_names()
            self.test_07_sanitize_filename_edge_cases()
            self.test_08_sanitize_layer_name()
            self.test_09_remove_line_breaks()
            self.test_10_normalize_separators()

            # Группа 3: AttributeProcessor (Msm_13_2)
            self.test_11_normalize_null_value_none_and_empty()
            self.test_12_normalize_null_value_special_fields()
            self.test_13_normalize_null_value_string_null()
            self.test_14_parse_field()
            self.test_15_join_field()
            self.test_16_capitalize_field()
            self.test_17_capitalize_first_letter_abbreviation()
            self.test_18_normalize_rights_order_basic()
            self.test_19_normalize_rights_order_already_first()
            self.test_20_deduplicate_encumbrances()
            self.test_21_simplify_rent_individuals()
            self.test_22_simplify_rent_individuals_below_threshold()
            self.test_23_is_ngs_by_kn()

            # Группа 4: FieldCleanup (Msm_13_3)
            self.test_24_is_field_empty()
            self.test_25_get_empty_fields()
            self.test_26_remove_empty_fields()

            # Группа 5: DataValidator (Msm_13_4)
            self.test_27_validator_without_metadata_manager()
            self.test_28_validate_attribute_value()

            # Группа 6: AttributeMapper (Msm_13_5)
            self.test_29_normalize_field_value()

            # Группа 7: End-to-end
            self.test_30_finalize_layer_e2e()
            self.test_31_get_statistics()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов M_13: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    # === Helpers ===

    def _create_memory_layer(self, field_defs, features_data, layer_name="test_layer"):
        """
        Создание in-memory слоя для тестов

        Args:
            field_defs: список кортежей (имя_поля, тип_qgis) - например [("Права", "string"), ("Площадь", "integer")]
            features_data: список словарей с данными - например [{"Права": "Собственность", "Площадь": 100}]
            layer_name: имя слоя

        Returns:
            QgsVectorLayer или None
        """
        from qgis.core import QgsVectorLayer, QgsFeature, QgsField
        from qgis.PyQt.QtCore import QMetaType

        type_map = {
            "string": QMetaType.Type.QString,
            "integer": QMetaType.Type.Int,
        }

        # Формируем URI для memory layer
        field_uri_parts = []
        for fname, ftype in field_defs:
            if ftype == "string":
                field_uri_parts.append(f"field={fname}:string(255)")
            elif ftype == "integer":
                field_uri_parts.append(f"field={fname}:integer")

        uri = f"Polygon?crs=EPSG:4326&{'&'.join(field_uri_parts)}"
        layer = QgsVectorLayer(uri, layer_name, "memory")

        if not layer.isValid():
            return None

        # Добавляем объекты
        provider = layer.dataProvider()
        for data in features_data:
            feat = QgsFeature(layer.fields())
            for fname, fvalue in data.items():
                idx = layer.fields().lookupField(fname)
                if idx >= 0:
                    feat.setAttribute(idx, fvalue)
            provider.addFeature(feat)

        layer.updateExtents()
        return layer

    # === Группа 1: Импорт и структура ===

    def test_01_import_module(self) -> None:
        """ТЕСТ 1: Импорт M_13 DataCleanupManager"""
        self.logger.section("1. Импорт модуля")

        try:
            from Daman_QGIS.managers.processing.M_13_data_cleanup_manager import DataCleanupManager
            self.manager = DataCleanupManager()
            self.logger.check(
                self.manager is not None,
                "DataCleanupManager создан",
                "DataCleanupManager не создан"
            )
        except Exception as e:
            self.logger.fail(f"Ошибка импорта DataCleanupManager: {e}")

    def test_02_submanager_structure(self) -> None:
        """ТЕСТ 2: Проверка структуры субменеджеров"""
        self.logger.section("2. Структура субменеджеров")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            # Проверяем наличие всех субменеджеров
            submanagers = {
                'string_sanitizer': 'StringSanitizer',
                'attribute_processor': 'AttributeProcessor',
                'field_cleanup': 'FieldCleanup',
                'data_validator': 'DataValidator',
                'attribute_mapper': 'AttributeMapper',
            }

            for attr_name, class_name in submanagers.items():
                has_attr = hasattr(self.manager, attr_name)
                obj = getattr(self.manager, attr_name, None)
                self.logger.check(
                    has_attr and obj is not None,
                    f"Субменеджер {class_name} ({attr_name}) доступен",
                    f"Субменеджер {class_name} ({attr_name}) отсутствует"
                )

            # Проверяем наличие делегирующих методов
            delegate_methods = [
                'sanitize_filename', 'sanitize_attribute_value', 'sanitize_layer_name',
                'remove_line_breaks', 'normalize_separators',
                'parse_field', 'join_field', 'capitalize_field',
                'normalize_null_value', 'normalize_rights_order',
                'deduplicate_encumbrances_and_tenants', 'simplify_rent_individuals',
                'finalize_layer',
                'is_field_empty', 'get_empty_fields', 'remove_empty_fields',
                'validate_metadata', 'validate_required_fields',
                'map_attributes', 'normalize_field_value', 'finalize_layer_null_values',
                'get_statistics',
            ]

            for method_name in delegate_methods:
                has_method = hasattr(self.manager, method_name) and callable(getattr(self.manager, method_name))
                self.logger.check(
                    has_method,
                    f"Метод {method_name}() доступен",
                    f"Метод {method_name}() отсутствует"
                )

        except Exception as e:
            self.logger.fail(f"Ошибка проверки структуры: {e}")

    # === Группа 2: StringSanitizer (Msm_13_1) ===

    def test_03_sanitize_attribute_value_semicolons(self) -> None:
        """ТЕСТ 3: sanitize_attribute_value - замена ; на /"""
        self.logger.section("3. sanitize_attribute_value: разделители")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            # Базовая замена точки с запятой
            result = self.manager.sanitize_attribute_value("Право1;Право2")
            self.logger.check(
                result == "Право1 / Право2",
                f"';' -> ' / ': '{result}'",
                f"Ожидалось 'Право1 / Право2', получено '{result}'"
            )

            # Пробелы вокруг точки с запятой
            result2 = self.manager.sanitize_attribute_value("Право1 ; Право2")
            self.logger.check(
                result2 == "Право1 / Право2",
                f"' ; ' -> ' / ': '{result2}'",
                f"Ожидалось 'Право1 / Право2', получено '{result2}'"
            )

            # Множественные разделители
            result3 = self.manager.sanitize_attribute_value("A;B;C")
            self.logger.check(
                result3 == "A / B / C",
                f"Множественные ';': '{result3}'",
                f"Ожидалось 'A / B / C', получено '{result3}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста sanitize_attribute_value: {e}")

    def test_04_sanitize_attribute_value_empty_inputs(self) -> None:
        """ТЕСТ 4: sanitize_attribute_value - пустые/невалидные входы"""
        self.logger.section("4. sanitize_attribute_value: пустые входы")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            # None
            result_none = self.manager.sanitize_attribute_value(None)
            self.logger.check(
                result_none is None,
                "None -> None",
                f"None -> '{result_none}' (ожидалось None)"
            )

            # Пустая строка
            result_empty = self.manager.sanitize_attribute_value("")
            self.logger.check(
                result_empty == "" or result_empty is None,
                f"Пустая строка -> '{result_empty}'",
                f"Пустая строка -> неожиданный результат: '{result_empty}'"
            )

            # Не строка (число)
            result_int = self.manager.sanitize_attribute_value(42)
            self.logger.check(
                result_int == 42,
                f"Число 42 -> {result_int} (без изменений)",
                f"Число 42 -> неожиданный результат: {result_int}"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_05_sanitize_filename_forbidden_chars(self) -> None:
        """ТЕСТ 5: sanitize_filename - запрещенные символы Windows"""
        self.logger.section("5. sanitize_filename: запрещенные символы")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            # Двоеточие
            result = self.manager.sanitize_filename("Слой: Здания")
            self.logger.check(
                ':' not in result,
                f"Двоеточие удалено: '{result}'",
                f"Двоеточие осталось: '{result}'"
            )

            # Слэш
            result2 = self.manager.sanitize_filename("Файл/Данные")
            self.logger.check(
                '/' not in result2,
                f"Слэш удален: '{result2}'",
                f"Слэш остался: '{result2}'"
            )

            # Множественные подчеркивания
            result3 = self.manager.sanitize_filename("Граница___работ")
            self.logger.check(
                '___' not in result3 and '__' not in result3,
                f"Множественные '_' схлопнуты: '{result3}'",
                f"Множественные '_' остались: '{result3}'"
            )

            # Все запрещенные символы
            result4 = self.manager.sanitize_filename('Тест<>:"/\\|?*Файл')
            forbidden = '<>:"/\\|?*'
            has_forbidden = any(c in result4 for c in forbidden)
            self.logger.check(
                not has_forbidden,
                f"Все запрещенные символы удалены: '{result4}'",
                f"Запрещенные символы остались: '{result4}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста sanitize_filename: {e}")

    def test_06_sanitize_filename_reserved_names(self) -> None:
        """ТЕСТ 6: sanitize_filename - зарезервированные имена Windows"""
        self.logger.section("6. sanitize_filename: зарезервированные имена")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            result = self.manager.sanitize_filename("CON")
            self.logger.check(
                result != "CON",
                f"CON экранирован: '{result}'",
                f"CON не экранирован: '{result}'"
            )

            result2 = self.manager.sanitize_filename("PRN")
            self.logger.check(
                result2 != "PRN",
                f"PRN экранирован: '{result2}'",
                f"PRN не экранирован: '{result2}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_07_sanitize_filename_edge_cases(self) -> None:
        """ТЕСТ 7: sanitize_filename - краевые случаи"""
        self.logger.section("7. sanitize_filename: краевые случаи")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            # Пустая строка -> ValueError
            error_raised = False
            try:
                self.manager.sanitize_filename("")
            except ValueError:
                error_raised = True
            self.logger.check(
                error_raised,
                "Пустая строка -> ValueError",
                "Пустая строка не вызвала ValueError"
            )

            # None -> ValueError
            error_raised = False
            try:
                self.manager.sanitize_filename(None)
            except ValueError:
                error_raised = True
            self.logger.check(
                error_raised,
                "None -> ValueError",
                "None не вызвал ValueError"
            )

            # Строка с точками и пробелами на конце
            result = self.manager.sanitize_filename("Данные...")
            self.logger.check(
                not result.endswith('.'),
                f"Точки с конца удалены: '{result}'",
                f"Точки остались на конце: '{result}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_08_sanitize_layer_name(self) -> None:
        """ТЕСТ 8: sanitize_layer_name - делегирует к sanitize_filename"""
        self.logger.section("8. sanitize_layer_name")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            result = self.manager.sanitize_layer_name("L_1_1_1: Границы работ")
            self.logger.check(
                ':' not in result,
                f"sanitize_layer_name работает: '{result}'",
                f"sanitize_layer_name не очистил: '{result}'"
            )
        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_09_remove_line_breaks(self) -> None:
        """ТЕСТ 9: remove_line_breaks - удаление переносов строк"""
        self.logger.section("9. remove_line_breaks")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            result = self.manager.remove_line_breaks("Строка1\nСтрока2\r\nСтрока3")
            self.logger.check(
                '\n' not in result and '\r' not in result,
                f"Переносы удалены: '{result}'",
                f"Переносы остались: '{result}'"
            )

            # Множественные пробелы схлопываются
            result2 = self.manager.remove_line_breaks("A  \n  B")
            self.logger.check(
                '  ' not in result2,
                f"Пробелы схлопнуты: '{result2}'",
                f"Пробелы не схлопнуты: '{result2}'"
            )

            # None возвращается как есть
            result_none = self.manager.remove_line_breaks(None)
            self.logger.check(
                result_none is None,
                "None -> None",
                f"None -> '{result_none}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_10_normalize_separators(self) -> None:
        """ТЕСТ 10: normalize_separators - нормализация разделителей"""
        self.logger.section("10. normalize_separators")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            result = self.manager.normalize_separators("A;B|C/D")
            expected = "A / B / C / D"
            self.logger.check(
                result == expected,
                f"Разделители нормализованы: '{result}'",
                f"Ожидалось '{expected}', получено '{result}'"
            )

            # С кастомным разделителем
            result2 = self.manager.normalize_separators("A;B;C", target_separator=", ")
            expected2 = "A, B, C"
            self.logger.check(
                result2 == expected2,
                f"Кастомный разделитель: '{result2}'",
                f"Ожидалось '{expected2}', получено '{result2}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    # === Группа 3: AttributeProcessor (Msm_13_2) ===

    def test_11_normalize_null_value_none_and_empty(self) -> None:
        """ТЕСТ 11: normalize_null_value - None и пустая строка"""
        self.logger.section("11. normalize_null_value: None/пустое")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            # None -> "-" для обычного поля
            result = self.manager.normalize_null_value(None, "ОбычноеПоле")
            self.logger.check(
                result == "-",
                f"None для обычного поля -> '{result}'",
                f"Ожидалось '-', получено '{result}'"
            )

            # Пустая строка -> "-"
            result2 = self.manager.normalize_null_value("", "ОбычноеПоле")
            self.logger.check(
                result2 == "-",
                f"Пустая строка -> '{result2}'",
                f"Ожидалось '-', получено '{result2}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_12_normalize_null_value_special_fields(self) -> None:
        """ТЕСТ 12: normalize_null_value - специальные поля"""
        self.logger.section("12. normalize_null_value: специальные поля")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            # Поле "Права" -> "Сведения отсутствуют"
            result = self.manager.normalize_null_value(None, "Права")
            self.logger.check(
                result == "Сведения отсутствуют",
                f"Права (None) -> '{result}'",
                f"Ожидалось 'Сведения отсутствуют', получено '{result}'"
            )

            # Поле "Собственники" -> "Сведения отсутствуют"
            result2 = self.manager.normalize_null_value("", "Собственники")
            self.logger.check(
                result2 == "Сведения отсутствуют",
                f"Собственники (пусто) -> '{result2}'",
                f"Ожидалось 'Сведения отсутствуют', получено '{result2}'"
            )

            # Поле "Категория" -> "Категория не установлена"
            result3 = self.manager.normalize_null_value(None, "Категория")
            self.logger.check(
                result3 == "Категория не установлена",
                f"Категория (None) -> '{result3}'",
                f"Ожидалось 'Категория не установлена', получено '{result3}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_13_normalize_null_value_string_null(self) -> None:
        """ТЕСТ 13: normalize_null_value - строка 'NULL'"""
        self.logger.section("13. normalize_null_value: строка NULL")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            # Строка "NULL" для обычного поля -> "-"
            result = self.manager.normalize_null_value("NULL", "ОбычноеПоле")
            self.logger.check(
                result == "-",
                f"'NULL' -> '{result}'",
                f"Ожидалось '-', получено '{result}'"
            )

            # Строка "NULL" для специального поля
            result2 = self.manager.normalize_null_value("NULL", "Права")
            self.logger.check(
                result2 == "Сведения отсутствуют",
                f"'NULL' для Права -> '{result2}'",
                f"Ожидалось 'Сведения отсутствуют', получено '{result2}'"
            )

            # Непустая строка не трогается
            result3 = self.manager.normalize_null_value("Собственность", "Права")
            self.logger.check(
                result3 == "Собственность",
                f"Непустое значение сохранено: '{result3}'",
                f"Непустое значение изменено: '{result3}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_14_parse_field(self) -> None:
        """ТЕСТ 14: parse_field - разбор множественных значений"""
        self.logger.section("14. parse_field")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            # Разбор через " / "
            result = self.manager.parse_field("Право1 / Право2 / Право3")
            self.logger.check(
                result == ["Право1", "Право2", "Право3"],
                f"Парсинг 3 значений: {result}",
                f"Ожидалось ['Право1', 'Право2', 'Право3'], получено {result}"
            )

            # Фильтрация "-"
            result2 = self.manager.parse_field("Право1 / - / Право2")
            self.logger.check(
                result2 == ["Право1", "Право2"],
                f"'-' отфильтрован: {result2}",
                f"'-' не отфильтрован: {result2}"
            )

            # None
            result3 = self.manager.parse_field(None)
            self.logger.check(
                result3 == [],
                "None -> []",
                f"None -> {result3}"
            )

            # Одиночный "-"
            result4 = self.manager.parse_field("-")
            self.logger.check(
                result4 == [],
                "'-' -> []",
                f"'-' -> {result4}"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_15_join_field(self) -> None:
        """ТЕСТ 15: join_field - объединение значений"""
        self.logger.section("15. join_field")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            result = self.manager.join_field(["Право1", "Право2"])
            self.logger.check(
                result == "Право1 / Право2",
                f"Объединение: '{result}'",
                f"Ожидалось 'Право1 / Право2', получено '{result}'"
            )

            # Пустой список
            result2 = self.manager.join_field([])
            self.logger.check(
                result2 == "-",
                f"Пустой список -> '{result2}'",
                f"Ожидалось '-', получено '{result2}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_16_capitalize_field(self) -> None:
        """ТЕСТ 16: capitalize_field - капитализация"""
        self.logger.section("16. capitalize_field")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            # Простая строка
            result = self.manager.capitalize_field("хранение автотранспорта")
            self.logger.check(
                result.startswith("Х"),
                f"Капитализация: '{result}'",
                f"Не капитализировано: '{result}'"
            )

            # Через разделитель
            result2 = self.manager.capitalize_field("постоянное пользование / собственность")
            parts = result2.split(" / ")
            all_capitalized = all(
                p[0].isupper() if p and p[0].isalpha() else True
                for p in parts
            )
            self.logger.check(
                all_capitalized,
                f"Множественная капитализация: '{result2}'",
                f"Не все части капитализированы: '{result2}'"
            )

            # Пустое значение
            result3 = self.manager.capitalize_field(None)
            self.logger.check(
                result3 == "-",
                f"None -> '{result3}'",
                f"None -> неожиданный результат: '{result3}'"
            )

            # Строка с числом вначале
            result4 = self.manager.capitalize_field("7.1. сооружения")
            self.logger.check(
                "С" in result4 or "с" in result4,
                f"Числовой префикс: '{result4}'",
                f"Ошибка обработки: '{result4}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_17_capitalize_first_letter_abbreviation(self) -> None:
        """ТЕСТ 17: capitalize_first_letter - исключение для сокращений"""
        self.logger.section("17. capitalize_first_letter: сокращения")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            processor = self.manager.attribute_processor

            # Сокращение "д." не должно капитализироваться
            result = processor.capitalize_first_letter("д. Овсянниково")
            self.logger.check(
                result == "д. Овсянниково",
                f"Сокращение 'д.' не тронуто: '{result}'",
                f"Сокращение 'д.' изменено: '{result}'"
            )

            # Обычное слово капитализируется
            result2 = processor.capitalize_first_letter("муниципальное образование")
            self.logger.check(
                result2 == "Муниципальное образование",
                f"Капитализация: '{result2}'",
                f"Ожидалось 'Муниципальное образование', получено '{result2}'"
            )

            # Пустая строка
            result3 = processor.capitalize_first_letter("")
            self.logger.check(
                result3 == "",
                f"Пустая строка сохранена: '{result3}'",
                f"Пустая строка изменена: '{result3}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_18_normalize_rights_order_basic(self) -> None:
        """ТЕСТ 18: normalize_rights_order - переупорядочивание"""
        self.logger.section("18. normalize_rights_order: переупорядочивание")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            rights, owners = self.manager.normalize_rights_order(
                "Постоянное (бессрочное) пользование / Собственность",
                "Муниципальная / Частная"
            )
            self.logger.check(
                rights.startswith("Собственность"),
                f"Права переупорядочены: '{rights}'",
                f"Права не переупорядочены: '{rights}'"
            )
            self.logger.check(
                owners.startswith("Частная"),
                f"Собственники синхронизированы: '{owners}'",
                f"Собственники не синхронизированы: '{owners}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_19_normalize_rights_order_already_first(self) -> None:
        """ТЕСТ 19: normalize_rights_order - уже на первом месте"""
        self.logger.section("19. normalize_rights_order: без изменений")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            rights, owners = self.manager.normalize_rights_order(
                "Собственность / Аренда",
                "Частная / ООО"
            )
            self.logger.check(
                rights == "Собственность / Аренда",
                f"Порядок сохранен: '{rights}'",
                f"Порядок изменен: '{rights}'"
            )

            # Пустые значения
            rights2, owners2 = self.manager.normalize_rights_order("-", "-")
            self.logger.check(
                rights2 == "-",
                f"'-' без изменений: '{rights2}'",
                f"'-' изменено: '{rights2}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_20_deduplicate_encumbrances(self) -> None:
        """ТЕСТ 20: deduplicate_encumbrances_and_tenants"""
        self.logger.section("20. deduplicate_encumbrances_and_tenants")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            enc, ten = self.manager.deduplicate_encumbrances_and_tenants(
                "Аренда / Сервитут / Аренда / Аренда",
                "Физ1 / ООО / Физ1 / Физ1"
            )

            # Должно остаться: Аренда / Сервитут (дубликаты Аренда+Физ1 удалены)
            enc_parts = [p.strip() for p in enc.split(" / ")]
            self.logger.check(
                enc_parts.count("Аренда") < 3,
                f"Дубликаты аренды удалены: '{enc}'",
                f"Дубликаты аренды не удалены: '{enc}'"
            )

            # Сервитут не дедуплицируется
            self.logger.check(
                "Сервитут" in enc,
                f"Сервитут сохранен: '{enc}'",
                f"Сервитут потерян: '{enc}'"
            )

            # Пустые входы
            enc2, ten2 = self.manager.deduplicate_encumbrances_and_tenants(None, "Физ1")
            self.logger.check(
                enc2 == "-",
                f"None -> '-': '{enc2}'",
                f"None -> неожиданный: '{enc2}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_21_simplify_rent_individuals(self) -> None:
        """ТЕСТ 21: simplify_rent_individuals - упрощение физлиц"""
        self.logger.section("21. simplify_rent_individuals")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            enc, ten = self.manager.simplify_rent_individuals(
                'Аренда / Сервитут / Аренда / Аренда / Аренда',
                'Физическое лицо / ООО "ИЛАР" / Физическое лицо / Физическое лицо / Физическое лицо'
            )

            self.logger.check(
                "Множество физических лиц" in ten,
                f"Физлица упрощены: '{ten}'",
                f"Физлица не упрощены: '{ten}'"
            )

            self.logger.check(
                '"ИЛАР"' in ten or "ИЛАР" in ten,
                f"Юрлицо сохранено: '{ten}'",
                f"Юрлицо потеряно: '{ten}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_22_simplify_rent_individuals_below_threshold(self) -> None:
        """ТЕСТ 22: simplify_rent_individuals - менее 2 физлиц, без изменений"""
        self.logger.section("22. simplify_rent_individuals: ниже порога")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            enc, ten = self.manager.simplify_rent_individuals(
                "Аренда / Сервитут / Аренда",
                'Физическое лицо / ООО "ИЛАР" / ООО "Рога"'
            )

            self.logger.check(
                "Множество физических лиц" not in ten,
                f"Менее 2 физлиц - без упрощения: '{ten}'",
                f"Упрощение ошибочно применено: '{ten}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_23_is_ngs_by_kn(self) -> None:
        """ТЕСТ 23: is_ngs_by_kn - определение НГС по кадастровому номеру"""
        self.logger.section("23. is_ngs_by_kn")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            processor = self.manager.attribute_processor

            # НГС формат (6 цифр)
            result_ngs = processor.is_ngs_by_kn("91:01:012001")
            self.logger.check(
                result_ngs is True,
                "91:01:012001 -> НГС",
                f"91:01:012001 -> не НГС (ошибка)"
            )

            # НГС формат (7 цифр)
            result_ngs7 = processor.is_ngs_by_kn("91:01:0120010")
            self.logger.check(
                result_ngs7 is True,
                "91:01:0120010 -> НГС",
                f"91:01:0120010 -> не НГС (ошибка)"
            )

            # ЗУ формат
            result_zu = processor.is_ngs_by_kn("91:01:012001:15")
            self.logger.check(
                result_zu is False,
                "91:01:012001:15 -> не НГС (ЗУ)",
                "91:01:012001:15 -> НГС (ошибка)"
            )

            # Пустое значение
            result_empty = processor.is_ngs_by_kn(None)
            self.logger.check(
                result_empty is False,
                "None -> False",
                f"None -> {result_empty}"
            )

            # is_zu_by_kn - обратная проверка
            result_zu2 = processor.is_zu_by_kn("91:01:012001:15")
            self.logger.check(
                result_zu2 is True,
                "91:01:012001:15 -> ЗУ",
                f"91:01:012001:15 -> не ЗУ (ошибка)"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    # === Группа 4: FieldCleanup (Msm_13_3) ===

    def test_24_is_field_empty(self) -> None:
        """ТЕСТ 24: is_field_empty - проверка пустого поля в слое"""
        self.logger.section("24. is_field_empty")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            layer = self._create_memory_layer(
                [("Права", "string"), ("Пустое", "string")],
                [
                    {"Права": "Собственность", "Пустое": None},
                    {"Права": "Аренда", "Пустое": ""},
                ]
            )

            if not layer:
                self.logger.fail("Не удалось создать тестовый слой")
                return

            result_rights = self.manager.is_field_empty(layer, "Права")
            self.logger.check(
                result_rights is False,
                "Поле 'Права' не пустое",
                "Поле 'Права' ошибочно определено как пустое"
            )

            result_empty = self.manager.is_field_empty(layer, "Пустое")
            self.logger.check(
                result_empty is True,
                "Поле 'Пустое' пустое",
                "Поле 'Пустое' ошибочно определено как непустое"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_25_get_empty_fields(self) -> None:
        """ТЕСТ 25: get_empty_fields - список пустых полей"""
        self.logger.section("25. get_empty_fields")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            layer = self._create_memory_layer(
                [("Заполненное", "string"), ("Пустое1", "string"), ("Пустое2", "string")],
                [
                    {"Заполненное": "Данные", "Пустое1": None, "Пустое2": ""},
                    {"Заполненное": "Ещё данные", "Пустое1": "", "Пустое2": None},
                ]
            )

            if not layer:
                self.logger.fail("Не удалось создать тестовый слой")
                return

            empty_fields = self.manager.get_empty_fields(layer)
            self.logger.check(
                "Пустое1" in empty_fields and "Пустое2" in empty_fields,
                f"Пустые поля найдены: {empty_fields}",
                f"Пустые поля не определены: {empty_fields}"
            )
            self.logger.check(
                "Заполненное" not in empty_fields,
                "Заполненное поле не в списке пустых",
                f"Заполненное поле ошибочно в списке пустых: {empty_fields}"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_26_remove_empty_fields(self) -> None:
        """ТЕСТ 26: remove_empty_fields - удаление пустых полей"""
        self.logger.section("26. remove_empty_fields")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            layer = self._create_memory_layer(
                [("Данные", "string"), ("Пустое", "string")],
                [
                    {"Данные": "Значение", "Пустое": None},
                    {"Данные": "Значение2", "Пустое": ""},
                ]
            )

            if not layer:
                self.logger.fail("Не удалось создать тестовый слой")
                return

            fields_before = layer.fields().count()
            stats = self.manager.remove_empty_fields(layer)

            self.logger.check(
                stats['removed_count'] > 0,
                f"Удалено полей: {stats['removed_count']}",
                f"Поля не удалены: {stats}"
            )
            self.logger.check(
                'Пустое' in stats['removed_fields'],
                "Пустое поле в списке удаленных",
                f"Пустое поле не в списке удаленных: {stats['removed_fields']}"
            )

            # Проверяем, что оставшееся поле 'Данные' на месте
            remaining_names = [f.name() for f in layer.fields()]
            self.logger.check(
                "Данные" in remaining_names,
                "Поле 'Данные' осталось в слое",
                f"Поле 'Данные' потеряно. Оставшиеся: {remaining_names}"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    # === Группа 5: DataValidator (Msm_13_4) ===

    def test_27_validator_without_metadata_manager(self) -> None:
        """ТЕСТ 27: DataValidator без metadata_manager"""
        self.logger.section("27. DataValidator: без metadata_manager")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            # Без metadata_manager валидация пропускается
            valid, errors = self.manager.validate_metadata({"test": "value"})
            self.logger.check(
                valid is True and len(errors) == 0,
                "Без metadata_manager -> валидация пропущена (OK)",
                f"Неожиданный результат: valid={valid}, errors={errors}"
            )

            # validate_required_fields без metadata_manager
            required_errors = self.manager.validate_required_fields({"test": "value"})
            self.logger.check(
                len(required_errors) == 0,
                "validate_required_fields без metadata_manager -> []",
                f"Неожиданные ошибки: {required_errors}"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    def test_28_validate_attribute_value(self) -> None:
        """ТЕСТ 28: validate_attribute_value"""
        self.logger.section("28. validate_attribute_value")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            # Без схемы -> всегда валидно
            valid, msg = self.manager.validate_attribute_value("test", {})
            self.logger.check(
                valid is True,
                "Без схемы -> валидно",
                f"Без схемы -> невалидно: {msg}"
            )

            # Тип string
            valid2, msg2 = self.manager.validate_attribute_value(123, {"type": "string"})
            self.logger.check(
                valid2 is False,
                f"Число для string -> невалидно: '{msg2}'",
                "Число для string ошибочно валидно"
            )

            # Enum - допустимое значение
            schema = {"type": "enum", "values": "Площадной/Линейный"}
            valid3, msg3 = self.manager.validate_attribute_value("Площадной", schema)
            self.logger.check(
                valid3 is True,
                "Допустимый enum -> валидно",
                f"Допустимый enum -> невалидно: {msg3}"
            )

            # Enum - недопустимое значение
            valid4, msg4 = self.manager.validate_attribute_value("Круглый", schema)
            self.logger.check(
                valid4 is False,
                f"Недопустимый enum -> невалидно: '{msg4}'",
                "Недопустимый enum ошибочно валидно"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    # === Группа 6: AttributeMapper (Msm_13_5) ===

    def test_29_normalize_field_value(self) -> None:
        """ТЕСТ 29: normalize_field_value - нормализация значения поля"""
        self.logger.section("29. normalize_field_value")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            # None для обычного поля -> "-"
            result = self.manager.normalize_field_value(None, "ОбычноеПоле")
            self.logger.check(
                result == "-",
                f"None -> '{result}'",
                f"Ожидалось '-', получено '{result}'"
            )

            # None для специального поля "Права" -> "Сведения отсутствуют"
            result2 = self.manager.normalize_field_value(None, "Права")
            self.logger.check(
                result2 == "Сведения отсутствуют",
                f"None для Права -> '{result2}'",
                f"Ожидалось 'Сведения отсутствуют', получено '{result2}'"
            )

            # Замена ";" на " / "
            result3 = self.manager.normalize_field_value("Аренда;Сервитут", "Обременения")
            self.logger.check(
                " / " in result3 and ";" not in result3,
                f"Разделители нормализованы: '{result3}'",
                f"Разделители не нормализованы: '{result3}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")

    # === Группа 7: End-to-end ===

    def test_30_finalize_layer_e2e(self) -> None:
        """ТЕСТ 30: finalize_layer - end-to-end обработка слоя"""
        self.logger.section("30. finalize_layer: end-to-end")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            layer = self._create_memory_layer(
                [
                    ("Права", "string"),
                    ("Собственники", "string"),
                    ("ВРИ", "string"),
                    ("Категория", "string"),
                ],
                [
                    {
                        "Права": None,
                        "Собственники": "",
                        "ВРИ": "хранение автотранспорта",
                        "Категория": None,
                    },
                ]
            )

            if not layer:
                self.logger.fail("Не удалось создать тестовый слой")
                return

            # Запуск finalize_layer
            self.manager.finalize_layer(layer, "L_2_1_1_Земельные_участки")

            # Проверяем результаты
            feature = next(layer.getFeatures())

            # Права: None -> "Сведения отсутствуют"
            rights_val = feature["Права"]
            self.logger.check(
                rights_val is not None and str(rights_val) != "" and str(rights_val) != "NULL",
                f"Права заполнены: '{rights_val}'",
                f"Права остались пустыми: '{rights_val}'"
            )

            # Собственники: "" -> "Сведения отсутствуют"
            owners_val = feature["Собственники"]
            self.logger.check(
                owners_val is not None and str(owners_val) != "",
                f"Собственники заполнены: '{owners_val}'",
                f"Собственники остались пустыми: '{owners_val}'"
            )

            # ВРИ: "хранение..." -> "Хранение..." (капитализация)
            vri_val = str(feature["ВРИ"]) if feature["ВРИ"] else ""
            self.logger.check(
                vri_val.startswith("Х"),
                f"ВРИ капитализирован: '{vri_val}'",
                f"ВРИ не капитализирован: '{vri_val}'"
            )

            # Категория: None -> "Категория не установлена"
            cat_val = feature["Категория"]
            self.logger.check(
                cat_val is not None and str(cat_val) != "-",
                f"Категория заполнена: '{cat_val}'",
                f"Категория не заполнена правильно: '{cat_val}'"
            )

        except Exception as e:
            self.logger.fail(f"Ошибка теста finalize_layer: {e}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_31_get_statistics(self) -> None:
        """ТЕСТ 31: get_statistics - статистика менеджера"""
        self.logger.section("31. get_statistics")

        if not self.manager:
            self.logger.fail("Manager не инициализирован")
            return

        try:
            stats = self.manager.get_statistics()

            self.logger.check(
                isinstance(stats, dict),
                f"Статистика возвращена: {stats}",
                f"Статистика не является dict: {type(stats)}"
            )

            expected_keys = [
                'string_sanitizer', 'attribute_processor',
                'field_cleanup', 'data_validator', 'attribute_mapper'
            ]
            for key in expected_keys:
                self.logger.check(
                    key in stats,
                    f"Ключ '{key}' в статистике: {stats[key]}",
                    f"Ключ '{key}' отсутствует в статистике"
                )

        except Exception as e:
            self.logger.fail(f"Ошибка теста: {e}")
