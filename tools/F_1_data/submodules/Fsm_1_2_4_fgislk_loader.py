# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_1_2_4 для загрузки данных ФГИС ЛК
Используется функцией F_1_2_Загрузка Web карт

АРХИТЕКТУРА (thread-safety):
- HTTP загрузка тайлов: requests (thread-safe, работает в ThreadPoolExecutor)
- Парсинг PBF файлов: QgsVectorLayer (только в main thread, после загрузки всех тайлов)

ВАЖНО: Qt объекты (QgsNetworkAccessManager, QEventLoop, QgsVectorLayer) НЕ thread-safe!
       Нельзя использовать их в ThreadPoolExecutor - это вызывает access violation.
"""

import math
import os
import hashlib
import time
import shutil
from typing import Optional, Dict, List, Tuple
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# Отключаем предупреждения о небезопасных SSL запросах
# ФГИС ЛК использует российские сертификаты Минцифры, которые не распознаются стандартным certifi
urllib3.disable_warnings(InsecureRequestWarning)

from qgis.core import (
    QgsVectorLayer, QgsProject, QgsFeature, QgsGeometry, QgsField, QgsFields,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY,
    QgsRectangle, QgsWkbTypes, Qgis
)
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.utils import log_info, log_warning, log_error, log_success
from Daman_QGIS.constants import TILE_DOWNLOAD_TIMEOUT


class TileCache:
    """Двухуровневый кэш для тайлов (RAM + диск)"""

    def __init__(self):
        self.memory_cache = {}  # RAM кэш для текущей сессии
        self.disk_cache = {}    # Пути к файлам на диске

    def get(self, key: str) -> Optional[bytes]:
        """Получить тайл из кэша"""
        # Проверяем RAM кэш
        if key in self.memory_cache:
            return self.memory_cache[key]

        # Проверяем диск кэш
        if key in self.disk_cache and os.path.exists(self.disk_cache[key]):
            # Загружаем с диска в память
            try:
                with open(self.disk_cache[key], 'rb') as f:
                    data = f.read()
                    self.memory_cache[key] = data
                    return data
            except Exception:
                return None

        return None

    def put(self, key: str, data: bytes, disk_path: Optional[str] = None):
        """Сохранить тайл в кэш"""
        self.memory_cache[key] = data
        if disk_path:
            self.disk_cache[key] = disk_path

    def clear_memory(self):
        """Очистить RAM кэш (диск остается)"""
        self.memory_cache.clear()


class Fsm_1_2_4_FgislkLoader:
    """Загрузчик данных ФГИС ЛК через vector tiles"""

    # Слои для загрузки в проект (от большего к меньшему)
    # Верифицировано через PBF тайлы 2026-03-22 (25 тайлов Подмосковья, QGIS MCP)
    LAYER_MAPPING = {
        # Административная иерархия (Polygon, от большего к меньшему)
        "FORESTRY_APPROVE": "Le_1_7_2_1_ФГИС_ЛК_УТВ_Лесничества",
        "FORESTRY_TAXATION_DATE": "Le_1_7_2_2_ФГИС_ЛК_Лесничества",
        "DISTRICT_FORESTRY_TAXATION_DATE": "Le_1_7_2_3_ФГИС_ЛК_Уч_Лесничества",
        "QUARTER": "Le_1_7_2_4_ФГИС_ЛК_Кварталы",
        "TAXATION_PIECE": "Le_1_7_2_5_ФГИС_ЛК_Выделы",
        "FOREST_STEAD": "Le_1_7_2_6_ФГИС_ЛК_Участки",
        "PART_FOREST_STEAD": "Le_1_7_2_7_ФГИС_ЛК_Части_участков",
        # Тематические (Polygon) — не обнаружены в PBF z12, возможно на других зумах/районах
        "FOREST_PURPOSE": "Le_1_7_2_8_ФГИС_ЛК_Целевое_назначение",
        "PROTECTIVE_FOREST": "Le_1_7_2_9_ФГИС_ЛК_Защитные_леса",
        "PROTECTIVE_FOREST_SUBCATEGORY": "Le_1_7_2_10_ФГИС_ЛК_Ценные_леса",
        "SPECIAL_PROTECT_STEAD": "Le_1_7_2_11_ФГИС_ЛК_ОЗУ",
        "CLEARCUT": "Le_1_7_2_12_ФГИС_ЛК_Лесосеки",
    }

    # Слои, которые НЕ загружаются, но мониторятся в логах (log_info)
    # Позволяет отслеживать изменения на сервере ФГИС ЛК без засорения проекта
    MONITORED_LAYERS = {
        "FORESTRY",              # Дубль FORESTRY_TAXATION_DATE без taxation_date
        "DISTRICT_FORESTRY",     # Дубль DISTRICT_FORESTRY_TAXATION_DATE без taxation_date
        "SUBJECT_BOUNDARY",      # Дубликат АТД из ЕГРН, нет externalid
        "TIMBER_YARD",           # Склады древесины (Point)
        "PROCESSING_OBJECT",     # Лесопереработка (Point)
    }

    # Слои, для которых уже существуют полигональные определения в Base_layers.json
    # Остальные слои (линии, точки или новые полигоны) получат временные названия
    POLYGON_LAYERS_IN_DB = {
        "FORESTRY_APPROVE",
        "FORESTRY_TAXATION_DATE",
        "DISTRICT_FORESTRY_TAXATION_DATE",
        "QUARTER",
        "TAXATION_PIECE",
        "FOREST_STEAD",
        "PART_FOREST_STEAD",
    }

    # Префикс для временных слоёв (не полигоны или слои без определения в БД)
    TEMP_LAYER_PREFIX = "_TEMP_FGISLK_"

    # Дополнительные слои для обогащения данных (атрибуты из связанных слоёв PBF)
    # Верифицировано через PBF тайлы 2026-03-13
    LAYER_EXTRAS = {
        "FORESTRY_APPROVE": set(),
        "FORESTRY_TAXATION_DATE": set(),
        "DISTRICT_FORESTRY_TAXATION_DATE": set(),
        "QUARTER": {"QUARTER_FIRE_DANGER"},
        "TAXATION_PIECE": {
            "TAXATION_PIECE_BONITET",
            "TAXATION_PIECE_EVENT_SCORE",
            "TAXATION_PIECE_EVENT_TYPE",
            "TAXATION_PIECE_PVS",
            "TAXATION_PIECE_TIMBER_STOCK"
        },
        "FOREST_STEAD": set(),
        "PART_FOREST_STEAD": set(),
        "FOREST_PURPOSE": set(),
        "PROTECTIVE_FOREST": set(),
        "PROTECTIVE_FOREST_SUBCATEGORY": set(),
        "SPECIAL_PROTECT_STEAD": set(),
        "CLEARCUT": set(),
    }

    # Параметры тайловой сетки
    TILE_SIZE_PIXELS = 256
    TILE_ZOOM_SERVER = 12
    CUSTOM_RESOLUTIONS = [
        13999.999999999998, 11199.999999999998, 5599.999999999999,
        2799.9999999999995, 1399.9999999999998, 699.9999999999999,
        280, 140, 55.99999999999999, 27.999999999999996,
        13.999999999998, 6.999999999999999, 2.8
    ]

    # REST API для обогащения атрибутов выделов (attributesinfo)
    # Публичный endpoint, авторизация НЕ требуется
    # object_id = поле mvt_id из PBF тайлов (подтверждено тестами)
    FGISLK_REST_API_URL = "https://map.fgislk.gov.ru/map/geo/map_api/layer/attributesinfo"

    # Маппинг полей REST API -> поля слоя
    # Ключ = имя в JSON payload, Значение = (имя поля в слое, тип QMetaType)
    # Верифицировано 2026-03-13: REST API возвращает 15 полей для TAXATION_PIECE
    ENRICHMENT_FIELDS: Dict[str, tuple] = {
        # Площади и статус
        "square": ("square", QMetaType.Type.Double),
        "totalArea": ("total_area", QMetaType.Type.Double),
        "objectValid": ("object_valid", QMetaType.Type.QString),
        # Категории земель
        "category_land": ("category_land", QMetaType.Type.QString),
        "type_land": ("type_land", QMetaType.Type.QString),
        "forest_land_type": ("forest_land_type", QMetaType.Type.QString),
        # Таксационные характеристики
        "taxation_date": ("taxation_date", QMetaType.Type.QString),
        "tree_species": ("tree_species", QMetaType.Type.QString),
        "age_group": ("age_group", QMetaType.Type.QString),
        "yield_class": ("yield_class", QMetaType.Type.QString),
        "timber_stock": ("timber_stock", QMetaType.Type.QString),
        # Номера и идентификаторы
        "number": ("number", QMetaType.Type.QString),
        "number_lud": ("number_lud", QMetaType.Type.QString),
        "forest_quarter_number": ("forest_quarter_number", QMetaType.Type.QString),
        "forest_quarter_number_lud": ("forest_quarter_number_lud", QMetaType.Type.QString),
        # Лесохозяйственные мероприятия
        "event": ("event", QMetaType.Type.QString),
    }

    # Параметры REST API обогащения
    ENRICHMENT_MAX_WORKERS = 6        # Параллельные запросы к REST API
    ENRICHMENT_REQUEST_TIMEOUT = 15   # Таймаут одного запроса (сек)
    ENRICHMENT_MAX_RETRIES = 2        # Ретраи для REST API

    def __init__(self, iface, api_manager=None):
        """
        Инициализация загрузчика

        Args:
            iface: Интерфейс QGIS
            api_manager: APIManager для получения ФГИС ЛК endpoint (обязательно)
        """
        self.iface = iface
        self.api_manager = api_manager
        self.tile_cache = TileCache()  # Двухуровневый кэш для тайлов

        # Получаем параметры ФГИС ЛК из api_manager (обязательно должен быть в Base_api_endpoints.json)
        assert self.api_manager is not None, "api_manager не инициализирован"

        # Получаем endpoint для ФГИС ЛК (api_group="FGISLK")
        fgislk_endpoints = [ep for ep in self.api_manager.get_all_endpoints() if ep.get('api_group') == 'FGISLK']
        assert fgislk_endpoints, "ФГИС ЛК endpoint не найден в Base_api_endpoints.json (api_group='FGISLK')"

        endpoint = fgislk_endpoints[0]  # Берём первый endpoint из группы FGISLK

        # Формируем tile_url_template из base_url
        base_url = endpoint['base_url']
        self.tile_url_template = f"{base_url}/{{z}}/{{x}}/{{y}}.pbf"

        # Получаем timeout, max_retries и max_workers
        # Парсим progressive timeout "3;10;30" -> берём максимальное значение для тайлов
        timeout_raw = endpoint['timeout_sec']
        parsed_timeout = self.api_manager.parse_timeout(timeout_raw)
        if isinstance(parsed_timeout, list):
            self.timeout = parsed_timeout[-1]  # Берём последнее (максимальное) значение
        else:
            self.timeout = parsed_timeout

        self.max_retries = endpoint['max_retries']
        self.max_workers = endpoint['max_workers']

        # Referer URL (требуется для доступа к ФГИС ЛК с марта 2026)
        referer = endpoint.get('referer_url')
        self.referer_url = referer if referer and referer not in (None, '', '-', 'null') else None

        # HTTP Session с connection pooling и retry (best practice urllib3 + requests docs)
        self._session = self._create_session()

        # HTTP Session для REST API обогащения атрибутов (отдельный хост map.fgislk.gov.ru)
        self._rest_session = self._create_rest_session()

        # Флаг: проверка серверной сетки выполнена (один раз за сессию загрузки)
        self._grid_verified = False

    def _create_session(self) -> requests.Session:
        """Создание HTTP Session с connection pooling и exponential backoff.

        Best practice из официальной документации urllib3 + requests:
        - Connection pooling: переиспользование TCP+TLS соединений к одному хосту
        - Exponential backoff: 0.5, 1, 2, 4 сек (не фиксированная пауза)
        - Jitter: случайная добавка 0-0.5 сек предотвращает thundering herd
        - status_forcelist: HTTP 404 включён, т.к. CDN ФГИС ЛК возвращает случайные 404
          (cache miss GeoWebCache, НЕ реальное отсутствие ресурса)
        """
        retry_strategy = Retry(
            total=self.max_retries,
            status_forcelist=[404, 500, 502, 503, 504],
            allowed_methods=["GET"],
            backoff_factor=0.5,     # задержки: 0.5, 1, 2, 4 сек
            backoff_max=10,         # не больше 10 сек между ретраями
            backoff_jitter=0.5,     # случайная добавка 0-0.5 сек
            raise_on_status=False,  # вернуть Response после исчерпания (не exception)
        )

        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=1,             # один хост (pub4.fgislk.gov.ru)
            pool_maxsize=self.max_workers,  # соответствует ThreadPoolExecutor
        )

        session = requests.Session()
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        session.verify = False  # Российские сертификаты Минцифры
        return session

    def _create_rest_session(self) -> requests.Session:
        """Создание HTTP Session для REST API обогащения атрибутов.

        Отличия от _create_session (тайловый CDN):
        - Отдельный хост: map.fgislk.gov.ru (не pub4.fgislk.gov.ru)
        - 404 НЕ в status_forcelist (404 = реальная ошибка, не cache miss)
        - Меньше ретраев (REST API стабильнее CDN)
        """
        retry_strategy = Retry(
            total=self.ENRICHMENT_MAX_RETRIES,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"],
            backoff_factor=0.5,
            backoff_max=10,
            backoff_jitter=0.5,
            raise_on_status=False,
        )

        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=1,
            pool_maxsize=self.ENRICHMENT_MAX_WORKERS,
        )

        session = requests.Session()
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        session.verify = False  # Российские сертификаты Минцифры
        return session

    def _fetch_attributes(self, mvt_id: int) -> Optional[dict]:
        """Запрос атрибутов одного выдела из REST API (thread-safe).

        Args:
            mvt_id: Числовой ID выдела из PBF тайла (поле mvt_id)

        Returns:
            dict с атрибутами из payload или None при ошибке
        """
        try:
            params = {
                "layer_code": "TAXATION_PIECE",
                "object_id": str(mvt_id),
            }
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
            }
            if self.referer_url:
                headers['Referer'] = self.referer_url

            response = self._rest_session.get(
                self.FGISLK_REST_API_URL,
                params=params,
                headers=headers,
                timeout=self.ENRICHMENT_REQUEST_TIMEOUT,
            )

            if response.status_code != 200:
                return None

            data = response.json()
            payload = data.get("payload")
            if not payload or not isinstance(payload, dict):
                return None

            return payload

        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.SSLError):
            return None
        except Exception as e:
            log_warning(f"Fsm_1_2_4 (_fetch_attributes): {type(e).__name__}: {str(e)[:200]}")
            return None

    def _enrich_attributes(self, mvt_id_map: Dict[str, int]) -> Dict[str, dict]:
        """Параллельное обогащение атрибутов выделов через REST API.

        Args:
            mvt_id_map: {externalid: mvt_id} для запросов

        Returns:
            {externalid: {field_name: value}} -- обогащённые атрибуты
        """
        if not mvt_id_map:
            return {}

        total = len(mvt_id_map)
        log_info(f"Fsm_1_2_4: Обогащение атрибутов: {total} выделов через REST API...")

        enrichment_data: Dict[str, dict] = {}
        success_count = 0
        fail_count = 0

        with ThreadPoolExecutor(max_workers=self.ENRICHMENT_MAX_WORKERS) as executor:
            futures = {
                executor.submit(self._fetch_attributes, mvt_id): eid
                for eid, mvt_id in mvt_id_map.items()
            }

            for future in futures:
                eid = futures[future]
                try:
                    payload = future.result(timeout=self.ENRICHMENT_REQUEST_TIMEOUT + 5)
                    if payload:
                        enriched: Dict[str, object] = {}
                        for api_field, (layer_field, _) in self.ENRICHMENT_FIELDS.items():
                            val = payload.get(api_field)
                            if val is not None:
                                enriched[layer_field] = val
                        enrichment_data[eid] = enriched
                        success_count += 1
                    else:
                        fail_count += 1
                except TimeoutError:
                    fail_count += 1
                except Exception as e:
                    fail_count += 1
                    if fail_count == 1:
                        log_warning(
                            f"Fsm_1_2_4 (_enrich_attributes): первая ошибка: "
                            f"{type(e).__name__}: {str(e)[:200]}"
                        )

        if fail_count > 0:
            log_warning(
                f"Fsm_1_2_4: Обогащение атрибутов: {success_count}/{total} успешно, "
                f"{fail_count} ошибок"
            )
        else:
            log_success(f"Fsm_1_2_4: Обогащение атрибутов: все {total} выделов обогащены")

        return enrichment_data

    def get_boundary_geometry(self) -> Optional[QgsGeometry]:
        """
        Получить геометрию границ из слоя L_1_1_1_Границы_работ

        Returns:
            QgsGeometry: Объединённая геометрия границ или None
        """
        try:
            # Ищем слой границ
            layers = QgsProject.instance().mapLayersByName('L_1_1_1_Границы_работ')
            if not layers:
                log_warning("Fsm_1_2_4: Слой L_1_1_1_Границы_работ не найден. Загрузка ФГИС ЛК невозможна.")
                return None

            layer = layers[0]
            if not isinstance(layer, QgsVectorLayer):
                log_error("Fsm_1_2_4: Слой L_1_1_1_Границы_работ не является векторным!")
                return None

            # Проверяем наличие объектов
            if layer.featureCount() == 0:
                log_error("Fsm_1_2_4: Слой L_1_1_1_Границы_работ пустой! Загрузка ФГИС ЛК невозможна.")
                return None

            # Получаем геометрию всех объектов слоя
            features = list(layer.getFeatures())

            # Объединяем все геометрии
            combined_geom = features[0].geometry()
            for feature in features[1:]:
                combined_geom = combined_geom.combine(feature.geometry())

            return combined_geom

        except Exception as e:
            log_error(f"Fsm_1_2_4: Ошибка получения границ: {str(e)}")
            return None

    def mercator_to_tile(self, x: float, y: float, z: Optional[int] = None) -> Tuple[int, int]:
        """
        Конвертация координат Mercator в индексы тайлов

        Args:
            x: Координата X в EPSG:3857
            y: Координата Y в EPSG:3857
            z: Уровень зума (по умолчанию TILE_ZOOM_SERVER)

        Returns:
            tuple: (tile_x, tile_y)
        """
        if z is None:
            z = self.TILE_ZOOM_SERVER
        res = self.CUSTOM_RESOLUTIONS[z]
        tile_x = int((x + 20037508.34) / (res * self.TILE_SIZE_PIXELS))
        tile_y = int((y + 20037508.34) / (res * self.TILE_SIZE_PIXELS))
        return tile_x, tile_y

    def tile_to_geometry(self, x: int, y: int, z: Optional[int] = None) -> QgsGeometry:
        """
        Создание геометрии тайла по его индексам

        Args:
            x, y: Индексы тайла
            z: Уровень зума (по умолчанию TILE_ZOOM_SERVER)

        Returns:
            QgsGeometry: Прямоугольник тайла в EPSG:3857
        """
        if z is None:
            z = self.TILE_ZOOM_SERVER
        res = self.CUSTOM_RESOLUTIONS[z]
        merc_origin = 20037508.34
        xmin = (x * res * self.TILE_SIZE_PIXELS) - merc_origin
        ymin = (y * res * self.TILE_SIZE_PIXELS) - merc_origin
        xmax = ((x + 1) * res * self.TILE_SIZE_PIXELS) - merc_origin
        ymax = ((y + 1) * res * self.TILE_SIZE_PIXELS) - merc_origin
        return QgsGeometry.fromRect(QgsRectangle(xmin, ymin, xmax, ymax))

    def transform_coords(self, geom: QgsGeometry, xmin: float, ymin: float,
                        xmax: float, ymax: float) -> QgsGeometry:
        """
        Трансформация координат из тайловой системы (0-4096) в глобальные

        Args:
            geom: Геометрия в тайловых координатах
            xmin, ymin, xmax, ymax: Границы тайла в EPSG:3857

        Returns:
            QgsGeometry: Геометрия в глобальных координатах
        """
        def to_global(pt):
            xr, yr = pt.x() / 4096.0, pt.y() / 4096.0
            return QgsPointXY(xmin + (xmax - xmin) * xr, ymin + (ymax - ymin) * yr)

        if geom.isEmpty():
            return QgsGeometry()

        gtype = QgsWkbTypes.geometryType(geom.wkbType())

        if gtype == Qgis.GeometryType.Polygon:
            # МИГРАЦИЯ POLYGON → MULTIPOLYGON: упрощённый паттерн
            parts = [[[to_global(pt) for pt in ring] for ring in part]
                    for part in (geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()])]
            return QgsGeometry.fromMultiPolygonXY(parts)

        elif gtype == Qgis.GeometryType.Line:
            # МИГРАЦИЯ LINESTRING → MULTILINESTRING: упрощённый паттерн
            lines = [[to_global(pt) for pt in line]
                     for line in (geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()])]
            return QgsGeometry.fromMultiPolylineXY(lines)

        elif gtype == Qgis.GeometryType.Point:
            if geom.isMultipart():
                points = [to_global(pt) for pt in geom.asMultiPoint()]
                return QgsGeometry.fromMultiPointXY(points)
            else:
                return QgsGeometry.fromPointXY(to_global(geom.asPoint()))

        return QgsGeometry()

    def _verify_grid(self, response: requests.Response, x: int, y: int) -> None:
        """Сравнить наш расчёт границ тайла с серверным заголовком geowebcache-tile-bounds.

        Вызывается один раз на первом успешном тайле. Если сервер изменил сетку
        (CUSTOM_RESOLUTIONS устарели), разница будет ненулевой — логируем warning.
        """
        self._grid_verified = True
        bounds_header = response.headers.get("geowebcache-tile-bounds")
        if not bounds_header:
            return

        try:
            srv_xmin, srv_ymin, srv_xmax, srv_ymax = map(float, bounds_header.split(","))
        except (ValueError, AttributeError):
            return

        res = self.CUSTOM_RESOLUTIONS[self.TILE_ZOOM_SERVER]
        merc_origin = 20037508.34
        our_xmin = x * res * self.TILE_SIZE_PIXELS - merc_origin
        our_ymin = y * res * self.TILE_SIZE_PIXELS - merc_origin
        our_xmax = (x + 1) * res * self.TILE_SIZE_PIXELS - merc_origin
        our_ymax = (y + 1) * res * self.TILE_SIZE_PIXELS - merc_origin

        max_diff = max(
            abs(our_xmin - srv_xmin), abs(our_ymin - srv_ymin),
            abs(our_xmax - srv_xmax), abs(our_ymax - srv_ymax),
        )

        if max_diff > 0.01:
            log_warning(
                f"Fsm_1_2_4: СЕТКА ФГИС ЛК ИЗМЕНИЛАСЬ! "
                f"Расхождение {max_diff:.3f} м на тайле ({x},{y}). "
                f"Наш: [{our_xmin:.2f},{our_ymin:.2f},{our_xmax:.2f},{our_ymax:.2f}], "
                f"Сервер: [{srv_xmin:.2f},{srv_ymin:.2f},{srv_xmax:.2f},{srv_ymax:.2f}]. "
                f"Требуется обновление CUSTOM_RESOLUTIONS!"
            )
        else:
            log_info(f"Fsm_1_2_4: Серверная сетка верифицирована (diff={max_diff:.6f} м)")

    def download_tile_file(self, x: int, y: int, temp_dir: str) -> Optional[str]:
        """
        Загрузка тайла с сервера (thread-safe)

        Retry обрабатывается urllib3.Retry через Session (exponential backoff + jitter).
        CDN GeoWebCache возвращает случайные HTTP 404 (cache miss) — 404 в status_forcelist.

        ВАЖНО: Использует requests.Session (thread-safe) для работы в ThreadPoolExecutor.
               НЕ использует Qt объекты - они не thread-safe!

        Args:
            x, y: Индексы тайла
            temp_dir: Директория для временных файлов

        Returns:
            str: Путь к загруженному PBF файлу или None при ошибке
        """
        # Подготовка путей и ключа кэша
        hash_name = hashlib.md5(f"{x}_{y}".encode()).hexdigest()
        pbf_path = os.path.join(temp_dir, f"tile_{hash_name}.pbf")
        cache_key = f"{self.TILE_ZOOM_SERVER}_{x}_{y}"

        # Проверяем двухуровневый кэш (RAM + диск)
        cached_data = self.tile_cache.get(cache_key)
        if cached_data:
            if not os.path.exists(pbf_path):
                with open(pbf_path, "wb") as f:
                    f.write(cached_data)
            return pbf_path

        url = self.tile_url_template.format(z=self.TILE_ZOOM_SERVER, x=x, y=y)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*'
        }
        if self.referer_url:
            headers['Referer'] = self.referer_url

        # Retry (exponential backoff + jitter) обрабатывается urllib3.Retry в _session
        # Connection pooling: TCP+TLS переиспользуются между тайлами
        try:
            response = self._session.get(url, headers=headers, timeout=self.timeout)

            if response.status_code == 200 and response.content:
                # Верификация серверной сетки (один раз за сессию)
                if not self._grid_verified:
                    self._verify_grid(response, x, y)

                pbf_data = response.content
                with open(pbf_path, "wb") as f:
                    f.write(pbf_data)
                self.tile_cache.put(cache_key, pbf_data, pbf_path)
                return pbf_path

            if response.status_code == 403:
                # Fatal: доступ запрещён, retry не поможет
                return None

            # Все ретраи urllib3 исчерпаны, тайл недоступен
            return None

        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.SSLError):
            # Все ретраи urllib3 исчерпаны, сетевая ошибка
            return None
        except Exception:
            return None

    def parse_tile(self, pbf_path: str, x: int, y: int,
                   required_layers: set) -> Dict[str, List[QgsFeature]]:
        """
        Парсинг PBF тайла (только в main thread!)

        ВАЖНО: Использует QgsVectorLayer - вызывать ТОЛЬКО из main thread!

        Args:
            pbf_path: Путь к PBF файлу
            x, y: Индексы тайла (для расчёта границ)
            required_layers: Набор необходимых слоёв

        Returns:
            dict: Словарь {layer_name: [features]}
        """
        try:
            # Вычисляем границы тайла
            res = self.CUSTOM_RESOLUTIONS[self.TILE_ZOOM_SERVER]
            xmin = x * res * self.TILE_SIZE_PIXELS - 20037508.34
            ymin = y * res * self.TILE_SIZE_PIXELS - 20037508.34
            xmax = (x + 1) * res * self.TILE_SIZE_PIXELS - 20037508.34
            ymax = (y + 1) * res * self.TILE_SIZE_PIXELS - 20037508.34

            # Получаем список слоёв в PBF через OGR напрямую
            # (не все слои присутствуют в каждом тайле - это нормально)
            from osgeo import ogr
            available_layers = set()
            ds = ogr.Open(pbf_path)
            if ds:
                for i in range(ds.GetLayerCount()):
                    ol = ds.GetLayerByIndex(i)
                    if ol:
                        available_layers.add(ol.GetName())
                ds = None

            # Парсим тайл — открываем только существующие слои
            tile_data = defaultdict(list)
            for lname in required_layers:
                if lname not in available_layers:
                    continue

                uri = f"{pbf_path}|layername={lname}"
                lyr = QgsVectorLayer(uri, lname, "ogr")

                if not lyr.isValid():
                    continue

                # Слои без поля externalid (например SUBJECT_BOUNDARY) пропускаем
                if lyr.fields().indexFromName("externalid") == -1:
                    continue

                skipped_no_eid = 0
                total_feats = 0
                for feat in lyr.getFeatures():
                    total_feats += 1
                    eid = feat.attribute("externalid")
                    if eid is None:
                        skipped_no_eid += 1
                        continue

                    # Трансформируем геометрию
                    g = self.transform_coords(feat.geometry(), xmin, ymin, xmax, ymax)

                    new_feat = QgsFeature()
                    new_feat.setFields(lyr.fields())
                    new_feat.setGeometry(g)
                    new_feat.setAttributes(feat.attributes())
                    tile_data[lname].append(new_feat)

                if skipped_no_eid > 0 and total_feats > 0:
                    skip_ratio = skipped_no_eid / total_feats
                    if skip_ratio > 0.5:
                        log_warning(
                            f"Fsm_1_2_4: Слой {lname} тайл {x}/{y}: "
                            f"{skipped_no_eid}/{total_feats} объектов без externalid "
                            f"({skip_ratio:.0%})"
                        )

            return tile_data

        except Exception as e:
            log_warning(f"Fsm_1_2_4: Ошибка парсинга тайла {x}/{y}: {str(e)}")
            return {}

    def diagnose_pbf_layers(self, pbf_path: str, verbose: bool = False) -> Dict[str, dict]:
        """
        Диагностика: получить список ВСЕХ слоёв в PBF файле с полными схемами.

        Сравнивает с известными слоями и выводит предупреждение
        если обнаружены новые неизвестные слои. В verbose режиме
        дополнительно выводит поля каждого слоя.

        Args:
            pbf_path: Путь к PBF файлу
            verbose: Если True, выводить детали полей каждого слоя

        Returns:
            dict: {layer_name: {"feature_count": int, "fields": [(name, type)]}}
        """
        from osgeo import ogr

        layer_info: Dict[str, dict] = {}
        try:
            ds = ogr.Open(pbf_path)
            if ds:
                for i in range(ds.GetLayerCount()):
                    layer = ds.GetLayerByIndex(i)
                    if layer:
                        lname = layer.GetName()
                        feat_count = layer.GetFeatureCount()
                        # Извлекаем схему полей
                        defn = layer.GetLayerDefn()
                        fields = []
                        for fi in range(defn.GetFieldCount()):
                            fd = defn.GetFieldDefn(fi)
                            fields.append((fd.GetName(), fd.GetTypeName()))

                        layer_info[lname] = {
                            "feature_count": feat_count,
                            "fields": fields,
                        }

                        if verbose:
                            field_names = [f[0] for f in fields]
                            log_info(
                                f"Fsm_1_2_4: PBF слой '{lname}': "
                                f"{feat_count} фичей, поля: {field_names}"
                            )

                ds = None  # Закрываем датасет
        except Exception as e:
            log_warning(f"Fsm_1_2_4: Ошибка диагностики PBF: {str(e)}")
            return layer_info

        # Собираем все известные слои (загружаемые + extras + мониторинг)
        loadable_layers = set(self.LAYER_MAPPING.keys())
        for extras in self.LAYER_EXTRAS.values():
            loadable_layers |= extras
        all_known = loadable_layers | self.MONITORED_LAYERS

        found_layers = set(layer_info.keys())

        # 1. Мониторинг: известные слои, которые не загружаются (log_info)
        monitored_found = found_layers & self.MONITORED_LAYERS
        if monitored_found:
            for lname in sorted(monitored_found):
                info = layer_info[lname]
                field_names = [f[0] for f in info["fields"]]
                log_info(
                    f"Fsm_1_2_4: [{lname}] {info['feature_count']} фичей, "
                    f"поля: {field_names} (мониторинг, не загружается)"
                )

        # 2. Действительно новые слои (log_warning)
        unknown_layers = found_layers - all_known
        if unknown_layers:
            log_warning("Fsm_1_2_4: ОБНАРУЖЕНЫ НОВЫЕ СЛОИ В PBF!")
            for lname in sorted(unknown_layers):
                info = layer_info[lname]
                field_names = [f[0] for f in info["fields"]]
                log_warning(
                    f"Fsm_1_2_4: Неизвестный слой '{lname}': "
                    f"{info['feature_count']} фичей, поля: {field_names}"
                )
            log_warning("Fsm_1_2_4: Проверьте - возможно нужно добавить в LAYER_MAPPING или MONITORED_LAYERS")

        return layer_info

    def load_layers(self, temp_dir: str, enrich_attributes: bool = True) -> Dict[str, QgsVectorLayer]:
        """
        Загрузка всех слоёв ФГИС ЛК

        Args:
            temp_dir: Директория для временных файлов
            enrich_attributes: Обогащать выделы атрибутами из REST API (по умолчанию True)

        Returns:
            dict: Словарь {layer_name: QgsVectorLayer}
        """
        start_total = time.time()

        # Получаем геометрию границ
        boundaries_geom = self.get_boundary_geometry()
        if not boundaries_geom:
            log_error("Fsm_1_2_4: Не удалось получить геометрию границ")
            return {}

        # Трансформируем границы в EPSG:3857
        boundary_layers = QgsProject.instance().mapLayersByName('L_1_1_1_Границы_работ')
        if not boundary_layers:
            log_error("Fsm_1_2_4: Слой L_1_1_1_Границы_работ не найден для определения CRS")
            return {}
        source_crs = boundary_layers[0].crs()
        dest_crs = QgsCoordinateReferenceSystem("EPSG:3857")
        transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())
        boundaries_geom.transform(transform)

        # Буферизуем границу на 10м для захвата граничных объектов
        # (в EPSG:3857 единицы - метры)
        BUFFER_DISTANCE_M = 10
        boundaries_geom_buffered = boundaries_geom.buffer(BUFFER_DISTANCE_M, 5)

        # Получаем extent для определения диапазона тайлов
        extent = boundaries_geom_buffered.boundingBox()

        # Определяем диапазон тайлов
        tx1, ty1 = self.mercator_to_tile(extent.xMinimum(), extent.yMinimum())
        tx2, ty2 = self.mercator_to_tile(extent.xMaximum(), extent.yMaximum())

        xmin_t, xmax_t = min(tx1, tx2), max(tx1, tx2)
        ymin_t, ymax_t = min(ty1, ty2), max(ty1, ty2)

        total_tiles_bbox = (xmax_t - xmin_t + 1) * (ymax_t - ymin_t + 1)

        # Собираем список необходимых слоёв
        required_layers = set(self.LAYER_MAPPING.keys())
        for layer_key in self.LAYER_MAPPING.keys():
            required_layers |= self.LAYER_EXTRAS.get(layer_key, set())

        # Фильтруем тайлы по пересечению с буферизованной геометрией границ
        # (экономия трафика для непрямоугольных границ)
        tile_coords = []
        for x in range(xmin_t, xmax_t + 1):
            for y in range(ymin_t, ymax_t + 1):
                tile_geom = self.tile_to_geometry(x, y)
                if boundaries_geom_buffered.intersects(tile_geom):
                    tile_coords.append((x, y))

        total_tiles = len(tile_coords)

        # ФАЗА 1: Загрузка тайлов параллельно через ThreadPoolExecutor (thread-safe requests)

        RETRY_WAVES = 2        # Количество волн повторных загрузок failed тайлов
        RETRY_WAVE_DELAY = 5   # Пауза между волнами (сек) — даёт CDN ротировать бэкенд

        downloaded_tiles = []  # List[(x, y, pbf_path)]
        failed_tile_coords = []  # List[(x, y)] — координаты failed тайлов для повторной загрузки

        def _download_batch(coords: List[Tuple[int, int]]) -> Tuple[List[Tuple[int, int, str]], List[Tuple[int, int]]]:
            """Параллельная загрузка пакета тайлов. Возвращает (ok, failed)."""
            ok = []
            failed = []
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self.download_tile_file, x, y, temp_dir): (x, y)
                    for x, y in coords
                }
                for future in futures:
                    x, y = futures[future]
                    try:
                        pbf_path = future.result(timeout=TILE_DOWNLOAD_TIMEOUT)
                        if pbf_path:
                            ok.append((x, y, pbf_path))
                        else:
                            failed.append((x, y))
                    except TimeoutError:
                        failed.append((x, y))
                    except Exception:
                        failed.append((x, y))
            return ok, failed

        # Основная загрузка
        ok_tiles, failed_tile_coords = _download_batch(tile_coords)
        downloaded_tiles.extend(ok_tiles)

        if failed_tile_coords:
            log_warning(
                f"Fsm_1_2_4: Загружено {len(downloaded_tiles)}/{total_tiles} тайлов "
                f"(ошибки: {len(failed_tile_coords)})"
            )

        # Волны повторных загрузок failed тайлов
        for wave in range(RETRY_WAVES):
            if not failed_tile_coords:
                break

            log_info(
                f"Fsm_1_2_4: Волна {wave + 1}/{RETRY_WAVES}: "
                f"повтор {len(failed_tile_coords)} тайлов (пауза {RETRY_WAVE_DELAY} сек)..."
            )
            time.sleep(RETRY_WAVE_DELAY)

            recovered, still_failed = _download_batch(failed_tile_coords)
            downloaded_tiles.extend(recovered)

            if recovered:
                log_success(
                    f"Fsm_1_2_4: Волна {wave + 1}: восстановлено {len(recovered)} тайлов"
                )
            failed_tile_coords = still_failed

        # Логирование оставшихся потерянных тайлов с координатами
        if failed_tile_coords:
            res = self.CUSTOM_RESOLUTIONS[self.TILE_ZOOM_SERVER]
            for tx, ty in failed_tile_coords:
                # Центр тайла в EPSG:3857 -> WGS-84 (приблизительная конвертация)
                cx_merc = (tx + 0.5) * res * self.TILE_SIZE_PIXELS - 20037508.34
                cy_merc = (ty + 0.5) * res * self.TILE_SIZE_PIXELS - 20037508.34
                lon = cx_merc / 20037508.34 * 180.0
                lat = math.degrees(2 * math.atan(math.exp(cy_merc / 20037508.34 * math.pi)) - math.pi / 2)
                log_warning(
                    f"Fsm_1_2_4: Тайл ({tx},{ty}) потерян "
                    f"(центр: lat={lat:.4f}, lon={lon:.4f})"
                )
            log_warning(
                f"Fsm_1_2_4: Итого потеряно {len(failed_tile_coords)} "
                f"из {total_tiles} тайлов после {RETRY_WAVES} волн повторов"
            )

        # Итоговая сводка
        if not failed_tile_coords:
            log_success(f"Fsm_1_2_4: Все {total_tiles} тайлов загружены")

        # Диагностика первого тайла - проверяем наличие новых неизвестных слоёв
        if downloaded_tiles:
            first_pbf = downloaded_tiles[0][2]
            self.diagnose_pbf_layers(first_pbf)

        # ФАЗА 2: Парсинг PBF файлов в main thread (QgsVectorLayer не thread-safe!)

        layer_features = defaultdict(list)

        for x, y, pbf_path in downloaded_tiles:
            tile_data = self.parse_tile(pbf_path, x, y, required_layers)
            for k, v in tile_data.items():
                layer_features[k].extend(v)

        # Создаём финальные слои
        result_layers = {}

        for base_layer_key, target_layer_name in self.LAYER_MAPPING.items():
            extras = self.LAYER_EXTRAS.get(base_layer_key, set())

            # Группируем данные по externalid
            # Структура: {externalid: {"geom": [QgsGeometry], "attrs": dict, "fields": dict}}
            base_data: dict = defaultdict(lambda: {"geom": [], "attrs": {}, "fields": {}})

            # Обрабатываем базовый слой
            base_features = layer_features.get(base_layer_key, [])

            for feat in base_features:
                eid = feat.attribute("externalid")
                if eid is None:
                    continue

                # Извлекаем данные для текущего externalid
                eid_data = base_data[eid]
                eid_data["geom"].append(feat.geometry())  # type: ignore[attr-defined]
                for fld in feat.fields():
                    eid_data["fields"][fld.name()] = fld
                    eid_data["attrs"][fld.name()] = feat.attribute(fld.name())

            # Обогащаем дополнительными слоями
            if extras:
                for extra_layer in extras:
                    extra_features = layer_features.get(extra_layer, [])
                    for feat in extra_features:
                        eid = feat.attribute("externalid")
                        if eid not in base_data:
                            continue

                        for fld in feat.fields():
                            n = fld.name()
                            if n == "externalid":
                                continue
                            base_data[eid]["fields"][n] = fld
                            base_data[eid]["attrs"][n] = feat.attribute(n)

            # Обогащение атрибутов выделов через REST API
            # Применяется ТОЛЬКО к TAXATION_PIECE (выделы)
            enrichment_data: Dict[str, dict] = {}
            if enrich_attributes and base_layer_key == "TAXATION_PIECE" and base_data:
                mvt_id_map: Dict[str, int] = {}
                for eid, eid_data in base_data.items():
                    mvt_id = eid_data["attrs"].get("mvt_id")
                    if mvt_id is not None:
                        try:
                            mvt_id_map[eid] = int(mvt_id)
                        except (ValueError, TypeError):
                            pass

                if mvt_id_map:
                    enrichment_data = self._enrich_attributes(mvt_id_map)
                else:
                    log_warning("Fsm_1_2_4: Нет mvt_id в выделах -- обогащение невозможно")

            if not base_data:
                log_info(f"Fsm_1_2_4: Нет данных для слоя {target_layer_name}")
                continue

            # Создаём поля — union из ВСЕХ записей
            # PBF тайлы имеют переменные схемы: если все значения поля NULL в тайле,
            # GeoWebCache не включает это поле в PBF. Разные записи base_data могут
            # иметь разные наборы полей. Union гарантирует, что ни одно поле не потеряется.
            all_fields: Dict[str, QgsField] = {}
            for eid_data in base_data.values():
                for fname, fld in eid_data["fields"].items():
                    if fname not in all_fields:
                        all_fields[fname] = fld

            fields = QgsFields()
            for field in all_fields.values():
                fields.append(field)

            # Добавляем поля обогащения если данные получены
            if enrichment_data:
                for api_field, (layer_field, field_type) in self.ENRICHMENT_FIELDS.items():
                    if layer_field not in all_fields:
                        fields.append(QgsField(layer_field, field_type))

            # Определяем тип геометрии
            any_geom = next(iter(base_data.values()))["geom"][0]
            gtype = QgsWkbTypes.geometryType(any_geom.wkbType())

            if gtype == Qgis.GeometryType.Polygon:
                geom_type = "MultiPolygon"
                geom_type_ru = "полигон"
            elif gtype == Qgis.GeometryType.Line:
                geom_type = "MultiLineString"
                geom_type_ru = "линия"
            elif gtype == Qgis.GeometryType.Point:
                geom_type = "MultiPoint"
                geom_type_ru = "точка"
            else:
                log_error(f"Fsm_1_2_4: Неизвестный тип геометрии в слое {base_layer_key}")
                continue

            # Определяем название слоя:
            # - Полигоны из POLYGON_LAYERS_IN_DB -> используем target_layer_name из LAYER_MAPPING
            # - Всё остальное (линии, точки, новые полигоны) -> временное название
            is_known_polygon = (
                gtype == Qgis.GeometryType.Polygon and
                base_layer_key in self.POLYGON_LAYERS_IN_DB
            )

            if is_known_polygon:
                final_layer_name = target_layer_name
            else:
                # Временное название: _TEMP_FGISLK_QUARTER_линия или _TEMP_FGISLK_CLEARCUT_полигон
                final_layer_name = f"{self.TEMP_LAYER_PREFIX}{base_layer_key}_{geom_type_ru}"
                log_info(f"Fsm_1_2_4: Слой '{base_layer_key}' ({geom_type_ru}) -> временное название '{final_layer_name}'")

            # Создаём memory layer
            layer = QgsVectorLayer(f"{geom_type}?crs=EPSG:3857", final_layer_name, "memory")
            provider = layer.dataProvider()
            provider.addAttributes(fields)
            layer.updateFields()

            # Добавляем объекты
            features_to_add = []

            for eid, data in base_data.items():
                # Валидация и полировка геометрий перед объединением
                raw_parts = []
                for g in data["geom"]:
                    # Привязка к сетке 0.01м (1 см) -- обеспечивает совпадение вершин
                    # на границах тайлов для корректного unaryUnion (ref: Fadeev v2.1)
                    g = g.snappedToGrid(0.01, 0.01, 0, 0)
                    # Исправляем невалидные геометрии
                    if not g.isGeosValid():
                        g = g.makeValid()
                    # Полировка геометрии (исправляет самопересечения)
                    g = g.buffer(0.0, 5)
                    if not g.isEmpty():
                        raw_parts.append(g)

                if not raw_parts:
                    continue

                # Объединяем валидные геометрии
                uni = QgsGeometry.unaryUnion(raw_parts)

                # Финальная валидация и полировка
                if not uni.isGeosValid():
                    uni = uni.makeValid()
                uni = uni.buffer(0.0, 5)

                if uni.isNull() or uni.isEmpty():
                    continue

                # Фильтрация GeometryCollection: извлекаем только полигоны
                # (PBF-тайлы могут содержать обрезки линий границ соседних кварталов)
                if gtype == Qgis.GeometryType.Polygon and QgsWkbTypes.geometryType(uni.wkbType()) == Qgis.GeometryType.Unknown:
                    parts_collection = uni.asGeometryCollection()
                    poly_parts = []
                    for p in parts_collection:
                        if QgsWkbTypes.geometryType(p.wkbType()) == Qgis.GeometryType.Polygon:
                            poly_parts.append(p)
                    if poly_parts:
                        uni = QgsGeometry.unaryUnion(poly_parts)
                    else:
                        continue

                # Конвертируем в Multi-тип если нужно
                if not uni.isMultipart():
                    uni.convertToMultiType()

                f = QgsFeature()
                f.setFields(fields)
                f.setGeometry(uni)
                # Объединяем атрибуты PBF + enrichment (enrichment имеет приоритет)
                eid_enrichment = enrichment_data.get(eid, {})
                vals = []
                for fld in fields:  # type: ignore[attr-defined]
                    fname = fld.name()
                    if fname in eid_enrichment:
                        vals.append(eid_enrichment[fname])
                    else:
                        vals.append(data["attrs"].get(fname))
                f.setAttributes(vals)
                features_to_add.append(f)

            provider.addFeatures(features_to_add)
            layer.updateExtents()

            log_success(f"Fsm_1_2_4: Слой '{final_layer_name}' создан: {len(features_to_add)} объектов")
            result_layers[final_layer_name] = layer

        total_time = time.time() - start_total
        log_success(f"Fsm_1_2_4: Загрузка ФГИС ЛК завершена: {len(result_layers)} слоя(ёв) за {total_time:.2f} сек")

        # Очистка временных PBF файлов
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                pass  # Временная папка очищена
        except Exception as e:
            log_warning(f"Fsm_1_2_4: Не удалось очистить временную папку {temp_dir}: {str(e)}")

        return result_layers
