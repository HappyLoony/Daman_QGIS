# -*- coding: utf-8 -*-
"""
Msm_30_3_CacheManager - Кэширование HTTP ответов.

Отвечает за:
- In-memory кэш с TTL
- Генерация ключей кэша
- Автоматическая очистка устаревших записей
"""

import time
import hashlib
import json
from typing import Optional, Dict, Any
from pathlib import Path

from ...utils import log_info, log_warning
from ...constants import CACHE_MAX_AGE_HOURS


class CacheEntry:
    """Запись кэша с временем жизни."""

    def __init__(self, data: Any, ttl: int):
        """
        Args:
            data: Кэшируемые данные
            ttl: Время жизни в секундах
        """
        self.data = data
        self.expires_at = time.time() + ttl

    def is_expired(self) -> bool:
        """Проверка истечения срока."""
        return time.time() > self.expires_at

    def time_remaining(self) -> int:
        """Оставшееся время жизни в секундах."""
        return max(0, int(self.expires_at - time.time()))


class CacheManager:
    """
    Менеджер кэширования HTTP ответов.

    Особенности:
    - In-memory кэш (не персистентный)
    - TTL для каждой записи
    - Автоматическая очистка при доступе
    - Лимит размера кэша
    """

    MAX_ENTRIES = 100  # Максимум записей в кэше
    DEFAULT_TTL = CACHE_MAX_AGE_HOURS * 3600  # По умолчанию из constants

    def __init__(self):
        self._cache: Dict[str, CacheEntry] = {}
        self._initialized: bool = False

    def initialize(self) -> bool:
        """Инициализация кэша."""
        self._cache = {}
        self._initialized = True
        log_info("Msm_30_3: Cache initialized")
        return True

    def make_key(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Генерация ключа кэша.

        Args:
            endpoint: Путь API
            params: Параметры запроса

        Returns:
            Уникальный ключ кэша
        """
        key_parts = [endpoint]

        if params:
            # Сортируем параметры для консистентности
            sorted_params = json.dumps(params, sort_keys=True)
            key_parts.append(sorted_params)

        key_string = "|".join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        """
        Получение данных из кэша.

        Args:
            key: Ключ кэша

        Returns:
            Данные или None если нет/истёк
        """
        self._cleanup_expired()

        entry = self._cache.get(key)
        if entry is None:
            return None

        if entry.is_expired():
            del self._cache[key]
            return None

        return entry.data

    def set(self, key: str, data: Any, ttl: Optional[int] = None):
        """
        Сохранение данных в кэш.

        Args:
            key: Ключ кэша
            data: Данные для кэширования
            ttl: Время жизни в секундах (опционально)
        """
        if ttl is None:
            ttl = self.DEFAULT_TTL

        # Проверка лимита
        if len(self._cache) >= self.MAX_ENTRIES:
            self._evict_oldest()

        self._cache[key] = CacheEntry(data, ttl)

    def has(self, key: str) -> bool:
        """Проверка наличия валидной записи."""
        entry = self._cache.get(key)
        if entry is None:
            return False
        if entry.is_expired():
            del self._cache[key]
            return False
        return True

    def delete(self, key: str):
        """Удаление записи из кэша."""
        self._cache.pop(key, None)

    def clear(self):
        """Полная очистка кэша."""
        self._cache = {}
        log_info("Msm_30_3: Cache cleared")

    def get_stats(self) -> Dict[str, Any]:
        """
        Статистика кэша.

        Returns:
            {"entries": N, "valid": M, "expired": K}
        """
        valid = 0
        expired = 0

        for entry in self._cache.values():
            if entry.is_expired():
                expired += 1
            else:
                valid += 1

        return {
            "entries": len(self._cache),
            "valid": valid,
            "expired": expired,
            "max_entries": self.MAX_ENTRIES
        }

    # =========================================================================
    # Приватные методы
    # =========================================================================

    def _cleanup_expired(self):
        """Удаление истёкших записей."""
        expired_keys = [
            key for key, entry in self._cache.items()
            if entry.is_expired()
        ]
        for key in expired_keys:
            del self._cache[key]

        if expired_keys:
            log_info(f"Msm_30_3: Cleaned up {len(expired_keys)} expired entries")

    def _evict_oldest(self):
        """Удаление самой старой записи (FIFO)."""
        if not self._cache:
            return

        # Находим запись с минимальным expires_at
        oldest_key = min(
            self._cache.keys(),
            key=lambda k: self._cache[k].expires_at
        )
        del self._cache[oldest_key]
        log_warning(f"Msm_30_3: Evicted oldest cache entry")
