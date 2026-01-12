# -*- coding: utf-8 -*-
"""
Msm_29_3_LicenseValidator - Валидатор лицензии через API сервер.

Выполняет:
- Активацию новой лицензии
- Проверку существующей лицензии
- Деактивацию лицензии

MOCK MODE: Когда API сервер недоступен, используется mock режим для тестирования.
"""

import hashlib
import time
from typing import Dict, Any, Optional

from ...constants import API_BASE_URL, API_TIMEOUT
from ...utils import log_info, log_error, log_warning

# Флаг mock режима (True пока нет реального сервера)
MOCK_MODE = True

# Mock данные для тестирования
MOCK_LICENSES = {
    "DAMAN-B4E2-B0F9-4796": {
        "status": "active",
        "subscription_type": "Бессрочно",
        "expires_at": None,
        "user_name": "Плахотнюк А.А.",
        "user_email": "sashaplahot@gmail.com",
        "features": ["basic", "export_dxf", "export_tab"]
    },
    "DAMAN-TEST-TEST-TEST": {
        "status": "active",
        "subscription_type": "Месяц",
        "expires_at": "2025-12-31T23:59:59Z",
        "user_name": "Test User",
        "user_email": "test@example.com",
        "features": ["basic"]
    }
}

# Mock public key (для тестирования, НЕ использовать в production)
MOCK_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0Z3VS5JJcds3xfn/ygWyf
Mockt3st1ngK3yOnlyForT3st1ng0nlyNotForProduct1on
MOCK_KEY_DO_NOT_USE_IN_PRODUCTION
-----END PUBLIC KEY-----"""


class LicenseValidator:
    """
    Валидатор лицензии через API сервер.

    В mock режиме эмулирует ответы сервера для тестирования.
    """

    def __init__(self):
        self.base_url = API_BASE_URL
        self._session = None
        self._mock_hardware_bindings: Dict[str, str] = {}  # api_key -> hardware_id

    def _get_session(self):
        """Ленивая инициализация requests session."""
        if self._session is None:
            try:
                import requests
                self._session = requests.Session()
            except ImportError:
                log_warning("Msm_29_3: requests library not available, using mock mode")
        return self._session

    def activate(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """
        Активация лицензии.

        Args:
            api_key: Ключ активации
            hardware_id: Hardware ID компьютера

        Returns:
            Результат активации
        """
        if MOCK_MODE:
            return self._mock_activate(api_key, hardware_id)

        try:
            session = self._get_session()
            if not session:
                return self._mock_activate(api_key, hardware_id)

            response = session.post(
                f"{self.base_url}/api/v1/license/activate",
                json={
                    "api_key": api_key,
                    "hardware_id": hardware_id
                },
                timeout=API_TIMEOUT
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "status": "success",
                    "license_info": data.get("license"),
                    "public_key": data.get("public_key")
                }

            elif response.status_code == 400:
                error = response.json()
                error_code = error.get("error_code")

                if error_code == "ALREADY_BOUND":
                    return {"status": "already_bound"}
                elif error_code == "INVALID_KEY":
                    return {"status": "invalid_key"}
                elif error_code == "EXPIRED":
                    return {"status": "expired"}
                else:
                    return {
                        "status": "error",
                        "message": error.get("message", "Unknown error")
                    }

            else:
                return {
                    "status": "error",
                    "message": f"Server error: {response.status_code}"
                }

        except Exception as e:
            log_error(f"Msm_29_3: Activation request failed: {e}")
            # Fallback to mock mode
            return self._mock_activate(api_key, hardware_id)

    def _mock_activate(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """Mock активация для тестирования."""
        log_info("Msm_29_3: Using MOCK activation")

        # Проверяем ключ
        license_data = MOCK_LICENSES.get(api_key)
        if not license_data:
            return {"status": "invalid_key"}

        # Проверяем привязку
        existing_hwid = self._mock_hardware_bindings.get(api_key)
        if existing_hwid and existing_hwid != hardware_id:
            return {"status": "already_bound"}

        # Привязываем
        self._mock_hardware_bindings[api_key] = hardware_id

        return {
            "status": "success",
            "license_info": license_data,
            "public_key": MOCK_PUBLIC_KEY
        }

    def verify(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """
        Проверка лицензии.

        Args:
            api_key: API ключ
            hardware_id: Hardware ID

        Returns:
            Результат проверки
        """
        if MOCK_MODE:
            return self._mock_verify(api_key, hardware_id)

        try:
            session = self._get_session()
            if not session:
                return self._mock_verify(api_key, hardware_id)

            response = session.post(
                f"{self.base_url}/api/v1/auth/verify",
                json={
                    "api_key": api_key,
                    "hardware_id": hardware_id
                },
                timeout=API_TIMEOUT
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "status": data.get("status", "active"),
                    "expires_at": data.get("expires_at"),
                    "subscription_type": data.get("subscription_type"),
                    "license_info": data,
                    "public_key": data.get("public_key")
                }

            elif response.status_code == 401:
                return {"status": "invalid_key"}

            elif response.status_code == 403:
                error = response.json()
                error_code = error.get("error_code")

                if error_code == "LICENSE_EXPIRED":
                    return {
                        "status": "expired",
                        "expires_at": error.get("expires_at")
                    }
                elif error_code == "HARDWARE_MISMATCH":
                    return {"status": "hardware_mismatch"}
                elif error_code == "SUSPENDED":
                    return {"status": "suspended"}
                else:
                    return {"status": "error", "message": error.get("message")}

            else:
                return {
                    "status": "error",
                    "message": f"Server error: {response.status_code}"
                }

        except Exception as e:
            log_error(f"Msm_29_3: Verification request failed: {e}")
            return self._mock_verify(api_key, hardware_id)

    def _mock_verify(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """Mock проверка для тестирования."""
        log_info("Msm_29_3: Using MOCK verification")

        license_data = MOCK_LICENSES.get(api_key)
        if not license_data:
            return {"status": "invalid_key"}

        # Проверяем привязку (если уже активирован)
        existing_hwid = self._mock_hardware_bindings.get(api_key)
        if existing_hwid and existing_hwid != hardware_id:
            return {"status": "hardware_mismatch"}

        # Автоматически привязываем если ещё не привязан
        if not existing_hwid:
            self._mock_hardware_bindings[api_key] = hardware_id

        return {
            "status": license_data.get("status", "active"),
            "expires_at": license_data.get("expires_at"),
            "subscription_type": license_data.get("subscription_type"),
            "license_info": license_data,
            "public_key": MOCK_PUBLIC_KEY
        }

    def deactivate(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """
        Деактивация лицензии.

        Освобождает привязку к Hardware ID.
        """
        if MOCK_MODE:
            return self._mock_deactivate(api_key, hardware_id)

        try:
            session = self._get_session()
            if not session:
                return self._mock_deactivate(api_key, hardware_id)

            response = session.post(
                f"{self.base_url}/api/v1/license/deactivate",
                json={
                    "api_key": api_key,
                    "hardware_id": hardware_id
                },
                timeout=API_TIMEOUT
            )

            if response.status_code == 200:
                return {"status": "success"}
            else:
                return {
                    "status": "error",
                    "message": f"Server error: {response.status_code}"
                }

        except Exception as e:
            log_error(f"Msm_29_3: Deactivation request failed: {e}")
            return self._mock_deactivate(api_key, hardware_id)

    def _mock_deactivate(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """Mock деактивация для тестирования."""
        log_info("Msm_29_3: Using MOCK deactivation")

        existing_hwid = self._mock_hardware_bindings.get(api_key)
        if existing_hwid != hardware_id:
            return {"status": "error", "message": "Hardware ID mismatch"}

        # Удаляем привязку
        self._mock_hardware_bindings.pop(api_key, None)
        return {"status": "success"}

    def report_hardware_change(
        self,
        api_key: str,
        old_hardware_id: str,
        new_hardware_id: str,
        changed_components: list
    ) -> Dict[str, Any]:
        """
        Отчёт о смене оборудования.

        Отправляется разработчику для рассмотрения.
        """
        if MOCK_MODE:
            log_info(f"Msm_29_3: MOCK hardware change report - components: {changed_components}")
            return {"status": "reported"}

        try:
            session = self._get_session()
            if not session:
                return {"status": "reported"}  # Mock

            response = session.post(
                f"{self.base_url}/api/v1/license/report-hardware-change",
                json={
                    "api_key": api_key,
                    "old_hardware_id": old_hardware_id,
                    "new_hardware_id": new_hardware_id,
                    "changed_components": changed_components
                },
                timeout=API_TIMEOUT
            )

            if response.status_code == 200:
                log_info("Msm_29_3: Hardware change reported")
                return {"status": "reported"}
            else:
                return {"status": "error"}

        except Exception as e:
            log_error(f"Msm_29_3: Failed to report hardware change: {e}")
            return {"status": "error", "message": str(e)}
