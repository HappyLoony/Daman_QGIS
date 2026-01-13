# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_5_2_T_api - Комплексное тестирование Yandex Cloud API

Тестирует:
- BaseReferenceLoader (загрузка справочных данных)
- LicenseValidator (валидация лицензий)
- Сетевые ошибки и edge cases
- Производительность и таймауты

Best practices:
- AAA Pattern (Arrange, Act, Assert)
- Тестирование edge cases и ошибок
- Проверка схемы ответов API
- Мониторинг производительности
"""

import time
from typing import Dict, Any, Optional


class TestAPI:
    """Комплексные тесты Yandex Cloud API"""

    # Тестовые данные
    INVALID_API_KEY = "INVALID-KEY-12345-FAKE"
    MALFORMED_API_KEY = "not-a-valid-uuid-format"
    EMPTY_API_KEY = ""
    SQL_INJECTION_KEY = "'; DROP TABLE licenses; --"
    XSS_KEY = "<script>alert('xss')</script>"
    UNICODE_KEY = "ключ-с-юникодом-"
    LONG_KEY = "A" * 1000  # Очень длинный ключ

    # Ожидаемые JSON файлы
    EXPECTED_JSON_FILES = [
        "Base_layers",
        "Base_Functions",
        "Base_managers",
        "Base_sub_managers",
        "Base_field_mapping_EGRN",
        "Base_selection_ZU",
        "Base_selection_OKS",
    ]

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.loader = None
        self.validator = None
        self.api_url = None

    def run_all_tests(self):
        """Запуск всех тестов API"""
        self.logger.section("ТЕСТ API: Yandex Cloud Function")

        try:
            # Инициализация
            self.test_01_init_modules()
            self.test_02_check_api_url()

            # BaseReferenceLoader тесты
            self.test_10_loader_basic()
            self.test_11_loader_all_json_files()
            self.test_12_loader_invalid_file()
            self.test_13_loader_schema_validation()
            self.test_14_loader_caching()
            self.test_15_loader_performance()

            # LicenseValidator тесты
            self.test_20_validator_basic()
            self.test_21_validator_invalid_key()
            self.test_22_validator_malformed_keys()
            self.test_23_validator_security_payloads()
            self.test_24_validator_missing_params()
            self.test_25_validator_hardware_mismatch()
            self.test_26_validator_deactivate()

            # Edge cases
            self.test_30_concurrent_requests()
            self.test_31_timeout_handling()
            self.test_32_empty_responses()
            self.test_33_large_payloads()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов API: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    # === ИНИЦИАЛИЗАЦИЯ ===

    def test_01_init_modules(self):
        """ТЕСТ 1: Инициализация модулей API"""
        self.logger.section("1. Инициализация модулей")

        try:
            # BaseReferenceLoader
            from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
            self.loader = BaseReferenceLoader()
            self.logger.success("BaseReferenceLoader загружен")

            # LicenseValidator
            from Daman_QGIS.managers.submodules.Msm_29_3_license_validator import LicenseValidator
            self.validator = LicenseValidator()
            self.logger.success("LicenseValidator загружен")

            # Проверяем методы
            self.logger.check(
                hasattr(self.loader, '_load_from_remote'),
                "Метод _load_from_remote существует",
                "Метод _load_from_remote отсутствует!"
            )

            self.logger.check(
                hasattr(self.validator, 'activate'),
                "Метод activate существует",
                "Метод activate отсутствует!"
            )

            self.logger.check(
                hasattr(self.validator, 'verify'),
                "Метод verify существует",
                "Метод verify отсутствует!"
            )

            self.logger.check(
                hasattr(self.validator, 'deactivate'),
                "Метод deactivate существует",
                "Метод deactivate отсутствует!"
            )

        except ImportError as e:
            self.logger.error(f"Ошибка импорта: {str(e)}")
        except Exception as e:
            self.logger.error(f"Ошибка инициализации: {str(e)}")

    def test_02_check_api_url(self):
        """ТЕСТ 2: Проверка URL API"""
        self.logger.section("2. Проверка конфигурации API")

        try:
            from Daman_QGIS.constants import API_BASE_URL, API_TIMEOUT

            self.api_url = API_BASE_URL
            self.logger.info(f"API_BASE_URL: {API_BASE_URL}")
            self.logger.info(f"API_TIMEOUT: {API_TIMEOUT}")

            # Проверяем формат URL
            self.logger.check(
                API_BASE_URL.startswith("https://"),
                "URL использует HTTPS",
                "URL не использует HTTPS - небезопасно!"
            )

            self.logger.check(
                "yandexcloud" in API_BASE_URL or "functions" in API_BASE_URL,
                "URL указывает на Yandex Cloud",
                f"Неожиданный URL: {API_BASE_URL}"
            )

            self.logger.check(
                API_TIMEOUT > 0,
                f"Таймаут положительный: {API_TIMEOUT}s",
                "Таймаут некорректный!"
            )

        except ImportError as e:
            self.logger.error(f"Ошибка импорта констант: {str(e)}")

    # === BASEREFERENCE LOADER ТЕСТЫ ===

    def test_10_loader_basic(self):
        """ТЕСТ 10: Базовая загрузка JSON"""
        self.logger.section("10. Базовая загрузка данных")

        if not self.loader:
            self.logger.fail("Loader не инициализирован")
            return

        try:
            # Загружаем Base_layers.json
            start_time = time.time()
            data = self.loader._load_from_remote("Base_layers.json")
            elapsed = time.time() - start_time

            self.logger.check(
                data is not None,
                f"Base_layers.json загружен за {elapsed:.2f}s",
                "Base_layers.json не загружен!"
            )

            if data:
                self.logger.check(
                    isinstance(data, (dict, list)),
                    f"Данные корректного типа: {type(data).__name__}",
                    f"Неожиданный тип данных: {type(data)}"
                )

                # Проверяем размер
                if isinstance(data, list):
                    self.logger.info(f"Записей в Base_layers: {len(data)}")
                elif isinstance(data, dict):
                    self.logger.info(f"Ключей в Base_layers: {len(data)}")

        except Exception as e:
            self.logger.error(f"Ошибка загрузки: {str(e)}")

    def test_11_loader_all_json_files(self):
        """ТЕСТ 11: Загрузка всех JSON файлов"""
        self.logger.section("11. Загрузка всех справочников")

        if not self.loader:
            self.logger.fail("Loader не инициализирован")
            return

        for filename in self.EXPECTED_JSON_FILES:
            try:
                data = self.loader._load_from_remote(f"{filename}.json")

                if data is not None:
                    self.logger.success(f"{filename}.json загружен")
                else:
                    self.logger.fail(f"{filename}.json не загружен")

            except Exception as e:
                self.logger.fail(f"{filename}.json ошибка: {str(e)}")

    def test_12_loader_invalid_file(self):
        """ТЕСТ 12: Запрос несуществующего файла"""
        self.logger.section("12. Обработка несуществующего файла")

        if not self.loader:
            self.logger.fail("Loader не инициализирован")
            return

        try:
            # Запрос несуществующего файла
            data = self.loader._load_from_remote("NonExistent_File_12345.json")

            self.logger.check(
                data is None,
                "Несуществующий файл корректно возвращает None",
                f"Неожиданный ответ для несуществующего файла: {data}"
            )

        except Exception as e:
            # Исключение тоже допустимо
            self.logger.success(f"Исключение для несуществующего файла: {type(e).__name__}")

    def test_13_loader_schema_validation(self):
        """ТЕСТ 13: Валидация схемы ответов"""
        self.logger.section("13. Валидация схемы данных")

        if not self.loader:
            self.logger.fail("Loader не инициализирован")
            return

        try:
            # Base_layers должен содержать определённые поля
            data = self.loader._load_from_remote("Base_layers.json")

            if data and isinstance(data, list) and len(data) > 0:
                first_item = data[0]

                # Проверяем ожидаемые поля (реальная структура)
                expected_fields = ["full_name", "section", "geometry_type"]
                for field in expected_fields:
                    self.logger.check(
                        field in first_item,
                        f"Поле '{field}' присутствует в Base_layers",
                        f"Поле '{field}' отсутствует в Base_layers!"
                    )

            # Base_Functions должен содержать функции
            funcs = self.loader._load_from_remote("Base_Functions.json")

            if funcs and isinstance(funcs, list) and len(funcs) > 0:
                first_func = funcs[0]

                # Реальная структура Base_Functions
                expected_func_fields = ["tool_id", "function_name", "class_name"]
                for field in expected_func_fields:
                    self.logger.check(
                        field in first_func,
                        f"Поле '{field}' присутствует в Base_Functions",
                        f"Поле '{field}' отсутствует в Base_Functions!"
                    )

        except Exception as e:
            self.logger.error(f"Ошибка валидации схемы: {str(e)}")

    def test_14_loader_caching(self):
        """ТЕСТ 14: Проверка кэширования"""
        self.logger.section("14. Кэширование запросов")

        if not self.loader:
            self.logger.fail("Loader не инициализирован")
            return

        try:
            # Первый запрос
            start1 = time.time()
            data1 = self.loader._load_from_remote("Base_layers.json")
            time1 = time.time() - start1

            # Второй запрос (должен использовать кэш если есть)
            start2 = time.time()
            data2 = self.loader._load_from_remote("Base_layers.json")
            time2 = time.time() - start2

            self.logger.info(f"Первый запрос: {time1:.3f}s")
            self.logger.info(f"Второй запрос: {time2:.3f}s")

            # Данные должны быть идентичны
            if data1 and data2:
                self.logger.check(
                    len(str(data1)) == len(str(data2)),
                    "Данные идентичны",
                    "Данные отличаются!"
                )

        except Exception as e:
            self.logger.error(f"Ошибка теста кэширования: {str(e)}")

    def test_15_loader_performance(self):
        """ТЕСТ 15: Производительность загрузки"""
        self.logger.section("15. Производительность API")

        if not self.loader:
            self.logger.fail("Loader не инициализирован")
            return

        try:
            # Измеряем время загрузки нескольких файлов
            total_time = 0
            file_count = 0

            for filename in self.EXPECTED_JSON_FILES[:3]:  # Первые 3 файла
                start = time.time()
                data = self.loader._load_from_remote(f"{filename}.json")
                elapsed = time.time() - start

                if data:
                    total_time += elapsed
                    file_count += 1

            if file_count > 0:
                avg_time = total_time / file_count
                self.logger.info(f"Среднее время загрузки: {avg_time:.3f}s")

                # Предупреждение если медленно
                if avg_time > 2.0:
                    self.logger.warning(f"API медленный: {avg_time:.3f}s > 2s")
                else:
                    self.logger.success(f"API быстрый: {avg_time:.3f}s")

        except Exception as e:
            self.logger.error(f"Ошибка теста производительности: {str(e)}")

    # === LICENSE VALIDATOR ТЕСТЫ ===

    def test_20_validator_basic(self):
        """ТЕСТ 20: Базовая работа валидатора"""
        self.logger.section("20. Базовая проверка LicenseValidator")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # Проверяем что base_url установлен
            self.logger.check(
                hasattr(self.validator, 'base_url') and self.validator.base_url,
                f"base_url установлен: {self.validator.base_url}",
                "base_url не установлен!"
            )

            # Проверяем clear_cache (для совместимости)
            self.logger.check(
                hasattr(self.validator, 'clear_cache'),
                "Метод clear_cache существует",
                "Метод clear_cache отсутствует!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка базовой проверки: {str(e)}")

    def test_21_validator_invalid_key(self):
        """ТЕСТ 21: Невалидный API ключ"""
        self.logger.section("21. Тест невалидного ключа")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            result = self.validator.verify(
                api_key=self.INVALID_API_KEY,
                hardware_id="test-hardware-id"
            )

            self.logger.check(
                result.get("status") in ["invalid_key", "error"],
                f"Невалидный ключ отклонён: {result.get('status')}",
                f"Неожиданный статус для невалидного ключа: {result}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка теста невалидного ключа: {str(e)}")

    def test_22_validator_malformed_keys(self):
        """ТЕСТ 22: Некорректные форматы ключей"""
        self.logger.section("22. Тест некорректных форматов ключей")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        malformed_keys = [
            ("Пустой ключ", self.EMPTY_API_KEY),
            ("Malformed ключ", self.MALFORMED_API_KEY),
            ("Unicode ключ", self.UNICODE_KEY),
            ("Очень длинный ключ", self.LONG_KEY),
        ]

        for name, key in malformed_keys:
            try:
                result = self.validator.verify(
                    api_key=key,
                    hardware_id="test-hardware-id"
                )

                # Должен вернуть ошибку, а не упасть
                self.logger.check(
                    result.get("status") in ["invalid_key", "error"],
                    f"{name}: корректно отклонён",
                    f"{name}: неожиданный ответ {result.get('status')}"
                )

            except Exception as e:
                self.logger.fail(f"{name}: исключение {type(e).__name__}: {e}")

    def test_23_validator_security_payloads(self):
        """ТЕСТ 23: Безопасность - SQL injection, XSS"""
        self.logger.section("23. Тест безопасности (SQL injection, XSS)")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        security_payloads = [
            ("SQL Injection", self.SQL_INJECTION_KEY),
            ("XSS Payload", self.XSS_KEY),
            ("Path Traversal", "../../../etc/passwd"),
            ("Null Byte", "key\x00injection"),
            ("CRLF Injection", "key\r\nX-Injected: header"),
        ]

        for name, payload in security_payloads:
            try:
                result = self.validator.verify(
                    api_key=payload,
                    hardware_id="test-hardware-id"
                )

                # API должен безопасно обработать вредоносный payload
                self.logger.check(
                    result.get("status") in ["invalid_key", "error"],
                    f"{name}: безопасно обработан",
                    f"{name}: подозрительный ответ {result}"
                )

            except Exception as e:
                # Исключение тоже допустимо (но нежелательно)
                self.logger.warning(f"{name}: исключение {type(e).__name__}")

    def test_24_validator_missing_params(self):
        """ТЕСТ 24: Отсутствующие параметры"""
        self.logger.section("24. Тест отсутствующих параметров")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # Пустой hardware_id
            result = self.validator.verify(
                api_key="some-key",
                hardware_id=""
            )

            self.logger.check(
                result.get("status") in ["error", "invalid_key"],
                f"Пустой hardware_id: отклонён ({result.get('status')})",
                f"Пустой hardware_id: неожиданный ответ {result}"
            )

        except Exception as e:
            self.logger.warning(f"Пустой hardware_id вызвал исключение: {e}")

    def test_25_validator_hardware_mismatch(self):
        """ТЕСТ 25: Несовпадение Hardware ID"""
        self.logger.section("25. Тест несовпадения Hardware ID")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # Используем невалидный ключ с разными hardware_id
            result1 = self.validator.verify(
                api_key=self.INVALID_API_KEY,
                hardware_id="hardware-1"
            )

            result2 = self.validator.verify(
                api_key=self.INVALID_API_KEY,
                hardware_id="hardware-2"
            )

            # Оба должны быть отклонены (ключ невалидный)
            self.logger.check(
                result1.get("status") in ["invalid_key", "error", "hardware_mismatch"],
                f"Hardware-1: {result1.get('status')}",
                f"Hardware-1: неожиданный ответ"
            )

            self.logger.check(
                result2.get("status") in ["invalid_key", "error", "hardware_mismatch"],
                f"Hardware-2: {result2.get('status')}",
                f"Hardware-2: неожиданный ответ"
            )

        except Exception as e:
            self.logger.error(f"Ошибка теста hardware mismatch: {str(e)}")

    def test_26_validator_deactivate(self):
        """ТЕСТ 26: Деактивация лицензии"""
        self.logger.section("26. Тест деактивации")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # Попытка деактивации невалидного ключа
            result = self.validator.deactivate(
                api_key=self.INVALID_API_KEY,
                hardware_id="test-hardware-id"
            )

            self.logger.check(
                result.get("status") in ["error", "success"],
                f"Деактивация невалидного ключа: {result.get('status')}",
                f"Неожиданный ответ деактивации: {result}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка теста деактивации: {str(e)}")

    # === EDGE CASES ===

    def test_30_concurrent_requests(self):
        """ТЕСТ 30: Параллельные запросы"""
        self.logger.section("30. Параллельные запросы")

        if not self.loader:
            self.logger.fail("Loader не инициализирован")
            return

        try:
            import concurrent.futures

            files_to_load = ["Base_layers.json", "Base_Functions.json", "Base_managers.json"]

            start = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = {
                    executor.submit(self.loader._load_from_remote, f): f
                    for f in files_to_load
                }

                results = {}
                for future in concurrent.futures.as_completed(futures):
                    filename = futures[future]
                    try:
                        data = future.result()
                        results[filename] = data is not None
                    except Exception as e:
                        results[filename] = False

            elapsed = time.time() - start

            success_count = sum(1 for v in results.values() if v)
            self.logger.info(f"Параллельная загрузка: {success_count}/{len(files_to_load)} за {elapsed:.2f}s")

            self.logger.check(
                success_count == len(files_to_load),
                "Все параллельные запросы успешны",
                f"Некоторые запросы не удались: {results}"
            )

        except ImportError:
            self.logger.warning("concurrent.futures недоступен, пропускаем тест")
        except Exception as e:
            self.logger.error(f"Ошибка параллельных запросов: {str(e)}")

    def test_31_timeout_handling(self):
        """ТЕСТ 31: Обработка таймаутов"""
        self.logger.section("31. Обработка таймаутов")

        # Этот тест проверяет что система корректно обрабатывает таймауты
        # Мы не можем искусственно создать таймаут, но можем проверить настройки

        try:
            from Daman_QGIS.constants import API_TIMEOUT

            self.logger.check(
                API_TIMEOUT >= 5,
                f"Таймаут достаточный: {API_TIMEOUT}s >= 5s",
                f"Таймаут слишком маленький: {API_TIMEOUT}s"
            )

            self.logger.check(
                API_TIMEOUT <= 60,
                f"Таймаут разумный: {API_TIMEOUT}s <= 60s",
                f"Таймаут слишком большой: {API_TIMEOUT}s"
            )

        except Exception as e:
            self.logger.error(f"Ошибка проверки таймаутов: {str(e)}")

    def test_32_empty_responses(self):
        """ТЕСТ 32: Пустые ответы"""
        self.logger.section("32. Обработка пустых ответов")

        if not self.loader:
            self.logger.fail("Loader не инициализирован")
            return

        try:
            # Запрос файла который может быть пустым
            data = self.loader._load_from_remote("Base_licenses.json")

            # Base_licenses.json должен вернуть 403 (защищён)
            # или None (если API правильно скрывает)
            self.logger.check(
                data is None,
                "Base_licenses.json защищён (403 или None)",
                f"Base_licenses.json доступен публично - УЯЗВИМОСТЬ! {type(data)}"
            )

        except Exception as e:
            # Исключение тоже допустимо для защищённого файла
            self.logger.success(f"Base_licenses.json защищён: {type(e).__name__}")

    def test_33_large_payloads(self):
        """ТЕСТ 33: Большие данные"""
        self.logger.section("33. Работа с большими данными")

        if not self.loader:
            self.logger.fail("Loader не инициализирован")
            return

        try:
            # Base_layers обычно самый большой файл
            start = time.time()
            data = self.loader._load_from_remote("Base_layers.json")
            elapsed = time.time() - start

            if data:
                # Оцениваем размер данных
                data_str = str(data)
                size_kb = len(data_str) / 1024

                self.logger.info(f"Base_layers размер: ~{size_kb:.1f} KB")
                self.logger.info(f"Время загрузки: {elapsed:.2f}s")

                self.logger.check(
                    elapsed < 10,
                    f"Большой файл загружен за {elapsed:.2f}s < 10s",
                    f"Слишком медленно: {elapsed:.2f}s"
                )

        except Exception as e:
            self.logger.error(f"Ошибка теста больших данных: {str(e)}")
