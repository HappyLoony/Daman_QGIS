# -*- coding: utf-8 -*-
"""
Fsm_0_5_4_4 - Метод Helmert 7-параметрический (Helmert7PMethod)

Минимум: 3 точки (даёт 9 уравнений для 7 неизвестных)
Оптимизирует: lon_0 + x_0, y_0 (towgs84 фиксирован из МСК)

Поддерживает два подхода:
- Calibration: оптимизация lon_0 с анализом остатков
- LDP: создание проекции под RAW координаты + оптимизация lon_0

ВАЖНО: Полная оптимизация всех 7 параметров towgs84 требует точных
3D координат (с высотами). Для 2D задачи подбора проекции используется
итеративная оптимизация lon_0 с анализом остатков.

Алгоритм v2 (Calibration):
1. Анализ распределения ошибок по направлениям
2. Оптимизация lon_0 для минимизации систематической ошибки по X
3. Вычисление x_0, y_0 для компенсации остаточного смещения

Алгоритм (LDP):
1. Оптимизация lon_0 методом золотого сечения с LDP-смещениями
2. x_0 = mean(raw_wrong.x - ref_msk.x)
3. y_0 = mean(raw_wrong.y - ref_msk.y)
"""

import math
from typing import List, Tuple, Dict, Optional

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

    def calculate_ldp(
        self,
        raw_wrong_coords: List[Tuple[float, float]],
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        base_params: Dict,
        initial_lon_0: float
    ) -> Optional[CalculationResult]:
        """
        LDP-расчёт с ФИКСИРОВАННЫМ lon_0 на центре объекта.

        ВАЖНО: Использует ПРЯМУЮ трансформацию EPSG:3857 -> test_proj.
        Это критически важно для визуального совпадения с WFS слоями.

        lon_0 фиксируется на центре объекта (НЕ оптимизируется).
        LDP создаёт "проекцию под данные" - lon_0 должен быть в центре объекта по определению.
        """
        if len(raw_wrong_coords) < self.min_points:
            log_warning(f"Fsm_0_5_4_4 [LDP]: Нужно минимум {self.min_points} точек")
            return None

        # Проверяем наличие reference_3857 для прямой трансформации
        reference_3857 = base_params.get('reference_3857')
        use_direct_3857 = reference_3857 is not None

        if use_direct_3857 and len(raw_wrong_coords) != len(reference_3857):
            log_error("Fsm_0_5_4_4 [LDP]: Несоответствие количества точек (raw vs 3857)")
            return None
        elif not use_direct_3857 and len(raw_wrong_coords) != len(control_points_wgs84):
            log_error("Fsm_0_5_4_4 [LDP]: Несоответствие количества точек")
            return None

        try:
            # Извлекаем параметры
            lat_0 = base_params.get('lat_0', 0.0)
            k_0 = base_params.get('k_0', 1.0)
            ellps_param = base_params.get('ellps_param', ELLPS_KRASS)
            towgs84_param = base_params.get('towgs84_param', TOWGS84_SK42_PROJ)

            # LDP: ФИКСИРУЕМ lon_0 на центре объекта (НЕ оптимизируем!)
            object_center_lon = base_params.get('object_center_lon', None)
            if object_center_lon is None:
                log_error("Fsm_0_5_4_4 [LDP]: object_center_lon не задан, используем initial_lon_0")
                object_center_lon = initial_lon_0

            fixed_lon_0 = object_center_lon

            # Вычисляем x_0, y_0 для фиксированного lon_0
            if use_direct_3857:
                # ПРЯМАЯ трансформация 3857 -> test_proj
                final_x0, final_y0, final_rmse, errors = self._calc_offset_ldp_3857(
                    raw_wrong_coords, reference_3857,
                    fixed_lon_0, lat_0, k_0, ellps_param, towgs84_param
                )
            else:
                # Fallback: через WGS84
                reference_wgs84 = [ref for _, ref in control_points_wgs84]
                final_x0, final_y0, final_rmse, errors = self._calc_offset_ldp(
                    raw_wrong_coords, reference_wgs84,
                    fixed_lon_0, lat_0, k_0, ellps_param, towgs84_param
                )

            # Проверка на ошибку
            if final_rmse == float('inf'):
                log_error(f"Fsm_0_5_4_4 [LDP]: Невалидная CRS для lon_0={fixed_lon_0}")
                return None

            # Анализ остатков для диагностики в LDP режиме
            dx_residuals = []
            dy_residuals = []
            mean_dx = sum(raw_wrong_coords[i][0] for i in range(len(raw_wrong_coords))) / len(raw_wrong_coords)
            mean_dy = sum(raw_wrong_coords[i][1] for i in range(len(raw_wrong_coords))) / len(raw_wrong_coords)
            for raw in raw_wrong_coords:
                dx_residuals.append(raw[0] - mean_dx)
                dy_residuals.append(raw[1] - mean_dy)
            dx_std = self._std_dev(dx_residuals)
            dy_std = self._std_dev(dy_residuals)

            rmse, min_err, max_err = self._get_error_stats(errors)
            success = rmse < RMSE_THRESHOLD_OK

            # Компактный лог
            status = "OK" if success else "WARN"
            log_info(
                f"Fsm_0_5_4_4 [{self.method_id}] [LDP]: "
                f"lon_0={fixed_lon_0:.4f} (fixed at object center) "
                f"x_0={final_x0:.2f} y_0={final_y0:.2f} "
                f"RMSE={rmse:.4f}m [{status}]"
            )
            log_info(
                f"Fsm_0_5_4_4 [LDP]: residuals std: dX={dx_std:.3f}m dY={dy_std:.3f}m"
            )

            return CalculationResult(
                method_name=self.name,
                method_id=self.method_id,
                lon_0=fixed_lon_0,
                x_0=final_x0,
                y_0=final_y0,
                rmse=rmse,
                min_error=min_err,
                max_error=max_err,
                success=success,
                min_points_required=self.min_points,
                approach_type="ldp",
                diagnostics={
                    'errors': errors,
                    'residuals': {
                        'dx_std': dx_std,
                        'dy_std': dy_std
                    },
                    'initial_lon_0': initial_lon_0,
                    'object_center_lon': object_center_lon,
                    'lon_0_fixed': True
                }
            )

        except Exception as e:
            log_error(f"Fsm_0_5_4_4 [LDP]: Ошибка расчёта: {e}")
            return None

    # _golden_section_search, _calc_offset, _calc_offset_ldp наследуются из BaseCalculationMethod
