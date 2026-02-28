# -*- coding: utf-8 -*-
"""
Fsm_0_5_4_3 - Метод аффинной коррекции (AffineMethod)

Минимум: 3 точки
Оптимизирует: lon_0, dS (towgs84), x_0, y_0

Поддерживает два подхода:
- Calibration: аффинный анализ с корректировкой lon_0 и dS
- LDP: создание проекции под RAW координаты + оптимизация lon_0

Алгоритм (Calibration):
1. Вычисление аффинных параметров (rotation, scale, translation)
2. Корректировка lon_0 на основе rotation
3. Корректировка dS в towgs84 на основе scale
4. Финальный расчёт x_0, y_0

Алгоритм (LDP):
1. Оптимизация lon_0 методом золотого сечения
2. x_0 = mean(raw_wrong.x - ref_msk.x)
3. y_0 = mean(raw_wrong.y - ref_msk.y)
"""

from typing import List, Tuple, Dict, Optional

from qgis.core import QgsPointXY

from .Fsm_0_5_4_base_method import BaseCalculationMethod, CalculationResult
from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.constants import ELLPS_KRASS, TOWGS84_SK42_PROJ, RMSE_THRESHOLD_OK


class Fsm_0_5_4_3_Affine(BaseCalculationMethod):
    """
    Аффинный анализ + коррекция dS в towgs84.
    Минимум: 3 точки.
    """

    @property
    def name(self) -> str:
        return "Аффинная коррекция"

    @property
    def method_id(self) -> str:
        return "affine"

    @property
    def min_points(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "Анализ rotation/scale, корректировка lon_0 и dS в towgs84"

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
        Расчёт с аффинной коррекцией.
        """
        if len(control_points_wgs84) < self.min_points:
            log_warning(f"Fsm_0_5_4_3: Нужно минимум {self.min_points} точек")
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

            # Шаг 1: Трансформируем точки в МСК с начальными параметрами
            transform_result = self._create_msk_transform(
                initial_lon_0, lat_0, k_0, ellps_param, towgs84_param
            )

            if transform_result is None:
                log_error("Fsm_0_5_4_3: Невалидная CRS")
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

            # Собираем пары точек в МСК
            obj_points, ref_points = self._transform_points_to_msk(
                control_points_wgs84, transform_to_msk
            )

            # Шаг 2: Вычисляем аффинные параметры
            affine = self._calculate_affine_params(obj_points, ref_points)

            rotation_deg = affine['rotation_deg']
            scale = affine['scale']
            scale_ppm = (scale - 1) * 1e6

            # Шаг 3: Корректируем параметры проекции
            # Корректировка lon_0 на основе поворота (теория сходимости меридианов)
            lon_0_correction = self._calculate_lon0_correction(
                rotation_deg, control_points_wgs84
            )
            corrected_lon_0 = initial_lon_0 + lon_0_correction

            # Корректировка dS на основе масштаба
            current_dS = self._extract_dS(towgs84_param)
            dS_correction = -scale_ppm
            corrected_dS = current_dS + dS_correction

            # Формируем новый towgs84
            corrected_towgs84 = self._update_towgs84_dS(towgs84_param, corrected_dS)

            # Шаг 4: Пересчитываем x_0, y_0 с новыми параметрами
            final_x0, final_y0, final_rmse, errors = self._calc_offset(
                control_points_wgs84, corrected_lon_0, lat_0, k_0,
                ellps_param, corrected_towgs84
            )

            rmse, min_err, max_err = self._get_error_stats(errors)
            success = rmse < RMSE_THRESHOLD_OK

            # Компактный лог
            status = "OK" if success else "WARN"
            log_info(
                f"Fsm_0_5_4_3 [{self.method_id}]: "
                f"lon_0={corrected_lon_0:.4f} dS={corrected_dS:.2f}ppm "
                f"x_0={final_x0:.2f} y_0={final_y0:.2f} "
                f"RMSE={rmse:.4f}m [{status}]"
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
                    'scale': scale,
                    'scale_ppm': scale_ppm,
                    'dS_correction': dS_correction,
                    'original_lon_0': initial_lon_0,
                    'original_dS': current_dS
                }
            )

        except Exception as e:
            log_error(f"Fsm_0_5_4_3: Ошибка расчёта: {e}")
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
        LDP-расчёт с ФИКСИРОВАННЫМ lon_0 на центре объекта.

        ВАЖНО: Использует ПРЯМУЮ трансформацию EPSG:3857 -> test_proj.
        Это критически важно для визуального совпадения с WFS слоями.

        В LDP-режиме НЕ корректируем dS (towgs84), только x_0/y_0.
        lon_0 фиксируется на центре объекта (НЕ оптимизируется).
        """
        if len(raw_wrong_coords) < self.min_points:
            log_warning(f"Fsm_0_5_4_3 [LDP]: Нужно минимум {self.min_points} точек")
            return None

        # Проверяем наличие reference_3857 для прямой трансформации
        reference_3857 = base_params.get('reference_3857')
        use_direct_3857 = reference_3857 is not None

        if use_direct_3857 and len(raw_wrong_coords) != len(reference_3857):
            log_error("Fsm_0_5_4_3 [LDP]: Несоответствие количества точек (raw vs 3857)")
            return None
        elif not use_direct_3857 and len(raw_wrong_coords) != len(control_points_wgs84):
            log_error("Fsm_0_5_4_3 [LDP]: Несоответствие количества точек")
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
                log_error("Fsm_0_5_4_3 [LDP]: object_center_lon не задан, используем initial_lon_0")
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
                log_error(f"Fsm_0_5_4_3 [LDP]: Невалидная CRS для lon_0={fixed_lon_0}")
                return None

            rmse, min_err, max_err = self._get_error_stats(errors)
            success = rmse < RMSE_THRESHOLD_OK

            # Компактный лог
            status = "OK" if success else "WARN"
            log_info(
                f"Fsm_0_5_4_3 [{self.method_id}] [LDP]: "
                f"lon_0={fixed_lon_0:.4f} (fixed at object center) "
                f"x_0={final_x0:.2f} y_0={final_y0:.2f} "
                f"RMSE={rmse:.4f}m [{status}]"
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
                    'initial_lon_0': initial_lon_0,
                    'object_center_lon': object_center_lon,
                    'lon_0_fixed': True
                }
            )

        except Exception as e:
            log_error(f"Fsm_0_5_4_3 [LDP]: Ошибка расчёта: {e}")
            return None

    # _calculate_affine_params, _extract_dS, _update_towgs84_dS, _calc_offset,
    # _calc_offset_ldp, _golden_section_search наследуются из BaseCalculationMethod
