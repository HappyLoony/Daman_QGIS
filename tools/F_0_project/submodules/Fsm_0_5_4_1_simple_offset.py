# -*- coding: utf-8 -*-
"""
Fsm_0_5_4_1 - Метод простого смещения (SimpleOffsetMethod)

Минимум: 1 точка
Оптимизирует: x_0, y_0
lon_0 остаётся фиксированным (initial_lon_0)

Алгоритм:
1. WGS84 точки трансформируются в тестовую МСК с lon_0 и x_0=0, y_0=0
2. Вычисляется смещение dx, dy между object и reference
3. Среднее смещение = x_0, y_0
"""

from typing import List, Tuple, Dict

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

    # _calc_offset наследуется из BaseCalculationMethod
