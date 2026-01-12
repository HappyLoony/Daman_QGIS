# -*- coding: utf-8 -*-
"""
Fsm_0_5_4_2 - Метод смещения с оптимизацией меридиана (OffsetMeridianMethod)

Минимум: 2 точки
Оптимизирует: lon_0, x_0, y_0

Алгоритм:
1. Итеративный подбор lon_0 методом золотого сечения
2. Для каждого lon_0 вычисляется x_0, y_0 и RMSE
3. Выбирается lon_0 с минимальным RMSE
"""

from typing import List, Tuple, Dict

from qgis.core import QgsPointXY

from .Fsm_0_5_4_base_method import BaseCalculationMethod, CalculationResult
from Daman_QGIS.utils import log_info, log_error
from Daman_QGIS.constants import ELLPS_KRASS, TOWGS84_SK42_PROJ, RMSE_THRESHOLD_OK


class Fsm_0_5_4_2_OffsetMeridian(BaseCalculationMethod):
    """
    Смещение + оптимизация центрального меридиана.
    Минимум: 2 точки.
    """

    @property
    def name(self) -> str:
        return "Смещение + меридиан"

    @property
    def method_id(self) -> str:
        return "meridian"

    @property
    def min_points(self) -> int:
        return 2

    @property
    def description(self) -> str:
        return "Оптимизация lon_0 методом золотого сечения + x_0, y_0"

    def calculate(
        self,
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        base_params: Dict,
        initial_lon_0: float
    ) -> CalculationResult:
        """
        Расчёт оптимального lon_0 и смещения x_0, y_0.
        """
        if len(control_points_wgs84) < self.min_points:
            log_error(f"Fsm_0_5_4_2: Нужно минимум {self.min_points} точек")
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

            # Функция для вычисления RMSE при заданном lon_0
            def calc_rmse_for_lon0(lon_0: float) -> Tuple[float, float, float, List[float]]:
                return self._calc_offset(
                    control_points_wgs84, lon_0, lat_0, k_0, ellps_param, towgs84_param
                )

            # Грубый поиск: проверяем диапазон вокруг initial_lon_0
            best_lon_0 = initial_lon_0
            best_rmse = float('inf')
            best_x0, best_y0 = 0.0, 0.0

            # Начальное значение
            x0, y0, rmse, _ = calc_rmse_for_lon0(initial_lon_0)
            if rmse < best_rmse:
                best_lon_0 = initial_lon_0
                best_rmse = rmse
                best_x0, best_y0 = x0, y0

            # Тестируем смещения
            for delta in [-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0]:
                test_lon_0 = initial_lon_0 + delta
                x0, y0, rmse, _ = calc_rmse_for_lon0(test_lon_0)
                if rmse < best_rmse:
                    best_lon_0 = test_lon_0
                    best_rmse = rmse
                    best_x0, best_y0 = x0, y0

            # Точный поиск методом золотого сечения
            def objective(lon_0):
                _, _, rmse, _ = calc_rmse_for_lon0(lon_0)
                return rmse

            search_result = self._golden_section_search(
                objective,
                best_lon_0 - 0.5,
                best_lon_0 + 0.5,
                tol=1e-6,
                max_iter=50
            )

            optimal_lon_0 = search_result['x']
            final_x0, final_y0, final_rmse, errors = calc_rmse_for_lon0(optimal_lon_0)

            rmse, min_err, max_err = self._get_error_stats(errors)
            success = rmse < RMSE_THRESHOLD_OK

            # Компактный лог
            status = "OK" if success else "WARN"
            log_info(
                f"Fsm_0_5_4_2 [{self.method_id}]: "
                f"lon_0={optimal_lon_0:.4f} x_0={final_x0:.2f} y_0={final_y0:.2f} "
                f"RMSE={rmse:.4f}m [{status}]"
            )

            return CalculationResult(
                method_name=self.name,
                method_id=self.method_id,
                lon_0=optimal_lon_0,
                x_0=final_x0,
                y_0=final_y0,
                rmse=rmse,
                min_error=min_err,
                max_error=max_err,
                success=success,
                min_points_required=self.min_points,
                diagnostics={
                    'errors': errors,
                    'initial_lon_0': initial_lon_0,
                    'search_iterations': search_result['iterations']
                }
            )

        except Exception as e:
            log_error(f"Fsm_0_5_4_2: Ошибка расчёта: {e}")
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

    # _calc_offset и _golden_section_search наследуются из BaseCalculationMethod
