# -*- coding: utf-8 -*-
"""
Msm_40_2_CookieStore - In-memory хранилище cookies сессии НСПД

Потокобезопасное хранение cookies для использования из разных потоков
(ThreadPoolExecutor в Fsm_1_2_1_EgrnLoader).

Cookies хранятся ТОЛЬКО в памяти -- не сохраняются на диск и не в QSettings.
При перезапуске QGIS сессия сбрасывается.
"""

import threading
from typing import Dict

from Daman_QGIS.utils import log_info


class Msm_40_2_CookieStore:
    """In-memory хранилище cookies НСПД.

    Потокобезопасность обеспечивается threading.Lock --
    cookies используются из main thread (UI) и worker threads (HTTP requests).
    """

    def __init__(self) -> None:
        self._cookies: Dict[str, str] = {}
        self._lock = threading.Lock()

    def set_cookies(self, cookies: Dict[str, str]) -> None:
        """Сохранить cookies.

        Args:
            cookies: Словарь {name: value} cookies
        """
        with self._lock:
            self._cookies = dict(cookies)

    def get_cookies(self) -> Dict[str, str]:
        """Получить копию cookies.

        Returns:
            Копия словаря cookies (потокобезопасно)
        """
        with self._lock:
            return dict(self._cookies)

    def is_valid(self) -> bool:
        """Проверка наличия cookies.

        Returns:
            True если есть хотя бы один cookie
        """
        with self._lock:
            return len(self._cookies) > 0

    def get_cookie_count(self) -> int:
        """Количество сохраненных cookies."""
        with self._lock:
            return len(self._cookies)

    def clear(self) -> None:
        """Очистить все cookies."""
        with self._lock:
            self._cookies.clear()
            log_info("Msm_40_2: Cookies очищены")
