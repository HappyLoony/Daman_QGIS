# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_21_1 - Тест Msm_21_1_ExistingVRIValidator

Тестирует валидатор existing_vri:
- Парсинг различных форматов ВРИ
- Мягкую валидацию по VRI.json
- Сравнение existing_vri с zpr_vri
- Пакетную обработку features_data
"""


class TestMsm211ExistingVRIValidator:
    """Тесты для Msm_21_1_ExistingVRIValidator"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.validator = None

    def run_all_tests(self):
        self.logger.section("ТЕСТ Msm_21_1: ExistingVRIValidator")

        try:
            self.test_01_import()
            self.test_02_parse_full_name_format()
            self.test_03_parse_code_only()
            self.test_04_parse_name_only()
            self.test_05_parse_reversed_format()
            self.test_06_parse_code_with_prefix()
            self.test_07_soft_validate_by_code()
            self.test_08_soft_validate_by_name()
            self.test_09_soft_validate_invalid()
            self.test_10_matches_same_full_name()
            self.test_11_matches_code_to_full_name()
            self.test_12_matches_name_to_full_name()
            self.test_13_matches_different_vri()
            self.test_14_validate_and_decide_keep_existing()
            self.test_15_validate_and_decide_use_zpr()
            self.test_16_validate_batch()
        except Exception as e:
            self.logger.fail(f"Критическая ошибка: {e}")

        self.logger.summary()

    def test_01_import(self):
        """ТЕСТ 1: Импорт и инициализация"""
        self.logger.section("1. Импорт Msm_21_1_ExistingVRIValidator")

        try:
            from Daman_QGIS.managers.validation.submodules import Msm_21_1_ExistingVRIValidator

            # Тестовые данные VRI
            test_vri_data = [
                {
                    "code": "5.0",
                    "name": "Отдых (рекреация)",
                    "full_name": "Отдых (рекреация) (код 5.0)",
                    "is_public_territory": True
                },
                {
                    "code": "12.0.2",
                    "name": "Благоустройство территории",
                    "full_name": "Благоустройство территории (код 12.0.2)",
                    "is_public_territory": True
                },
                {
                    "code": "3.1",
                    "name": "Коммунальное обслуживание",
                    "full_name": "Коммунальное обслуживание (код 3.1)",
                    "is_public_territory": False
                },
            ]

            self.validator = Msm_21_1_ExistingVRIValidator(test_vri_data)
            self.logger.success("Msm_21_1_ExistingVRIValidator инициализирован")
        except ImportError as e:
            self.logger.fail(f"Ошибка импорта: {e}")
        except Exception as e:
            self.logger.fail(f"Ошибка инициализации: {e}")

    def test_02_parse_full_name_format(self):
        """ТЕСТ 2: Парсинг формата full_name"""
        self.logger.section("2. Парсинг: 'Название (код X.Y)'")

        if not self.validator:
            self.logger.fail("Валидатор не инициализирован")
            return

        code, name = self.validator.parse_vri_value("Отдых (рекреация) (код 5.0)")

        if code == "5.0":
            self.logger.success(f"Код извлечён: {code}")
        else:
            self.logger.fail(f"Неверный код: {code}, ожидалось 5.0")

        if name == "Отдых (рекреация)":
            self.logger.success(f"Имя извлечено: {name}")
        else:
            self.logger.fail(f"Неверное имя: {name}")

    def test_03_parse_code_only(self):
        """ТЕСТ 3: Парсинг только кода"""
        self.logger.section("3. Парсинг: '5.0'")

        if not self.validator:
            self.logger.fail("Валидатор не инициализирован")
            return

        code, name = self.validator.parse_vri_value("5.0")

        if code == "5.0":
            self.logger.success(f"Код извлечён: {code}")
        else:
            self.logger.fail(f"Неверный код: {code}")

        if name is None:
            self.logger.success("Имя = None (корректно)")
        else:
            self.logger.fail(f"Ожидалось имя None, получено: {name}")

    def test_04_parse_name_only(self):
        """ТЕСТ 4: Парсинг только имени"""
        self.logger.section("4. Парсинг: 'Благоустройство территории'")

        if not self.validator:
            self.logger.fail("Валидатор не инициализирован")
            return

        code, name = self.validator.parse_vri_value("Благоустройство территории")

        if code is None:
            self.logger.success("Код = None (корректно)")
        else:
            self.logger.fail(f"Ожидался код None, получен: {code}")

        if name == "Благоустройство территории":
            self.logger.success(f"Имя извлечено: {name}")
        else:
            self.logger.fail(f"Неверное имя: {name}")

    def test_05_parse_reversed_format(self):
        """ТЕСТ 5: Парсинг перевёрнутого формата"""
        self.logger.section("5. Парсинг: '(код 5.0) Отдых (рекреация)'")

        if not self.validator:
            self.logger.fail("Валидатор не инициализирован")
            return

        code, name = self.validator.parse_vri_value("(код 5.0) Отдых (рекреация)")

        if code == "5.0":
            self.logger.success(f"Код извлечён: {code}")
        else:
            self.logger.fail(f"Неверный код: {code}")

        if name and "Отдых" in name:
            self.logger.success(f"Имя извлечено: {name}")
        else:
            self.logger.fail(f"Неверное имя: {name}")

    def test_06_parse_code_with_prefix(self):
        """ТЕСТ 6: Парсинг кода с префиксом"""
        self.logger.section("6. Парсинг: 'код 12.0.2'")

        if not self.validator:
            self.logger.fail("Валидатор не инициализирован")
            return

        code, name = self.validator.parse_vri_value("код 12.0.2")

        if code == "12.0.2":
            self.logger.success(f"Код извлечён: {code}")
        else:
            self.logger.fail(f"Неверный код: {code}")

    def test_07_soft_validate_by_code(self):
        """ТЕСТ 7: Мягкая валидация по коду"""
        self.logger.section("7. Soft validate: '5.0'")

        if not self.validator:
            self.logger.fail("Валидатор не инициализирован")
            return

        is_valid, vri_data = self.validator.soft_validate("5.0")

        if is_valid:
            self.logger.success("Валидация пройдена по коду")
        else:
            self.logger.fail("Валидация не пройдена")

        if vri_data and vri_data.get('name') == "Отдых (рекреация)":
            self.logger.success(f"Найден VRI: {vri_data.get('name')}")
        else:
            self.logger.fail(f"Неверные данные VRI: {vri_data}")

    def test_08_soft_validate_by_name(self):
        """ТЕСТ 8: Мягкая валидация по имени"""
        self.logger.section("8. Soft validate: 'Благоустройство территории'")

        if not self.validator:
            self.logger.fail("Валидатор не инициализирован")
            return

        is_valid, vri_data = self.validator.soft_validate("Благоустройство территории")

        if is_valid:
            self.logger.success("Валидация пройдена по имени")
        else:
            self.logger.fail("Валидация не пройдена")

        if vri_data and vri_data.get('code') == "12.0.2":
            self.logger.success(f"Найден VRI код: {vri_data.get('code')}")
        else:
            self.logger.fail(f"Неверные данные VRI: {vri_data}")

    def test_09_soft_validate_invalid(self):
        """ТЕСТ 9: Мягкая валидация невалидного значения"""
        self.logger.section("9. Soft validate: 'Несуществующий ВРИ'")

        if not self.validator:
            self.logger.fail("Валидатор не инициализирован")
            return

        is_valid, vri_data = self.validator.soft_validate("Несуществующий ВРИ")

        if not is_valid:
            self.logger.success("Валидация НЕ пройдена (корректно)")
        else:
            self.logger.fail("Валидация пройдена для невалидного значения!")

        if vri_data is None:
            self.logger.success("VRI data = None (корректно)")
        else:
            self.logger.fail(f"VRI data должен быть None: {vri_data}")

    def test_10_matches_same_full_name(self):
        """ТЕСТ 10: Сравнение одинаковых full_name"""
        self.logger.section("10. Matches: одинаковые full_name")

        if not self.validator:
            self.logger.fail("Валидатор не инициализирован")
            return

        matches, reason = self.validator.matches_zpr_vri(
            "Отдых (рекреация) (код 5.0)",
            "Отдых (рекреация) (код 5.0)"
        )

        if matches:
            self.logger.success(f"Совпадение: {reason}")
        else:
            self.logger.fail(f"Ожидалось совпадение: {reason}")

    def test_11_matches_code_to_full_name(self):
        """ТЕСТ 11: Сравнение кода с full_name"""
        self.logger.section("11. Matches: '5.0' vs 'Отдых (рекреация) (код 5.0)'")

        if not self.validator:
            self.logger.fail("Валидатор не инициализирован")
            return

        matches, reason = self.validator.matches_zpr_vri(
            "5.0",
            "Отдых (рекреация) (код 5.0)"
        )

        if matches:
            self.logger.success(f"Совпадение по коду: {reason}")
        else:
            self.logger.fail(f"Ожидалось совпадение: {reason}")

    def test_12_matches_name_to_full_name(self):
        """ТЕСТ 12: Сравнение имени с full_name"""
        self.logger.section("12. Matches: 'Благоустройство территории' vs full_name")

        if not self.validator:
            self.logger.fail("Валидатор не инициализирован")
            return

        matches, reason = self.validator.matches_zpr_vri(
            "Благоустройство территории",
            "Благоустройство территории (код 12.0.2)"
        )

        if matches:
            self.logger.success(f"Совпадение по имени: {reason}")
        else:
            self.logger.fail(f"Ожидалось совпадение: {reason}")

    def test_13_matches_different_vri(self):
        """ТЕСТ 13: Сравнение разных ВРИ"""
        self.logger.section("13. Matches: разные ВРИ")

        if not self.validator:
            self.logger.fail("Валидатор не инициализирован")
            return

        matches, reason = self.validator.matches_zpr_vri(
            "5.0",  # Отдых (рекреация)
            "Благоустройство территории (код 12.0.2)"
        )

        if not matches:
            self.logger.success(f"Не совпадают (корректно): {reason}")
        else:
            self.logger.fail(f"Ожидалось несовпадение: {reason}")

    def test_14_validate_and_decide_keep_existing(self):
        """ТЕСТ 14: Решение - сохранить existing"""
        self.logger.section("14. Решение: сохранить '5.0' (совпадает с ZPR)")

        if not self.validator:
            self.logger.fail("Валидатор не инициализирован")
            return

        plan_vri, kept_existing, reason = self.validator.validate_and_decide(
            "5.0",
            "Отдых (рекреация) (код 5.0)"
        )

        if kept_existing:
            self.logger.success(f"Сохранён existing: '{plan_vri}'")
        else:
            self.logger.fail(f"Ожидалось сохранение existing: {reason}")

        if plan_vri == "5.0":
            self.logger.success("План_ВРИ = '5.0' (оригинал)")
        else:
            self.logger.fail(f"План_ВРИ должен быть '5.0': {plan_vri}")

    def test_15_validate_and_decide_use_zpr(self):
        """ТЕСТ 15: Решение - использовать ZPR"""
        self.logger.section("15. Решение: использовать ZPR (разные ВРИ)")

        if not self.validator:
            self.logger.fail("Валидатор не инициализирован")
            return

        plan_vri, kept_existing, reason = self.validator.validate_and_decide(
            "5.0",  # Отдых
            "Благоустройство территории (код 12.0.2)"  # Благоустройство
        )

        if not kept_existing:
            self.logger.success(f"Использован ZPR: '{plan_vri}'")
        else:
            self.logger.fail(f"Ожидалось использование ZPR: {reason}")

        if "Благоустройство" in plan_vri:
            self.logger.success("План_ВРИ содержит 'Благоустройство'")
        else:
            self.logger.fail(f"План_ВРИ должен быть из ZPR: {plan_vri}")

    def test_16_validate_batch(self):
        """ТЕСТ 16: Пакетная валидация"""
        self.logger.section("16. Пакетная валидация features_data")

        if not self.validator:
            self.logger.fail("Валидатор не инициализирован")
            return

        # Тестовые данные
        features_data = [
            {
                'attributes': {'ВРИ': '5.0', 'План_ВРИ': '-'},
                'zpr_vri': 'Отдых (рекреация) (код 5.0)'
            },
            {
                'attributes': {'ВРИ': 'Благоустройство территории', 'План_ВРИ': '-'},
                'zpr_vri': 'Благоустройство территории (код 12.0.2)'
            },
            {
                'attributes': {'ВРИ': '3.1', 'План_ВРИ': '-'},
                'zpr_vri': 'Отдых (рекреация) (код 5.0)'  # Разные!
            },
        ]

        result = self.validator.validate_batch(features_data)

        # Проверка 1: сохранён existing '5.0'
        plan1 = result[0]['attributes']['План_ВРИ']
        if plan1 == '5.0':
            self.logger.success(f"Feature 1: План_ВРИ = '{plan1}' (existing сохранён)")
        else:
            self.logger.fail(f"Feature 1: ожидалось '5.0', получено '{plan1}'")

        # Проверка 2: сохранён existing имя
        plan2 = result[1]['attributes']['План_ВРИ']
        if plan2 == 'Благоустройство территории':
            self.logger.success(f"Feature 2: План_ВРИ = '{plan2}' (existing сохранён)")
        else:
            self.logger.fail(f"Feature 2: ожидалось 'Благоустройство...', получено '{plan2}'")

        # Проверка 3: использован ZPR (разные ВРИ)
        plan3 = result[2]['attributes']['План_ВРИ']
        if 'Отдых' in plan3:
            self.logger.success(f"Feature 3: План_ВРИ = '{plan3}' (ZPR использован)")
        else:
            self.logger.fail(f"Feature 3: ожидалось ZPR 'Отдых...', получено '{plan3}'")


def run_tests(iface, logger):
    """Точка входа для запуска тестов"""
    test = TestMsm211ExistingVRIValidator(iface, logger)
    test.run_all_tests()
    return test
