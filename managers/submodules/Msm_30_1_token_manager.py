# -*- coding: utf-8 -*-
"""
Msm_30_1_TokenManager - Управление JWT токенами.

Отвечает за:
- Хранение access/refresh токенов
- Проверку срока действия
- Offline валидация через RS256 public key
- Интеграция с M_29_LicenseManager для персистентного хранения
"""

import time
import json
import base64
from typing import Optional, Dict, Any
from datetime import datetime

from ...utils import log_info, log_error, log_warning
from ...constants import ACCESS_TOKEN_LIFETIME_MINUTES


class TokenManager:
    """
    Менеджер JWT токенов.

    Особенности:
    - RS256 offline валидация (если доступен public key)
    - Автоматическая проверка срока действия
    - Интеграция с LicenseManager для хранения
    """

    def __init__(self):
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._access_expires_at: Optional[float] = None
        self._public_key: Optional[str] = None
        self._initialized: bool = False

    def initialize(self) -> bool:
        """Инициализация с загрузкой сохранённых токенов."""
        try:
            # Получаем токены из LicenseManager
            from ..M_29_license_manager import get_license_manager

            license_mgr = get_license_manager()
            if not license_mgr.is_activated():
                log_warning("Msm_30_1: License not activated")
                return False

            # Загрузка сохранённых токенов
            stored = license_mgr.get_stored_tokens()
            self._access_token = stored.get("access_token")
            self._refresh_token = stored.get("refresh_token")
            self._access_expires_at = stored.get("access_expires_at")

            # Загрузка public key для offline валидации
            self._public_key = license_mgr.get_public_key()

            self._initialized = True
            log_info("Msm_30_1: Initialized")
            return True

        except Exception as e:
            log_error(f"Msm_30_1: Initialization failed: {e}")
            return False

    def get_access_token(self) -> Optional[str]:
        """
        Получение access token.

        Returns:
            Токен или None если истёк/отсутствует
        """
        if not self._access_token:
            return None

        # Проверка срока действия
        if self._is_token_expired():
            log_warning("Msm_30_1: Access token expired")
            return None

        return self._access_token

    def get_refresh_token(self) -> Optional[str]:
        """Получение refresh token."""
        return self._refresh_token

    def has_valid_token(self) -> bool:
        """Проверка наличия валидного access token."""
        return self.get_access_token() is not None

    def store_tokens(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
        access_expires_at: Optional[float] = None
    ):
        """
        Сохранение токенов.

        Args:
            access_token: Новый access token
            refresh_token: Новый refresh token (ротация)
            access_expires_at: Время истечения (unix timestamp)
        """
        self._access_token = access_token
        if refresh_token:
            self._refresh_token = refresh_token

        # Вычисление времени истечения
        if access_expires_at:
            self._access_expires_at = access_expires_at
        else:
            # Парсинг exp из JWT payload
            exp = self._extract_exp_from_jwt(access_token)
            if exp:
                self._access_expires_at = exp
            else:
                # Fallback: текущее время + TTL
                self._access_expires_at = time.time() + ACCESS_TOKEN_LIFETIME_MINUTES * 60

        # Сохранение в LicenseManager
        self._persist_tokens()

        log_info("Msm_30_1: Tokens stored")

    def clear_tokens(self):
        """Очистка токенов."""
        self._access_token = None
        self._refresh_token = None
        self._access_expires_at = None

        # Очистка в LicenseManager
        try:
            from ..M_29_license_manager import get_license_manager
            license_mgr = get_license_manager()
            license_mgr.store_tokens({})
        except Exception:
            pass

        log_info("Msm_30_1: Tokens cleared")

    def validate_offline(self, token: Optional[str] = None) -> bool:
        """
        Offline валидация JWT через RS256 public key.

        Args:
            token: Токен для проверки (по умолчанию текущий access)

        Returns:
            True если токен валиден
        """
        token = token or self._access_token
        if not token:
            return False

        if not self._public_key:
            log_warning("Msm_30_1: No public key for offline validation")
            # Без public key проверяем только срок действия
            return not self._is_token_expired()

        try:
            # Попытка использовать PyJWT для RS256
            import jwt
            decoded = jwt.decode(
                token,
                self._public_key,
                algorithms=["RS256"],
                options={"verify_exp": True}
            )
            return True

        except ImportError:
            # PyJWT не установлен - только проверка exp
            log_warning("Msm_30_1: PyJWT not installed, using basic validation")
            return not self._is_token_expired()

        except jwt.ExpiredSignatureError:
            log_warning("Msm_30_1: Token expired (offline check)")
            return False

        except jwt.InvalidTokenError as e:
            log_error(f"Msm_30_1: Invalid token: {e}")
            return False

        except Exception as e:
            log_error(f"Msm_30_1: Validation error: {e}")
            return False

    def get_token_payload(self, token: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Извлечение payload из JWT (без проверки подписи).

        Args:
            token: Токен (по умолчанию текущий access)

        Returns:
            Decoded payload или None
        """
        token = token or self._access_token
        if not token:
            return None

        try:
            # JWT: header.payload.signature
            parts = token.split('.')
            if len(parts) != 3:
                return None

            # Base64 decode payload
            payload_b64 = parts[1]
            # Добавляем padding если нужно
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += '=' * padding

            payload_json = base64.urlsafe_b64decode(payload_b64)
            return json.loads(payload_json)

        except Exception as e:
            log_error(f"Msm_30_1: Failed to decode token payload: {e}")
            return None

    def get_token_expiry(self) -> Optional[datetime]:
        """Время истечения access token."""
        if self._access_expires_at:
            return datetime.fromtimestamp(self._access_expires_at)
        return None

    def get_time_until_expiry(self) -> Optional[int]:
        """
        Секунды до истечения токена.

        Returns:
            Секунды или None если нет токена
        """
        if not self._access_expires_at:
            return None

        remaining = self._access_expires_at - time.time()
        return max(0, int(remaining))

    # =========================================================================
    # Приватные методы
    # =========================================================================

    def _is_token_expired(self) -> bool:
        """Проверка истечения срока токена."""
        if not self._access_expires_at:
            # Пробуем извлечь из токена
            if self._access_token:
                exp = self._extract_exp_from_jwt(self._access_token)
                if exp:
                    self._access_expires_at = exp

        if not self._access_expires_at:
            return True  # Неизвестный срок = истёк

        # Добавляем 30 секунд буфера
        return time.time() > (self._access_expires_at - 30)

    def _extract_exp_from_jwt(self, token: str) -> Optional[float]:
        """Извлечение exp claim из JWT."""
        payload = self.get_token_payload(token)
        if payload and "exp" in payload:
            return float(payload["exp"])
        return None

    def _persist_tokens(self):
        """Сохранение токенов в LicenseManager."""
        try:
            from ..M_29_license_manager import get_license_manager

            license_mgr = get_license_manager()
            license_mgr.store_tokens({
                "access_token": self._access_token,
                "refresh_token": self._refresh_token,
                "access_expires_at": self._access_expires_at
            })

        except Exception as e:
            log_error(f"Msm_30_1: Failed to persist tokens: {e}")
