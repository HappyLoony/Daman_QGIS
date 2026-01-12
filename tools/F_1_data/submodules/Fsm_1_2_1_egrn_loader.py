# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_1_2_1 для загрузки данных ЕГРН через API NSPD
Используется функцией F_1_2_Загрузка Web карт

ВАЖНО: Использует requests.post() для HTTP запросов (thread-safe, без Qt event loop).
       Ранее использовался QNetworkAccessManager + QEventLoop, но это вызывало
       access violation при параллельной загрузке из-за вложенных event loop'ов.
"""

import json
from typing import Optional, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import random
import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

from qgis.core import (
    QgsVectorLayer, QgsProject, QgsField, QgsFeature, QgsGeometry,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY,
    QgsRectangle
)
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.utils import log_info, log_warning, log_error, log_success
from Daman_QGIS.constants import DEFAULT_REQUEST_TIMEOUT, DEFAULT_MAX_WORKERS, DEFAULT_MAX_RETRIES
from collections import deque
import threading


def requests_post_with_timeout(url, session=None, **kwargs):
    """
    Wrapper для requests.post() с ПРИНУДИТЕЛЬНЫМ timeout через threading.

    НА WINDOWS без VPN requests.post() может зависать НАВСЕГДА, игнорируя timeout!
    Причины: DNS resolve, SSL handshake, Windows socket blocking, антивирус.

    Решение: Запускаем requests.post() в отдельном потоке и УБИВАЕМ поток если зависнет.

    Args:
        url: URL для запроса
        session: requests.Session для Connection Pooling (опционально)
        **kwargs: Параметры для requests.post (json, headers, timeout, verify, etc.)

    Returns:
        Response object или None если timeout
    """
    result: Dict[str, Any] = {'response': None, 'exception': None}

    def target():
        try:
            # Подавляем warnings о непроверенных SSL сертификатах (как в старой версии)
            urllib3.disable_warnings(InsecureRequestWarning)

            # Используем session если передан (Connection Pooling), иначе прямой requests.post()
            if session:
                result['response'] = session.post(url, **kwargs)
            else:
                result['response'] = requests.post(url, **kwargs)
        except Exception as e:
            result['exception'] = e

    thread = threading.Thread(target=target, daemon=True)
    thread.start()

    # Ждём завершения потока с timeout
    # Если timeout в kwargs, используем его + 5 сек запас
    # Иначе используем 30 сек по умолчанию
    timeout_value = kwargs.get('timeout', 30)
    if isinstance(timeout_value, tuple):
        # timeout=(connect, read) -> берём сумму + 5 сек запас
        max_timeout = sum(timeout_value) + 5
    else:
        max_timeout = timeout_value + 5

    thread.join(timeout=max_timeout)

    if thread.is_alive():
        # Поток всё ещё работает = ЗАВИСАНИЕ!
        log_error(f"Fsm_1_2_1: TIMEOUT: ПРИНУДИТЕЛЬНЫЙ TIMEOUT requests.post() после {max_timeout} сек!")
        log_error(f"Fsm_1_2_1:    URL: {url[:100]}...")
        log_error(f"Fsm_1_2_1:    Поток будет убит принудительно (daemon=True)")
        return None

    if result['exception']:
        raise result['exception']

    return result['response']


class RateLimiter:
    """
    Ограничитель частоты запросов (не более N запросов в секунду)

    Thread-safe реализация для параллельных запросов.
    Предотвращает 429 ошибки и защищает от временной блокировки IP.
    """
    def __init__(self, max_per_second: int = 10):
        """
        Args:
            max_per_second: Максимальное количество запросов в секунду
        """
        self.max_per_second = max_per_second
        self.requests = deque()  # Timestamps последних запросов
        self.lock = threading.Lock()  # Защита от race conditions в многопоточной среде

    def wait_if_needed(self):
        """Ждать если достигнут лимит запросов в секунду"""
        with self.lock:
            now = time.time()

            # Удаляем запросы старше 1 секунды
            while self.requests and self.requests[0] < now - 1:
                self.requests.popleft()

            # Если достигнут лимит - ждем
            if len(self.requests) >= self.max_per_second:
                sleep_time = 1 - (now - self.requests[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    # Очищаем устаревшие после ожидания
                    now = time.time()
                    while self.requests and self.requests[0] < now - 1:
                        self.requests.popleft()

            # Регистрируем текущий запрос
            self.requests.append(time.time())


class Fsm_1_2_1_EgrnLoader:
    """Загрузчик данных ЕГРН через API NSPD"""

    def __init__(self, iface, api_manager):
        """
        Инициализация загрузчика

        Args:
            iface: Интерфейс QGIS
            api_manager: APIManager для получения endpoint параметров
        """
        self.iface = iface
        self.api_manager = api_manager
        # Кэш ответов API: {hash(payload): response}
        self._api_cache = {}
        # Счетчики HTTP ошибок для мониторинга
        self._http_error_counts = {
            '403': 0,  # Forbidden - блокировка IP
            '429': 0,  # Too Many Requests - превышение лимита
            'connection': 0,  # Connection errors - проблемы с соединением
            'other': 0  # Прочие HTTP ошибки
        }

        # ОПТИМИЗАЦИЯ: Rate Limiting для защиты от перегрузки API
        # Гарантирует не более 10 запросов в секунду, предотвращает 429 ошибки
        self.rate_limiter = RateLimiter(max_per_second=10)

        # ОПТИМИЗАЦИЯ: Connection Pooling через requests.Session + HTTPAdapter
        # Keep-alive соединения - меньше SSL handshakes, быстрее повторные запросы
        # Thread-safe для использования в ThreadPoolExecutor
        import requests
        from requests.adapters import HTTPAdapter

        self.session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=5,   # Число одновременных соединений (max_workers в F_1_2)
            pool_maxsize=10,      # Максимум соединений в пуле
            max_retries=0         # Retry логика реализована в send_request()
        )
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)

    def clear_cache(self):
        """Очистить кэш API (вызывать при повторной загрузке)"""
        self._api_cache = {}

    def log_http_error_stats(self):
        """Вывести статистику HTTP ошибок для мониторинга"""
        total_errors = sum(self._http_error_counts.values())

        if total_errors > 0:
            log_warning(f"Fsm_1_2_1: МОНИТОРИНГ API: Статистика ошибок")
            if self._http_error_counts['403'] > 0:
                log_error(f"Fsm_1_2_1: FORBIDDEN: Ошибок 403 (Forbidden): {self._http_error_counts['403']}")
            if self._http_error_counts['429'] > 0:
                log_warning(f"Fsm_1_2_1: TOO MANY REQUESTS: Ошибок 429 (Too Many Requests): {self._http_error_counts['429']}")
            if self._http_error_counts['connection'] > 0:
                log_warning(f"Fsm_1_2_1: CONNECTION ERROR: Ошибок соединения (Connection Error): {self._http_error_counts['connection']}")
            if self._http_error_counts['other'] > 0:
                log_warning(f"Fsm_1_2_1: HTTP ERROR: Прочих HTTP ошибок: {self._http_error_counts['other']}")
            log_warning(f"Fsm_1_2_1: Всего ошибок API: {total_errors}")

            # Сбрасываем счетчики после вывода статистики
            self._http_error_counts = {'403': 0, '429': 0, 'connection': 0, 'other': 0}

    def get_boundary_extent(self, use_500m_buffer: bool = False, use_no_buffer: bool = False) -> Optional[Dict[str, Any]]:
        """
        Получить геометрию границ в формате GeoJSON (WGS84)

        Args:
            use_500m_buffer: Использовать слой L_1_1_3 (500м буфер) - для ЗОУИТ, ОКС
            use_no_buffer: Использовать слой L_1_1_1 (без буфера) - для ЗУ, КК, НП (чтобы бюджет считал правильно)

        Returns:
            dict: Геометрия полигона в формате GeoJSON или None
        """
        try:
            # Выбираем слой в зависимости от параметров
            if use_no_buffer:
                layer_name = 'L_1_1_1_Границы_работ'  # Точные границы без буфера
            elif use_500m_buffer:
                layer_name = 'L_1_1_3_Границы_работ_500_м'  # Буфер 500м
            else:
                layer_name = 'L_1_1_2_Границы_работ_10_м'  # Буфер 10м (по умолчанию)

            # Ищем слой в проекте
            layers = QgsProject.instance().mapLayersByName(layer_name)
            if not layers:
                log_error(f"Fsm_1_2_1: Слой {layer_name} не найден! Загрузка невозможна.")
                return None

            layer = layers[0]
            if not isinstance(layer, QgsVectorLayer):
                log_error(f"Fsm_1_2_1: Слой {layer_name} не является векторным")
                return None

            # Если слой в режиме редактирования - коммитим изменения
            if layer.isEditable():
                log_warning(f"Fsm_1_2_1: Слой {layer_name} в режиме редактирования, выполняем commitChanges()")
                layer.commitChanges()

            # Обновляем данные провайдера (на случай устаревшего кэша)
            layer.dataProvider().reloadData()

            # Проверяем наличие объектов
            if layer.featureCount() == 0:
                log_error(f"Fsm_1_2_1: Слой {layer_name} пустой! Загрузка невозможна.")
                return None

            # Получаем геометрию всех объектов слоя
            features = list(layer.getFeatures())

            # Проверяем наличие features (может быть 0 если слой в режиме редактирования)
            if not features:
                log_warning(f"Fsm_1_2_1: Слой {layer_name} не содержит features (getFeatures() вернул пустой список)!")
                log_warning(f"Fsm_1_2_1: isValid={layer.isValid()}, isEditable={layer.isEditable()}, featureCount={layer.featureCount()}")
                # Fallback: используем extent слоя как прямоугольник
                log_warning(f"Fsm_1_2_1: Использую fallback через layer.extent()")
                extent = layer.extent()
                if extent.isEmpty():
                    log_error(f"Fsm_1_2_1: Extent слоя {layer_name} пустой!")
                    return None
                # Создаём геометрию из extent
                combined_geom = QgsGeometry.fromRect(extent)
            else:
                # Объединяем все геометрии
                combined_geom = features[0].geometry()
                for feature in features[1:]:
                    combined_geom = combined_geom.combine(feature.geometry())

            # Трансформируем в WGS84
            crs_src = layer.crs()
            crs_dest = QgsCoordinateReferenceSystem('EPSG:4326')
            transform = QgsCoordinateTransform(crs_src, crs_dest, QgsProject.instance())
            combined_geom.transform(transform)

            # Конвертируем в GeoJSON
            geojson_str = combined_geom.asJson()
            geometry_dict = json.loads(geojson_str)

            return geometry_dict

        except Exception as e:
            log_error(f"Fsm_1_2_1: Ошибка получения границ из {layer_name}: {str(e)}")
            return None

    def create_geojson(self, geometry_dict: Dict[str, Any], category_id: int) -> Dict[str, Any]:
        """
        Создать payload для API запроса

        Args:
            geometry_dict: Геометрия в формате GeoJSON
            category_id: ID категории ЕГРН

        Returns:
            dict: Payload для API
        """
        feature_geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": geometry_dict,
                "properties": {}
            }]
        }
        # category_id передаётся ТОЛЬКО в payload (НЕ в URL)
        return {"categories": [{"id": category_id}], "geom": feature_geojson}

    def _extract_origin_from_referer(self, referer_url: str) -> str:
        """
        Извлечь Origin URL из Referer (для CORS заголовков)

        Args:
            referer_url: Referer URL (например, "https://nspd.gov.ru/map")

        Returns:
            Origin URL (например, "https://nspd.gov.ru")
        """
        from urllib.parse import urlparse
        try:
            parsed = urlparse(referer_url)
            return f"{parsed.scheme}://{parsed.netloc}"
        except Exception as e:
            log_warning(f"Fsm_1_2_1: Не удалось извлечь Origin из Referer '{referer_url}': {e}")
            return referer_url  # Fallback на полный Referer

    def send_request(self, payload: Dict[str, Any], layer_name: Optional[str] = None, retry_on_429: bool = True) -> Optional[Dict[str, Any]]:
        """
        Отправить запрос к API NSPD с обработкой rate limiting, timeout и кэшированием

        ВАЖНО: Использует requests.post() (thread-safe, без Qt event loop) для корректной
        работы в ThreadPoolExecutor. QNetworkAccessManager + QEventLoop вызывали access violation
        при вложенных event loop'ах в разных потоках.

        Args:
            payload: Данные запроса (с category_id внутри)
            layer_name: Имя слоя для получения endpoint из api_manager (ОБЯЗАТЕЛЬНО)
            retry_on_429: Повторять запрос при ошибке 429 (Too Many Requests)

        Returns:
            dict: Ответ API или None

        Raises:
            ValueError: Если endpoint не найден или некорректен
        """
        assert self.api_manager is not None  # Type narrowing для Pylance

        import hashlib

        # Проверяем кэш
        cache_key = hashlib.md5(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        if cache_key in self._api_cache:
            cached_result = self._api_cache[cache_key]
            return cached_result

        # Получаем endpoint из api_manager (ОБЯЗАТЕЛЬНО)
        if not layer_name:
            raise ValueError("layer_name обязателен для получения endpoint из api_manager")

        endpoint = self.api_manager.get_endpoint_by_layer(layer_name)
        if not endpoint:
            raise ValueError(
                f"Endpoint для слоя '{layer_name}' не найден в Base_api_endpoints.json!\n"
                f"Добавьте endpoint или удалите слой из загрузки F_1_2."
            )

        # Формируем URL (БЕЗ category_id - он только в payload!)
        url_template = endpoint.get('url_template')
        if not url_template:
            raise ValueError(
                f"url_template отсутствует в endpoint '{layer_name}' (Base_api_endpoints.json)!\n"
                f"Исправьте конфигурацию endpoint."
            )

        api_url = url_template.format(base_url=endpoint['base_url'])

        # Получаем остальные параметры из endpoint
        referer = endpoint.get('referer_url')
        origin = self._extract_origin_from_referer(referer) if referer else None
        timeouts = self.api_manager.parse_timeout(endpoint.get('timeout_sec'))
        max_retries = endpoint.get('max_retries', DEFAULT_MAX_RETRIES)

        base_retry_delay = 2.0  # Начальная задержка для exponential backoff

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    # Exponential Backoff с Jitter
                    retry_delay = base_retry_delay * (2 ** (attempt - 1)) + random.uniform(0, 1)
                    time.sleep(retry_delay)

                # Обработка прогрессивных таймаутов
                if isinstance(timeouts, list):
                    current_timeout = timeouts[attempt] if attempt < len(timeouts) else timeouts[-1]
                elif isinstance(timeouts, int):
                    current_timeout = timeouts
                else:
                    current_timeout = DEFAULT_REQUEST_TIMEOUT

                # Rate Limiting
                self.rate_limiter.wait_if_needed()

                # Формируем headers для requests
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "*/*",
                    "Content-Type": "application/json",
                    "Origin": origin,
                    "Referer": referer,
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-origin"
                }

                # Отправляем синхронный POST запрос через requests (thread-safe)
                # timeout=(connect_timeout, read_timeout) - защита от зависания БЕЗ VPN
                # ВНИМАНИЕ: На Windows без VPN requests.post() может зависать НЕСМОТРЯ на timeout!
                # Причины: DNS resolve, SSL handshake, Windows socket blocking, антивирус
                # Решение: Используем requests_post_with_timeout() wrapper с принудительным timeout

                request_start = time.time()

                try:
                    response = requests_post_with_timeout(
                        api_url,
                        session=self.session,  # Connection Pooling через HTTPAdapter
                        json=payload,
                        headers=headers,
                        timeout=(10, current_timeout),  # 10 сек на connect, current_timeout на read
                        verify=False  # Отключаем проверку SSL - может помочь при зависании
                    )

                    # Проверяем, что wrapper не вернул None (принудительный timeout)
                    if response is None:
                        log_error(f"Fsm_1_2_1: TIMEOUT: ПРИНУДИТЕЛЬНЫЙ TIMEOUT: requests.post() был убит после зависания")
                        return None

                except requests.exceptions.Timeout as e:
                    request_elapsed = time.time() - request_start
                    log_error(f"Fsm_1_2_1: TIMEOUT: TIMEOUT requests.post() после {request_elapsed:.1f} сек: {str(e)}")
                    return None
                except requests.exceptions.SSLError as e:
                    # SSL ошибки (UNEXPECTED_EOF_WHILE_READING, handshake failure) - retry
                    request_elapsed = time.time() - request_start
                    self._http_error_counts['connection'] += 1
                    if attempt < max_retries - 1:
                        retry_delay = base_retry_delay * (2 ** attempt) + random.uniform(0, 1)
                        log_warning(f"Fsm_1_2_1: SSL ERROR: SSL ошибка после {request_elapsed:.1f} сек: {str(e)}")
                        log_warning(f"Fsm_1_2_1: Повторная попытка через {retry_delay:.1f} сек (попытка {attempt + 2}/{max_retries})")
                        time.sleep(retry_delay)
                        continue
                    else:
                        log_error(f"Fsm_1_2_1: SSL ERROR: SSL ошибка после {max_retries} попыток: {str(e)}")
                        return None
                except requests.exceptions.ConnectionError as e:
                    # Connection errors - retry
                    request_elapsed = time.time() - request_start
                    self._http_error_counts['connection'] += 1
                    if attempt < max_retries - 1:
                        retry_delay = base_retry_delay * (2 ** attempt) + random.uniform(0, 1)
                        log_warning(f"Fsm_1_2_1: CONNECTION ERROR: Ошибка соединения после {request_elapsed:.1f} сек: {str(e)}")
                        log_warning(f"Fsm_1_2_1: Повторная попытка через {retry_delay:.1f} сек (попытка {attempt + 2}/{max_retries})")
                        time.sleep(retry_delay)
                        continue
                    else:
                        log_error(f"Fsm_1_2_1: CONNECTION ERROR: Ошибка соединения после {max_retries} попыток: {str(e)}")
                        return None
                except Exception as e:
                    request_elapsed = time.time() - request_start
                    log_error(f"Fsm_1_2_1: ERROR: ОШИБКА requests.post() после {request_elapsed:.1f} сек: {str(e)}")
                    return None

                http_status = response.status_code

                # Обработка ошибок HTTP
                if http_status == 429 and retry_on_429 and attempt < max_retries - 1:
                    self._http_error_counts['429'] += 1
                    next_delay = base_retry_delay * (2 ** attempt) + random.uniform(0, 1)
                    log_warning(f"Fsm_1_2_1: МОНИТОРИНГ API: Ошибка 429 (Too Many Requests) - превышен лимит запросов")
                    log_warning(f"Fsm_1_2_1: Повторная попытка через {next_delay:.1f} сек (попытка {attempt + 2}/{max_retries})")
                    continue

                elif http_status == 403:
                    self._http_error_counts['403'] += 1
                    log_error(f"Fsm_1_2_1: FORBIDDEN: МОНИТОРИНГ API: Ошибка 403 (Forbidden) - возможна блокировка IP")
                    log_error(f"Fsm_1_2_1: Рекомендация: проверьте доступ к nspd.gov.ru или уменьшите количество потоков")
                    return None

                elif http_status != 200:
                    self._http_error_counts['other'] += 1
                    log_error(f"Fsm_1_2_1: HTTP ERROR: МОНИТОРИНГ API: Ошибка HTTP {http_status}")
                    return None

                # Успешный ответ
                if response.text:
                    result = response.json()

                    # Сохраняем в кэш
                    self._api_cache[cache_key] = result

                    return result
                else:
                    log_warning("Fsm_1_2_1: API вернул пустой ответ")
                    return None

            except requests.exceptions.Timeout:
                # Timeout - требуется дробление территории
                log_warning(f"Fsm_1_2_1: Timeout ({current_timeout} сек) при запросе к API - требуется дробление территории")
                return None

            except requests.exceptions.RequestException as e:
                self._http_error_counts['other'] += 1
                if attempt < max_retries - 1:
                    next_delay = base_retry_delay * (2 ** attempt) + random.uniform(0, 1)
                    log_warning(f"Fsm_1_2_1: REQUEST ERROR: МОНИТОРИНГ API: Ошибка при запросе - попытка {attempt + 1}/{max_retries}")
                    log_warning(f"Fsm_1_2_1: Повтор через {next_delay:.1f} сек: {str(e)}")
                    continue
                else:
                    log_error(f"Fsm_1_2_1: Ошибка при запросе к API после {max_retries} попыток: {str(e)}")
                    return None

            except Exception as e:
                self._http_error_counts['other'] += 1
                if attempt < max_retries - 1:
                    next_delay = base_retry_delay * (2 ** attempt) + random.uniform(0, 1)
                    log_warning(f"Fsm_1_2_1: UNEXPECTED ERROR: МОНИТОРИНГ API: Неожиданная ошибка - попытка {attempt + 1}/{max_retries}")
                    log_warning(f"Fsm_1_2_1: Повтор через {next_delay:.1f} сек: {str(e)}")
                    continue
                else:
                    log_error(f"Fsm_1_2_1: Неожиданная ошибка при запросе к API после {max_retries} попыток: {str(e)}")
                    return None

        log_error(f"Fsm_1_2_1: МОНИТОРИНГ API: Исчерпаны все {max_retries} попытки запроса к API НСПД")
        return None

    def create_geometry(self, geometry_type: str, coordinates: Any) -> Optional[QgsGeometry]:
        """
        Создать QGIS геометрию из GeoJSON координат

        Args:
            geometry_type: Тип геометрии (Polygon, MultiPolygon, etc.)
            coordinates: Координаты в формате GeoJSON

        Returns:
            QgsGeometry или None
        """
        try:
            if geometry_type == "Polygon":
                return QgsGeometry.fromPolygonXY(
                    [[QgsPointXY(x, y) for x, y in ring] for ring in coordinates]
                )
            
            elif geometry_type == "MultiPolygon":
                multipolygons = []
                for polygon in coordinates:
                    if not any(isinstance(ring, list) for ring in polygon):
                        polygon = [polygon]
                    rings = [[QgsPointXY(x, y) for x, y in ring] for ring in polygon]
                    multipolygons.append(rings)
                return QgsGeometry.fromMultiPolygonXY(multipolygons)
            
            elif geometry_type == "Point":
                x, y = coordinates
                return QgsGeometry.fromPointXY(QgsPointXY(x, y))
            
            elif geometry_type == "MultiPoint":
                if isinstance(coordinates[0], (list, tuple)):
                    points = [QgsPointXY(x, y) for x, y in coordinates]
                else:
                    points = [QgsPointXY(x, y) for x, y in [coordinates]]
                return QgsGeometry.fromMultiPointXY(points)
            
            elif geometry_type == "LineString":
                return QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in coordinates])
            
            elif geometry_type == "MultiLineString":
                multilines = []
                for line in coordinates:
                    if not any(isinstance(point, (list, tuple)) for point in line):
                        line = [line]
                    points = [QgsPointXY(x, y) for x, y in line]
                    multilines.append(points)
                return QgsGeometry.fromMultiPolylineXY(multilines)

            log_warning(f"Fsm_1_2_1: Неизвестный тип геометрии: {geometry_type}")
            return None

        except Exception as e:
            log_error(f"Fsm_1_2_1: Ошибка создания геометрии: {str(e)}")
            return None

    def _force_split_geometry(self, geometry: QgsGeometry, crs: QgsCoordinateReferenceSystem, grid_size: int) -> list:
        """
        Принудительно разбить геометрию на сетку NxN ячеек (при timeout API)

        Args:
            geometry: Геометрия для разбиения
            crs: CRS геометрии
            grid_size: Размер сетки (например, 2 для 2x2 = 4 ячейки)

        Returns:
            list: Список геометрий-ячеек
        """
        bbox = geometry.boundingBox()
        cell_width = bbox.width() / grid_size
        cell_height = bbox.height() / grid_size

        grid_geometries = []
        skipped_cells = 0

        for i in range(grid_size):
            for j in range(grid_size):
                # Создаем прямоугольник ячейки
                x_min = bbox.xMinimum() + i * cell_width
                y_min = bbox.yMinimum() + j * cell_height
                x_max = x_min + cell_width
                y_max = y_min + cell_height

                cell_rect = QgsRectangle(x_min, y_min, x_max, y_max)
                cell_geom = QgsGeometry.fromRect(cell_rect)

                # ОПТИМИЗАЦИЯ: Проверяем реальное пересечение перед intersection
                if not cell_geom.intersects(geometry):
                    skipped_cells += 1
                    continue

                # Пересекаем с исходной геометрией
                intersection = cell_geom.intersection(geometry)

                if not intersection.isEmpty():
                    grid_geometries.append(intersection)

        total_cells = grid_size * grid_size
        log_info(f"Fsm_1_2_1: Создано {len(grid_geometries)} ячеек при принудительном разбиении (пропущено {skipped_cells} из {total_cells})")
        return grid_geometries

    def _load_cell_with_subdivision(self, cell_geometry: QgsGeometry, category_id: int,
                                    cell_label: str, layer_name: str, max_depth: int = 2, current_depth: int = 0) -> list:
        """
        Загрузить данные для ячейки с автоматическим дроблением при timeout

        Args:
            cell_geometry: Геометрия ячейки
            category_id: ID категории ЕГРН
            cell_label: Метка ячейки для логирования (например, "1/3")
            layer_name: Имя слоя для получения endpoint из api_manager
            max_depth: Максимальная глубина рекурсивного дробления
            current_depth: Текущая глубина рекурсии

        Returns:
            list: Список features из API
        """
        import json
        from qgis.PyQt.QtWidgets import QApplication

        # Конвертируем геометрию в GeoJSON
        grid_geom_json = json.loads(cell_geometry.asJson())
        payload = self.create_geojson(grid_geom_json, category_id)

        # Отправляем запрос
        response = self.send_request(payload, layer_name=layer_name)

        # Успешная загрузка
        if response and "features" in response and response["features"]:
            return response["features"]

        # Timeout или нет данных
        if response is None:
            # Timeout - пробуем дробление
            if current_depth < max_depth:
                log_info(f"Fsm_1_2_1: Ячейка {cell_label}: timeout - дробление на 2x2 подъячейки (глубина {current_depth + 1}/{max_depth})")

                # Разбиваем ячейку на 2x2
                sub_cells = self._force_split_geometry(cell_geometry, QgsCoordinateReferenceSystem('EPSG:4326'), 2)

                all_sub_features = []
                for sub_idx, sub_cell in enumerate(sub_cells, start=1):
                    sub_label = f"{cell_label}.{sub_idx}"
                    # КРИТИЧНО: НЕ вызываем QApplication.processEvents() в worker потоке!
                    # Метод _load_cell_with_subdivision вызывается из ThreadPoolExecutor
                    # QApplication.processEvents()

                    # Рекурсивно загружаем подъячейку
                    sub_features = self._load_cell_with_subdivision(
                        sub_cell, category_id, sub_label, layer_name, max_depth, current_depth + 1
                    )
                    all_sub_features.extend(sub_features)

                log_info(f"Fsm_1_2_1: Ячейка {cell_label}: собрано {len(all_sub_features)} объектов из {len(sub_cells)} подъячеек")
                return all_sub_features
            else:
                # Достигнута максимальная глубина
                log_warning(f"Fsm_1_2_1: Ячейка {cell_label}: достигнута максимальная глубина дробления ({max_depth}), данные пропущены")
                return []
        else:
            # Пустой ответ (нет данных в этой ячейке)
            return []

    def _parallel_load_cells(self, grid_geometries: list, category_id: int, category_name: str,
                            layer_name: str, max_workers: int = 3, progress_task = None) -> list:
        """
        Параллельная загрузка данных для списка ячеек сетки

        Args:
            grid_geometries: Список геометрий ячеек для загрузки
            category_id: ID категории ЕГРН
            category_name: Название категории (для логов)
            layer_name: Имя слоя для получения endpoint из api_manager
            max_workers: Максимальное количество параллельных потоков (по умолчанию 3)
            progress_task: ProgressTask для обновления прогресса

        Returns:
            list: Объединенный список features из всех ячеек
        """
        from qgis.PyQt.QtWidgets import QApplication

        total_cells = len(grid_geometries)

        # Решаем использовать ли параллелизм
        use_parallel = total_cells > 1

        if not use_parallel:
            # Загружаем единственную ячейку последовательно
            cell_features = self._load_cell_with_subdivision(
                grid_geometries[0], category_id, "1/1", layer_name
            )
            return cell_features if cell_features else []

        # Запуск параллельной загрузки
        all_features = []
        completed_count = 0
        start_time = time.time()
        cell_timings = []  # Список (cell_idx, время_загрузки)

        def load_single_cell(idx_and_geom):
            """Загрузить одну ячейку (для запуска в потоке)"""
            idx, grid_geom = idx_and_geom
            cell_label = f"{idx}/{total_cells}"

            cell_start = time.time()

            # Загружаем ячейку с автоматическим дроблением при timeout
            cell_features = self._load_cell_with_subdivision(
                grid_geom, category_id, cell_label, layer_name
            )

            cell_elapsed = time.time() - cell_start

            return {
                'idx': idx,
                'features': cell_features if cell_features else [],
                'time': cell_elapsed
            }

        # Создаем список (индекс, геометрия) для параллельной обработки
        indexed_geometries = list(enumerate(grid_geometries, start=1))

        # Запускаем параллельную загрузку
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Отправляем все задачи
            future_to_idx = {
                executor.submit(load_single_cell, idx_geom): idx_geom[0]
                for idx_geom in indexed_geometries
            }

            # Собираем результаты по мере завершения
            for future in as_completed(future_to_idx):
                # Проверка отмены пользователем
                if progress_task and progress_task.is_canceled():
                    log_warning(f"Fsm_1_2_1: Загрузка {category_name} отменена пользователем")
                    executor.shutdown(wait=False, cancel_futures=True)
                    return []

                try:
                    # КРИТИЧНО: timeout=120 сек (2 мин) на загрузку ОДНОЙ ячейки
                    # Если поток зависнет, не блокируем весь executor
                    result = future.result(timeout=120)
                    all_features.extend(result['features'])
                    cell_timings.append((result['idx'], result['time']))
                    completed_count += 1

                except TimeoutError:
                    idx = future_to_idx[future]
                    log_error(f"Fsm_1_2_1: TIMEOUT (120 сек) загрузки ячейки {idx}/{total_cells} - пропускаем ячейку")
                    completed_count += 1
                    # Не прерываем весь процесс - пропускаем проблемную ячейку
                except Exception as e:
                    idx = future_to_idx[future]
                    log_error(f"Fsm_1_2_1: Ошибка загрузки ячейки {idx}/{total_cells}: {str(e)}")
                    completed_count += 1

                # КРИТИЧНО: НЕ ВЫЗЫВАЕМ QApplication.processEvents() во время параллельной загрузки!
                # Это вызывает race condition с QEventLoop.exec_() в worker потоках → access violation
                # QApplication.processEvents()

        # Выводим статистику HTTP ошибок (если были)
        self.log_http_error_stats()

        return all_features

    def _split_geometry_to_grid(self, geometry: QgsGeometry, crs: QgsCoordinateReferenceSystem, layer_name: str) -> list:
        """
        Разбить геометрию на сетку ячеек для батчинга запросов

        Args:
            geometry: Геометрия для разбиения
            crs: CRS геометрии
            layer_name: Имя слоя для получения split_threshold_km2 из api_manager

        Returns:
            list: Список геометрий-ячеек или [geometry] если разбиение не требуется
        """
        assert self.api_manager is not None  # Type narrowing для Pylance

        # Вычисляем площадь в км²
        # Трансформируем во временную проекцию для точного расчета площади
        area_calc_crs = QgsCoordinateReferenceSystem('EPSG:3857')  # Метры
        if crs.authid() != area_calc_crs.authid():
            transform = QgsCoordinateTransform(crs, area_calc_crs, QgsProject.instance())
            geom_copy = QgsGeometry(geometry)
            geom_copy.transform(transform)
        else:
            geom_copy = geometry

        area_m2 = geom_copy.area()
        area_km2 = area_m2 / 1_000_000

        log_info(f"Fsm_1_2_1: Площадь территории: {area_km2:.2f} км²")

        # Получаем порог из api_manager по имени слоя
        max_area = self.api_manager.get_split_threshold(layer_name)

        # Если порог None (null в JSON) - БЕЗ дробления (для ЗОУИТ и других)
        if max_area is None:
            log_info(f"Fsm_1_2_1: Слой {layer_name}: split_threshold=null - разбиение отключено")
            return [geometry]

        # Если площадь меньше максимальной - не разбиваем
        if area_km2 <= max_area:
            log_info(f"Fsm_1_2_1: Площадь не превышает {max_area} км² (split_threshold для {layer_name}) - разбиение не требуется")
            return [geometry]

        # Разбиваем на сетку
        bbox = geometry.boundingBox()

        # Вычисляем количество ячеек по каждой оси
        grid_cells = int((area_km2 / max_area) ** 0.5) + 1
        log_info(f"Fsm_1_2_1: Разбиение территории на сетку {grid_cells}x{grid_cells} ({grid_cells**2} ячеек) для {layer_name} (split_threshold={max_area} км²)")

        cell_width = bbox.width() / grid_cells
        cell_height = bbox.height() / grid_cells

        grid_geometries = []
        from qgis.PyQt.QtWidgets import QApplication

        total_cells = grid_cells * grid_cells
        skipped_cells = 0  # Счётчик пропущенных пустых ячеек
        cells_with_data = []  # Список индексов ячеек с данными (для диагностики)

        for i in range(grid_cells):
            for j in range(grid_cells):
                # Создаем прямоугольник ячейки
                x_min = bbox.xMinimum() + i * cell_width
                y_min = bbox.yMinimum() + j * cell_height
                x_max = x_min + cell_width
                y_max = y_min + cell_height

                cell_rect = QgsRectangle(x_min, y_min, x_max, y_max)
                cell_geom = QgsGeometry.fromRect(cell_rect)

                # ОПТИМИЗАЦИЯ: Быстрая проверка пересечения bbox'ов перед точной проверкой
                if not cell_geom.boundingBox().intersects(geometry.boundingBox()):
                    skipped_cells += 1
                    continue  # Bounding box'ы не пересекаются - пропускаем

                # ОПТИМИЗАЦИЯ: Проверяем реальное пересечение геометрий
                if not cell_geom.intersects(geometry):
                    skipped_cells += 1
                    continue  # Геометрии не пересекаются - пропускаем

                # Пересекаем с исходной геометрией (только для пересекающихся ячеек)
                intersection = cell_geom.intersection(geometry)

                if not intersection.isEmpty():
                    grid_geometries.append(intersection)
                    cells_with_data.append((i, j))

                # Обновляем интерфейс каждые 10 ячеек
                current = i * grid_cells + j + 1
                if current % 10 == 0:
                    log_info(f"Fsm_1_2_1: Создание сетки: {current}/{total_cells} ячеек (пропущено пустых: {skipped_cells})...")
                    QApplication.processEvents()

        efficiency = (1 - skipped_cells / total_cells) * 100 if total_cells > 0 else 0
        log_info(f"Fsm_1_2_1: Создано {len(grid_geometries)} непустых ячеек для загрузки (пропущено {skipped_cells} пустых, эффективность: {efficiency:.1f}%)")

        return grid_geometries

    def load_layer(
        self,
        layer_name: str,
        geometry_provider,
        progress_task = None
    ) -> Tuple[Optional[QgsVectorLayer], int]:
        """
        Загрузить слой из API NSPD с автоматическим батчингом для больших территорий

        Args:
            layer_name: Имя слоя для получения ВСЕХ параметров из api_manager
            geometry_provider: Функция для получения геометрии запроса
            progress_task: ProgressTask для обновления прогресса

        Returns:
            tuple: (слой, количество объектов) или (None, 0)

        Raises:
            ValueError: Если endpoint не найден или некорректен
        """
        from qgis.PyQt.QtWidgets import QApplication

        assert self.api_manager is not None  # Type narrowing для Pylance

        # Получаем endpoint из api_manager
        endpoint = self.api_manager.get_endpoint_by_layer(layer_name)
        if not endpoint:
            raise ValueError(
                f"Endpoint для слоя '{layer_name}' не найден в Base_api_endpoints.json!\n"
                f"Проверьте конфигурацию или удалите слой из загрузки."
            )

        # Извлекаем все параметры из endpoint
        category_id = endpoint.get('category_id')
        if category_id is None:
            raise ValueError(
                f"category_id отсутствует в endpoint '{layer_name}' (Base_api_endpoints.json)!\n"
                f"Исправьте конфигурацию endpoint."
            )

        category_name = endpoint.get('category_name')
        if category_name is None:
            raise ValueError(
                f"category_name отсутствует в endpoint '{layer_name}' (Base_api_endpoints.json)!\n"
                f"Исправьте конфигурацию endpoint."
            )

        # КРИТИЧНО: НЕ вызываем QApplication.processEvents() во время параллельной загрузки!
        # load_layer() вызывается из ГЛАВНОГО потока, но если в это время работают worker потоки
        # из ThreadPoolExecutor (_parallel_load_cells), то processEvents() создаёт race condition
        # с QEventLoop.exec_() в worker потоках → access violation.
        # ProgressManager уже обновляет UI через task.update(), эти вызовы избыточны.
        # QApplication.processEvents()

        # Получаем геометрию для запроса
        geometry = geometry_provider()
        if not geometry:
            log_warning(f"Fsm_1_2_1: Не удалось получить геометрию для {category_name}")
            return None, 0

        # Конвертируем геометрию
        import json

        if isinstance(geometry, dict):
            # Уже словарь GeoJSON - создаем QgsGeometry из координат
            geometry_type = geometry.get('type', '')
            coordinates = geometry.get('coordinates', [])

            qgs_geometry = self.create_geometry(geometry_type, coordinates)
            if not qgs_geometry or qgs_geometry.isEmpty():
                log_warning(f"Fsm_1_2_1: Не удалось создать геометрию из GeoJSON dict для {category_name}")
                return None, 0

            source_crs = QgsCoordinateReferenceSystem('EPSG:4326')
        else:
            # QgsGeometry
            qgs_geometry = geometry
            source_crs = QgsCoordinateReferenceSystem('EPSG:4326')

        # Проверяем, нужно ли разбивать геометрию на части
        grid_geometries = self._split_geometry_to_grid(qgs_geometry, source_crs, layer_name)
        # QApplication.processEvents()

        # Если разбиение не требовалось или площадь маленькая - один запрос
        if len(grid_geometries) == 1:
            # Используем исходную геометрию (dict) или конвертируем QgsGeometry обратно в dict
            if isinstance(geometry, dict):
                geometry_geojson = geometry
            else:
                geometry_geojson = json.loads(qgs_geometry.asJson())

            # Прогрессивное дробление: при timeout делаем /2 территории до 3 уровней
            max_split_levels = 3  # Максимум 3 уровня дробления (2x2, 4x4, 8x8)
            current_geometry = qgs_geometry

            for split_level in range(1, max_split_levels + 1):
                if split_level == 1:
                    # Первая попытка - отправляем весь полигон
                    geometry_geojson = json.loads(current_geometry.asJson()) if isinstance(geometry, QgsGeometry) else geometry
                    payload = self.create_geojson(geometry_geojson, category_id)
                    response = self.send_request(payload, layer_name=layer_name)
                else:
                    # Уровень дробления > 1: используем разбиение
                    grid_size = 2 ** split_level  # 2, 4, 8...
                    log_info(f"Fsm_1_2_1: Прогрессивное дробление: уровень {split_level}/{max_split_levels}, сетка {grid_size}x{grid_size}")
                    grid_geometries = self._force_split_geometry(current_geometry, source_crs, grid_size)
                    # Переходим к батчинговой загрузке (код ниже)
                    break

                # Проверяем результат
                if response is None:
                    # Timeout - переходим к следующему уровню дробления
                    log_warning(f"Fsm_1_2_1: Timeout API на уровне {split_level}/{max_split_levels} - дробление территории пополам")
                    continue  # Попробуем следующий уровень дробления
                elif "features" not in response or not response["features"]:
                    # Штатная ситуация - нет данных в области
                    return None, 0
                else:
                    # Успех - возвращаем результат
                    return self._create_layer_from_response(response, category_name)

            # Если дошли сюда - все 3 уровня timeout, используем последнюю сетку
            if not grid_geometries:
                log_error(f"Fsm_1_2_1: Не удалось загрузить {category_name} даже после {max_split_levels} уровней дробления")
                return None, 0

        # Батчинг: загружаем каждую ячейку сетки (последовательно или параллельно)
        log_info(f"Fsm_1_2_1: Начало батчинговой загрузки {category_name} ({len(grid_geometries)} ячеек)")
        # QApplication.processEvents()

        # Получаем max_workers из endpoint (используем уже полученный endpoint)
        max_workers_value = endpoint.get('max_workers', DEFAULT_MAX_WORKERS)

        # ПАРАЛЛЕЛЬНАЯ загрузка с N потоками (из базы данных)
        all_features = self._parallel_load_cells(
            grid_geometries=grid_geometries,
            category_id=category_id,
            category_name=category_name,
            layer_name=layer_name,
            max_workers=max_workers_value,
            progress_task=progress_task
        )

        if not all_features:
            log_warning(f"Fsm_1_2_1: Батчинговая загрузка не вернула данных для {category_name}")
            return None, 0

        log_info(f"Fsm_1_2_1: Батчинговая загрузка завершена: {len(all_features)} объектов для {category_name}")

        # Создаём слой из всех собранных features
        combined_response = {"features": all_features}
        return self._create_layer_from_response(combined_response, category_name)

    def _create_layer_from_response(
        self, 
        response: Dict[str, Any], 
        layer_name: str
    ) -> Tuple[Optional[QgsVectorLayer], int]:
        """
        Создать векторный слой из ответа API

        Args:
            response: Ответ API с features
            layer_name: Имя создаваемого слоя

        Returns:
            tuple: (слой, количество объектов)
        """
        try:
            features_data = response["features"]
            if not features_data:
                return None, 0

            # Определяем тип геометрии
            first_feature = features_data[0]
            geometry_type_str = first_feature["geometry"]["type"]
            
            layer_type = {
                "Polygon": "Polygon",
                "MultiPolygon": "MultiPolygon",
                "LineString": "LineString",
                "MultiLineString": "MultiLineString",
                "Point": "Point",
                "MultiPoint": "MultiPoint",
            }.get(geometry_type_str, "Polygon")

            # Создаём временный слой
            layer = QgsVectorLayer(f"{layer_type}?crs=EPSG:3857", layer_name, "memory")
            provider = layer.dataProvider()

            # Создаём поля на основе первого объекта
            attributes = [QgsField("interactionId", QMetaType.Type.QString)]
            if first_feature["properties"].get("options"):
                for key, value in first_feature["properties"]["options"].items():
                    field_type = QMetaType.Type.QString
                    if isinstance(value, int):
                        field_type = QMetaType.Type.LongLong
                    elif isinstance(value, float):
                        field_type = QMetaType.Type.Double
                    attributes.append(QgsField(key, field_type))

            provider.addAttributes(attributes)
            layer.updateFields()

            # Получаем список полей для проверки при установке атрибутов
            field_names = [field.name() for field in layer.fields()]

            # Добавляем все объекты одним вызовом для синхронного появления на карте
            layer.startEditing()
            features_to_add = []

            for idx, feature_data in enumerate(features_data, start=1):
                interaction_id = str(feature_data["properties"].get("interactionId", ""))
                if not interaction_id:
                    continue

                geometry_data = feature_data.get("geometry", {})
                if not geometry_data or not geometry_data.get("coordinates"):
                    continue

                geometry = self.create_geometry(geometry_data["type"], geometry_data["coordinates"])
                if not geometry or geometry.isEmpty():
                    continue

                new_feature = QgsFeature(layer.fields())
                new_feature.setGeometry(geometry)
                new_feature.setAttribute("interactionId", interaction_id)

                props = feature_data["properties"].get("options", {})
                for key, value in props.items():
                    if key in field_names:
                        if value is None:
                            new_feature.setAttribute(key, None)
                        elif isinstance(value, list):
                            new_feature.setAttribute(key, "; ".join(map(str, value)))
                        else:
                            new_feature.setAttribute(key, value)

                features_to_add.append(new_feature)

            # Добавляем все объекты одним вызовом
            if features_to_add:
                provider.addFeatures(features_to_add)

            layer.commitChanges()
            layer.updateExtents()

            # Удаляем дубликаты по interactionId (возникают при фрагментированной загрузке)
            duplicates_removed = self._remove_duplicates_by_interaction_id(layer)

            return layer, len(features_to_add)

        except Exception as e:
            log_error(f"Fsm_1_2_1: Ошибка создания слоя из ответа API: {str(e)}")
            return None, 0

    def _remove_duplicates_by_interaction_id(self, layer: QgsVectorLayer) -> int:
        """
        Удаление дублей по interactionId из слоя

        Дубли появляются при загрузке по фрагментам через API NSPD.
        Крупные объекты попадают в несколько фрагментов, создавая дубли.
        Оставляет только первую найденную запись для каждого уникального interactionId.

        Args:
            layer: Слой для дедупликации

        Returns:
            int: Количество удалённых дублей
        """
        # Проверяем наличие поля interactionId
        if layer.fields().indexOf('interactionId') == -1:
            # Если поля нет - это нормально для некоторых слоев (например, АТД)
            return 0

        # Собираем уникальные interactionId и ID дублей
        seen_interaction_ids = set()
        duplicate_ids = []

        for feature in layer.getFeatures():
            interaction_id = feature['interactionId']

            if not interaction_id or interaction_id == '' or interaction_id == '-':
                continue

            if interaction_id in seen_interaction_ids:
                # Это дубль - добавляем ID для удаления
                duplicate_ids.append(feature.id())
            else:
                # Первая встреча этого interactionId
                seen_interaction_ids.add(interaction_id)

        # Удаляем дубли
        if duplicate_ids:
            layer.startEditing()
            layer.deleteFeatures(duplicate_ids)
            layer.commitChanges()

            log_info(f"Fsm_1_2_1: Удалено дублей из {layer.name()}: {len(duplicate_ids)} (уникальных объектов: {len(seen_interaction_ids)})")
            return len(duplicate_ids)
        else:
            return 0

    def _classify_by_database(self, props: dict) -> Optional[str]:
        """
        Классифицировать ЗОУИТ по правилам из справочной базы данных

        Правила загружаются из Base_zouit_classification.json через ZOUITClassificationManager.
        Проверка происходит по приоритету (rule_id): меньше = раньше.

        Args:
            props: Словарь атрибутов объекта

        Returns:
            str: full_name слоя ЗОУИТ или None если не распознано
        """
        from Daman_QGIS.managers import get_reference_managers

        # Получаем правила классификации (отсортированы по rule_id)
        ref_managers = get_reference_managers()
        rules = ref_managers.zouit_classification.get_rules()

        # Извлекаем поля для поиска
        search_texts = {
            'type_zone': props.get("type_zone", "").lower(),
            'name_by_doc': props.get("name_by_doc", "").lower(),
            'doc_name': props.get("doc_name", "").lower(),
            'type_boundary_value': props.get("type_boundary_value", "").lower()
        }

        # Проверяем каждое правило по порядку rule_id (приоритет)
        for rule in rules:
            search_field_raw = rule.get('search_field', '').strip()
            keywords_raw = rule.get('keywords', '').strip()

            if not search_field_raw or not keywords_raw:
                continue

            # Разбиваем search_field и keywords по ";"
            search_fields = [f.strip() for f in search_field_raw.split(';') if f.strip()]
            keywords_list = [k.strip() for k in keywords_raw.split(';') if k.strip()]

            # Проверяем количество полей и ключевых слов
            if len(search_fields) > 1:
                # СЛУЧАЙ 1: Несколько полей - каждое ключевое слово проверяется в своем поле
                if len(search_fields) != len(keywords_list):
                    log_warning(
                        f"Fsm_1_2_1: Rule {rule.get('rule_id')}: "
                        f"количество полей ({len(search_fields)}) != количество keywords ({len(keywords_list)})"
                    )
                    continue

                # Проверяем все пары (поле, ключевое слово)
                all_matched = True
                for field, keyword in zip(search_fields, keywords_list):
                    search_text = search_texts.get(field, '')
                    if keyword not in search_text:
                        all_matched = False
                        break

                if all_matched:
                    return rule.get('target_layer')

            else:
                # СЛУЧАЙ 2: Одно поле - ЛЮБОЕ ключевое слово должно быть найдено (OR)
                field = search_fields[0]
                search_text = search_texts.get(field, '')

                # ЛЮБОЕ из ключевых слов должно присутствовать в поле (OR логика)
                if any(keyword in search_text for keyword in keywords_list):
                    return rule.get('target_layer')

        # Не распознано
        return None

    def load_zouit_layers(self, layer_name: str, geometry_provider, layer_manager, progress_task = None) -> tuple:
        """
        Загрузить слои ЗОУИТ с распределением по type_zone

        Args:
            layer_name: Имя слоя для получения endpoint из api_manager
            geometry_provider: Функция для получения геометрии запроса
            layer_manager: LayerReferenceManager для получения справочника ЗОУИТ
            progress_task: ProgressTask для обновления прогресса

        Returns:
            tuple: (словарь {layer_name: layer}, общее количество объектов)

        Raises:
            ValueError: Если endpoint не найден или некорректен
        """
        from Daman_QGIS.managers import get_reference_managers
        from .Fsm_1_2_1_zouit_classifier_dialog import ZouitClassifierDialog

        assert self.api_manager is not None  # Type narrowing для Pylance

        # Получаем endpoint для ЗОУИТ из Base_api_endpoints.json
        endpoint = self.api_manager.get_endpoint_by_layer(layer_name)
        if not endpoint:
            raise ValueError(
                f"Endpoint для ЗОУИТ слоя '{layer_name}' не найден в Base_api_endpoints.json!\n"
                f"Проверьте конфигурацию endpoint."
            )

        # Извлекаем category_id из endpoint
        category_id = endpoint.get('category_id')
        if category_id is None:
            raise ValueError(
                f"category_id отсутствует в endpoint '{layer_name}' (Base_api_endpoints.json)!\n"
                f"Исправьте конфигурацию endpoint."
            )

        # Извлекаем category_name из endpoint
        category_name = endpoint.get('category_name')
        if category_name is None:
            raise ValueError(
                f"category_name отсутствует в endpoint '{layer_name}' (Base_api_endpoints.json)!\n"
                f"Исправьте конфигурацию endpoint."
            )

        log_info(f"Fsm_1_2_1: Начало загрузки ЗОУИТ слоёв: {category_name} (category_id={category_id})")

        # Получаем геометрию для запроса
        geometry = geometry_provider()
        if not geometry:
            log_warning("Fsm_1_2_1: Не удалось получить геометрию для ЗОУИТ")
            return {}, 0

        # Конвертируем геометрию в QgsGeometry для анализа площади
        import json
        from qgis.PyQt.QtWidgets import QApplication

        if isinstance(geometry, dict):
            geometry_type = geometry.get('type', '')
            coordinates = geometry.get('coordinates', [])
            qgs_geometry = self.create_geometry(geometry_type, coordinates)
            if not qgs_geometry or qgs_geometry.isEmpty():
                log_warning("Fsm_1_2_1: Не удалось создать геометрию из GeoJSON для ЗОУИТ")
                return {}, 0
            source_crs = QgsCoordinateReferenceSystem('EPSG:4326')
        else:
            qgs_geometry = geometry
            source_crs = QgsCoordinateReferenceSystem('EPSG:4326')

        # Проверяем нужно ли дробление (для ЗОУИТ split_threshold="null" в Base_api_endpoints.json)
        # Это означает что разбиение НЕ произойдет на этапе _split_geometry_to_grid,
        # НО _load_cell_with_subdivision всё равно сработает при timeout
        grid_geometries = self._split_geometry_to_grid(qgs_geometry, source_crs, layer_name)

        # Получаем max_workers из уже полученного endpoint
        max_workers_value = endpoint.get('max_workers', DEFAULT_MAX_WORKERS)

        # Батчинг: загружаем каждую ячейку (обычно одна для ЗОУИТ, но может быть несколько при timeout)
        # ПАРАЛЛЕЛЬНАЯ загрузка с N потоками (из базы данных)
        all_features = self._parallel_load_cells(
            grid_geometries=grid_geometries,
            category_id=category_id,
            category_name=category_name,
            layer_name=layer_name,
            max_workers=max_workers_value,
            progress_task=progress_task
        )

        if not all_features:
            log_warning("Fsm_1_2_1: Не получено данных ЗОУИТ (возможно нет объектов в данной области)")
            return {}, 0

        features_data = all_features
        log_info(f"Fsm_1_2_1: Получено {len(features_data)} объектов ЗОУИТ из API")

        # Получаем справочник ЗОУИТ из Base_layers.json (для GUI классификатора)
        ref_managers = get_reference_managers()
        zouit_data = ref_managers.zouit.get_zouit()

        # Группируем объекты по правилам из Base_zouit_classification.json
        groups = {}
        unknown_features = []  # Список неопознанных объектов для GUI классификации

        for feature_data in features_data:
            props = feature_data["properties"].get("options", {})

            # Классификация ТОЛЬКО через Base_zouit_classification.json
            target_layer = self._classify_by_database(props)

            if not target_layer:
                # Не распознано по правилам - добавляем в список для GUI классификации
                unknown_features.append(feature_data)
                continue  # Пропускаем, обработаем через GUI

            if target_layer not in groups:
                groups[target_layer] = []

            groups[target_layer].append(feature_data)

        # Обрабатываем неопознанные объекты через GUI
        if unknown_features:
            log_info(f"Fsm_1_2_1: Обнаружено {len(unknown_features)} неопознанных объектов ЗОУИТ")
            log_info("Fsm_1_2_1: Запуск GUI классификатора для ручного распределения...")

            skip_all_flag = False
            for idx, feature_data in enumerate(unknown_features, start=1):
                # Проверка отмены пользователем перед каждым диалогом классификации
                if progress_task and progress_task.is_canceled():
                    log_warning(f"Fsm_1_2_1: Классификация ЗОУИТ отменена пользователем на объекте {idx}/{len(unknown_features)}")
                    return {}, 0

                if skip_all_flag:
                    # "Пропустить все" - отправляем в ИНАЯ_ЗОНА
                    target_layer = "Le_1_2_5_45_WFS_ЗОУИТ_ИНАЯ_ЗОНА"
                else:
                    # Показываем GUI для классификации
                    dialog = ZouitClassifierDialog(
                        parent=self.iface.mainWindow(),
                        feature_data=feature_data,
                        zouit_layers=zouit_data,
                        current_index=idx,
                        total_count=len(unknown_features)
                    )

                    if dialog.exec_():
                        selected_layer, skip_all_flag = dialog.get_result()

                        if selected_layer:
                            # Пользователь выбрал конкретный слой
                            target_layer = selected_layer
                            log_info(f"Fsm_1_2_1: Объект #{idx} классифицирован пользователем как: {target_layer}")
                        else:
                            # Пользователь нажал "Пропустить" или "Пропустить все"
                            target_layer = "Le_1_2_5_45_WFS_ЗОУИТ_ИНАЯ_ЗОНА"
                            log_info(f"Fsm_1_2_1: Объект #{idx} отправлен в ИНАЯ_ЗОНА (пропущен пользователем)")
                    else:
                        # Диалог закрыт без выбора - отправляем в ИНАЯ_ЗОНА
                        target_layer = "Le_1_2_5_45_WFS_ЗОУИТ_ИНАЯ_ЗОНА"
                        log_warning(f"Fsm_1_2_1: Объект #{idx} отправлен в ИНАЯ_ЗОНА (диалог закрыт)")

                # Добавляем объект в соответствующую группу
                if target_layer not in groups:
                    groups[target_layer] = []
                groups[target_layer].append(feature_data)

        log_info(f"Fsm_1_2_1: Объекты распределены по {len(groups)} слоям ЗОУИТ")

        # Создаем слои для каждой группы
        layers = {}
        total_count = 0

        for layer_name, group_features in groups.items():
            # Создаем временный response для группы
            group_response = {"features": group_features}

            layer, count = self._create_layer_from_response(group_response, layer_name)
            if layer and count > 0:
                layers[layer_name] = layer
                total_count += count

        return layers, total_count

    def _load_single_oks_type(self, oks_type: str, category_id: int, geometry,
                              qgs_geometry: QgsGeometry, source_crs: QgsCoordinateReferenceSystem,
                              grid_geometries: list, layer_name: str, progress_task = None) -> list:
        """
        Загрузить один тип ОКС (для параллельного выполнения)

        Args:
            oks_type: Тип ОКС ('Здание', 'Сооружения', 'ОНС')
            category_id: ID категории ЕГРН
            layer_name: Имя слоя для получения endpoint из api_manager
            geometry: Исходная геометрия (dict или QgsGeometry)
            qgs_geometry: QgsGeometry для дробления
            source_crs: CRS геометрии
            grid_geometries: Предварительно разбитая сетка ячеек
            progress_task: ProgressTask для обновления прогресса

        Returns:
            list: Список features для данного типа ОКС
        """
        import json
        assert self.api_manager is not None  # Type narrowing для Pylance

        from qgis.PyQt.QtWidgets import QApplication

        # Проверка отмены пользователем
        if progress_task and progress_task.is_canceled():
            log_warning(f"Fsm_1_2_1: Загрузка ОКС-{oks_type} отменена пользователем")
            return []

        # Формируем правильное имя слоя для поиска endpoint в api_manager
        # layer_name приходит как "L_1_2_4_WFS_ОКС", но endpoint'ы называются:
        # "L_1_2_4_WFS_ОКС_Здания", "L_1_2_4_WFS_ОКС_Сооружения", "L_1_2_4_WFS_ОКС_ОНС"
        oks_type_mapping = {
            'Здание': 'Здания',  # Множественное число для endpoint
            'Сооружения': 'Сооружения',
            'ОНС': 'ОНС'
        }
        specific_layer_name = f"{layer_name}_{oks_type_mapping.get(oks_type, oks_type)}"

        log_info(f"Fsm_1_2_1: ПАРАЛЛЕЛИЗМ ОКС: Поток начал загрузку {oks_type} (category_id={category_id})")
        log_info(f"Fsm_1_2_1: ОКС-{oks_type}: Используется endpoint для слоя {specific_layer_name}")

        # Инициализация переменных для загрузки
        features = []
        use_batching = False
        current_grid_geometries = list(grid_geometries)  # Копия для изменения

        # Загружаем данные для этого типа ОКС (батчинг или одним запросом)
        if len(current_grid_geometries) == 1:
            # Прогрессивное дробление при timeout
            log_info(f"Fsm_1_2_1: ОКС-{oks_type}: Начало загрузки с прогрессивным дроблением при timeout")

            max_split_levels = 3
            current_geometry = qgs_geometry
            response = None

            for split_level in range(1, max_split_levels + 1):
                if split_level == 1:
                    # Первая попытка - отправляем весь полигон
                    if isinstance(geometry, dict):
                        geometry_geojson = geometry
                    else:
                        geometry_geojson = json.loads(current_geometry.asJson())

                    payload = self.create_geojson(geometry_geojson, category_id)
                    response = self.send_request(payload, layer_name=specific_layer_name)
                else:
                    # Уровень дробления > 1: используем разбиение
                    grid_size = 2 ** split_level
                    log_info(f"Fsm_1_2_1: ОКС-{oks_type}: Прогрессивное дробление уровень {split_level}/{max_split_levels}, сетка {grid_size}x{grid_size}")
                    current_grid_geometries = self._force_split_geometry(current_geometry, source_crs, grid_size)
                    use_batching = True
                    break

                # Проверяем результат
                if response is None:
                    log_warning(f"Fsm_1_2_1: ОКС-{oks_type}: Timeout API на уровне {split_level}/{max_split_levels} - дробление территории")
                    continue
                elif "features" not in response or not response["features"]:
                    # Штатная ситуация - нет объектов в области
                    features = []
                    break
                else:
                    features = response["features"]
                    log_info(f"Fsm_1_2_1: ОКС-{oks_type}: Успешная загрузка на уровне {split_level} ({len(features)} объектов)")
                    break

            # Если после всех попыток response == None, активируем батчинг
            if response is None and len(current_grid_geometries) > 1:
                log_info(f"Fsm_1_2_1: ОКС-{oks_type}: Все уровни timeout, переход к батчинговой загрузке ({len(current_grid_geometries)} ячеек)")
                use_batching = True
        else:
            # Изначально больше 1 ячейки - используем батчинг
            use_batching = True

        # Получаем max_workers из endpoint (вместо hardcoded значения)
        endpoint = self.api_manager.get_endpoint_by_layer(specific_layer_name)
        max_workers_value = endpoint.get('max_workers', DEFAULT_MAX_WORKERS) if endpoint else DEFAULT_MAX_WORKERS

        # Батчинговая загрузка для множественных ячеек
        if use_batching:
            features = self._parallel_load_cells(
                grid_geometries=current_grid_geometries,
                category_id=category_id,
                category_name=f"ОКС-{oks_type}",
                layer_name=specific_layer_name,
                max_workers=max_workers_value,
                progress_task=progress_task
            )

        return features

    def load_oks_combined(self, layer_name: str, geometry_provider, progress_task = None) -> Tuple[Optional[QgsVectorLayer], int]:
        """
        Загрузить все типы ОКС (Здание, Сооружения, ОНС) в один слой L_1_2_4_WFS_ОКС

        Делает 3 API запроса и объединяет результаты с добавлением поля oks_type

        Args:
            layer_name: Имя слоя для получения endpoint из api_manager
            geometry_provider: Функция для получения геометрии запроса
            progress_task: ProgressTask для обновления прогресса

        Returns:
            tuple: (слой, количество объектов) или (None, 0)

        Raises:
            ValueError: Если OKS endpoints не найдены или некорректны
        """
        from qgis.PyQt.QtWidgets import QApplication

        log_info("Fsm_1_2_1: Начало загрузки объединённого слоя ОКС (Здание + Сооружения + ОНС)")
        assert self.api_manager is not None  # Type narrowing для Pylance

        # Получаем список ОКС слоёв из APIManager (single source of truth)
        oks_layer_names = self.api_manager.OKS_LAYER_NAMES

        # Маппинг суффикса layer_name → oks_type для feature properties
        # (учитываем что "Здания" (plural) → "Здание" (singular) для oks_type)
        suffix_to_oks_type = {
            "Здания": "Здание",       # singular для oks_type
            "Сооружения": "Сооружения",
            "ОНС": "ОНС"
        }

        # Строим oks_categories из endpoints: {oks_type: category_id}
        oks_categories = {}
        for oks_layer_name in oks_layer_names:
            endpoint = self.api_manager.get_endpoint_by_layer(oks_layer_name)
            if not endpoint:
                raise ValueError(
                    f"Endpoint для ОКС слоя '{oks_layer_name}' не найден в Base_api_endpoints.json!\n"
                    f"Проверьте конфигурацию endpoint."
                )

            category_id = endpoint.get('category_id')
            if category_id is None:
                raise ValueError(
                    f"category_id отсутствует в endpoint '{oks_layer_name}' (Base_api_endpoints.json)!\n"
                    f"Исправьте конфигурацию endpoint."
                )

            # Извлекаем суффикс: "L_1_2_4_WFS_ОКС_Здания" → "Здания"
            suffix = oks_layer_name.split("L_1_2_4_WFS_ОКС_")[-1]
            oks_type = suffix_to_oks_type.get(suffix)

            if oks_type is None:
                raise ValueError(
                    f"Неизвестный суффикс ОКС слоя: '{suffix}' в '{oks_layer_name}'!\n"
                    f"Ожидаемые суффиксы: {list(suffix_to_oks_type.keys())}"
                )

            oks_categories[oks_type] = category_id

        # Валидация: должно быть ровно 3 типа ОКС
        if len(oks_categories) != 3:
            raise ValueError(
                f"Ожидается 3 типа ОКС, получено: {len(oks_categories)}\n"
                f"Проверьте конфигурацию Base_api_endpoints.json"
            )

        log_info(f"Fsm_1_2_1: Получены ОКС endpoints: {oks_categories}")

        # Получаем геометрию
        geometry = geometry_provider()
        if not geometry:
            log_warning("Fsm_1_2_1: Не удалось получить геометрию для ОКС")
            return None, 0

        # Конвертируем геометрию в QgsGeometry для анализа площади
        if isinstance(geometry, dict):
            geometry_type = geometry.get('type', '')
            coordinates = geometry.get('coordinates', [])
            qgs_geometry = self.create_geometry(geometry_type, coordinates)
            if not qgs_geometry or qgs_geometry.isEmpty():
                log_warning("Fsm_1_2_1: Не удалось создать геометрию из GeoJSON для ОКС")
                return None, 0
            source_crs = QgsCoordinateReferenceSystem('EPSG:4326')
        else:
            qgs_geometry = geometry
            source_crs = QgsCoordinateReferenceSystem('EPSG:4326')

        # Проверяем нужно ли дробление
        grid_geometries = self._split_geometry_to_grid(qgs_geometry, source_crs, layer_name)

        # ============================================================================
        # ПАРАЛЛЕЛЬНАЯ ЗАГРУЗКА ВСЕХ 3 ТИПОВ ОКС (Здание, Сооружения, ОНС)
        # ============================================================================
        start_time = time.time()

        # Получаем max_workers из endpoint (для координирующего ThreadPoolExecutor)
        # Берём из первого типа ОКС (Здания), все 3 типа имеют одинаковые настройки
        first_oks_endpoint = self.api_manager.get_endpoint_by_layer(oks_layer_names[0])
        coordinator_max_workers = first_oks_endpoint.get('max_workers', DEFAULT_MAX_WORKERS) if first_oks_endpoint else DEFAULT_MAX_WORKERS

        # Собираем все features и уникальные поля из всех 3 запросов
        all_features = []
        all_fields = {}  # {field_name: QgsField} - всегда QString при конфликте

        def load_oks_wrapper(oks_type_and_id):
            """Обёртка для загрузки одного типа ОКС в потоке"""
            oks_type, category_id = oks_type_and_id
            oks_start = time.time()

            features = self._load_single_oks_type(
                oks_type=oks_type,
                category_id=category_id,
                geometry=geometry,
                qgs_geometry=qgs_geometry,
                source_crs=source_crs,
                grid_geometries=grid_geometries,
                layer_name=layer_name,
                progress_task=progress_task
            )

            oks_elapsed = time.time() - oks_start

            return {
                'oks_type': oks_type,
                'features': features,
                'time': oks_elapsed
            }

        # Запускаем параллельную загрузку всех 3 типов ОКС (координирующий ThreadPoolExecutor)
        with ThreadPoolExecutor(max_workers=coordinator_max_workers) as executor:
            # Отправляем все задачи
            futures = {
                executor.submit(load_oks_wrapper, item): item[0]
                for item in oks_categories.items()
            }

            # Собираем результаты по мере завершения
            results = []
            completed_count = 0
            total_oks_types = len(oks_categories)

            for future in as_completed(futures):
                # Проверка отмены пользователем
                if progress_task and progress_task.is_canceled():
                    log_warning(f"Fsm_1_2_1: Загрузка ОКС отменена пользователем")
                    executor.shutdown(wait=False, cancel_futures=True)
                    return None, 0

                try:
                    # КРИТИЧНО: timeout=180 сек (3 мин) на загрузку ОДНОГО типа ОКС
                    # Если поток зависнет, не блокируем весь executor
                    result = future.result(timeout=180)
                    results.append(result)
                except TimeoutError:
                    oks_type = futures[future]
                    log_error(f"Fsm_1_2_1: TIMEOUT (180 сек) загрузки {oks_type} - пропускаем тип")
                    # Не прерываем весь процесс - пропускаем проблемный тип ОКС
                except Exception as e:
                    oks_type = futures[future]
                    log_error(f"Fsm_1_2_1: Ошибка загрузки {oks_type}: {str(e)}")

                # ОБНОВЛЕНИЕ ПРОГРЕССА: Показываем завершение каждого типа ОКС
                completed_count += 1
                if progress_task:
                    # Обновляем текст для информирования о прогрессе
                    progress_task.update(
                        completed_count / total_oks_types,
                        f"Загрузка ОКС... ({completed_count}/{total_oks_types} типов)"
                    )

                # КРИТИЧНО: НЕ вызываем QApplication.processEvents() во время параллельной загрузки!
                # Этот цикл as_completed() работает в ГЛАВНОМ потоке, но пока работают worker потоки
                # из ThreadPoolExecutor (load_oks_wrapper), processEvents() создаёт race condition
                # с QEventLoop.exec_() в worker потоках → access violation.
                # ProgressManager уже обновляет UI через progress_task.update(), этот вызов избыточен.
                # QApplication.processEvents()

        # Обрабатываем результаты
        for result in results:
            oks_type = result['oks_type']
            features = result['features']

            log_info(f"Fsm_1_2_1:   Получено {len(features)} объектов типа {oks_type}")

            # Добавляем поле oks_type к каждому feature
            for feature in features:
                if "properties" not in feature:
                    feature["properties"] = {}
                if "options" not in feature["properties"]:
                    feature["properties"]["options"] = {}

                # Добавляем тип ОКС
                feature["properties"]["options"]["oks_type"] = oks_type

            # Собираем уникальные поля (всегда QString при конфликте)
            if features and "properties" in features[0]:
                props = features[0]["properties"].get("options", {})
                for key in props.keys():
                    if key not in all_fields:
                        # Всегда QString как указал пользователь
                        all_fields[key] = QgsField(key, QMetaType.Type.QString)

            all_features.extend(features)

        # Выводим статистику HTTP ошибок (если были)
        self.log_http_error_stats()

        if not all_features:
            log_warning("Fsm_1_2_1: Не получено ни одного объекта ОКС")
            return None, 0

        log_info(f"Fsm_1_2_1: Всего объектов ОКС: {len(all_features)}")

        # Создаём слой с объединёнными полями
        # Определяем тип геометрии из первого feature
        first_feature = all_features[0]
        geometry_type_str = first_feature["geometry"]["type"]

        layer_type_map = {
            "Polygon": "Polygon",
            "MultiPolygon": "MultiPolygon",
            "LineString": "LineString",
            "MultiLineString": "MultiLineString",
            "Point": "Point",
            "MultiPoint": "MultiPoint",
        }
        layer_geom_type = layer_type_map.get(geometry_type_str, "Polygon")

        # Создаём временный слой
        layer = QgsVectorLayer(f"{layer_geom_type}?crs=EPSG:3857", "L_1_2_4_WFS_ОКС", "memory")
        provider = layer.dataProvider()

        # Добавляем все собранные поля (включая oks_type)
        attributes = [QgsField("interactionId", QMetaType.Type.QString)]
        attributes.extend(all_fields.values())

        provider.addAttributes(attributes)
        layer.updateFields()

        # Получаем список полей для проверки при установке атрибутов
        field_names = [field.name() for field in layer.fields()]

        # Добавляем объекты
        layer.startEditing()
        features_to_add = []

        for feature_data in all_features:
            interaction_id = str(feature_data["properties"].get("interactionId", ""))
            if not interaction_id:
                continue

            geometry_data = feature_data.get("geometry", {})
            if not geometry_data or not geometry_data.get("coordinates"):
                continue

            geometry = self.create_geometry(geometry_data["type"], geometry_data["coordinates"])
            if not geometry or geometry.isEmpty():
                continue

            new_feature = QgsFeature(layer.fields())
            new_feature.setGeometry(geometry)
            new_feature.setAttribute("interactionId", interaction_id)

            props = feature_data["properties"].get("options", {})
            for key, value in props.items():
                if key in field_names:
                    if value is None:
                        new_feature.setAttribute(key, None)
                    elif isinstance(value, list):
                        new_feature.setAttribute(key, "; ".join(map(str, value)))
                    else:
                        # Всегда конвертируем в строку (QString)
                        new_feature.setAttribute(key, str(value))

            features_to_add.append(new_feature)

        # Добавляем все объекты одним вызовом
        if features_to_add:
            provider.addFeatures(features_to_add)

        layer.commitChanges()
        layer.updateExtents()

        # Удаляем дубликаты по interactionId (возникают при фрагментированной загрузке)
        duplicates_removed = self._remove_duplicates_by_interaction_id(layer)

        return layer, len(features_to_add)
