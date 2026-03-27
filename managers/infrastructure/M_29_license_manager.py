# -*- coding: utf-8 -*-
"""
M_29_LicenseManager - Менеджер лицензирования Daman QGIS.

Отвечает за:
- Генерацию Hardware ID (привязка к оборудованию)
- Хранение API ключа (QSettings)
- Проверку лицензии на сервере (fail-closed)
- Управление подпиской

Зависимости:
- Msm_29_1_HardwareIDGenerator - генерация Hardware ID
- Msm_29_2_LicenseStorage - хранение API ключа (QSettings)
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
    - Хранение API ключа (QSettings)
    - Проверку лицензии на сервере (fail-closed)
    - Управление подпиской
    """

    # Сигналы
    license_validated = pyqtSignal(bool)           # is_valid
    license_expired = pyqtSignal(str)              # expiry_date

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
            # Инициализация хранилища (QSettings)
            if not self._storage.initialize():
                log_error("M_29: Failed to initialize storage")
                return False

            # Генерация Hardware ID
            self._hardware_id = self._hardware.generate()
            if not self._hardware_id:
                log_error("M_29: Failed to generate Hardware ID")
                return False

            self._initialized = True
            log_info(f"M_29: Initialized (Hardware ID: {self._hardware_id[:16]}...)")
            return True

        except Exception as e:
            log_error(f"M_29: Initialization failed: {e}")
            return False

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
                # Сохранение ключа в QSettings
                self._storage.save_api_key(api_key)

                self._license_info = result.get("license_info")
                self._status = LicenseStatus.VALID

                # Инициализация телеметрии после успешной активации
                self._init_telemetry_after_activation(api_key)

                # JWT: сохранение токенов в RAM если сервер их выдал
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

                # JWT: сохранение/обновление токенов в RAM если сервер их выдал
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
        """Email пользователя из лицензии.

        API daman.tools возвращает user_email из таблицы user (JOIN).
        Если лицензия не привязана к аккаунту -- пустая строка "".
        """
        if self._license_info:
            email = self._license_info.get("user_email", "")
            if email and email not in ("", "-"):
                return email
        return None

    # === JWT Token Management ===

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
        Сохранение JWT токенов из ответа сервера в TokenManager (RAM).

        Вызывается после успешной activate() и verify().
        Если сервер не выдал токены - игнорируем.

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
                # Очистка JWT токенов (RAM)
                TokenManager.reset_instance()

                # Очистка QSettings
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
