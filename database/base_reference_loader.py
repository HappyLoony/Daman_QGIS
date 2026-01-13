# -*- coding: utf-8 -*-
"""
Базовый класс для загрузки справочных данных из JSON файлов.

Предоставляет общую функциональность для всех менеджеров справочных данных:
- Загрузка JSON с кэшированием
- Построение индексов для быстрого поиска
- Управление кэшем
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from Daman_QGIS.utils import log_warning, log_error, log_info


class BaseReferenceLoader:
    """Базовый класс для загрузки и кэширования справочных данных из JSON"""

    def __init__(self, reference_dir: str):
        """
        Инициализация базового загрузчика

        Args:
            reference_dir: Путь к директории со справочными JSON файлами
        """
        self.reference_dir = reference_dir

        # Кэш для загруженных данных {filename: data}
        self._cache: Dict[str, Any] = {}

        # Кэш для индексов {index_key: {key_value: item}}
        self._index_cache: Dict[str, Dict] = {}

    def _load_json(self, filename: str) -> Any:
        """
        Загружает JSON файл с кэшированием.

        Режимы (DATA_REFERENCE_MODE):
        - local: только локальные файлы
        - remote: только HTTP (GitHub Raw)
        - auto: remote с fallback на local

        Args:
            filename: Имя JSON файла

        Returns:
            Данные из файла или None при ошибке
        """
        # Проверяем расширение файла
        if not filename.endswith('.json'):
            log_warning(f"Попытка загрузить не-JSON файл: {filename}")
            return None

        # Проверяем кэш
        if filename in self._cache:
            return self._cache[filename]

        from Daman_QGIS.constants import DATA_REFERENCE_MODE

        data = None

        # Remote загрузка (для режимов 'remote' и 'auto')
        if DATA_REFERENCE_MODE in ('remote', 'auto'):
            data = self._load_from_remote(filename)

        # Local загрузка (для 'local' или fallback в 'auto')
        if data is None and DATA_REFERENCE_MODE in ('local', 'auto'):
            data = self._load_from_local(filename)

        if data is not None:
            self._cache[filename] = data

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

    def _load_from_local(self, filename: str) -> Optional[Any]:
        """
        Загрузить JSON из локальной файловой системы.

        Args:
            filename: Имя JSON файла

        Returns:
            Данные из файла или None при ошибке
        """
        base_path = Path(self.reference_dir).resolve()
        filepath = (base_path / filename).resolve()

        # Защита от path traversal
        try:
            filepath.relative_to(base_path)
        except ValueError:
            log_error(f"BaseReferenceLoader: Попытка path traversal: {filename}")
            return None

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                log_info(f"BaseReferenceLoader: Загружен {filename} локально")
                return data
        except FileNotFoundError:
            log_warning(f"Файл базы данных не найден: {filepath}")
        except json.JSONDecodeError as e:
            log_error(f"Ошибка чтения JSON: {filepath} - {str(e)}")

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
        # Проверяем индекс
        if index_key not in self._index_cache:
            data = data_getter()
            self._index_cache[index_key] = self._build_index(data, field_name)

        return self._index_cache[index_key].get(value)

    def clear_cache(self):
        """Очистить весь кэш (данные и индексы)"""
        self._cache.clear()
        self._index_cache.clear()

    def reload(self, filename: Optional[str] = None):
        """
        Перезагрузить данные из файла

        Args:
            filename: Имя файла для перезагрузки. Если None, очищается весь кэш
        """
        if filename:
            # Удаляем конкретный файл из кэша
            if filename in self._cache:
                del self._cache[filename]

            # Очищаем связанные индексы (они будут пересозданы при следующем обращении)
            # Примечание: индексы не привязаны напрямую к filename, поэтому очищаем все
            self._index_cache.clear()
        else:
            # Очищаем весь кэш
            self.clear_cache()
