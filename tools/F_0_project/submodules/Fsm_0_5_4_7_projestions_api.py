# -*- coding: utf-8 -*-
"""
Fsm_0_5_4_7 - Метод Projestions API (ProjectionsApiMethod)

Минимум: 1 точка (для определения региона)
Оптимизирует: подбор CRS по региону через онлайн API

Использует API projest.io для подбора подходящих CRS.
Требует интернет-соединение.

API: https://projest.io/ns/api/
"""

from typing import List, Tuple, Dict, Optional

from qgis.core import QgsPointXY

from .Fsm_0_5_4_base_method import BaseCalculationMethod, CalculationResult
from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.constants import ELLPS_KRASS, TOWGS84_SK42_PROJ, RMSE_THRESHOLD_OK


class Fsm_0_5_4_7_ProjectionsApi(BaseCalculationMethod):
    """
    Подбор CRS через внешний API projest.io.
    Требует интернет-соединение.
    Минимум: 1 точка (для определения региона).
    """

    API_URL = "https://projest.io/ns/api/"
    TIMEOUT = 10  # секунд

    @property
    def name(self) -> str:
        return "Projestions API"

    @property
    def method_id(self) -> str:
        return "projestions"

    @property
    def min_points(self) -> int:
        return 1

    @property
    def description(self) -> str:
        return "Онлайн подбор CRS через projest.io API"

    def is_available(self) -> bool:
        """Проверка доступности интернета и API"""
        try:
            import requests
            response = requests.get(self.API_URL, timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def calculate(
        self,
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        base_params: Dict,
        initial_lon_0: float
    ) -> CalculationResult:
        """
        Подбор CRS через Projestions API.
        """
        if not self.is_available():
            log_warning("Fsm_0_5_4_7: Projestions API недоступен")
            return CalculationResult(
                method_name=self.name,
                method_id=self.method_id,
                lon_0=initial_lon_0,
                x_0=0.0,
                y_0=0.0,
                rmse=float('inf'),
                success=False,
                min_points_required=self.min_points,
                diagnostics={'error': 'Projestions API not available'}
            )

        if len(control_points_wgs84) < self.min_points:
            log_warning(f"Fsm_0_5_4_7: Нужно минимум {self.min_points} точек")
            return CalculationResult(
                method_name=self.name,
                method_id=self.method_id,
                lon_0=initial_lon_0,
                x_0=0.0,
                y_0=0.0,
                rmse=float('inf'),
                success=False,
                min_points_required=self.min_points
            )

        try:
            import requests
            import json

            # Извлекаем параметры
            lat_0 = base_params.get('lat_0', 0.0)
            k_0 = base_params.get('k_0', 1.0)
            ellps_param = base_params.get('ellps_param', ELLPS_KRASS)
            # ГОСТ 32453-2017: параметры преобразования СК-42 -> WGS-84
            towgs84_param = base_params.get('towgs84_param', TOWGS84_SK42_PROJ)

            # Формируем bounding box из эталонных точек
            ref_lons = [ref.x() for _, ref in control_points_wgs84]
            ref_lats = [ref.y() for _, ref in control_points_wgs84]

            min_lon = min(ref_lons)
            max_lon = max(ref_lons)
            min_lat = min(ref_lats)
            max_lat = max(ref_lats)

            # Создаём GeoJSON polygon (bounding box)
            if len(control_points_wgs84) == 1:
                # Одна точка - создаём небольшой bbox вокруг неё
                buffer = 0.01  # ~1 км
                geojson = {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [min_lon - buffer, min_lat - buffer],
                            [max_lon + buffer, min_lat - buffer],
                            [max_lon + buffer, max_lat + buffer],
                            [min_lon - buffer, max_lat + buffer],
                            [min_lon - buffer, min_lat - buffer]
                        ]]
                    }
                }
            else:
                # Несколько точек - bounding box
                geojson = {
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
                    }
                }

            # Запрос к API
            params = {
                "geom": json.dumps(geojson),
                "max": 10,
                "sort": "areadiff"
            }

            response = requests.get(self.API_URL, params=params, timeout=self.TIMEOUT)

            if response.status_code != 200:
                log_error(f"Fsm_0_5_4_7: API вернул статус {response.status_code}")
                return CalculationResult(
                    method_name=self.name,
                    method_id=self.method_id,
                    lon_0=initial_lon_0,
                    x_0=0.0,
                    y_0=0.0,
                    rmse=float('inf'),
                    success=False,
                    min_points_required=self.min_points,
                    diagnostics={'error': f'API status {response.status_code}'}
                )

            crs_list = response.json()

            if not crs_list:
                log_warning("Fsm_0_5_4_7: API не вернул CRS")
                return CalculationResult(
                    method_name=self.name,
                    method_id=self.method_id,
                    lon_0=initial_lon_0,
                    x_0=0.0,
                    y_0=0.0,
                    rmse=float('inf'),
                    success=False,
                    min_points_required=self.min_points,
                    diagnostics={'error': 'No CRS returned'}
                )

            # Логируем найденные CRS
            log_info(f"Fsm_0_5_4_7: Найдено {len(crs_list)} CRS для региона")

            # Ищем подходящую МСК
            best_crs = None
            for crs_info in crs_list:
                code = crs_info.get('code', '')
                name = crs_info.get('name', '')

                # Фильтруем - ищем российские МСК
                if 'МСК' in name or 'MSK' in name or 'Pulkovo' in name:
                    best_crs = crs_info
                    break

            if best_crs is None and crs_list:
                best_crs = crs_list[0]  # Берём первую

            # Извлекаем параметры из найденной CRS
            suggested_lon_0 = initial_lon_0
            if best_crs:
                proj4 = best_crs.get('proj4', '')
                if '+lon_0=' in proj4:
                    try:
                        lon_0_str = proj4.split('+lon_0=')[1].split()[0]
                        suggested_lon_0 = float(lon_0_str)
                    except (IndexError, ValueError):
                        pass

            # Вычисляем x_0, y_0 с предложенным lon_0
            final_x0, final_y0, final_rmse, errors = self._calc_offset(
                control_points_wgs84, suggested_lon_0, lat_0, k_0,
                ellps_param, towgs84_param
            )

            rmse, min_err, max_err = self._get_error_stats(errors)
            success = rmse < RMSE_THRESHOLD_OK

            # Компактный лог
            status = "OK" if success else "WARN"
            log_info(
                f"Fsm_0_5_4_7 [{self.method_id}]: "
                f"lon_0={suggested_lon_0:.4f} x_0={final_x0:.2f} y_0={final_y0:.2f} "
                f"RMSE={rmse:.4f}m [{status}]"
            )
            if best_crs:
                log_info(
                    f"Fsm_0_5_4_7: Предложенная CRS: {best_crs.get('code', 'N/A')} - "
                    f"{best_crs.get('name', 'N/A')}"
                )

            return CalculationResult(
                method_name=self.name,
                method_id=self.method_id,
                lon_0=suggested_lon_0,
                x_0=final_x0,
                y_0=final_y0,
                rmse=rmse,
                min_error=min_err,
                max_error=max_err,
                success=success,
                min_points_required=self.min_points,
                diagnostics={
                    'errors': errors,
                    'suggested_crs': best_crs,
                    'all_crs': crs_list[:5],  # Первые 5
                    'bbox': {
                        'min_lon': min_lon, 'max_lon': max_lon,
                        'min_lat': min_lat, 'max_lat': max_lat
                    },
                    'original_lon_0': initial_lon_0
                }
            )

        except Exception as e:
            log_error(f"Fsm_0_5_4_7: Ошибка расчёта: {e}")
            return CalculationResult(
                method_name=self.name,
                method_id=self.method_id,
                lon_0=initial_lon_0,
                x_0=0.0,
                y_0=0.0,
                rmse=float('inf'),
                success=False,
                min_points_required=self.min_points,
                diagnostics={'error': str(e)}
            )

    # _calc_offset наследуется из BaseCalculationMethod
