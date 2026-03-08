# -*- coding: utf-8 -*-
"""
M_29_LicenseManager - Менеджер лицензирования Daman QGIS.

Отвечает за:
- Генерацию Hardware ID (привязка к оборудованию)
- Хранение API ключа и JWT токенов
- Проверку лицензии на сервере
- Управление подпиской

Зависимости:
- Msm_29_1_HardwareIDGenerator - генерация Hardware ID
- Msm_29_2_LicenseStorage - хранение данных лицензии
- Msm_29_3_LicenseValidator - валидация на сервере
"""

from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum

from qgis.PyQt.QtCore import QObject, pyqtSignal

from .submodules.Msm_29_1_hardware_id import HardwareIDGenerator
from .submodules.Msm_29_2_license_storage import LicenseStorage
from .submodules.Msm_29_3_license_validator import LicenseValidator
from .submodules.Msm_29_4_token_manager import TokenManager

from Daman_QGIS.utils import log_info, log_error, log_warning

__all__ = [
    'LicenseStatus', 'LicenseManager',
    # Субменеджеры (реэкспорт для from Daman_QGIS.managers import X)
    'HardwareIDGenerator', 'LicenseStorage', 'LicenseValidator', 'TokenManager',
]


class LicenseStatus(Enum):
    """Статусы лицензии."""
    VALID = "valid"
    EXPIRED = "expired"
    INVALID_KEY = "invalid_key"
    HARDWARE_MISMATCH = "hardware_mismatch"
    NOT_ACTIVATED = "not_activated"
    SERVER_ERROR = "server_error"
    SUSPENDED = "suspended"



class LicenseManager(QObject):
    """
    Менеджер лицензирования.

    Отвечает за:
    - Генерацию Hardware ID
    - Хранение API ключа
    - Проверку лицензии на сервере
    - Управление подпиской
    """

    # Сигналы
    license_validated = pyqtSignal(bool)           # is_valid
    license_expired = pyqtSignal(str)              # expiry_date
    hardware_changed = pyqtSignal(str, str)        # old_id, new_id

    def __init__(self):
        super().__init__()

        # Субменеджеры
        self._hardware = HardwareIDGenerator()
        self._storage = LicenseStorage()
        self._validator = LicenseValidator()

        # Состояние
        self._hardware_id: Optional[str] = None
        self._license_info: Optional[Dict[str, Any]] = None
        self._status: LicenseStatus = LicenseStatus.NOT_ACTIVATED
        self._initialized: bool = False
        self._session_verified: bool = False  # Кэш проверки на время сессии

    def initialize(self) -> bool:
        """Инициализация менеджера."""
        if self._initialized:
            return True

        try:
            # Инициализация хранилища
            if not self._storage.initialize():
                log_error("M_29: Failed to initialize storage")
                return False

            # Генерация Hardware ID
            self._hardware_id = self._hardware.generate()
            if not self._hardware_id:
                log_error("M_29: Failed to generate Hardware ID")
                return False

            # Проверка fallback файла (восстановление при сбое профиля)
            self._check_hardware_fallback()

            # Сохранение Hardware ID в fallback файл
            self._storage.save_fallback_hardware_id(self._hardware_id)

            self._initialized = True
            log_info(f"M_29: Initialized (Hardware ID: {self._hardware_id[:16]}...)")
            return True

        except Exception as e:
            log_error(f"M_29: Initialization failed: {e}")
            return False

    def _check_hardware_fallback(self):
        """Проверка совпадения Hardware ID с fallback файлом."""
        stored_hwid = self._storage.get_fallback_hardware_id()
        if stored_hwid and stored_hwid != self._hardware_id:
            # Hardware ID изменился - возможно смена оборудования
            log_warning(f"M_29: Hardware ID mismatch detected")
            self.hardware_changed.emit(stored_hwid, self._hardware_id)

    def get_api_key(self) -> Optional[str]:
        """Получение API ключа."""
        return self._storage.get_api_key()

    def get_hardware_id(self) -> str:
        """Получение Hardware ID."""
        if not self._hardware_id:
            self._hardware_id = self._hardware.generate()
        return self._hardware_id or ""

    def is_activated(self) -> bool:
        """Проверка активации."""
        return self._storage.has_api_key()

    def check_access(self) -> bool:
        """
        Проверка доступа к функциям плагина.

        Используется BaseTool для блокировки функций без лицензии.
        Кэширует результат на время сессии QGIS.
        Требует подключение к серверу -- при недоступности сервера доступ запрещён.

        Returns:
            True если доступ разрешён
        """
        # Кэш на уровне сессии - не проверять при каждом вызове функции
        if self._session_verified and self._status == LicenseStatus.VALID:
            return True

        if not self._initialized:
            if not self.initialize():
                log_warning("M_29: check_access - initialization failed, denying access")
                return False

        if not self.is_activated():
            log_info("M_29: check_access - not activated")
            return False

        # Проверяем на сервере (интернет обязателен)
        result = self.verify()
        if result:
            self._session_verified = True
            return True

        # Сервер недоступен или лицензия невалидна -- запрещаем доступ
        if self._status == LicenseStatus.SERVER_ERROR:
            log_warning("M_29: check_access - server unreachable, denying access (internet required)")

        return False

    def activate(self, api_key: str) -> tuple:
        """
        Активация лицензии.

        Args:
            api_key: API ключ для активации

        Returns:
            (success: bool, message: str)
        """
        if not self._initialized:
            if not self.initialize():
                return False, "Ошибка инициализации менеджера лицензий"

        try:
            # Проверка ключа на сервере
            result = self._validator.activate(
                api_key=api_key,
                hardware_id=self._hardware_id
            )

            if result["status"] == "success":
                # Сохранение ключа
                self._storage.save_api_key(api_key)

                # Сохранение компонентов оборудования для check_hardware_changes()
                self._storage.save_hardware_components(self._hardware.get_components())

                # Сохранение public key для offline валидации
                public_key = result.get("public_key")
                if public_key:
                    self._storage.save_public_key(public_key)

                self._license_info = result.get("license_info")
                self._status = LicenseStatus.VALID

                # Инициализация телеметрии после успешной активации
                # (если плагин был запущен без лицензии, телеметрия была пропущена)
                self._init_telemetry_after_activation(api_key)

                # JWT: сохранение токенов если сервер их выдал
                self._store_jwt_tokens(result, self._hardware_id)

                log_info("M_29: License activated successfully")
                self.license_validated.emit(True)
                return True, "Лицензия активирована успешно"

            elif result["status"] == "already_bound":
                return False, "Ключ уже привязан к другому компьютеру"

            elif result["status"] == "invalid_key":
                return False, "Неверный ключ активации"

            elif result["status"] == "expired":
                return False, "Срок действия ключа истёк"

            else:
                return False, result.get("message", "Неизвестная ошибка")

        except Exception as e:
            log_error(f"M_29: Activation failed: {e}")
            return False, f"Ошибка активации: {e}"

    def verify(self) -> bool:
        """
        Проверка текущей лицензии.

        Returns:
            True если лицензия валидна
        """
        if not self._initialized:
            if not self.initialize():
                return False

        if not self.is_activated():
            self._status = LicenseStatus.NOT_ACTIVATED
            return False

        api_key = self.get_api_key()

        try:
            result = self._validator.verify(
                api_key=api_key,
                hardware_id=self._hardware_id
            )

            if result["status"] == "active":
                self._license_info = result.get("license_info")
                self._status = LicenseStatus.VALID

                # Обновляем public key если получен
                public_key = result.get("public_key")
                if public_key:
                    self._storage.save_public_key(public_key)

                # Проверка срока
                expires_at = result.get("expires_at")
                if expires_at:
                    try:
                        expiry_date = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                        days_left = (expiry_date - datetime.now(expiry_date.tzinfo)).days

                        if days_left <= 7:
                            log_warning(f"M_29: License expires in {days_left} days")
                    except Exception:
                        pass

                # Сохраняем время успешной проверки
                self._storage.save_last_verification()

                # JWT: сохранение/обновление токенов если сервер их выдал
                self._store_jwt_tokens(result, self._hardware_id)

                self.license_validated.emit(True)
                return True

            elif result["status"] == "expired":
                self._status = LicenseStatus.EXPIRED
                self.license_expired.emit(result.get("expires_at", ""))
                return False

            elif result["status"] == "hardware_mismatch":
                self._status = LicenseStatus.HARDWARE_MISMATCH
                log_error("M_29: Hardware ID mismatch")
                return False

            elif result["status"] == "suspended":
                self._status = LicenseStatus.SUSPENDED
                return False

            else:
                self._status = LicenseStatus.INVALID_KEY
                return False

        except Exception as e:
            log_error(f"M_29: Verification failed: {e}")
            self._status = LicenseStatus.SERVER_ERROR
            # FAIL-CLOSED: при ошибке сервера -- запрещаем доступ (интернет обязателен)
            return False

    def verify_for_display(self) -> tuple:
        """Проверка лицензии для отображения в UI без мутации сессии.

        F_4_3 использует этот метод чтобы показать актуальный статус
        без порчи _session_verified / _status работающей сессии.

        Returns:
            (is_valid: bool, display_status: LicenseStatus)
        """
        saved_verified = self._session_verified
        saved_status = self._status

        result = self.verify()
        display_status = self._status

        # Восстанавливаем состояние сессии если она была валидна,
        # а verify упал из-за транзиентной ошибки (SSL, сеть)
        if saved_verified and saved_status == LicenseStatus.VALID and not result:
            self._session_verified = saved_verified
            self._status = saved_status

        return result, display_status

    def get_status(self) -> LicenseStatus:
        """Текущий статус лицензии."""
        return self._status

    def get_license_info(self) -> Optional[Dict[str, Any]]:
        """Информация о лицензии."""
        return self._license_info

    def get_expiry_date(self) -> Optional[str]:
        """Дата истечения лицензии."""
        if self._license_info:
            return self._license_info.get("expires_at")
        return None

    def get_subscription_type(self) -> Optional[str]:
        """Тип подписки (Месяц/Бессрочно)."""
        if self._license_info:
            return self._license_info.get("subscription_type")
        return None

    def get_user_email(self) -> Optional[str]:
        """Email пользователя из лицензии."""
        if self._license_info:
            email = self._license_info.get("user_email", "")
            if email and email != "-":
                return email
        return None

    # === JWT Token Management (для M_30_NetworkManager) ===

    def get_stored_tokens(self) -> Dict[str, Any]:
        """
        Получение сохранённых JWT токенов.

        Используется NetworkManager при инициализации для
        восстановления токенов между сессиями.

        Returns:
            Dict с ключами: access_token, refresh_token, access_expires_at
        """
        return {
            "access_token": self._storage.get_access_token(),
            "refresh_token": self._storage.get_refresh_token(),
            "access_expires_at": self._storage.get_access_expires_at()
        }

    def store_tokens(self, tokens: Dict[str, Any]):
        """
        Сохранение JWT токенов.

        Вызывается NetworkManager после получения/обновления токенов.

        Args:
            tokens: Dict с ключами access_token, refresh_token, access_expires_at
        """
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        access_expires_at = tokens.get("access_expires_at")

        if access_token and refresh_token:
            self._storage.save_tokens(access_token, refresh_token, access_expires_at)
        elif access_token:
            self._storage.update_access_token(access_token, access_expires_at)

    def get_public_key(self) -> Optional[str]:
        """Получение RS256 public key для offline валидации JWT."""
        return self._storage.get_public_key()

    def _init_telemetry_after_activation(self, api_key: str) -> None:
        """
        Инициализация телеметрии после успешной активации лицензии.

        Вызывается когда плагин был запущен без лицензии, а затем
        пользователь активировал лицензию через F_4_3.
        """
        try:
            from Daman_QGIS.managers._registry import registry
            from .submodules.Msm_32_1_global_exception_hook import install_global_exception_hook

            telemetry = registry.get('M_32')

            # Проверяем, не была ли телеметрия уже инициализирована
            if telemetry._uid:
                log_info("M_29: Telemetry already initialized, skipping")
                return

            # Устанавливаем UID и Hardware ID
            telemetry.set_uid(api_key, self._hardware_id)

            # Устанавливаем глобальный перехват исключений
            install_global_exception_hook()

            # Отправляем событие активации
            telemetry.track_event('license_activated')

            log_info("M_29: Telemetry initialized after license activation")

        except Exception as e:
            log_warning(f"M_29: Failed to init telemetry after activation: {e}")

    def _store_jwt_tokens(self, server_result: Dict[str, Any], hardware_id: str) -> None:
        """
        Сохранение JWT токенов из ответа сервера в TokenManager.

        Вызывается после успешной activate() и verify().
        Если сервер не выдал токены - игнорируем (обратная совместимость Phase 2).

        Args:
            server_result: Ответ сервера с опциональным ключом "tokens"
            hardware_id: Hardware ID текущего ПК
        """
        tokens = server_result.get("tokens")
        if not tokens:
            return

        try:
            token_mgr = TokenManager.get_instance()
            token_mgr.set_tokens_from_response(tokens, hardware_id)

            # Устанавливаем callback для полного отказа аутентификации
            token_mgr.set_on_auth_failure(self._on_jwt_auth_failure)

        except Exception as e:
            log_warning(f"M_29: Failed to store JWT tokens: {e}")

    def _on_jwt_auth_failure(self) -> None:
        """
        Callback при полном отказе JWT аутентификации.

        Вызывается TokenManager когда и access, и refresh невалидны.
        Сбрасывает session_verified, принудительная повторная проверка лицензии.
        """
        log_warning("M_29: JWT auth failure - forcing re-verification")
        self._session_verified = False

    def deactivate(self) -> bool:
        """
        Деактивация лицензии на текущем ПК.

        Очищает локальные данные лицензии и JWT токены.
        Для переноса на другой компьютер свяжитесь с разработчиком.
        """
        try:
            api_key = self.get_api_key()
            if not api_key:
                return False

            result = self._validator.deactivate(
                api_key=api_key,
                hardware_id=self._hardware_id
            )

            if result["status"] == "success":
                # Очистка JWT токенов
                TokenManager.reset_instance()

                self._storage.clear()
                self._license_info = None
                self._status = LicenseStatus.NOT_ACTIVATED
                self._session_verified = False
                log_info(
                    "M_29: Local license data cleared. "
                    "Contact developer to complete transfer to another device."
                )
                return True

            return False

        except Exception as e:
            log_error(f"M_29: Deactivation failed: {e}")
            return False

    def check_hardware_changes(self) -> Optional[Dict[str, Any]]:
        """
        Проверка изменений в оборудовании.

        Returns:
            Dict с информацией об изменениях или None
        """
        stored_components = self._storage.get_hardware_components()
        if not stored_components:
            return None

        current_components = self._hardware.get_components()

        changes = {}
        for key, stored_value in stored_components.items():
            current_value = current_components.get(key)
            if current_value != stored_value:
                changes[key] = {
                    "old": stored_value,
                    "new": current_value
                }

        if changes:
            log_warning(f"M_29: Hardware changes detected: {list(changes.keys())}")
            return changes

        return None
