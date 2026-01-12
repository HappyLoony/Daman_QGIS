# -*- coding: utf-8 -*-
"""
Fsm_0_5_4_4 - Метод Helmert 7-параметрический (Helmert7PMethod)

Минимум: 3 точки (даёт 9 уравнений для 7 неизвестных)
Оптимизирует: lon_0 + x_0, y_0 (towgs84 фиксирован из МСК)

ВАЖНО: Полная оптимизация всех 7 параметров towgs84 требует точных
3D координат (с высотами). Для 2D задачи подбора проекции используется
итеративная оптимизация lon_0 с анализом остатков.

Алгоритм v2:
1. Анализ распределения ошибок по направлениям
2. Оптимизация lon_0 для минимизации систематической ошибки по X
3. Вычисление x_0, y_0 для компенсации остаточного смещения
"""

import math
from typing import List, Tuple, Dict

from qgis.core import (
    QgsPointXY,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject
)

from .Fsm_0_5_4_base_method import BaseCalculationMethod, CalculationResult
from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.constants import (
    ELLPS_KRASS, TOWGS84_SK42_PROJ, ELLIPSOID_KRASS_A, ELLIPSOID_KRASS_F,
    RMSE_THRESHOLD_OK
)


class Fsm_0_5_4_4_Helmert7P(BaseCalculationMethod):
    """
    Полная 7-параметрическая трансформация Helmert.
    Оптимизация всех 7 параметров towgs84.
    Минимум: 3 точки.
    """

    # Константы эллипсоида Красовского (ГОСТ 32453-2017)
    KRASS_A = ELLIPSOID_KRASS_A  # Большая полуось
    KRASS_F = ELLIPSOID_KRASS_F  # Сжатие

    @property
    def name(self) -> str:
        return "Helmert 7P"

    @property
    def method_id(self) -> str:
        return "helmert"

    @property
    def min_points(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "Оптимизация lon_0 с анализом остатков + x_0, y_0"

    def calculate(
        self,
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        base_params: Dict,
        initial_lon_0: float
    ) -> CalculationResult:
        """
        Расчёт параметров проекции с анализом остатков.

        Алгоритм v2:
        1. Анализируем ошибки при начальном lon_0
        2. Оптимизируем lon_0 по градиенту ошибок
        3. Вычисляем x_0, y_0
        """
        if len(control_points_wgs84) < self.min_points:
            log_warning(f"Fsm_0_5_4_4: Нужно минимум {self.min_points} точек")
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

            # Шаг 1: Анализ ошибок при начальном lon_0
            dx_errors, dy_errors = self._analyze_residuals(
                control_points_wgs84, initial_lon_0, lat_0, k_0,
                ellps_param, towgs84_param
            )

            # Шаг 2: Оптимизация lon_0 методом градиентного спуска
            # Ищем lon_0, который минимизирует дисперсию dx_errors
            best_lon_0 = initial_lon_0
            best_rmse = float('inf')
            best_x0, best_y0 = 0.0, 0.0

            # Грубый поиск
            for delta in [-1.0, -0.5, 0.0, 0.5, 1.0]:
                test_lon_0 = initial_lon_0 + delta
                x0, y0, rmse, _ = self._calc_offset(
                    control_points_wgs84, test_lon_0, lat_0, k_0,
                    ellps_param, towgs84_param
                )
                if rmse < best_rmse:
                    best_lon_0 = test_lon_0
                    best_rmse = rmse
                    best_x0, best_y0 = x0, y0

            # Точный поиск методом золотого сечения
            search_result = self._golden_section_search(
                lambda lon: self._calc_offset(
                    control_points_wgs84, lon, lat_0, k_0,
                    ellps_param, towgs84_param
                )[2],
                best_lon_0 - 0.3,
                best_lon_0 + 0.3,
                tol=1e-6
            )
            optimal_lon_0 = search_result['x']

            # Финальный расчёт с оптимальным lon_0
            final_x0, final_y0, final_rmse, errors = self._calc_offset(
                control_points_wgs84, optimal_lon_0, lat_0, k_0,
                ellps_param, towgs84_param
            )

            # Анализ остатков для диагностики
            dx_final, dy_final = self._analyze_residuals(
                control_points_wgs84, optimal_lon_0, lat_0, k_0,
                ellps_param, towgs84_param
            )
            dx_std = self._std_dev(dx_final)
            dy_std = self._std_dev(dy_final)

            rmse, min_err, max_err = self._get_error_stats(errors)
            success = rmse < RMSE_THRESHOLD_OK

            # Компактный лог
            status = "OK" if success else "WARN"
            log_info(
                f"Fsm_0_5_4_4 [{self.method_id}]: "
                f"lon_0={optimal_lon_0:.4f} x_0={final_x0:.2f} y_0={final_y0:.2f} "
                f"RMSE={rmse:.4f}m [{status}]"
            )
            log_info(
                f"Fsm_0_5_4_4: residuals std: dX={dx_std:.3f}m dY={dy_std:.3f}m"
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
                    'residuals': {
                        'dx_std': dx_std,
                        'dy_std': dy_std,
                        'dx_values': dx_final,
                        'dy_values': dy_final
                    },
                    'original_lon_0': initial_lon_0,
                    'original_towgs84': towgs84_param
                }
            )

        except Exception as e:
            log_error(f"Fsm_0_5_4_4: Ошибка расчёта: {e}")
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

    def _analyze_residuals(
        self,
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        lon_0: float,
        lat_0: float,
        k_0: float,
        ellps_param: str,
        towgs84_param: str
    ) -> Tuple[List[float], List[float]]:
        """
        Анализ остатков (dx, dy) после применения x_0, y_0.

        Returns:
        --------
        Tuple[List[float], List[float]]: (dx_residuals, dy_residuals)
        """
        try:
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")

            proj_string = (
                f"+proj=tmerc "
                f"+lat_0={lat_0} "
                f"+lon_0={lon_0} "
                f"+k_0={k_0} "
                f"+x_0=0 +y_0=0 "
                f"{ellps_param} "
                f"{towgs84_param} "
                f"+units=m +no_defs"
            )

            test_crs = QgsCoordinateReferenceSystem()
            test_crs.createFromProj(proj_string)

            if not test_crs.isValid():
                return ([], [])

            transform_to_msk = QgsCoordinateTransform(
                wgs84, test_crs, QgsProject.instance()
            )

            dx_list = []
            dy_list = []

            for object_wgs, reference_wgs in control_points_wgs84:
                obj_msk = transform_to_msk.transform(object_wgs)
                ref_msk = transform_to_msk.transform(reference_wgs)

                dx = ref_msk.x() - obj_msk.x()
                dy = ref_msk.y() - obj_msk.y()

                dx_list.append(dx)
                dy_list.append(dy)

            # Вычисляем остатки относительно среднего
            mean_dx = sum(dx_list) / len(dx_list) if dx_list else 0
            mean_dy = sum(dy_list) / len(dy_list) if dy_list else 0

            dx_residuals = [dx - mean_dx for dx in dx_list]
            dy_residuals = [dy - mean_dy for dy in dy_list]

            return (dx_residuals, dy_residuals)

        except Exception:
            return ([], [])

    def _std_dev(self, values: List[float]) -> float:
        """Стандартное отклонение."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return math.sqrt(variance)

    # _golden_section_search и _calc_offset наследуются из BaseCalculationMethod
