# -*- coding: utf-8 -*-
"""
Базовый класс для загрузки справочных данных из JSON файлов с GitHub Raw.

Требует интернет-соединение. Кэширование только в памяти на время сессии.

Предоставляет общую функциональность для всех менеджеров справочных данных:
- Загрузка JSON с GitHub Raw
- Кэширование в памяти на время сессии
- Построение индексов для быстрого поиска
"""

import json
from typing import Dict, List, Any, Optional
from Daman_QGIS.utils import log_warning, log_error, log_info


class BaseReferenceLoader:
    """Базовый класс для загрузки справочных данных с GitHub Raw

    Кэш общий для всех экземпляров (на уровне класса).
    Данные загружаются один раз за сессию.
    """

    # Общий кэш для всех экземпляров (загрузка один раз за сессию)
    _shared_cache: Dict[str, Any] = {}
    _shared_index_cache: Dict[str, Dict] = {}

    def __init__(self, reference_dir: str = None):
        """
        Инициализация базового загрузчика

        Args:
            reference_dir: Не используется (для совместимости с API)
        """
        # reference_dir сохраняется для совместимости, но не используется
        self.reference_dir = reference_dir

    def _load_json(self, filename: str) -> Any:
        """
        Загружает JSON файл с GitHub Raw с кэшированием в памяти.

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

        # Загрузка с GitHub Raw (требует интернет)
        data = self._load_from_remote(filename)

        if data is not None:
            BaseReferenceLoader._shared_cache[filename] = data

        return data

    def _load_from_remote(self, filename: str) -> Optional[Any]:
        """
        Загрузить JSON с GitHub Raw.

        Args:
            filename: Имя JSON файла

        Returns:
            Данные из файла или None при ошибке
        """
        from Daman_QGIS.constants import DATA_REFERENCE_BASE_URL, DEFAULT_REQUEST_TIMEOUT

        try:
            import requests
        except ImportError:
            log_warning("BaseReferenceLoader: requests не установлен, remote загрузка недоступна")
            return None

        url = f"{DATA_REFERENCE_BASE_URL}/{filename}"
        try:
            response = requests.get(url, timeout=DEFAULT_REQUEST_TIMEOUT)
            if response.status_code == 200:
                data = response.json()
                log_info(f"BaseReferenceLoader: Загружен {filename} с remote")
                return data
            else:
                log_warning(f"BaseReferenceLoader: HTTP {response.status_code} для {filename}")
        except requests.exceptions.Timeout:
            log_warning(f"BaseReferenceLoader: Таймаут при загрузке {filename}")
        except requests.exceptions.RequestException as e:
            log_warning(f"BaseReferenceLoader: Ошибка сети при загрузке {filename}: {e}")
        except json.JSONDecodeError as e:
            log_error(f"BaseReferenceLoader: Ошибка парсинга JSON {filename}: {e}")

        return None

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
