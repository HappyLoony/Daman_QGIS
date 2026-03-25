# -*- coding: utf-8 -*-
"""
M_39_DaDataGeocodingManager -- Геокодирование через DaData API.

Отвечает за:
- Обратный геокодинг (координаты WGS-84 -> адрес + ОКАТО/ОКТМО/ФИАС)
- Подсказки по адресу (для UI автодополнения)
- Поиск по идентификатору (кадастровый номер, ФИАС-код)
- Хранение API-ключа в QSettings
- Сессионное кэширование результатов

Зависимости:
- requests (HTTP клиент, уже в requirements.txt)

Использование:
    from Daman_QGIS.managers import registry
    geocoder = registry.get('M_39')
    geocoder.set_api_key('ваш_токен')
    result = geocoder.geolocate(lat=55.878, lon=37.653)
"""

import time
from typing import Optional, Dict, Any, List

import requests

from qgis.PyQt.QtCore import QSettings

from Daman_QGIS.utils import log_info, log_error, log_warning

__all__ = ['DaDataGeocodingManager']


class DaDataGeocodingManager:
    """
    Геокодирование через DaData API. Singleton через registry (M_39).

    Функционал: получение данных по координатам (адреса, коды),
    но НЕ геометрий. Используется для заполнения атрибутов НГС,
    Этап 2, метаданных проекта.
    """

    # DaData API endpoints
    GEOLOCATE_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/geolocate/address"
    SUGGEST_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address"
    FIND_BY_ID_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/address"

    # Настройки
    DEFAULT_TIMEOUT = 10    # секунд
    DEFAULT_RADIUS = 500    # метров для geolocate
    MAX_RADIUS = 1000       # максимум API
    MAX_RETRIES = 3
    RATE_LIMIT_DELAY = 0.05  # 20 req/sec (ниже лимита 30/sec)

    # QSettings
    SETTINGS_KEY = "daman_qgis/dadata_api_key"

    # TODO: Перенести API-ключ на серверный proxy (daman.tools).
    #  План: клиент -> daman.tools -> DaData, ключ хранится в env vars.
    #  Пользователи получают доступ через лицензию (M_29), без прямого ключа.
    _BUNDLED_KEY = "377b9daf9e16b5f733a0380b1839e2b7115e4aca"

    def __init__(self):
        self._api_key: Optional[str] = None
        self._session_cache: Dict[str, Any] = {}
        self._initialized: bool = False

    # ── Lifecycle ──────────────────────────────────────────────

    def initialize(self) -> bool:
        """Загрузка API-ключа: QSettings -> встроенный ключ."""
        if self._initialized:
            return True
        try:
            self._api_key = self._load_key_from_settings()
            if self._api_key:
                log_info("M_39: DaData API-ключ загружен из настроек")
            else:
                self._api_key = self._BUNDLED_KEY
                log_info("M_39: Используется встроенный DaData API-ключ")
            self._initialized = True
            return True
        except Exception as e:
            log_error(f"M_39: Ошибка инициализации: {e}")
            return False

    def shutdown(self) -> None:
        """Очистка при выгрузке плагина."""
        self._session_cache.clear()
        self._initialized = False

    # ── API key management ────────────────────────────────────

    def is_configured(self) -> bool:
        """Проверка наличия API-ключа."""
        return bool(self._api_key)

    def set_api_key(self, key: str) -> None:
        """Сохранение API-ключа в QSettings."""
        key = key.strip()
        self._api_key = key
        self._save_key_to_settings(key)
        log_info("M_39: DaData API-ключ сохранён")

    def get_api_key(self) -> Optional[str]:
        """Получение API-ключа."""
        return self._api_key

    # ── Public API ────────────────────────────────────────────

    def geolocate(
        self,
        lat: float,
        lon: float,
        radius_meters: int = 500,
        count: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """
        Обратный геокодинг: координаты WGS-84 -> адрес.

        Кэширует по округлённым координатам (4 знака ~ 10м).
        Retry с exponential backoff.

        Args:
            lat: Широта (WGS-84)
            lon: Долгота (WGS-84)
            radius_meters: Радиус поиска (макс. 1000м)
            count: Количество результатов (макс. 20)

        Returns:
            Первый suggestion: {'value': str, 'data': dict}
            или None при ошибке / отсутствии результатов.
        """
        if not self._api_key:
            log_warning("M_39: API-ключ не настроен, geolocate невозможен")
            return None

        # Проверка кэша
        cache_key = self._get_cache_key(lat, lon)
        if cache_key in self._session_cache:
            return self._session_cache[cache_key]

        # Ограничение радиуса
        radius_meters = min(radius_meters, self.MAX_RADIUS)

        payload = {
            "lat": lat,
            "lon": lon,
            "count": count,
            "radius_meters": radius_meters,
        }

        response = self._request(self.GEOLOCATE_URL, payload)
        if not response:
            return None

        suggestions = response.get("suggestions", [])
        if not suggestions:
            log_info(f"M_39: geolocate({lat:.4f}, {lon:.4f}): нет результатов в радиусе {radius_meters}м")
            # Кэшируем пустой результат
            self._session_cache[cache_key] = None
            return None

        result = suggestions[0]

        # Кэшируем
        self._session_cache[cache_key] = result
        return result

    def suggest(
        self,
        query: str,
        count: int = 5,
        locations: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Подсказки по адресу (для UI автодополнения).

        Args:
            query: Строка поиска (адрес или его часть)
            count: Количество подсказок (макс. 20)
            locations: Ограничение по региону [{kladr_id: ...}]

        Returns:
            Список suggestions [{value, data}, ...] или пустой список.
        """
        if not self._api_key:
            log_warning("M_39: API-ключ не настроен, suggest невозможен")
            return []

        payload: Dict[str, Any] = {
            "query": query,
            "count": count,
        }
        if locations:
            payload["locations"] = locations

        response = self._request(self.SUGGEST_URL, payload)
        if not response:
            return []

        return response.get("suggestions", [])

    def find_by_id(self, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Поиск по идентификатору (кадастровый номер, ФИАС-код, КЛАДР).

        Args:
            identifier: Идентификатор (напр. "77:02:0004008:4143" или ФИАС GUID)

        Returns:
            Первый suggestion: {value, data} или None.
        """
        if not self._api_key:
            log_warning("M_39: API-ключ не настроен, find_by_id невозможен")
            return None

        payload = {"query": identifier}

        response = self._request(self.FIND_BY_ID_URL, payload)
        if not response:
            return None

        suggestions = response.get("suggestions", [])
        if not suggestions:
            log_info(f"M_39: find_by_id('{identifier}'): не найдено")
            return None

        return suggestions[0]

    def format_address_by_quality(self, result: Dict[str, Any]) -> str:
        """
        Форматирование адреса с учётом qc_geo (качество геокодинга).

        Стратегия:
        - qc_geo 0-1: value как есть (дом / ближайший дом)
        - qc_geo 2: "Местоположение установлено относительно ..." + value
        - qc_geo 3-4: регион + район + город/НП (без точного адреса)
        - qc_geo 5 или нет данных: "-"

        Args:
            result: Один suggestion из DaData (с полями value, data)

        Returns:
            Отформатированный адрес.
        """
        data = result.get("data", {})
        qc_geo = data.get("qc_geo")
        value = result.get("value", "")

        if qc_geo is None:
            return value if value else "-"

        qc_geo = int(qc_geo)

        if qc_geo <= 1:
            # Точный адрес (дом или ближайший дом)
            return value

        if qc_geo == 2:
            # Улица -- формулируем относительно
            return f"Местоположение установлено относительно: {value}"

        if qc_geo <= 4:
            # НП или город -- собираем из компонентов
            parts = []
            for field in ("region", "area", "city", "settlement"):
                val = data.get(field)
                if val:
                    field_type = data.get(f"{field}_type", "")
                    if field_type:
                        parts.append(f"{field_type} {val}")
                    else:
                        parts.append(val)
            if parts:
                return "Местоположение установлено относительно: " + ", ".join(parts)
            return value if value else "-"

        # qc_geo == 5 -- координаты не определены
        return "-"

    def clear_cache(self) -> None:
        """Очистка сессионного кэша."""
        count = len(self._session_cache)
        self._session_cache.clear()
        if count > 0:
            log_info(f"M_39: Кэш очищен ({count} записей)")

    # ── Private ───────────────────────────────────────────────

    def _request(self, url: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        HTTP POST к DaData API с retry и обработкой ошибок.

        Args:
            url: Endpoint URL
            payload: JSON payload

        Returns:
            Parsed JSON response или None при ошибке.
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Token {self._api_key}",
        }

        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.post(
                    url, json=payload, headers=headers,
                    timeout=self.DEFAULT_TIMEOUT,
                )

                if response.status_code == 429:
                    # Rate limit -- подождать и повторить
                    log_warning("M_39: Rate limit DaData, ожидание 1 сек")
                    time.sleep(1)
                    continue

                if response.status_code in (401, 403):
                    log_error(
                        "M_39: Невалидный API-ключ DaData или email не подтверждён "
                        f"(HTTP {response.status_code})"
                    )
                    return None

                response.raise_for_status()
                return response.json()

            except requests.ConnectionError:
                if attempt < self.MAX_RETRIES - 1:
                    delay = 2 ** attempt
                    log_warning(f"M_39: Ошибка подключения к DaData, повтор через {delay} сек")
                    time.sleep(delay)
                else:
                    log_error("M_39: DaData недоступен после всех попыток")

            except requests.Timeout:
                if attempt < self.MAX_RETRIES - 1:
                    log_warning(f"M_39: Таймаут DaData, повтор {attempt + 2}/{self.MAX_RETRIES}")
                else:
                    log_error(f"M_39: Таймаут DaData после {self.MAX_RETRIES} попыток")

            except requests.RequestException as e:
                log_error(f"M_39: Ошибка запроса к DaData: {e}")
                return None

        return None

    def _get_cache_key(self, lat: float, lon: float) -> str:
        """Ключ кэша: округление до 4 знаков (~10м точность)."""
        return f"{round(lat, 4)}_{round(lon, 4)}"

    def _load_key_from_settings(self) -> Optional[str]:
        """Загрузка API-ключа из QSettings."""
        value = QSettings().value(self.SETTINGS_KEY)
        return str(value) if value else None

    def _save_key_to_settings(self, key: str) -> None:
        """Сохранение API-ключа в QSettings."""
        QSettings().setValue(self.SETTINGS_KEY, key)
