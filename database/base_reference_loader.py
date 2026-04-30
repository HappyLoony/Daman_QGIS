# -*- coding: utf-8 -*-
"""
Базовый класс для загрузки справочных данных из JSON через Daman API.

Требует интернет-соединение. Кэширование только в памяти на время сессии.

Предоставляет общую функциональность для всех менеджеров справочных данных:
- Загрузка JSON через API (daman.tools)
- Кэширование в памяти на время сессии
- Построение индексов для быстрого поиска

API URL: constants.API_BASE_URL
Формат запроса: /data/{filename} или ?action=data&file={filename}
"""

import json
from typing import Dict, List, Any, Optional
from Daman_QGIS.utils import log_warning, log_error


class BaseReferenceLoader:
    """Базовый класс для загрузки справочных данных через Daman API.

    Кэш общий для всех экземпляров (на уровне класса).
    Данные загружаются один раз за сессию.
    """

    # Общий кэш для всех экземпляров (загрузка один раз за сессию)
    _shared_cache: Dict[str, Any] = {}
    _shared_index_cache: Dict[str, Dict] = {}

    def __init__(self):
        """Инициализация базового загрузчика.

        Данные загружаются через Daman API, локальные пути не используются.
        """
        pass

    def _load_json(self, filename: str) -> Any:
        """
        Загружает JSON файл через Daman API с кэшированием в памяти.

        Требует интернет-соединение. Кэш хранится только на время сессии.

        Args:
            filename: Имя JSON файла

        Returns:
            Данные из файла или None при ошибке
        """
        # Проверяем расширение файла
        if not filename.endswith('.json'):
            log_warning(f"Попытка загрузить не-JSON файл: {filename}")
            return None

        # Проверяем общий кэш (один раз за сессию)
        if filename in BaseReferenceLoader._shared_cache:
            return BaseReferenceLoader._shared_cache[filename]

        # Загрузка через Daman API (требует интернет)
        data = self._load_from_remote(filename)

        if data is not None:
            BaseReferenceLoader._shared_cache[filename] = data

        return data

    def _load_from_remote(self, filename: str) -> Optional[Any]:
        """
        Загрузить JSON через Daman API с JWT авторизацией.

        Все retry/refresh/backoff логика вынесена в Msm_29_6_AuthedRequestManager
        (single source of truth). Здесь только парсинг ответа.

        Args:
            filename: Имя JSON файла (с или без .json расширения)

        Returns:
            Данные из файла или None при ошибке
        """
        from Daman_QGIS.constants import get_api_url
        from Daman_QGIS.managers.infrastructure.submodules.Msm_29_6_authed_request import (
            AuthedRequestManager,
            AuthFailureError,
            CircuitBreakerError,
            VersionMismatchError,
        )

        try:
            import requests
        except ImportError:
            log_warning("BaseReferenceLoader: requests не установлен, remote загрузка недоступна")
            return None

        # Убираем .json для API запроса (API добавит сам)
        file_param = filename.replace('.json', '')
        url = get_api_url("data", file=file_param)

        try:
            response = AuthedRequestManager.get_instance().request(
                "GET",
                url,
                # Один endpoint_key на все Base_*.json — общая квота 3 попытки/60с.
                endpoint_key="/api/plugin/data",
            )
        except CircuitBreakerError as e:
            # Тихо — не спамить запросами и не пугать юзера повторно.
            # AuthFailureError уже показал UI ранее, circuit breaker = cooldown.
            log_warning(f"BaseReferenceLoader: {filename} skipped: {e}")
            return None
        except AuthFailureError as e:
            # UI-сообщение «Требуется повторная активация» уже показано
            # из AuthedRequestManager (через registered callback).
            log_error(f"BaseReferenceLoader: Auth failure для {filename}: {e}")
            return None
        except VersionMismatchError as e:
            # M_42 hot update detected — токены инвалидированы, форсим re-validate.
            log_warning(f"BaseReferenceLoader: {filename} version mismatch: {e}")
            self._handle_jwt_version_mismatch()
            return None
        except requests.exceptions.Timeout:
            log_warning(f"BaseReferenceLoader: Таймаут при загрузке {filename}")
            return None
        except requests.exceptions.RequestException as e:
            log_warning(f"BaseReferenceLoader: Ошибка сети при загрузке {filename}: {e}")
            return None

        if response is None:
            return None

        try:
            if response.status_code == 200:
                response_json = response.json()
                # Сервер оборачивает данные в {'data': ..., 'copyright': ...}
                data = response_json.get('data', response_json) if isinstance(response_json, dict) else response_json
                return data
            if response.status_code == 403:
                # 403 не-AUTH_FAILED (например, ACCOUNT_PENDING_DELETION,
                # INTEGRITY_MISMATCH, HARDWARE_MISMATCH) — refresh не помог бы,
                # AuthedRequestManager пропускает их без retry. Логируем код.
                try:
                    error_body = response.json()
                    error_code = error_body.get('error_code', error_body.get('error', 'unknown'))
                except Exception:
                    error_code = response.text[:100] if response.text else 'empty'
                log_warning(
                    f"BaseReferenceLoader: Доступ запрещён к {filename} "
                    f"(reason: {error_code})"
                )
            elif response.status_code == 404:
                log_warning(f"BaseReferenceLoader: Файл {filename} не найден на сервере")
            else:
                log_warning(
                    f"BaseReferenceLoader: HTTP {response.status_code} для {filename}"
                )
        except json.JSONDecodeError as e:
            log_error(f"BaseReferenceLoader: Ошибка парсинга JSON {filename}: {e}")

        return None

    @staticmethod
    def _handle_jwt_version_mismatch() -> None:
        """JWT integrity claims устарели после M_42 hot-update.

        Форсим M_29.force_revalidate() — verify() с обнулённым кэшем сессии,
        чтобы /validate выдал свежий JWT с актуальными integrity claims
        для текущей PLUGIN_VERSION. Best-effort — если M_29 недоступен,
        возвращаемся (next request попадёт в _check_jwt_version с уже
        очищенными токенами и пойдёт по обычному auth-failure пути).
        """
        try:
            from Daman_QGIS.managers._registry import registry
            license_mgr = registry.get('M_29')
            if license_mgr is None:
                return
            license_mgr.force_revalidate()
        except Exception as e:
            log_warning(f"BaseReferenceLoader: Force re-validate failed: {e}")

    def _build_index(self, data: List[Dict], key_field: str) -> Dict:
        """
        Построить индекс для быстрого поиска по ключу

        Args:
            data: Список словарей для индексации
            key_field: Имя поля для использования как ключ

        Returns:
            Словарь {значение_ключа: элемент}
        """
        index = {}
        for item in data:
            if key_field in item and item[key_field] is not None:
                index[item[key_field]] = item
        return index

    def _get_by_key(self, data_getter, index_key: str, field_name: str, value: Any) -> Optional[Dict]:
        """
        Универсальный метод поиска по ключу с кэшированием индекса

        Args:
            data_getter: Callable для получения полного списка данных
            index_key: Ключ для хранения индекса в кэше
            field_name: Имя поля для индексации
            value: Значение для поиска

        Returns:
            Найденный элемент или None
        """
        # Проверяем общий индексный кэш
        if index_key not in BaseReferenceLoader._shared_index_cache:
            data = data_getter()
            BaseReferenceLoader._shared_index_cache[index_key] = self._build_index(data, field_name)

        return BaseReferenceLoader._shared_index_cache[index_key].get(value)

    @classmethod
    def clear_cache(cls):
        """Очистить весь общий кэш (данные и индексы)"""
        cls._shared_cache.clear()
        cls._shared_index_cache.clear()

    @classmethod
    def reload(cls, filename: Optional[str] = None):
        """
        Перезагрузить данные из файла

        Args:
            filename: Имя файла для перезагрузки. Если None, очищается весь кэш
        """
        if filename:
            # Удаляем конкретный файл из кэша
            if filename in cls._shared_cache:
                del cls._shared_cache[filename]

            # Очищаем связанные индексы (они будут пересозданы при следующем обращении)
            cls._shared_index_cache.clear()
        else:
            # Очищаем весь кэш
            cls.clear_cache()
