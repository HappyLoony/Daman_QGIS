# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_22 - Тесты для M_22 WorkTypeAssignmentManager

Тестирует:
- Инициализацию менеджера
- Перечисления LayerType и StageType
- _get_work_type_value: логику формирования Вид_Работ
- assign_work_type_basic: базовая нарезка
- assign_work_type_stage2: объединение с номерами контуров
- update_sostav_separator: замена ";" на ", "
- get_all_work_types: загрузка базы Work_types
"""


class TestM22:
    """Тесты для M_22_WorkTypeAssignmentManager"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.manager = None

    def run_all_tests(self):
        """Запуск всех тестов M_22"""
        self.logger.section("ТЕСТ M_22: WorkTypeAssignmentManager")

        try:
            # Инициализация
            self.test_01_init()
            self.test_02_layer_type_enum()
            self.test_03_stage_type_enum()

            # _get_work_type_value
            self.test_04_work_type_razdel()
            self.test_05_work_type_ngs()
            self.test_06_work_type_bez_mej()
            self.test_07_work_type_ps()
            self.test_08_work_type_stage2()

            # assign_work_type_basic
            self.test_09_assign_basic_razdel()
            self.test_10_assign_basic_ngs()
            self.test_11_assign_basic_empty()

            # update_sostav_separator
            self.test_12_update_separator()
            self.test_13_update_separator_no_change()

            # get_all_work_types
            self.test_14_get_all_work_types()

            # get_work_type_record_for_vedomost
            self.test_15_vedomost_record()

        except Exception as e:
            self.logger.error(f"Критическая ошибка: {e}")

        self.logger.summary()

    # --- Инициализация ---

    def test_01_init(self):
        """ТЕСТ 1: Инициализация менеджера"""
        self.logger.section("1. Инициализация WorkTypeAssignmentManager")
        try:
            from Daman_QGIS.managers import WorkTypeAssignmentManager
            self.manager = WorkTypeAssignmentManager()

            self.logger.check(
                self.manager is not None,
                "WorkTypeAssignmentManager создан",
                "WorkTypeAssignmentManager не создан!"
            )

            methods = ['assign_work_type_basic', 'assign_work_type_stage1',
                        'assign_work_type_stage2', 'update_sostav_separator',
                        'get_all_work_types', 'get_work_type_record_for_vedomost']
            for method in methods:
                self.logger.check(
                    hasattr(self.manager, method),
                    f"Метод {method}() существует",
                    f"Метод {method}() отсутствует!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_02_layer_type_enum(self):
        """ТЕСТ 2: Перечисление LayerType"""
        self.logger.section("2. LayerType enum")
        try:
            from Daman_QGIS.managers.validation.M_22_work_type_assignment_manager import LayerType

            expected_members = ['RAZDEL', 'NGS', 'BEZ_MEJ', 'PS']
            for member in expected_members:
                self.logger.check(
                    hasattr(LayerType, member),
                    f"LayerType.{member} существует",
                    f"LayerType.{member} отсутствует!"
                )

            self.logger.check(
                LayerType.RAZDEL.value == "razdel",
                "RAZDEL.value = 'razdel'",
                f"RAZDEL.value = '{LayerType.RAZDEL.value}'!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_03_stage_type_enum(self):
        """ТЕСТ 3: Перечисление StageType"""
        self.logger.section("3. StageType enum")
        try:
            from Daman_QGIS.managers.validation.M_22_work_type_assignment_manager import StageType

            expected_members = ['STAGE_1', 'STAGE_2', 'FINAL']
            for member in expected_members:
                self.logger.check(
                    hasattr(StageType, member),
                    f"StageType.{member} существует",
                    f"StageType.{member} отсутствует!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- _get_work_type_value ---

    def test_04_work_type_razdel(self):
        """ТЕСТ 4: Вид_Работ для RAZDEL"""
        self.logger.section("4. Вид_Работ: RAZDEL")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return
        try:
            from Daman_QGIS.managers.validation.M_22_work_type_assignment_manager import LayerType

            result = self.manager._get_work_type_value(LayerType.RAZDEL)
            self.logger.check(
                "раздел" in result.lower(),
                f"RAZDEL: содержит 'раздел'",
                f"RAZDEL: '{result}' не содержит 'раздел'!"
            )
            self.logger.check(
                result == "Образование земельного участка путем раздела",
                "RAZDEL: точное соответствие",
                f"RAZDEL: '{result}'!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_05_work_type_ngs(self):
        """ТЕСТ 5: Вид_Работ для NGS"""
        self.logger.section("5. Вид_Работ: NGS")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return
        try:
            from Daman_QGIS.managers.validation.M_22_work_type_assignment_manager import LayerType

            result = self.manager._get_work_type_value(LayerType.NGS)
            self.logger.check(
                "государственной" in result.lower(),
                f"NGS: содержит 'государственной'",
                f"NGS: '{result[:50]}...' не содержит 'государственной'!"
            )
            self.logger.check(
                "муниципальной" in result.lower(),
                "NGS: содержит 'муниципальной'",
                f"NGS: не содержит 'муниципальной'!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_06_work_type_bez_mej(self):
        """ТЕСТ 6: Вид_Работ для BEZ_MEJ"""
        self.logger.section("6. Вид_Работ: BEZ_MEJ")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return
        try:
            from Daman_QGIS.managers.validation.M_22_work_type_assignment_manager import LayerType

            result = self.manager._get_work_type_value(LayerType.BEZ_MEJ)
            self.logger.check(
                result == "-",
                "BEZ_MEJ: '-' (заглушка)",
                f"BEZ_MEJ: '{result}'!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_07_work_type_ps(self):
        """ТЕСТ 7: Вид_Работ для PS"""
        self.logger.section("7. Вид_Работ: PS")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return
        try:
            from Daman_QGIS.managers.validation.M_22_work_type_assignment_manager import LayerType

            result = self.manager._get_work_type_value(LayerType.PS)
            self.logger.check(
                result == "-",
                "PS: '-' (заглушка)",
                f"PS: '{result}'!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_08_work_type_stage2(self):
        """ТЕСТ 8: Вид_Работ для этапа 2 (объединение)"""
        self.logger.section("8. Вид_Работ: этап 2 (объединение)")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return
        try:
            from Daman_QGIS.managers.validation.M_22_work_type_assignment_manager import (
                LayerType, StageType,
            )

            result = self.manager._get_work_type_value(
                LayerType.RAZDEL,
                stage_type=StageType.STAGE_2,
                merged_ids=[100, 101, 102]
            )
            self.logger.check(
                "объединения" in result.lower(),
                "Stage 2: содержит 'объединения'",
                f"Stage 2: '{result[:50]}...' не содержит 'объединения'!"
            )
            self.logger.check(
                "100, 101, 102" in result,
                "Stage 2: содержит номера '100, 101, 102'",
                f"Stage 2: не содержит номера!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- assign_work_type_basic ---

    def test_09_assign_basic_razdel(self):
        """ТЕСТ 9: assign_work_type_basic для RAZDEL"""
        self.logger.section("9. assign_work_type_basic: RAZDEL")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return
        try:
            from Daman_QGIS.managers.validation.M_22_work_type_assignment_manager import LayerType

            features = [
                {'attributes': {'ID': '1', 'ВРИ': 'Жилая застройка'}},
                {'attributes': {'ID': '2', 'ВРИ': 'Промышленность'}},
            ]

            result = self.manager.assign_work_type_basic(features, LayerType.RAZDEL)

            self.logger.check(
                len(result) == 2,
                "2 features обработаны",
                f"Ожидалось 2, получено {len(result)}"
            )

            # Оба должны иметь Вид_Работ
            all_have = all('Вид_Работ' in f['attributes'] for f in result)
            self.logger.check(
                all_have,
                "Все features имеют Вид_Работ",
                "Не все features имеют Вид_Работ!"
            )

            # RAZDEL -> "...путем раздела"
            self.logger.check(
                "раздел" in result[0]['attributes']['Вид_Работ'].lower(),
                "Вид_Работ содержит 'раздел'",
                f"Вид_Работ: '{result[0]['attributes']['Вид_Работ'][:40]}...'!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_10_assign_basic_ngs(self):
        """ТЕСТ 10: assign_work_type_basic для NGS"""
        self.logger.section("10. assign_work_type_basic: NGS")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return
        try:
            from Daman_QGIS.managers.validation.M_22_work_type_assignment_manager import LayerType

            features = [{'attributes': {'ID': '1'}}]
            result = self.manager.assign_work_type_basic(features, LayerType.NGS)

            self.logger.check(
                "государственной" in result[0]['attributes'].get('Вид_Работ', '').lower(),
                "NGS: Вид_Работ содержит 'государственной'",
                f"NGS: Вид_Работ = '{result[0]['attributes'].get('Вид_Работ', 'NOT SET')[:50]}...'!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_11_assign_basic_empty(self):
        """ТЕСТ 11: assign_work_type_basic с пустым входом"""
        self.logger.section("11. assign_work_type_basic: пустой вход")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return
        try:
            from Daman_QGIS.managers.validation.M_22_work_type_assignment_manager import LayerType

            result = self.manager.assign_work_type_basic([], LayerType.RAZDEL)
            self.logger.check(
                result == [],
                "Пустой вход -> пустой результат",
                f"Пустой вход -> {result}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- update_sostav_separator ---

    def test_12_update_separator(self):
        """ТЕСТ 12: Замена ";" на ", " в Состав_контуров"""
        self.logger.section("12. update_sostav_separator")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return
        try:
            features = [
                {'attributes': {'Состав_контуров': '100;101;102'}},
                {'attributes': {'Состав_контуров': '200;201'}},
            ]
            result = self.manager.update_sostav_separator(features)

            self.logger.check(
                result[0]['attributes']['Состав_контуров'] == '100, 101, 102',
                "100;101;102 -> 100, 101, 102",
                f"Результат: '{result[0]['attributes']['Состав_контуров']}'!"
            )
            self.logger.check(
                result[1]['attributes']['Состав_контуров'] == '200, 201',
                "200;201 -> 200, 201",
                f"Результат: '{result[1]['attributes']['Состав_контуров']}'!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_13_update_separator_no_change(self):
        """ТЕСТ 13: Состав_контуров без ";" не изменяется"""
        self.logger.section("13. update_sostav_separator: без изменений")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return
        try:
            features = [
                {'attributes': {'Состав_контуров': '100, 101'}},
                {'attributes': {'Состав_контуров': ''}},
                {'attributes': {}},
            ]
            result = self.manager.update_sostav_separator(features)

            self.logger.check(
                result[0]['attributes']['Состав_контуров'] == '100, 101',
                "Уже с запятой: не изменено",
                f"Результат: '{result[0]['attributes']['Состав_контуров']}'!"
            )
            self.logger.check(
                result[1]['attributes']['Состав_контуров'] == '',
                "Пустая строка: не изменена",
                f"Результат: '{result[1]['attributes']['Состав_контуров']}'!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- get_all_work_types ---

    def test_14_get_all_work_types(self):
        """ТЕСТ 14: Загрузка базы Work_types"""
        self.logger.section("14. get_all_work_types")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return
        try:
            work_types = self.manager.get_all_work_types()

            self.logger.check(
                isinstance(work_types, list),
                "get_all_work_types() -> list",
                f"get_all_work_types() -> {type(work_types)}"
            )
            self.logger.check(
                len(work_types) > 0,
                f"Загружено {len(work_types)} записей",
                "Записи не загружены!"
            )

            # Проверяем структуру записей
            if work_types:
                first = work_types[0]
                self.logger.check(
                    'vedomost_value' in first,
                    "Ключ 'vedomost_value' существует",
                    "Ключ 'vedomost_value' отсутствует!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # --- get_work_type_record_for_vedomost ---

    def test_15_vedomost_record(self):
        """ТЕСТ 15: Поиск записи для ведомости"""
        self.logger.section("15. get_work_type_record_for_vedomost")
        if not self.manager:
            self.logger.skip("Менеджер не инициализирован")
            return
        try:
            # Ищем запись для раздела
            record = self.manager.get_work_type_record_for_vedomost(
                "Образование земельного участка путем раздела"
            )
            self.logger.check(
                record is not None,
                "Запись для 'раздела' найдена",
                "Запись для 'раздела' не найдена!"
            )

            if record:
                self.logger.check(
                    'code' in record or 'style' in record,
                    f"Запись содержит 'code' или 'style'",
                    f"Запись не содержит 'code' или 'style': {list(record.keys())}"
                )

            # Несуществующая запись
            none_record = self.manager.get_work_type_record_for_vedomost("Несуществующий тип")
            self.logger.check(
                none_record is None,
                "Несуществующий тип -> None",
                f"Несуществующий тип -> {none_record}!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {e}")


def run_tests(iface, logger):
    """Точка входа для запуска тестов"""
    test = TestM22(iface, logger)
    test.run_all_tests()
    return test
