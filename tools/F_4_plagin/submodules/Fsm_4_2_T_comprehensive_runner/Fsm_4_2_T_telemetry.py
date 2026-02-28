# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_telemetry - Тесты для системы телеметрии.

Тестирует:
- M_32_TelemetryManager - клиентская часть
- API endpoint ?action=telemetry - серверная часть
- Санитизация данных
- Батчинг и отправка
"""

import time
from typing import Dict, Any, List, Optional


class TelemetryTests:
    """Тесты системы телеметрии."""

    def __init__(self, iface, logger):
        """
        Инициализация теста

        Args:
            iface: QGIS interface
            logger: TestLogger instance
        """
        self.iface = iface
        self.logger = logger
        self._session = None

    def _get_session(self):
        """Ленивая инициализация requests session."""
        if self._session is None:
            try:
                import requests
                self._session = requests.Session()
            except ImportError:
                pass
        return self._session

    def run_all_tests(self):
        """Запуск всех тестов телеметрии."""
        self.logger.section("ТЕСТ: Система телеметрии (M_32)")

        # API тесты
        self.test_api_basic_event()
        self.test_api_batch_events()
        self.test_api_missing_uid()
        self.test_api_missing_events()
        self.test_api_too_many_events()

        # Клиентские тесты
        self.test_manager_init()
        self.test_manager_track_event()
        self.test_manager_track_error()

        # Sanitize тесты
        self.test_sanitize_paths()
        self.test_sanitize_long_strings()

        # Decorator тест
        self.test_track_function_decorator()

        self.logger.summary()

    # ==================== API тесты ====================

    def test_api_basic_event(self):
        """Тест базовой отправки события через API."""
        self.logger.section("API: базовая отправка события")

        try:
            from Daman_QGIS.constants import API_BASE_URL, API_TIMEOUT
        except ImportError:
            self.logger.skip("constants не доступны")
            return

        session = self._get_session()
        if not session:
            self.logger.skip("requests library not available")
            return

        url = f"{API_BASE_URL}?action=telemetry"
        payload = {
            "uid": "DAMAN-TEST-XXXX-XXXX",
            "hardware_id": "TEST-HARDWARE-ID-12345",
            "events": [
                {
                    "ts": int(time.time()),
                    "v": "0.9.67",
                    "qgis": "3.40.1",
                    "os": "win",
                    "py": "3.12",
                    "event": "test_event",
                    "data": {"test": True}
                }
            ]
        }

        try:
            response = session.post(url, json=payload, timeout=API_TIMEOUT)

            if response.status_code != 200:
                self.logger.fail(f"HTTP {response.status_code}: {response.text}")
                return

            data = response.json()

            if data.get("status") != "success":
                self.logger.fail(f"Unexpected status: {data}")
                return

            saved = data.get("saved", 0)
            if saved != 1:
                self.logger.fail(f"Expected 1 saved event, got {saved}")
                return

            self.logger.success(f"Event saved successfully")

        except Exception as e:
            self.logger.fail(f"Request failed: {e}")

    def test_api_batch_events(self):
        """Тест отправки batch событий."""
        self.logger.section("API: отправка batch событий")

        try:
            from Daman_QGIS.constants import API_BASE_URL, API_TIMEOUT
        except ImportError:
            self.logger.skip("constants не доступны")
            return

        session = self._get_session()
        if not session:
            self.logger.skip("requests library not available")
            return

        url = f"{API_BASE_URL}?action=telemetry"

        # Создаём batch из 10 событий
        events = []
        for i in range(10):
            events.append({
                "ts": int(time.time()),
                "v": "0.9.67",
                "event": f"batch_test_{i}",
                "data": {"index": i}
            })

        payload = {
            "uid": "DAMAN-TEST-BATCH-XXX",
            "hardware_id": "TEST-HARDWARE-BATCH",
            "events": events
        }

        try:
            response = session.post(url, json=payload, timeout=API_TIMEOUT)

            if response.status_code != 200:
                self.logger.fail(f"HTTP {response.status_code}")
                return

            data = response.json()
            saved = data.get("saved", 0)

            if saved != 10:
                self.logger.fail(f"Expected 10 saved, got {saved}")
                return

            self.logger.success(f"Batch of {saved} events saved")

        except Exception as e:
            self.logger.fail(f"Request failed: {e}")

    def test_api_missing_uid(self):
        """Тест ошибки при отсутствии uid."""
        self.logger.section("API: ошибка при отсутствии uid")

        try:
            from Daman_QGIS.constants import API_BASE_URL, API_TIMEOUT
        except ImportError:
            self.logger.skip("constants не доступны")
            return

        session = self._get_session()
        if not session:
            self.logger.skip("requests library not available")
            return

        url = f"{API_BASE_URL}?action=telemetry"
        payload = {
            "events": [{"ts": int(time.time()), "event": "test"}]
        }

        try:
            response = session.post(url, json=payload, timeout=API_TIMEOUT)

            if response.status_code != 400:
                self.logger.fail(f"Expected 400, got {response.status_code}")
                return

            data = response.json()
            if data.get("error_code") != "MISSING_UID":
                self.logger.fail(f"Expected MISSING_UID error, got {data}")
                return

            self.logger.success("Correctly rejected missing uid")

        except Exception as e:
            self.logger.fail(f"Request failed: {e}")

    def test_api_missing_events(self):
        """Тест ошибки при отсутствии events."""
        self.logger.section("API: ошибка при отсутствии events")

        try:
            from Daman_QGIS.constants import API_BASE_URL, API_TIMEOUT
        except ImportError:
            self.logger.skip("constants не доступны")
            return

        session = self._get_session()
        if not session:
            self.logger.skip("requests library not available")
            return

        url = f"{API_BASE_URL}?action=telemetry"
        payload = {
            "uid": "TEST-NOEVENTS"
        }

        try:
            response = session.post(url, json=payload, timeout=API_TIMEOUT)

            if response.status_code != 400:
                self.logger.fail(f"Expected 400, got {response.status_code}")
                return

            data = response.json()
            if data.get("error_code") != "MISSING_EVENTS":
                self.logger.fail(f"Expected MISSING_EVENTS error, got {data}")
                return

            self.logger.success("Correctly rejected missing events")

        except Exception as e:
            self.logger.fail(f"Request failed: {e}")

    def test_api_too_many_events(self):
        """Тест ограничения на количество событий."""
        self.logger.section("API: ограничение на количество событий")

        try:
            from Daman_QGIS.constants import API_BASE_URL, API_TIMEOUT
        except ImportError:
            self.logger.skip("constants не доступны")
            return

        session = self._get_session()
        if not session:
            self.logger.skip("requests library not available")
            return

        url = f"{API_BASE_URL}?action=telemetry"

        # Создаём 150 событий (лимит 100)
        events = [{"ts": int(time.time()), "event": f"test_{i}"} for i in range(150)]

        payload = {
            "uid": "DAMAN-TEST-TOOMANY",
            "hardware_id": "TEST-HARDWARE-TOOMANY",
            "events": events
        }

        try:
            response = session.post(url, json=payload, timeout=API_TIMEOUT)

            if response.status_code != 400:
                self.logger.fail(f"Expected 400, got {response.status_code}")
                return

            data = response.json()
            if data.get("error_code") != "TOO_MANY_EVENTS":
                self.logger.fail(f"Expected TOO_MANY_EVENTS error, got {data}")
                return

            self.logger.success("Correctly rejected too many events")

        except Exception as e:
            self.logger.fail(f"Request failed: {e}")

    # ==================== Manager тесты ====================

    def test_manager_init(self):
        """Тест инициализации TelemetryManager."""
        self.logger.section("Manager: инициализация")

        try:
            from Daman_QGIS.managers import registry
        except ImportError:
            self.logger.skip("managers не доступны")
            return

        # Сбрасываем для чистого теста
        registry.reset('M_32')

        manager = registry.get('M_32')

        if manager is None:
            self.logger.fail("Manager is None")
            return

        # Проверяем атрибуты
        if not hasattr(manager, '_events'):
            self.logger.fail("Missing _events attribute")
            return

        if not hasattr(manager, '_system_info'):
            self.logger.fail("Missing _system_info attribute")
            return

        # Проверяем system_info
        info = manager._system_info
        required_fields = ['v', 'qgis', 'os', 'py']
        for field in required_fields:
            if field not in info:
                self.logger.fail(f"Missing {field} in system_info")
                return

        self.logger.success(f"Manager initialized: {info}")

    def test_manager_track_event(self):
        """Тест track_event."""
        self.logger.section("Manager: track_event")

        try:
            from Daman_QGIS.managers import registry
        except ImportError:
            self.logger.skip("managers не доступны")
            return

        registry.reset('M_32')
        manager = registry.get('M_32')

        # Используем тип события 'error' который всегда проходит фильтр TELEMETRY_LEVEL
        # (события типа 'test_event' фильтруются при SAMPLING level)
        manager.track_event('error', {'key': 'value', 'error_type': 'TestError', 'error_msg': 'test'})

        # Проверяем что событие добавлено
        if len(manager._events) != 1:
            self.logger.fail(f"Expected 1 event, got {len(manager._events)}")
            return

        event = manager._events[0]

        if event.get('event') != 'error':
            self.logger.fail(f"Wrong event type: {event.get('event')}")
            return

        if 'data' not in event:
            self.logger.fail("Missing data in event")
            return

        if event['data'].get('key') != 'value':
            self.logger.fail("Data not preserved")
            return

        self.logger.success("Event tracked correctly")

    def test_manager_track_error(self):
        """Тест track_error."""
        self.logger.section("Manager: track_error")

        try:
            from Daman_QGIS.managers import registry
        except ImportError:
            self.logger.skip("managers не доступны")
            return

        registry.reset('M_32')
        manager = registry.get('M_32')

        # Создаём исключение с traceback
        try:
            raise ValueError("Test error message")
        except Exception as e:
            manager.track_error('F_1_1', e, {'step': 'testing'})

        # Проверяем событие
        if len(manager._events) != 1:
            self.logger.fail(f"Expected 1 event, got {len(manager._events)}")
            return

        event = manager._events[0]

        if event.get('event') != 'error':
            self.logger.fail(f"Wrong event type: {event.get('event')}")
            return

        data = event.get('data', {})

        if data.get('error_type') != 'ValueError':
            self.logger.fail(f"Wrong error_type: {data.get('error_type')}")
            return

        if 'Test error message' not in data.get('error_msg', ''):
            self.logger.fail("Error message not captured")
            return

        if 'stack' not in data:
            self.logger.fail("Stack trace not captured")
            return

        self.logger.success("Error tracked with stack trace")

    # ==================== Sanitize тесты ====================

    def test_sanitize_paths(self):
        """Тест замены путей на [PATH]."""
        self.logger.section("Sanitize: замена путей")

        try:
            from Daman_QGIS.managers import registry
        except ImportError:
            self.logger.skip("managers не доступны")
            return

        registry.reset('M_32')
        manager = registry.get('M_32')

        test_data = {
            'file': 'C:\\Users\\TestUser\\Documents\\project.qgs',
            'unix_path': '/home/user/projects/test.gpkg',
            'normal_string': 'This is a normal string',
            'number': 42
        }

        sanitized = manager._sanitize_data(test_data)

        if sanitized.get('file') != '[PATH]':
            self.logger.fail(f"Windows path not sanitized: {sanitized.get('file')}")
            return

        if sanitized.get('unix_path') != '[PATH]':
            self.logger.fail(f"Unix path not sanitized: {sanitized.get('unix_path')}")
            return

        if sanitized.get('normal_string') != 'This is a normal string':
            self.logger.fail("Normal string incorrectly modified")
            return

        if sanitized.get('number') != 42:
            self.logger.fail("Number incorrectly modified")
            return

        self.logger.success("Paths sanitized correctly")

    def test_sanitize_long_strings(self):
        """Тест обрезки длинных строк."""
        self.logger.section("Sanitize: обрезка длинных строк")

        try:
            from Daman_QGIS.managers import registry
        except ImportError:
            self.logger.skip("managers не доступны")
            return

        registry.reset('M_32')
        manager = registry.get('M_32')

        long_string = "A" * 500  # 500 символов

        test_data = {
            'long': long_string,
            'short': 'short string'
        }

        sanitized = manager._sanitize_data(test_data)

        if len(sanitized.get('long', '')) > 210:  # 200 + "..."
            self.logger.fail(f"Long string not truncated: {len(sanitized.get('long'))}")
            return

        if '...' not in sanitized.get('long', ''):
            self.logger.fail("Truncation marker missing")
            return

        if sanitized.get('short') != 'short string':
            self.logger.fail("Short string incorrectly modified")
            return

        self.logger.success("Long strings truncated correctly")

    def test_track_function_decorator(self):
        """Тест декоратора track_function."""
        self.logger.section("Decorator: track_function")

        try:
            from Daman_QGIS.managers import registry, track_function
        except ImportError:
            self.logger.skip("managers не доступны")
            return

        registry.reset('M_32')
        manager = registry.get('M_32')
        manager.set_uid("DAMAN-TEST-DECORATOR-XX", "TEST-HARDWARE-DECORATOR")

        # Создаём тестовую функцию которая бросает исключение
        # (error события всегда отправляются при любом TELEMETRY_LEVEL)
        @track_function("F_TEST")
        def test_func_error():
            raise ValueError("Test error")

        # Вызываем функцию, ожидаем исключение
        try:
            test_func_error()
            self.logger.fail("Expected exception was not raised")
            return
        except ValueError:
            pass  # Ожидаемое поведение

        # Проверяем события - при SAMPLING уровне:
        # - function_start НЕ отправляется
        # - function_end НЕ отправляется (фильтруется при success=False для SAMPLING)
        # - error ВСЕГДА отправляется
        events = manager._events

        # Ищем событие error
        error_events = [e for e in events if e.get('event') == 'error']

        if len(error_events) < 1:
            self.logger.fail(f"Expected at least 1 error event, got {len(error_events)}")
            return

        error_event = error_events[0]
        error_data = error_event.get('data', {})

        if error_data.get('func') != 'F_TEST':
            self.logger.fail(f"Wrong function ID: {error_data.get('func')}")
            return

        if error_data.get('error_type') != 'ValueError':
            self.logger.fail(f"Wrong error type: {error_data.get('error_type')}")
            return

        self.logger.success(f"Decorator works, error tracked correctly")
