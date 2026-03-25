# -*- coding: utf-8 -*-
"""
Msm_29_4_TokenManager - Управление JWT токенами для API.

Отвечает за:
- Хранение access и refresh токенов в памяти (RAM only)
- Автоматическое обновление access token до истечения
- Добавление Authorization заголовка к запросам
- Обработку 401 ответов (re-auth)

Singleton: один экземпляр на сессию QGIS.
Токены НЕ персистятся между сессиями (безопасность).

Зависимости:
- Msm_29_3_license_validator (получение начальных токенов)
- constants (API_BASE_URL, TOKEN_* константы)
- utils (log_info, log_error, log_warning)
"""

import time
from typing import Dict, Any, Optional, Callable

from Daman_QGIS.constants import (
    API_TIMEOUT,
    TOKEN_REFRESH_THRESHOLD_SECONDS,
    TOKEN_MAX_RETRY_COUNT,
    TOKEN_RETRY_DELAY_SECONDS,
    get_api_url,
)
from Daman_QGIS.utils import log_info, log_error, log_warning


class TokenManager:
    """
    Singleton менеджер JWT токенов.

    Жизненный цикл:
    1. LicenseManager вызывает set_tokens() после успешной валидации
    2. BaseReferenceLoader вызывает get_auth_headers() для каждого запроса
    3. TokenManager автоматически обновляет access token при необходимости
    4. При 401 ответе -- вызывает on_auth_failure callback

    Хранение: только в памяти (RAM). НЕ в QSettings, НЕ на диске.
    При перезапуске QGIS -- повторная валидация лицензии.
    """

    _instance: Optional['TokenManager'] = None

    def __init__(self):
        """Приватный конструктор. Используйте get_instance()."""
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._access_expires_at: float = 0
        self._refresh_expires_at: float = 0
        self._hardware_id: Optional[str] = None
        self._on_auth_failure: Optional[Callable] = None
        self._is_refreshing: bool = False
        self._session = None

    @classmethod
    def get_instance(cls) -> 'TokenManager':
        """Получить singleton экземпляр."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Сброс singleton (для тестов и деактивации)."""
        if cls._instance:
            cls._instance.clear_tokens()
        cls._instance = None

    # === Публичный API ===

    def set_tokens(
        self,
        access_token: str,
        refresh_token: str,
        access_expires_in: int,
        refresh_expires_in: int,
        hardware_id: str
    ) -> None:
        """
        Установка токенов после успешной валидации лицензии.

        Args:
            access_token: JWT access token
            refresh_token: JWT refresh token
            access_expires_in: Время жизни access token (секунды)
            refresh_expires_in: Время жизни refresh token (секунды)
            hardware_id: Hardware ID текущего ПК
        """
        now = time.time()
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._access_expires_at = now + access_expires_in
        self._refresh_expires_at = now + refresh_expires_in
        self._hardware_id = hardware_id

        log_info(
            f"Msm_29_4: Tokens set. "
            f"Access expires in {access_expires_in}s, "
            f"Refresh expires in {refresh_expires_in}s"
        )

    def set_tokens_from_response(self, tokens_dict: Dict[str, Any], hardware_id: str) -> None:
        """
        Установка токенов из ответа сервера.

        Args:
            tokens_dict: Словарь из response["tokens"]
            hardware_id: Hardware ID текущего ПК
        """
        self.set_tokens(
            access_token=tokens_dict['access_token'],
            refresh_token=tokens_dict['refresh_token'],
            access_expires_in=tokens_dict['access_expires_in'],
            refresh_expires_in=tokens_dict['refresh_expires_in'],
            hardware_id=hardware_id
        )

    def clear_tokens(self) -> None:
        """Очистка токенов (logout / деактивация)."""
        self._access_token = None
        self._refresh_token = None
        self._access_expires_at = 0
        self._refresh_expires_at = 0
        log_info("Msm_29_4: Tokens cleared")

    def has_valid_tokens(self) -> bool:
        """Есть ли действующие токены (access или refresh)."""
        now = time.time()
        return (
            (self._access_token and now < self._access_expires_at) or
            (self._refresh_token and now < self._refresh_expires_at)
        )

    def set_on_auth_failure(self, callback: Callable) -> None:
        """
        Установка callback при полном отказе аутентификации.

        Вызывается когда и access, и refresh невалидны.
        """
        self._on_auth_failure = callback

    def get_auth_headers(self) -> Dict[str, str]:
        """
        Получить заголовки авторизации для HTTP запроса.

        Автоматически обновляет access token если скоро истечёт.
        Если токенов нет -- возвращает пустой словарь (обратная совместимость).

        Returns:
            {"X-Auth-Token": "Bearer eyJ...", "X-Hardware-Id": "abc..."} или {}

        Note:
            Используем X-Auth-Token вместо Authorization, т.к. Yandex Cloud Functions
            перехватывает Authorization заголовок для IAM-авторизации.
        """
        if not self._access_token:
            return {}

        now = time.time()
        time_until_expiry = self._access_expires_at - now

        if time_until_expiry < TOKEN_REFRESH_THRESHOLD_SECONDS:
            if self._refresh_token and now < self._refresh_expires_at:
                self._auto_refresh()
            elif time_until_expiry <= 0:
                log_warning("Msm_29_4: All tokens expired")
                if self._on_auth_failure:
                    self._on_auth_failure()
                return {}

        if self._access_token:
            result = {'X-Auth-Token': f'Bearer {self._access_token}'}
            if self._hardware_id:
                result['X-Hardware-Id'] = self._hardware_id
            return result

        return {}

    def handle_401_response(self) -> bool:
        """
        Обработка 401 ответа от сервера.

        Returns:
            True если токен обновлён (повторить запрос)
            False если обновление не удалось
        """
        log_warning("Msm_29_4: Received 401, attempting token refresh")

        if self._refresh_token and time.time() < self._refresh_expires_at:
            success = self._do_refresh()
            if success:
                log_info("Msm_29_4: Token refreshed after 401")
                return True

        log_error("Msm_29_4: Token refresh failed after 401")
        self.clear_tokens()
        if self._on_auth_failure:
            self._on_auth_failure()
        return False

    # === Приватные методы ===

    def _get_session(self):
        """Ленивая инициализация requests session."""
        if self._session is None:
            try:
                import requests
                self._session = requests.Session()
            except ImportError:
                log_warning("Msm_29_4: requests library not available")
        return self._session

    def _auto_refresh(self) -> None:
        """Автоматическое обновление access token."""
        if self._is_refreshing:
            return
        self._do_refresh()

    def _do_refresh(self) -> bool:
        """
        Выполнить refresh запрос к серверу.

        Returns:
            True при успехе, False при ошибке
        """
        if self._is_refreshing:
            return False

        self._is_refreshing = True

        try:
            session = self._get_session()
            if not session:
                return False

            url = get_api_url("refresh")
            payload = {
                'refresh_token': self._refresh_token,
                'hardware_id': self._hardware_id
            }

            for attempt in range(TOKEN_MAX_RETRY_COUNT):
                try:
                    response = session.post(
                        url,
                        json=payload,
                        timeout=API_TIMEOUT
                    )

                    if response.status_code == 200:
                        data = response.json()
                        if data.get('status') == 'success':
                            self.set_tokens(
                                access_token=data['access_token'],
                                refresh_token=data['refresh_token'],
                                access_expires_in=data['access_expires_in'],
                                refresh_expires_in=data['refresh_expires_in'],
                                hardware_id=self._hardware_id
                            )
                            log_info("Msm_29_4: Tokens refreshed successfully")
                            return True

                    # Проверяем код ошибки
                    try:
                        error_data = response.json()
                        error_code = error_data.get('error_code', '')
                    except Exception:
                        error_code = ''

                    if error_code in ('TOKEN_REUSED', 'LICENSE_EXPIRED', 'HARDWARE_MISMATCH',
                                      'REFRESH_INVALID_SIGNATURE', 'REFRESH_HWID_MISMATCH'):
                        # Фатальные ошибки -- не повторяем
                        log_error(f"Msm_29_4: Refresh fatal error: {error_code}")
                        self.clear_tokens()
                        return False

                    if response.status_code == 401:
                        log_error("Msm_29_4: Refresh token rejected (401)")
                        self.clear_tokens()
                        return False

                except Exception as e:
                    log_warning(f"Msm_29_4: Refresh attempt {attempt + 1} failed: {e}")

                # Задержка перед повтором
                if attempt < TOKEN_MAX_RETRY_COUNT - 1:
                    time.sleep(TOKEN_RETRY_DELAY_SECONDS)

            log_error("Msm_29_4: All refresh attempts failed")
            return False

        finally:
            self._is_refreshing = False
