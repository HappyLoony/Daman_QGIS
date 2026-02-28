# -*- coding: utf-8 -*-
"""
Fsm_0_6_2 - Методы трансформации координат

Три метода:
- OffsetMethod: простой сдвиг (2 параметра: dX, dY)
- Helmert2DMethod: конформная трансформация (4 параметра: dX, dY, rotation, scale)
- AffineMethod: аффинная трансформация (6 параметров: a1, a2, tx, b1, b2, ty)

Все солверы на чистом Python (без numpy), консистентно с F_0_5.
Helmert2D делегирует в shared core.math.helmert_2d.
"""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from statistics import median

from Daman_QGIS.core.math.helmert_2d import (
    Helmert2DResult,
    calculate_helmert_2d,
    transform_point as helmert_transform_point,
    calculate_rmse,
)
from Daman_QGIS.utils import log_info, log_error, log_warning


@dataclass
class TransformResult:
    """Результат расчёта трансформации."""
    method_name: str
    params: dict  # Параметры трансформации (зависят от метода)
    rmse: float  # RMSE в метрах
    residuals: List[float]  # Невязка по каждой паре
    max_residual: float  # Максимальная невязка
    blunder_indices: List[int]  # Индексы подозрительных пар (> 3 * median)
    success: bool = True


class BaseTransformMethod(ABC):
    """Базовый класс метода трансформации координат."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Название метода."""
        ...

    @property
    @abstractmethod
    def min_points(self) -> int:
        """Минимальное количество точек."""
        ...

    @abstractmethod
    def calculate(
        self,
        src_points: List[Tuple[float, float]],
        dst_points: List[Tuple[float, float]]
    ) -> TransformResult:
        """Рассчитать параметры трансформации."""
        ...

    @abstractmethod
    def apply_to_point(self, x: float, y: float) -> Tuple[float, float]:
        """Применить трансформацию к точке. Вызывать после calculate()."""
        ...

    def get_residuals(
        self,
        src_points: List[Tuple[float, float]],
        dst_points: List[Tuple[float, float]]
    ) -> List[float]:
        """Вычислить невязки для каждой пары точек."""
        residuals = []
        for (sx, sy), (dx, dy) in zip(src_points, dst_points):
            tx, ty = self.apply_to_point(sx, sy)
            residual = math.sqrt((tx - dx) ** 2 + (ty - dy) ** 2)
            residuals.append(residual)
        return residuals

    @staticmethod
    def detect_blunders(residuals: List[float]) -> List[int]:
        """
        Детекция грубых ошибок (blunders).

        Если невязка > 3 * медианная невязка -> подозрительная пара.

        Returns:
            Список индексов подозрительных пар
        """
        if len(residuals) < 3:
            return []

        med = median(residuals)
        if med < 1e-10:
            return []

        threshold = 3.0 * med
        return [i for i, r in enumerate(residuals) if r > threshold]


class OffsetMethod(BaseTransformMethod):
    """Простой сдвиг (Translation): 2 параметра (dX, dY)."""

    def __init__(self) -> None:
        self._dx: float = 0.0
        self._dy: float = 0.0

    @property
    def name(self) -> str:
        return "Offset (2P)"

    @property
    def min_points(self) -> int:
        return 1

    def calculate(
        self,
        src_points: List[Tuple[float, float]],
        dst_points: List[Tuple[float, float]]
    ) -> TransformResult:
        """Расчёт среднего смещения."""
        n = len(src_points)
        if n < self.min_points:
            return TransformResult(
                method_name=self.name, params={}, rmse=float('inf'),
                residuals=[], max_residual=float('inf'),
                blunder_indices=[], success=False
            )

        self._dx = sum(d[0] - s[0] for s, d in zip(src_points, dst_points)) / n
        self._dy = sum(d[1] - s[1] for s, d in zip(src_points, dst_points)) / n

        residuals = self.get_residuals(src_points, dst_points)
        rmse = calculate_rmse(residuals)
        blunders = self.detect_blunders(residuals)

        return TransformResult(
            method_name=self.name,
            params={
                'dx': self._dx,
                'dy': self._dy,
            },
            rmse=rmse,
            residuals=residuals,
            max_residual=max(residuals) if residuals else 0.0,
            blunder_indices=blunders,
            success=True
        )

    def apply_to_point(self, x: float, y: float) -> Tuple[float, float]:
        return (x + self._dx, y + self._dy)


class Helmert2DMethod(BaseTransformMethod):
    """
    2D Helmert (Similarity): 4 параметра (dX, dY, rotation, scale).

    Конформная трансформация - сохраняет форму объектов.
    Стандарт для кадастровой практики.
    Делегирует в shared core.math.helmert_2d.
    """

    def __init__(self) -> None:
        self._result: Optional[Helmert2DResult] = None

    @property
    def name(self) -> str:
        return "Helmert 2D (4P)"

    @property
    def min_points(self) -> int:
        return 2

    def calculate(
        self,
        src_points: List[Tuple[float, float]],
        dst_points: List[Tuple[float, float]]
    ) -> TransformResult:
        """Расчёт через shared Helmert2D solver."""
        if len(src_points) < self.min_points:
            return TransformResult(
                method_name=self.name, params={}, rmse=float('inf'),
                residuals=[], max_residual=float('inf'),
                blunder_indices=[], success=False
            )

        self._result = calculate_helmert_2d(src_points, dst_points)

        if not self._result.success:
            return TransformResult(
                method_name=self.name, params={}, rmse=float('inf'),
                residuals=[], max_residual=float('inf'),
                blunder_indices=[], success=False
            )

        blunders = self.detect_blunders(self._result.residuals)

        return TransformResult(
            method_name=self.name,
            params={
                'dx': self._result.dx,
                'dy': self._result.dy,
                'scale': self._result.scale,
                'scale_ppm': (self._result.scale - 1.0) * 1e6,
                'rotation_deg': self._result.rotation_deg,
                'rotation_arcsec': self._result.rotation_arcsec,
            },
            rmse=self._result.rmse,
            residuals=self._result.residuals,
            max_residual=max(self._result.residuals) if self._result.residuals else 0.0,
            blunder_indices=blunders,
            success=True
        )

    def apply_to_point(self, x: float, y: float) -> Tuple[float, float]:
        if self._result is None:
            return (x, y)
        return helmert_transform_point(x, y, self._result)


class AffineMethod(BaseTransformMethod):
    """
    Аффинная трансформация: 6 параметров (a1, a2, tx, b1, b2, ty).

    target_x = a1 * source_x + a2 * source_y + tx
    target_y = b1 * source_x + b2 * source_y + ty

    Допускает неравномерное масштабирование и сдвиг.
    Решение через нормальные уравнения (Cramer's rule для 3x3).

    ВНИМАНИЕ: это ИСТИННЫЙ 6-param affine, НЕ similarity из F_0_5.
    """

    def __init__(self) -> None:
        self._a1: float = 1.0
        self._a2: float = 0.0
        self._tx: float = 0.0
        self._b1: float = 0.0
        self._b2: float = 1.0
        self._ty: float = 0.0

    @property
    def name(self) -> str:
        return "Affine (6P)"

    @property
    def min_points(self) -> int:
        return 3

    def calculate(
        self,
        src_points: List[Tuple[float, float]],
        dst_points: List[Tuple[float, float]]
    ) -> TransformResult:
        """
        Расчёт 6 параметров аффинной трансформации через нормальные уравнения.

        Система: A^T * A * x = A^T * b, где A - матрица [xi, yi, 1] для каждой точки.
        Две независимые системы 3x3 (для X' и Y' отдельно).
        """
        n = len(src_points)
        if n < self.min_points:
            return TransformResult(
                method_name=self.name, params={}, rmse=float('inf'),
                residuals=[], max_residual=float('inf'),
                blunder_indices=[], success=False
            )

        # Нормальные уравнения для X': a1*x + a2*y + tx = X'
        # A^T * A:
        # [sum(xi^2),  sum(xi*yi), sum(xi)]   [a1]   [sum(xi*Xi')]
        # [sum(xi*yi), sum(yi^2),  sum(yi)] * [a2] = [sum(yi*Xi')]
        # [sum(xi),    sum(yi),    n      ]   [tx]   [sum(Xi')   ]

        sum_x = sum(s[0] for s in src_points)
        sum_y = sum(s[1] for s in src_points)
        sum_x2 = sum(s[0] ** 2 for s in src_points)
        sum_y2 = sum(s[1] ** 2 for s in src_points)
        sum_xy = sum(s[0] * s[1] for s in src_points)

        # Правые части для X'
        sum_x_xp = sum(s[0] * d[0] for s, d in zip(src_points, dst_points))
        sum_y_xp = sum(s[1] * d[0] for s, d in zip(src_points, dst_points))
        sum_xp = sum(d[0] for d in dst_points)

        # Правые части для Y'
        sum_x_yp = sum(s[0] * d[1] for s, d in zip(src_points, dst_points))
        sum_y_yp = sum(s[1] * d[1] for s, d in zip(src_points, dst_points))
        sum_yp = sum(d[1] for d in dst_points)

        # Матрица A^T*A (одинаковая для обеих систем)
        # [sum_x2,  sum_xy, sum_x]
        # [sum_xy,  sum_y2, sum_y]
        # [sum_x,   sum_y,  n    ]

        # Решение через Cramer's rule для 3x3
        # Определитель матрицы
        det = (sum_x2 * (sum_y2 * n - sum_y * sum_y)
               - sum_xy * (sum_xy * n - sum_y * sum_x)
               + sum_x * (sum_xy * sum_y - sum_y2 * sum_x))

        if abs(det) < 1e-20:
            log_warning("Fsm_0_6_2: Вырожденная матрица в Affine (точки коллинеарны?)")
            return TransformResult(
                method_name=self.name, params={}, rmse=float('inf'),
                residuals=[], max_residual=float('inf'),
                blunder_indices=[], success=False
            )

        # Решение для X': a1, a2, tx
        self._a1 = (sum_x_xp * (sum_y2 * n - sum_y ** 2)
                     - sum_xy * (sum_y_xp * n - sum_y * sum_xp)
                     + sum_x * (sum_y_xp * sum_y - sum_y2 * sum_xp)) / det

        self._a2 = (sum_x2 * (sum_y_xp * n - sum_y * sum_xp)
                     - sum_x_xp * (sum_xy * n - sum_y * sum_x)
                     + sum_x * (sum_xy * sum_xp - sum_y_xp * sum_x)) / det

        self._tx = (sum_x2 * (sum_y2 * sum_xp - sum_y_xp * sum_y)
                     - sum_xy * (sum_xy * sum_xp - sum_y_xp * sum_x)
                     + sum_x_xp * (sum_xy * sum_y - sum_y2 * sum_x)) / det

        # Решение для Y': b1, b2, ty
        self._b1 = (sum_x_yp * (sum_y2 * n - sum_y ** 2)
                     - sum_xy * (sum_y_yp * n - sum_y * sum_yp)
                     + sum_x * (sum_y_yp * sum_y - sum_y2 * sum_yp)) / det

        self._b2 = (sum_x2 * (sum_y_yp * n - sum_y * sum_yp)
                     - sum_x_yp * (sum_xy * n - sum_y * sum_x)
                     + sum_x * (sum_xy * sum_yp - sum_y_yp * sum_x)) / det

        self._ty = (sum_x2 * (sum_y2 * sum_yp - sum_y_yp * sum_y)
                     - sum_xy * (sum_xy * sum_yp - sum_y_yp * sum_x)
                     + sum_x_yp * (sum_xy * sum_y - sum_y2 * sum_x)) / det

        residuals = self.get_residuals(src_points, dst_points)
        rmse = calculate_rmse(residuals)
        blunders = self.detect_blunders(residuals)

        return TransformResult(
            method_name=self.name,
            params={
                'a1': self._a1,
                'a2': self._a2,
                'tx': self._tx,
                'b1': self._b1,
                'b2': self._b2,
                'ty': self._ty,
            },
            rmse=rmse,
            residuals=residuals,
            max_residual=max(residuals) if residuals else 0.0,
            blunder_indices=blunders,
            success=True
        )

    def apply_to_point(self, x: float, y: float) -> Tuple[float, float]:
        new_x = self._a1 * x + self._a2 * y + self._tx
        new_y = self._b1 * x + self._b2 * y + self._ty
        return (new_x, new_y)


def auto_select_method(
    src_points: List[Tuple[float, float]],
    dst_points: List[Tuple[float, float]]
) -> Tuple[TransformResult, BaseTransformMethod]:
    """
    Автоматический выбор лучшего метода трансформации.

    Логика:
    1. Рассчитать все 3 метода
    2. Helmert предпочтителен (конформный, сохраняет форму)
    3. Affine если RMSE < Helmert*0.8 (на 20%+ лучше)
    4. Offset если rotation ~0 и scale ~1

    Parameters:
        src_points: Исходные точки
        dst_points: Целевые точки

    Returns:
        (TransformResult, BaseTransformMethod) - лучший результат и метод
    """
    n = len(src_points)

    # Рассчитать все доступные методы
    offset = OffsetMethod()
    offset_result = offset.calculate(src_points, dst_points)

    helmert = Helmert2DMethod()
    helmert_result = helmert.calculate(src_points, dst_points)

    affine = AffineMethod()
    affine_result = affine.calculate(src_points, dst_points)

    log_info(
        f"Fsm_0_6_2: Результаты: "
        f"Offset RMSE={offset_result.rmse:.4f}m, "
        f"Helmert RMSE={helmert_result.rmse:.4f}m, "
        f"Affine RMSE={affine_result.rmse:.4f}m"
    )

    # Выбор лучшего метода
    best_result = offset_result
    best_method: BaseTransformMethod = offset

    if helmert_result.success:
        best_result = helmert_result
        best_method = helmert

        # Проверяем: может Offset достаточно?
        # (rotation ~0, scale ~1 -> нет поворота/масштаба)
        rotation_arcsec = abs(helmert_result.params.get('rotation_arcsec', 0.0))
        scale_ppm = abs(helmert_result.params.get('scale_ppm', 0.0))

        if (offset_result.success
                and rotation_arcsec < 1.0
                and scale_ppm < 1.0
                and offset_result.rmse <= helmert_result.rmse * 1.05):
            best_result = offset_result
            best_method = offset
            log_info("Fsm_0_6_2: Выбран Offset (поворот и масштаб незначительны)")

        # Проверяем: может Affine значительно лучше?
        elif (affine_result.success
              and affine_result.rmse < helmert_result.rmse * 0.8):
            best_result = affine_result
            best_method = affine
            log_info(
                f"Fsm_0_6_2: Выбран Affine "
                f"(RMSE лучше на {(1 - affine_result.rmse / helmert_result.rmse) * 100:.1f}%)"
            )
        else:
            log_info("Fsm_0_6_2: Выбран Helmert2D (конформная трансформация)")

    elif affine_result.success:
        best_result = affine_result
        best_method = affine
        log_info("Fsm_0_6_2: Выбран Affine (Helmert не сошёлся)")

    elif offset_result.success:
        log_info("Fsm_0_6_2: Выбран Offset (единственный успешный)")

    else:
        log_error("Fsm_0_6_2: Ни один метод не сошёлся")

    return (best_result, best_method)
