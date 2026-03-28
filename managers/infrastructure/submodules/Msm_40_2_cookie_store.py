# -*- coding: utf-8 -*-
"""
Msm_40_2_CookieStore - In-memory хранилище cookies сессии НСПД

Потокобезопасное хранение cookies для использования из разных потоков
(ThreadPoolExecutor в Fsm_1_2_1_EgrnLoader).

Cookies хранятся ТОЛЬКО в памяти -- не сохраняются на диск и не в QSettings.
При перезапуске QGIS сессия сбрасывается.
"""

import threading
import time
from typing import Dict, Optional

from Daman_QGIS.utils import log_info

# ЕСИА access tokens expire after 3 hours
_ESIA_SESSION_TIMEOUT = 3 * 60 * 60  # 10800 секунд


class Msm_40_2_CookieStore:
    """In-memory хранилище cookies НСПД.

    Потокобезопасность обеспечивается threading.Lock --
    cookies используются из main thread (UI) и worker threads (HTTP requests).
    """

    def __init__(self) -> None:
        self._cookies: Dict[str, str] = {}
        self._lock = threading.Lock()
        self._auth_timestamp: Optional[float] = None

    def set_cookies(self, cookies: Dict[str, str]) -> None:
        """Сохранить cookies.

        Args:
            cookies: Словарь {name: value} cookies
        """
        with self._lock:
            self._cookies = dict(cookies)
            self._auth_timestamp = time.time()

    def get_cookies(self) -> Dict[str, str]:
        """Получить копию cookies.

        Returns:
            Копия словаря cookies (потокобезопасно)
        """
        with self._lock:
            return dict(self._cookies)

    def is_valid(self) -> bool:
        """Проверка наличия cookies и актуальности сессии.

        Returns:
            True если есть cookies и сессия ЕСИА не истекла (3 часа)
        """
        with self._lock:
            if len(self._cookies) == 0:
                return False
            if self._auth_timestamp is None:
                return True
            return (time.time() - self._auth_timestamp) < _ESIA_SESSION_TIMEOUT

    def get_cookie_count(self) -> int:
        """Количество сохраненных cookies."""
        with self._lock:
            return len(self._cookies)

    def get_remaining_seconds(self) -> Optional[int]:
        """Секунды до истечения сессии ЕСИА.

        Returns:
            Оставшееся время в секундах, или None если не авторизован
        """
        with self._lock:
            if self._auth_timestamp is None:
                return None
            remaining = _ESIA_SESSION_TIMEOUT - (time.time() - self._auth_timestamp)
            return max(0, int(remaining))

    def clear(self) -> None:
        """Очистить все cookies."""
        with self._lock:
            self._cookies.clear()
            self._auth_timestamp = None
            log_info("Msm_40_2: Cookies очищены")
