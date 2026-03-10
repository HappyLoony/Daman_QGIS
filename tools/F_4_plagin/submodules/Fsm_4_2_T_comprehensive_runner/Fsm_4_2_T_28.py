# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_28 - Тесты для M_28 LayerSchemaValidator + Msm_28_1

Тестирует:
- Инициализацию валидатора
- Схемы ZPR и FOREST_VYDELY
- Определение схемы по имени слоя
- Получение обязательных полей (статических и динамических)
- Msm_28_1 ForestVydelySchemaProvider: парсинг mapinfo_format
- ensure_required_fields: добавление полей с типами
- validate_layer: проверка структуры
"""

from qgis.core import QgsVectorLayer, QgsField, QgsFields
from qgis.PyQt.QtCore import QMetaType


class TestM28:
    """Тесты для M_28_LayerSchemaValidator + Msm_28_1"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.validator = None

    def run_all_tests(self):
        """Запуск всех тестов M_28"""
        self.logger.section("ТЕСТ M_28: LayerSchemaValidator")

        try:
            # Инициализация
            self.test_01_init()
            self.test_02_schemas_exist()

            # ZPR schema
            self.test_03_zpr_schema_layers()
            self.test_04_zpr_required_fields()

            # FOREST_VYDELY schema
            self.test_05_forest_vydely_schema_exists()
            self.test_06_forest_vydely_layers()
            self.test_07_forest_vydely_dynamic_fields()

            # Schema detection
            self.test_08_get_schema_for_zpr_layer()
            self.test_09_get_schema_for_forest_layer()
            self.test_10_get_schema_for_unknown()

            # Msm_28_1 ForestVydelySchemaProvider
            self.test_11_forest_provider_init()
            self.test_12_forest_provider_field_count()
            self.test_13_forest_provider_field_names()
            self.test_14_forest_provider_field_types()
            self.test_15_parse_mapinfo_format()

            # validate_layer with memory layers
            self.test_16_validate_complete_zpr_layer()
            self.test_17_validate_incomplete_zpr_layer()

            # ensure_required_fields with memory layers
            self.test_18_ensure_zpr_fields()
            self.test_19_ensure_forest_vydely_fields()
            self.test_20_ensure_forest_vydely_typed_fields()

            # Частичный импорт (имитация TAB)
            self.test_21_ensure_partial_forest_vydely()

            # Edge cases
            self.test_22_validate_none_layer()
            self.test_23_unknown_schema()

        except Exception as e:
            self.logger.error(f"Критическая ошибка: {e}")

        self.logger.summary()

    # --- Инициализация ---

    def test_01_init(self):
        """ТЕСТ 1: Инициализация валидатора"""
        self.logger.section("1. Инициализация LayerSchemaValidator")
        try:
            from Daman_QGIS.managers import LayerSchemaValidator
            self.validator = LayerSchemaValidator()
            self.logger.check(
                self.validator is not None,
                "LayerSchemaValidator создан",
                "LayerSchemaValidator не создан!"
            )
        except Exception as e:
            self.logger.error(f"Ошибка создания: {e}")

    def test_02_schemas_exist(self):
        """ТЕСТ 2: Проверка наличия схем"""
        self.logger.section("2. Наличие схем в LAYER_SCHEMAS")
        if not self.validator:
            self.logger.skip("Валидатор не инициализирован")
            return

        schemas = self.validator.LAYER_SCHEMAS
        self.logger.check(
            'ZPR' in schemas,
            "Схема ZPR присутствует",
            "Схема ZPR отсутствует!"
        )
        self.logger.check(
            'FOREST_VYDELY' in schemas,
            "Схема FOREST_VYDELY присутствует",
            "Схема FOREST_VYDELY отсутствует!"
        )

    # --- ZPR ---

    def test_03_zpr_schema_layers(self):
        """ТЕСТ 3: Слои схемы ZPR"""
        self.logger.section("3. Слои схемы ZPR")
        if not self.validator:
            self.logger.skip("Валидатор не инициализирован")
            return

        schema = self.validator.LAYER_SCHEMAS.get('ZPR', {})
        layers = schema.get('layers', [])

        self.logger.check(
            len(layers) == 7,
            f"ZPR: 7 слоёв ({len(layers)})",
            f"ZPR: ожидалось 7 слоёв, получено {len(layers)}"
        )

        expected = ['L_1_12_1_ЗПР_ОКС', 'L_1_12_2_ЗПР_ПО', 'L_1_12_3_ЗПР_ВО']
        for name in expected:
            self.logger.check(
                name in layers,
                f"Слой {name} в ZPR",
                f"Слой {name} отсутствует в ZPR!"
            )

    def test_04_zpr_required_fields(self):
        """ТЕСТ 4: Обязательные поля ZPR"""
        self.logger.section("4. Обязательные поля ZPR")
        if not self.validator:
            self.logger.skip("Валидатор не инициализирован")
            return

        fields = self.validator.get_required_fields('ZPR')
        expected = ['ID', 'ID_KV', 'VRI', 'MIN_AREA_VRI']

        self.logger.check(
            len(fields) == 4,
            f"ZPR: 4 обязательных поля",
            f"ZPR: ожидалось 4, получено {len(fields)}"
        )

        for name in expected:
            self.logger.check(
                name in fields,
                f"Поле {name} в ZPR",
                f"Поле {name} отсутствует в ZPR!"
            )

    # --- FOREST_VYDELY ---

    def test_05_forest_vydely_schema_exists(self):
        """ТЕСТ 5: Схема FOREST_VYDELY существует"""
        self.logger.section("5. Схема FOREST_VYDELY")
        if not self.validator:
            self.logger.skip("Валидатор не инициализирован")
            return

        schema = self.validator.LAYER_SCHEMAS.get('FOREST_VYDELY')
        self.logger.check(
            schema is not None,
            "Схема FOREST_VYDELY существует",
            "Схема FOREST_VYDELY не найдена!"
        )
        self.logger.check(
            schema.get('dynamic_provider') == 'forest_vydely',
            "dynamic_provider = 'forest_vydely'",
            f"dynamic_provider = '{schema.get('dynamic_provider')}'!"
        )

    def test_06_forest_vydely_layers(self):
        """ТЕСТ 6: Слои FOREST_VYDELY"""
        self.logger.section("6. Слои FOREST_VYDELY")
        if not self.validator:
            self.logger.skip("Валидатор не инициализирован")
            return

        schema = self.validator.LAYER_SCHEMAS.get('FOREST_VYDELY', {})
        layers = schema.get('layers', [])

        self.logger.check(
            'Le_3_1_1_1_Лес_Ред_Выделы' in layers,
            "Le_3_1_1_1_Лес_Ред_Выделы в FOREST_VYDELY",
            "Le_3_1_1_1_Лес_Ред_Выделы отсутствует!"
        )

    def test_07_forest_vydely_dynamic_fields(self):
        """ТЕСТ 7: Динамические поля FOREST_VYDELY через get_required_fields"""
        self.logger.section("7. Динамические поля FOREST_VYDELY")
        if not self.validator:
            self.logger.skip("Валидатор не инициализирован")
            return

        fields = self.validator.get_required_fields('FOREST_VYDELY')

        self.logger.check(
            len(fields) == 17,
            f"FOREST_VYDELY: 17 обязательных полей",
            f"FOREST_VYDELY: ожидалось 17, получено {len(fields)}"
        )

        # Проверяем ключевые поля
        expected_names = ['Лесничество', 'Номер_квартала', 'Номер_выдела', 'Состав', 'Возраст']
        for name in expected_names:
            self.logger.check(
                name in fields,
                f"Поле {name} в FOREST_VYDELY",
                f"Поле {name} отсутствует!"
            )

    # --- Schema detection ---

    def test_08_get_schema_for_zpr_layer(self):
        """ТЕСТ 8: Определение схемы для слоя ZPR"""
        self.logger.section("8. Определение схемы ZPR")
        if not self.validator:
            self.logger.skip("Валидатор не инициализирован")
            return

        schema = self.validator._get_schema_for_layer('L_1_12_1_ЗПР_ОКС')
        self.logger.check(
            schema == 'ZPR',
            "L_1_12_1_ЗПР_ОКС -> ZPR",
            f"L_1_12_1_ЗПР_ОКС -> '{schema}'!"
        )

    def test_09_get_schema_for_forest_layer(self):
        """ТЕСТ 9: Определение схемы для лесного слоя"""
        self.logger.section("9. Определение схемы FOREST_VYDELY")
        if not self.validator:
            self.logger.skip("Валидатор не инициализирован")
            return

        schema = self.validator._get_schema_for_layer('Le_3_1_1_1_Лес_Ред_Выделы')
        self.logger.check(
            schema == 'FOREST_VYDELY',
            "Le_3_1_1_1_Лес_Ред_Выделы -> FOREST_VYDELY",
            f"Le_3_1_1_1_Лес_Ред_Выделы -> '{schema}'!"
        )

    def test_10_get_schema_for_unknown(self):
        """ТЕСТ 10: Неизвестный слой -> None"""
        self.logger.section("10. Неизвестный слой")
        if not self.validator:
            self.logger.skip("Валидатор не инициализирован")
            return

        schema = self.validator._get_schema_for_layer('L_1_1_1_Границы_работ')
        self.logger.check(
            schema is None,
            "Неизвестный слой -> None",
            f"Неизвестный слой -> '{schema}'!"
        )

    # --- Msm_28_1 ForestVydelySchemaProvider ---

    def test_11_forest_provider_init(self):
        """ТЕСТ 11: Инициализация ForestVydelySchemaProvider"""
        self.logger.section("11. ForestVydelySchemaProvider")
        try:
            from Daman_QGIS.managers.validation.submodules.Msm_28_1_forest_vydely_schema import (
                ForestVydelySchemaProvider,
            )
            provider = ForestVydelySchemaProvider()
            self.logger.check(
                provider is not None,
                "ForestVydelySchemaProvider создан",
                "ForestVydelySchemaProvider не создан!"
            )
        except Exception as e:
            self.logger.error(f"Ошибка импорта: {e}")

    def test_12_forest_provider_field_count(self):
        """ТЕСТ 12: Количество полей из провайдера"""
        self.logger.section("12. Количество полей провайдера")
        try:
            from Daman_QGIS.managers.validation.submodules.Msm_28_1_forest_vydely_schema import (
                ForestVydelySchemaProvider,
            )
            provider = ForestVydelySchemaProvider()
            fields = provider.get_required_fields()

            self.logger.check(
                len(fields) == 17,
                f"17 полей загружено",
                f"Ожидалось 17, получено {len(fields)}"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_13_forest_provider_field_names(self):
        """ТЕСТ 13: Имена полей из провайдера"""
        self.logger.section("13. Имена полей провайдера")
        try:
            from Daman_QGIS.managers.validation.submodules.Msm_28_1_forest_vydely_schema import (
                ForestVydelySchemaProvider,
            )
            provider = ForestVydelySchemaProvider()
            names = provider.get_field_names()

            self.logger.check(
                len(names) == 17,
                f"17 имён полей",
                f"Ожидалось 17, получено {len(names)}"
            )

            # Первое и последнее поле
            self.logger.check(
                names[0] == 'Лесничество',
                "Первое поле: Лесничество",
                f"Первое поле: '{names[0]}'!"
            )
            self.logger.check(
                names[-1] == 'Распределение_земель',
                "Последнее поле: Распределение_земель",
                f"Последнее поле: '{names[-1]}'!"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_14_forest_provider_field_types(self):
        """ТЕСТ 14: Типы полей из провайдера"""
        self.logger.section("14. Типы полей провайдера")
        try:
            from Daman_QGIS.managers.validation.submodules.Msm_28_1_forest_vydely_schema import (
                ForestVydelySchemaProvider,
            )
            provider = ForestVydelySchemaProvider()
            fields = provider.get_required_fields()

            # Создаём словарь для быстрого доступа
            field_dict = {f["name"]: f for f in fields}

            # Целые поля (согласно Base_forest_vydely.json)
            int_fields = ['Номер_квартала', 'Номер_выдела', 'Возраст', 'Группа_возраста', 'Запас_на_1_га']
            for int_field in int_fields:
                f = field_dict.get(int_field)
                self.logger.check(
                    f is not None and f["type"] == QMetaType.Type.Int,
                    f"{int_field}: тип Int",
                    f"{int_field}: тип {f['type'] if f else 'NOT FOUND'}!"
                )

            # Символьные поля QString(254)
            str_fields = ['Лесничество', 'Бонитет', 'Полнота', 'Преобладающая_порода', 'Распределение_земель']
            for str_field in str_fields:
                f = field_dict.get(str_field)
                self.logger.check(
                    f is not None and f["type"] == QMetaType.Type.QString and f["length"] == 254,
                    f"{str_field}: QString(254)",
                    f"{str_field}: тип/длина не совпадает (type={f.get('type') if f else '?'}, len={f.get('length') if f else '?'})!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_15_parse_mapinfo_format(self):
        """ТЕСТ 15: Парсинг mapinfo_format"""
        self.logger.section("15. Парсинг mapinfo_format")
        try:
            from Daman_QGIS.managers.validation.submodules.Msm_28_1_forest_vydely_schema import (
                ForestVydelySchemaProvider,
            )

            test_cases = [
                ("(Целое)", QMetaType.Type.Int, 0),
                ("(Символьное, ограничение по символам 254)", QMetaType.Type.QString, 254),
                ("(Символьное, ограничение по символам 50)", QMetaType.Type.QString, 50),
                ("(Символьное, ограничение по символам 10)", QMetaType.Type.QString, 10),
                ("(Символьное, ограничение по символам 100)", QMetaType.Type.QString, 100),
                ("", QMetaType.Type.QString, 254),  # default
            ]

            for fmt, expected_type, expected_len in test_cases:
                result_type, result_len = ForestVydelySchemaProvider._parse_mapinfo_format(fmt)
                self.logger.check(
                    result_type == expected_type and result_len == expected_len,
                    f"'{fmt}' -> ({result_type}, {result_len})",
                    f"'{fmt}': ожидалось ({expected_type}, {expected_len}), получено ({result_type}, {result_len})!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- validate_layer с memory layers ---

    def test_16_validate_complete_zpr_layer(self):
        """ТЕСТ 16: Валидация полного слоя ZPR"""
        self.logger.section("16. Валидация полного ZPR слоя")
        if not self.validator:
            self.logger.skip("Валидатор не инициализирован")
            return

        try:
            # Создаём memory layer с всеми полями ZPR
            layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "L_1_12_1_ЗПР_ОКС", "memory")
            dp = layer.dataProvider()
            dp.addAttributes([
                QgsField("ID", QMetaType.Type.QString, len=254),
                QgsField("ID_KV", QMetaType.Type.QString, len=254),
                QgsField("VRI", QMetaType.Type.QString, len=254),
                QgsField("MIN_AREA_VRI", QMetaType.Type.QString, len=254),
            ])
            layer.updateFields()

            result = self.validator.validate_layer(layer, 'ZPR')

            self.logger.check(
                result['valid'] is True,
                "Полный ZPR слой валиден",
                f"Полный ZPR слой невалиден: missing={result.get('missing_fields')}"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_17_validate_incomplete_zpr_layer(self):
        """ТЕСТ 17: Валидация неполного слоя ZPR"""
        self.logger.section("17. Валидация неполного ZPR слоя")
        if not self.validator:
            self.logger.skip("Валидатор не инициализирован")
            return

        try:
            # Создаём memory layer с частью полей ZPR
            layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "L_1_12_1_ЗПР_ОКС", "memory")
            dp = layer.dataProvider()
            dp.addAttributes([
                QgsField("ID", QMetaType.Type.QString, len=254),
                # Отсутствуют: ID_KV, VRI, MIN_AREA_VRI
            ])
            layer.updateFields()

            result = self.validator.validate_layer(layer, 'ZPR')

            self.logger.check(
                result['valid'] is False,
                "Неполный ZPR слой невалиден",
                "Неполный ZPR слой ошибочно валиден!"
            )
            self.logger.check(
                len(result['missing_fields']) == 3,
                f"3 отсутствующих поля: {result['missing_fields']}",
                f"Ожидалось 3, получено {len(result['missing_fields'])}"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- ensure_required_fields ---

    def test_18_ensure_zpr_fields(self):
        """ТЕСТ 18: Добавление недостающих полей ZPR"""
        self.logger.section("18. ensure_required_fields ZPR")
        if not self.validator:
            self.logger.skip("Валидатор не инициализирован")
            return

        try:
            layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "L_1_12_1_ЗПР_ОКС", "memory")
            dp = layer.dataProvider()
            dp.addAttributes([
                QgsField("ID", QMetaType.Type.QString, len=254),
            ])
            layer.updateFields()

            result = self.validator.ensure_required_fields(layer, 'ZPR')

            self.logger.check(
                result['success'] is True,
                "ensure_required_fields ZPR: success",
                f"ensure_required_fields ZPR: error={result.get('error')}"
            )
            self.logger.check(
                len(result['fields_added']) == 3,
                f"Добавлено 3 поля: {result['fields_added']}",
                f"Ожидалось 3, добавлено {len(result['fields_added'])}"
            )

            # Проверяем, что поля реально добавлены
            field_names = [f.name() for f in layer.fields()]
            for name in ['ID', 'ID_KV', 'VRI', 'MIN_AREA_VRI']:
                self.logger.check(
                    name in field_names,
                    f"Поле {name} существует после ensure",
                    f"Поле {name} отсутствует после ensure!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_19_ensure_forest_vydely_fields(self):
        """ТЕСТ 19: Добавление недостающих полей FOREST_VYDELY"""
        self.logger.section("19. ensure_required_fields FOREST_VYDELY")
        if not self.validator:
            self.logger.skip("Валидатор не инициализирован")
            return

        try:
            # Пустой слой - все 17 полей должны быть добавлены
            layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "Le_3_1_1_1_Лес_Ред_Выделы", "memory")

            result = self.validator.ensure_required_fields(layer, 'FOREST_VYDELY')

            self.logger.check(
                result['success'] is True,
                "ensure_required_fields FOREST_VYDELY: success",
                f"ensure_required_fields FOREST_VYDELY: error={result.get('error')}"
            )
            self.logger.check(
                len(result['fields_added']) == 17,
                f"Добавлено 17 полей",
                f"Ожидалось 17, добавлено {len(result['fields_added'])}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_20_ensure_forest_vydely_typed_fields(self):
        """ТЕСТ 20: Проверка типов добавленных полей FOREST_VYDELY"""
        self.logger.section("20. Типы полей после ensure FOREST_VYDELY")
        if not self.validator:
            self.logger.skip("Валидатор не инициализирован")
            return

        try:
            layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "Le_3_1_1_1_Лес_Ред_Выделы", "memory")
            self.validator.ensure_required_fields(layer, 'FOREST_VYDELY')

            fields = layer.fields()
            field_map = {f.name(): f for f in fields}

            # Целые поля
            for int_name in ['Номер_квартала', 'Номер_выдела']:
                f = field_map.get(int_name)
                self.logger.check(
                    f is not None and f.type() == QMetaType.Type.Int,
                    f"{int_name}: тип Int в слое",
                    f"{int_name}: тип {f.type() if f else 'NOT FOUND'}!"
                )

            # Символьные поля
            f_les = field_map.get('Лесничество')
            self.logger.check(
                f_les is not None and f_les.type() == QMetaType.Type.QString,
                "Лесничество: тип QString в слое",
                f"Лесничество: тип {f_les.type() if f_les else 'NOT FOUND'}!"
            )

            # Существующие поля не удалены
            self.logger.check(
                'Лесничество' in field_map and 'Распределение_земель' in field_map,
                "Все 17 полей присутствуют",
                "Не все поля присутствуют!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_21_ensure_partial_forest_vydely(self):
        """ТЕСТ 21: Дополнение частично заполненного слоя (имитация импорта TAB)"""
        self.logger.section("21. ensure_required_fields для частичного слоя")
        if not self.validator:
            self.logger.skip("Валидатор не инициализирован")
            return

        try:
            # Имитация TAB файла с 5 полями из 17
            layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "Le_3_1_1_1_Лес_Ред_Выделы", "memory")
            dp = layer.dataProvider()
            dp.addAttributes([
                QgsField("Лесничество", QMetaType.Type.QString, len=254),
                QgsField("Уч_лесничество", QMetaType.Type.QString, len=254),
                QgsField("Номер_квартала", QMetaType.Type.Int),
                QgsField("Номер_выдела", QMetaType.Type.Int),
                QgsField("Состав", QMetaType.Type.QString, len=254),
            ])
            layer.updateFields()

            fields_before = [f.name() for f in layer.fields()]
            result = self.validator.ensure_required_fields(layer, 'FOREST_VYDELY')
            fields_after = [f.name() for f in layer.fields()]

            self.logger.check(
                result['success'] is True,
                "Частичный слой: success",
                f"Частичный слой: error={result.get('error')}"
            )

            # Должно быть добавлено 12 полей (17 - 5 существующих)
            self.logger.check(
                len(result['fields_added']) == 12,
                f"Добавлено 12 недостающих полей",
                f"Ожидалось 12, добавлено {len(result['fields_added'])}: {result['fields_added']}"
            )

            # Итого 17 полей
            self.logger.check(
                len(fields_after) == 17,
                f"Итого 17 полей в слое",
                f"Итого {len(fields_after)} полей!"
            )

            # Существующие поля НЕ дублированы
            field_names = [f.name() for f in layer.fields()]
            for name in fields_before:
                count = field_names.count(name)
                self.logger.check(
                    count == 1,
                    f"Поле '{name}' не дублировано",
                    f"Поле '{name}' встречается {count} раз!"
                )

            # Проверяем типы добавленных целых полей
            field_map = {f.name(): f for f in layer.fields()}
            for int_name in ['Возраст', 'Группа_возраста', 'Запас_на_1_га']:
                f = field_map.get(int_name)
                self.logger.check(
                    f is not None and f.type() == QMetaType.Type.Int,
                    f"Добавленное поле {int_name}: Int",
                    f"Добавленное поле {int_name}: {f.type() if f else 'NOT FOUND'}!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- Edge cases ---

    def test_22_validate_none_layer(self):
        """ТЕСТ 22: Валидация None слоя"""
        self.logger.section("22. Валидация None слоя")
        if not self.validator:
            self.logger.skip("Валидатор не инициализирован")
            return

        try:
            result = self.validator.validate_layer(None, 'ZPR')
            self.logger.check(
                result['valid'] is False,
                "None слой невалиден",
                "None слой ошибочно валиден!"
            )
            self.logger.check(
                result['error'] is not None,
                f"Ошибка описана: {result['error']}",
                "Ошибка не описана!"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_23_unknown_schema(self):
        """ТЕСТ 23: Неизвестная схема"""
        self.logger.section("23. Неизвестная схема")
        if not self.validator:
            self.logger.skip("Валидатор не инициализирован")
            return

        try:
            fields = self.validator.get_required_fields('NONEXISTENT')
            self.logger.check(
                len(fields) == 0,
                "Неизвестная схема: пустой список полей",
                f"Неизвестная схема: {len(fields)} полей!"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")


def run_tests(iface, logger):
    """Точка входа для запуска тестов"""
    test = TestM28(iface, logger)
    test.run_all_tests()
    return test
