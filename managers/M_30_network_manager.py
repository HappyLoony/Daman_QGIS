# -*- coding: utf-8 -*-
"""
M_30_NetworkManager - HTTP клиент с JWT авторизацией.

Отвечает за:
- Авторизованные HTTP запросы к API
- Управление JWT токенами (access/refresh)
- Offline валидация токенов через RS256
- Кэширование ответов

Зависимости:
- Msm_30_1_TokenManager - управление JWT токенами
- Msm_30_2_RequestHandler - HTTP запросы с retry
- Msm_30_3_CacheManager - кэширование ответов
- M_29_LicenseManager - хранение токенов
"""

from typing import Optional, Dict, Any, Callable
from enum import Enum

from qgis.PyQt.QtCore import QObject, pyqtSignal

from .submodules.Msm_30_1_token_manager import TokenManager
from .submodules.Msm_30_2_request_handler import RequestHandler, RequestError
from .submodules.Msm_30_3_cache_manager import CacheManager

from ..utils import log_info, log_error, log_warning
from ..constants import API_BASE_URL, API_TIMEOUT


class NetworkStatus(Enum):
    """Статус сетевого подключения."""
    ONLINE = "online"
    OFFLINE = "offline"
    AUTH_REQUIRED = "auth_required"
    TOKEN_EXPIRED = "token_expired"
    SERVER_ERROR = "server_error"


# Синглтон для глобального доступа
_network_manager_instance: Optional['NetworkManager'] = None


def get_network_manager() -> 'NetworkManager':
    """Получить экземпляр NetworkManager (синглтон)."""
    global _network_manager_instance
    if _network_manager_instance is None:
        _network_manager_instance = NetworkManager()
    return _network_manager_instance


def reset_network_manager():
    """Сбросить синглтон (для тестов)."""
    global _network_manager_instance
    if _network_manager_instance:
        _network_manager_instance.cleanup()
    _network_manager_instance = None


class NetworkManager(QObject):
    """
    HTTP клиент с JWT авторизацией.

    Особенности:
    - Автоматическое обновление access token при истечении
    - Ротация refresh token при обновлении
    - Offline валидация через RS256 public key
    - Кэширование ответов с TTL
    """

    # Сигналы
    token_refreshed = pyqtSignal()              # Токен обновлён
    auth_required = pyqtSignal()                # Требуется авторизация
    network_error = pyqtSignal(str)             # Сетевая ошибка
    status_changed = pyqtSignal(NetworkStatus)  # Изменение статуса

    def __init__(self):
        super().__init__()

        # Субменеджеры
        self._token_manager = TokenManager()
        self._request_handler = RequestHandler()
        self._cache = CacheManager()

        # Состояние
        self._status: NetworkStatus = NetworkStatus.OFFLINE
        self._initialized: bool = False

    def initialize(self) -> bool:
        """Инициализация менеджера."""
        if self._initialized:
            return True

        try:
            # Инициализация субменеджеров
            if not self._token_manager.initialize():
                log_warning("M_30: Token manager initialization failed")

            if not self._cache.initialize():
                log_warning("M_30: Cache initialization failed")

            # Настройка request handler
            self._request_handler.set_token_provider(self._get_access_token)
            self._request_handler.set_token_refresher(self._refresh_token)

            self._initialized = True
            log_info("M_30: Initialized")
            return True

        except Exception as e:
            log_error(f"M_30: Initialization failed: {e}")
            return False

    def cleanup(self):
        """Очистка ресурсов."""
        self._cache.clear()
        self._initialized = False

    # =========================================================================
    # Публичные методы для HTTP запросов
    # =========================================================================

    def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        use_cache: bool = True,
        cache_ttl: int = 3600
    ) -> Optional[Dict[str, Any]]:
        """
        GET запрос к API.

        Args:
            endpoint: Путь API (например, "/api/v1/versions")
            params: Query параметры
            use_cache: Использовать кэш
            cache_ttl: Время жизни кэша в секундах

        Returns:
            JSON ответ или None при ошибке
        """
        if not self._initialized:
            if not self.initialize():
                return None

        # Проверка кэша
        cache_key = self._cache.make_key(endpoint, params)
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        try:
            response = self._request_handler.get(endpoint, params)

            # Сохранение в кэш
            if use_cache and response:
                self._cache.set(cache_key, response, cache_ttl)

            self._update_status(NetworkStatus.ONLINE)
            return response

        except RequestError as e:
            self._handle_request_error(e)
            return None

    def post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        POST запрос к API.

        Args:
            endpoint: Путь API
            data: Form data
            json_data: JSON body

        Returns:
            JSON ответ или None при ошибке
        """
        if not self._initialized:
            if not self.initialize():
                return None

        try:
            response = self._request_handler.post(endpoint, data, json_data)
            self._update_status(NetworkStatus.ONLINE)
            return response

        except RequestError as e:
            self._handle_request_error(e)
            return None

    def download(
        self,
        endpoint: str,
        save_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> bool:
        """
        Скачивание файла.

        Args:
            endpoint: Путь API
            save_path: Путь для сохранения
            progress_callback: Callback(downloaded, total)

        Returns:
            True если успешно
        """
        if not self._initialized:
            if not self.initialize():
                return False

        try:
            return self._request_handler.download(endpoint, save_path, progress_callback)

        except RequestError as e:
            self._handle_request_error(e)
            return False

    # =========================================================================
    # Статус и информация
    # =========================================================================

    def get_status(self) -> NetworkStatus:
        """Текущий статус сети."""
        return self._status

    def is_online(self) -> bool:
        """Проверка доступности сети."""
        return self._status == NetworkStatus.ONLINE

    def check_connectivity(self) -> bool:
        """
        Проверка подключения к серверу.

        Returns:
            True если сервер доступен
        """
        try:
            response = self._request_handler.get("/api/v1/health", auth=False)
            if response and response.get("status") == "ok":
                self._update_status(NetworkStatus.ONLINE)
                return True
        except Exception:
            pass

        self._update_status(NetworkStatus.OFFLINE)
        return False

    def has_valid_token(self) -> bool:
        """Проверка валидности текущего токена."""
        return self._token_manager.has_valid_token()

    # =========================================================================
    # Авторизация
    # =========================================================================

    def login(self, api_key: str, hardware_id: str) -> tuple:
        """
        Авторизация по API ключу.

        Args:
            api_key: API ключ лицензии
            hardware_id: Hardware ID

        Returns:
            (success: bool, message: str)
        """
        try:
            response = self._request_handler.post(
                "/api/v1/auth/login",
                json_data={
                    "api_key": api_key,
                    "hardware_id": hardware_id
                },
                auth=False
            )

            if response and response.get("access_token"):
                # Сохранение токенов
                self._token_manager.store_tokens(
                    access_token=response["access_token"],
                    refresh_token=response["refresh_token"],
                    access_expires_at=response.get("access_expires_at")
                )

                self._update_status(NetworkStatus.ONLINE)
                log_info("M_30: Login successful")
                return True, "Авторизация успешна"

            return False, response.get("message", "Неизвестная ошибка")

        except RequestError as e:
            log_error(f"M_30: Login failed: {e}")
            return False, str(e)

    def logout(self):
        """Выход из системы."""
        self._token_manager.clear_tokens()
        self._cache.clear()
        self._update_status(NetworkStatus.AUTH_REQUIRED)
        log_info("M_30: Logged out")

    # =========================================================================
    # Приватные методы
    # =========================================================================

    def _get_access_token(self) -> Optional[str]:
        """Получение access token для запросов."""
        return self._token_manager.get_access_token()

    def _refresh_token(self) -> bool:
        """
        Обновление access token через refresh token.

        Returns:
            True если успешно обновлен
        """
        refresh_token = self._token_manager.get_refresh_token()
        if not refresh_token:
            self._update_status(NetworkStatus.AUTH_REQUIRED)
            self.auth_required.emit()
            return False

        try:
            response = self._request_handler.post(
                "/api/v1/auth/refresh",
                json_data={"refresh_token": refresh_token},
                auth=False
            )

            if response and response.get("access_token"):
                # Ротация refresh token
                new_refresh = response.get("refresh_token")
                self._token_manager.store_tokens(
                    access_token=response["access_token"],
                    refresh_token=new_refresh or refresh_token,
                    access_expires_at=response.get("access_expires_at")
                )

                self.token_refreshed.emit()
                log_info("M_30: Token refreshed")
                return True

            # Refresh token недействителен
            self._token_manager.clear_tokens()
            self._update_status(NetworkStatus.AUTH_REQUIRED)
            self.auth_required.emit()
            return False

        except RequestError as e:
            log_error(f"M_30: Token refresh failed: {e}")
            return False

    def _update_status(self, status: NetworkStatus):
        """Обновление статуса с сигналом."""
        if self._status != status:
            self._status = status
            self.status_changed.emit(status)

    def _handle_request_error(self, error: RequestError):
        """Обработка ошибок запросов."""
        if error.status_code == 401:
            self._update_status(NetworkStatus.AUTH_REQUIRED)
            self.auth_required.emit()
        elif error.status_code == 403:
            self._update_status(NetworkStatus.TOKEN_EXPIRED)
        elif error.is_network_error:
            self._update_status(NetworkStatus.OFFLINE)
            self.network_error.emit(str(error))
        else:
            self._update_status(NetworkStatus.SERVER_ERROR)
            self.network_error.emit(str(error))

        log_error(f"M_30: Request error: {error}")

    # =========================================================================
    # Методы для специфичных API endpoints
    # =========================================================================

    def check_version(self) -> Optional[Dict[str, Any]]:
        """
        Проверка версии плагина.

        Returns:
            {"latest_version": "1.2.3", "download_url": "...", "changelog": "..."}
        """
        return self.get("/api/v1/plugin/version", use_cache=True, cache_ttl=3600)

    def get_data_versions(self) -> Optional[Dict[str, Any]]:
        """
        Получение версий справочных данных.

        Returns:
            {"Base_layers": {"version": "1.0", "checksum": "..."}, ...}
        """
        return self.get("/api/v1/data/versions", use_cache=True, cache_ttl=3600)

    def download_data_file(
        self,
        file_key: str,
        save_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> bool:
        """
        Скачивание справочного файла.

        Args:
            file_key: Ключ файла (например, "Base_layers")
            save_path: Путь для сохранения
            progress_callback: Callback прогресса

        Returns:
            True если успешно
        """
        return self.download(
            f"/api/v1/data/download/{file_key}",
            save_path,
            progress_callback
        )
