"""
Msm_41_7: ORSBackend - HTTP клиент OpenRouteService API.

Опциональный backend для M_41: изохроны и маршруты через ORS API.
Используется для валидации результатов локального pipeline и при
отсутствии локальной дорожной сети.

Паттерн: M_39 DaDataGeocodingManager (HTTP POST + QSettings + cache).

Родительский менеджер: M_41_IsochroneTransportManager
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import requests

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
)
from qgis.PyQt.QtCore import QSettings

from Daman_QGIS.constants import (
    ORS_API_URL,
    ORS_PROFILE_MAP,
    ORS_RATE_LIMIT_DELAY,
    ORS_SETTINGS_KEY,
    ORS_TIMEOUT,
)
from Daman_QGIS.utils import log_error, log_info, log_warning

from .Msm_41_4_speed_profiles import IsochroneResult, RouteResult

__all__ = ['Msm_41_7_ORSBackend', 'ORSError']

MODULE_ID = "Msm_41_7"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ORSError(Exception):
    """Базовое исключение ORS API."""


class ORSAuthError(ORSError):
    """Невалидный API ключ (HTTP 401/403)."""


class ORSRateLimitError(ORSError):
    """Превышен лимит запросов (HTTP 429)."""


class ORSServerError(ORSError):
    """Серверная ошибка ORS (HTTP 500+)."""


class ORSTimeoutError(ORSError):
    """Таймаут запроса к ORS."""


# ---------------------------------------------------------------------------
# ORS Backend
# ---------------------------------------------------------------------------

_WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")

_MAX_RETRIES = 3


class Msm_41_7_ORSBackend:
    """
    HTTP клиент OpenRouteService API.

    Предоставляет изохроны и маршруты через ORS, возвращая стандартные
    RouteResult / IsochroneResult для совместимости с M_41 facade.

    Координаты автоматически трансформируются project CRS <-> WGS84.
    """

    def __init__(self) -> None:
        self._api_key: Optional[str] = None
        self._api_url: str = ORS_API_URL
        self._session_cache: dict[str, Any] = {}
        self._last_request_time: float = 0.0

    # --- Public: Configuration ---

    def set_api_key(self, key: str) -> None:
        """Установить и сохранить ORS API ключ."""
        key = key.strip()
        if not key:
            log_warning(f"{MODULE_ID}: Пустой API ключ")
            return
        self._api_key = key
        QSettings().setValue(ORS_SETTINGS_KEY, key)
        log_info(f"{MODULE_ID}: API ключ установлен")

    def load_api_key(self) -> Optional[str]:
        """Загрузить API ключ из QSettings."""
        value = QSettings().value(ORS_SETTINGS_KEY)
        if value:
            self._api_key = str(value)
            return self._api_key
        return None

    def is_available(self) -> bool:
        """Проверка: API ключ задан."""
        return bool(self._api_key)

    def clear_cache(self) -> None:
        """Очистить кэш сессии."""
        count = len(self._session_cache)
        self._session_cache.clear()
        if count > 0:
            log_info(f"{MODULE_ID}: Кэш очищен ({count} записей)")

    # --- Public: Analysis ---

    def isochrone(
        self,
        center: QgsPointXY,
        intervals: list[int],
        profile: str,
        unit: str,
        source_crs: QgsCoordinateReferenceSystem,
    ) -> list[IsochroneResult]:
        """
        Изохроны через ORS API.

        Args:
            center: Центральная точка (в source_crs)
            intervals: Интервалы в секундах (time) или метрах (distance)
            profile: Профиль M_41: 'walk', 'drive', 'fire_truck'
            unit: 'time' или 'distance'
            source_crs: CRS исходных координат

        Returns:
            Список IsochroneResult (geometry в source_crs)

        Raises:
            ORSError: При ошибке API
        """
        cache_key = self._cache_key(
            "iso", center.x(), center.y(), profile, unit, *intervals
        )
        cached = self._session_cache.get(cache_key)
        if cached is not None:
            log_info(f"{MODULE_ID}: Изохроны из кэша")
            return cached

        ors_profile = self._map_profile(profile)
        center_wgs = self._to_wgs84(center, source_crs)

        payload: dict[str, Any] = {
            "locations": [[center_wgs.x(), center_wgs.y()]],
            "range": sorted(intervals),
            "range_type": unit,
            "attributes": ["area"],
        }

        geojson = self._post(f"/v2/isochrones/{ors_profile}", payload)
        results = self._parse_isochrone_response(
            geojson, center, profile, unit, source_crs
        )

        self._session_cache[cache_key] = results
        log_info(
            f"{MODULE_ID}: Получено {len(results)} изохрон "
            f"(profile={ors_profile})"
        )
        return results

    def shortest_route(
        self,
        origin: QgsPointXY,
        destination: QgsPointXY,
        profile: str,
        source_crs: QgsCoordinateReferenceSystem,
    ) -> RouteResult:
        """
        Кратчайший маршрут через ORS API.

        Args:
            origin: Начальная точка (в source_crs)
            destination: Конечная точка (в source_crs)
            profile: Профиль M_41
            source_crs: CRS исходных координат

        Returns:
            RouteResult (geometry в source_crs)

        Raises:
            ORSError: При ошибке API
        """
        cache_key = self._cache_key(
            "route", origin.x(), origin.y(),
            destination.x(), destination.y(), profile
        )
        cached = self._session_cache.get(cache_key)
        if cached is not None:
            log_info(f"{MODULE_ID}: Маршрут из кэша")
            return cached

        ors_profile = self._map_profile(profile)
        origin_wgs = self._to_wgs84(origin, source_crs)
        dest_wgs = self._to_wgs84(destination, source_crs)

        payload: dict[str, Any] = {
            "coordinates": [
                [origin_wgs.x(), origin_wgs.y()],
                [dest_wgs.x(), dest_wgs.y()],
            ],
            "geometry": True,
            "instructions": False,
        }

        geojson = self._post(
            f"/v2/directions/{ors_profile}/geojson", payload
        )
        result = self._parse_route_response(
            geojson, origin, destination, profile, source_crs
        )

        self._session_cache[cache_key] = result
        log_info(
            f"{MODULE_ID}: Маршрут получен "
            f"({result.distance_m:.0f} м, {result.duration_s:.0f} с)"
        )
        return result

    # --- Private: HTTP ---

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        HTTP POST к ORS API с retry и rate limiting.

        Raises:
            ORSAuthError, ORSRateLimitError, ORSServerError, ORSTimeoutError
        """
        if not self._api_key:
            raise ORSAuthError(f"{MODULE_ID}: API ключ не задан")

        url = f"{self._api_url}{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": self._api_key,
        }

        # Rate limiting
        elapsed = time.time() - self._last_request_time
        if elapsed < ORS_RATE_LIMIT_DELAY:
            time.sleep(ORS_RATE_LIMIT_DELAY - elapsed)

        for attempt in range(_MAX_RETRIES):
            try:
                self._last_request_time = time.time()
                response = requests.post(
                    url, json=payload, headers=headers,
                    timeout=ORS_TIMEOUT,
                )

                if response.status_code in (401, 403):
                    raise ORSAuthError(
                        f"{MODULE_ID}: Невалидный API ключ "
                        f"(HTTP {response.status_code})"
                    )

                if response.status_code == 429:
                    if attempt < _MAX_RETRIES - 1:
                        delay = 2 ** (attempt + 1)
                        log_warning(
                            f"{MODULE_ID}: Rate limit ORS, "
                            f"ожидание {delay} сек"
                        )
                        time.sleep(delay)
                        continue
                    raise ORSRateLimitError(
                        f"{MODULE_ID}: Rate limit после {_MAX_RETRIES} попыток"
                    )

                if response.status_code >= 500:
                    if attempt < _MAX_RETRIES - 1:
                        delay = 2 ** attempt
                        log_warning(
                            f"{MODULE_ID}: ORS server error "
                            f"(HTTP {response.status_code}), "
                            f"повтор через {delay} сек"
                        )
                        time.sleep(delay)
                        continue
                    raise ORSServerError(
                        f"{MODULE_ID}: ORS недоступен "
                        f"(HTTP {response.status_code})"
                    )

                if response.status_code >= 400:
                    error_body = response.text[:300]
                    raise ORSError(
                        f"{MODULE_ID}: ORS ошибка "
                        f"(HTTP {response.status_code}): {error_body}"
                    )

                return response.json()

            except requests.ConnectionError:
                if attempt < _MAX_RETRIES - 1:
                    delay = 2 ** attempt
                    log_warning(
                        f"{MODULE_ID}: Ошибка подключения к ORS, "
                        f"повтор через {delay} сек"
                    )
                    time.sleep(delay)
                else:
                    raise ORSServerError(
                        f"{MODULE_ID}: ORS недоступен "
                        "после всех попыток"
                    )

            except requests.Timeout:
                if attempt < _MAX_RETRIES - 1:
                    log_warning(
                        f"{MODULE_ID}: Таймаут ORS, "
                        f"повтор {attempt + 2}/{_MAX_RETRIES}"
                    )
                else:
                    raise ORSTimeoutError(
                        f"{MODULE_ID}: Таймаут ORS "
                        f"после {_MAX_RETRIES} попыток"
                    )

            except ORSError:
                raise

            except requests.RequestException as e:
                raise ORSError(f"{MODULE_ID}: Ошибка запроса к ORS: {e}")

        raise ORSServerError(f"{MODULE_ID}: ORS недоступен")

    # --- Private: Parsing ---

    def _parse_isochrone_response(
        self,
        geojson: dict[str, Any],
        center: QgsPointXY,
        profile: str,
        unit: str,
        target_crs: QgsCoordinateReferenceSystem,
    ) -> list[IsochroneResult]:
        """Парсинг GeoJSON FeatureCollection в список IsochroneResult."""
        results: list[IsochroneResult] = []
        features = geojson.get("features", [])

        for feature in features:
            props = feature.get("properties", {})
            interval = int(props.get("value", 0))

            geom_json = json.dumps(feature.get("geometry", {}))
            geom_wgs = QgsGeometry.fromWkt(
                self._geojson_to_wkt(feature.get("geometry", {}))
            )

            if geom_wgs.isNull() or geom_wgs.isEmpty():
                log_warning(
                    f"{MODULE_ID}: Пустая геометрия изохроны "
                    f"(interval={interval})"
                )
                continue

            geom_local = self._transform_geometry(
                geom_wgs, _WGS84, target_crs
            )
            area = geom_local.area() if not geom_local.isNull() else 0.0

            results.append(IsochroneResult(
                geometry=geom_local,
                interval=interval,
                unit=unit,
                area_sq_m=area,
                profile=profile,
                center=center,
                entry_cost_s=0.0,
                method='ors_api',
            ))

        # ORS возвращает от большего к меньшему, сортируем по interval
        results.sort(key=lambda r: r.interval)
        return results

    def _parse_route_response(
        self,
        geojson: dict[str, Any],
        origin: QgsPointXY,
        destination: QgsPointXY,
        profile: str,
        target_crs: QgsCoordinateReferenceSystem,
    ) -> RouteResult:
        """Парсинг GeoJSON route response в RouteResult."""
        features = geojson.get("features", [])
        if not features:
            return RouteResult(
                geometry=QgsGeometry(),
                distance_m=0.0,
                duration_s=0.0,
                profile=profile,
                origin=origin,
                destination=destination,
                success=False,
                error_message="ORS: Маршрут не найден",
            )

        feature = features[0]
        props = feature.get("properties", {})
        summary = props.get("summary", {})
        distance_m = summary.get("distance", 0.0)
        duration_s = summary.get("duration", 0.0)

        geom_wgs = QgsGeometry.fromWkt(
            self._geojson_to_wkt(feature.get("geometry", {}))
        )
        geom_local = self._transform_geometry(
            geom_wgs, _WGS84, target_crs
        )

        return RouteResult(
            geometry=geom_local,
            distance_m=distance_m,
            duration_s=duration_s,
            profile=profile,
            origin=origin,
            destination=destination,
            entry_cost_s=0.0,
            exit_cost_s=0.0,
            success=True,
            error_message='',
        )

    # --- Private: CRS & Geometry ---

    def _to_wgs84(
        self,
        point: QgsPointXY,
        source_crs: QgsCoordinateReferenceSystem,
    ) -> QgsPointXY:
        """Трансформировать точку в WGS84 (lon, lat)."""
        if source_crs == _WGS84:
            return point
        transform = QgsCoordinateTransform(
            source_crs, _WGS84, QgsProject.instance()
        )
        return transform.transform(point)

    def _transform_geometry(
        self,
        geom: QgsGeometry,
        source_crs: QgsCoordinateReferenceSystem,
        target_crs: QgsCoordinateReferenceSystem,
    ) -> QgsGeometry:
        """Трансформировать геометрию между CRS."""
        if source_crs == target_crs or geom.isNull():
            return geom
        transform = QgsCoordinateTransform(
            source_crs, target_crs, QgsProject.instance()
        )
        geom_copy = QgsGeometry(geom)
        geom_copy.transform(transform)
        return geom_copy

    @staticmethod
    def _geojson_to_wkt(geom_dict: dict[str, Any]) -> str:
        """Конвертировать GeoJSON geometry dict в WKT."""
        geom_type = geom_dict.get("type", "")
        coords = geom_dict.get("coordinates", [])

        if geom_type == "Polygon":
            rings = []
            for ring in coords:
                pts = ", ".join(f"{c[0]} {c[1]}" for c in ring)
                rings.append(f"({pts})")
            return f"POLYGON({', '.join(rings)})"

        if geom_type == "MultiPolygon":
            polygons = []
            for polygon in coords:
                rings = []
                for ring in polygon:
                    pts = ", ".join(f"{c[0]} {c[1]}" for c in ring)
                    rings.append(f"({pts})")
                polygons.append(f"({', '.join(rings)})")
            return f"MULTIPOLYGON({', '.join(polygons)})"

        if geom_type == "LineString":
            pts = ", ".join(f"{c[0]} {c[1]}" for c in coords)
            return f"LINESTRING({pts})"

        if geom_type == "MultiLineString":
            lines = []
            for line in coords:
                pts = ", ".join(f"{c[0]} {c[1]}" for c in line)
                lines.append(f"({pts})")
            return f"MULTILINESTRING({', '.join(lines)})"

        log_warning(
            f"{MODULE_ID}: Неизвестный тип GeoJSON геометрии: {geom_type}"
        )
        return ""

    # --- Private: Utilities ---

    @staticmethod
    def _map_profile(profile: str) -> str:
        """Маппинг профиля M_41 -> ORS API."""
        ors_profile = ORS_PROFILE_MAP.get(profile)
        if not ors_profile:
            log_warning(
                f"{MODULE_ID}: Неизвестный профиль '{profile}', "
                "используется driving-car"
            )
            return 'driving-car'
        return ors_profile

    @staticmethod
    def _cache_key(method: str, *args: Any) -> str:
        """Генерация ключа кэша."""
        parts = [method]
        for arg in args:
            if isinstance(arg, float):
                parts.append(f"{arg:.4f}")
            else:
                parts.append(str(arg))
        return "|".join(parts)
