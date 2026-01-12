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
from dataclasses import dataclass

from qgis.core import QgsPointXY

from .Fsm_0_5_4_base_method import BaseCalculationMethod, CalculationResult
from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.constants import ELLPS_KRASS


@dataclass
class Helmert2DResult:
    """Результат 2D Helmert трансформации."""
    dx: float  # Смещение по X (метры)
    dy: float  # Смещение по Y (метры)
    scale: float  # Масштаб (безразмерный, ~1.0)
    rotation_deg: float  # Поворот (градусы)
    rotation_arcsec: float  # Поворот (угловые секунды для PROJ)
    rmse: float  # RMSE (метры)
    residuals: List[float]  # Остатки для каждой точки
    success: bool


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

        Модель:
            X' = dx + a*X - b*Y
            Y' = dy + b*X + a*Y

        Где:
            a = scale * cos(theta)
            b = scale * sin(theta)

        Parameters:
            src_points: Исходные точки [(x1,y1), (x2,y2), ...]
            dst_points: Целевые точки [(x1',y1'), (x2',y2'), ...]

        Returns:
            Helmert2DResult с параметрами трансформации
        """
        n = len(src_points)

        if n < 2:
            return Helmert2DResult(
                dx=0, dy=0, scale=1.0, rotation_deg=0,
                rotation_arcsec=0, rmse=float('inf'),
                residuals=[], success=False
            )

        # Метод наименьших квадратов для 4 параметров
        # Система уравнений: A * [dx, dy, a, b]^T = L

        # Построение матрицы коэффициентов A и вектора наблюдений L
        # Для каждой точки: 2 уравнения
        #   X' = dx + a*X - b*Y   =>  [1, 0, X, -Y] * [dx, dy, a, b]^T = X'
        #   Y' = dy + b*X + a*Y   =>  [0, 1, Y,  X] * [dx, dy, a, b]^T = Y'

        # Суммы для нормальных уравнений (без numpy)
        sum_1 = n  # сумма 1
        sum_X = sum(p[0] for p in src_points)
        sum_Y = sum(p[1] for p in src_points)
        sum_X2_Y2 = sum(p[0]**2 + p[1]**2 for p in src_points)

        sum_Xp = sum(p[0] for p in dst_points)
        sum_Yp = sum(p[1] for p in dst_points)
        sum_X_Xp_Y_Yp = sum(s[0]*d[0] + s[1]*d[1] for s, d in zip(src_points, dst_points))
        sum_X_Yp_Y_Xp = sum(s[0]*d[1] - s[1]*d[0] for s, d in zip(src_points, dst_points))

        # Решение системы нормальных уравнений
        # [n,    0,    sum_X,  -sum_Y ] [dx]   [sum_Xp]
        # [0,    n,    sum_Y,   sum_X ] [dy] = [sum_Yp]
        # [sum_X, sum_Y, sum_X2_Y2, 0 ] [a ]   [sum_X_Xp_Y_Yp]
        # [-sum_Y, sum_X, 0, sum_X2_Y2] [b ]   [sum_X_Yp_Y_Xp]

        # Упрощённое решение (для 2D Helmert с центрированием)
        # Центрируем точки для численной стабильности
        src_cx = sum_X / n
        src_cy = sum_Y / n
        dst_cx = sum_Xp / n
        dst_cy = sum_Yp / n

        # Центрированные суммы
        sum_dx_dx_dy_dy = sum((s[0]-src_cx)**2 + (s[1]-src_cy)**2 for s in src_points)

        if sum_dx_dx_dy_dy < 1e-10:
            return Helmert2DResult(
                dx=dst_cx - src_cx, dy=dst_cy - src_cy,
                scale=1.0, rotation_deg=0, rotation_arcsec=0,
                rmse=0.0, residuals=[0.0]*n, success=True
            )

        sum_dx_dxp_dy_dyp = sum(
            (s[0]-src_cx)*(d[0]-dst_cx) + (s[1]-src_cy)*(d[1]-dst_cy)
            for s, d in zip(src_points, dst_points)
        )
        sum_dx_dyp_dy_dxp = sum(
            (s[0]-src_cx)*(d[1]-dst_cy) - (s[1]-src_cy)*(d[0]-dst_cx)
            for s, d in zip(src_points, dst_points)
        )

        # Параметры a, b
        a = sum_dx_dxp_dy_dyp / sum_dx_dx_dy_dy
        b = sum_dx_dyp_dy_dxp / sum_dx_dx_dy_dy

        # Масштаб и поворот
        scale = math.sqrt(a**2 + b**2)
        rotation_rad = math.atan2(b, a)
        rotation_deg = math.degrees(rotation_rad)
        rotation_arcsec = rotation_deg * 3600  # градусы -> угловые секунды

        # Смещение (с учётом центрирования)
        dx = dst_cx - (a * src_cx - b * src_cy)
        dy = dst_cy - (b * src_cx + a * src_cy)

        # Вычисление остатков
        residuals = []
        for (sx, sy), (dx_t, dy_t) in zip(src_points, dst_points):
            tx = dx + a * sx - b * sy
            ty = dy + b * sx + a * sy
            residual = math.sqrt((tx - dx_t)**2 + (ty - dy_t)**2)
            residuals.append(residual)

        rmse = self._calculate_rmse(residuals)

        return Helmert2DResult(
            dx=dx,
            dy=dy,
            scale=scale,
            rotation_deg=rotation_deg,
            rotation_arcsec=rotation_arcsec,
            rmse=rmse,
            residuals=residuals,
            success=True
        )

    def transform_point(
        self,
        x: float,
        y: float,
        params: Helmert2DResult
    ) -> Tuple[float, float]:
        """
        Применение 2D Helmert к одной точке.

        Parameters:
            x, y: Исходные координаты
            params: Параметры трансформации

        Returns:
            (x', y'): Трансформированные координаты
        """
        a = params.scale * math.cos(math.radians(params.rotation_deg))
        b = params.scale * math.sin(math.radians(params.rotation_deg))

        x_new = params.dx + a * x - b * y
        y_new = params.dy + b * x + a * y

        return (x_new, y_new)

    def inverse_transform_point(
        self,
        x: float,
        y: float,
        params: Helmert2DResult
    ) -> Tuple[float, float]:
        """
        Обратная 2D Helmert трансформация.

        Parameters:
            x, y: Трансформированные координаты
            params: Параметры трансформации

        Returns:
            (x_orig, y_orig): Исходные координаты
        """
        a = params.scale * math.cos(math.radians(params.rotation_deg))
        b = params.scale * math.sin(math.radians(params.rotation_deg))

        # Обратная матрица: det = a^2 + b^2 = scale^2
        det = params.scale ** 2

        if det < 1e-10:
            return (x, y)

        # Убираем смещение
        x_shifted = x - params.dx
        y_shifted = y - params.dy

        # Обратная трансформация
        x_orig = (a * x_shifted + b * y_shifted) / det
        y_orig = (-b * x_shifted + a * y_shifted) / det

        return (x_orig, y_orig)

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
