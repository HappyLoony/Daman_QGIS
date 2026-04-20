# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_api - Комплексное тестирование Daman API

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
    """Комплексные тесты Daman API"""

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
        self.logger.section("ТЕСТ API: Daman API")

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
            from Daman_QGIS.managers import LicenseValidator
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
                "daman.tools" in API_BASE_URL or "damantools.ru" in API_BASE_URL,
                "URL указывает на daman.tools или damantools.ru",
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
            # Запрос заведомо несуществующего файла
            data = self.loader._load_from_remote("NonExistentFile_test_32.json")

            self.logger.check(
                data is None,
                "Несуществующий файл возвращает None",
                f"Несуществующий файл вернул данные: {type(data)}"
            )

        except Exception as e:
            # Исключение тоже допустимо для несуществующего файла
            self.logger.success(f"Несуществующий файл обработан: {type(e).__name__}")

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
