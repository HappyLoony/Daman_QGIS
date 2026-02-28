# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_40 - Тесты M_40 NspdAuthManager

Проверяет:
- Msm_40_2_CookieStore: set/get/clear, thread safety
- NspdAuthManager: инициализация, API, inject_cookies, logout, сигналы
- Инъекция cookies в requests.Session
- Интеграция: statusbar widget, cleanup

НЕ тестирует (требует ручного ввода):
- Реальную авторизацию через Госуслуги
- QWebEngineView cookie interception
"""

import threading
import time
from typing import Any, List


class TestM40:
    """Тесты M_40 NspdAuthManager и субменеджеров"""

    def __init__(self, iface: Any, logger: Any) -> None:
        self.iface = iface
        self.logger = logger

    def run_all_tests(self) -> None:
        """Entry point for comprehensive runner"""
        self.logger.section("M_40: NspdAuthManager")

        try:
            # 1. CookieStore unit tests
            self.test_01_cookie_store_init()
            self.test_02_cookie_store_set_get()
            self.test_03_cookie_store_clear()
            self.test_04_cookie_store_thread_safety()

            # 2. NspdAuthManager initialization
            self.test_10_manager_registry()
            self.test_11_manager_api_methods()
            self.test_12_webengine_availability()

            # 3. Auth workflow (без реального браузера)
            self.test_20_initial_state()
            self.test_21_manual_cookie_injection()
            self.test_22_logout()
            self.test_23_signal_emission()

            # 4. Session injection
            self.test_30_inject_empty_session()
            self.test_31_inject_with_cookies()

            # 5. Integration
            self.test_40_statusbar_widget()
            self.test_41_cleanup()

            # 6. Edge CDP (Msm_40_3)
            self.test_50_edge_detection()
            self.test_51_is_available_with_edge()
            self.test_52_free_port()
            self.test_53_cookie_domain_filtering()

        except Exception as e:
            self.logger.error(f"Fsm_4_2_T_40: Критическая ошибка: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    # =========================================================================
    # 1. CookieStore unit tests
    # =========================================================================

    def test_01_cookie_store_init(self) -> None:
        """TEST 1: CookieStore -- начальное состояние"""
        self.logger.section("1. CookieStore: начальное состояние")

        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_40_2_cookie_store import (
                Msm_40_2_CookieStore
            )

            store = Msm_40_2_CookieStore()

            self.logger.check(
                not store.is_valid(),
                "Пустой store: is_valid() = False",
                "Пустой store: is_valid() должен быть False!"
            )

            self.logger.check(
                store.get_cookies() == {},
                "Пустой store: get_cookies() = {}",
                f"Пустой store: get_cookies() не пуст: {store.get_cookies()}"
            )

            self.logger.check(
                store.get_cookie_count() == 0,
                "Пустой store: get_cookie_count() = 0",
                f"Пустой store: get_cookie_count() != 0: {store.get_cookie_count()}"
            )

        except Exception as e:
            self.logger.error(f"CookieStore init: {e}")

    def test_02_cookie_store_set_get(self) -> None:
        """TEST 2: CookieStore -- set/get"""
        self.logger.section("2. CookieStore: set/get")

        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_40_2_cookie_store import (
                Msm_40_2_CookieStore
            )

            store = Msm_40_2_CookieStore()
            test_cookies = {'session_id': 'abc123', 'token': 'xyz789', 'user': 'test'}

            store.set_cookies(test_cookies)

            self.logger.check(
                store.is_valid(),
                "После set: is_valid() = True",
                "После set: is_valid() должен быть True!"
            )

            self.logger.check(
                store.get_cookie_count() == 3,
                "После set: get_cookie_count() = 3",
                f"После set: get_cookie_count() = {store.get_cookie_count()}, ожидалось 3"
            )

            retrieved = store.get_cookies()

            self.logger.check(
                retrieved == test_cookies,
                "get_cookies() возвращает корректные данные",
                f"get_cookies() не совпадает: {retrieved}"
            )

            # Проверка что возвращается копия (иммутабельность)
            retrieved['hack'] = 'injected'

            self.logger.check(
                store.get_cookie_count() == 3,
                "get_cookies() возвращает копию (оригинал не изменён)",
                "get_cookies() вернул ссылку вместо копии!"
            )

        except Exception as e:
            self.logger.error(f"CookieStore set/get: {e}")

    def test_03_cookie_store_clear(self) -> None:
        """TEST 3: CookieStore -- clear"""
        self.logger.section("3. CookieStore: clear")

        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_40_2_cookie_store import (
                Msm_40_2_CookieStore
            )

            store = Msm_40_2_CookieStore()
            store.set_cookies({'a': '1', 'b': '2'})
            store.clear()

            self.logger.check(
                not store.is_valid(),
                "После clear: is_valid() = False",
                "После clear: is_valid() должен быть False!"
            )

            self.logger.check(
                store.get_cookie_count() == 0,
                "После clear: get_cookie_count() = 0",
                f"После clear: get_cookie_count() = {store.get_cookie_count()}"
            )

        except Exception as e:
            self.logger.error(f"CookieStore clear: {e}")

    def test_04_cookie_store_thread_safety(self) -> None:
        """TEST 4: CookieStore -- thread safety"""
        self.logger.section("4. CookieStore: thread safety")

        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_40_2_cookie_store import (
                Msm_40_2_CookieStore
            )

            store = Msm_40_2_CookieStore()
            errors: List[str] = []
            iterations = 100

            def writer(thread_id: int) -> None:
                """Параллельная запись cookies"""
                try:
                    for i in range(iterations):
                        store.set_cookies({f'key_{thread_id}_{i}': f'val_{i}'})
                except Exception as e:
                    errors.append(f"Writer {thread_id}: {e}")

            def reader(thread_id: int) -> None:
                """Параллельное чтение cookies"""
                try:
                    for _ in range(iterations):
                        _ = store.get_cookies()
                        _ = store.is_valid()
                        _ = store.get_cookie_count()
                except Exception as e:
                    errors.append(f"Reader {thread_id}: {e}")

            threads = []
            for i in range(2):
                threads.append(threading.Thread(target=writer, args=(i,)))
            for i in range(2):
                threads.append(threading.Thread(target=reader, args=(i,)))

            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            self.logger.check(
                len(errors) == 0,
                f"Thread safety: 4 потока x {iterations} итераций без ошибок",
                f"Thread safety: {len(errors)} ошибок: {errors[:3]}"
            )

            # Проверяем что ни один поток не завис
            alive = [t for t in threads if t.is_alive()]
            self.logger.check(
                len(alive) == 0,
                "Все потоки завершились (нет deadlock)",
                f"Deadlock: {len(alive)} потоков ещё работают!"
            )

        except Exception as e:
            self.logger.error(f"CookieStore thread safety: {e}")

    # =========================================================================
    # 2. NspdAuthManager initialization
    # =========================================================================

    def test_10_manager_registry(self) -> None:
        """TEST 10: M_40 доступен через registry"""
        self.logger.section("10. M_40: registry")

        try:
            from Daman_QGIS.managers import registry

            nspd_auth = registry.get('M_40')

            self.logger.check(
                nspd_auth is not None,
                "M_40 зарегистрирован в registry",
                "M_40 не найден в registry!"
            )

        except Exception as e:
            self.logger.error(f"M_40 registry: {e}")

    def test_11_manager_api_methods(self) -> None:
        """TEST 11: M_40 -- наличие API методов"""
        self.logger.section("11. M_40: API методы")

        try:
            from Daman_QGIS.managers import registry

            nspd_auth = registry.get('M_40')
            if not nspd_auth:
                self.logger.skip("M_40 недоступен -- пропуск")
                return

            required_methods = [
                'is_available', 'is_authenticated', 'get_cookies',
                'login', 'logout', 'inject_cookies', 'cleanup'
            ]

            for method_name in required_methods:
                self.logger.check(
                    hasattr(nspd_auth, method_name) and callable(getattr(nspd_auth, method_name)),
                    f"Метод {method_name}() присутствует",
                    f"Метод {method_name}() отсутствует!"
                )

            # Проверка сигнала
            self.logger.check(
                hasattr(nspd_auth, 'auth_changed'),
                "Сигнал auth_changed присутствует",
                "Сигнал auth_changed отсутствует!"
            )

        except Exception as e:
            self.logger.error(f"M_40 API methods: {e}")

    def test_12_webengine_availability(self) -> None:
        """TEST 12: Проверка доступности авторизации (QWebEngine или Edge)"""
        self.logger.section("12. Доступность авторизации")

        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_40_1_auth_browser_dialog import (
                is_webengine_available
            )
            from Daman_QGIS.managers.infrastructure.submodules.Msm_40_3_edge_auth import (
                is_edge_available
            )

            webengine = is_webengine_available()
            edge = is_edge_available()

            if webengine:
                self.logger.success("QWebEngine доступен")
            else:
                self.logger.warning("QWebEngine недоступен")

            if edge:
                self.logger.success("Edge CDP доступен")
            else:
                self.logger.warning("Edge CDP недоступен")

            expected_available = webengine or edge

            # Проверяем что is_available() менеджера совпадает
            from Daman_QGIS.managers import registry
            nspd_auth = registry.get('M_40')
            if nspd_auth:
                self.logger.check(
                    nspd_auth.is_available() == expected_available,
                    f"M_40.is_available()={nspd_auth.is_available()} == "
                    f"(webengine={webengine} or edge={edge})",
                    f"Рассогласование: M_40.is_available()={nspd_auth.is_available()}, "
                    f"ожидалось {expected_available}"
                )

        except Exception as e:
            self.logger.error(f"Availability check: {e}")

    # =========================================================================
    # 3. Auth workflow
    # =========================================================================

    def test_20_initial_state(self) -> None:
        """TEST 20: Начальное состояние авторизации"""
        self.logger.section("20. Начальное состояние")

        try:
            from Daman_QGIS.managers import registry

            nspd_auth = registry.get('M_40')
            if not nspd_auth:
                self.logger.skip("M_40 недоступен -- пропуск")
                return

            # Методы не должны выбрасывать исключений
            is_auth = nspd_auth.is_authenticated()
            cookies = nspd_auth.get_cookies()

            self.logger.check(
                isinstance(is_auth, bool),
                f"is_authenticated() возвращает bool: {is_auth}",
                f"is_authenticated() вернул не bool: {type(is_auth)}"
            )

            self.logger.check(
                isinstance(cookies, dict),
                f"get_cookies() возвращает dict ({len(cookies)} cookies)",
                f"get_cookies() вернул не dict: {type(cookies)}"
            )

        except Exception as e:
            self.logger.error(f"Initial state: {e}")

    def test_21_manual_cookie_injection(self) -> None:
        """TEST 21: Ручная инъекция cookies через CookieStore"""
        self.logger.section("21. Ручная инъекция cookies")

        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_40_2_cookie_store import (
                Msm_40_2_CookieStore
            )

            # Создаём отдельный store для изолированного теста
            store = Msm_40_2_CookieStore()

            self.logger.check(
                not store.is_valid(),
                "Пустой store: не авторизован",
                "Пустой store должен быть невалидным!"
            )

            store.set_cookies({
                'JSESSIONID': 'test_session_123',
                'nspd_token': 'test_token_456',
                'esia_auth': 'gosuslugi_789'
            })

            self.logger.check(
                store.is_valid(),
                "После инъекции: store валиден",
                "После инъекции: store должен быть валидным!"
            )

            self.logger.check(
                store.get_cookie_count() == 3,
                "3 cookies в store",
                f"Неверное количество cookies: {store.get_cookie_count()}"
            )

        except Exception as e:
            self.logger.error(f"Manual cookie injection: {e}")

    def test_22_logout(self) -> None:
        """TEST 22: Logout очищает cookies (изолированный экземпляр)"""
        self.logger.section("22. Logout")

        try:
            from Daman_QGIS.managers.infrastructure.M_40_nspd_auth_manager import NspdAuthManager

            # Изолированный экземпляр -- НЕ трогаем синглтон из registry
            manager = NspdAuthManager()

            # Инъецируем тестовые cookies
            manager._cookie_store.set_cookies({'test': 'logout_test'})

            self.logger.check(
                manager.is_authenticated(),
                "До logout: is_authenticated() = True",
                "До logout: cookies не сохранились!"
            )

            manager.logout()

            self.logger.check(
                not manager.is_authenticated(),
                "После logout: is_authenticated() = False",
                "После logout: cookies не очищены!"
            )

            manager.cleanup()

        except Exception as e:
            self.logger.error(f"Logout: {e}")

    def test_23_signal_emission(self) -> None:
        """TEST 23: Сигнал auth_changed эмитируется (изолированный экземпляр)"""
        self.logger.section("23. Сигнал auth_changed")

        try:
            from Daman_QGIS.managers.infrastructure.M_40_nspd_auth_manager import NspdAuthManager

            # Изолированный экземпляр -- НЕ трогаем синглтон из registry
            manager = NspdAuthManager()

            # Трекер сигналов
            signal_log: List[bool] = []

            def on_auth_changed(is_auth: bool) -> None:
                signal_log.append(is_auth)

            manager.auth_changed.connect(on_auth_changed)

            try:
                # Инъекция -> не эмитирует (напрямую через store)
                manager._cookie_store.set_cookies({'signal_test': '1'})

                # Logout -> эмитирует auth_changed(False)
                manager.logout()

                self.logger.check(
                    len(signal_log) >= 1 and signal_log[-1] is False,
                    "logout() эмитировал auth_changed(False)",
                    f"Сигнал не получен или неверный: {signal_log}"
                )

            finally:
                manager.auth_changed.disconnect(on_auth_changed)
                manager.cleanup()

        except Exception as e:
            self.logger.error(f"Signal emission: {e}")

    # =========================================================================
    # 4. Session injection
    # =========================================================================

    def test_30_inject_empty_session(self) -> None:
        """TEST 30: inject_cookies в пустую session (store пуст)"""
        self.logger.section("30. inject_cookies: пустой store")

        try:
            import requests

            from Daman_QGIS.managers.infrastructure.M_40_nspd_auth_manager import NspdAuthManager

            # Создаём изолированный менеджер
            manager = NspdAuthManager()
            session = requests.Session()

            manager.inject_cookies(session)

            cookie_count = len(session.cookies)
            self.logger.check(
                cookie_count == 0,
                "Пустой store: session.cookies пуст",
                f"Пустой store: session содержит {cookie_count} cookies!"
            )

            # Cleanup
            manager.cleanup()

        except Exception as e:
            self.logger.error(f"Inject empty session: {e}")

    def test_31_inject_with_cookies(self) -> None:
        """TEST 31: inject_cookies с заполненным store"""
        self.logger.section("31. inject_cookies: с cookies")

        try:
            import requests

            from Daman_QGIS.managers.infrastructure.M_40_nspd_auth_manager import NspdAuthManager

            manager = NspdAuthManager()
            session = requests.Session()

            # Заполняем store
            test_cookies = {
                'JSESSIONID': 'abc123',
                'nspd_session': 'def456',
                'esia_auth': 'ghi789'
            }
            manager._cookie_store.set_cookies(test_cookies)

            manager.inject_cookies(session)

            # Проверяем что cookies попали в session
            session_cookies = {c.name: c.value for c in session.cookies}

            self.logger.check(
                len(session_cookies) == 3,
                f"3 cookies инъецированы в session",
                f"Неверное количество cookies: {len(session_cookies)}"
            )

            for name, value in test_cookies.items():
                self.logger.check(
                    session_cookies.get(name) == value,
                    f"Cookie {name} = корректное значение",
                    f"Cookie {name}: ожидалось '{value}', получено '{session_cookies.get(name)}'"
                )

            # Cleanup
            manager.cleanup()

        except Exception as e:
            self.logger.error(f"Inject with cookies: {e}")

    # =========================================================================
    # 5. Integration
    # =========================================================================

    def test_40_statusbar_widget(self) -> None:
        """TEST 40: StatusBar widget НСПД"""
        self.logger.section("40. StatusBar widget")

        try:
            import qgis.utils

            plugin = qgis.utils.plugins.get('Daman_QGIS')
            if not plugin:
                self.logger.skip("Plugin не загружен -- пропуск")
                return

            has_label = hasattr(plugin, '_nspd_status_label')

            self.logger.check(
                has_label,
                "Plugin имеет _nspd_status_label",
                "Plugin не имеет _nspd_status_label!"
            )

            if has_label and plugin._nspd_status_label:
                text = plugin._nspd_status_label.text()
                self.logger.check(
                    'НСПД' in text,
                    f"StatusBar текст: '{text}'",
                    f"StatusBar текст не содержит 'НСПД': '{text}'"
                )

        except Exception as e:
            self.logger.error(f"StatusBar widget: {e}")

    def test_41_cleanup(self) -> None:
        """TEST 41: cleanup() без ошибок"""
        self.logger.section("41. Cleanup")

        try:
            from Daman_QGIS.managers.infrastructure.M_40_nspd_auth_manager import NspdAuthManager

            # Создаём отдельный экземпляр для теста cleanup
            manager = NspdAuthManager()
            manager._cookie_store.set_cookies({'cleanup_test': 'value'})

            # cleanup не должен выбрасывать исключений
            manager.cleanup()

            self.logger.check(
                not manager.is_authenticated(),
                "После cleanup: не авторизован",
                "После cleanup: cookies не очищены!"
            )

            # Повторный cleanup тоже безопасен
            manager.cleanup()
            self.logger.success("Повторный cleanup безопасен")

        except Exception as e:
            self.logger.error(f"Cleanup: {e}")

    # =========================================================================
    # 6. Edge CDP (Msm_40_3)
    # =========================================================================

    def test_50_edge_detection(self) -> None:
        """TEST 50: Обнаружение Microsoft Edge"""
        self.logger.section("50. Edge detection")

        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_40_3_edge_auth import (
                find_edge_executable, is_edge_available
            )

            edge_path = find_edge_executable()
            available = is_edge_available()

            self.logger.check(
                isinstance(available, bool),
                f"is_edge_available() -> {available} (bool)",
                f"is_edge_available() вернул не bool: {type(available)}"
            )

            if edge_path:
                import os
                self.logger.check(
                    os.path.isfile(edge_path),
                    f"Edge найден: {edge_path}",
                    f"Edge путь невалидный: {edge_path}"
                )
            else:
                self.logger.warning("Edge не найден (допустимо на не-Windows)")

        except Exception as e:
            self.logger.error(f"Edge detection: {e}")

    def test_51_is_available_with_edge(self) -> None:
        """TEST 51: M_40.is_available() учитывает Edge"""
        self.logger.section("51. is_available с Edge")

        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_40_3_edge_auth import (
                is_edge_available
            )
            from Daman_QGIS.managers.infrastructure.M_40_nspd_auth_manager import NspdAuthManager

            manager = NspdAuthManager()

            # Если Edge доступен -- is_available() должен быть True
            if is_edge_available():
                self.logger.check(
                    manager.is_available(),
                    "is_available()=True при наличии Edge",
                    "is_available()=False хотя Edge доступен!"
                )
                self.logger.check(
                    manager._use_edge,
                    "_use_edge=True на Windows с Edge",
                    "_use_edge=False хотя Edge доступен!"
                )
            else:
                self.logger.warning("Edge недоступен -- пропуск проверки")

            manager.cleanup()

        except Exception as e:
            self.logger.error(f"is_available with Edge: {e}")

    def test_52_free_port(self) -> None:
        """TEST 52: Поиск свободного порта"""
        self.logger.section("52. Free port finder")

        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_40_3_edge_auth import (
                _EdgeCdpSession
            )

            session = _EdgeCdpSession()
            port = session._find_free_port()

            self.logger.check(
                isinstance(port, int) and 0 < port < 65536,
                f"Свободный порт: {port}",
                f"Невалидный порт: {port}"
            )

        except Exception as e:
            self.logger.error(f"Free port: {e}")

    def test_53_cookie_domain_filtering(self) -> None:
        """TEST 53: Фильтрация cookies по домену"""
        self.logger.section("53. Cookie domain filtering")

        try:
            from Daman_QGIS.constants import NSPD_AUTH_COOKIE_DOMAINS

            # Симуляция cookies из CDP ответа
            mock_cookies = [
                {"name": "session_id", "value": "abc123", "domain": ".nspd.gov.ru"},
                {"name": "auth_token", "value": "xyz789", "domain": "esia.gosuslugi.ru"},
                {"name": "tracking", "value": "tr001", "domain": ".google.com"},
                {"name": "analytics", "value": "an002", "domain": ".yandex.ru"},
                {"name": "nspd_pref", "value": "pref1", "domain": "nspd.gov.ru"},
            ]

            # Логика фильтрации (идентична _EdgeCdpSession.extract_cookies)
            filtered = {}
            for cookie in mock_cookies:
                cookie_domain = cookie.get("domain", "")
                if any(d in cookie_domain for d in NSPD_AUTH_COOKIE_DOMAINS):
                    filtered[cookie["name"]] = cookie["value"]

            self.logger.check(
                len(filtered) == 3,
                f"Отфильтровано 3 из 5 cookies (nspd + gosuslugi)",
                f"Ожидалось 3 cookies, получено {len(filtered)}: {list(filtered.keys())}"
            )

            self.logger.check(
                "session_id" in filtered and "auth_token" in filtered and "nspd_pref" in filtered,
                "Корректные cookies: session_id, auth_token, nspd_pref",
                f"Неожиданные cookies: {list(filtered.keys())}"
            )

            self.logger.check(
                "tracking" not in filtered and "analytics" not in filtered,
                "google/yandex cookies отфильтрованы",
                "Посторонние cookies не отфильтрованы!"
            )

        except Exception as e:
            self.logger.error(f"Cookie domain filtering: {e}")
