# -*- coding: utf-8 -*-
"""
Fsm_0_5_4_1 - Метод простого смещения (SimpleOffsetMethod)

Минимум: 1 точка
Оптимизирует: x_0, y_0
lon_0 остаётся фиксированным (initial_lon_0)

Поддерживает два подхода:
- Calibration: трансформация object через исходную СК, x_0/y_0 - коррекция
- LDP: использование RAW координат, x_0/y_0 - полные false easting/northing

Алгоритм (Calibration):
1. WGS84 точки трансформируются в тестовую МСК с lon_0 и x_0=0, y_0=0
2. Вычисляется смещение dx, dy между object и reference
3. Среднее смещение = x_0, y_0

Алгоритм (LDP):
1. reference_wgs84 трансформируется в тестовую МСК
2. x_0 = mean(raw_wrong.x - ref_msk.x)
3. y_0 = mean(raw_wrong.y - ref_msk.y)
"""

from typing import List, Tuple, Dict, Optional

from qgis.core import QgsPointXY

from .Fsm_0_5_4_base_method import BaseCalculationMethod, CalculationResult
from Daman_QGIS.utils import log_info, log_error
from Daman_QGIS.constants import ELLPS_KRASS, TOWGS84_SK42_PROJ, RMSE_THRESHOLD_OK


class Fsm_0_5_4_1_SimpleOffset(BaseCalculationMethod):
    """
    Простое смещение x_0, y_0.
    lon_0 фиксирован (из исходной CRS).
    Минимум: 1 точка.
    """

    @property
    def name(self) -> str:
        return "Простое смещение"

    @property
    def method_id(self) -> str:
        return "simple"

    @property
    def min_points(self) -> int:
        return 1

    @property
    def description(self) -> str:
        return "Только смещение x_0, y_0. lon_0 не меняется."

    def supports_ldp(self) -> bool:
        """Метод поддерживает LDP-подход."""
        return True

    def calculate(
        self,
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        base_params: Dict,
        initial_lon_0: float
    ) -> CalculationResult:
        """
        Расчёт смещения x_0, y_0.

        lon_0 остаётся = initial_lon_0.
        """
        if not control_points_wgs84:
            log_error("Fsm_0_5_4_1: Нет контрольных точек")
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
            # Извлекаем параметры
            lat_0 = base_params.get('lat_0', 0.0)
            k_0 = base_params.get('k_0', 1.0)
            ellps_param = base_params.get('ellps_param', ELLPS_KRASS)
            # ГОСТ 32453-2017: параметры преобразования СК-42 -> WGS-84
            towgs84_param = base_params.get('towgs84_param', TOWGS84_SK42_PROJ)

            # Используем унаследованный метод _calc_offset
            x_0, y_0, calc_rmse, errors = self._calc_offset(
                control_points_wgs84, initial_lon_0, lat_0, k_0,
                ellps_param, towgs84_param
            )

            # Проверка на ошибку (невалидная CRS)
            if calc_rmse == float('inf'):
                log_error(f"Fsm_0_5_4_1: Невалидная CRS для lon_0={initial_lon_0}")
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

            rmse, min_err, max_err = self._get_error_stats(errors)
            success = rmse < RMSE_THRESHOLD_OK

            # Компактный лог
            status = "OK" if success else "WARN"
            log_info(
                f"Fsm_0_5_4_1 [{self.method_id}]: "
                f"lon_0={initial_lon_0:.4f} x_0={x_0:.2f} y_0={y_0:.2f} "
                f"RMSE={rmse:.4f}m [{status}]"
            )

            return CalculationResult(
                method_name=self.name,
                method_id=self.method_id,
                lon_0=initial_lon_0,
                x_0=x_0,
                y_0=y_0,
                rmse=rmse,
                min_error=min_err,
                max_error=max_err,
                success=success,
                min_points_required=self.min_points,
                diagnostics={'errors': errors}
            )

        except Exception as e:
            log_error(f"Fsm_0_5_4_1: Ошибка расчёта: {e}")
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

    def calculate_ldp(
        self,
        raw_wrong_coords: List[Tuple[float, float]],
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        base_params: Dict,
        initial_lon_0: float
    ) -> Optional[CalculationResult]:
        """
        LDP-расчёт смещения x_0, y_0 с ФИКСИРОВАННЫМ lon_0 на центре объекта.

        ВАЖНО: Использует ПРЯМУЮ трансформацию EPSG:3857 -> test_proj.
        Это критически важно для визуального совпадения с WFS слоями.

        lon_0 фиксируется на центре объекта (object_center_lon),
        а НЕ на lon_0 из исходной CRS (initial_lon_0).
        """
        if not raw_wrong_coords or not control_points_wgs84:
            log_error("Fsm_0_5_4_1 [LDP]: Нет контрольных точек")
            return None

        # Проверяем наличие reference_3857 для прямой трансформации
        reference_3857 = base_params.get('reference_3857')
        use_direct_3857 = reference_3857 is not None

        if use_direct_3857 and len(raw_wrong_coords) != len(reference_3857):
            log_error("Fsm_0_5_4_1 [LDP]: Несоответствие количества точек (raw vs 3857)")
            return None
        elif not use_direct_3857 and len(raw_wrong_coords) != len(control_points_wgs84):
            log_error("Fsm_0_5_4_1 [LDP]: Несоответствие количества точек")
            return None

        try:
            # Извлекаем параметры
            lat_0 = base_params.get('lat_0', 0.0)
            k_0 = base_params.get('k_0', 1.0)
            ellps_param = base_params.get('ellps_param', ELLPS_KRASS)
            towgs84_param = base_params.get('towgs84_param', TOWGS84_SK42_PROJ)

            # LDP: ФИКСИРУЕМ lon_0 на центре объекта (НЕ на initial_lon_0!)
            object_center_lon = base_params.get('object_center_lon', None)
            if object_center_lon is None:
                log_error("Fsm_0_5_4_1 [LDP]: object_center_lon не задан, используем initial_lon_0")
                object_center_lon = initial_lon_0

            fixed_lon_0 = object_center_lon

            # Используем прямую трансформацию 3857->proj если доступно
            if use_direct_3857:
                x_0, y_0, calc_rmse, errors = self._calc_offset_ldp_3857(
                    raw_wrong_coords, reference_3857,
                    fixed_lon_0, lat_0, k_0,
                    ellps_param, towgs84_param
                )
            else:
                # Fallback: через WGS84 (менее точный)
                reference_wgs84 = [ref for _, ref in control_points_wgs84]
                x_0, y_0, calc_rmse, errors = self._calc_offset_ldp(
                    raw_wrong_coords, reference_wgs84,
                    fixed_lon_0, lat_0, k_0,
                    ellps_param, towgs84_param
                )

            # Проверка на ошибку
            if calc_rmse == float('inf'):
                log_error(f"Fsm_0_5_4_1 [LDP]: Невалидная CRS для lon_0={fixed_lon_0}")
                return None

            rmse, min_err, max_err = self._get_error_stats(errors)
            success = rmse < RMSE_THRESHOLD_OK

            # Компактный лог
            status = "OK" if success else "WARN"
            log_info(
                f"Fsm_0_5_4_1 [{self.method_id}] [LDP]: "
                f"lon_0={fixed_lon_0:.4f} (fixed at object center) "
                f"x_0={x_0:.2f} y_0={y_0:.2f} "
                f"RMSE={rmse:.4f}m [{status}]"
            )

            return CalculationResult(
                method_name=self.name,
                method_id=self.method_id,
                lon_0=fixed_lon_0,
                x_0=x_0,
                y_0=y_0,
                rmse=rmse,
                min_error=min_err,
                max_error=max_err,
                success=success,
                min_points_required=self.min_points,
                approach_type="ldp",
                diagnostics={
                    'errors': errors,
                    'initial_lon_0': initial_lon_0,
                    'object_center_lon': object_center_lon,
                    'lon_0_fixed': True
                }
            )

        except Exception as e:
            log_error(f"Fsm_0_5_4_1 [LDP]: Ошибка расчёта: {e}")
            return None

    # _calc_offset и _calc_offset_ldp наследуются из BaseCalculationMethod
