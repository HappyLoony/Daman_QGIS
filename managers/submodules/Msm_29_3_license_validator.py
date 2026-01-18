# -*- coding: utf-8 -*-
"""
Msm_29_3_LicenseValidator - Валидатор лицензии через Yandex Cloud API.

Выполняет:
- Активацию новой лицензии (POST ?action=validate&mode=activate)
- Проверку существующей лицензии (POST ?action=validate&mode=verify)
- Деактивацию лицензии (POST ?action=deactivate)

Безопасность:
- HMAC-SHA256 подпись запросов с API ключом пользователя как secret
- Каждый пользователь имеет уникальный ключ подписи
- Защита от replay attacks (timestamp validation на сервере)

API: https://functions.yandexcloud.net/d4e9nvs008lt7sd87s7m
"""

import hashlib
import hmac
import time
from typing import Dict, Any, List

from ...constants import API_BASE_URL, API_TIMEOUT
from ...utils import log_info, log_error, log_warning

class LicenseValidator:
    """
    Валидатор лицензии через Yandex Cloud API.

    API endpoints (query params):
    - POST ?action=validate - активация/верификация лицензии
    - POST ?action=deactivate - деактивация лицензии
    """

    def __init__(self):
        self.base_url = API_BASE_URL
        self._session = None

    @classmethod
    def clear_cache(cls):
        """Очистить кэш (для совместимости с предыдущей версией)."""
        # В новой версии кэш не используется - данные всегда с API
        pass

    def _get_session(self):
        """Ленивая инициализация requests session."""
        if self._session is None:
            try:
                import requests
                self._session = requests.Session()
            except ImportError:
                log_warning("Msm_29_3: requests library not available")
        return self._session

    def _generate_hmac_signature(self, api_key: str, hardware_id: str, timestamp: int) -> str:
        """
        Генерация HMAC-SHA256 подписи запроса.

        Используем API ключ пользователя как HMAC secret.
        Каждый пользователь имеет уникальный ключ подписи.

        Подписываем: hardware_id + timestamp
        Secret: api_key (уникален для каждого пользователя)

        Это защищает от:
        - Подделки запросов (нужен api_key конкретного пользователя)
        - Replay attacks (timestamp проверяется на сервере)
        - Компрометация одного ключа не влияет на других

        Args:
            api_key: API ключ (используется как HMAC secret)
            hardware_id: Hardware ID
            timestamp: Unix timestamp

        Returns:
            Hex-encoded HMAC signature
        """
        # API ключ как secret - уникален для каждого пользователя
        secret = api_key.encode('utf-8')
        message = f"{hardware_id}|{timestamp}".encode('utf-8')
        signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
        return signature

    def _build_signed_payload(self, api_key: str, hardware_id: str, **extra) -> Dict[str, Any]:
        """
        Построение подписанного payload для запроса.

        Args:
            api_key: API ключ
            hardware_id: Hardware ID
            **extra: Дополнительные поля (mode, etc.)

        Returns:
            Dict с подписью и timestamp
        """
        timestamp = int(time.time())
        signature = self._generate_hmac_signature(api_key, hardware_id, timestamp)

        payload = {
            "api_key": api_key,
            "hardware_id": hardware_id,
            "timestamp": timestamp,
            "signature": signature,
            **extra
        }
        return payload

    def activate(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """
        Активация лицензии через Yandex Cloud API.

        Args:
            api_key: Ключ активации
            hardware_id: Hardware ID компьютера

        Returns:
            Результат активации
        """
        log_info("Msm_29_3: Активация лицензии через API")

        try:
            session = self._get_session()
            if not session:
                return {"status": "error", "message": "requests library not available"}

            url = f"{self.base_url}?action=validate"
            payload = self._build_signed_payload(api_key, hardware_id, mode="activate")

            response = session.post(
                url,
                json=payload,
                timeout=API_TIMEOUT
            )

            data = response.json()

            if response.status_code == 200 and data.get("status") == "success":
                log_info("Msm_29_3: Активация успешна")
                return {
                    "status": "success",
                    "license_info": data.get("license_info", {})
                }

            # Обработка ошибок
            error_code = data.get("error_code", "")
            message = data.get("message", "Unknown error")

            if error_code == "ALREADY_BOUND":
                return {"status": "already_bound"}
            elif error_code == "INVALID_KEY":
                return {"status": "invalid_key"}
            elif error_code == "EXPIRED":
                return {"status": "expired", "expires_at": data.get("expired_at")}
            elif error_code == "MISSING_KEY":
                return {"status": "error", "message": "API ключ не указан"}
            elif error_code == "MISSING_HWID":
                return {"status": "error", "message": "Hardware ID не указан"}
            else:
                return {"status": "error", "message": message}

        except Exception as e:
            log_error(f"Msm_29_3: Activation request failed: {e}")
            return {"status": "error", "message": f"Ошибка сети: {e}"}

    def verify(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """
        Проверка лицензии через Yandex Cloud API.

        Args:
            api_key: API ключ
            hardware_id: Hardware ID

        Returns:
            Результат проверки
        """
        try:
            session = self._get_session()
            if not session:
                return {"status": "error", "message": "requests library not available"}

            url = f"{self.base_url}?action=validate"
            payload = self._build_signed_payload(api_key, hardware_id, mode="verify")

            response = session.post(
                url,
                json=payload,
                timeout=API_TIMEOUT
            )

            data = response.json()

            if response.status_code == 200 and data.get("status") == "success":
                license_info = data.get("license_info", {})
                return {
                    "status": "active",
                    "expires_at": license_info.get("expires_at"),
                    "subscription_type": license_info.get("subscription_type"),
                    "license_info": license_info
                }

            # Обработка ошибок
            error_code = data.get("error_code", "")
            message = data.get("message", "Unknown error")

            if error_code == "INVALID_KEY":
                return {"status": "invalid_key"}
            elif error_code == "EXPIRED":
                return {"status": "expired", "expires_at": data.get("expired_at")}
            elif error_code == "HARDWARE_MISMATCH":
                return {"status": "hardware_mismatch"}
            elif error_code == "INVALID_SIGNATURE":
                return {"status": "error", "message": "Ошибка подписи запроса"}
            elif error_code == "EXPIRED_TIMESTAMP":
                return {"status": "error", "message": "Запрос устарел, проверьте время на ПК"}
            else:
                return {"status": "error", "message": message}

        except Exception as e:
            log_error(f"Msm_29_3: Verification request failed: {e}")
            return {"status": "error", "message": f"Ошибка сети: {e}"}

    def deactivate(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """
        Деактивация лицензии через Yandex Cloud API.

        Освобождает привязку к Hardware ID.
        """
        log_info("Msm_29_3: Деактивация лицензии через API")

        try:
            session = self._get_session()
            if not session:
                return {"status": "error", "message": "requests library not available"}

            url = f"{self.base_url}?action=deactivate"
            payload = self._build_signed_payload(api_key, hardware_id)

            response = session.post(
                url,
                json=payload,
                timeout=API_TIMEOUT
            )

            data = response.json()

            if response.status_code == 200 and data.get("status") == "success":
                log_info("Msm_29_3: Деактивация успешна")
                return {"status": "success"}

            # Обработка ошибок
            error_code = data.get("error_code", "")
            message = data.get("message", "Unknown error")

            if error_code == "INVALID_KEY":
                return {"status": "error", "message": "Ключ не найден"}
            elif error_code == "HARDWARE_MISMATCH":
                return {"status": "error", "message": "Деактивация возможна только с привязанного ПК"}
            else:
                return {"status": "error", "message": message}

        except Exception as e:
            log_error(f"Msm_29_3: Deactivation request failed: {e}")
            return {"status": "error", "message": f"Ошибка сети: {e}"}

    def report_hardware_change(
        self,
        api_key: str,
        old_hardware_id: str,
        new_hardware_id: str,
        changed_components: list
    ) -> Dict[str, Any]:
        """
        Отчёт о смене оборудования.

        Примечание: API пока не поддерживает этот endpoint.
        Возвращает успех для совместимости.
        """
        log_info(f"Msm_29_3: Hardware change report - components: {changed_components}")
        # API endpoint для report-hardware-change не реализован
        # Возвращаем успех для совместимости
        return {"status": "reported"}
