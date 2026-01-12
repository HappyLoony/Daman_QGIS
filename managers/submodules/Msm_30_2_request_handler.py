# -*- coding: utf-8 -*-
"""
Msm_30_2_RequestHandler - HTTP обработчик запросов.

Отвечает за:
- HTTP запросы с автоматическим retry
- Добавление JWT токена в заголовки
- Обновление токена при 401
- Скачивание файлов с прогрессом
"""

from typing import Optional, Dict, Any, Callable
from enum import Enum

from ...utils import log_info, log_error, log_warning
from ...constants import API_BASE_URL, API_TIMEOUT


class RequestError(Exception):
    """Ошибка HTTP запроса."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        is_network_error: bool = False
    ):
        super().__init__(message)
        self.status_code = status_code
        self.is_network_error = is_network_error


class RequestHandler:
    """
    HTTP обработчик с retry и авторизацией.

    Особенности:
    - Автоматический retry при сетевых ошибках
    - Добавление Bearer токена
    - Обновление токена при 401
    - Скачивание с progress callback
    """

    MAX_RETRIES = 3
    RETRY_DELAY = 1.0  # секунды

    def __init__(self):
        self._session = None
        self._base_url = API_BASE_URL
        self._timeout = API_TIMEOUT

        # Callbacks для получения/обновления токена
        self._token_provider: Optional[Callable[[], Optional[str]]] = None
        self._token_refresher: Optional[Callable[[], bool]] = None

    def set_token_provider(self, provider: Callable[[], Optional[str]]):
        """Установка callback для получения токена."""
        self._token_provider = provider

    def set_token_refresher(self, refresher: Callable[[], bool]):
        """Установка callback для обновления токена."""
        self._token_refresher = refresher

    def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        auth: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        GET запрос.

        Args:
            endpoint: Путь API
            params: Query параметры
            auth: Требуется ли авторизация

        Returns:
            JSON ответ

        Raises:
            RequestError: При ошибке
        """
        return self._request("GET", endpoint, params=params, auth=auth)

    def post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        auth: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        POST запрос.

        Args:
            endpoint: Путь API
            data: Form data
            json_data: JSON body
            auth: Требуется ли авторизация

        Returns:
            JSON ответ

        Raises:
            RequestError: При ошибке
        """
        return self._request("POST", endpoint, data=data, json_data=json_data, auth=auth)

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
            save_path: Путь сохранения
            progress_callback: Callback(downloaded_bytes, total_bytes)

        Returns:
            True если успешно

        Raises:
            RequestError: При ошибке
        """
        session = self._get_session()
        if not session:
            raise RequestError("requests library not available", is_network_error=True)

        url = self._build_url(endpoint)
        headers = self._build_headers(auth=True)

        try:
            response = session.get(
                url,
                headers=headers,
                stream=True,
                timeout=self._timeout * 10  # Увеличенный timeout для download
            )

            if response.status_code == 401:
                # Попытка обновить токен
                if self._try_refresh_token():
                    headers = self._build_headers(auth=True)
                    response = session.get(url, headers=headers, stream=True, timeout=self._timeout * 10)
                else:
                    raise RequestError("Unauthorized", status_code=401)

            if response.status_code != 200:
                raise RequestError(
                    f"Download failed: {response.status_code}",
                    status_code=response.status_code
                )

            # Скачивание с прогрессом
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            chunk_size = 8192

            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        if progress_callback and total_size > 0:
                            progress_callback(downloaded, total_size)

            log_info(f"Msm_30_2: Downloaded {downloaded} bytes to {save_path}")
            return True

        except Exception as e:
            if isinstance(e, RequestError):
                raise
            raise RequestError(str(e), is_network_error=True)

    # =========================================================================
    # Приватные методы
    # =========================================================================

    def _get_session(self):
        """Ленивая инициализация requests session."""
        if self._session is None:
            try:
                import requests
                self._session = requests.Session()

                # Настройка retry
                from requests.adapters import HTTPAdapter
                from urllib3.util.retry import Retry

                retry = Retry(
                    total=self.MAX_RETRIES,
                    backoff_factor=self.RETRY_DELAY,
                    status_forcelist=[500, 502, 503, 504]
                )
                adapter = HTTPAdapter(max_retries=retry)
                self._session.mount("http://", adapter)
                self._session.mount("https://", adapter)

            except ImportError:
                log_warning("Msm_30_2: requests library not available")
                return None

        return self._session

    def _build_url(self, endpoint: str) -> str:
        """Построение полного URL."""
        if endpoint.startswith("http"):
            return endpoint
        return f"{self._base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    def _build_headers(self, auth: bool = True) -> Dict[str, str]:
        """Построение заголовков запроса."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Daman_QGIS/1.0"
        }

        if auth and self._token_provider:
            token = self._token_provider()
            if token:
                headers["Authorization"] = f"Bearer {token}"

        return headers

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        auth: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Выполнение HTTP запроса."""
        session = self._get_session()
        if not session:
            raise RequestError("requests library not available", is_network_error=True)

        url = self._build_url(endpoint)
        headers = self._build_headers(auth)

        try:
            if method == "GET":
                response = session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self._timeout
                )
            elif method == "POST":
                response = session.post(
                    url,
                    data=data,
                    json=json_data,
                    headers=headers,
                    timeout=self._timeout
                )
            else:
                raise RequestError(f"Unsupported method: {method}")

            # Обработка 401 - попытка обновить токен
            if response.status_code == 401 and auth:
                if self._try_refresh_token():
                    # Повторный запрос с новым токеном
                    headers = self._build_headers(auth=True)
                    if method == "GET":
                        response = session.get(url, params=params, headers=headers, timeout=self._timeout)
                    else:
                        response = session.post(url, data=data, json=json_data, headers=headers, timeout=self._timeout)
                else:
                    raise RequestError("Unauthorized", status_code=401)

            # Проверка статуса
            if response.status_code >= 400:
                error_msg = self._extract_error_message(response)
                raise RequestError(error_msg, status_code=response.status_code)

            # Парсинг JSON
            if response.text:
                return response.json()
            return {}

        except RequestError:
            raise

        except Exception as e:
            # Сетевые ошибки (timeout, connection error, etc.)
            log_error(f"Msm_30_2: Request failed: {e}")
            raise RequestError(str(e), is_network_error=True)

    def _try_refresh_token(self) -> bool:
        """Попытка обновления токена."""
        if self._token_refresher:
            return self._token_refresher()
        return False

    def _extract_error_message(self, response) -> str:
        """Извлечение сообщения об ошибке из ответа."""
        try:
            error_data = response.json()
            return error_data.get("message") or error_data.get("error") or f"Error {response.status_code}"
        except Exception:
            return f"HTTP {response.status_code}: {response.text[:100]}"
