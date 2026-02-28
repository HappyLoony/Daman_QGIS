# -*- coding: utf-8 -*-
"""
Fsm_0_5_4_9 - 2D Helmert (4 параметра)

Чистая 2D трансформация Helmert (similarity transform):
- dx, dy (смещение)
- scale (масштаб)
- rotation (поворот)

Минимум: 2 точки
Рекомендуется: 3+ точки для контроля качества

Применение:
- Трансформация растров
- Локальная подгонка данных
- Когда не нужна CRS проекция

Формулы:
    X' = dx + scale * (X * cos(theta) - Y * sin(theta))
    Y' = dy + scale * (X * sin(theta) + Y * cos(theta))

PROJ синтаксис:
    +proj=helmert +x=dx +y=dy +s=scale +theta=rotation_arcsec

Источники:
- https://en.wikipedia.org/wiki/Helmert_transformation
- https://proj.org/en/stable/operations/transformations/helmert.html
"""

import math
from typing import List, Tuple, Dict, Optional

from qgis.core import QgsPointXY

from .Fsm_0_5_4_base_method import BaseCalculationMethod, CalculationResult
from Daman_QGIS.core.math.helmert_2d import (
    Helmert2DResult,
    calculate_helmert_2d as _shared_calculate_helmert_2d,
    transform_point as _shared_transform_point,
    inverse_transform_point as _shared_inverse_transform_point,
)
from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.constants import ELLPS_KRASS


class Fsm_0_5_4_9_Helmert2D(BaseCalculationMethod):
    """
    2D Helmert (4 параметра): dx, dy, scale, rotation.

    Применяет similarity transform к плоским координатам.
    Не изменяет CRS проекцию - работает напрямую с координатами.

    Минимум: 2 точки (даёт 4 уравнения для 4 неизвестных)
    """

    @property
    def name(self) -> str:
        return "Helmert 2D (4P)"

    @property
    def method_id(self) -> str:
        return "helmert_2d"

    @property
    def min_points(self) -> int:
        return 2

    @property
    def description(self) -> str:
        return "2D Helmert: dx, dy, scale, rotation (для координат)"

    def calculate(
        self,
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        base_params: Dict,
        initial_lon_0: float
    ) -> CalculationResult:
        """
        Расчёт параметров 2D Helmert.

        Для совместимости с интерфейсом F_0_5 принимает WGS84 точки,
        но расчёт ведётся в плоских координатах (после проекции).

        Returns:
            CalculationResult с параметрами в diagnostics['helmert_2d']
        """
        if len(control_points_wgs84) < self.min_points:
            log_warning(f"Fsm_0_5_4_9: Нужно минимум {self.min_points} точек")
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
            # Извлекаем параметры проекции
            lat_0 = base_params.get('lat_0', 0.0)
            k_0 = base_params.get('k_0', 1.0)
            ellps_param = base_params.get('ellps_param', ELLPS_KRASS)
            towgs84_param = base_params.get('towgs84_param', '')

            # Трансформируем точки в плоские координаты
            transform_result = self._create_msk_transform(
                initial_lon_0, lat_0, k_0, ellps_param, towgs84_param
            )

            if transform_result is None:
                log_error("Fsm_0_5_4_9: Не удалось создать CRS")
                return self._error_result(initial_lon_0)

            _, transform_to_msk = transform_result

            src_points, dst_points = self._transform_points_to_msk(
                control_points_wgs84, transform_to_msk
            )

            # Расчёт 2D Helmert
            helmert_result = self.calculate_helmert_2d(src_points, dst_points)

            if not helmert_result.success:
                return self._error_result(initial_lon_0)

            # Для совместимости с F_0_5: x_0, y_0 = dx, dy
            # lon_0 остаётся без изменений (2D Helmert не меняет проекцию)

            log_info(
                f"Fsm_0_5_4_9 [{self.method_id}]: "
                f"dx={helmert_result.dx:.3f} dy={helmert_result.dy:.3f} "
                f"scale={helmert_result.scale:.6f} rot={helmert_result.rotation_deg:.4f}deg "
                f"RMSE={helmert_result.rmse:.4f}m"
            )

            return CalculationResult(
                method_name=self.name,
                method_id=self.method_id,
                lon_0=initial_lon_0,
                x_0=helmert_result.dx,
                y_0=helmert_result.dy,
                rmse=helmert_result.rmse,
                min_error=min(helmert_result.residuals) if helmert_result.residuals else 0.0,
                max_error=max(helmert_result.residuals) if helmert_result.residuals else 0.0,
                success=helmert_result.success,
                min_points_required=self.min_points,
                result_type="coordinate_transform",  # НЕ для CRS, а для трансформации координат
                diagnostics={
                    'helmert_2d': {
                        'dx': helmert_result.dx,
                        'dy': helmert_result.dy,
                        'scale': helmert_result.scale,
                        'rotation_deg': helmert_result.rotation_deg,
                        'rotation_arcsec': helmert_result.rotation_arcsec,
                        'scale_ppm': (helmert_result.scale - 1.0) * 1e6,
                    },
                    'proj_helmert': self._to_proj_string(helmert_result),
                    'residuals': helmert_result.residuals
                }
            )

        except Exception as e:
            log_error(f"Fsm_0_5_4_9: Ошибка расчёта: {e}")
            return self._error_result(initial_lon_0)

    def calculate_helmert_2d(
        self,
        src_points: List[Tuple[float, float]],
        dst_points: List[Tuple[float, float]]
    ) -> Helmert2DResult:
        """
        Расчёт 4 параметров 2D Helmert методом наименьших квадратов.

        Делегирует в shared модуль core.math.helmert_2d.

        Parameters:
            src_points: Исходные точки [(x1,y1), (x2,y2), ...]
            dst_points: Целевые точки [(x1',y1'), (x2',y2'), ...]

        Returns:
            Helmert2DResult с параметрами трансформации
        """
        return _shared_calculate_helmert_2d(src_points, dst_points)

    def transform_point(
        self,
        x: float,
        y: float,
        params: Helmert2DResult
    ) -> Tuple[float, float]:
        """
        Применение 2D Helmert к одной точке.
        Делегирует в shared модуль core.math.helmert_2d.
        """
        return _shared_transform_point(x, y, params)

    def inverse_transform_point(
        self,
        x: float,
        y: float,
        params: Helmert2DResult
    ) -> Tuple[float, float]:
        """
        Обратная 2D Helmert трансформация.
        Делегирует в shared модуль core.math.helmert_2d.
        """
        return _shared_inverse_transform_point(x, y, params)

    def _to_proj_string(self, params: Helmert2DResult) -> str:
        """
        Формирование PROJ строки для 2D Helmert.

        PROJ использует угловые секунды для theta.
        """
        return (
            f"+proj=helmert "
            f"+x={params.dx:.6f} "
            f"+y={params.dy:.6f} "
            f"+s={params.scale - 1.0:.10f} "  # PROJ: s = scale - 1
            f"+theta={params.rotation_arcsec:.6f}"
        )

    def _error_result(self, initial_lon_0: float) -> CalculationResult:
        """Возвращает результат с ошибкой."""
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
