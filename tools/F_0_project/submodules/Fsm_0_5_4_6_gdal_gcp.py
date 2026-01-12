# -*- coding: utf-8 -*-
"""
Fsm_0_5_4_6 - Метод GDAL GCPsToGeoTransform (GdalGcpMethod)

Минимум: 3 точки
Оптимизирует: анализ трансформации через GDAL

Использует GCPsToGeoTransform для расчёта аффинной трансформации.
GDAL обычно доступен в QGIS.
"""

import math
from typing import List, Tuple, Dict

from qgis.core import (
    QgsPointXY, QgsCoordinateTransform, QgsProject
)

from .Fsm_0_5_4_base_method import BaseCalculationMethod, CalculationResult
from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.constants import ELLPS_KRASS, TOWGS84_SK42_PROJ, RMSE_THRESHOLD_OK


class Fsm_0_5_4_6_GdalGcp(BaseCalculationMethod):
    """
    Расчёт аффинной трансформации через GDAL GCPsToGeoTransform.
    Минимум: 3 точки.
    GDAL обычно доступен в QGIS.
    """

    @property
    def name(self) -> str:
        return "GDAL GCP"

    @property
    def method_id(self) -> str:
        return "gdal"

    @property
    def min_points(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "GCPsToGeoTransform из GDAL (анализ трансформации)"

    def is_available(self) -> bool:
        """Проверка доступности GDAL"""
        try:
            from osgeo import gdal
            return True
        except ImportError:
            return False

    def calculate(
        self,
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        base_params: Dict,
        initial_lon_0: float
    ) -> CalculationResult:
        """
        Расчёт через GDAL GCPsToGeoTransform.
        """
        if not self.is_available():
            log_warning("Fsm_0_5_4_6: GDAL не доступен")
            return CalculationResult(
                method_name=self.name,
                method_id=self.method_id,
                lon_0=initial_lon_0,
                x_0=0.0,
                y_0=0.0,
                rmse=float('inf'),
                success=False,
                min_points_required=self.min_points,
                diagnostics={'error': 'GDAL not available'}
            )

        if len(control_points_wgs84) < self.min_points:
            log_warning(f"Fsm_0_5_4_6: Нужно минимум {self.min_points} точек")
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
            from osgeo import gdal

            # Извлекаем параметры
            lat_0 = base_params.get('lat_0', 0.0)
            k_0 = base_params.get('k_0', 1.0)
            ellps_param = base_params.get('ellps_param', ELLPS_KRASS)
            # ГОСТ 32453-2017: параметры преобразования СК-42 -> WGS-84
            towgs84_param = base_params.get('towgs84_param', TOWGS84_SK42_PROJ)

            # Трансформируем точки в МСК
            transform_result = self._create_msk_transform(
                initial_lon_0, lat_0, k_0, ellps_param, towgs84_param
            )

            if transform_result is None:
                log_error("Fsm_0_5_4_6: Невалидная CRS")
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

            _, transform_to_msk = transform_result

            # Получаем точки через общий метод
            obj_points, ref_points = self._transform_points_to_msk(
                control_points_wgs84, transform_to_msk
            )

            # Создание GCP объектов
            gcps = []
            for i, (obj_xy, ref_xy) in enumerate(zip(obj_points, ref_points)):
                gcp = gdal.GCP(
                    ref_xy[0],  # GCPX - целевая X
                    ref_xy[1],  # GCPY - целевая Y
                    0,          # GCPZ
                    obj_xy[0],  # GCPPixel - исходная X
                    obj_xy[1]   # GCPLine - исходная Y
                )
                gcps.append(gcp)

            # Расчет аффинной трансформации
            geotransform = gdal.GCPsToGeoTransform(gcps)

            if geotransform is None:
                log_error("Fsm_0_5_4_6: Не удалось вычислить GeoTransform")
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

            # Извлекаем параметры из GeoTransform
            # GT[0] = x origin, GT[3] = y origin
            # GT[1] = pixel width (scale x), GT[5] = pixel height (scale y)
            # GT[2], GT[4] = rotation
            x_origin = geotransform[0]
            pixel_width = geotransform[1]
            rotation_x = geotransform[2]
            y_origin = geotransform[3]
            rotation_y = geotransform[4]
            pixel_height = geotransform[5]

            # Вычисляем scale и rotation
            scale_x = math.sqrt(pixel_width**2 + rotation_y**2)
            scale_y = math.sqrt(pixel_height**2 + rotation_x**2)
            rotation_rad = math.atan2(rotation_y, pixel_width)
            rotation_deg = math.degrees(rotation_rad)

            scale_avg = (scale_x + scale_y) / 2
            scale_ppm = (scale_avg - 1) * 1e6

            # Корректировка lon_0 на основе поворота (теория сходимости меридианов)
            lon_0_correction = self._calculate_lon0_correction(
                rotation_deg, control_points_wgs84
            )
            corrected_lon_0 = initial_lon_0 + lon_0_correction

            # Корректировка dS
            current_dS = self._extract_dS(towgs84_param)
            dS_correction = -scale_ppm
            corrected_dS = current_dS + dS_correction
            corrected_towgs84 = self._update_towgs84_dS(towgs84_param, corrected_dS)

            # Пересчитываем x_0, y_0
            final_x0, final_y0, final_rmse, errors = self._calc_offset(
                control_points_wgs84, corrected_lon_0, lat_0, k_0,
                ellps_param, corrected_towgs84
            )

            rmse, min_err, max_err = self._get_error_stats(errors)
            success = rmse < RMSE_THRESHOLD_OK

            # Компактный лог
            status = "OK" if success else "WARN"
            log_info(
                f"Fsm_0_5_4_6 [{self.method_id}]: "
                f"lon_0={corrected_lon_0:.4f} x_0={final_x0:.2f} y_0={final_y0:.2f} "
                f"RMSE={rmse:.4f}m [{status}]"
            )
            log_info(
                f"Fsm_0_5_4_6: rotation={rotation_deg:.4f}deg scale={scale_ppm:.2f}ppm"
            )

            return CalculationResult(
                method_name=self.name,
                method_id=self.method_id,
                lon_0=corrected_lon_0,
                x_0=final_x0,
                y_0=final_y0,
                towgs84_param=corrected_towgs84,
                rmse=rmse,
                min_error=min_err,
                max_error=max_err,
                success=success,
                min_points_required=self.min_points,
                diagnostics={
                    'errors': errors,
                    'geotransform': geotransform,
                    'rotation_deg': rotation_deg,
                    'scale_x': scale_x,
                    'scale_y': scale_y,
                    'scale_ppm': scale_ppm,
                    'original_lon_0': initial_lon_0,
                    'original_dS': current_dS
                }
            )

        except Exception as e:
            log_error(f"Fsm_0_5_4_6: Ошибка расчёта: {e}")
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

    # _extract_dS, _update_towgs84_dS, _calc_offset наследуются из BaseCalculationMethod
