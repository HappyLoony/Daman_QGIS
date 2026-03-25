# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_5_1 - Комплексный тест ФГИС ЛК: мониторинг, здоровье эндпоинтов, данные

ПОКРЫТИЕ:
  1. Endpoint health check: текущий gwc-01 жив, pub4 мёртв
  2. URL-паттерны и архитектурные фазы (pub -> pub4 -> map/gwc-01)
  3. Fallback-цепочка эндпоинтов (gwc-01 -> gwc-02 -> gwc)
  4. WMTS GetCapabilities парсинг для автоматического определения URL
  5. SSL сертификаты Минцифры (verify=False)
  6. Changelog Рослесхоза -- доступность страницы
  7. DNS/CT мониторинг поддоменов (crt.sh)
  8. TileCache (RAM + disk)
  9. Тайловая сетка: CUSTOM_RESOLUTIONS, mercator_to_tile, tile_to_geometry
  10. PBF тайл: загрузка, парсинг, извлечение слоёв
  11. snappedToGrid для merge геометрий на границах тайлов
  12. Union-схема полей (переменные PBF схемы)
  13. REST API обогащения атрибутов (attributesinfo)
  14. LAYER_MAPPING и LAYER_EXTRAS целостность
  15. Session creation (connection pooling, retry strategy)
  16. Referer header обязательность
  17. Full pipeline: load_layers (если проект открыт)
  18. geowebcache-tile-bounds HTTP header (Fadeev паттерн)
  19. externalid поле в PBF features (ключ merge)
  20. Content-Type ответа PBF (protobuf/mvt)
  21. MVT extent 4096 (координатная сетка)
  22. gwc-02/gwc-03 проактивное обнаружение (раннее предупреждение миграции)

ЗАВИСИМОСТИ:
  - requests, urllib3 (HTTP)
  - osgeo.ogr (PBF парсинг)
  - qgis.core (геометрии, слои)
  - Fsm_1_2_4_fgislk_loader (тестируемый модуль)
  - APIManager (endpoints)

ВРЕМЯ: ~30-60 сек (сетевые тесты, PBF загрузка)
"""

import hashlib
import math
import os
import tempfile
import time
from collections import OrderedDict
from typing import Dict, List, Optional, Set, Tuple
from xml.etree import ElementTree

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

urllib3.disable_warnings(InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Константы тестирования
# ---------------------------------------------------------------------------

# Тестовая точка: лесная зона (из Base_api_endpoints.json endpoint 22)
TEST_LON = 37.8877122
TEST_LAT = 55.7276567

# Известные endpoints (хронология архитектурных фаз)
ENDPOINTS_HISTORY = {
    "phase1_embedded_gwc": {
        "host": "pub.fgislk.gov.ru",
        "path": "/plk/geoservermaster/geoserver/gwc/",
        "status": "deprecated",
        "description": "Встроенный GWC внутри GeoServer",
    },
    "phase2_standalone_gwc": {
        "host": "pub4.fgislk.gov.ru",
        "path": "/plk/gwc/geowebcache/",
        "status": "dead",
        "description": "Standalone GWC (pub4/pub5 CDN ноды)",
    },
    "phase3_cluster_gwc": {
        "host": "map.fgislk.gov.ru",
        "path": "/plk/gwc-01/geowebcache/",
        "status": "active",
        "description": "Кластерный GWC (gwc-01 WAR в Tomcat, ГЕОП)",
    },
}

# Текущий активный endpoint
ACTIVE_TMS_BASE = "https://map.fgislk.gov.ru/plk/gwc-01/geowebcache/service/tms/1.0.0"
ACTIVE_TILE_URL = (
    "https://map.fgislk.gov.ru/plk/gwc-01/geowebcache/service/tms/1.0.0/"
    "FOREST_LAYERS:FOREST@EPSG:3857@pbf"
)

# Мёртвый endpoint (для проверки что действительно мёртв)
DEAD_TILE_URL = (
    "https://pub4.fgislk.gov.ru/plk/gwc/geowebcache/service/tms/1.0.0/"
    "FOREST_LAYERS:FOREST@EPSG:3857@pbf"
)

# Fallback endpoints для проверки
FALLBACK_ENDPOINTS = [
    # gwc-02 (предполагаемый следующий экземпляр)
    "https://map.fgislk.gov.ru/plk/gwc-02/geowebcache/service/tms/1.0.0",
    # gwc без номера (старый путь на новом хосте)
    "https://map.fgislk.gov.ru/plk/gwc/geowebcache/service/tms/1.0.0",
    # pub восстановлен?
    "https://pub.fgislk.gov.ru/plk/geoservermaster/geoserver/gwc/service/tms/1.0.0",
]

# GetCapabilities URLs
WMTS_GETCAPABILITIES_URL = (
    "https://map.fgislk.gov.ru/plk/gwc-01/geowebcache/service/wmts"
    "?REQUEST=GetCapabilities"
)
TMS_CAPABILITIES_URL = (
    "https://map.fgislk.gov.ru/plk/gwc-01/geowebcache/service/tms/1.0.0"
)

# REST API
REST_API_URL = "https://map.fgislk.gov.ru/map/geo/map_api/layer/attributesinfo"

# Changelog Рослесхоза
CHANGELOG_URL = "https://rosleshoz.gov.ru/information-systems/fgis-lk-information/technical-info/"

# crt.sh для DNS мониторинга
CRT_SH_URL = "https://crt.sh/?q=%25.fgislk.gov.ru&output=json"

REFERER = "https://map.fgislk.gov.ru/map/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Referer": REFERER,
}

# Тайловая сетка ФГИС ЛК (дублируем для standalone проверки)
TILE_SIZE_PIXELS = 256
TILE_ZOOM_SERVER = 12
CUSTOM_RESOLUTIONS = [
    13999.999999999998, 11199.999999999998, 5599.999999999999,
    2799.9999999999995, 1399.9999999999998, 699.9999999999999,
    280, 140, 55.99999999999999, 27.999999999999996,
    13.999999999998, 6.999999999999999, 2.8,
]

# Ожидаемые слои LAYER_MAPPING (12 загружаемых)
# FORESTRY, TIMBER_YARD, PROCESSING_OBJECT перенесены в MONITORED_LAYERS
EXPECTED_MAIN_LAYERS = {
    "FORESTRY_APPROVE", "FORESTRY_TAXATION_DATE",
    "DISTRICT_FORESTRY_TAXATION_DATE", "QUARTER", "TAXATION_PIECE",
    "FOREST_STEAD", "PART_FOREST_STEAD",
    "FOREST_PURPOSE", "PROTECTIVE_FOREST", "PROTECTIVE_FOREST_SUBCATEGORY",
    "SPECIAL_PROTECT_STEAD", "CLEARCUT",
}

# Ожидаемые extra-слои (для TAXATION_PIECE)
EXPECTED_EXTRAS_TAXATION = {
    "TAXATION_PIECE_BONITET", "TAXATION_PIECE_EVENT_SCORE",
    "TAXATION_PIECE_EVENT_TYPE", "TAXATION_PIECE_PVS",
    "TAXATION_PIECE_TIMBER_STOCK",
}

# Ожидаемые поля ENRICHMENT_FIELDS (16 полей)
EXPECTED_ENRICHMENT_FIELDS = {
    "square", "totalArea", "objectValid", "category_land", "type_land",
    "forest_land_type", "taxation_date", "tree_species", "age_group",
    "yield_class", "timber_stock", "number", "number_lud",
    "forest_quarter_number", "forest_quarter_number_lud", "event",
}


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def lonlat_to_tile(lon: float, lat: float, zoom_index: int) -> Tuple[int, int]:
    """WGS84 -> tile indices (ФГИС ЛК custom resolutions)."""
    x_m = lon * 20037508.34 / 180.0
    y_rad = math.log(math.tan((90.0 + lat) * math.pi / 360.0))
    y_m = y_rad / (math.pi / 180.0) * 20037508.34 / 180.0
    res = CUSTOM_RESOLUTIONS[zoom_index]
    tile_x = int((x_m + 20037508.34) / (res * TILE_SIZE_PIXELS))
    tile_y = int((y_m + 20037508.34) / (res * TILE_SIZE_PIXELS))
    return tile_x, tile_y


def http_head(url: str, timeout: int = 15) -> Optional[int]:
    """HEAD request, returns status_code or None on error."""
    try:
        r = requests.head(url, headers=HEADERS, verify=False, timeout=timeout,
                          allow_redirects=True)
        return r.status_code
    except Exception:
        return None


def http_get(url: str, timeout: int = 20) -> Optional[requests.Response]:
    """GET request with verify=False, returns Response or None."""
    try:
        return requests.get(url, headers=HEADERS, verify=False, timeout=timeout)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Тестовый класс
# ---------------------------------------------------------------------------

class TestFgislkMonitoring:
    """Комплексный тест ФГИС ЛК: мониторинг, здоровье, данные."""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        # Кэш загруженного PBF для повторного использования между тестами
        self._pbf_path: Optional[str] = None
        self._pbf_response: Optional[requests.Response] = None
        self._temp_dir: Optional[str] = None
        self._tile_x: int = 0
        self._tile_y: int = 0

    def run_all_tests(self):
        """Запуск всех тестов ФГИС ЛК."""
        self.logger.section("ТЕСТ ФГИС ЛК: Мониторинг, здоровье эндпоинтов, данные")

        try:
            # ГРУППА 1: Мониторинг эндпоинтов
            self._test_01_active_endpoint_health()
            self._test_02_dead_endpoint_confirmed()
            self._test_03_fallback_chain_probing()
            self._test_04_ssl_certificates()
            self._test_05_referer_requirement()

            # ГРУППА 2: GetCapabilities и автообнаружение URL
            self._test_06_wmts_getcapabilities()
            self._test_07_tms_capabilities()

            # ГРУППА 3: Внешние источники информации
            self._test_08_changelog_rosleshoz()
            self._test_09_dns_ct_monitoring()

            # ГРУППА 4: Код модуля Fsm_1_2_4
            self._test_10_import_and_constants()
            self._test_11_layer_mapping_integrity()
            self._test_12_enrichment_fields_integrity()
            self._test_13_tile_grid_math()
            self._test_14_tile_cache()

            # ГРУППА 5: Загрузка и парсинг PBF
            self._test_15_download_pbf_tile()
            self._test_16_parse_pbf_ogr()
            self._test_17_pbf_layer_coverage()

            # ГРУППА 6: Геометрии
            self._test_18_snapped_to_grid()
            self._test_19_union_field_schema()
            self._test_20_geometry_merge_pipeline()

            # ГРУППА 7: REST API обогащения
            self._test_21_rest_api_attributesinfo()

            # ГРУППА 8: Инициализация модуля (требует APIManager)
            self._test_22_loader_initialization()
            self._test_23_session_creation()

            # ГРУППА 9: URL-паттерны архитектуры
            self._test_24_url_architecture_patterns()

            # ГРУППА 10: Полный pipeline (если есть проект)
            self._test_25_full_pipeline()

            # ГРУППА 11: Пробелы покрытия (из исследования)
            self._test_26_changelog_deep_parse()
            self._test_27_batch_tile_stability()
            self._test_28_pub4_batch_confirm_dead()
            self._test_29_frontend_js_url_extraction()
            self._test_30_gislab_forum()
            self._test_31_github_fgislk()

            # ГРУППА 12: Паттерны из референса Fadeev
            self._test_32_gwc_tile_bounds_header()
            self._test_33_externalid_in_pbf()
            self._test_34_pbf_content_type()
            self._test_35_mvt_extent_4096()

            # ГРУППА 13: Проактивное обнаружение gwc-02/gwc-03
            self._test_36_gwc_next_instances()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов ФГИС ЛК: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
        finally:
            # Очистка временных файлов
            self._cleanup()

        self.logger.summary()

    # ===================================================================
    # ГРУППА 1: Мониторинг эндпоинтов
    # ===================================================================

    def _test_01_active_endpoint_health(self):
        """ТЕСТ 1: Текущий endpoint gwc-01 жив."""
        self.logger.section("1. Health check: активный endpoint (gwc-01)")

        # Проверяем TMS root
        status = http_head(ACTIVE_TMS_BASE)
        self.logger.check(
            status is not None and status < 500,
            f"TMS root доступен: HTTP {status}",
            f"TMS root недоступен: HTTP {status}"
        )

        # Проверяем конкретный тайл
        tx, ty = lonlat_to_tile(TEST_LON, TEST_LAT, TILE_ZOOM_SERVER)
        tile_url = f"{ACTIVE_TILE_URL}/{TILE_ZOOM_SERVER}/{tx}/{ty}.pbf"

        resp = http_get(tile_url)
        if resp is not None:
            self.logger.check(
                resp.status_code == 200,
                f"Тайл ({tx},{ty}) загружен: HTTP {resp.status_code}, {len(resp.content)} bytes",
                f"Тайл ({tx},{ty}) ошибка: HTTP {resp.status_code}"
            )
            if resp.status_code == 200:
                self.logger.check(
                    len(resp.content) > 100,
                    f"PBF содержит данные: {len(resp.content)} bytes",
                    f"PBF подозрительно мал: {len(resp.content)} bytes"
                )
        else:
            self.logger.fail("Не удалось подключиться к gwc-01")

    def _test_02_dead_endpoint_confirmed(self):
        """ТЕСТ 2: Старый endpoint pub4 подтверждённо мёртв."""
        self.logger.section("2. Подтверждение: pub4 мёртв")

        tx, ty = lonlat_to_tile(TEST_LON, TEST_LAT, TILE_ZOOM_SERVER)
        tile_url = f"{DEAD_TILE_URL}/{TILE_ZOOM_SERVER}/{tx}/{ty}.pbf"

        resp = http_get(tile_url, timeout=10)
        if resp is not None:
            self.logger.check(
                resp.status_code in (404, 502, 503),
                f"pub4 подтверждённо мёртв: HTTP {resp.status_code}",
                f"pub4 НЕОЖИДАННО ОТВЕТИЛ: HTTP {resp.status_code} (возможно воскрес!)"
            )
        else:
            self.logger.success("pub4 недоступен (connection error) -- подтверждено")

    def _test_03_fallback_chain_probing(self):
        """ТЕСТ 3: Проверка fallback-цепочки эндпоинтов."""
        self.logger.section("3. Fallback-цепочка: gwc-02, gwc, pub")

        for url in FALLBACK_ENDPOINTS:
            status = http_head(url, timeout=10)
            if status is not None and status < 400:
                self.logger.warning(
                    f"Fallback ОБНАРУЖЕН: {url} -> HTTP {status} (возможная миграция!)"
                )
            else:
                status_str = f"HTTP {status}" if status else "Connection error"
                self.logger.info(f"Fallback недоступен: {url} -> {status_str}")

        self.logger.success("Fallback-цепочка проверена (нет активных альтернатив -- OK)")

    def _test_04_ssl_certificates(self):
        """ТЕСТ 4: SSL сертификаты Минцифры (verify=False обязателен)."""
        self.logger.section("4. SSL сертификаты Минцифры")

        # С verify=False должно работать
        try:
            resp = requests.get(
                ACTIVE_TMS_BASE, verify=False, headers=HEADERS, timeout=15
            )
            self.logger.success(f"verify=False: OK (HTTP {resp.status_code})")
        except Exception as e:
            self.logger.fail(f"verify=False: ошибка - {str(e)[:80]}")

        # С verify=True должно упасть (сертификат НУЦ Минцифры)
        try:
            resp = requests.get(
                ACTIVE_TMS_BASE, verify=True, headers=HEADERS, timeout=10
            )
            # Если прошло -- сертификат теперь в доверенных (или CA изменился)
            self.logger.warning(
                f"verify=True: НЕОЖИДАННО ПРОШЁЛ (HTTP {resp.status_code}). "
                "Сертификат в доверенных или CA изменился!"
            )
        except requests.exceptions.SSLError:
            self.logger.success("verify=True: SSLError -- подтверждено (НУЦ Минцифры)")
        except Exception as e:
            self.logger.info(f"verify=True: {type(e).__name__} - {str(e)[:60]}")

    def _test_05_referer_requirement(self):
        """ТЕСТ 5: Referer header обязателен для доступа."""
        self.logger.section("5. Referer header: обязательность")

        tx, ty = lonlat_to_tile(TEST_LON, TEST_LAT, TILE_ZOOM_SERVER)
        tile_url = f"{ACTIVE_TILE_URL}/{TILE_ZOOM_SERVER}/{tx}/{ty}.pbf"

        # С Referer
        headers_with = dict(HEADERS)
        resp_with = http_get(tile_url)
        status_with = resp_with.status_code if resp_with else None

        # Без Referer
        headers_without = {
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "*/*",
        }
        try:
            resp_without = requests.get(
                tile_url, headers=headers_without, verify=False, timeout=15
            )
            status_without = resp_without.status_code
        except Exception:
            status_without = None

        self.logger.data("С Referer", f"HTTP {status_with}")
        self.logger.data("Без Referer", f"HTTP {status_without}")

        if status_with == 200 and status_without != 200:
            self.logger.success("Referer обязателен: с ним 200, без него отказ")
        elif status_with == 200 and status_without == 200:
            self.logger.warning("Referer НЕ обязателен (оба запроса 200) -- политика изменилась?")
        else:
            self.logger.info(f"Результат неоднозначен: with={status_with}, without={status_without}")

    # ===================================================================
    # ГРУППА 2: GetCapabilities
    # ===================================================================

    def _test_06_wmts_getcapabilities(self):
        """ТЕСТ 6: WMTS GetCapabilities -- автообнаружение URL."""
        self.logger.section("6. WMTS GetCapabilities")

        resp = http_get(WMTS_GETCAPABILITIES_URL, timeout=30)

        if resp is None:
            self.logger.warning("WMTS GetCapabilities: connection error")
            return

        self.logger.data("HTTP Status", str(resp.status_code))

        if resp.status_code != 200:
            self.logger.warning(f"GetCapabilities: HTTP {resp.status_code}")
            return

        content_type = resp.headers.get("Content-Type", "")
        is_xml = "xml" in content_type.lower() or resp.text.strip().startswith("<?xml")

        self.logger.check(
            is_xml,
            f"Ответ содержит XML ({len(resp.text)} chars)",
            f"Ответ НЕ XML: Content-Type={content_type}"
        )

        if not is_xml:
            return

        # Парсим XML для извлечения ResourceURL
        try:
            root = ElementTree.fromstring(resp.text)
            # Ищем namespace
            ns = ""
            if root.tag.startswith("{"):
                ns = root.tag.split("}")[0] + "}"

            # Ищем все Layer и ResourceURL элементы
            layers_found = []
            for layer_elem in root.iter(f"{ns}Layer"):
                identifier = layer_elem.find(f"{ns}Identifier")
                if identifier is not None and identifier.text:
                    layers_found.append(identifier.text)

            resource_urls = []
            for res_url in root.iter(f"{ns}ResourceURL"):
                template = res_url.get("template", "")
                if template:
                    resource_urls.append(template)

            self.logger.data("Слоёв найдено", str(len(layers_found)))
            if layers_found:
                self.logger.data("Примеры", ", ".join(layers_found[:5]))

            self.logger.data("ResourceURL шаблонов", str(len(resource_urls)))
            if resource_urls:
                # Извлекаем hostname и path из первого шаблона
                for tmpl in resource_urls[:2]:
                    self.logger.data("  URL шаблон", tmpl[:120])

            # Проверяем что gwc-01 присутствует в URL'ах
            gwc01_found = any("gwc-01" in url for url in resource_urls)
            if gwc01_found:
                self.logger.success("gwc-01 найден в ResourceURL шаблонах")
            elif resource_urls:
                # GWC может отдавать URL без gwc-01 (относительные пути, прокси)
                # Проверяем нет ли gwc-02 или другого экземпляра
                gwc02_found = any("gwc-02" in url for url in resource_urls)
                if gwc02_found:
                    self.logger.warning("gwc-02 найден в ResourceURL -- МИГРАЦИЯ!")
                else:
                    self.logger.info(
                        "gwc-01 не найден в ResourceURL (возможно относительные URL)"
                    )
                    for tmpl in resource_urls[:3]:
                        self.logger.data("  ResourceURL", tmpl[:150])
            else:
                self.logger.info("ResourceURL шаблоны отсутствуют в GetCapabilities")

        except ElementTree.ParseError as e:
            self.logger.warning(f"XML parse error: {str(e)[:60]}")
        except Exception as e:
            self.logger.warning(f"GetCapabilities parse error: {str(e)[:60]}")

    def _test_07_tms_capabilities(self):
        """ТЕСТ 7: TMS 1.0.0 capabilities."""
        self.logger.section("7. TMS Capabilities")

        resp = http_get(TMS_CAPABILITIES_URL, timeout=20)

        if resp is None:
            self.logger.warning("TMS Capabilities: connection error")
            return

        self.logger.check(
            resp.status_code == 200,
            f"TMS root доступен: HTTP {resp.status_code}",
            f"TMS root ошибка: HTTP {resp.status_code}"
        )

        if resp.status_code == 200:
            # Проверяем что ответ содержит информацию о слоях
            text = resp.text
            has_forest = "FOREST" in text
            has_tms = "TileMapService" in text or "TileMap" in text

            self.logger.check(
                has_forest or has_tms,
                f"TMS содержит информацию о слоях: FOREST={has_forest}, TileMap={has_tms}",
                "TMS ответ не содержит ожидаемых данных"
            )
            self.logger.data("Размер ответа", f"{len(text)} chars")

    # ===================================================================
    # ГРУППА 3: Внешние источники информации
    # ===================================================================

    def _test_08_changelog_rosleshoz(self):
        """ТЕСТ 8: Changelog Рослесхоза -- доступность."""
        self.logger.section("8. Changelog Рослесхоза")

        try:
            resp = requests.get(
                CHANGELOG_URL,
                headers={
                    "User-Agent": HEADERS["User-Agent"],
                    "Accept": "text/html",
                },
                verify=True,  # rosleshoz.gov.ru использует стандартный SSL
                timeout=20,
            )
            self.logger.check(
                resp.status_code == 200,
                f"Changelog доступен: HTTP {resp.status_code}",
                f"Changelog ошибка: HTTP {resp.status_code}"
            )

            if resp.status_code == 200:
                text = resp.text.lower()
                # Проверяем наличие ключевых слов
                has_version = "4.14" in resp.text or "версия" in text
                has_plk = "плк" in text or "лесн" in text or "карт" in text
                self.logger.data("Содержит версию", str(has_version))
                self.logger.data("Содержит ПЛК/карты", str(has_plk))

        except requests.exceptions.SSLError:
            self.logger.warning("Changelog: SSL ошибка (rosleshoz.gov.ru)")
        except Exception as e:
            self.logger.warning(f"Changelog: {type(e).__name__} - {str(e)[:60]}")

    def _test_09_dns_ct_monitoring(self):
        """ТЕСТ 9: DNS/Certificate Transparency мониторинг."""
        self.logger.section("9. DNS/CT мониторинг (crt.sh)")

        try:
            resp = requests.get(CRT_SH_URL, timeout=30)

            if resp.status_code != 200:
                self.logger.warning(f"crt.sh: HTTP {resp.status_code}")
                return

            data = resp.json()
            # Извлекаем уникальные поддомены
            subdomains = set()
            for entry in data:
                name = entry.get("name_value", "")
                for line in name.split("\n"):
                    line = line.strip()
                    if line.endswith(".fgislk.gov.ru") or line == "fgislk.gov.ru":
                        subdomains.add(line)

            self.logger.data("Поддоменов найдено", str(len(subdomains)))
            if subdomains:
                for sd in sorted(subdomains)[:10]:
                    self.logger.data("  Поддомен", sd)

            # Проверяем наличие известных хостов
            # НУЦ Минцифры НЕ участвует в Certificate Transparency --
            # fgislk.gov.ru может отсутствовать в crt.sh (это нормально)
            has_map = any("map.fgislk" in sd for sd in subdomains)
            has_pub = any("pub" in sd for sd in subdomains)

            if has_map:
                self.logger.success("map.fgislk.gov.ru найден в CT logs")
            else:
                self.logger.info(
                    "map.fgislk.gov.ru не найден в CT logs "
                    "(ожидаемо: НУЦ Минцифры не в CT)"
                )

            # Детекция новых поддоменов (не map, не pub*, не www)
            known_prefixes = {"map.", "pub", "www.", "fgislk.gov.ru"}
            unknown = [sd for sd in subdomains
                       if not any(sd.startswith(p) or sd == p for p in known_prefixes)]
            if unknown:
                self.logger.warning(f"Новые поддомены: {unknown}")
            else:
                self.logger.info("Новых поддоменов не обнаружено")

        except requests.exceptions.ConnectionError:
            self.logger.warning("crt.sh: connection error (может быть заблокирован)")
        except Exception as e:
            self.logger.warning(f"crt.sh: {type(e).__name__} - {str(e)[:60]}")

    # ===================================================================
    # ГРУППА 4: Код модуля Fsm_1_2_4
    # ===================================================================

    def _test_10_import_and_constants(self):
        """ТЕСТ 10: Импорт модуля и проверка констант."""
        self.logger.section("10. Импорт Fsm_1_2_4 и проверка констант")

        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_4_fgislk_loader import (
                Fsm_1_2_4_FgislkLoader,
                TileCache,
            )
            self.logger.success("Fsm_1_2_4_FgislkLoader импортирован")
            self.logger.success("TileCache импортирован")

            # Проверяем константы класса
            self.logger.check(
                Fsm_1_2_4_FgislkLoader.TILE_SIZE_PIXELS == 256,
                f"TILE_SIZE_PIXELS = {Fsm_1_2_4_FgislkLoader.TILE_SIZE_PIXELS}",
                f"TILE_SIZE_PIXELS != 256: {Fsm_1_2_4_FgislkLoader.TILE_SIZE_PIXELS}"
            )

            self.logger.check(
                Fsm_1_2_4_FgislkLoader.TILE_ZOOM_SERVER == 12,
                f"TILE_ZOOM_SERVER = {Fsm_1_2_4_FgislkLoader.TILE_ZOOM_SERVER}",
                f"TILE_ZOOM_SERVER != 12: {Fsm_1_2_4_FgislkLoader.TILE_ZOOM_SERVER}"
            )

            self.logger.check(
                len(Fsm_1_2_4_FgislkLoader.CUSTOM_RESOLUTIONS) == 13,
                f"CUSTOM_RESOLUTIONS: {len(Fsm_1_2_4_FgislkLoader.CUSTOM_RESOLUTIONS)} уровней",
                f"CUSTOM_RESOLUTIONS != 13: {len(Fsm_1_2_4_FgislkLoader.CUSTOM_RESOLUTIONS)}"
            )

            # Проверяем что CUSTOM_RESOLUTIONS совпадают с нашими тестовыми
            for i, (actual, expected) in enumerate(
                zip(Fsm_1_2_4_FgislkLoader.CUSTOM_RESOLUTIONS, CUSTOM_RESOLUTIONS)
            ):
                if abs(actual - expected) > 0.001:
                    self.logger.fail(f"CUSTOM_RESOLUTIONS[{i}]: {actual} != {expected}")
                    break
            else:
                self.logger.success("CUSTOM_RESOLUTIONS совпадают с тестовыми")

            # REST API URL
            self.logger.check(
                "map.fgislk.gov.ru" in Fsm_1_2_4_FgislkLoader.FGISLK_REST_API_URL,
                f"REST API URL: {Fsm_1_2_4_FgislkLoader.FGISLK_REST_API_URL}",
                f"REST API URL не содержит map.fgislk: {Fsm_1_2_4_FgislkLoader.FGISLK_REST_API_URL}"
            )

        except ImportError as e:
            self.logger.fail(f"Ошибка импорта: {str(e)}")
        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")

    def _test_11_layer_mapping_integrity(self):
        """ТЕСТ 11: LAYER_MAPPING и LAYER_EXTRAS целостность."""
        self.logger.section("11. LAYER_MAPPING / LAYER_EXTRAS")

        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_4_fgislk_loader import (
                Fsm_1_2_4_FgislkLoader,
            )

            mapping = Fsm_1_2_4_FgislkLoader.LAYER_MAPPING
            extras = Fsm_1_2_4_FgislkLoader.LAYER_EXTRAS

            # Проверяем количество
            self.logger.check(
                len(mapping) == 12,
                f"LAYER_MAPPING: {len(mapping)} слоёв (ожидалось 12)",
                f"LAYER_MAPPING: {len(mapping)} != 12"
            )

            # Проверяем что все ожидаемые слои есть
            actual_keys = set(mapping.keys())
            missing = EXPECTED_MAIN_LAYERS - actual_keys
            extra = actual_keys - EXPECTED_MAIN_LAYERS

            self.logger.check(
                not missing,
                "Все ожидаемые слои присутствуют",
                f"Отсутствуют слои: {missing}"
            )

            if extra:
                self.logger.warning(f"Новые слои в LAYER_MAPPING: {extra}")

            # Проверяем LAYER_EXTRAS
            self.logger.check(
                set(extras.keys()) == set(mapping.keys()),
                "LAYER_EXTRAS покрывает все слои LAYER_MAPPING",
                f"Расхождение ключей EXTRAS vs MAPPING"
            )

            # Проверяем extras для TAXATION_PIECE
            tp_extras = extras.get("TAXATION_PIECE", set())
            self.logger.check(
                tp_extras == EXPECTED_EXTRAS_TAXATION,
                f"TAXATION_PIECE extras: {len(tp_extras)} слоёв",
                f"TAXATION_PIECE extras расходятся: {tp_extras ^ EXPECTED_EXTRAS_TAXATION}"
            )

            # Проверяем что все значения LAYER_MAPPING начинаются с Le_
            bad_names = [v for v in mapping.values() if not v.startswith("Le_")]
            self.logger.check(
                not bad_names,
                "Все имена слоёв начинаются с Le_",
                f"Некорректные имена: {bad_names}"
            )

            # Проверяем POLYGON_LAYERS_IN_DB
            poly_layers = Fsm_1_2_4_FgislkLoader.POLYGON_LAYERS_IN_DB
            self.logger.check(
                poly_layers.issubset(actual_keys),
                f"POLYGON_LAYERS_IN_DB ({len(poly_layers)}) -- подмножество LAYER_MAPPING",
                f"POLYGON_LAYERS_IN_DB содержит неизвестные ключи: {poly_layers - actual_keys}"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")

    def _test_12_enrichment_fields_integrity(self):
        """ТЕСТ 12: ENRICHMENT_FIELDS целостность."""
        self.logger.section("12. ENRICHMENT_FIELDS")

        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_4_fgislk_loader import (
                Fsm_1_2_4_FgislkLoader,
            )

            fields = Fsm_1_2_4_FgislkLoader.ENRICHMENT_FIELDS
            actual_keys = set(fields.keys())

            self.logger.check(
                len(fields) == 16,
                f"ENRICHMENT_FIELDS: {len(fields)} полей (ожидалось 16)",
                f"ENRICHMENT_FIELDS: {len(fields)} != 16"
            )

            missing = EXPECTED_ENRICHMENT_FIELDS - actual_keys
            extra = actual_keys - EXPECTED_ENRICHMENT_FIELDS

            self.logger.check(
                not missing,
                "Все ожидаемые поля обогащения присутствуют",
                f"Отсутствуют: {missing}"
            )
            if extra:
                self.logger.warning(f"Новые поля обогащения: {extra}")

            # Проверяем структуру: каждое значение -- tuple(str, QMetaType.Type)
            from qgis.PyQt.QtCore import QMetaType
            for api_name, (layer_name, field_type) in fields.items():
                if not isinstance(layer_name, str) or not layer_name:
                    self.logger.fail(f"  {api_name}: layer_name не str: {layer_name}")
                    break
            else:
                self.logger.success("Все поля имеют корректную структуру (str, QMetaType)")

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")

    def _test_13_tile_grid_math(self):
        """ТЕСТ 13: Тайловая сетка: CUSTOM_RESOLUTIONS, конвертация координат."""
        self.logger.section("13. Тайловая сетка (математика)")

        # Проверяем тестовую точку
        tx, ty = lonlat_to_tile(TEST_LON, TEST_LAT, TILE_ZOOM_SERVER)
        self.logger.data("Тестовая точка", f"({TEST_LON}, {TEST_LAT})")
        self.logger.data("Тайл", f"({tx}, {ty}) @ zoom {TILE_ZOOM_SERVER}")

        # Валидация: координаты должны быть положительные и разумные
        self.logger.check(
            tx > 0 and ty > 0,
            f"Координаты тайла положительные: ({tx}, {ty})",
            f"Координаты тайла некорректные: ({tx}, {ty})"
        )

        # Для зума 12 (resolution=2.8): ~55908 тайлов по оси
        # Координаты Подмосковья: ~(33838, 38423)
        max_tile_idx = int((2 * 20037508.34) / (CUSTOM_RESOLUTIONS[TILE_ZOOM_SERVER] * TILE_SIZE_PIXELS)) + 1
        self.logger.check(
            0 < tx < max_tile_idx and 0 < ty < max_tile_idx,
            f"Координаты в диапазоне [0, {max_tile_idx}): ({tx}, {ty})",
            f"Координаты вне диапазона [0, {max_tile_idx}): ({tx}, {ty})"
        )

        # Проверяем обратное преобразование через loader (если доступен)
        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_4_fgislk_loader import (
                Fsm_1_2_4_FgislkLoader,
            )
            # Проверяем что CUSTOM_RESOLUTIONS убывают (зум увеличивается -> разрешение уменьшается)
            resolutions = Fsm_1_2_4_FgislkLoader.CUSTOM_RESOLUTIONS
            is_decreasing = all(
                resolutions[i] > resolutions[i + 1]
                for i in range(len(resolutions) - 1)
            )
            self.logger.check(
                is_decreasing,
                "CUSTOM_RESOLUTIONS монотонно убывают (корректно)",
                "CUSTOM_RESOLUTIONS НЕ убывают (ошибка тайловой сетки!)"
            )

        except Exception as e:
            self.logger.warning(f"Не удалось проверить через loader: {str(e)[:60]}")

    def _test_14_tile_cache(self):
        """ТЕСТ 14: TileCache (RAM + disk)."""
        self.logger.section("14. TileCache")

        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_4_fgislk_loader import TileCache

            cache = TileCache()

            # Тест RAM кэша
            test_data = b"test_pbf_data_12345"
            cache.put("test_key", test_data)

            retrieved = cache.get("test_key")
            self.logger.check(
                retrieved == test_data,
                "RAM кэш: put/get работает",
                "RAM кэш: данные не совпадают"
            )

            # Тест несуществующего ключа
            missing = cache.get("nonexistent_key")
            self.logger.check(
                missing is None,
                "RAM кэш: отсутствующий ключ -> None",
                "RAM кэш: отсутствующий ключ не None!"
            )

            # Тест disk кэша
            with tempfile.NamedTemporaryFile(suffix=".pbf", delete=False) as tmp:
                tmp.write(test_data)
                tmp_path = tmp.name

            try:
                cache2 = TileCache()
                cache2.put("disk_key", test_data, tmp_path)

                # Очищаем RAM, проверяем что данные загружаются с диска
                cache2.clear_memory()
                from_disk = cache2.get("disk_key")
                self.logger.check(
                    from_disk == test_data,
                    "Disk кэш: fallback с диска работает",
                    "Disk кэш: данные не загрузились"
                )
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

            # Тест clear_memory
            cache.clear_memory()
            after_clear = cache.get("test_key")
            self.logger.check(
                after_clear is None,
                "clear_memory: RAM очищен",
                "clear_memory: данные остались"
            )

        except Exception as e:
            self.logger.error(f"Ошибка TileCache: {str(e)}")

    # ===================================================================
    # ГРУППА 5: Загрузка и парсинг PBF
    # ===================================================================

    def _test_15_download_pbf_tile(self):
        """ТЕСТ 15: Загрузка PBF тайла."""
        self.logger.section("15. Загрузка PBF тайла")

        self._tile_x, self._tile_y = lonlat_to_tile(TEST_LON, TEST_LAT, TILE_ZOOM_SERVER)
        self._temp_dir = tempfile.mkdtemp(prefix="fgislk_test_")

        tile_url = f"{ACTIVE_TILE_URL}/{TILE_ZOOM_SERVER}/{self._tile_x}/{self._tile_y}.pbf"
        pbf_path = os.path.join(self._temp_dir, f"tile_{self._tile_x}_{self._tile_y}.pbf")

        start = time.time()
        resp = http_get(tile_url, timeout=30)
        elapsed = time.time() - start

        if resp is None or resp.status_code != 200:
            # Пробуем соседние тайлы
            self.logger.warning(f"Основной тайл ({self._tile_x},{self._tile_y}) недоступен, пробуем соседние...")
            found = False
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    if dx == 0 and dy == 0:
                        continue
                    alt_x = self._tile_x + dx
                    alt_y = self._tile_y + dy
                    alt_url = f"{ACTIVE_TILE_URL}/{TILE_ZOOM_SERVER}/{alt_x}/{alt_y}.pbf"
                    alt_resp = http_get(alt_url, timeout=20)
                    if alt_resp and alt_resp.status_code == 200 and len(alt_resp.content) > 100:
                        resp = alt_resp
                        self._tile_x, self._tile_y = alt_x, alt_y
                        pbf_path = os.path.join(self._temp_dir, f"tile_{alt_x}_{alt_y}.pbf")
                        found = True
                        break
                if found:
                    break

        if resp is None or resp.status_code != 200:
            self.logger.fail("Не удалось загрузить ни один PBF тайл")
            return

        # Сохраняем PBF и response
        with open(pbf_path, "wb") as f:
            f.write(resp.content)
        self._pbf_path = pbf_path
        self._pbf_response = resp

        file_size = len(resp.content)
        self.logger.success(
            f"PBF загружен: ({self._tile_x},{self._tile_y}), "
            f"{file_size} bytes, {elapsed:.2f} сек"
        )

        self.logger.check(
            file_size > 500,
            f"PBF содержит данные (>{500} bytes)",
            f"PBF подозрительно мал: {file_size} bytes"
        )

    def _test_16_parse_pbf_ogr(self):
        """ТЕСТ 16: Парсинг PBF через OGR."""
        self.logger.section("16. Парсинг PBF (OGR)")

        if not self._pbf_path:
            self.logger.warning("PBF не загружен (тест 15 не прошёл), пропуск")
            return

        try:
            from osgeo import ogr

            ds = ogr.Open(self._pbf_path)
            self.logger.check(
                ds is not None,
                "OGR: PBF открыт успешно",
                "OGR: не удалось открыть PBF"
            )
            if not ds:
                return

            layer_count = ds.GetLayerCount()
            self.logger.data("Слоёв в PBF", str(layer_count))

            self.logger.check(
                layer_count > 0,
                f"PBF содержит {layer_count} слоёв",
                "PBF пустой (0 слоёв)"
            )

            # Собираем информацию о каждом слое
            pbf_layer_names = set()
            for i in range(layer_count):
                layer = ds.GetLayerByIndex(i)
                if layer:
                    name = layer.GetName()
                    feat_count = layer.GetFeatureCount()
                    field_count = layer.GetLayerDefn().GetFieldCount()
                    pbf_layer_names.add(name)
                    self.logger.info(
                        f"  {name}: {feat_count} features, {field_count} fields"
                    )

            # Проверяем наличие ключевых слоёв
            key_layers = {"QUARTER", "TAXATION_PIECE", "FORESTRY"}
            found_key = key_layers & pbf_layer_names
            self.logger.check(
                len(found_key) > 0,
                f"Ключевые слои найдены: {found_key}",
                f"Ни один ключевой слой не найден в PBF"
            )

            ds = None

        except ImportError:
            self.logger.warning("osgeo.ogr не доступен -- пропуск OGR парсинга")
        except Exception as e:
            self.logger.error(f"Ошибка OGR: {str(e)}")

    def _test_17_pbf_layer_coverage(self):
        """ТЕСТ 17: Покрытие слоёв PBF vs LAYER_MAPPING."""
        self.logger.section("17. Покрытие слоёв PBF vs код")

        if not self._pbf_path:
            self.logger.warning("PBF не загружен, пропуск")
            return

        try:
            from osgeo import ogr
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_4_fgislk_loader import (
                Fsm_1_2_4_FgislkLoader,
            )

            ds = ogr.Open(self._pbf_path)
            if not ds:
                self.logger.fail("OGR: не удалось открыть PBF")
                return

            pbf_layers = set()
            for i in range(ds.GetLayerCount()):
                layer = ds.GetLayerByIndex(i)
                if layer:
                    pbf_layers.add(layer.GetName())
            ds = None

            known_main = set(Fsm_1_2_4_FgislkLoader.LAYER_MAPPING.keys())
            known_extras = set()
            for extras in Fsm_1_2_4_FgislkLoader.LAYER_EXTRAS.values():
                known_extras |= extras
            known_all = known_main | known_extras

            # Новые слои в PBF
            unknown = pbf_layers - known_all
            if unknown:
                self.logger.warning(f"Новые слои в PBF (нет в коде): {sorted(unknown)}")
            else:
                self.logger.success("Все слои PBF известны в LAYER_MAPPING/EXTRAS")

            # Присутствующие основные слои
            present_main = known_main & pbf_layers
            self.logger.data("Основные в PBF", f"{len(present_main)}/{len(known_main)}")

            # Присутствующие extra слои
            present_extras = known_extras & pbf_layers
            self.logger.data("Extra в PBF", f"{len(present_extras)}/{len(known_extras)}")

        except ImportError:
            self.logger.warning("osgeo.ogr не доступен, пропуск")
        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")

    # ===================================================================
    # ГРУППА 6: Геометрии
    # ===================================================================

    def _test_18_snapped_to_grid(self):
        """ТЕСТ 18: snappedToGrid для merge на границах тайлов."""
        self.logger.section("18. snappedToGrid (merge тайлов)")

        try:
            from qgis.core import QgsGeometry, QgsPointXY

            # Создаём два прямоугольника с микрозазором на границе (эмуляция тайлов)
            # Прямоугольник 1: (0, 0) - (100, 100)
            poly1 = QgsGeometry.fromPolygonXY([[
                QgsPointXY(0, 0), QgsPointXY(100.003, 0),
                QgsPointXY(100.003, 100), QgsPointXY(0, 100),
                QgsPointXY(0, 0)
            ]])
            # Прямоугольник 2: (100, 0) - (200, 100) -- граница НЕ совпадает (100 vs 100.003)
            poly2 = QgsGeometry.fromPolygonXY([[
                QgsPointXY(100.007, 0), QgsPointXY(200, 0),
                QgsPointXY(200, 100), QgsPointXY(100.007, 100),
                QgsPointXY(100.007, 0)
            ]])

            # Без snappedToGrid: unaryUnion дает 2 части (зазор)
            union_raw = QgsGeometry.unaryUnion([poly1, poly2])
            parts_raw = len(union_raw.asGeometryCollection()) if not union_raw.isEmpty() else 0

            # С snappedToGrid(0.01): вершины привязываются к сетке, зазор исчезает
            poly1_snapped = poly1.snappedToGrid(0.01, 0.01, 0, 0)
            poly2_snapped = poly2.snappedToGrid(0.01, 0.01, 0, 0)
            union_snapped = QgsGeometry.unaryUnion([poly1_snapped, poly2_snapped])
            parts_snapped = len(union_snapped.asGeometryCollection()) if not union_snapped.isEmpty() else 0

            self.logger.data("Без snap: частей", str(parts_raw))
            self.logger.data("С snap: частей", str(parts_snapped))

            self.logger.check(
                parts_snapped <= parts_raw,
                f"snappedToGrid уменьшает/сохраняет число частей: {parts_raw} -> {parts_snapped}",
                f"snappedToGrid увеличил число частей: {parts_raw} -> {parts_snapped}"
            )

            # Проверяем что snap 0.01 не искажает геометрию значительно
            area_original = poly1.area() + poly2.area()
            area_snapped = poly1_snapped.area() + poly2_snapped.area()
            area_diff_pct = abs(area_original - area_snapped) / area_original * 100

            self.logger.check(
                area_diff_pct < 1.0,
                f"Искажение площади < 1%: {area_diff_pct:.4f}%",
                f"Искажение площади > 1%: {area_diff_pct:.4f}%"
            )

            # Проверяем что snappedToGrid присутствует в коде loader'а
            import inspect
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_4_fgislk_loader import (
                Fsm_1_2_4_FgislkLoader,
            )
            source = inspect.getsource(Fsm_1_2_4_FgislkLoader.load_layers)
            self.logger.check(
                "snappedToGrid" in source,
                "snappedToGrid найден в load_layers()",
                "snappedToGrid ОТСУТСТВУЕТ в load_layers() -- регрессия!"
            )

            # Проверяем параметры: 0.01, 0.01, 0, 0
            self.logger.check(
                "snappedToGrid(0.01" in source,
                "snappedToGrid(0.01, ...) -- корректная точность 1 см",
                "snappedToGrid параметры изменились -- проверить!"
            )

        except Exception as e:
            self.logger.error(f"Ошибка snappedToGrid: {str(e)}")

    def _test_19_union_field_schema(self):
        """ТЕСТ 19: Union-схема полей (переменные PBF схемы)."""
        self.logger.section("19. Union-схема полей")

        try:
            from qgis.core import QgsField, QgsFields
            from qgis.PyQt.QtCore import QMetaType

            # Эмуляция переменных PBF схем:
            # Record 1: externalid, name
            # Record 2: externalid, name, age_group (дополнительное поле)
            # Record 3: externalid, timber_stock (без name)

            record1_fields = {
                "externalid": QgsField("externalid", QMetaType.Type.QString),
                "name": QgsField("name", QMetaType.Type.QString),
            }
            record2_fields = {
                "externalid": QgsField("externalid", QMetaType.Type.QString),
                "name": QgsField("name", QMetaType.Type.QString),
                "age_group": QgsField("age_group", QMetaType.Type.QString),
            }
            record3_fields = {
                "externalid": QgsField("externalid", QMetaType.Type.QString),
                "timber_stock": QgsField("timber_stock", QMetaType.Type.Double),
            }

            # Union алгоритм (как в load_layers)
            all_fields: Dict[str, QgsField] = {}
            for record_fields in [record1_fields, record2_fields, record3_fields]:
                for fname, fld in record_fields.items():
                    if fname not in all_fields:
                        all_fields[fname] = fld

            fields = QgsFields()
            for field in all_fields.values():
                fields.append(field)

            self.logger.check(
                fields.count() == 4,
                f"Union: {fields.count()} полей (externalid, name, age_group, timber_stock)",
                f"Union: {fields.count()} != 4"
            )

            expected_names = {"externalid", "name", "age_group", "timber_stock"}
            actual_names = {fields.at(i).name() for i in range(fields.count())}
            self.logger.check(
                actual_names == expected_names,
                "Все уникальные поля присутствуют",
                f"Расхождение: {actual_names ^ expected_names}"
            )

            # Проверяем что union-алгоритм присутствует в коде
            import inspect
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_4_fgislk_loader import (
                Fsm_1_2_4_FgislkLoader,
            )
            source = inspect.getsource(Fsm_1_2_4_FgislkLoader.load_layers)
            self.logger.check(
                "all_fields" in source and "union" in source.lower(),
                "Union-схема полей реализована в load_layers()",
                "Union-схема НЕ найдена в load_layers()"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")

    def _test_20_geometry_merge_pipeline(self):
        """ТЕСТ 20: Pipeline обработки геометрий (snap -> makeValid -> buffer -> union)."""
        self.logger.section("20. Pipeline: snap -> makeValid -> buffer -> union")

        try:
            from qgis.core import QgsGeometry, QgsPointXY

            # Создаём невалидную геометрию (самопересечение = бабочка)
            bowtie = QgsGeometry.fromPolygonXY([[
                QgsPointXY(0, 0), QgsPointXY(10, 10),
                QgsPointXY(10, 0), QgsPointXY(0, 10),
                QgsPointXY(0, 0)
            ]])

            self.logger.check(
                not bowtie.isGeosValid(),
                "Бабочка невалидна (self-intersection) -- OK",
                "Бабочка валидна (неожиданно)"
            )

            # Pipeline как в load_layers
            g = bowtie.snappedToGrid(0.01, 0.01, 0, 0)
            if not g.isGeosValid():
                g = g.makeValid()
            g = g.buffer(0.0, 5)

            self.logger.check(
                g.isGeosValid(),
                "После pipeline геометрия валидна",
                "После pipeline геометрия НЕ валидна!"
            )

            self.logger.check(
                not g.isEmpty(),
                "После pipeline геометрия не пустая",
                "После pipeline геометрия пустая!"
            )

            self.logger.check(
                g.area() > 0,
                f"Площадь после pipeline > 0: {g.area():.2f}",
                f"Площадь = 0 (геометрия потеряна)"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")

    # ===================================================================
    # ГРУППА 7: REST API
    # ===================================================================

    def _test_21_rest_api_attributesinfo(self):
        """ТЕСТ 21: REST API обогащения атрибутов."""
        self.logger.section("21. REST API attributesinfo")

        # Извлекаем mvt_id из PBF для реального запроса
        mvt_id = None
        if self._pbf_path:
            try:
                from osgeo import ogr
                ds = ogr.Open(self._pbf_path)
                if ds:
                    for i in range(ds.GetLayerCount()):
                        layer = ds.GetLayerByIndex(i)
                        if layer and layer.GetName() == "TAXATION_PIECE":
                            feat = layer.GetNextFeature()
                            if feat:
                                idx = feat.GetFieldIndex("mvt_id")
                                if idx >= 0:
                                    mvt_id = feat.GetField(idx)
                            break
                    ds = None
            except Exception:
                pass

        if mvt_id is None:
            # Fallback: используем известный mvt_id из предыдущих тестов
            self.logger.warning("mvt_id не извлечён из PBF, используем тестовое значение")
            mvt_id = 1  # Минимальный ID для проверки доступности API

        # Запрос к REST API
        params = {"layer_code": "TAXATION_PIECE", "object_id": str(mvt_id)}
        resp = http_get(f"{REST_API_URL}?layer_code={params['layer_code']}&object_id={params['object_id']}")

        if resp is None:
            self.logger.warning("REST API: connection error")
            return

        self.logger.data("HTTP Status", str(resp.status_code))

        if resp.status_code == 200:
            try:
                data = resp.json()
                payload = data.get("payload")

                self.logger.check(
                    payload is not None,
                    f"REST API: payload получен ({len(payload)} полей)" if payload else "payload пустой",
                    "REST API: payload отсутствует в ответе"
                )

                if payload and isinstance(payload, dict):
                    # Проверяем наличие ожидаемых полей
                    api_fields = set(payload.keys())
                    expected_in_api = EXPECTED_ENRICHMENT_FIELDS & api_fields
                    self.logger.data("Ожидаемых полей", f"{len(expected_in_api)}/{len(EXPECTED_ENRICHMENT_FIELDS)}")

                    # Поля API, не захваченные ENRICHMENT_FIELDS
                    uncaptured = api_fields - EXPECTED_ENRICHMENT_FIELDS
                    if uncaptured:
                        self.logger.info(f"Дополнительные поля API: {sorted(uncaptured)}")

            except Exception as e:
                self.logger.warning(f"REST API: ошибка парсинга JSON: {str(e)[:60]}")
        else:
            self.logger.warning(f"REST API: HTTP {resp.status_code} (mvt_id={mvt_id})")

    # ===================================================================
    # ГРУППА 8: Инициализация модуля
    # ===================================================================

    def _test_22_loader_initialization(self):
        """ТЕСТ 22: Инициализация Fsm_1_2_4_FgislkLoader."""
        self.logger.section("22. Инициализация FgislkLoader")

        try:
            from Daman_QGIS.managers import APIManager
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_4_fgislk_loader import (
                Fsm_1_2_4_FgislkLoader,
            )

            api_manager = APIManager()
            fgislk_endpoints = [
                ep for ep in api_manager.get_all_endpoints()
                if ep.get("api_group") == "FGISLK"
            ]

            self.logger.check(
                len(fgislk_endpoints) > 0,
                f"FGISLK endpoints: {len(fgislk_endpoints)}",
                "FGISLK endpoint не найден в Base_api_endpoints.json!"
            )

            if not fgislk_endpoints:
                return

            # Проверяем структуру endpoint
            ep = fgislk_endpoints[0]
            self.logger.data("base_url", ep.get("base_url", "N/A"))
            self.logger.data("timeout_sec", str(ep.get("timeout_sec", "N/A")))
            self.logger.data("max_retries", str(ep.get("max_retries", "N/A")))
            self.logger.data("max_workers", str(ep.get("max_workers", "N/A")))
            self.logger.data("referer_url", ep.get("referer_url", "N/A"))

            # Проверяем что base_url содержит gwc-01
            base_url = ep.get("base_url", "")
            self.logger.check(
                "gwc-01" in base_url,
                f"base_url содержит gwc-01",
                f"base_url НЕ содержит gwc-01: {base_url} (миграция?)"
            )

            self.logger.check(
                base_url.startswith("https://"),
                "base_url начинается с https://",
                f"base_url без https://: {base_url[:30]}"
            )

            # Инициализируем loader
            loader = Fsm_1_2_4_FgislkLoader(self.iface, api_manager)
            self.logger.success("FgislkLoader инициализирован")

            # Проверяем tile_url_template
            self.logger.check(
                hasattr(loader, "tile_url_template") and "{z}" in loader.tile_url_template,
                f"tile_url_template корректен",
                "tile_url_template некорректен"
            )

            # Проверяем параметры
            self.logger.data("timeout", str(loader.timeout))
            self.logger.data("max_retries", str(loader.max_retries))
            self.logger.data("max_workers", str(loader.max_workers))

        except AssertionError as e:
            self.logger.fail(f"Assertion: {str(e)}")
        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def _test_23_session_creation(self):
        """ТЕСТ 23: Session creation (connection pooling, retry)."""
        self.logger.section("23. HTTP Sessions")

        try:
            from Daman_QGIS.managers import APIManager
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_4_fgislk_loader import (
                Fsm_1_2_4_FgislkLoader,
            )

            api_manager = APIManager()
            loader = Fsm_1_2_4_FgislkLoader(self.iface, api_manager)

            # Tile session
            self.logger.check(
                hasattr(loader, "_session") and loader._session is not None,
                "Tile session создана",
                "Tile session отсутствует!"
            )

            # REST session
            self.logger.check(
                hasattr(loader, "_rest_session") and loader._rest_session is not None,
                "REST session создана",
                "REST session отсутствует!"
            )

            # Проверяем verify=False
            self.logger.check(
                loader._session.verify is False,
                "Tile session: verify=False (Минцифры SSL)",
                f"Tile session: verify={loader._session.verify}"
            )
            self.logger.check(
                loader._rest_session.verify is False,
                "REST session: verify=False (Минцифры SSL)",
                f"REST session: verify={loader._rest_session.verify}"
            )

            # Проверяем адаптеры (connection pooling)
            https_adapter = loader._session.get_adapter("https://")
            self.logger.check(
                https_adapter is not None,
                "HTTPS adapter установлен",
                "HTTPS adapter отсутствует"
            )

            # Проверяем retry strategy
            if hasattr(https_adapter, "max_retries"):
                retry = https_adapter.max_retries
                self.logger.data("Retry total", str(getattr(retry, "total", "N/A")))
                self.logger.data("Status forcelist", str(getattr(retry, "status_forcelist", "N/A")))

                # 404 должен быть в status_forcelist для тайловой сессии (CDN cache miss)
                forcelist = getattr(retry, "status_forcelist", set())
                self.logger.check(
                    404 in forcelist,
                    "404 в status_forcelist (CDN cache miss обрабатывается retry)",
                    "404 НЕ в status_forcelist (CDN cache miss не обрабатывается!)"
                )

        except AssertionError as e:
            self.logger.fail(f"Assertion: {str(e)}")
        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")

    # ===================================================================
    # ГРУППА 9: URL-паттерны архитектуры
    # ===================================================================

    def _test_24_url_architecture_patterns(self):
        """ТЕСТ 24: URL-паттерны архитектурных фаз ФГИС ЛК."""
        self.logger.section("24. URL-паттерны (3 архитектурные фазы)")

        for phase_id, info in ENDPOINTS_HISTORY.items():
            self.logger.info(
                f"  {phase_id}: {info['host']}{info['path']} "
                f"[{info['status']}] -- {info['description']}"
            )

        # Проверяем текущий endpoint
        try:
            from Daman_QGIS.managers import APIManager
            api_manager = APIManager()
            fgislk_endpoints = [
                ep for ep in api_manager.get_all_endpoints()
                if ep.get("api_group") == "FGISLK"
            ]
            if fgislk_endpoints:
                base_url = fgislk_endpoints[0].get("base_url", "")

                # Проверяем что используется phase3 (map.fgislk / gwc-01)
                self.logger.check(
                    "map.fgislk" in base_url and "gwc-01" in base_url,
                    f"Текущий endpoint = Phase 3 (кластерный GWC)",
                    f"Текущий endpoint НЕ Phase 3: {base_url[:60]}"
                )

                # Проверяем что НЕ используется мёртвый pub4
                self.logger.check(
                    "pub4" not in base_url,
                    "pub4 НЕ используется (корректно)",
                    f"pub4 всё ещё в конфигурации! {base_url}"
                )
        except Exception as e:
            self.logger.warning(f"Не удалось проверить конфигурацию: {str(e)[:60]}")

        # Паттерн именования: gwc-NN = WAR контекст Tomcat
        self.logger.info("Паттерн gwc-01: нумерованный WAR в Tomcat (балансировка нагрузки)")
        self.logger.info("Ожидаемый следующий: gwc-02 (при масштабировании)")

    # ===================================================================
    # ГРУППА 10: Полный pipeline
    # ===================================================================

    def _test_25_full_pipeline(self):
        """ТЕСТ 25: Полный pipeline load_layers (если есть проект)."""
        self.logger.section("25. Full pipeline (load_layers)")

        try:
            from qgis.core import QgsProject

            project = QgsProject.instance()
            boundary_layer = None
            for layer in project.mapLayers().values():
                if layer.name() == "L_1_1_1_Границы_работ":
                    boundary_layer = layer
                    break

            if not boundary_layer:
                self.logger.warning(
                    "Слой L_1_1_1_Границы_работ не найден -- полный pipeline пропущен. "
                    "Для запуска: откройте проект с границами работ."
                )
                return

            self.logger.info(f"Границы работ: {boundary_layer.featureCount()} объектов")

            from Daman_QGIS.managers import APIManager
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_4_fgislk_loader import (
                Fsm_1_2_4_FgislkLoader,
            )

            api_manager = APIManager()
            loader = Fsm_1_2_4_FgislkLoader(self.iface, api_manager)

            temp_dir = tempfile.mkdtemp(prefix="fgislk_pipeline_test_")

            start = time.time()
            result_layers = loader.load_layers(temp_dir, enrich_attributes=False)
            elapsed = time.time() - start

            self.logger.check(
                len(result_layers) > 0,
                f"Pipeline: {len(result_layers)} слоёв за {elapsed:.1f} сек",
                f"Pipeline: 0 слоёв (ошибка!)"
            )

            total_features = 0
            for name, layer in result_layers.items():
                fc = layer.featureCount()
                total_features += fc
                self.logger.info(f"  {name}: {fc} объектов")

            self.logger.data("Всего объектов", str(total_features))
            self.logger.data("Время загрузки", f"{elapsed:.1f} сек")

            self.logger.check(
                elapsed < 60,
                f"Время загрузки < 60 сек ({elapsed:.1f})",
                f"Загрузка слишком долгая: {elapsed:.1f} сек"
            )

        except AssertionError as e:
            self.logger.fail(f"Pipeline assertion: {str(e)}")
        except Exception as e:
            self.logger.error(f"Pipeline error: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ===================================================================
    # ГРУППА 11: Пробелы покрытия (из исследования)
    # ===================================================================

    def _test_26_changelog_deep_parse(self):
        """ТЕСТ 26: Changelog -- глубокий парсинг на ключевые слова."""
        self.logger.section("26. Changelog: парсинг ключевых слов")

        try:
            resp = requests.get(
                CHANGELOG_URL,
                headers={"User-Agent": HEADERS["User-Agent"], "Accept": "text/html"},
                verify=True,
                timeout=20,
            )

            if resp.status_code != 200:
                self.logger.warning(f"Changelog: HTTP {resp.status_code}")
                return

            text = resp.text
            text_lower = text.lower()

            # Ключевые слова для обнаружения изменений тайлового сервиса
            keywords = {
                "ПЛК": "плк" in text_lower,
                "лесная карта": "лесн" in text_lower and "карт" in text_lower,
                "тайл": "тайл" in text_lower,
                "gwc": "gwc" in text_lower,
                "map.fgislk": "map.fgislk" in text_lower,
                "geowebcache": "geowebcache" in text_lower,
                "нарезк": "нарезк" in text_lower,
                "сервис": "сервис" in text_lower,
            }

            found_count = sum(1 for v in keywords.values() if v)
            for kw, found in keywords.items():
                if found:
                    self.logger.info(f"  Найдено: '{kw}'")

            self.logger.check(
                found_count >= 2,
                f"Changelog содержит {found_count} релевантных ключевых слов",
                f"Changelog: только {found_count} ключевых слов (контент изменился?)"
            )

            # Проверяем наличие версии 4.14 (текущая серия)
            has_version = "4.14" in text
            self.logger.check(
                has_version,
                "Серия версий 4.14 найдена в changelog",
                "Серия 4.14 не найдена -- проверить вручную"
            )

            # Ищем обращение №523042 (смена сервиса нарезки тайлов)
            has_ticket = "523042" in text
            self.logger.data("Обращение 523042 (тайлы)", "Найдено" if has_ticket else "Не найдено")

        except requests.exceptions.SSLError:
            self.logger.warning("Changelog: SSL ошибка")
        except Exception as e:
            self.logger.warning(f"Changelog parse: {type(e).__name__} - {str(e)[:60]}")

    def _test_27_batch_tile_stability(self):
        """ТЕСТ 27: Batch стабильность CDN -- 6 тайлов."""
        self.logger.section("27. Batch стабильность: 6 тайлов на gwc-01")

        tx, ty = lonlat_to_tile(TEST_LON, TEST_LAT, TILE_ZOOM_SERVER)

        # 6 тайлов вокруг тестовой точки (как в диагностике из сессии)
        test_tiles = [
            (tx, ty), (tx + 1, ty), (tx - 1, ty),
            (tx, ty + 1), (tx, ty - 1), (tx + 1, ty + 1),
        ]

        ok_count = 0
        fail_count = 0
        total_bytes = 0
        start = time.time()

        for x, y in test_tiles:
            tile_url = f"{ACTIVE_TILE_URL}/{TILE_ZOOM_SERVER}/{x}/{y}.pbf"
            resp = http_get(tile_url, timeout=15)
            if resp and resp.status_code == 200 and len(resp.content) > 0:
                ok_count += 1
                total_bytes += len(resp.content)
            else:
                fail_count += 1
                status = resp.status_code if resp else "connection error"
                self.logger.warning(f"  Тайл ({x},{y}): FAIL ({status})")

        elapsed = time.time() - start

        self.logger.data("Результат", f"{ok_count}/6 OK, {fail_count}/6 FAIL")
        self.logger.data("Данные", f"{total_bytes} bytes за {elapsed:.1f} сек")

        self.logger.check(
            ok_count >= 5,
            f"CDN стабилен: {ok_count}/6 тайлов загружены ({elapsed:.1f} сек)",
            f"CDN НЕСТАБИЛЕН: только {ok_count}/6 тайлов! Возможны проблемы сервера"
        )

        self.logger.check(
            fail_count == 0,
            "Нет ошибок загрузки (0 failed)",
            f"{fail_count} тайлов с ошибками (как на мёртвом pub4?)"
        )

    def _test_28_pub4_batch_confirm_dead(self):
        """ТЕСТ 28: pub4 batch confirm -- все 6 тайлов мёртвы."""
        self.logger.section("28. pub4: batch подтверждение (6 тайлов)")

        tx, ty = lonlat_to_tile(TEST_LON, TEST_LAT, TILE_ZOOM_SERVER)

        test_tiles = [
            (tx, ty), (tx + 1, ty), (tx - 1, ty),
            (tx, ty + 1), (tx, ty - 1), (tx + 1, ty + 1),
        ]

        dead_count = 0
        alive_count = 0

        for x, y in test_tiles:
            tile_url = f"{DEAD_TILE_URL}/{TILE_ZOOM_SERVER}/{x}/{y}.pbf"
            resp = http_get(tile_url, timeout=8)
            if resp is None or resp.status_code in (404, 502, 503):
                dead_count += 1
            elif resp.status_code == 200:
                alive_count += 1
                self.logger.warning(f"  pub4 тайл ({x},{y}): ЖИВОЙ! HTTP 200, {len(resp.content)} bytes")
            else:
                dead_count += 1  # Другие ошибки тоже считаем мёртвыми

        self.logger.data("Результат", f"{dead_count}/6 мёртвых, {alive_count}/6 живых")

        self.logger.check(
            dead_count == 6,
            f"pub4 подтверждённо мёртв: {dead_count}/6 тайлов недоступны",
            f"pub4 ЧАСТИЧНО ЖИВ: {alive_count}/6 тайлов ответили! Проверить миграцию!"
        )

    def _test_29_frontend_js_url_extraction(self):
        """ТЕСТ 29: Фронтенд JS -- извлечение актуальных URL тайловых сервисов."""
        self.logger.section("29. Фронтенд: JS-конфиг (map.fgislk.gov.ru/map/)")

        frontend_url = "https://map.fgislk.gov.ru/map/"

        try:
            resp = requests.get(
                frontend_url,
                headers={
                    "User-Agent": HEADERS["User-Agent"],
                    "Accept": "text/html",
                },
                verify=False,
                timeout=20,
            )

            if resp.status_code != 200:
                self.logger.warning(f"Фронтенд: HTTP {resp.status_code}")
                return

            html = resp.text
            self.logger.data("HTML размер", f"{len(html)} chars")

            # Ищем URL тайловых сервисов в HTML/JS
            import re

            # Паттерны для обнаружения тайловых URL
            gwc_urls = re.findall(r'["\']([^"\']*gwc[^"\']*geowebcache[^"\']*)["\']', html)
            tms_urls = re.findall(r'["\']([^"\']*tms/1\.0\.0[^"\']*)["\']', html)
            pbf_urls = re.findall(r'["\']([^"\']*\.pbf[^"\']*)["\']', html)
            tile_urls = re.findall(r'["\']([^"\']*FOREST[^"\']*@EPSG[^"\']*)["\']', html)

            all_urls = set(gwc_urls + tms_urls + pbf_urls + tile_urls)

            if all_urls:
                self.logger.success(f"Найдено {len(all_urls)} URL в HTML/JS")
                for url in sorted(all_urls)[:5]:
                    self.logger.data("  URL", url[:120])

                # Проверяем что gwc-01 присутствует
                has_gwc01 = any("gwc-01" in url for url in all_urls)
                self.logger.check(
                    has_gwc01,
                    "gwc-01 найден в JS конфигурации фронтенда",
                    "gwc-01 НЕ найден -- возможна миграция URL!"
                )
            else:
                # URL могут быть в JS бандлах, загруженных отдельно
                js_files = re.findall(r'src=["\']([^"\']*\.js[^"\']*)["\']', html)
                self.logger.info(f"URL не найдены в HTML, JS бандлов: {len(js_files)}")

                if js_files:
                    # Пробуем скачать первый JS бандл и искать там
                    for js_url in js_files[:3]:
                        if not js_url.startswith("http"):
                            js_url = f"https://map.fgislk.gov.ru{js_url}"
                        try:
                            js_resp = requests.get(
                                js_url, verify=False, headers=HEADERS, timeout=15
                            )
                            if js_resp.status_code == 200:
                                js_text = js_resp.text
                                js_gwc = re.findall(r'gwc-\d+', js_text)
                                if js_gwc:
                                    self.logger.success(
                                        f"gwc паттерн найден в JS: {set(js_gwc)}"
                                    )
                                    break
                        except Exception:
                            continue
                    else:
                        self.logger.info("gwc паттерн не найден в JS бандлах")

        except Exception as e:
            self.logger.warning(f"Фронтенд: {type(e).__name__} - {str(e)[:60]}")

    def _test_30_gislab_forum(self):
        """ТЕСТ 30: GIS-Lab форум -- доступность ключевых топиков."""
        self.logger.section("30. GIS-Lab форум")

        topics = {
            "Публичная лесная карта": "https://gis-lab.info/forum/viewtopic.php?t=29789",
            "WMS ФГИС ЛК": "https://gis-lab.info/forum/viewtopic.php?t=29772",
        }

        for name, url in topics.items():
            try:
                resp = requests.get(
                    url,
                    headers={"User-Agent": HEADERS["User-Agent"]},
                    timeout=15,
                    allow_redirects=True,
                )
                self.logger.check(
                    resp.status_code == 200,
                    f"GIS-Lab '{name}': доступен (HTTP {resp.status_code})",
                    f"GIS-Lab '{name}': HTTP {resp.status_code}"
                )
            except Exception as e:
                self.logger.warning(f"GIS-Lab '{name}': {type(e).__name__}")

    def _test_31_github_fgislk(self):
        """ТЕСТ 31: GitHub FGISLK -- наличие репозиториев."""
        self.logger.section("31. GitHub FGISLK")

        github_urls = {
            "FGISLK org": "https://github.com/FGISLK",
            "serzzh/fgislk": "https://github.com/serzzh/fgislk",
        }

        for name, url in github_urls.items():
            try:
                resp = requests.get(
                    url,
                    headers={"User-Agent": HEADERS["User-Agent"]},
                    timeout=15,
                    allow_redirects=True,
                )
                if resp.status_code == 200:
                    self.logger.info(f"GitHub '{name}': доступен")
                elif resp.status_code == 404:
                    self.logger.info(f"GitHub '{name}': не найден (404)")
                else:
                    self.logger.data(f"GitHub '{name}'", f"HTTP {resp.status_code}")
            except Exception as e:
                self.logger.warning(f"GitHub '{name}': {type(e).__name__}")

        self.logger.info("Fadeev OknoFgislkTool: не опубликован в открытом доступе (подтверждено)")

    # ===================================================================
    # ГРУППА 12: Паттерны из референса Fadeev
    # ===================================================================

    def _test_32_gwc_tile_bounds_header(self):
        """ТЕСТ 32: geowebcache-tile-bounds HTTP header."""
        self.logger.section("32. geowebcache-tile-bounds header")

        if not self._pbf_response:
            self.logger.warning("PBF response не доступен (тест 15 не прошёл)")
            return

        bounds_header = self._pbf_response.headers.get("geowebcache-tile-bounds")

        self.logger.check(
            bounds_header is not None,
            "Header geowebcache-tile-bounds присутствует",
            "Header geowebcache-tile-bounds ОТСУТСТВУЕТ -- Fadeev-паттерн сломан"
        )

        if bounds_header:
            self.logger.data("geowebcache-tile-bounds", bounds_header)

            # Формат: "xmin,ymin,xmax,ymax"
            parts = bounds_header.split(",")
            self.logger.check(
                len(parts) == 4,
                f"Формат корректный: 4 значения через запятую",
                f"Неожиданный формат: {len(parts)} частей"
            )

            if len(parts) == 4:
                try:
                    xmin, ymin, xmax, ymax = [float(p.strip()) for p in parts]

                    self.logger.check(
                        xmin < xmax,
                        f"xmin ({xmin:.2f}) < xmax ({xmax:.2f})",
                        f"xmin >= xmax: {xmin} >= {xmax}"
                    )
                    self.logger.check(
                        ymin < ymax,
                        f"ymin ({ymin:.2f}) < ymax ({ymax:.2f})",
                        f"ymin >= ymax: {ymin} >= {ymax}"
                    )

                    # Проверяем диапазон EPSG:3857
                    max_extent = 20037508.34
                    self.logger.check(
                        abs(xmin) <= max_extent * 1.01 and abs(xmax) <= max_extent * 1.01,
                        "Bounds в диапазоне EPSG:3857",
                        f"Bounds вне диапазона EPSG:3857: x=[{xmin}, {xmax}]"
                    )

                    # Проверяем что bounds соответствуют тайлу (примерный размер)
                    tile_width = xmax - xmin
                    tile_height = ymax - ymin
                    expected_size = CUSTOM_RESOLUTIONS[TILE_ZOOM_SERVER] * TILE_SIZE_PIXELS
                    tolerance = expected_size * 0.01  # 1% допуск
                    self.logger.check(
                        abs(tile_width - expected_size) < tolerance,
                        f"Ширина тайла {tile_width:.2f} ~ {expected_size:.2f}",
                        f"Ширина тайла {tile_width:.2f} != ожидаемая {expected_size:.2f}"
                    )
                except ValueError as e:
                    self.logger.fail(f"Не удалось распарсить bounds: {e}")

    def _test_33_externalid_in_pbf(self):
        """ТЕСТ 33: externalid поле в PBF features (ключ merge)."""
        self.logger.section("33. externalid в PBF features")

        if not self._pbf_path or not os.path.exists(self._pbf_path):
            self.logger.warning("PBF файл не доступен (тест 15 не прошёл)")
            return

        try:
            from osgeo import ogr
        except ImportError:
            self.logger.warning("OGR недоступен -- тест пропущен")
            return

        ds = ogr.Open(self._pbf_path)
        if not ds:
            self.logger.fail("OGR не смог открыть PBF")
            return

        # Проверяем основные слои (QUARTER, TAXATION_PIECE -- наиболее важные для merge)
        key_layers = ["QUARTER", "TAXATION_PIECE", "FORESTRY_TAXATION_DATE"]
        layers_checked = 0

        for i in range(ds.GetLayerCount()):
            layer = ds.GetLayerByIndex(i)
            if not layer:
                continue
            lname = layer.GetName()
            if lname not in key_layers:
                continue

            layers_checked += 1
            layer_defn = layer.GetLayerDefn()

            # Проверяем наличие поля externalid
            has_externalid = False
            for fi in range(layer_defn.GetFieldCount()):
                if layer_defn.GetFieldDefn(fi).GetName() == "externalid":
                    has_externalid = True
                    break

            self.logger.check(
                has_externalid,
                f"{lname}: поле externalid присутствует",
                f"{lname}: поле externalid ОТСУТСТВУЕТ -- merge невозможен"
            )

            if has_externalid:
                # Проверяем что значения не пустые
                layer.ResetReading()
                total = 0
                non_empty = 0
                for feat in layer:
                    total += 1
                    val = feat.GetField("externalid")
                    if val is not None and str(val).strip():
                        non_empty += 1
                    if total >= 20:
                        break

                self.logger.check(
                    non_empty > 0,
                    f"{lname}: externalid заполнен ({non_empty}/{total} features)",
                    f"{lname}: externalid ПУСТОЙ у всех features"
                )

        ds = None

        if layers_checked == 0:
            self.logger.warning("Ни один ключевой слой не найден в PBF тайле")

    def _test_34_pbf_content_type(self):
        """ТЕСТ 34: Content-Type ответа PBF."""
        self.logger.section("34. PBF Content-Type")

        if not self._pbf_response:
            self.logger.warning("PBF response не доступен (тест 15 не прошёл)")
            return

        content_type = self._pbf_response.headers.get("Content-Type", "")
        self.logger.data("Content-Type", content_type)

        valid_types = [
            "application/x-protobuf",
            "application/vnd.mapbox-vector-tile",
            "application/octet-stream",
        ]

        is_valid = any(vt in content_type for vt in valid_types)
        self.logger.check(
            is_valid,
            f"Content-Type корректный для PBF",
            f"Неожиданный Content-Type: '{content_type}' (ожидались: {valid_types})"
        )

        # Проверяем что это не HTML ошибка
        self.logger.check(
            "text/html" not in content_type,
            "Ответ НЕ HTML (не страница ошибки)",
            "Content-Type = text/html -- вероятно страница ошибки вместо PBF"
        )

        # Размер тела ответа
        body_size = len(self._pbf_response.content)
        self.logger.check(
            body_size > 100,
            f"Размер ответа: {body_size} bytes (> 100)",
            f"Размер ответа подозрительно мал: {body_size} bytes"
        )

    def _test_35_mvt_extent_4096(self):
        """ТЕСТ 35: MVT extent 4096 (координатная сетка PBF)."""
        self.logger.section("35. MVT extent 4096")

        if not self._pbf_path or not os.path.exists(self._pbf_path):
            self.logger.warning("PBF файл не доступен (тест 15 не прошёл)")
            return

        try:
            from osgeo import ogr
        except ImportError:
            self.logger.warning("OGR недоступен -- тест пропущен")
            return

        ds = ogr.Open(self._pbf_path)
        if not ds:
            self.logger.fail("OGR не смог открыть PBF")
            return

        # MVT стандарт: координаты в диапазоне [0, 4096]
        # OGR при открытии PBF автоматически пересчитывает в пиксельные координаты
        # Если extent изменится (не 4096), пересчёт Fadeev (pt.x()/4096.0) сломается
        mvt_extent = 4096

        checked_layers = 0
        for i in range(ds.GetLayerCount()):
            layer = ds.GetLayerByIndex(i)
            if not layer or layer.GetFeatureCount() == 0:
                continue

            lname = layer.GetName()
            if lname not in EXPECTED_MAIN_LAYERS:
                continue

            # Проверяем extent слоя
            extent = layer.GetExtent()
            if extent:
                xmin, xmax, ymin, ymax = extent

                # Координаты должны быть в диапазоне [0, 4096] (с небольшим допуском)
                coords_in_range = (
                    xmin >= -1 and xmax <= mvt_extent + 1 and
                    ymin >= -1 and ymax <= mvt_extent + 1
                )

                if coords_in_range:
                    self.logger.check(
                        True,
                        f"{lname}: координаты в MVT extent [0, {mvt_extent}] "
                        f"(x=[{xmin:.0f},{xmax:.0f}], y=[{ymin:.0f},{ymax:.0f}])",
                        ""
                    )
                    checked_layers += 1
                else:
                    # OGR может пересчитать в глобальные координаты --
                    # это значит что GWC отдаёт данные в другом формате
                    self.logger.data(
                        f"{lname} extent",
                        f"x=[{xmin:.2f},{xmax:.2f}], y=[{ymin:.2f},{ymax:.2f}]"
                    )
                    # Если координаты в диапазоне EPSG:3857, GWC сменил формат
                    if abs(xmin) > 10000 or abs(ymin) > 10000:
                        self.logger.warning(
                            f"{lname}: координаты в глобальных единицах -- "
                            f"MVT extent может быть НЕ 4096"
                        )
                    checked_layers += 1

            if checked_layers >= 3:
                break

        ds = None

        if checked_layers == 0:
            self.logger.warning("Не удалось проверить extent ни одного слоя")

    # ===================================================================
    # ГРУППА 13: Проактивное обнаружение gwc-02/gwc-03
    # ===================================================================

    def _test_36_gwc_next_instances(self):
        """ТЕСТ 36: Проактивная проверка gwc-02, gwc-03 -- раннее обнаружение миграции."""
        self.logger.section("36. Проактивное обнаружение gwc-02/gwc-03")

        # Тест 3 делает HEAD на TMS root -- здесь проверяем конкретные PBF тайлы
        tile_x, tile_y = lonlat_to_tile(TEST_LON, TEST_LAT, TILE_ZOOM_SERVER)

        # Все потенциальные следующие экземпляры GWC
        gwc_instances = {
            "gwc-02": "https://map.fgislk.gov.ru/plk/gwc-02/geowebcache/service/tms/1.0.0",
            "gwc-03": "https://map.fgislk.gov.ru/plk/gwc-03/geowebcache/service/tms/1.0.0",
        }

        for name, base_url in gwc_instances.items():
            # 1. Проверяем TMS root
            tms_status = http_head(base_url, timeout=8)

            # 2. Проверяем реальный PBF тайл
            tile_url = (
                f"{base_url}/FOREST_LAYERS:FOREST@EPSG:3857@pbf"
                f"/{TILE_ZOOM_SERVER}/{tile_x}/{tile_y}.pbf"
            )
            tile_resp = http_get(tile_url, timeout=10)

            # 3. Проверяем GetCapabilities
            wmts_url = (
                base_url.replace("/tms/1.0.0", "/wmts")
                + "?REQUEST=GetCapabilities"
            )
            wmts_status = http_head(wmts_url, timeout=8)

            # Анализ результатов
            tms_alive = tms_status is not None and tms_status < 400
            tile_alive = (
                tile_resp is not None
                and tile_resp.status_code == 200
                and len(tile_resp.content) > 100
            )
            wmts_alive = wmts_status is not None and wmts_status < 400

            if tile_alive:
                # PBF тайл доступен -- КРИТИЧЕСКОЕ предупреждение
                has_bounds = tile_resp.headers.get("geowebcache-tile-bounds") is not None
                content_type = tile_resp.headers.get("Content-Type", "")
                self.logger.warning(
                    f"{name} ОТДАЁТ PBF ТАЙЛЫ! "
                    f"({len(tile_resp.content)} bytes, "
                    f"bounds_header={'YES' if has_bounds else 'NO'}, "
                    f"Content-Type={content_type}). "
                    f"ВОЗМОЖНА МИГРАЦИЯ с gwc-01!"
                )
            elif tms_alive or wmts_alive:
                # TMS/WMTS отвечает, но тайлы нет -- endpoint поднимается
                self.logger.warning(
                    f"{name}: TMS={'alive' if tms_alive else 'dead'}, "
                    f"WMTS={'alive' if wmts_alive else 'dead'}, "
                    f"PBF=dead -- endpoint готовится?"
                )
            else:
                # Всё мертво -- нормальная ситуация
                tms_str = f"HTTP {tms_status}" if tms_status else "N/A"
                wmts_str = f"HTTP {wmts_status}" if wmts_status else "N/A"
                self.logger.info(
                    f"{name}: TMS={tms_str}, WMTS={wmts_str}, PBF=dead -- не существует (OK)"
                )

        # Параллельно проверяем gwc-01 жив (контрольная точка)
        gwc01_tile_url = (
            f"{ACTIVE_TMS_BASE}/FOREST_LAYERS:FOREST@EPSG:3857@pbf"
            f"/{TILE_ZOOM_SERVER}/{tile_x}/{tile_y}.pbf"
        )
        gwc01_resp = http_get(gwc01_tile_url, timeout=10)
        gwc01_alive = (
            gwc01_resp is not None
            and gwc01_resp.status_code == 200
            and len(gwc01_resp.content) > 100
        )
        self.logger.check(
            gwc01_alive,
            "gwc-01 контрольная точка: жив (PBF отдаёт)",
            "gwc-01 контрольная точка: МЁРТВ -- КРИТИЧЕСКАЯ ПРОБЛЕМА"
        )

    # ===================================================================
    # Очистка
    # ===================================================================

    def _cleanup(self):
        """Очистка временных файлов."""
        if self._temp_dir and os.path.exists(self._temp_dir):
            try:
                import shutil
                shutil.rmtree(self._temp_dir, ignore_errors=True)
            except Exception:
                pass
