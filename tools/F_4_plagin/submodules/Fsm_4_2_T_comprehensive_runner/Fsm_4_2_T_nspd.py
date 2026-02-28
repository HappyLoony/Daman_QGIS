# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_nspd - Мониторинг стабильности NSPD API + валидация конфигурации базы

Проверяет:
- Конфигурацию ВСЕХ endpoint'ов в Base_api_endpoints.json (все группы)
- Доступность NSPD API для каждого EGRN_WFS endpoint
- Совпадение состава полей ответа с expected_fields из Base_api_endpoints.json
- Валидность category_id (корректный ответ vs пустой/ошибка)

NETWORK_DEPENDENT: требуется интернет-соединение к nspd.gov.ru

Логика вывода (все через logger.fail для видимости в GUI при LOG_LEVEL_ERROR):
- Конфигурация OK -> logger.success (молчит)
- Конфигурация невалидна -> FAIL с деталями
- Ответ OK + поля совпали -> logger.success (молчит)
- Ответ OK + поля различаются -> FAIL с удалёнными/новыми полями + актуальный состав для Excel
- Нет ответа (timeout/ошибка) -> FAIL "проверить сеть или category_id"
- expected_fields не задан -> FAIL с обнаруженными полями (discovery mode)
"""

import math
import time
from typing import Dict, Any, Optional, Set, List, Tuple

from Daman_QGIS.utils import log_info


class TestNSPD:
    """Мониторинг стабильности NSPD API + валидация конфигурации базы"""

    API_URL = "https://nspd.gov.ru/api/geoportal/v1/intersects?typeIntersect=fullObject"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Origin": "https://nspd.gov.ru",
        "Referer": "https://nspd.gov.ru/map",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }

    REQUEST_TIMEOUT = 30
    DELAY_BETWEEN_REQUESTS = 0.5
    BUFFER_KM = 5.0  # Буфер вокруг тестовой точки (км)

    # Все известные группы endpoint'ов в Base_api_endpoints.json
    KNOWN_GROUPS = [
        'EGRN_WFS', 'EGRN_WMTS', 'OVERPASS',
        'OVERPASS_FALLBACK', 'FGISLK', 'GOOGLE'
    ]

    # Обязательные поля по группам (помимо общих endpoint_id, api_group)
    # base_url -- основной URL, url_template -- шаблон с {base_url} + {z}/{x}/{y}
    GROUP_REQUIRED_FIELDS: Dict[str, List[str]] = {
        'EGRN_WFS': ['category_id', 'test_extent'],
        'EGRN_WMTS': ['base_url', 'url_template'],
        'OVERPASS': ['base_url', 'url_template', 'osm_values'],
        'OVERPASS_FALLBACK': ['base_url', 'url_template'],
        'FGISLK': ['base_url', 'url_template'],
        'GOOGLE': ['base_url', 'url_template'],
    }

    # Группы, где layer_name может быть null (fallback-серверы)
    GROUPS_OPTIONAL_LAYER_NAME = {'OVERPASS_FALLBACK'}

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.api_manager = None
        self.session = None  # requests.Session с cookies НСПД (если авторизован)
        self.egrn_endpoints = []  # EGRN_WFS endpoints with expected_fields + test_extent
        self.discovery_endpoints = []  # EGRN_WFS endpoints without expected_fields (but with test_extent)

    def run_all_tests(self):
        """Entry point for comprehensive runner"""
        self.logger.section("NSPD API: Мониторинг стабильности")

        try:
            if not self._init_config():
                return

            self._validate_database_config()
            self._test_all_endpoints()
            self._run_discovery()

        except Exception as e:
            self.logger.error(f"Fsm_4_2_T_nspd: Критическая ошибка: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------

    def _init_config(self) -> bool:
        """Загрузка APIManager, фильтрация EGRN_WFS endpoints"""
        self.logger.section("1. Инициализация конфигурации")

        # Load APIManager
        try:
            from Daman_QGIS.managers import registry

            self.api_manager = registry.get('M_14')

            if not self.api_manager:
                from Daman_QGIS.managers.infrastructure.M_14_api_manager import APIManager
                self.api_manager = APIManager()

            self.logger.check(
                self.api_manager is not None,
                "M_14 APIManager загружен",
                "M_14 APIManager не доступен!"
            )

            if not self.api_manager:
                return False

        except Exception as e:
            self.logger.error(f"Fsm_4_2_T_nspd: Ошибка загрузки APIManager: {e}")
            return False

        # Separate EGRN_WFS endpoints into monitoring and discovery groups
        egrn_all = self.api_manager.get_endpoints_by_group("EGRN_WFS")
        skipped_no_point = 0
        skipped_no_cat = 0

        for ep in egrn_all:
            cat_id = ep.get('category_id')
            if not cat_id or str(cat_id).strip() in ('null', '-'):
                skipped_no_cat += 1
                continue

            point = self._parse_test_point(ep.get('test_extent'))

            if not point:
                skipped_no_point += 1
                continue

            raw_fields = ep.get('expected_fields')
            parsed = self._parse_fields_string(raw_fields)

            if parsed:
                self.egrn_endpoints.append(ep)
            else:
                self.discovery_endpoints.append(ep)

        log_info(
            f"Fsm_4_2_T_nspd: monitoring={len(self.egrn_endpoints)}, "
            f"discovery={len(self.discovery_endpoints)}, "
            f"no_point={skipped_no_point}, no_cat={skipped_no_cat}"
        )

        self.logger.info(
            f"EGRN_WFS: {len(self.egrn_endpoints)} monitoring, "
            f"{len(self.discovery_endpoints)} discovery, "
            f"{skipped_no_point} без test_extent"
        )

        # Авторизация НСПД: некоторые endpoints (МИНСТРОЙ) требуют cookies
        self._init_nspd_auth()

        return True

    def _init_nspd_auth(self) -> None:
        """Авторизация НСПД для доступа к endpoints, требующим cookies.

        Проверяет M_40: если уже авторизован -- инъецирует cookies в session.
        Если нет -- вызывает M_40.login() (открывает Edge, пользователь
        авторизуется через Госуслуги). Без авторизации МИНСТРОЙ endpoints
        вернут пустой ответ.
        """
        self.logger.section("1.1. Авторизация НСПД")

        try:
            from Daman_QGIS.managers import registry
            nspd_auth = registry.get('M_40')

            if not nspd_auth:
                self.logger.warning(
                    "M_40 NspdAuthManager недоступен. "
                    "МИНСТРОЙ endpoints могут не ответить"
                )
                return

            if not nspd_auth.is_available():
                self.logger.warning(
                    "M_40: Авторизация недоступна (ни Edge, ни QWebEngine). "
                    "МИНСТРОЙ endpoints могут не ответить"
                )
                return

            # Если уже авторизован -- используем существующие cookies
            if nspd_auth.is_authenticated():
                self.logger.success("НСПД: уже авторизован, используем cookies")
            else:
                # Запускаем авторизацию (Edge / QWebEngine диалог)
                self.logger.info(
                    "НСПД: не авторизован. Запуск авторизации..."
                )
                login_ok = nspd_auth.login(parent=self.iface.mainWindow())

                if not login_ok:
                    self.logger.warning(
                        "НСПД: авторизация отменена или не удалась. "
                        "МИНСТРОЙ endpoints могут не ответить"
                    )
                    return

                self.logger.success("НСПД: авторизация успешна")

            # Создаём session с cookies
            import requests
            self.session = requests.Session()
            nspd_auth.inject_cookies(self.session)

            cookie_count = len(self.session.cookies)
            self.logger.info(f"НСПД: {cookie_count} cookies инъецированы в session")

        except Exception as e:
            self.logger.warning(f"НСПД auth: ошибка -- {e}")

    # -------------------------------------------------------------------------
    # Database config validation (all groups, no network)
    # -------------------------------------------------------------------------

    def _validate_database_config(self):
        """Валидация конфигурации ВСЕХ endpoint'ов в Base_api_endpoints.json"""
        self.logger.section("2. Валидация конфигурации Base_api_endpoints")

        all_endpoints = self.api_manager.get_all_endpoints()
        self.logger.info(f"Всего endpoint'ов в базе: {len(all_endpoints)}")

        # Группировка по api_group
        by_group: Dict[str, List[Dict[str, Any]]] = {}
        no_group = []
        for ep in all_endpoints:
            group = ep.get('api_group')
            if not group:
                no_group.append(ep)
                continue
            by_group.setdefault(group, []).append(ep)

        # Endpoint'ы без группы
        for ep in no_group:
            ep_id = ep.get('endpoint_id', '?')
            self.logger.fail(
                f"EP {ep_id}: api_group пуст!"
            )

        # Проверка уникальности endpoint_id
        seen_ids: Dict[Any, str] = {}
        for ep in all_endpoints:
            ep_id = ep.get('endpoint_id')
            layer = ep.get('layer_name', '?')
            if ep_id is None:
                self.logger.fail(f"EP ??? ({layer}): endpoint_id отсутствует!")
            elif ep_id in seen_ids:
                self.logger.fail(
                    f"EP {ep_id}: дублирование endpoint_id! "
                    f"({layer} и {seen_ids[ep_id]})"
                )
            else:
                seen_ids[ep_id] = layer

        # Валидация по группам
        group_summary = []
        for group_name in self.KNOWN_GROUPS:
            endpoints = by_group.pop(group_name, [])
            errors = self._validate_group(group_name, endpoints)
            group_summary.append((group_name, len(endpoints), errors))

        # Неизвестные группы
        for group_name, endpoints in by_group.items():
            self.logger.fail(
                f"Неизвестная группа '{group_name}': {len(endpoints)} endpoint'ов"
            )

        # Сводка
        self.logger.section("2.1. Сводка по группам")
        for group_name, count, errors in group_summary:
            if count == 0:
                self.logger.fail(f"{group_name}: 0 endpoint'ов в базе!")
            elif errors > 0:
                self.logger.fail(
                    f"{group_name}: {count} endpoint'ов, {errors} ошибок конфигурации"
                )
            else:
                self.logger.success(
                    f"{group_name}: {count} endpoint'ов, конфигурация OK"
                )

    def _validate_group(self, group_name: str, endpoints: List[Dict[str, Any]]) -> int:
        """Валидация endpoint'ов одной группы. Возвращает количество ошибок."""
        if not endpoints:
            return 0

        required = self.GROUP_REQUIRED_FIELDS.get(group_name, [])
        errors = 0

        for ep in endpoints:
            ep_id = ep.get('endpoint_id', '?')
            layer = ep.get('layer_name')

            # Общие проверки (layer_name опционален для fallback-групп)
            if not layer and group_name not in self.GROUPS_OPTIONAL_LAYER_NAME:
                self.logger.fail(f"EP {ep_id} ({group_name}): layer_name пуст!")
                errors += 1

            # Группо-специфичные проверки
            for field in required:
                value = ep.get(field)

                if field == 'test_extent':
                    # Для test_extent проверяем парсинг
                    point = self._parse_test_point(value)
                    if not point:
                        self.logger.fail(
                            f"EP {ep_id} ({layer or '?'}): "
                            f"test_extent невалидный или пуст: '{value}'"
                        )
                        errors += 1
                elif not value or str(value).strip() in ('', 'null', '-'):
                    self.logger.fail(
                        f"EP {ep_id} ({layer or '?'}): "
                        f"{field} пуст!"
                    )
                    errors += 1

        return errors

    # -------------------------------------------------------------------------
    # EGRN_WFS endpoint testing (network)
    # -------------------------------------------------------------------------

    def _test_all_endpoints(self):
        """Тестирование endpoints с expected_fields"""
        if not self.egrn_endpoints:
            return

        self.logger.section("3. Проверка полей EGRN_WFS endpoints (monitoring)")

        for ep in self.egrn_endpoints:
            self._test_single_endpoint(ep)
            time.sleep(self.DELAY_BETWEEN_REQUESTS)

    def _test_single_endpoint(self, endpoint: Dict[str, Any]):
        """Тест одного endpoint: запрос -> сравнение полей"""
        ep_id = endpoint.get('endpoint_id')
        cat_id = endpoint.get('category_id')
        cat_name = endpoint.get('category_name', '?')

        # Parse expected fields
        expected = self._parse_fields_string(endpoint.get('expected_fields', ''))
        if not expected:
            return

        # Parse test point for this endpoint
        point = self._parse_test_point(endpoint.get('test_extent'))
        if not point:
            return

        # Send request
        response_data = self._send_request(cat_id, point)

        if response_data is None:
            self.logger.fail(
                f"EP {ep_id} ({cat_name}): Нет ответа. "
                f"Проверить сеть или category_id {cat_id}"
            )
            return

        # Extract features
        features = response_data.get('features', [])

        if not features:
            self.logger.fail(
                f"EP {ep_id} ({cat_name}): 0 объектов в test extent. "
                f"Проверить category_id {cat_id} или выбрать другой extent"
            )
            return

        # Extract actual options keys
        actual = self._extract_options_fields(features)

        if actual is None:
            self.logger.fail(
                f"EP {ep_id} ({cat_name}): Объекты есть, но options отсутствует в properties"
            )
            return

        # Compare
        self._compare_fields(ep_id, cat_name, expected, actual)

    def _run_discovery(self):
        """Discovery mode: показать обнаруженные поля для endpoints без expected_fields"""
        if not self.discovery_endpoints:
            return

        self.logger.section("4. Discovery: EGRN_WFS без expected_fields")

        for ep in self.discovery_endpoints:
            ep_id = ep.get('endpoint_id')
            cat_id = ep.get('category_id')
            cat_name = ep.get('category_name', '?')

            point = self._parse_test_point(ep.get('test_extent'))
            if not point:
                continue

            response_data = self._send_request(cat_id, point)

            if response_data is None:
                self.logger.fail(
                    f"EP {ep_id} ({cat_name}): Нет ответа (cat_id={cat_id}). "
                    f"Проверить сеть или category_id"
                )
                time.sleep(self.DELAY_BETWEEN_REQUESTS)
                continue

            features = response_data.get('features', [])

            if not features:
                self.logger.fail(
                    f"EP {ep_id} ({cat_name}): 0 объектов (cat_id={cat_id}). "
                    f"Проверить category_id или выбрать другой test_extent"
                )
                time.sleep(self.DELAY_BETWEEN_REQUESTS)
                continue

            actual = self._extract_options_fields(features)

            if actual:
                fields_str = ";".join(sorted(actual))
                self.logger.fail(
                    f"EP {ep_id} ({cat_name}): expected_fields пуст. "
                    f"Обнаружено {len(actual)} полей. "
                    f"Внесите в Excel: {fields_str}"
                )
            else:
                self.logger.fail(
                    f"EP {ep_id} ({cat_name}): options отсутствует в ответе API"
                )

            time.sleep(self.DELAY_BETWEEN_REQUESTS)

    # -------------------------------------------------------------------------
    # API communication
    # -------------------------------------------------------------------------

    def _send_request(self, category_id, point: Tuple[float, float]) -> Optional[Dict[str, Any]]:
        """POST запрос к NSPD intersects API"""
        try:
            import requests
            import urllib3
            from urllib3.exceptions import InsecureRequestWarning
            urllib3.disable_warnings(InsecureRequestWarning)

            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_1_egrn_loader import (
                requests_post_with_timeout
            )

            payload = self._build_payload(category_id, point)

            response = requests_post_with_timeout(
                self.API_URL,
                session=self.session,
                json=payload,
                headers=self.HEADERS,
                timeout=self.REQUEST_TIMEOUT,
                verify=False
            )

            if response is None:
                log_info("Fsm_4_2_T_nspd: _send_request timeout (response is None)")
                return None

            if response.status_code != 200:
                log_info(f"Fsm_4_2_T_nspd: HTTP {response.status_code} for cat_id={category_id}: {response.text[:200]}")
                return None

            return response.json()

        except Exception as e:
            log_info(f"Fsm_4_2_T_nspd: Exception for cat_id={category_id}: {e}")
            return None

    def _build_payload(self, category_id, point: Tuple[float, float]) -> Dict[str, Any]:
        """Построить GeoJSON payload: bbox = точка + буфер BUFFER_KM"""
        lon, lat = point
        bbox = self._point_to_bbox(lon, lat, self.BUFFER_KM)
        min_lon, min_lat, max_lon, max_lat = bbox
        return {
            "categories": [{"id": category_id}],
            "geom": {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [min_lon, min_lat],
                            [max_lon, min_lat],
                            [max_lon, max_lat],
                            [min_lon, max_lat],
                            [min_lon, min_lat]
                        ]]
                    },
                    "properties": {}
                }]
            }
        }

    @staticmethod
    def _point_to_bbox(lon: float, lat: float, buffer_km: float) -> Tuple[float, float, float, float]:
        """Построить bbox вокруг точки с буфером в км (WGS-84)"""
        # 1 градус широты ~ 111.32 км (постоянно)
        # 1 градус долготы ~ 111.32 * cos(lat) км
        d_lat = buffer_km / 111.32
        d_lon = buffer_km / (111.32 * math.cos(math.radians(lat)))
        return (lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat)

    # -------------------------------------------------------------------------
    # Field extraction and comparison
    # -------------------------------------------------------------------------

    # Служебные ключи properties (не являются атрибутами объекта)
    _SYSTEM_KEYS = {'interactionId', 'options', 'category', 'categoryId', 'geometry'}

    def _extract_options_fields(self, features: List[Dict]) -> Optional[Set[str]]:
        """Извлечь union ключей атрибутов из всех features.

        Поддерживает два формата ответа NSPD API:
        - options-wrapped (ЕГРН): properties.options.{field}
        - flat (МИНСТРОЙ): properties.{field} напрямую
        """
        all_keys = set()
        found_data = False

        for feature in features:
            props = feature.get('properties', {})
            options = props.get('options')
            if options and isinstance(options, dict):
                found_data = True
                all_keys.update(options.keys())
            else:
                # Flat properties (МИНСТРОЙ): все ключи кроме служебных
                flat_keys = {
                    k for k in props.keys()
                    if k not in self._SYSTEM_KEYS and not k.startswith('_')
                }
                if flat_keys:
                    found_data = True
                    all_keys.update(flat_keys)

        return all_keys if found_data else None

    def _compare_fields(
        self,
        ep_id: int,
        cat_name: str,
        expected: Set[str],
        actual: Set[str]
    ):
        """Сравнение expected vs actual полей"""
        if expected == actual:
            self.logger.success(
                f"EP {ep_id} ({cat_name}): поля совпадают ({len(actual)} полей)"
            )
            return

        removed = expected - actual

        if removed:
            self.logger.fail(
                f"EP {ep_id} ({cat_name}): СТАРЫЕ поля: {sorted(removed)}"
            )

        # Полный текущий состав для copy-paste в Excel
        fields_str = ";".join(sorted(actual))
        self.logger.fail(
            f"EP {ep_id} ({cat_name}): Актуальный состав для Excel: {fields_str}"
        )

    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_fields_string(raw) -> Set[str]:
        """Парсинг строки полей (semicolon-delimited) в set"""
        if not raw or str(raw).strip() in ('', 'null', '-'):
            return set()
        return {f.strip() for f in str(raw).split(';') if f.strip()}

    @staticmethod
    def _parse_test_point(raw) -> Optional[Tuple[float, float]]:
        """Парсинг строки test_extent (lon,lat) в tuple WGS-84"""
        if not raw or str(raw).strip() in ('', 'null', '-'):
            return None

        try:
            parts = str(raw).split(',')
            if len(parts) != 2:
                return None

            lon = float(parts[0].strip())
            lat = float(parts[1].strip())

            if not (-180 <= lon <= 180):
                return None
            if not (-90 <= lat <= 90):
                return None

            return (lon, lat)

        except (ValueError, TypeError):
            return None
