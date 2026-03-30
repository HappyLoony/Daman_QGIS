# -*- coding: utf-8 -*-
"""
Msm_29_3_LicenseValidator - Валидатор лицензии через Daman API.

Выполняет:
- Активацию новой лицензии (POST /validate или ?action=validate&mode=activate)
- Проверку существующей лицензии (POST /validate или ?action=validate&mode=verify)
- Деактивацию лицензии (POST /deactivate или ?action=deactivate)
- Отчёт об использовании offline кэша (POST /report-offline или ?action=report_offline)

Безопасность:
- HMAC-SHA256 подпись запросов с API ключом пользователя как secret
- Каждый пользователь имеет уникальный ключ подписи
- Защита от replay attacks (timestamp validation на сервере)

API: constants.API_BASE_URL (daman.tools)
"""

import hashlib
import hmac
import time
from typing import Dict, Any, List

from Daman_QGIS.constants import API_BASE_URL, API_TIMEOUT, PLUGIN_VERSION, get_api_url
from Daman_QGIS.utils import log_info, log_error, log_warning

class LicenseValidator:
    """
    Валидатор лицензии через Daman API.

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
            self._create_session()
        return self._session

    def _create_session(self):
        """Создание новой requests session.

        Connection: close отключает keep-alive. Serverless-бэкенды
        агрессивно закрывают idle-соединения, что приводит к
        [CRYPTO] unknown error при SSL resumption на мёртвом TCP.
        """
        try:
            import requests
            self._session = requests.Session()
            self._session.headers.update({"Connection": "close"})
        except ImportError:
            log_warning("Msm_29_3: requests library not available")

    def _reset_session(self):
        """Пересоздание session (при SSL ошибках на протухшем соединении)."""
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
        self._create_session()

    def _generate_hmac_signature(self, api_key: str, hardware_id: str, timestamp: int) -> str:
        """
        Генерация HMAC-SHA256 подписи запроса.

        Используем API ключ пользователя как HMAC secret.

        Подписываем: hardware_id + timestamp
        Secret: api_key (уникален для каждого пользователя)

        ВАЖНО: Вся безопасность обеспечивается TLS (HTTPS).
        HMAC НЕ обеспечивает независимую защиту, т.к. api_key
        (secret) передаётся в том же запросе.

        НЕ защищает от:
        - Replay attacks (timestamp check независим от HMAC)
        - Перехвата (api_key в том же payload)
        - Подделки без TLS (secret доступен в запросе)

        Основная защита - TLS + server-side валидация api_key + hardware_id.

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
            "plugin_version": PLUGIN_VERSION,
            **extra
        }
        return payload

    def activate(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """
        Активация лицензии через Daman API.

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

            url = get_api_url("validate")
            payload = self._build_signed_payload(api_key, hardware_id, mode="activate")

            response = session.post(
                url,
                json=payload,
                timeout=API_TIMEOUT
            )

            data = response.json()

            if response.status_code == 200 and data.get("status") == "success":
                log_info("Msm_29_3: Активация успешна")
                result = {
                    "status": "success",
                    "license_info": data.get("license_info", {})
                }
                # JWT: прокидываем токены если сервер их выдал
                if "tokens" in data:
                    result["tokens"] = data["tokens"]
                return result

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
            elif error_code == "EXPIRED_TIMESTAMP":
                return {
                    "status": "error",
                    "message": "Рассинхронизация времени. Проверьте системное время ПК"
                }
            elif error_code == "INVALID_SIGNATURE":
                return {"status": "error", "message": "Ошибка подписи запроса"}
            else:
                return {"status": "error", "message": message}

        except Exception as e:
            if self._is_ssl_error(e):
                log_warning(f"Msm_29_3: SSL error during activation, retrying with new session")
                self._reset_session()
                try:
                    session = self._get_session()
                    if session:
                        response = session.post(
                            get_api_url("validate"),
                            json=self._build_signed_payload(api_key, hardware_id, mode="activate"),
                            timeout=API_TIMEOUT
                        )
                        data = response.json()
                        if response.status_code == 200 and data.get("status") == "success":
                            log_info("Msm_29_3: Активация успешна (после retry)")
                            result = {
                                "status": "success",
                                "license_info": data.get("license_info", {})
                            }
                            if "tokens" in data:
                                result["tokens"] = data["tokens"]
                            return result
                except Exception as retry_err:
                    log_error(f"Msm_29_3: Activation retry also failed: {retry_err}")
            log_error(f"Msm_29_3: Activation request failed: {e}")
            return {"status": "error", "message": f"Ошибка сети: {e}"}

    def _is_ssl_error(self, error: Exception) -> bool:
        """Проверка что ошибка связана с SSL (протухшее соединение)."""
        error_str = str(error).lower()
        return 'ssl' in error_str or 'crypto' in error_str

    def verify(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """
        Проверка лицензии через Daman API.

        При SSL ошибке (типично для OSGeo4W + протухшее соединение)
        пересоздаёт session и делает одну повторную попытку.

        Args:
            api_key: API ключ
            hardware_id: Hardware ID

        Returns:
            Результат проверки
        """
        result = self._verify_request(api_key, hardware_id)

        # Retry с новой session при SSL ошибке
        if result.get("_ssl_retry"):
            log_info("Msm_29_3: SSL ошибка, пересоздание session и повтор")
            self._reset_session()
            result = self._verify_request(api_key, hardware_id)

        result.pop("_ssl_retry", None)
        return result

    def _verify_request(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """Один запрос верификации."""
        try:
            session = self._get_session()
            if not session:
                return {"status": "error", "message": "requests library not available"}

            url = get_api_url("validate")
            payload = self._build_signed_payload(api_key, hardware_id, mode="verify")

            response = session.post(
                url,
                json=payload,
                timeout=API_TIMEOUT
            )

            data = response.json()

            if response.status_code == 200 and data.get("status") == "success":
                license_info = data.get("license_info", {})
                result = {
                    "status": "active",
                    "expires_at": license_info.get("expires_at"),
                    "subscription_type": license_info.get("subscription_type"),
                    "access_list": license_info.get("access_list", ["qgis"]),
                    "is_admin": license_info.get("is_admin", False),
                    "license_info": license_info
                }
                # JWT: прокидываем токены если сервер их выдал
                if "tokens" in data:
                    result["tokens"] = data["tokens"]
                return result

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
            if self._is_ssl_error(e):
                log_warning(f"Msm_29_3: SSL error (will retry): {e}")
                return {"status": "error", "message": str(e), "_ssl_retry": True}
            log_error(f"Msm_29_3: Verification request failed: {e}")
            return {"status": "error", "message": f"Ошибка сети: {e}"}

    def deactivate(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """
        Деактивация лицензии через Daman API.

        Освобождает привязку к Hardware ID.
        """
        log_info("Msm_29_3: Деактивация лицензии через API")

        try:
            session = self._get_session()
            if not session:
                return {"status": "error", "message": "requests library not available"}

            url = get_api_url("deactivate")
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

    def report_offline_usage(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """
        Отчёт об использовании offline кэша.

        Вызывается клиентом когда он использует кэшированную лицензию
        вместо онлайн-проверки (сервер недоступен).

        Позволяет серверу отслеживать consecutive offline периоды
        и применять OPT-2 лимиты.

        Args:
            api_key: API ключ
            hardware_id: Hardware ID

        Returns:
            {"status": "success"} или {"status": "error", "error_code": "...", "message": "..."}
        """
        try:
            session = self._get_session()
            if not session:
                # Нет сети - ожидаемо, просто логируем локально
                return {"status": "offline"}

            url = get_api_url("report_offline")
            payload = self._build_signed_payload(api_key, hardware_id)

            response = session.post(
                url,
                json=payload,
                timeout=API_TIMEOUT
            )

            data = response.json()

            if response.status_code == 200 and data.get("status") == "success":
                return {"status": "success"}

            # Обработка ошибок
            error_code = data.get("error_code", "")
            message = data.get("message", "Unknown error")

            if error_code == "OFFLINE_LIMIT_EXCEEDED":
                log_warning(f"Msm_29_3: Offline limit exceeded - {message}")
                return {
                    "status": "blocked",
                    "error_code": error_code,
                    "message": message
                }

            return {"status": "error", "message": message}

        except Exception as e:
            # Сеть недоступна - ожидаемо при offline usage
            return {"status": "offline"}
