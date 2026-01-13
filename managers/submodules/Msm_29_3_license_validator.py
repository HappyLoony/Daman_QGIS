# -*- coding: utf-8 -*-
"""
Msm_29_3_LicenseValidator - Валидатор лицензии через API сервер.

Выполняет:
- Активацию новой лицензии
- Проверку существующей лицензии
- Деактивацию лицензии

SIMULATION MODE: Использует Base_licenses.json с GitHub Raw для симуляции работы сервера.
Когда API сервер будет готов, переключить USE_REMOTE_LICENSES = False.
"""

from datetime import datetime
from typing import Dict, Any, Optional, List

from ...constants import API_BASE_URL, API_TIMEOUT
from ...utils import log_info, log_error, log_warning

# Флаг режима симуляции через Base_licenses.json (True пока нет реального сервера)
USE_REMOTE_LICENSES = True

# Mock public key (для тестирования, НЕ использовать в production)
MOCK_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0Z3VS5JJcds3xfn/ygWyf
Mockt3st1ngK3yOnlyForT3st1ng0nlyNotForProduct1on
MOCK_KEY_DO_NOT_USE_IN_PRODUCTION
-----END PUBLIC KEY-----"""


class LicenseValidator:
    """
    Валидатор лицензии через API сервер.

    В режиме симуляции (USE_REMOTE_LICENSES=True) загружает лицензии
    из Base_licenses.json через BaseReferenceLoader.
    """

    # Кэш лицензий (загружается один раз за сессию через BaseReferenceLoader)
    _licenses_cache: Optional[Dict[str, Dict[str, Any]]] = None

    def __init__(self):
        self.base_url = API_BASE_URL
        self._session = None
        self._hardware_bindings: Dict[str, str] = {}  # api_key -> hardware_id

    @classmethod
    def _load_licenses(cls) -> Dict[str, Dict[str, Any]]:
        """
        Загрузка лицензий из Base_licenses.json через BaseReferenceLoader.

        Returns:
            Dict {api_key: license_data}
        """
        if cls._licenses_cache is not None:
            log_info(f"Msm_29_3: Используем кэш лицензий ({len(cls._licenses_cache)} записей)")
            return cls._licenses_cache

        try:
            from ...database.base_reference_loader import BaseReferenceLoader

            loader = BaseReferenceLoader()
            log_info("Msm_29_3: Загружаем Base_licenses.json...")
            data = loader._load_json('Base_licenses.json')

            if data is None:
                log_warning("Msm_29_3: Base_licenses.json не найден, лицензирование недоступно")
                cls._licenses_cache = {}
                return cls._licenses_cache

            log_info(f"Msm_29_3: Получено {len(data)} записей из JSON")

            # Преобразуем список в словарь по api_key
            licenses = {}
            for record in data:
                api_key = record.get('api_key')
                if api_key:
                    licenses[api_key] = {
                        "user_name": record.get('user_name'),
                        "user_email": record.get('user_email'),
                        "subscription_type": record.get('subscription_type'),
                        "starts_at": record.get('starts_at'),
                        "expires_at": record.get('expires_at'),
                        "hardware_id": record.get('hardware_id'),  # Привязка к ПК из Excel
                        "notes": record.get('notes'),
                        "features": ["basic", "export_dxf", "export_tab"]  # Базовые функции
                    }
                    log_info(f"Msm_29_3: Добавлен ключ {api_key} (hardware_id: {record.get('hardware_id', 'не задан')})")

            cls._licenses_cache = licenses
            log_info(f"Msm_29_3: Загружено {len(licenses)} лицензий из Base_licenses.json")
            log_info(f"Msm_29_3: Доступные ключи: {list(licenses.keys())}")
            return cls._licenses_cache

        except Exception as e:
            log_error(f"Msm_29_3: Ошибка загрузки лицензий: {e}")
            import traceback
            log_error(f"Msm_29_3: Traceback: {traceback.format_exc()}")
            cls._licenses_cache = {}
            return cls._licenses_cache

    @classmethod
    def clear_cache(cls):
        """Очистить кэш лицензий."""
        cls._licenses_cache = None

    def _check_license_expiry(self, license_data: Dict[str, Any]) -> str:
        """
        Проверка срока действия лицензии.

        Args:
            license_data: Данные лицензии

        Returns:
            Статус: "active", "expired", "not_started"
        """
        subscription_type = license_data.get("subscription_type", "")
        expires_at = license_data.get("expires_at")
        starts_at = license_data.get("starts_at")

        now = datetime.now()

        # Проверка даты начала
        if starts_at:
            try:
                start_date = datetime.strptime(starts_at.split()[0], "%Y-%m-%d")
                if now < start_date:
                    return "not_started"
            except (ValueError, TypeError):
                pass

        # Бессрочная лицензия
        if subscription_type == "Бессрочно" or expires_at is None:
            return "active"

        # Проверка срока истечения
        if expires_at:
            try:
                # Поддержка формата "YYYY-MM-DD" и "YYYY-MM-DDTHH:MM:SSZ"
                if "T" in str(expires_at):
                    expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00").replace("+00:00", ""))
                else:
                    expiry = datetime.strptime(expires_at, "%Y-%m-%d")

                if now > expiry:
                    return "expired"
            except (ValueError, TypeError) as e:
                log_warning(f"Msm_29_3: Ошибка парсинга expires_at '{expires_at}': {e}")

        return "active"

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
        if USE_REMOTE_LICENSES:
            return self._simulate_activate(api_key, hardware_id)

        try:
            session = self._get_session()
            if not session:
                return self._simulate_activate(api_key, hardware_id)

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
            # Fallback to simulation mode
            return self._simulate_activate(api_key, hardware_id)

    def _simulate_activate(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """
        Симуляция активации через Base_licenses.json.

        Загружает лицензии с GitHub Raw и проверяет ключ.
        """
        log_info("Msm_29_3: Using SIMULATION activation (Base_licenses.json)")
        log_info(f"Msm_29_3: Проверяем ключ: '{api_key}'")

        # Загружаем лицензии
        licenses = self._load_licenses()

        log_info(f"Msm_29_3: Поиск ключа в {len(licenses)} лицензиях")

        # Проверяем ключ
        license_data = licenses.get(api_key)
        if not license_data:
            log_warning(f"Msm_29_3: Ключ '{api_key}' не найден в базе")
            log_info(f"Msm_29_3: Доступные ключи: {list(licenses.keys())}")
            return {"status": "invalid_key"}

        # Проверяем срок действия
        status = self._check_license_expiry(license_data)
        if status == "expired":
            return {"status": "expired", "expires_at": license_data.get("expires_at")}
        if status == "not_started":
            return {"status": "error", "message": "Лицензия ещё не активна"}

        # Проверяем привязку к hardware_id
        stored_hwid = license_data.get("hardware_id")
        log_info(f"Msm_29_3: Проверка привязки: stored={stored_hwid}, current={hardware_id}")

        if stored_hwid:
            # Если в базе есть hardware_id - проверяем совпадение
            if stored_hwid != hardware_id:
                log_warning(f"Msm_29_3: Ключ уже привязан к другому ПК: {stored_hwid}")
                return {"status": "already_bound"}
        else:
            # Если hardware_id не задан - первая активация, запоминаем в памяти
            # (в реальной системе здесь будет запись на сервер)
            log_info(f"Msm_29_3: Первая активация, привязываем к {hardware_id}")
            self._hardware_bindings[api_key] = hardware_id

        return {
            "status": "success",
            "license_info": {
                "status": "active",
                "subscription_type": license_data.get("subscription_type"),
                "expires_at": license_data.get("expires_at"),
                "user_name": license_data.get("user_name"),
                "user_email": license_data.get("user_email"),
                "features": license_data.get("features", [])
            },
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
        if USE_REMOTE_LICENSES:
            return self._simulate_verify(api_key, hardware_id)

        try:
            session = self._get_session()
            if not session:
                return self._simulate_verify(api_key, hardware_id)

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
            return self._simulate_verify(api_key, hardware_id)

    def _simulate_verify(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """
        Симуляция проверки лицензии через Base_licenses.json.
        """
        log_info("Msm_29_3: Using SIMULATION verification (Base_licenses.json)")

        # Загружаем лицензии
        licenses = self._load_licenses()

        license_data = licenses.get(api_key)
        if not license_data:
            return {"status": "invalid_key"}

        # Проверяем привязку к hardware_id из JSON
        stored_hwid = license_data.get("hardware_id")

        if stored_hwid:
            # Если в базе есть hardware_id - проверяем совпадение
            if stored_hwid != hardware_id:
                log_warning(f"Msm_29_3: Hardware mismatch: stored={stored_hwid}, current={hardware_id}")
                return {"status": "hardware_mismatch"}
        else:
            # Проверяем привязку в памяти (для первой активации в сессии)
            existing_hwid = self._hardware_bindings.get(api_key)
            if existing_hwid and existing_hwid != hardware_id:
                return {"status": "hardware_mismatch"}
            # Автоматически привязываем если ещё не привязан
            if not existing_hwid:
                self._hardware_bindings[api_key] = hardware_id

        # Проверяем срок действия
        status = self._check_license_expiry(license_data)
        if status == "expired":
            return {
                "status": "expired",
                "expires_at": license_data.get("expires_at")
            }

        return {
            "status": "active",
            "expires_at": license_data.get("expires_at"),
            "subscription_type": license_data.get("subscription_type"),
            "license_info": {
                "status": "active",
                "subscription_type": license_data.get("subscription_type"),
                "expires_at": license_data.get("expires_at"),
                "user_name": license_data.get("user_name"),
                "user_email": license_data.get("user_email"),
                "features": license_data.get("features", [])
            },
            "public_key": MOCK_PUBLIC_KEY
        }

    def deactivate(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """
        Деактивация лицензии.

        Освобождает привязку к Hardware ID.
        """
        if USE_REMOTE_LICENSES:
            return self._simulate_deactivate(api_key, hardware_id)

        try:
            session = self._get_session()
            if not session:
                return self._simulate_deactivate(api_key, hardware_id)

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
            return self._simulate_deactivate(api_key, hardware_id)

    def _simulate_deactivate(self, api_key: str, hardware_id: str) -> Dict[str, Any]:
        """
        Симуляция деактивации лицензии.

        В режиме симуляции просто возвращаем успех - реальная деактивация
        будет на сервере, который обнулит hardware_id в базе.
        """
        log_info("Msm_29_3: Using SIMULATION deactivation (Base_licenses.json)")

        # Загружаем лицензии для проверки
        licenses = self._load_licenses()
        license_data = licenses.get(api_key)

        if not license_data:
            log_warning(f"Msm_29_3: Ключ '{api_key}' не найден при деактивации")
            return {"status": "error", "message": "Ключ не найден"}

        # Проверяем что деактивируем с правильного ПК
        stored_hwid = license_data.get("hardware_id")
        if stored_hwid and stored_hwid != hardware_id:
            log_warning(f"Msm_29_3: Деактивация с неверного ПК: stored={stored_hwid}, current={hardware_id}")
            return {"status": "error", "message": "Деактивация возможна только с привязанного ПК"}

        # В симуляции просто удаляем из памяти (реальный сервер обнулит hardware_id)
        self._hardware_bindings.pop(api_key, None)
        log_info(f"Msm_29_3: Лицензия {api_key} деактивирована (симуляция)")
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
        if USE_REMOTE_LICENSES:
            log_info(f"Msm_29_3: SIMULATION hardware change report - components: {changed_components}")
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
