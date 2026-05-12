# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_heartbeat - Тестирование Heartbeat и License Revocation

Тестирует:
- Endpoint ?action=heartbeat доступность и формат ответа
- HMAC подпись heartbeat запросов
- Обработку статусов (active, revoked)
- Server-side integrity check (Phase B wire-contract: plugin_hash + plugin_version)
- Защиту от replay attacks (timestamp)
- Клиентскую интеграцию (таймер, константы)

ВНИМАНИЕ: Этот тест делает реальные сетевые запросы!
"""

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

            # Клиентская интеграция
            self.test_30_client_timer_setup()
            self.test_31_client_revocation_handler()

            # Производительность
            self.test_40_heartbeat_performance()

            # Phase B integrity wire-contract
            self.test_50_heartbeat_with_valid_hash()
            self.test_51_heartbeat_with_tampered_hash()
            self.test_55_client_sends_hash_in_payload()

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

    def _compute_real_plugin_hash(self) -> Optional[str]:
        """Вычислить реальный SHA-256 дерева файлов плагина (Phase B contract)."""
        try:
            from qgis.utils import plugins
            plugin = plugins.get('Daman_QGIS')
            if not plugin or not hasattr(plugin, 'plugin_dir'):
                return None
            from Daman_QGIS.integrity_hash import compute_plugin_hash
            return compute_plugin_hash(plugin.plugin_dir)
        except Exception:
            return None

    def _build_heartbeat_payload(self, api_key: Optional[str] = None,
                                  hardware_id: Optional[str] = None,
                                  timestamp: Optional[int] = None,
                                  signature: Optional[str] = None,
                                  include_integrity: bool = True) -> Dict[str, Any]:
        """Построить payload для heartbeat запроса.

        Phase A.1 server STRICT requires plugin_version + plugin_hash.
        include_integrity=False — для негативных тестов.
        """
        _api_key = api_key if api_key is not None else self.api_key
        _hardware_id = hardware_id if hardware_id is not None else self.hardware_id
        _timestamp = timestamp if timestamp is not None else int(time.time())

        if signature is None and _api_key and _hardware_id:
            signature = hmac.new(
                _api_key.encode('utf-8'),
                f"{_hardware_id}|{_timestamp}".encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

        payload: Dict[str, Any] = {
            "api_key": _api_key or "",
            "hardware_id": _hardware_id or "",
            "timestamp": _timestamp,
            "signature": signature or ""
        }

        if include_integrity:
            from Daman_QGIS.constants import PLUGIN_VERSION
            payload["plugin_version"] = PLUGIN_VERSION
            real_hash = self._compute_real_plugin_hash()
            if real_hash:
                payload["plugin_hash"] = real_hash

        return payload

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

            # Phase B: mark_update_pending для INTEGRITY_MISMATCH
            self.logger.check(
                hasattr(token_mgr, 'mark_update_pending'),
                "TokenManager.mark_update_pending() доступен (Phase B)",
                "mark_update_pending() отсутствует — Phase B integrity refactor не применён"
            )

            self.logger.check(
                hasattr(token_mgr, 'is_update_pending'),
                "TokenManager.is_update_pending() доступен (Phase B)",
                "is_update_pending() отсутствует — Phase B integrity refactor не применён"
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
            for _ in range(3):
                payload = self._build_heartbeat_payload()
                start = time.time()
                self._send_heartbeat(payload)
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

    # === Phase B integrity wire-contract ===

    def test_50_heartbeat_with_valid_hash(self):
        """ТЕСТ 50: Heartbeat с валидным plugin_hash -> active

        Phase B wire-contract: payload включает plugin_version + plugin_hash.
        Сервер сверяет plugin_hash с эталоном из integrity registry,
        совпадение -> active.
        """
        self.logger.section("50. Phase B: валидный plugin_hash -> active")

        if not self.api_key:
            self.logger.warning("API key отсутствует -- тест пропущен")
            return

        try:
            real_hash = self._compute_real_plugin_hash()
            if not real_hash:
                self.logger.warning("Не удалось вычислить plugin_hash -- тест пропущен")
                return

            payload = self._build_heartbeat_payload()
            response = self._send_heartbeat(payload)

            self.logger.info(
                f"HTTP статус: {response.status_code}, "
                f"plugin_hash отправлен: {real_hash[:16]}..."
            )

            self.logger.check(
                response.status_code == 200,
                "Heartbeat вернул 200",
                f"Неожиданный статус: {response.status_code}"
            )

            if response.status_code == 200:
                data = response.json()
                self.logger.check(
                    data.get('status') == 'active',
                    "Валидный plugin_hash -> active",
                    f"Валидный plugin_hash -> {data.get('status')} "
                    f"(reason: {data.get('reason', '-')})"
                )

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_51_heartbeat_with_tampered_hash(self):
        """ТЕСТ 51: Heartbeat с подменённым plugin_hash -> INTEGRITY_MISMATCH

        Phase B wire-contract: подменяем plugin_hash на заведомо неправильный,
        сервер возвращает revoked с reason=INTEGRITY_MISMATCH.

        ВАЖНО: используем BETA channel (фиксированная версия), не PLUGIN_VERSION.
        DEV channel mismatch by Phase A.1 design возвращает active (silent —
        developer self-syncs через `daman deploy`, не ломаем рабочую сессию).
        Enforcement path тестируется на beta/stable.
        """
        self.logger.section("51. Phase B: подменённый plugin_hash")

        if not self.api_key:
            self.logger.warning("API key отсутствует -- тест пропущен")
            return

        try:
            payload = self._build_heartbeat_payload(include_integrity=False)
            # Beta channel: server возвращает revoked + INTEGRITY_MISMATCH
            payload['plugin_version'] = '0.9.960-beta.1'
            payload['plugin_hash'] = 'a' * 64  # заведомо не совпадает

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
                    "Подменённый plugin_hash -> revoked (INTEGRITY_MISMATCH)",
                    f"Подменённый plugin_hash -> {data.get('status')} "
                    f"(reason: {data.get('reason', '-')})"
                )

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")

    def test_55_client_sends_hash_in_payload(self):
        """ТЕСТ 55: Клиент включает plugin_hash и plugin_version в heartbeat payload

        Проверяем что клиентский код _heartbeat_check() формирует
        payload с plugin_hash и plugin_version (Phase B wire-contract).
        """
        self.logger.section("55. Клиент: plugin_hash в payload")

        try:
            from Daman_QGIS.main_plugin import DamanQGIS
            import inspect

            source = inspect.getsource(DamanQGIS._heartbeat_check)

            self.logger.check(
                'plugin_hash' in source,
                "Клиент отправляет plugin_hash в heartbeat",
                "plugin_hash отсутствует в _heartbeat_check!"
            )

            self.logger.check(
                'PLUGIN_VERSION' in source or 'plugin_version' in source,
                "Клиент отправляет plugin_version в heartbeat",
                "plugin_version отсутствует в _heartbeat_check!"
            )

            # FIX-5 (review 2026-05-09): _heartbeat_check теперь использует
            # module-level cache get_cached_or_compute (saves ~200ms × N
            # heartbeats/day). Принимаем любую из двух функций.
            uses_hash_fn = (
                'get_cached_or_compute' in source
                or 'compute_plugin_hash' in source
            )
            self.logger.check(
                uses_hash_fn,
                "Клиент использует integrity_hash функцию для хеширования",
                "Ни get_cached_or_compute, ни compute_plugin_hash "
                "не найдены в _heartbeat_check!"
            )

            self.logger.check(
                'mark_update_pending' in source,
                "Клиент обрабатывает INTEGRITY_MISMATCH через mark_update_pending",
                "mark_update_pending отсутствует — INTEGRITY_MISMATCH не обработан"
            )

        except Exception as e:
            self.logger.error(f"Ошибка теста: {str(e)}")
