# -*- coding: utf-8 -*-
"""
Msm_29_3_LicenseValidator - Валидатор лицензии через Yandex Cloud API.

Выполняет:
- Активацию новой лицензии (POST ?action=validate&mode=activate)
- Проверку существующей лицензии (POST ?action=validate&mode=verify)
- Деактивацию лицензии (POST ?action=deactivate)

API: https://functions.yandexcloud.net/d4e9nvs008lt7sd87s7m
"""

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

    def activate(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """
        Активация лицензии через Yandex Cloud API.

        Args:
            api_key: Ключ активации
            hardware_id: Hardware ID компьютера

        Returns:
            Результат активации
        """
        log_info(f"Msm_29_3: Активация лицензии через API")

        try:
            session = self._get_session()
            if not session:
                return {"status": "error", "message": "requests library not available"}

            url = f"{self.base_url}?action=validate"
            response = session.post(
                url,
                json={
                    "api_key": api_key,
                    "hardware_id": hardware_id,
                    "mode": "activate"
                },
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
        log_info("Msm_29_3: Проверка лицензии через API")

        try:
            session = self._get_session()
            if not session:
                return {"status": "error", "message": "requests library not available"}

            url = f"{self.base_url}?action=validate"
            response = session.post(
                url,
                json={
                    "api_key": api_key,
                    "hardware_id": hardware_id,
                    "mode": "verify"
                },
                timeout=API_TIMEOUT
            )

            data = response.json()

            if response.status_code == 200 and data.get("status") == "success":
                license_info = data.get("license_info", {})
                log_info("Msm_29_3: Проверка успешна")
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
            response = session.post(
                url,
                json={
                    "api_key": api_key,
                    "hardware_id": hardware_id
                },
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
