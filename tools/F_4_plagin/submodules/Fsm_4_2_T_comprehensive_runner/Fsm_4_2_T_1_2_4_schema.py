# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_1_2_4_schema - Верификация структуры данных ФГИС ЛК

Standalone скрипт, который:
1. Скачивает реальный PBF тайл с pub4.fgislk.gov.ru
2. Извлекает полные схемы ВСЕХ слоёв через osgeo.ogr
3. Запрашивает REST API attributesinfo с реальным mvt_id
4. Сравнивает результаты с кодом Fsm_1_2_4 (LAYER_MAPPING, ENRICHMENT_FIELDS)
5. Сравнивает с документированной структурой (250 полей SHP загрузки)

Запуск: Работает как в QGIS (через тест-раннер), так и standalone.
Зависимости: requests, osgeo (GDAL/OGR) -- оба доступны в QGIS Python.

РЕЗУЛЬТАТ: Отчёт о всех найденных расхождениях между кодом и реальными данными.
"""

import json
import os
import sys
import tempfile
import time
from collections import OrderedDict
from typing import Dict, List, Optional, Set, Tuple, Any

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

urllib3.disable_warnings(InsecureRequestWarning)

# --------------------------------------------------------------------------
# Константы из Fsm_1_2_4_fgislk_loader.py (дублируем для standalone)
# --------------------------------------------------------------------------

LAYER_MAPPING = {
    "FORESTRY": "Le_1_7_2_0",
    "FORESTRY_APPROVE": "Le_1_7_2_0a",
    "FORESTRY_TAXATION_DATE": "Le_1_7_2_1",
    "DISTRICT_FORESTRY_TAXATION_DATE": "Le_1_7_2_2",
    "QUARTER": "Le_1_7_2_3",
    "TAXATION_PIECE": "Le_1_7_2_4",
    "FOREST_STEAD": "Le_1_7_2_6",
    "PART_FOREST_STEAD": "Le_1_7_2_7",
    # SUBJECT_BOUNDARY -- исключён: дубликат АТД из ЕГРН, нет externalid
    "TIMBER_YARD": "Le_1_7_12",
    "FOREST_PURPOSE": "Le_1_7_6",
    "PROTECTIVE_FOREST": "Le_1_7_7",
    "PROTECTIVE_FOREST_SUBCATEGORY": "Le_1_7_8",
    "SPECIAL_PROTECT_STEAD": "Le_1_7_9",
    "CLEARCUT": "Le_1_7_10",
    "PROCESSING_OBJECT": "Le_1_7_11",
}

LAYER_EXTRAS = {
    "FORESTRY": set(),
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
    "TIMBER_YARD": set(),
    "FOREST_PURPOSE": set(),
    "PROTECTIVE_FOREST": set(),
    "PROTECTIVE_FOREST_SUBCATEGORY": set(),
    "SPECIAL_PROTECT_STEAD": set(),
    "CLEARCUT": set(),
    "PROCESSING_OBJECT": set(),
}

ENRICHMENT_FIELDS_CODE = {
    "square": "square",
    "totalArea": "total_area",
    "objectValid": "object_valid",
    "category_land": "category_land",
    "type_land": "type_land",
    "forest_land_type": "forest_land_type",
    "taxation_date": "taxation_date",
    "tree_species": "tree_species",
    "age_group": "age_group",
    "yield_class": "yield_class",
    "timber_stock": "timber_stock",
    "number": "number",
    "number_lud": "number_lud",
    "forest_quarter_number": "forest_quarter_number",
    "forest_quarter_number_lud": "forest_quarter_number_lud",
    "event": "event",
}

# Документированная структура КВАРТАЛОВ (8 полей MID/MIF, из методички v1.0.1)
DOC_QUARTER_FIELDS = ["SUB", "NAME_SUB", "LES", "NAME_LES", "UCHLES", "NAME_UCHLES", "KV", "DOP"]

# Документированная структура ВЫДЕЛОВ -- ключевые поля SHP загрузки (из методички v3.0.1)
# Полный список 250+ полей в Приложении 1 Excel-файла; здесь -- основные
DOC_VYDELY_KEY_FIELDS = [
    "MUK", "SRI", "MU", "GIR", "MK", "UD", "KV", "PL", "ZK", "ZKG",
    "BON", "MTIP", "DTG", "AGR", "MR", "VMR", "PR", "VPR",
    "KZAS", "KZP", "PLKV",
    # Ярус 1
    "ARD1", "HRD1", "D1RD1", "DP1RD1", "HRD1_1", "D1RD1_1",
    # + ещё ~230 полей (ярусы 2-10, подлесок, подрост и т.д.)
]

# 17 полей Base_forest_vydely.json (Le_3_1_1_1)
BASE_VYDELY_JSON_FIELDS = [
    "Лесничество", "Уч_лесничество", "Номер_квартала", "Номер_выдела",
    "Площадь_выдела_га", "Состав", "Возраст", "Группа_возраста",
    "Бонитет", "Полнота", "Запас_на_1_га", "Категория_по_таксации",
    "Целевое_назначение", "ОЗУ", "Хозяйство", "Преобладающая_порода",
    "Распределение_земель"
]

# Параметры тайловой сетки
TILE_SIZE_PIXELS = 256
TILE_ZOOM_SERVER = 12
CUSTOM_RESOLUTIONS = [
    13999.999999999998, 11199.999999999998, 5599.999999999999,
    2799.9999999999995, 1399.9999999999998, 699.9999999999999,
    280, 140, 55.99999999999999, 27.999999999999996,
    13.999999999998, 6.999999999999999, 2.8
]

# Тестовая точка: лесная зона Подмосковья (из Base_api_endpoints.json endpoint 22)
TEST_LON = 37.8877122
TEST_LAT = 55.7276567

PBF_BASE_URL = "https://pub4.fgislk.gov.ru/plk/gwc/geowebcache/service/tms/1.0.0/FOREST_LAYERS:FOREST@EPSG:3857@pbf"
REST_API_URL = "https://map.fgislk.gov.ru/map/geo/map_api/layer/attributesinfo"
REFERER = "https://map.fgislk.gov.ru/map/"


# --------------------------------------------------------------------------
# Утилиты
# --------------------------------------------------------------------------

def lonlat_to_tile(lon: float, lat: float, zoom_index: int) -> Tuple[int, int]:
    """Пересчёт WGS84 координат в индексы тайла ФГИС ЛК."""
    import math

    # WGS84 -> EPSG:3857 (Web Mercator)
    x_m = lon * 20037508.34 / 180.0
    y_m = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
    y_m = y_m * 20037508.34 / 180.0

    res = CUSTOM_RESOLUTIONS[zoom_index]
    tile_x = int((x_m + 20037508.34) / (res * TILE_SIZE_PIXELS))
    tile_y = int((y_m + 20037508.34) / (res * TILE_SIZE_PIXELS))

    return tile_x, tile_y


def ogr_field_type_name(ogr_type: int) -> str:
    """Название типа OGR поля."""
    from osgeo import ogr
    type_names = {
        ogr.OFTInteger: "Integer",
        ogr.OFTInteger64: "Integer64",
        ogr.OFTReal: "Real",
        ogr.OFTString: "String",
        ogr.OFTBinary: "Binary",
        ogr.OFTDate: "Date",
        ogr.OFTTime: "Time",
        ogr.OFTDateTime: "DateTime",
        ogr.OFTIntegerList: "IntegerList",
        ogr.OFTInteger64List: "Integer64List",
        ogr.OFTRealList: "RealList",
        ogr.OFTStringList: "StringList",
    }
    return type_names.get(ogr_type, f"Unknown({ogr_type})")


def ogr_geom_type_name(ogr_geom_type: int) -> str:
    """Название типа геометрии OGR."""
    from osgeo import ogr
    type_names = {
        ogr.wkbPoint: "Point",
        ogr.wkbLineString: "LineString",
        ogr.wkbPolygon: "Polygon",
        ogr.wkbMultiPoint: "MultiPoint",
        ogr.wkbMultiLineString: "MultiLineString",
        ogr.wkbMultiPolygon: "MultiPolygon",
        ogr.wkbGeometryCollection: "GeometryCollection",
        ogr.wkbUnknown: "Unknown",
        ogr.wkbNone: "None",
    }
    return type_names.get(ogr_geom_type, f"GeomType({ogr_geom_type})")


# --------------------------------------------------------------------------
# Фаза 1: Скачивание и парсинг PBF тайла
# --------------------------------------------------------------------------

def download_pbf_tile(tile_x: int, tile_y: int, output_path: str) -> bool:
    """Скачать PBF тайл с ФГИС ЛК.

    Returns:
        True если скачан успешно
    """
    url = f"{PBF_BASE_URL}/{TILE_ZOOM_SERVER}/{tile_x}/{tile_y}.pbf"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': '*/*',
        'Referer': REFERER,
    }

    try:
        resp = requests.get(url, headers=headers, verify=False, timeout=30)
        if resp.status_code == 200 and len(resp.content) > 0:
            with open(output_path, 'wb') as f:
                f.write(resp.content)
            return True
        else:
            print(f"  HTTP {resp.status_code}, body={len(resp.content)} bytes")
            return False
    except Exception as e:
        print(f"  Ошибка загрузки: {e}")
        return False


def extract_pbf_schema(pbf_path: str) -> Dict[str, dict]:
    """Извлечь полную схему всех слоёв из PBF файла.

    Использует osgeo.ogr (QGIS Python) или mapbox_vector_tile (standalone fallback).

    Returns:
        {layer_name: {
            "geom_type": str,
            "feature_count": int,
            "fields": OrderedDict[(field_name, field_type_str)],
            "sample_values": {field_name: first_non_null_value},
        }}
    """
    try:
        return _extract_pbf_schema_ogr(pbf_path)
    except ImportError:
        print("  OGR недоступен, используем mapbox_vector_tile (fallback)")
        return _extract_pbf_schema_mvt(pbf_path)


def _extract_pbf_schema_ogr(pbf_path: str) -> Dict[str, dict]:
    """Парсинг PBF через osgeo.ogr (QGIS Python)."""
    from osgeo import ogr

    result = {}

    ds = ogr.Open(pbf_path)
    if not ds:
        print(f"  OGR: Не удалось открыть {pbf_path}")
        return result

    for i in range(ds.GetLayerCount()):
        layer = ds.GetLayerByIndex(i)
        if not layer:
            continue

        lname = layer.GetName()
        geom_type = ogr_geom_type_name(layer.GetGeomType())
        feature_count = layer.GetFeatureCount()

        # Собираем поля
        layer_defn = layer.GetLayerDefn()
        fields = OrderedDict()
        for fi in range(layer_defn.GetFieldCount()):
            fd = layer_defn.GetFieldDefn(fi)
            fname = fd.GetName()
            ftype = ogr_field_type_name(fd.GetType())
            fields[fname] = ftype

        # Собираем примеры значений (первая non-null запись каждого поля)
        sample_values = {}
        layer.ResetReading()
        samples_needed = set(fields.keys())
        for feat in layer:
            if not samples_needed:
                break
            done = set()
            for fname in samples_needed:
                val = feat.GetField(fname)
                if val is not None:
                    sample_values[fname] = val
                    done.add(fname)
            samples_needed -= done

        result[lname] = {
            "geom_type": geom_type,
            "feature_count": feature_count,
            "fields": fields,
            "sample_values": sample_values,
        }

    ds = None
    return result


def _extract_pbf_schema_mvt(pbf_path: str) -> Dict[str, dict]:
    """Парсинг PBF через mapbox_vector_tile (standalone, без QGIS)."""
    import mapbox_vector_tile as mvt

    result = {}

    with open(pbf_path, 'rb') as f:
        raw_data = f.read()

    decoded = mvt.decode(raw_data)

    for layer_name, layer_data in decoded.items():
        features = layer_data.get('features', [])

        # Собираем типы полей и примеры из всех фичей
        all_fields = OrderedDict()
        sample_values = {}

        for feat in features:
            props = feat.get('properties', {})
            for k, v in props.items():
                if k not in all_fields:
                    all_fields[k] = type(v).__name__ if v is not None else 'NoneType'
                    if v is not None:
                        sample_values[k] = v
                elif all_fields[k] == 'NoneType' and v is not None:
                    all_fields[k] = type(v).__name__
                    sample_values[k] = v

        # Типы геометрий
        geom_types = set()
        for feat in features:
            gt = feat.get('geometry', {}).get('type', 'Unknown')
            geom_types.add(gt)
        geom_type = '/'.join(sorted(geom_types)) if geom_types else 'Unknown'

        result[layer_name] = {
            "geom_type": geom_type,
            "feature_count": len(features),
            "fields": all_fields,
            "sample_values": sample_values,
        }

    return result


# --------------------------------------------------------------------------
# Фаза 2: REST API attributesinfo
# --------------------------------------------------------------------------

def query_rest_api(mvt_id: int, layer_code: str = "TAXATION_PIECE") -> Optional[dict]:
    """Запрос полного JSON ответа REST API attributesinfo.

    Returns:
        Полный payload или None
    """
    params = {
        "layer_code": layer_code,
        "object_id": str(mvt_id),
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json',
        'Referer': REFERER,
    }

    try:
        resp = requests.get(REST_API_URL, params=params, headers=headers,
                            verify=False, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("payload")
        else:
            print(f"  REST API HTTP {resp.status_code}")
            return None
    except Exception as e:
        print(f"  REST API ошибка: {e}")
        return None


def query_rest_api_all_layers(mvt_id: int) -> Dict[str, Optional[dict]]:
    """Запрос REST API для ВСЕХ layer_code из LAYER_MAPPING.

    Проверяем, есть ли REST API данные для кварталов, лесничеств и т.д.
    """
    results = {}
    for layer_code in LAYER_MAPPING.keys():
        results[layer_code] = query_rest_api(mvt_id, layer_code)
        time.sleep(0.3)  # Rate limiting
    return results


# --------------------------------------------------------------------------
# Анализ и сравнение
# --------------------------------------------------------------------------

def compare_with_code(schema: Dict[str, dict]) -> List[str]:
    """Сравнить найденные слои PBF с LAYER_MAPPING и LAYER_EXTRAS.

    Returns:
        Список замечаний
    """
    findings = []

    pbf_layers = set(schema.keys())

    # Все известные слои в коде
    known_main = set(LAYER_MAPPING.keys())
    known_extras = set()
    for extras in LAYER_EXTRAS.values():
        known_extras |= extras
    known_all = known_main | known_extras

    # Новые (неизвестные) слои
    unknown = pbf_layers - known_all
    if unknown:
        findings.append(f"НОВЫЕ СЛОИ В PBF (отсутствуют в коде): {sorted(unknown)}")

    # Отсутствующие ожидаемые слои
    missing_main = known_main - pbf_layers
    if missing_main:
        findings.append(f"Ожидаемые основные слои ОТСУТСТВУЮТ в PBF: {sorted(missing_main)}")

    missing_extras = known_extras - pbf_layers
    if missing_extras:
        findings.append(f"Ожидаемые extra-слои ОТСУТСТВУЮТ в PBF: {sorted(missing_extras)}")

    # Присутствующие основные слои
    present_main = known_main & pbf_layers
    if present_main:
        findings.append(f"Основные слои НАЙДЕНЫ: {sorted(present_main)}")

    present_extras = known_extras & pbf_layers
    if present_extras:
        findings.append(f"Extra-слои НАЙДЕНЫ: {sorted(present_extras)}")

    return findings


def compare_vydely_with_docs(pbf_fields: OrderedDict, rest_payload: Optional[dict]) -> List[str]:
    """Сравнить поля выделов из PBF и REST API с документацией.

    Returns:
        Список замечаний
    """
    findings = []

    # 1. PBF поля vs документированные SHP поля загрузки
    pbf_field_names = set(pbf_fields.keys())
    doc_field_names = set(DOC_VYDELY_KEY_FIELDS)

    common_with_doc = pbf_field_names & doc_field_names
    only_in_pbf = pbf_field_names - doc_field_names
    only_in_doc = doc_field_names - pbf_field_names

    findings.append(f"PBF TAXATION_PIECE: всего {len(pbf_field_names)} полей")
    if common_with_doc:
        findings.append(f"  Совпадают с документацией SHP: {sorted(common_with_doc)}")
    if only_in_pbf:
        findings.append(f"  Только в PBF (нет в документации загрузки): {sorted(only_in_pbf)}")
    if only_in_doc:
        findings.append(f"  Только в документации SHP (нет в PBF): {sorted(only_in_doc)}")

    # 2. REST API поля vs текущие ENRICHMENT_FIELDS
    if rest_payload and isinstance(rest_payload, dict):
        rest_fields = set(rest_payload.keys())
        enrichment_api_keys = set(ENRICHMENT_FIELDS_CODE.keys())

        captured = rest_fields & enrichment_api_keys
        uncaptured = rest_fields - enrichment_api_keys

        findings.append(f"REST API: всего {len(rest_fields)} полей в payload")
        findings.append(f"  Захвачены ENRICHMENT_FIELDS: {sorted(captured)}")
        if uncaptured:
            findings.append(f"  НЕ ЗАХВАЧЕНЫ (потенциальное расширение): {sorted(uncaptured)}")
            # Детали незахваченных полей
            for key in sorted(uncaptured):
                val = rest_payload[key]
                val_preview = str(val)[:80] if val is not None else "null"
                findings.append(f"    {key} = {val_preview}")
    else:
        findings.append("REST API: ответ не получен или пустой")

    # 3. Маппинг PBF/REST -> Base_forest_vydely.json (17 полей)
    findings.append(f"Base_forest_vydely.json: {len(BASE_VYDELY_JSON_FIELDS)} полей для Le_3_1_1_1")
    # Эти 17 полей -- ручной маппинг для редактируемого слоя, не обязательно 1:1 с PBF/API

    return findings


def compare_quarter_with_docs(pbf_fields: OrderedDict) -> List[str]:
    """Сравнить поля кварталов из PBF с документацией MID/MIF.

    Returns:
        Список замечаний
    """
    findings = []
    pbf_field_names = set(pbf_fields.keys())
    doc_field_names = set(DOC_QUARTER_FIELDS)

    common = pbf_field_names & doc_field_names
    only_pbf = pbf_field_names - doc_field_names
    only_doc = doc_field_names - pbf_field_names

    findings.append(f"PBF QUARTER: всего {len(pbf_field_names)} полей")
    if common:
        findings.append(f"  Совпадают с MID/MIF документацией: {sorted(common)}")
    if only_pbf:
        findings.append(f"  Только в PBF (нет в MID/MIF): {sorted(only_pbf)}")
    if only_doc:
        findings.append(f"  Только в MID/MIF документации (нет в PBF): {sorted(only_doc)}")

    return findings


# --------------------------------------------------------------------------
# Главная функция
# --------------------------------------------------------------------------

def run_schema_verification() -> Dict[str, Any]:
    """Запуск полной верификации схемы.

    Returns:
        Словарь с результатами верификации
    """
    results = {
        "status": "started",
        "pbf_schema": {},
        "rest_api_payload": None,
        "rest_api_all_layers": {},
        "findings": [],
        "errors": [],
    }

    print("=" * 80)
    print("ВЕРИФИКАЦИЯ СТРУКТУРЫ ДАННЫХ ФГИС ЛК")
    print("=" * 80)

    # ---- Шаг 1: Расчёт координат тайла ----
    tile_x, tile_y = lonlat_to_tile(TEST_LON, TEST_LAT, TILE_ZOOM_SERVER)
    print(f"\n1. Тайловые координаты для ({TEST_LON}, {TEST_LAT}):")
    print(f"   Zoom: {TILE_ZOOM_SERVER}, Tile: ({tile_x}, {tile_y})")
    print(f"   Resolution: {CUSTOM_RESOLUTIONS[TILE_ZOOM_SERVER]}")

    # ---- Шаг 2: Скачивание PBF тайла ----
    print(f"\n2. Скачивание PBF тайла...")
    temp_dir = tempfile.mkdtemp(prefix="fgislk_schema_")
    pbf_path = os.path.join(temp_dir, f"tile_{tile_x}_{tile_y}.pbf")

    if not download_pbf_tile(tile_x, tile_y, pbf_path):
        # Попробуем соседние тайлы
        print("   Основной тайл пустой, пробуем соседние...")
        found = False
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if dx == 0 and dy == 0:
                    continue
                alt_x, alt_y = tile_x + dx, tile_y + dy
                alt_path = os.path.join(temp_dir, f"tile_{alt_x}_{alt_y}.pbf")
                if download_pbf_tile(alt_x, alt_y, alt_path):
                    pbf_path = alt_path
                    tile_x, tile_y = alt_x, alt_y
                    print(f"   Найден тайл ({alt_x}, {alt_y})")
                    found = True
                    break
            if found:
                break

        if not found:
            results["errors"].append("Не удалось скачать ни один PBF тайл")
            results["status"] = "failed_download"
            print("   ОШИБКА: Не удалось скачать PBF тайл")
            return results

    file_size = os.path.getsize(pbf_path)
    print(f"   OK: {file_size} bytes -> {pbf_path}")

    # ---- Шаг 3: Извлечение схемы PBF ----
    print(f"\n3. Извлечение схемы PBF...")
    try:
        schema = extract_pbf_schema(pbf_path)
        results["pbf_schema"] = schema
        print(f"   Найдено слоёв: {len(schema)}")
    except Exception as e:
        results["errors"].append(f"OGR ошибка: {e}")
        results["status"] = "failed_ogr"
        print(f"   ОШИБКА OGR: {e}")
        return results

    # Вывод полных схем
    print(f"\n{'=' * 80}")
    print("ПОЛНЫЕ СХЕМЫ СЛОЁВ PBF")
    print(f"{'=' * 80}")

    for lname, ldata in sorted(schema.items()):
        print(f"\n--- {lname} ---")
        print(f"  Геометрия: {ldata['geom_type']}")
        print(f"  Фичей: {ldata['feature_count']}")
        print(f"  Полей: {len(ldata['fields'])}")
        for fname, ftype in ldata['fields'].items():
            sample = ldata['sample_values'].get(fname, '')
            sample_str = f"  (пример: {str(sample)[:60]})" if sample != '' else ""
            print(f"    {fname}: {ftype}{sample_str}")

    # ---- Шаг 4: Сравнение с кодом ----
    print(f"\n{'=' * 80}")
    print("СРАВНЕНИЕ С КОДОМ (LAYER_MAPPING / LAYER_EXTRAS)")
    print(f"{'=' * 80}")

    code_findings = compare_with_code(schema)
    for f in code_findings:
        print(f"  {f}")
    results["findings"].extend(code_findings)

    # ---- Шаг 5: Сравнение ВЫДЕЛОВ с документацией ----
    if "TAXATION_PIECE" in schema:
        print(f"\n{'=' * 80}")
        print("ВЕРИФИКАЦИЯ ВЫДЕЛОВ (TAXATION_PIECE)")
        print(f"{'=' * 80}")

        tp_data = schema["TAXATION_PIECE"]

        # Извлекаем mvt_id для REST API запроса
        mvt_id = tp_data["sample_values"].get("mvt_id")
        rest_payload = None

        if mvt_id is not None:
            print(f"\n  Запрос REST API с mvt_id={mvt_id}...")
            rest_payload = query_rest_api(int(mvt_id))
            results["rest_api_payload"] = rest_payload

            if rest_payload:
                print(f"  REST API: получено {len(rest_payload)} полей")
                print(f"\n  Полный ответ REST API:")
                for key, val in sorted(rest_payload.items()):
                    val_str = str(val)[:100] if val is not None else "null"
                    print(f"    {key} = {val_str}")
            else:
                print("  REST API: пустой ответ")
        else:
            print("  mvt_id не найден в PBF -- REST API запрос невозможен")

        vydely_findings = compare_vydely_with_docs(tp_data["fields"], rest_payload)
        for f in vydely_findings:
            print(f"  {f}")
        results["findings"].extend(vydely_findings)

    else:
        results["findings"].append("TAXATION_PIECE отсутствует в PBF!")
        print("  ВНИМАНИЕ: TAXATION_PIECE отсутствует в PBF!")

    # ---- Шаг 6: Сравнение КВАРТАЛОВ с документацией ----
    if "QUARTER" in schema:
        print(f"\n{'=' * 80}")
        print("ВЕРИФИКАЦИЯ КВАРТАЛОВ (QUARTER)")
        print(f"{'=' * 80}")

        quarter_findings = compare_quarter_with_docs(schema["QUARTER"]["fields"])
        for f in quarter_findings:
            print(f"  {f}")
        results["findings"].extend(quarter_findings)

    # ---- Шаг 7: Документирование слоёв без документации ----
    undocumented_layers = [
        "FORESTRY_TAXATION_DATE",
        "DISTRICT_FORESTRY_TAXATION_DATE",
        "FOREST_STEAD",
        "FOREST_PURPOSE",
        "PROTECTIVE_FOREST",
        "PROTECTIVE_FOREST_SUBCATEGORY",
        "SPECIAL_PROTECT_STEAD",
        "CLEARCUT",
        "PROCESSING_OBJECT",
    ]

    print(f"\n{'=' * 80}")
    print("СЛОИ БЕЗ ОФИЦИАЛЬНОЙ ДОКУМЕНТАЦИИ")
    print(f"{'=' * 80}")

    for layer_name in undocumented_layers:
        if layer_name in schema:
            ldata = schema[layer_name]
            print(f"\n  {layer_name}: {ldata['feature_count']} фичей, {ldata['geom_type']}")
            print(f"    Поля ({len(ldata['fields'])}):")
            for fname, ftype in ldata['fields'].items():
                sample = ldata['sample_values'].get(fname, '')
                sample_str = f" = {str(sample)[:50]}" if sample != '' else ""
                print(f"      {fname} ({ftype}){sample_str}")
        else:
            print(f"\n  {layer_name}: НЕТ В PBF ТАЙЛЕ")

    # ---- Шаг 8: REST API для других layer_code ----
    if "TAXATION_PIECE" in schema:
        tp_data = schema["TAXATION_PIECE"]
        mvt_id = tp_data["sample_values"].get("mvt_id")

        if mvt_id is not None:
            print(f"\n{'=' * 80}")
            print("REST API: ПРОВЕРКА ДРУГИХ LAYER_CODE")
            print(f"{'=' * 80}")

            other_codes = ["QUARTER", "FORESTRY_TAXATION_DATE",
                           "DISTRICT_FORESTRY_TAXATION_DATE", "FOREST_STEAD"]
            for code in other_codes:
                # Используем externalid/mvt_id из соответствующего слоя если он есть
                test_mvt_id = mvt_id
                if code in schema:
                    code_mvt = schema[code]["sample_values"].get("mvt_id")
                    if code_mvt is not None:
                        test_mvt_id = code_mvt

                print(f"\n  {code} (mvt_id={test_mvt_id}):")
                payload = query_rest_api(int(test_mvt_id), code)
                if payload:
                    print(f"    Получено {len(payload)} полей:")
                    for key, val in sorted(payload.items()):
                        val_str = str(val)[:80] if val is not None else "null"
                        print(f"      {key} = {val_str}")
                    results["rest_api_all_layers"][code] = payload
                else:
                    print(f"    Пустой ответ / ошибка")
                    results["rest_api_all_layers"][code] = None
                time.sleep(0.5)

    # ---- Итоги ----
    print(f"\n{'=' * 80}")
    print("ИТОГИ ВЕРИФИКАЦИИ")
    print(f"{'=' * 80}")

    print(f"\nСлоёв в PBF: {len(schema)}")
    print(f"Слоёв в LAYER_MAPPING: {len(LAYER_MAPPING)}")

    all_known = set(LAYER_MAPPING.keys())
    for extras in LAYER_EXTRAS.values():
        all_known |= extras
    print(f"Всего известных слоёв в коде: {len(all_known)}")

    pbf_layers = set(schema.keys())
    unknown = pbf_layers - all_known
    missing = all_known - pbf_layers

    if unknown:
        print(f"\nНОВЫЕ СЛОИ (требуют добавления в код):")
        for layer_name in sorted(unknown):
            ldata = schema[layer_name]
            print(f"  {layer_name}: {ldata['feature_count']} фичей, {len(ldata['fields'])} полей")

    if missing:
        print(f"\nОТСУТСТВУЮТ В PBF (могут быть в других тайлах):")
        for layer_name in sorted(missing):
            print(f"  {layer_name}")

    # Проверяем полноту ENRICHMENT_FIELDS
    if results.get("rest_api_payload"):
        rest_fields = set(results["rest_api_payload"].keys())
        enrichment_keys = set(ENRICHMENT_FIELDS_CODE.keys())
        uncaptured = rest_fields - enrichment_keys
        if uncaptured:
            print(f"\nREST API: {len(uncaptured)} полей НЕ захвачены ENRICHMENT_FIELDS:")
            for key in sorted(uncaptured):
                val = results["rest_api_payload"][key]
                print(f"  {key} = {str(val)[:60]}")

    results["status"] = "completed"

    # Очистка
    try:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass

    return results


# --------------------------------------------------------------------------
# Интерфейс для тест-раннера QGIS
# --------------------------------------------------------------------------

class TestFgislkSchema:
    """Тест верификации структуры данных ФГИС ЛК для comprehensive runner."""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger

    def run_all_tests(self):
        """Запуск верификации через тест-раннер."""
        self.logger.section("ТЕСТ Fsm_1_2_4: Верификация структуры данных ФГИС ЛК")

        try:
            results = run_schema_verification()

            if results["status"] == "completed":
                self.logger.success(f"Верификация завершена: {len(results['pbf_schema'])} слоёв")

                # Проверяем наличие критических расхождений
                for finding in results.get("findings", []):
                    if "НОВЫЕ СЛОИ" in finding or "ОТСУТСТВУЮТ" in finding:
                        self.logger.warning(finding)
                    elif "НЕ ЗАХВАЧЕНЫ" in finding:
                        self.logger.warning(finding)
                    else:
                        self.logger.info(finding)

                for error in results.get("errors", []):
                    self.logger.error(error)
            else:
                self.logger.fail(f"Верификация не завершена: {results['status']}")
                for error in results.get("errors", []):
                    self.logger.error(error)

        except Exception as e:
            self.logger.error(f"Критическая ошибка: {e}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()


# --------------------------------------------------------------------------
# Standalone запуск
# --------------------------------------------------------------------------

if __name__ == "__main__":
    print("Standalone запуск верификации ФГИС ЛК...\n")
    results = run_schema_verification()

    # Сохраняем JSON отчёт
    report_path = os.path.join(os.path.dirname(__file__), "_schema_report.json")
    try:
        # Сериализуем OrderedDict -> dict для JSON
        serializable = {
            "status": results["status"],
            "findings": results["findings"],
            "errors": results["errors"],
            "pbf_layers": {},
            "rest_api_payload_keys": [],
            "rest_api_all_layers_keys": {},
        }
        for lname, ldata in results["pbf_schema"].items():
            serializable["pbf_layers"][lname] = {
                "geom_type": ldata["geom_type"],
                "feature_count": ldata["feature_count"],
                "fields": dict(ldata["fields"]),
                "sample_values": {k: str(v)[:100] for k, v in ldata["sample_values"].items()},
            }
        if results["rest_api_payload"]:
            serializable["rest_api_payload_keys"] = sorted(results["rest_api_payload"].keys())
        for code, payload in results.get("rest_api_all_layers", {}).items():
            if payload:
                serializable["rest_api_all_layers_keys"][code] = sorted(payload.keys())

        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)
        print(f"\nОтчёт сохранён: {report_path}")
    except Exception as e:
        print(f"\nОшибка сохранения отчёта: {e}")

    print(f"\nСтатус: {results['status']}")
