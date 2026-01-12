# -*- coding: utf-8 -*-
"""
Fsm_0_5_4_5 - Метод scikit-image AffineTransform (ScikitAffineMethod)

Минимум: 3 точки
Оптимизирует: анализ трансформации через scikit-image

Использует AffineTransform.estimate() для расчёта параметров.
Требует: pip install scikit-image

Зависимости:
- scikit-image >= 0.19.0
- numpy
"""

from typing import List, Tuple, Dict

from qgis.core import (
    QgsPointXY, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsProject
)

from .Fsm_0_5_4_base_method import BaseCalculationMethod, CalculationResult
from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.constants import ELLPS_KRASS, TOWGS84_SK42_PROJ, RMSE_THRESHOLD_OK


class Fsm_0_5_4_5_ScikitAffine(BaseCalculationMethod):
    """
    Аффинная трансформация через scikit-image.
    Минимум: 3 точки.
    Требует внешнюю библиотеку scikit-image.
    """

    @property
    def name(self) -> str:
        return "scikit-image Affine"

    @property
    def method_id(self) -> str:
        return "scikit"

    @property
    def min_points(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "AffineTransform из scikit-image (внешняя библиотека)"

    def is_available(self) -> bool:
        """Проверка доступности библиотеки"""
        try:
            from skimage.transform import AffineTransform
            import numpy as np
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
        Расчёт через scikit-image AffineTransform.
        """
        if not self.is_available():
            log_warning("Fsm_0_5_4_5: scikit-image не доступен")
            return CalculationResult(
                method_name=self.name,
                method_id=self.method_id,
                lon_0=initial_lon_0,
                x_0=0.0,
                y_0=0.0,
                rmse=float('inf'),
                success=False,
                min_points_required=self.min_points,
                diagnostics={'error': 'scikit-image not available'}
            )

        if len(control_points_wgs84) < self.min_points:
            log_warning(f"Fsm_0_5_4_5: Нужно минимум {self.min_points} точек")
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
            from skimage.transform import AffineTransform
            import numpy as np

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
                log_error("Fsm_0_5_4_5: Невалидная CRS")
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

            # Собираем точки через общий метод
            obj_points, ref_points = self._transform_points_to_msk(
                control_points_wgs84, transform_to_msk
            )

            # Конвертируем в формат для scikit-image
            src_points = [[x, y] for x, y in obj_points]
            dst_points = [[x, y] for x, y in ref_points]

            # Конвертируем в numpy массивы
            src = np.array(src_points)
            dst = np.array(dst_points)

            # Оценка трансформации
            tform = AffineTransform()
            success_estimate = tform.estimate(src, dst)

            if not success_estimate:
                log_error("Fsm_0_5_4_5: Не удалось оценить трансформацию")
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

            # Извлекаем параметры (params - матрица 3x3 трансформации)
            params = getattr(tform, 'params', None)
            if params is None:
                log_error("Fsm_0_5_4_5: Не удалось получить параметры трансформации")
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
            scale_x = tform.scale[0] if hasattr(tform, 'scale') else np.sqrt(params[0, 0]**2 + params[1, 0]**2)
            scale_y = tform.scale[1] if hasattr(tform, 'scale') else np.sqrt(params[0, 1]**2 + params[1, 1]**2)
            rotation = tform.rotation if hasattr(tform, 'rotation') else np.arctan2(params[1, 0], params[0, 0])
            translation = tform.translation if hasattr(tform, 'translation') else (params[0, 2], params[1, 2])

            rotation_deg = np.degrees(rotation)
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
                f"Fsm_0_5_4_5 [{self.method_id}]: "
                f"lon_0={corrected_lon_0:.4f} x_0={final_x0:.2f} y_0={final_y0:.2f} "
                f"RMSE={rmse:.4f}m [{status}]"
            )
            log_info(
                f"Fsm_0_5_4_5: rotation={rotation_deg:.4f}deg scale={scale_ppm:.2f}ppm"
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
                    'rotation_deg': rotation_deg,
                    'scale_x': float(scale_x),
                    'scale_y': float(scale_y),
                    'scale_ppm': scale_ppm,
                    'translation': (float(translation[0]), float(translation[1])),
                    'original_lon_0': initial_lon_0,
                    'original_dS': current_dS
                }
            )

        except Exception as e:
            log_error(f"Fsm_0_5_4_5: Ошибка расчёта: {e}")
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
