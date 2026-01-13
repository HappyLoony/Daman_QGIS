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

import os
import hashlib
import time
import shutil
from typing import Optional, Dict, List, Tuple
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import wraps

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

# Отключаем предупреждения о небезопасных SSL запросах
# ФГИС ЛК использует российские сертификаты Минцифры, которые не распознаются стандартным certifi
urllib3.disable_warnings(InsecureRequestWarning)

from qgis.core import (
    QgsVectorLayer, QgsProject, QgsFeature, QgsGeometry, QgsField, QgsFields,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY,
    QgsRectangle, QgsWkbTypes
)
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.utils import log_info, log_warning, log_error, log_success
from Daman_QGIS.constants import TILE_DOWNLOAD_TIMEOUT, DEFAULT_MAX_RETRIES


def retry(max_attempts=DEFAULT_MAX_RETRIES, delay=2):
    """
    Декоратор для повторных попыток при сбоях

    Args:
        max_attempts: Максимальное количество попыток
        delay: Задержка между попытками в секундах

    Returns:
        Декорированная функция с механизмом retry
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        # Последняя попытка - пробрасываем исключение
                        raise e
                    log_warning(f"Fsm_1_2_4: [RETRY] {func.__name__} попытка {attempt + 1}/{max_attempts} не удалась. Повтор через {delay} сек... Ошибка: {str(e)}")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator


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

    # Маппинг слоёв ФГИС ЛК на слои проекта
    # TODO: После анализа данных обновить названия слоёв-заглушек (Le_1_7_*)
    LAYER_MAPPING = {
        # Основные слои (уже в базе)
        "FORESTRY_TAXATION_DATE": "Le_1_7_1_2_ФГИС_ЛК_Лесничества",
        "DISTRICT_FORESTRY_TAXATION_DATE": "L_1_7_2_ФГИС_ЛК_Уч_Лесничества",
        "QUARTER": "L_1_7_3_ФГИС_ЛК_Кварталы",
        "TAXATION_PIECE": "L_1_7_4_ФГИС_ЛК_Выделы",
        "FOREST_STEAD": "L_1_7_5_ФГИС_ЛК_Участки",
        # Новые слои (заглушки - требуют анализа и добавления в Base_layers.json)
        "FOREST_PURPOSE": "Le_1_7_6_ФГИС_ЛК_Целевое_назначение",          # Виды лесов согласно целевому назначению
        "PROTECTIVE_FOREST": "Le_1_7_7_ФГИС_ЛК_Защитные_леса",            # Категории защитных лесов
        "PROTECTIVE_FOREST_SUBCATEGORY": "Le_1_7_8_ФГИС_ЛК_Ценные_леса",  # Запись о ценных лесах
        "SPECIAL_PROTECT_STEAD": "Le_1_7_9_ФГИС_ЛК_ОЗУ",                  # Особо защитные участки лесов
        "CLEARCUT": "Le_1_7_10_ФГИС_ЛК_Лесосеки",                         # Лесосека
        "PROCESSING_OBJECT": "Le_1_7_11_ФГИС_ЛК_Лесопереработка",         # Пункт лесопереработки
        "TIMBER_YARD": "Le_1_7_12_ФГИС_ЛК_Склады_древесины",              # Складирование древесины
    }

    # Слои, для которых уже существуют полигональные определения в Base_layers.json
    # Остальные слои (линии, точки или новые полигоны) получат временные названия
    POLYGON_LAYERS_IN_DB = {
        "FORESTRY_TAXATION_DATE",
        "DISTRICT_FORESTRY_TAXATION_DATE",
        "QUARTER",
        "TAXATION_PIECE",
        "FOREST_STEAD",
    }

    # Префикс для временных слоёв (не полигоны или слои без определения в БД)
    TEMP_LAYER_PREFIX = "_TEMP_FGISLK_"

    # Дополнительные слои для обогащения данных (атрибуты из связанных слоёв PBF)
    LAYER_EXTRAS = {
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
        # Новые слои - extras пока пустые (требуют анализа)
        "FOREST_PURPOSE": set(),
        "PROTECTIVE_FOREST": set(),
        "PROTECTIVE_FOREST_SUBCATEGORY": set(),
        "SPECIAL_PROTECT_STEAD": set(),
        "CLEARCUT": set(),
        "PROCESSING_OBJECT": set(),
        "TIMBER_YARD": set(),
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

        if gtype == QgsWkbTypes.PolygonGeometry:
            # МИГРАЦИЯ POLYGON → MULTIPOLYGON: упрощённый паттерн
            parts = [[[to_global(pt) for pt in ring] for ring in part]
                    for part in (geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()])]
            return QgsGeometry.fromMultiPolygonXY(parts)

        elif gtype == QgsWkbTypes.LineGeometry:
            # МИГРАЦИЯ LINESTRING → MULTILINESTRING: упрощённый паттерн
            lines = [[to_global(pt) for pt in line]
                     for line in (geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()])]
            return QgsGeometry.fromMultiPolylineXY(lines)

        elif gtype == QgsWkbTypes.PointGeometry:
            if geom.isMultipart():
                points = [to_global(pt) for pt in geom.asMultiPoint()]
                return QgsGeometry.fromMultiPointXY(points)
            else:
                return QgsGeometry.fromPointXY(to_global(geom.asPoint()))

        return QgsGeometry()

    @retry(max_attempts=3, delay=2)
    def download_tile_file(self, x: int, y: int, temp_dir: str) -> Optional[str]:
        """
        Загрузка тайла с сервера (только HTTP, thread-safe)

        Декорирован @retry для автоматических повторных попыток при сбоях сервера.

        ВАЖНО: Использует requests (thread-safe) для работы в ThreadPoolExecutor.
               НЕ использует Qt объекты - они не thread-safe!

        Args:
            x, y: Индексы тайла
            temp_dir: Директория для временных файлов

        Returns:
            str: Путь к загруженному PBF файлу или None при ошибке
        """
        try:
            url = self.tile_url_template.format(z=self.TILE_ZOOM_SERVER, x=x, y=y)

            # Подготовка путей и ключа кэша
            hash_name = hashlib.md5(f"{x}_{y}".encode()).hexdigest()
            pbf_path = os.path.join(temp_dir, f"tile_{hash_name}.pbf")
            cache_key = f"{self.TILE_ZOOM_SERVER}_{x}_{y}"

            # Проверяем двухуровневый кэш (RAM + диск)
            cached_data = self.tile_cache.get(cache_key)

            if cached_data:
                # Тайл найден в кэше (RAM или диск)
                # Сохраняем на диск если его там нет
                if not os.path.exists(pbf_path):
                    with open(pbf_path, "wb") as f:
                        f.write(cached_data)
                return pbf_path

            # Загружаем новый тайл с сервера через requests (thread-safe!)
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': '*/*'
            }

            # ФГИС ЛК использует российские сертификаты Минцифры
            # verify=False - отключаем проверку SSL (безопасно для публичных тайлов)
            response = requests.get(url, headers=headers, timeout=self.timeout, verify=False)

            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}")

            if not response.content:
                raise Exception("Пустой ответ")

            pbf_data = response.content

            # Сохраняем тайл на диск
            with open(pbf_path, "wb") as f:
                f.write(pbf_data)

            # Добавляем в двухуровневый кэш
            self.tile_cache.put(cache_key, pbf_data, pbf_path)

            return pbf_path

        except requests.exceptions.SSLError as e:
            # SSL ошибки - логируем отдельно (российские сертификаты)
            log_warning(f"Fsm_1_2_4: SSL ошибка загрузки тайла {x}/{y}: {str(e)}")
            return None

        except requests.exceptions.Timeout as e:
            log_warning(f"Fsm_1_2_4: Timeout загрузки тайла {x}/{y}: {str(e)}")
            return None

        except requests.exceptions.ConnectionError as e:
            log_warning(f"Fsm_1_2_4: Ошибка соединения при загрузке тайла {x}/{y}: {str(e)}")
            return None

        except Exception as e:
            log_warning(f"Fsm_1_2_4: Ошибка загрузки тайла {x}/{y}: {str(e)}")
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

            # Парсим тайл
            tile_data = defaultdict(list)
            for lname in required_layers:
                uri = f"{pbf_path}|layername={lname}"
                lyr = QgsVectorLayer(uri, lname, "ogr")

                if not lyr.isValid():
                    continue

                for feat in lyr.getFeatures():
                    eid = feat.attribute("externalid")
                    if eid is None:
                        continue

                    # Трансформируем геометрию
                    g = self.transform_coords(feat.geometry(), xmin, ymin, xmax, ymax)

                    new_feat = QgsFeature()
                    new_feat.setFields(lyr.fields())
                    new_feat.setGeometry(g)
                    new_feat.setAttributes(feat.attributes())
                    tile_data[lname].append(new_feat)

            return tile_data

        except Exception as e:
            log_warning(f"Fsm_1_2_4: Ошибка парсинга тайла {x}/{y}: {str(e)}")
            return {}

    def diagnose_pbf_layers(self, pbf_path: str) -> set:
        """
        Диагностика: получить список ВСЕХ слоёв в PBF файле

        Сравнивает с известными слоями и выводит предупреждение
        если обнаружены новые неизвестные слои.

        Args:
            pbf_path: Путь к PBF файлу

        Returns:
            set: Множество всех найденных слоёв в PBF
        """
        from osgeo import ogr

        found_layers = set()
        try:
            ds = ogr.Open(pbf_path)
            if ds:
                for i in range(ds.GetLayerCount()):
                    layer = ds.GetLayerByIndex(i)
                    if layer:
                        found_layers.add(layer.GetName())
                ds = None  # Закрываем датасет
        except Exception as e:
            log_warning(f"Fsm_1_2_4: Ошибка диагностики PBF: {str(e)}")
            return found_layers

        # Собираем все известные слои (основные + extras)
        known_layers = set(self.LAYER_MAPPING.keys())
        for extras in self.LAYER_EXTRAS.values():
            known_layers |= extras

        # Находим новые неизвестные слои
        unknown_layers = found_layers - known_layers

        if unknown_layers:
            log_warning("Fsm_1_2_4: ОБНАРУЖЕНЫ НОВЫЕ СЛОИ В PBF!")
            log_warning(f"Fsm_1_2_4: Неизвестные слои: {sorted(unknown_layers)}")
            log_warning("Fsm_1_2_4: Проверьте - возможно нужно добавить в LAYER_MAPPING или LAYER_EXTRAS")

        return found_layers

    def load_layers(self, temp_dir: str) -> Dict[str, QgsVectorLayer]:
        """
        Загрузка всех слоёв ФГИС ЛК

        Args:
            temp_dir: Директория для временных файлов

        Returns:
            dict: Словарь {layer_name: QgsVectorLayer}
        """
        import time

        start_total = time.time()

        # Получаем геометрию границ
        boundaries_geom = self.get_boundary_geometry()
        if not boundaries_geom:
            log_error("Fsm_1_2_4: Не удалось получить геометрию границ")
            return {}

        # Трансформируем границы в EPSG:3857
        source_crs = QgsProject.instance().mapLayersByName('L_1_1_1_Границы_работ')[0].crs()
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

        # Загружаем файлы параллельно (только HTTP, thread-safe)
        downloaded_tiles = []  # List[(x, y, pbf_path)]

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self.download_tile_file, x, y, temp_dir): (x, y)
                for x, y in tile_coords
            }

            for future in futures:
                x, y = futures[future]
                try:
                    # КРИТИЧНО: timeout на загрузку одного тайла ФГИС ЛК
                    pbf_path = future.result(timeout=TILE_DOWNLOAD_TIMEOUT)
                    if pbf_path:
                        downloaded_tiles.append((x, y, pbf_path))
                except TimeoutError:
                    log_error(f"Fsm_1_2_4: TIMEOUT ({TILE_DOWNLOAD_TIMEOUT}s) загрузки тайла {x}/{y} - пропускаем")
                except Exception as e:
                    log_error(f"Fsm_1_2_4: Ошибка загрузки тайла {x}/{y}: {str(e)}")

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

            if not base_data:
                log_warning(f"Fsm_1_2_4: Нет данных для слоя {target_layer_name}")
                continue

            # Создаём поля
            fields = QgsFields()
            for field in next(iter(base_data.values()))["fields"].values():  # type: ignore[attr-defined]
                fields.append(field)

            # Определяем тип геометрии
            any_geom = next(iter(base_data.values()))["geom"][0]
            gtype = QgsWkbTypes.geometryType(any_geom.wkbType())

            if gtype == QgsWkbTypes.PolygonGeometry:
                geom_type = "MultiPolygon"
                geom_type_ru = "полигон"
            elif gtype == QgsWkbTypes.LineGeometry:
                geom_type = "MultiLineString"
                geom_type_ru = "линия"
            elif gtype == QgsWkbTypes.PointGeometry:
                geom_type = "MultiPoint"
                geom_type_ru = "точка"
            else:
                log_error(f"Fsm_1_2_4: Неизвестный тип геометрии в слое {base_layer_key}")
                continue

            # Определяем название слоя:
            # - Полигоны из POLYGON_LAYERS_IN_DB -> используем target_layer_name из LAYER_MAPPING
            # - Всё остальное (линии, точки, новые полигоны) -> временное название
            is_known_polygon = (
                gtype == QgsWkbTypes.PolygonGeometry and
                base_layer_key in self.POLYGON_LAYERS_IN_DB
            )

            if is_known_polygon:
                final_layer_name = target_layer_name
            else:
                # Временное название: _TEMP_FGISLK_QUARTER_линия или _TEMP_FGISLK_CLEARCUT_полигон
                final_layer_name = f"{self.TEMP_LAYER_PREFIX}{base_layer_key}_{geom_type_ru}"
                log_warning(f"Fsm_1_2_4: Слой '{base_layer_key}' ({geom_type_ru}) -> временное название '{final_layer_name}'")

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
                if gtype == QgsWkbTypes.PolygonGeometry and QgsWkbTypes.geometryType(uni.wkbType()) == QgsWkbTypes.UnknownGeometry:
                    parts_collection = uni.asGeometryCollection()
                    poly_parts = []
                    for p in parts_collection:
                        if QgsWkbTypes.geometryType(p.wkbType()) == QgsWkbTypes.PolygonGeometry:
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
                vals = [data["attrs"].get(fld.name()) for fld in fields]  # type: ignore[attr-defined]
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
