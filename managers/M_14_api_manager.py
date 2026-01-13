# -*- coding: utf-8 -*-
"""
M_14: API Manager - Менеджер API endpoints для загрузки слоёв

Централизованное управление всеми API endpoints (EGRN, Overpass, FGISLK, Google).
Заменяет hardcoded URLs и category_id в функциях загрузки.

Примеры использования:
    >>> from Daman_QGIS.managers import APIManager
    >>> manager = APIManager()
    >>>
    >>> # Получение endpoint по имени слоя
    >>> endpoint = manager.get_endpoint_by_layer("L_1_2_1_WFS_ЗУ")
    >>> print(endpoint['category_id'])  # 36368
    >>>
    >>> # Получение всех endpoints группы
    >>> egrn_endpoints = manager.get_endpoints_by_group("EGRN_WFS")
    >>>
    >>> # Fallback серверы Overpass
    >>> fallbacks = manager.get_fallback_servers("overpass_group")
    >>>
    >>> # Объединённая загрузка ОКС (Здания + Сооружения + ОНС)
    >>> oks_categories = manager.get_oks_combined_categories()  # [36369, 36383, 36384]
    >>>
    >>> # HTTP заголовки для API запросов
    >>> referer = manager.get_referer_url("L_1_2_1_WFS_ЗУ")  # "https://nspd.gov.ru/map"
    >>> origin = manager.get_origin_url("L_1_2_1_WFS_ЗУ")    # "https://nspd.gov.ru"
    >>>
    >>> # Прогрессивные таймауты
    >>> timeout = manager.get_timeout("L_1_2_1_WFS_ЗУ")  # [3, 10, 30]
"""

import os
import json
from typing import List, Dict, Optional, Any, Union
from Daman_QGIS.utils import log_info, log_error, log_warning


class APIManager:
    """
    Менеджер API endpoints для загрузки Web слоёв

    Предоставляет централизованный доступ к конфигурации всех API:
    - EGRN WFS/WMTS (векторные и растровые слои ЕГРН)
    - Overpass API (OSM данные с fallback серверами)
    - ФГИС ЛК (лесничества)
    - Google Maps (спутниковые снимки и подписи)
    """

    # Путь к JSON базе данных
    @staticmethod
    def _get_db_path():
        from Daman_QGIS.constants import DATA_REFERENCE_PATH
        return os.path.join(DATA_REFERENCE_PATH, 'Base_api_endpoints.json')

    _DB_PATH = None  # Будет установлен при первом вызове

    # Список слоёв для объединённой загрузки ОКС (Здания + Сооружения + ОНС)
    OKS_LAYER_NAMES = [
        "L_1_2_4_WFS_ОКС_Здания",
        "L_1_2_4_WFS_ОКС_Сооружения",
        "L_1_2_4_WFS_ОКС_ОНС"
    ]

    def __init__(self):
        """Инициализация менеджера"""
        self._endpoints: List[Dict[str, Any]] = []
        self._cache_by_id: Dict[int, Dict] = {}
        self._cache_by_layer: Dict[str, Dict] = {}
        self._cache_by_group: Dict[str, List[Dict]] = {}
        self._db_path = self._get_db_path()

        self._load_database()

    def _load_database(self) -> None:
        """Загрузка базы данных endpoints из JSON (через BaseReferenceLoader для remote/local)"""
        try:
            from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
            from Daman_QGIS.constants import DATA_REFERENCE_PATH

            loader = BaseReferenceLoader(DATA_REFERENCE_PATH)
            data = loader._load_json('Base_api_endpoints.json')

            if data is None:
                log_error("M_14_ApiManager: Base_api_endpoints.json не найден ни на remote ни локально")
                return

            self._endpoints = data

            # Построение кэшей для быстрого доступа
            for endpoint in self._endpoints:
                endpoint_id = endpoint.get('endpoint_id')
                layer_name = endpoint.get('layer_name')
                api_group = endpoint.get('api_group')

                if endpoint_id:
                    self._cache_by_id[endpoint_id] = endpoint

                if layer_name:
                    self._cache_by_layer[layer_name] = endpoint

                if api_group:
                    if api_group not in self._cache_by_group:
                        self._cache_by_group[api_group] = []
                    self._cache_by_group[api_group].append(endpoint)

            log_info(f"M_14_ApiManager: Загружено {len(self._endpoints)} API endpoints")

        except Exception as e:
            log_error(f"M_14_ApiManager: Ошибка загрузки Base_api_endpoints.json: {str(e)}")

    # ========== Основные методы получения endpoints ==========

    def get_endpoint_by_id(self, endpoint_id: int) -> Optional[Dict[str, Any]]:
        """
        Получить endpoint по ID

        Args:
            endpoint_id: ID endpoint (1-26)

        Returns:
            Словарь с данными endpoint или None
        """
        return self._cache_by_id.get(endpoint_id)

    def get_endpoint_by_layer(self, layer_name: str) -> Optional[Dict[str, Any]]:
        """
        Получить endpoint по имени слоя

        Args:
            layer_name: Имя слоя (например, "L_1_2_1_WFS_ЗУ")

        Returns:
            Словарь с данными endpoint или None

        Example:
            >>> endpoint = manager.get_endpoint_by_layer("L_1_2_1_WFS_ЗУ")
            >>> print(endpoint['category_id'])  # 36368
        """
        return self._cache_by_layer.get(layer_name)

    def get_endpoints_by_group(self, api_group: str) -> List[Dict[str, Any]]:
        """
        Получить все endpoints группы

        Args:
            api_group: Название группы ("EGRN_WFS", "OVERPASS", "GOOGLE" и т.д.)

        Returns:
            Список endpoints группы

        Example:
            >>> egrn_endpoints = manager.get_endpoints_by_group("EGRN_WFS")
            >>> print(len(egrn_endpoints))  # 16
        """
        return self._cache_by_group.get(api_group, [])

    def get_all_endpoints(self) -> List[Dict[str, Any]]:
        """
        Получить все endpoints

        Returns:
            Список всех endpoints
        """
        return self._endpoints.copy()

    # ========== Специализированные методы ==========

    def get_fallback_servers(self, fallback_group: str) -> List[Dict[str, Any]]:
        """
        Получить fallback серверы группы (для Overpass)

        Args:
            fallback_group: Название группы ("overpass_group")

        Returns:
            Список fallback серверов, отсортированных по приоритету

        Example:
            >>> fallbacks = manager.get_fallback_servers("overpass_group")
            >>> # [DE, Kumi, CH серверы]
        """
        fallback_endpoints = [
            ep for ep in self._endpoints
            if ep.get('fallback_group') == fallback_group
        ]

        # Сортируем по endpoint_id (меньший = выше приоритет)
        return sorted(fallback_endpoints, key=lambda x: x.get('endpoint_id', 999))

    def parse_timeout(self, timeout_sec: Any) -> Union[List[int], int, None]:
        """
        Парсинг значения timeout (может быть строкой "3;10;30" или числом)

        Args:
            timeout_sec: Значение из поля timeout_sec

        Returns:
            - List[int] если прогрессивный таймаут ("3;10;30" → [3, 10, 30])
            - int если одиночное значение
            - None если не задан

        Example:
            >>> manager.parse_timeout("3;10;30")  # [3, 10, 30]
            >>> manager.parse_timeout(15)  # 15
            >>> manager.parse_timeout(None)  # None
        """
        # Обработка null (строка или None)
        if timeout_sec is None or timeout_sec == "null":
            return None

        if isinstance(timeout_sec, str) and ';' in timeout_sec:
            try:
                return [int(x.strip()) for x in timeout_sec.split(';')]
            except ValueError:
                log_warning(f"M_14_ApiManager: Некорректный формат timeout: {timeout_sec}")
                return None

        try:
            return int(timeout_sec)
        except (ValueError, TypeError):
            return None

    def get_category_ids_for_layer(self, layer_name: str) -> Optional[Union[int, str]]:
        """
        Получить category_id для слоя

        Args:
            layer_name: Имя слоя

        Returns:
            - int для EGRN слоёв, включая АТД (36368, 38999)
            - str для OSM слоёв ("highway", "railway")
            - None если не найден

        Example:
            >>> manager.get_category_ids_for_layer("L_1_2_1_WFS_ЗУ")  # 36368
            >>> manager.get_category_ids_for_layer("L_1_4_1_OSM_Дороги")  # "highway"
            >>> manager.get_category_ids_for_layer("Le_1_2_3_13_АТД_Суб_РФ_line")  # 38999
        """
        endpoint = self.get_endpoint_by_layer(layer_name)
        return endpoint.get('category_id') if endpoint else None

    def get_url_for_layer(self, layer_name: str, format_params: Optional[Dict] = None) -> Optional[str]:
        """
        Получить полный URL для слоя

        Args:
            layer_name: Имя слоя
            format_params: Параметры для форматирования URL (category_id, x, y, z и т.д.)

        Returns:
            Отформатированный URL или None

        Example:
            >>> url = manager.get_url_for_layer("L_1_2_1_WFS_ЗУ")
            >>> # "https://nspd.gov.ru/api/geoportal/v1/intersects?typeIntersect=fullObject"
            >>> # NOTE: category_id передается в POST body, НЕ в URL
        """
        endpoint = self.get_endpoint_by_layer(layer_name)
        if not endpoint:
            return None

        base_url = endpoint.get('base_url', '')
        url_template = endpoint.get('url_template', '')
        category_id = endpoint.get('category_id')

        # Параметры по умолчанию
        params = {
            'base_url': base_url,
            'category_id': category_id
        }

        # Добавляем пользовательские параметры
        if format_params:
            params.update(format_params)

        try:
            return url_template.format(**params)
        except KeyError as e:
            log_warning(f"M_14_ApiManager: Не хватает параметра для форматирования URL: {e}")
            return None

    def get_boundary_layer_name(self, layer_name: str) -> Optional[str]:
        """
        Получить имя слоя границ для загрузки (Layer_selector)

        Args:
            layer_name: Имя загружаемого слоя

        Returns:
            Имя слоя границ ("L_1_1_2_Границы_работ_10_м" или "L_1_1_3_Границы_работ_500_м")

        Example:
            >>> manager.get_boundary_layer_name("L_1_2_1_WFS_ЗУ")
            >>> # "L_1_1_2_Границы_работ_10_м"
        """
        endpoint = self.get_endpoint_by_layer(layer_name)
        return endpoint.get('Layer_selector') if endpoint else None

    def get_split_threshold(self, layer_name: str) -> Optional[Union[float, List[float]]]:
        """
        Получить порог дробления для слоя (км²)

        Args:
            layer_name: Имя слоя

        Returns:
            - float: одиночный порог (10.0)
            - List[float]: прогрессивные пороги (если используется)
            - None: без дробления (КК, АТД, ЗОУИТ)

        Example:
            >>> manager.get_split_threshold("L_1_2_1_WFS_ЗУ")  # 10.0
            >>> manager.get_split_threshold("L_1_2_2_WFS_КК")  # None (без дробления)
            >>> manager.get_split_threshold("WFS_ЗОУИТ_UNIVERSAL")  # None
        """
        endpoint = self.get_endpoint_by_layer(layer_name)
        if not endpoint:
            return None

        threshold = endpoint.get('split_threshold_km2')

        # Обработка null (для ЗОУИТ и других слоёв без дробления)
        if threshold is None or threshold == "null":
            return None

        # Обработка прогрессивных порогов: "10;5" → [10.0, 5.0]
        if isinstance(threshold, str) and ';' in threshold:
            try:
                return [float(x.strip()) for x in threshold.split(';')]
            except ValueError:
                log_warning(f"M_14_ApiManager: Некорректный формат split_threshold: {threshold}")
                return None

        # Обработка одиночного порога
        try:
            return float(threshold)
        except (ValueError, TypeError):
            return None

    def get_max_workers(self, layer_name: str) -> Optional[int]:
        """
        Получить количество параллельных потоков для загрузки слоя

        Args:
            layer_name: Имя слоя

        Returns:
            Количество потоков (5, 8) или None

        Example:
            >>> manager.get_max_workers("L_1_2_1_WFS_ЗУ")  # 5
            >>> manager.get_max_workers("L_4_1_1_ЛЕС_Лесничества")  # 8
        """
        endpoint = self.get_endpoint_by_layer(layer_name)
        if not endpoint:
            return None

        max_workers = endpoint.get('max_workers')

        # Обработка null (строка или None)
        if max_workers is None or max_workers == "null":
            return None

        try:
            return int(max_workers)
        except (ValueError, TypeError):
            return None

    # ========== Специальные методы для миграции хардкода ==========

    def get_oks_combined_categories(self) -> List[int]:
        """
        Получить все category_id для ОКС (для объединённой загрузки)

        Используется в F_1_2 для загрузки объединённого слоя L_1_2_4_WFS_ОКС,
        который включает 3 типа: Здания, Сооружения, ОНС.

        Returns:
            List[int]: [36369, 36383, 36384] для Здания/Сооружения/ОНС

        Example:
            >>> manager = APIManager()
            >>> categories = manager.get_oks_combined_categories()
            >>> # [36369, 36383, 36384]
            >>> for category_id in categories:
            >>>     load_layer(..., category_id=category_id, ...)
        """
        categories = []
        for layer_name in self.OKS_LAYER_NAMES:
            endpoint = self.get_endpoint_by_layer(layer_name)
            if endpoint:
                category_id = endpoint.get('category_id')
                if category_id is not None:
                    categories.append(category_id)

        if len(categories) != 3:
            log_warning(f"M_14_ApiManager: Получено {len(categories)} category_id для ОКС вместо ожидаемых 3")

        return categories

    def get_referer_url(self, layer_name: str) -> Optional[str]:
        """
        Получить Referer URL для слоя

        Args:
            layer_name: Имя слоя

        Returns:
            Referer URL или None

        Example:
            >>> manager.get_referer_url("L_1_2_1_WFS_ЗУ")
            >>> # "https://nspd.gov.ru/map"
        """
        endpoint = self.get_endpoint_by_layer(layer_name)
        if not endpoint:
            return None

        referer = endpoint.get('referer_url')

        # Обработка null (строка или None)
        if referer is None or referer == "null":
            return None

        return referer

    def get_timeout(self, layer_name: str) -> Union[List[int], int, None]:
        """
        Получить готовый timeout для слоя (обертка для parse_timeout)

        Удобный метод, который сразу возвращает распарсенный timeout.
        Заменяет вызов parse_timeout(endpoint['timeout_sec']).

        Args:
            layer_name: Имя слоя

        Returns:
            - List[int]: прогрессивные таймауты ([3, 10, 30])
            - int: одиночный таймаут (15)
            - None: если не задан

        Example:
            >>> manager.get_timeout("L_1_2_1_WFS_ЗУ")
            >>> # [3, 10, 30]
            >>> manager.get_timeout("L_1_2_2_WFS_КК")
            >>> # 15
        """
        endpoint = self.get_endpoint_by_layer(layer_name)
        if not endpoint:
            return None

        return self.parse_timeout(endpoint.get('timeout_sec'))

    # ========== Утилиты ==========

    def get_statistics(self) -> Dict[str, Any]:
        """
        Получить статистику endpoints

        Returns:
            Словарь со статистикой
        """
        stats = {
            'total_endpoints': len(self._endpoints),
            'by_group': {},
            'by_api_type': {}
        }

        for endpoint in self._endpoints:
            api_group = endpoint.get('api_group', 'unknown')
            api_type = endpoint.get('api_type', 'unknown')

            stats['by_group'][api_group] = stats['by_group'].get(api_group, 0) + 1
            stats['by_api_type'][api_type] = stats['by_api_type'].get(api_type, 0) + 1

        return stats
