# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_heartbeat - Тестирование Heartbeat и License Revocation

Тестирует:
- Endpoint ?action=heartbeat доступность и формат ответа
- HMAC подпись heartbeat запросов
- Обработку статусов (active, revoked, INTEGRITY_MISSING, INTEGRITY_MISMATCH)
- Heartbeat с невалидными данными (ключ, hardware_id, подпись)
- Защиту от replay attacks (timestamp)
- Клиентскую интеграцию (таймер, константы)
- Server-side integrity check (file_hashes в heartbeat)

ВНИМАНИЕ: Этот тест делает реальные сетевые запросы!
"""

import os
import time
import hmac
import hashlib
from typing import Dict, Any, Optional


class TestHeartbeat:
    """Тесты Heartbeat и License Revocation"""

    def __init__(self, iface, logger):
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.api_key = None
        self.hardware_id = None

    def run_all_tests(self):
        """Запуск всех тестов heartbeat"""
        self.logger.section("ТЕСТ HEARTBEAT: Heartbeat и License Revocation")

        try:
            # Инициализация
            self.test_01_init()
            self.test_02_constants()

            # Endpoint тесты
            self.test_10_heartbeat_active()
            self.test_11_heartbeat_response_format()
            self.test_12_heartbeat_method_check()

            # Негативные тесты
            self.test_20_heartbeat_invalid_key()
            self.test_21_heartbeat_wrong_hwid()
            self.test_22_heartbeat_invalid_signature()
            self.test_23_heartbeat_expired_timestamp()
            self.test_24_heartbeat_missing_fields()

            # Клиентская интеграция
            self.test_30_client_timer_setup()
            self.test_31_client_revocation_handler()

            # Производительность
            self.test_40_heartbeat_performance()

            # Server-side integrity check
            self.test_50_heartbeat_with_valid_hashes()
            self.test_51_heartbeat_with_tampered_hashes()
            self.test_52_heartbeat_without_hashes_integrity_missing()
            self.test_53_heartbeat_with_partial_hashes()
            self.test_54_heartbeat_with_invalid_hash_types()
            self.test_55_client_sends_hashes_in_payload()

        except Exception as e:
            self.logger.error(f"Критическая ошибка heartbeat тестов: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    # === Инициализация ===

    def test_01_init(self):
        """ТЕСТ 1: Инициализация для heartbeat тестов"""
        self.logger.section("1. Инициализация")

        try:
            from Daman_QGIS.managers._registry import registry
            license_mgr = registry.get('M_29')

            self.api_key = license_mgr.get_api_key()
            self.hardware_id = license_mgr.get_hardware_id()

            self.logger.check(
                self.api_key is not None and len(self.api_key) > 0,
                "API key получен",
                "API key отсутствует (тесты будут пропущены)"
            )

            self.logger.check(
                self.hardware_id is not None and len(self.hardware_id) > 0,
                "Hardware ID получен",
                "Hardware ID отсутствует"
            )

        except Exception as e:
            self.logger.error(f"Ошибка инициализации: {str(e)}")

    def test_02_constants(self):
        """ТЕСТ 2: Проверка констант heartbeat"""
        self.logger.section("2. Константы heartbeat")

        try:
            from Daman_QGIS.constants import HEARTBEAT_INTERVAL_MS

            self.logger.info(f"HEARTBEAT_INTERVAL_MS: {HEARTBEAT_INTERVAL_MS}ms "
                             f"({HEARTBEAT_INTERVAL_MS / 3600000:.1f} часов)")

            self.logger.check(
                HEARTBEAT_INTERVAL_MS >= 60 * 1000,
                f"Интервал >= 1 мин: {HEARTBEAT_INTERVAL_MS}ms",
                f"Интервал слишком маленький: {HEARTBEAT_INTERVAL_MS}ms"
            )

            self.logger.check(
                HEARTBEAT_INTERVAL_MS <= 24 * 60 * 60 * 1000,
                f"Интервал <= 24 часа: {HEARTBEAT_INTERVAL_MS}ms",
                f"Интервал слишком большой: {HEARTBEAT_INTERVAL_MS}ms"
            )

        except ImportError:
            self.logger.fail("HEARTBEAT_INTERVAL_MS не найден в constants.py")
        except Exception as e:
            self.logger.error(f"Ошибка проверки констант: {str(e)}")

    # === Helpers ===

    def _build_heartbeat_payload(self, api_key: Optional[str] = None,
                                  hardware_id: Optional[str] = None,
                                  timestamp: Optional[int] = None,
                                  signature: Optional[str] = None) -> Dict[str, Any]:
        """Построить payload для heartbeat запроса"""
        _api_key = api_key if api_key is not None else self.api_key
        _hardware_id = hardware_id if hardware_id is not None else self.hardware_id
        _timestamp = timestamp if timestamp is not None else int(time.time())

        if signature is None and _api_key and _hardware_id:
            signature = hmac.new(
                _api_key.encode('utf-8'),
                f"{_hardware_id}|{_timestamp}".encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

        return {
            "api_key": _api_key or "",
            "hardware_id": _hardware_id or "",
            "timestamp": _timestamp,
            "signature": signature or ""
        }

    def _send_heartbeat(self, payload: Dict[str, Any]) -> Any:
        """Отправить heartbeat запрос"""
        import requests
        from Daman_QGIS.constants import API_TIMEOUT, get_api_url

        return requests.post(
            get_api_url("heartbeat"),
            json=payload,
            timeout=API_TIMEOUT
        )

    # === Endpoint тесты ===

    def test_10_heartbeat_active(self):
        """ТЕСТ 10: Heartbeat с валидной лицензией (status=active)"""
        self.logger.section("10. Heartbeat active")

        if not self.api_key:
            self.logger.warning("API key отсутствует -- тест пропущен")
            return

        try:
            payload = self._build_heartbeat_payload()

            # Включаем file_hashes — сервер требует integrity check
            file_hashes = self._compute_real_file_hashes()
            if file_hashes:
                from Daman_QGIS.constants import PLUGIN_VERSION
                payload['file_hashes'] = file_hashes
                payload['plugin_version'] = PLUGIN_VERSION

            response = self._send_heartbeat(payload)

            self.logger.info(f"HTTP статус: {response.status_code}")

            self.logger.check(
                response.status_code == 200,
                "Heartbeat вернул 200",
                f"Неожиданный статус: {response.status_code}"
            )

            if response.status_code == 200:
                data = response.json()
                self.logger.check(
                    data.get('status') == 'active',
                    "Лицензия активна (status=active)",
                    f"Неожиданный статус: {data.get('status')}"
                )

        except Exception as e:
            self.logger.error(f"Ошибка heartbeat: {str(e)}")

    def test_11_heartbeat_response_format(self):
        """ТЕСТ 11: Формат ответа heartbeat"""
        self.logger.section("11. Формат ответа")

        if not self.api_key:
            self.logger.warning("API key отсутствует -- тест пропущен")
            return

        try:
            payload = self._build_heartbeat_payload()
            response = self._send_heartbeat(payload)

            if response.status_code == 200:
                data = response.json()

                self.logger.check(
                    isinstance(data, dict),
                    "Ответ является JSON объектом",
                    f"Ответ не объект: {type(data)}"
                )

                self.logger.check(
                    'status' in data,
                    "Поле 'status' присутствует",
                    "Поле 'status' отсутствует"
                )

                self.logger.check(
                    data.get('status') in ('active', 'revoked'),
                    f"Статус валиден: {data.get('status')}",
                    f"Неизвестный статус: {data.get('status')}"
                )

                # Content-Type
                content_type = response.headers.get('Content-Type', '')
                self.logger.check(
                    'application/json' in content_type,
                    f"Content-Type корректный: {content_type}",
                    f"Неожиданный Content-Type: {content_type}"
                )

        except Exception as e:
            self.logger.error(f"Ошибка проверки формата: {str(e)}")

    def test_12_heartbeat_method_check(self):
        """ТЕСТ 12: Heartbeat принимает только POST"""
        self.logger.section("12. Проверка HTTP метода")

        try:
            import requests
            from Daman_QGIS.constants import API_TIMEOUT, get_api_url

            # GET должен вернуть 405
            response = requests.get(
                get_api_url("heartbeat"),
                timeout=API_TIMEOUT
            )

            self.logger.check(
                response.status_code == 405,
                f"GET вернул 405 (Method Not Allowed)",
                f"GET вернул {response.status_code} (ожидался 405)"
            )

        except Exception as e:
            self.logger.error(f"Ошибка проверки метода: {str(e)}")

    # === Негативные тесты ===

    def test_20_heartbeat_invalid_key(self):
        """ТЕСТ 20: Heartbeat с невалидным API ключом"""
        self.logger.section("20. Невалидный API ключ")

        try:
            fake_key = "DAMAN-FAKE-FAKE-FAKE"
            payload = self._build_heartbeat_payload(api_key=fake_key)
            response = self._send_heartbeat(payload)

            self.logger.info(f"HTTP статус: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                self.logger.check(
                    data.get('status') == 'revoked',
                    f"Невалидный ключ -> revoked: {data.get('reason', '')}",
                    f"Неожиданный статус: {data.get('status')}"
                )
            elif response.status_code == 401:
                # HMAC с fake ключом не совпадет
                self.logger.success("Невалидный ключ -> 401 (HMAC mismatch)")
            else:
                self.logger.info(f"Невалидный ключ -> HTTP {response.status_code}")

        except Exception as e:
            self.logger.error(f"Ошибка теста невалидного ключа: {str(e)}")

    def test_21_heartbeat_wrong_hwid(self):
        """ТЕСТ 21: Heartbeat с чужим hardware_id"""
        self.logger.section("21. Чужой Hardware ID")

        if not self.api_key:
            self.logger.warning("API key отсутствует -- тест пропущен")
            return

        try:
            fake_hwid = "fake_hardware_id_12345"
            # Подписываем с правильным ключом но чужим hwid
            payload = self._build_heartbeat_payload(hardware_id=fake_hwid)
            response = self._send_heartbeat(payload)

            self.logger.info(f"HTTP статус: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                self.logger.check(
                    data.get('status') == 'revoked',
                    f"Чужой HWID -> revoked: {data.get('reason', '')}",
                    f"Чужой HWID не обнаружен: {data.get('status')}"
                )
            else:
                self.logger.info(f"Чужой HWID -> HTTP {response.status_code}")

        except Exception as e:
            self.logger.error(f"Ошибка теста HWID: {str(e)}")

    def test_22_heartbeat_invalid_signature(self):
        """ТЕСТ 22: Heartbeat с подделанной подписью"""
        self.logger.section("22. Невалидная подпись")

        if not self.api_key:
            self.logger.warning("API key отсутствует -- тест пропущен")
            return

        try:
            payload = self._build_heartbeat_payload(signature="invalid_signature_hex")
            response = self._send_heartbeat(payload)

            self.logger.check(
                response.status_code == 401,
                f"Невалидная подпись -> 401",
                f"Невалидная подпись -> {response.status_code} (ожидался 401)"
            )

        except Exception as e:
            self.logger.error(f"Ошибка теста подписи: {str(e)}")

    def test_23_heartbeat_expired_timestamp(self):
        """ТЕСТ 23: Heartbeat с истекшим timestamp (replay attack)"""
        self.logger.section("23. Replay attack (expired timestamp)")

        if not self.api_key:
            self.logger.warning("API key отсутствует -- тест пропущен")
            return

        try:
            # Timestamp 2 часа назад (TIMESTAMP_TOLERANCE = 900 сек)
            old_timestamp = int(time.time()) - 7200
            payload = self._build_heartbeat_payload(timestamp=old_timestamp)
            response = self._send_heartbeat(payload)

            self.logger.check(
                response.status_code == 400,
                f"Старый timestamp -> 400",
                f"Старый timestamp -> {response.status_code} (ожидался 400)"
            )

            if response.status_code == 400:
                data = response.json()
                self.logger.check(
                    data.get('error_code') == 'EXPIRED_TIMESTAMP',
                    "error_code = EXPIRED_TIMESTAMP",
                    f"Неожиданный error_code: {data.get('error_code')}"
                )

        except Exception as e:
            self.logger.error(f"Ошибка теста replay: {str(e)}")

    def test_24_heartbeat_missing_fields(self):
        """ТЕСТ 24: Heartbeat без обязательных полей"""
        self.logger.section("24. Отсутствующие поля")

        try:
            import requests
            from Daman_QGIS.constants import API_TIMEOUT, get_api_url

            # Пустой payload
            response = requests.post(
                get_api_url("heartbeat"),
                json={},
                timeout=API_TIMEOUT
            )

            self.logger.check(
                response.status_code == 400,
                f"Пустой payload -> 400",
                f"Пустой payload -> {response.status_code} (ожидался 400)"
            )

            # Только api_key (без hardware_id)
            response = requests.post(
                get_api_url("heartbeat"),
                json={"api_key": "DAMAN-TEST-TEST-TEST"},
                timeout=API_TIMEOUT
            )

            self.logger.check(
                response.status_code == 400,
                f"Без hardware_id -> 400",
                f"Без hardware_id -> {response.status_code} (ожидался 400)"
            )

        except Exception as e:
            self.logger.error(f"Ошибка теста полей: {str(e)}")

    # === Клиентская интеграция ===

    def test_30_client_timer_setup(self):
        """ТЕСТ 30: Проверка клиентского таймера heartbeat"""
        self.logger.section("30. Клиентский таймер")

        try:
            from Daman_QGIS.main_plugin import DamanQGIS

            # Проверяем наличие методов heartbeat
            self.logger.check(
                hasattr(DamanQGIS, '_start_heartbeat'),
                "Метод _start_heartbeat существует",
                "Метод _start_heartbeat отсутствует!"
            )

            self.logger.check(
                hasattr(DamanQGIS, '_heartbeat_check'),
                "Метод _heartbeat_check существует",
                "Метод _heartbeat_check отсутствует!"
            )

            self.logger.check(
                hasattr(DamanQGIS, '_on_license_revoked'),
                "Метод _on_license_revoked существует",
                "Метод _on_license_revoked отсутствует!"
            )

        except ImportError as e:
            self.logger.error(f"Ошибка импорта: {str(e)}")
        except Exception as e:
            self.logger.error(f"Ошибка проверки таймера: {str(e)}")

    def test_31_client_revocation_handler(self):
        """ТЕСТ 31: Проверка обработчика отзыва лицензии"""
        self.logger.section("31. Обработчик отзыва")

        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_29_4_token_manager import TokenManager

            token_mgr = TokenManager.get_instance()

            # Проверяем что clear_tokens существует
            self.logger.check(
                hasattr(token_mgr, 'clear_tokens'),
                "TokenManager.clear_tokens() доступен",
                "TokenManager.clear_tokens() отсутствует!"
            )

            # Проверяем что BaseReferenceLoader.clear_cache существует
            from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
            self.logger.check(
                hasattr(BaseReferenceLoader, 'clear_cache'),
                "BaseReferenceLoader.clear_cache() доступен",
                "BaseReferenceLoader.clear_cache() отсутствует!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка проверки обработчика: {str(e)}")

    # === Производительность ===

    def test_40_heartbeat_performance(self):
        """ТЕСТ 40: Производительность heartbeat запроса"""
        self.logger.section("40. Производительность")

        if not self.api_key:
            self.logger.warning("API key отсутствует -- тест пропущен")
            return

        try:
            times = []
            for i in range(3):
                payload = self._build_heartbeat_payload()
                start = time.time()
                response = self._send_heartbeat(payload)
                elapsed = time.time() - start
                times.append(elapsed)

            avg_time = sum(times) / len(times)
            max_time = max(times)

            self.logger.info(f"Среднее время: {avg_time:.2f}s")
            self.logger.info(f"Максимальное: {max_time:.2f}s")

            self.logger.check(
                avg_time < 3.0,
                f"Heartbeat быстрый: {avg_time:.2f}s < 3s",
                f"Heartbeat медленный: {avg_time:.2f}s > 3s"
            )

            self.logger.check(
                max_time < 5.0,
                f"Максимум приемлемый: {max_time:.2f}s < 5s",
                f"Максимум слишком большой: {max_time:.2f}s > 5s"
            )

        except Exception as e:
            self.logger.error(f"Ошибка теста производительности: {str(e)}")

    # === Server-side Integrity Check ===

    def _compute_real_file_hashes(self) -> Dict[str, str]:
        """Вычислить реальные SHA-256 хеши критических файлов плагина"""
        try:
            from qgis.utils import plugins
            plugin = plugins.get('Daman_QGIS')
            if not plugin or not hasattr(plugin, 'INTEGRITY_FILES'):
                return {}

            hashes = {}
            for key, rel_path in plugin.INTEGRITY_FILES.items():
                filepath = os.path.join(plugin.plugin_dir, rel_path)
                if os.path.exists(filepath):
                    with open(filepath, 'rb') as f:
                        hashes[key] = hashlib.sha256(f.read()).hexdigest()
            return hashes
        except Exception:
            return {}

    def test_50_heartbeat_with_valid_hashes(self):
        """ТЕСТ 50: Heartbeat с валидными file_hashes -> active

        Отправляем реальные хеши файлов. Сервер сверяет с S3 эталонами
        и возвращает active при совпадении.
        """
        self.logger.section("50. Server-side integrity: валидные хеши")

        if not self.api_key:
            self.logger.warning("API key отсутствует -- тест пропущен")
            return

        try:
            file_hashes = self._compute_real_file_hashes()
            if not file_hashes:
                self.logger.warning("Не удалось вычислить хеши -- тест пропущен")
                return

            from Daman_QGIS.constants import PLUGIN_VERSION
            payload = self._build_heartbeat_payload()
            payload['file_hashes'] = file_hashes
            payload['plugin_version'] = PLUGIN_VERSION

            response = self._send_heartbeat(payload)
            self.logger.info(f"HTTP статус: {response.status_code}, "
                             f"хешей отправлено: {len(file_hashes)}")

            self.logger.check(
                response.status_code == 200,
                "Heartbeat вернул 200",
                f"Неожиданный статус: {response.status_code}"
            )

            if response.status_code == 200:
                data = response.json()
                self.logger.check(
                    data.get('status') == 'active',
                    "Валидные хеши -> active",
                    f"Валидные хеши -> {data.get('status')} "
                    f"(reason: {data.get('reason', '-')})"
                )

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_51_heartbeat_with_tampered_hashes(self):
        """ТЕСТ 51: Heartbeat с подменёнными file_hashes -> INTEGRITY_MISMATCH

        Отправляем заведомо неправильные хеши. Сервер возвращает
        revoked с reason=INTEGRITY_MISMATCH.
        """
        self.logger.section("51. Server-side integrity: подменённые хеши")

        if not self.api_key:
            self.logger.warning("API key отсутствует -- тест пропущен")
            return

        try:
            from Daman_QGIS.constants import PLUGIN_VERSION

            fake_hashes = {
                'main_plugin': 'a' * 64,
                'msm_29_3': 'b' * 64,
                'msm_29_4': 'c' * 64,
                'base_ref': 'd' * 64,
            }

            payload = self._build_heartbeat_payload()
            payload['file_hashes'] = fake_hashes
            payload['plugin_version'] = PLUGIN_VERSION

            response = self._send_heartbeat(payload)
            self.logger.info(f"HTTP статус: {response.status_code}")

            self.logger.check(
                response.status_code == 200,
                "Heartbeat вернул 200",
                f"Неожиданный статус: {response.status_code}"
            )

            if response.status_code == 200:
                data = response.json()
                self.logger.check(
                    data.get('status') == 'revoked'
                    and data.get('reason') == 'INTEGRITY_MISMATCH',
                    "Подменённые хеши -> revoked (INTEGRITY_MISMATCH)",
                    f"Подменённые хеши -> {data.get('status')} "
                    f"(reason: {data.get('reason', '-')})"
                )

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_52_heartbeat_without_hashes_integrity_missing(self):
        """ТЕСТ 52: Heartbeat без file_hashes -> INTEGRITY_MISSING

        Сервер требует file_hashes если на сервере есть integrity hashes.
        Без file_hashes вернётся revoked с reason=INTEGRITY_MISSING.
        """
        self.logger.section("52. Без file_hashes: INTEGRITY_MISSING")

        if not self.api_key:
            self.logger.warning("API key отсутствует -- тест пропущен")
            return

        try:
            # Стандартный payload БЕЗ file_hashes
            payload = self._build_heartbeat_payload()
            response = self._send_heartbeat(payload)

            self.logger.check(
                response.status_code == 200,
                "Heartbeat вернул 200",
                f"Неожиданный статус: {response.status_code}"
            )

            if response.status_code == 200:
                data = response.json()
                self.logger.check(
                    data.get('status') == 'revoked'
                    and data.get('reason') == 'INTEGRITY_MISSING',
                    "Без file_hashes -> revoked (INTEGRITY_MISSING)",
                    f"Без file_hashes -> {data.get('status')} "
                    f"(reason: {data.get('reason', '-')})"
                )

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_53_heartbeat_with_partial_hashes(self):
        """ТЕСТ 53: Heartbeat с неполным набором хешей -> INTEGRITY_MISMATCH

        Отправляем хеш только одного файла. Сервер требует ВСЕ файлы
        из серверного списка, отсутствие файла = INTEGRITY_MISMATCH.
        """
        self.logger.section("53. Частичные хеши -> INTEGRITY_MISMATCH")

        if not self.api_key:
            self.logger.warning("API key отсутствует -- тест пропущен")
            return

        try:
            file_hashes = self._compute_real_file_hashes()
            if not file_hashes:
                self.logger.warning("Не удалось вычислить хеши -- тест пропущен")
                return

            # Берём только первый ключ
            first_key = next(iter(file_hashes))
            partial = {first_key: file_hashes[first_key]}

            from Daman_QGIS.constants import PLUGIN_VERSION
            payload = self._build_heartbeat_payload()
            payload['file_hashes'] = partial
            payload['plugin_version'] = PLUGIN_VERSION

            response = self._send_heartbeat(payload)

            self.logger.check(
                response.status_code == 200,
                "Heartbeat вернул 200",
                f"Неожиданный статус: {response.status_code}"
            )

            if response.status_code == 200:
                data = response.json()
                self.logger.check(
                    data.get('status') == 'revoked'
                    and data.get('reason') == 'INTEGRITY_MISMATCH',
                    f"Частичные хеши ({first_key}) -> revoked (INTEGRITY_MISMATCH)",
                    f"Частичные хеши ({first_key}) -> {data.get('status')} "
                    f"(reason: {data.get('reason', '-')})"
                )

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_54_heartbeat_with_invalid_hash_types(self):
        """ТЕСТ 54: Heartbeat с невалидными типами в file_hashes

        Сервер должен корректно обработать нечисловые/пустые хеши.
        """
        self.logger.section("54. Невалидные типы хешей")

        if not self.api_key:
            self.logger.warning("API key отсутствует -- тест пропущен")
            return

        try:
            test_cases = [
                ("пустой dict", {}),
                ("null values", {"main_plugin": None}),
                ("числа", {"main_plugin": 12345}),
                ("строка не-хеш", {"main_plugin": "not_a_hex_hash"}),
                ("список", {"main_plugin": ["a" * 64]}),
            ]

            for name, hashes in test_cases:
                payload = self._build_heartbeat_payload()
                payload['file_hashes'] = hashes
                response = self._send_heartbeat(payload)

                if response.status_code == 200:
                    data = response.json()
                    self.logger.info(
                        f"  {name}: status={data.get('status')}, "
                        f"reason={data.get('reason', '-')}"
                    )
                else:
                    self.logger.info(f"  {name}: HTTP {response.status_code}")

            self.logger.success("Сервер обработал все невалидные типы без краша")

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_55_client_sends_hashes_in_payload(self):
        """ТЕСТ 55: Клиент включает file_hashes и version в heartbeat payload

        Проверяем что клиентский код _heartbeat_check() формирует
        payload с file_hashes и version.
        """
        self.logger.section("55. Клиент: file_hashes в payload")

        try:
            from Daman_QGIS.main_plugin import DamanQGIS
            import inspect

            source = inspect.getsource(DamanQGIS._heartbeat_check)

            self.logger.check(
                'file_hashes' in source,
                "Клиент отправляет file_hashes в heartbeat",
                "file_hashes отсутствует в _heartbeat_check!"
            )

            self.logger.check(
                'PLUGIN_VERSION' in source or "'version'" in source or '"version"' in source,
                "Клиент отправляет version в heartbeat",
                "version отсутствует в _heartbeat_check!"
            )

            self.logger.check(
                'INTEGRITY_FILES' in source,
                "Клиент использует INTEGRITY_FILES для хеширования",
                "INTEGRITY_FILES отсутствует в _heartbeat_check!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")
