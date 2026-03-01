# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_29 - Тесты лицензионной логики (M_29)

Проверяет:
1. LicenseStatus enum и состояния M_29
2. check_access() кэширование сессии
3. verify_for_display() защита сессии от транзиентных ошибок
4. _acquire_jwt_tokens() проверка результата verify()

Регрессия:
- Баг: _acquire_jwt_tokens() игнорировал результат verify()
- Баг: F_4_3 мутировал сессию M_29 при SSL ошибке
"""

import time
from typing import Any, Dict, Optional


class TestLicenseLogic:
    """Тесты лицензионной логики M_29"""

    def __init__(self, iface: Any, logger: Any) -> None:
        self.iface = iface
        self.logger = logger
        self.m29 = None
        self._saved_state: Optional[Dict] = None

    def run_all_tests(self) -> None:
        """Запуск всех тестов лицензии"""
        self.logger.section("ТЕСТ ЛИЦЕНЗИИ: M_29")

        try:
            # Группа 1: Состояния
            self.test_01_license_status_enum()
            self.test_02_m29_initialization()

            # Группа 2: check_access()
            self.test_03_check_access_session_cache()
            self.test_04_check_access_invalid_status()

            # Группа 3: verify_for_display()
            self.test_05_verify_for_display_preserves_session()
            self.test_06_verify_for_display_no_restore_when_not_valid()

            # Группа 4: Интеграция
            self.test_07_acquire_jwt_tokens_checks_verify()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов M_29: {str(e)}")

        self.logger.summary()

    # === Helpers ===

    def _save_state(self) -> Dict:
        """Сохранить состояние M_29 перед тестом"""
        return {
            'session_verified': self.m29._session_verified,
            'status': self.m29._status,
        }

    def _restore_state(self, state: Dict) -> None:
        """Восстановить состояние M_29 после теста"""
        self.m29._session_verified = state['session_verified']
        self.m29._status = state['status']

    # === Группа 1: LicenseStatus и состояния ===

    def test_01_license_status_enum(self) -> None:
        """ТЕСТ 1: LicenseStatus enum содержит все статусы"""
        self.logger.section("1. LicenseStatus enum")

        try:
            from Daman_QGIS.managers import LicenseStatus

            expected_statuses = [
                'VALID', 'EXPIRED', 'INVALID_KEY',
                'HARDWARE_MISMATCH', 'NOT_ACTIVATED',
                'SERVER_ERROR', 'SUSPENDED'
            ]

            for status_name in expected_statuses:
                self.logger.check(
                    hasattr(LicenseStatus, status_name),
                    f"LicenseStatus.{status_name} существует",
                    f"LicenseStatus.{status_name} отсутствует!"
                )

            # Проверяем значения
            self.logger.check(
                LicenseStatus.VALID.value == "valid",
                "LicenseStatus.VALID.value == 'valid'",
                f"LicenseStatus.VALID.value == '{LicenseStatus.VALID.value}' (ожидалось 'valid')"
            )

        except ImportError as e:
            self.logger.error(f"Не удалось импортировать LicenseStatus: {e}")

    def test_02_m29_initialization(self) -> None:
        """ТЕСТ 2: M_29 инициализирован в registry"""
        self.logger.section("2. M_29 инициализация")

        try:
            from Daman_QGIS.managers import registry

            self.m29 = registry.get('M_29')

            self.logger.check(
                self.m29 is not None,
                "M_29 доступен из registry",
                "M_29 не найден в registry!"
            )

            if self.m29 is None:
                return

            self.logger.check(
                self.m29._initialized,
                "M_29._initialized == True",
                "M_29 не инициализирован!"
            )

            self.logger.check(
                hasattr(self.m29, '_storage') and self.m29._storage is not None,
                "M_29._storage инициализирован",
                "M_29._storage отсутствует!"
            )

            self.logger.check(
                hasattr(self.m29, '_validator') and self.m29._validator is not None,
                "M_29._validator инициализирован",
                "M_29._validator отсутствует!"
            )

            self.logger.check(
                hasattr(self.m29, '_hardware_id') and self.m29._hardware_id,
                f"M_29._hardware_id установлен ({self.m29._hardware_id[:8]}...)",
                "M_29._hardware_id пуст!"
            )

            # Проверяем наличие verify_for_display
            self.logger.check(
                hasattr(self.m29, 'verify_for_display'),
                "M_29.verify_for_display() метод существует",
                "M_29.verify_for_display() отсутствует!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка проверки M_29: {e}")

    # === Группа 2: check_access() ===

    def test_03_check_access_session_cache(self) -> None:
        """ТЕСТ 3: check_access() использует кэш сессии при VALID"""
        self.logger.section("3. check_access() кэш сессии")

        if self.m29 is None:
            self.logger.skip("M_29 не доступен")
            return

        from Daman_QGIS.managers import LicenseStatus

        state = self._save_state()
        try:
            # Устанавливаем VALID сессию
            self.m29._session_verified = True
            self.m29._status = LicenseStatus.VALID

            # check_access() должен вернуть True мгновенно (из кэша)
            start = time.perf_counter()
            result = self.m29.check_access()
            elapsed_ms = (time.perf_counter() - start) * 1000

            self.logger.check(
                result is True,
                "check_access() == True при VALID сессии",
                "check_access() вернул False при VALID сессии!"
            )

            # Кэш должен отработать за < 10ms (без сетевого запроса)
            self.logger.check(
                elapsed_ms < 10,
                f"check_access() из кэша за {elapsed_ms:.1f}ms (< 10ms)",
                f"check_access() занял {elapsed_ms:.1f}ms (ожидалось < 10ms, возможен сетевой запрос)"
            )

        finally:
            self._restore_state(state)

    def test_04_check_access_invalid_status(self) -> None:
        """ТЕСТ 4: check_access() НЕ использует кэш при невалидном статусе"""
        self.logger.section("4. check_access() без кэша при INVALID")

        if self.m29 is None:
            self.logger.skip("M_29 не доступен")
            return

        from Daman_QGIS.managers import LicenseStatus

        state = self._save_state()
        original_verify = self.m29.verify
        try:
            # Сессия verified, но статус INVALID_KEY
            self.m29._session_verified = True
            self.m29._status = LicenseStatus.INVALID_KEY

            # Подменяем verify чтобы он не делал сетевой запрос
            verify_called = False

            def mock_verify():
                nonlocal verify_called
                verify_called = True
                self.m29._status = LicenseStatus.SERVER_ERROR
                return False

            self.m29.verify = mock_verify  # type: ignore[assignment]

            result = self.m29.check_access()

            self.logger.check(
                result is False,
                "check_access() == False при INVALID статусе",
                "check_access() вернул True при INVALID статусе!"
            )

            # verify() должен был быть вызван (кэш не сработал)
            self.logger.check(
                verify_called,
                "verify() вызван (кэш не использовался при _status != VALID)",
                "verify() НЕ вызван (кэш сработал при невалидном статусе!)"
            )

        finally:
            self.m29.verify = original_verify  # type: ignore[assignment]
            self._restore_state(state)

    # === Группа 3: verify_for_display() ===

    def test_05_verify_for_display_preserves_session(self) -> None:
        """ТЕСТ 5: verify_for_display() не ломает VALID сессию при ошибке"""
        self.logger.section("5. verify_for_display() защита сессии (РЕГРЕССИЯ)")

        if self.m29 is None:
            self.logger.skip("M_29 не доступен")
            return

        from Daman_QGIS.managers import LicenseStatus

        state = self._save_state()
        original_validator_verify = self.m29._validator.verify
        try:
            # Устанавливаем валидную сессию
            self.m29._session_verified = True
            self.m29._status = LicenseStatus.VALID

            # Подменяем валидатор -- симулируем SSL ошибку
            def mock_validator_verify(**kwargs):
                return {"status": "error", "message": "SSL Error (mock)"}

            self.m29._validator.verify = mock_validator_verify  # type: ignore[assignment]

            # Вызываем verify_for_display
            is_valid, display_status = self.m29.verify_for_display()

            # display_status должен показать ошибку
            self.logger.check(
                display_status != LicenseStatus.VALID,
                f"display_status = {display_status.value} (показывает ошибку)",
                f"display_status = VALID (должен показывать ошибку!)"
            )

            self.logger.check(
                is_valid is False,
                "is_valid == False (верификация не прошла)",
                "is_valid == True (должен быть False при ошибке!)"
            )

            # ГЛАВНАЯ ПРОВЕРКА: сессия НЕ сломана
            self.logger.check(
                self.m29._session_verified is True,
                "_session_verified восстановлен (True)",
                "_session_verified сброшен! Сессия сломана транзиентной ошибкой!"
            )

            self.logger.check(
                self.m29._status == LicenseStatus.VALID,
                "_status восстановлен (VALID)",
                f"_status изменён на {self.m29._status.value}! Сессия сломана!"
            )

        finally:
            self.m29._validator.verify = original_validator_verify  # type: ignore[assignment]
            self._restore_state(state)

    def test_06_verify_for_display_no_restore_when_not_valid(self) -> None:
        """ТЕСТ 6: verify_for_display() НЕ восстанавливает если сессия не была VALID"""
        self.logger.section("6. verify_for_display() без восстановления для невалидной сессии")

        if self.m29 is None:
            self.logger.skip("M_29 не доступен")
            return

        from Daman_QGIS.managers import LicenseStatus

        state = self._save_state()
        original_validator_verify = self.m29._validator.verify
        try:
            # Сессия НЕ была валидна
            self.m29._session_verified = False
            self.m29._status = LicenseStatus.NOT_ACTIVATED

            # Подменяем валидатор
            def mock_validator_verify(**kwargs):
                return {"status": "error", "message": "Network error (mock)"}

            self.m29._validator.verify = mock_validator_verify  # type: ignore[assignment]

            is_valid, display_status = self.m29.verify_for_display()

            self.logger.check(
                is_valid is False,
                "is_valid == False",
                "is_valid == True (неожиданно!)"
            )

            # Статус НЕ должен быть восстановлен (сессия не была VALID)
            self.logger.check(
                self.m29._status != LicenseStatus.NOT_ACTIVATED,
                f"_status обновлён на {self.m29._status.value} (не восстановлен)",
                "_status остался NOT_ACTIVATED (должен был измениться на ошибку)"
            )

        finally:
            self.m29._validator.verify = original_validator_verify  # type: ignore[assignment]
            self._restore_state(state)

    # === Группа 4: Интеграция с initGui ===

    def test_07_acquire_jwt_tokens_checks_verify(self) -> None:
        """ТЕСТ 7: _acquire_jwt_tokens() проверяет результат verify() (РЕГРЕССИЯ)"""
        self.logger.section("7. _acquire_jwt_tokens() проверяет verify() (РЕГРЕССИЯ)")

        try:
            import qgis.utils
            plugin = qgis.utils.plugins.get('Daman_QGIS')

            if plugin is None:
                self.logger.skip("Plugin instance не доступен")
                return

            self.logger.check(
                hasattr(plugin, '_acquire_jwt_tokens'),
                "_acquire_jwt_tokens() метод существует",
                "_acquire_jwt_tokens() метод отсутствует!"
            )

            if not hasattr(plugin, '_acquire_jwt_tokens'):
                return

            from Daman_QGIS.managers import registry, LicenseStatus

            m29 = registry.get('M_29')
            if m29 is None:
                self.logger.skip("M_29 не доступен")
                return

            # Сохраняем оригинальные методы
            original_verify = m29.verify
            original_is_activated = m29.is_activated
            state = self._save_state()

            try:
                # Подменяем: лицензия активирована, но verify возвращает False
                m29.is_activated = lambda: True  # type: ignore[assignment]
                m29.verify = lambda: False  # type: ignore[assignment]

                result = plugin._acquire_jwt_tokens()

                self.logger.check(
                    result is False,
                    "_acquire_jwt_tokens() == False при verify() == False",
                    "_acquire_jwt_tokens() == True при verify() == False! РЕГРЕССИЯ!"
                )

            finally:
                m29.verify = original_verify  # type: ignore[assignment]
                m29.is_activated = original_is_activated  # type: ignore[assignment]
                self._restore_state(state)

        except Exception as e:
            self.logger.error(f"Ошибка теста _acquire_jwt_tokens: {e}")
