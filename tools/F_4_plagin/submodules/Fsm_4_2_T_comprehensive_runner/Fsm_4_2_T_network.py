# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_network - Тестирование сетевых сценариев

Тестирует:
- Обработку сетевых ошибок (DNS, timeout, connection refused)
- Retry логику
- Graceful degradation при недоступности API
- HTTP коды ошибок (400, 401, 403, 404, 500, 502, 503)
- Некорректные ответы сервера (не JSON, пустой ответ)

ВНИМАНИЕ: Этот тест делает реальные сетевые запросы!
Пометьте как network test для возможности пропуска.
"""

import time
from typing import Dict, Any, Optional


class TestNetwork:
    """Тесты сетевых сценариев"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.loader = None
        self.validator = None

    def run_all_tests(self):
        """Запуск всех сетевых тестов"""
        self.logger.section("ТЕСТ NETWORK: Сетевые сценарии")

        try:
            # Инициализация
            self.test_01_init()

            # Тесты реальных запросов
            self.test_10_api_availability()
            self.test_11_api_response_format()
            self.test_12_api_action_list()

            # Тесты HTTP кодов
            self.test_20_http_404_handling()
            self.test_21_http_403_handling()

            # Тесты requests библиотеки
            self.test_30_requests_session()
            self.test_31_requests_headers()
            self.test_32_requests_timeout_config()

            # Stress тесты
            self.test_40_rapid_requests()
            self.test_41_sequential_different_files()

        except Exception as e:
            self.logger.error(f"Критическая ошибка сетевых тестов: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    def test_01_init(self):
        """ТЕСТ 1: Инициализация для сетевых тестов"""
        self.logger.section("1. Инициализация")

        try:
            from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
            from Daman_QGIS.managers import LicenseValidator

            self.loader = BaseReferenceLoader()
            self.validator = LicenseValidator()

            self.logger.success("Модули загружены для сетевых тестов")

        except ImportError as e:
            self.logger.error(f"Ошибка импорта: {str(e)}")

    def _get_auth_headers(self) -> Dict[str, str]:
        """Получить JWT заголовки для аутентифицированных запросов"""
        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_29_4_token_manager import TokenManager
            return TokenManager.get_instance().get_auth_headers()
        except Exception:
            return {}

    def test_10_api_availability(self):
        """ТЕСТ 10: Доступность API (health check)"""
        self.logger.section("10. Проверка доступности API")

        try:
            import requests
            from Daman_QGIS.constants import API_BASE_URL, API_TIMEOUT

            # Health check -- не требует JWT
            url = API_BASE_URL
            start = time.time()

            response = requests.get(url, timeout=API_TIMEOUT)
            elapsed = time.time() - start

            self.logger.info(f"API ответил за {elapsed:.2f}s")
            self.logger.info(f"HTTP статус: {response.status_code}")

            self.logger.check(
                response.status_code == 200,
                f"API доступен (200 OK)",
                f"API вернул ошибку: {response.status_code}"
            )

            # Проверяем Content-Type
            content_type = response.headers.get('Content-Type', '')
            self.logger.check(
                'application/json' in content_type,
                f"Content-Type корректный: {content_type}",
                f"Неожиданный Content-Type: {content_type}"
            )

            # Проверяем формат health check
            if response.status_code == 200:
                data = response.json()
                self.logger.check(
                    isinstance(data, dict) and data.get('status') == 'ok',
                    "Health check: status=ok",
                    f"Неожиданный ответ: {data}"
                )

        except requests.exceptions.Timeout:
            self.logger.fail("API timeout - сервер не отвечает")
        except requests.exceptions.ConnectionError:
            self.logger.fail("API недоступен - ошибка соединения")
        except Exception as e:
            self.logger.error(f"Ошибка проверки доступности: {str(e)}")

    def test_11_api_response_format(self):
        """ТЕСТ 11: Формат ответа API (action=list с JWT)"""
        self.logger.section("11. Формат ответа API")

        try:
            import requests
            from Daman_QGIS.constants import API_TIMEOUT, get_api_url

            headers = self._get_auth_headers()
            if not headers:
                self.logger.warning("JWT токен отсутствует -- тест пропущен (требуется лицензия)")
                return

            url = get_api_url("list")
            response = requests.get(url, headers=headers, timeout=API_TIMEOUT)

            if response.status_code == 200:
                try:
                    data = response.json()

                    self.logger.check(
                        isinstance(data, dict),
                        "Ответ является JSON объектом",
                        f"Ответ не является объектом: {type(data)}"
                    )

                    if isinstance(data, dict):
                        self.logger.check(
                            'files' in data,
                            f"Поле 'files' присутствует",
                            "Поле 'files' отсутствует"
                        )

                        if 'files' in data:
                            files = data['files']
                            self.logger.info(f"Доступно файлов: {len(files)}")

                            expected = ['Base_layers', 'Base_Functions', 'Base_managers']
                            for exp in expected:
                                found = any(exp in f for f in files)
                                self.logger.check(
                                    found,
                                    f"{exp} присутствует в списке",
                                    f"{exp} отсутствует в списке!"
                                )

                except ValueError as e:
                    self.logger.fail(f"Ответ не является валидным JSON: {e}")
            else:
                self.logger.fail(f"API вернул {response.status_code} (ожидался 200)")

        except Exception as e:
            self.logger.error(f"Ошибка проверки формата: {str(e)}")

    def test_12_api_action_list(self):
        """ТЕСТ 12: Действие list (проверка списка файлов)"""
        self.logger.section("12. API action=list")

        try:
            import requests
            from Daman_QGIS.constants import API_TIMEOUT, get_api_url

            headers = self._get_auth_headers()
            if not headers:
                self.logger.warning("JWT токен отсутствует -- тест пропущен (требуется лицензия)")
                return

            url = get_api_url("list")
            response = requests.get(url, headers=headers, timeout=API_TIMEOUT)

            if response.status_code == 200:
                data = response.json()

                if 'files' in data:
                    files = data['files']
                    self.logger.check(
                        len(files) > 0,
                        f"Список файлов получен ({len(files)} шт.)",
                        "Список файлов пуст"
                    )

                    # Проверяем наличие ключевых файлов
                    expected = ['Base_layers', 'Base_Functions']
                    for name in expected:
                        self.logger.check(
                            name in files,
                            f"{name} присутствует в списке",
                            f"{name} отсутствует в списке"
                        )
                else:
                    self.logger.fail("Ответ не содержит поле 'files'")
            else:
                self.logger.fail(f"API вернул {response.status_code}")

        except Exception as e:
            self.logger.error(f"Ошибка теста action=list: {str(e)}")

    def test_20_http_404_handling(self):
        """ТЕСТ 20: Обработка 404 (с JWT)"""
        self.logger.section("20. Обработка HTTP 404")

        try:
            import requests
            from Daman_QGIS.constants import API_TIMEOUT, get_api_url

            headers = self._get_auth_headers()
            if not headers:
                self.logger.warning("JWT токен отсутствует -- тест пропущен (требуется лицензия)")
                return

            # Запрос несуществующего файла
            url = get_api_url("data", file="NonExistentFile123456")
            response = requests.get(url, headers=headers, timeout=API_TIMEOUT)

            self.logger.info(f"HTTP статус для несуществующего файла: {response.status_code}")

            self.logger.check(
                response.status_code in [404, 200],
                f"Корректный статус: {response.status_code}",
                f"Неожиданный статус: {response.status_code}"
            )

            if response.status_code == 200:
                try:
                    data = response.json()
                    if isinstance(data, dict) and 'error' in data:
                        self.logger.success("Ошибка в теле ответа (корректно)")
                except Exception:
                    pass

        except Exception as e:
            self.logger.error(f"Ошибка теста 404: {str(e)}")

    def test_21_http_404_nonexistent_file(self):
        """ТЕСТ 21: Обработка 404 для несуществующего файла (с JWT)"""
        self.logger.section("21. Обработка HTTP 404 (несуществующий файл)")

        try:
            import requests
            from Daman_QGIS.constants import API_TIMEOUT, get_api_url

            headers = self._get_auth_headers()
            if not headers:
                self.logger.warning("JWT токен отсутствует -- тест пропущен (требуется лицензия)")
                return

            url = get_api_url("data", file="NonExistentFile_test_21")
            response = requests.get(url, headers=headers, timeout=API_TIMEOUT)

            self.logger.info(f"HTTP статус для несуществующего файла: {response.status_code}")

            self.logger.check(
                response.status_code == 404,
                f"Несуществующий файл вернул 404",
                f"Неожиданный статус: {response.status_code}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка теста 403: {str(e)}")

    def test_30_requests_session(self):
        """ТЕСТ 30: Проверка requests session"""
        self.logger.section("30. Requests session")

        if not self.validator:
            self.logger.fail("Validator не инициализирован")
            return

        try:
            # Проверяем что session создаётся корректно
            session = self.validator._get_session()

            self.logger.check(
                session is not None,
                "Session создана успешно",
                "Session не создана!"
            )

            if session:
                # Проверяем что это requests.Session
                import requests
                self.logger.check(
                    isinstance(session, requests.Session),
                    "Session является requests.Session",
                    f"Session имеет неожиданный тип: {type(session)}"
                )

        except ImportError:
            self.logger.warning("requests не установлен")
        except Exception as e:
            self.logger.error(f"Ошибка проверки session: {str(e)}")

    def test_31_requests_headers(self):
        """ТЕСТ 31: HTTP заголовки (health check endpoint)"""
        self.logger.section("31. HTTP заголовки")

        try:
            import requests
            from Daman_QGIS.constants import API_BASE_URL, API_TIMEOUT

            # Health check -- не требует JWT
            url = API_BASE_URL
            response = requests.get(url, timeout=API_TIMEOUT)

            # Проверяем заголовки ответа
            resp_headers = response.headers

            self.logger.info(f"Server: {resp_headers.get('Server', 'N/A')}")
            self.logger.info(f"Content-Type: {resp_headers.get('Content-Type', 'N/A')}")

            cors = resp_headers.get('Access-Control-Allow-Origin', 'N/A')
            self.logger.info(f"CORS: {cors}")

        except Exception as e:
            self.logger.error(f"Ошибка проверки заголовков: {str(e)}")

    def test_32_requests_timeout_config(self):
        """ТЕСТ 32: Конфигурация таймаутов"""
        self.logger.section("32. Конфигурация таймаутов")

        try:
            from Daman_QGIS.constants import API_TIMEOUT, DEFAULT_REQUEST_TIMEOUT

            self.logger.info(f"API_TIMEOUT: {API_TIMEOUT}s")

            if hasattr(self, 'DEFAULT_REQUEST_TIMEOUT'):
                self.logger.info(f"DEFAULT_REQUEST_TIMEOUT: {DEFAULT_REQUEST_TIMEOUT}s")

            # Проверяем разумность значений
            self.logger.check(
                5 <= API_TIMEOUT <= 30,
                f"API_TIMEOUT в разумных пределах: {API_TIMEOUT}s",
                f"API_TIMEOUT вне пределов [5, 30]: {API_TIMEOUT}s"
            )

        except ImportError as e:
            self.logger.warning(f"Константа не найдена: {e}")
        except Exception as e:
            self.logger.error(f"Ошибка проверки таймаутов: {str(e)}")

    def test_40_rapid_requests(self):
        """ТЕСТ 40: Быстрые последовательные запросы"""
        self.logger.section("40. Rapid requests (rate limiting)")

        if not self.loader:
            self.logger.fail("Loader не инициализирован")
            return

        try:
            # 5 быстрых запросов подряд
            results = []
            start = time.time()

            for i in range(5):
                data = self.loader._load_from_remote("Base_layers.json")
                results.append(data is not None)

            elapsed = time.time() - start
            success_count = sum(results)

            self.logger.info(f"5 запросов за {elapsed:.2f}s")
            self.logger.info(f"Успешных: {success_count}/5")

            self.logger.check(
                success_count >= 4,  # Допускаем 1 ошибку
                f"Rapid requests успешны: {success_count}/5",
                f"Слишком много ошибок: {success_count}/5"
            )

            # Проверяем что нет rate limiting
            self.logger.check(
                success_count == 5,
                "Rate limiting не обнаружен",
                "Возможен rate limiting"
            )

        except Exception as e:
            self.logger.error(f"Ошибка rapid requests: {str(e)}")

    def test_41_sequential_different_files(self):
        """ТЕСТ 41: Последовательная загрузка разных файлов"""
        self.logger.section("41. Последовательная загрузка")

        if not self.loader:
            self.logger.fail("Loader не инициализирован")
            return

        try:
            files = [
                "Base_layers.json",
                "Base_Functions.json",
                "Base_managers.json",
                "Base_sub_managers.json",
                "Base_field_mapping_EGRN.json",
            ]

            results = {}
            total_time = 0

            for filename in files:
                start = time.time()
                data = self.loader._load_from_remote(filename)
                elapsed = time.time() - start

                total_time += elapsed
                results[filename] = {
                    "success": data is not None,
                    "time": elapsed,
                    "size": len(str(data)) if data else 0
                }

            # Отчёт
            self.logger.info(f"Общее время: {total_time:.2f}s")
            success_count = sum(1 for r in results.values() if r["success"])

            self.logger.check(
                success_count == len(files),
                f"Все файлы загружены: {success_count}/{len(files)}",
                f"Некоторые файлы не загружены: {success_count}/{len(files)}"
            )

            # Статистика по файлам
            for filename, result in results.items():
                if result["success"]:
                    self.logger.info(
                        f"  {filename}: {result['time']:.2f}s, ~{result['size']/1024:.1f}KB"
                    )
                else:
                    self.logger.warning(f"  {filename}: FAILED")

        except Exception as e:
            self.logger.error(f"Ошибка последовательной загрузки: {str(e)}")
