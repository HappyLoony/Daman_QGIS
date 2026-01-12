# -*- coding: utf-8 -*-
"""
Fsm_0_5_4_10 - Полный Helmert 7P LSQ (с H=0)

Полная 7-параметрическая трансформация Helmert (Bursa-Wolf) с расчётом
всех параметров towgs84 методом наименьших квадратов.

Параметры: dX, dY, dZ, rX, rY, rZ, dS (7 параметров)

Минимум: 3 точки (даёт 9 уравнений для 7 неизвестных)
Рекомендуется: 4+ точки для контроля качества

ВАЖНО: Работает с 2D координатами (lat, lon), высота принимается = 0.
Это вносит ошибку < 1 метра для точек близких к поверхности Земли.

Алгоритм:
1. Конвертация lat, lon -> XYZ (геоцентрические, H=0)
2. LSQ для 7 параметров Helmert
3. Формирование towgs84 строки для PROJ

Формула Helmert:
    [X']   [dX]   [1    -rZ   rY ] [X]
    [Y'] = [dY] + [rZ    1   -rX ] [Y] * (1 + dS)
    [Z']   [dZ]   [-rY   rX   1  ] [Z]

Источники:
- ГОСТ 32453-2017: Глобальная навигационная спутниковая система
- https://en.wikipedia.org/wiki/Helmert_transformation
- https://www.geometrictools.com/Documentation/HelmertTransformation.pdf
"""

import math
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass

from qgis.core import QgsPointXY

from .Fsm_0_5_4_base_method import BaseCalculationMethod, CalculationResult
from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.constants import (
    ELLIPSOID_KRASS_A, ELLIPSOID_KRASS_F,
    ELLIPSOID_WGS84_A, ELLIPSOID_WGS84_F
)


@dataclass
class Helmert7PResult:
    """Результат 7P Helmert трансформации."""
    dX: float  # Смещение по X (метры)
    dY: float  # Смещение по Y (метры)
    dZ: float  # Смещение по Z (метры)
    rX: float  # Поворот вокруг X (угловые секунды)
    rY: float  # Поворот вокруг Y (угловые секунды)
    rZ: float  # Поворот вокруг Z (угловые секунды)
    dS: float  # Масштаб (ppm, 10^-6)
    rmse: float  # RMSE (метры)
    residuals: List[float]  # Остатки для каждой точки
    towgs84_string: str  # Готовая строка для PROJ
    success: bool


class Fsm_0_5_4_10_Helmert7PLSQ(BaseCalculationMethod):
    """
    Полный Helmert 7P с LSQ расчётом всех параметров.

    Конвертирует 2D координаты (lat, lon) в 3D (XYZ) с H=0,
    затем вычисляет 7 параметров методом наименьших квадратов.

    Минимум: 3 точки
    """

    # Эллипсоиды
    # Красовского (СК-42, МСК)
    KRASS_A = ELLIPSOID_KRASS_A
    KRASS_F = ELLIPSOID_KRASS_F
    KRASS_E2 = 2 * KRASS_F - KRASS_F ** 2

    # WGS-84
    WGS84_A = ELLIPSOID_WGS84_A
    WGS84_F = ELLIPSOID_WGS84_F
    WGS84_E2 = 2 * WGS84_F - WGS84_F ** 2

    @property
    def name(self) -> str:
        return "Helmert 7P LSQ"

    @property
    def method_id(self) -> str:
        return "helmert_7p_lsq"

    @property
    def min_points(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "Полный Helmert 7P: расчёт всех параметров towgs84 (H=0)"

    def calculate(
        self,
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        base_params: Dict,
        initial_lon_0: float
    ) -> CalculationResult:
        """
        Расчёт 7 параметров Helmert методом наименьших квадратов.

        Parameters:
            control_points_wgs84: Пары (object_wgs84, reference_wgs84)
                - object: точки в исходной системе (СК-42/МСК)
                - reference: точки в целевой системе (WGS-84 эталон)
            base_params: Параметры проекции
            initial_lon_0: Начальный центральный меридиан

        Returns:
            CalculationResult с параметрами в diagnostics['helmert_7p']
        """
        if len(control_points_wgs84) < self.min_points:
            log_warning(f"Fsm_0_5_4_10: Нужно минимум {self.min_points} точек")
            return self._error_result(initial_lon_0)

        try:
            # Конвертируем точки в XYZ
            # object -> XYZ на эллипсоиде Красовского (источник)
            # reference -> XYZ на эллипсоиде WGS-84 (цель)

            src_xyz = []  # Исходные точки (Красовский)
            dst_xyz = []  # Целевые точки (WGS-84)

            for object_wgs, reference_wgs in control_points_wgs84:
                # object_wgs - это координаты в "неправильной" системе
                # которые нужно трансформировать в WGS-84
                src = self._geodetic_to_xyz(
                    object_wgs.y(), object_wgs.x(), 0.0,
                    self.KRASS_A, self.KRASS_E2
                )
                src_xyz.append(src)

                # reference_wgs - это "правильные" координаты WGS-84
                dst = self._geodetic_to_xyz(
                    reference_wgs.y(), reference_wgs.x(), 0.0,
                    self.WGS84_A, self.WGS84_E2
                )
                dst_xyz.append(dst)

            # Расчёт 7 параметров LSQ
            helmert_result = self.calculate_helmert_7p_lsq(src_xyz, dst_xyz)

            if not helmert_result.success:
                return self._error_result(initial_lon_0)

            log_info(
                f"Fsm_0_5_4_10 [{self.method_id}]: "
                f"dX={helmert_result.dX:.2f} dY={helmert_result.dY:.2f} dZ={helmert_result.dZ:.2f} "
                f"rX={helmert_result.rX:.4f}\" rY={helmert_result.rY:.4f}\" rZ={helmert_result.rZ:.4f}\" "
                f"dS={helmert_result.dS:.4f}ppm RMSE={helmert_result.rmse:.4f}m"
            )
            log_info(f"Fsm_0_5_4_10: towgs84={helmert_result.towgs84_string}")

            # Для F_0_5: lon_0 не меняется, x_0/y_0 = 0
            # Вся коррекция в towgs84
            return CalculationResult(
                method_name=self.name,
                method_id=self.method_id,
                lon_0=initial_lon_0,
                x_0=0.0,
                y_0=0.0,
                rmse=helmert_result.rmse,
                min_error=min(helmert_result.residuals) if helmert_result.residuals else 0.0,
                max_error=max(helmert_result.residuals) if helmert_result.residuals else 0.0,
                success=helmert_result.success,
                min_points_required=self.min_points,
                result_type="towgs84_only",  # Только коррекция towgs84, не CRS params
                diagnostics={
                    'helmert_7p': {
                        'dX': helmert_result.dX,
                        'dY': helmert_result.dY,
                        'dZ': helmert_result.dZ,
                        'rX': helmert_result.rX,
                        'rY': helmert_result.rY,
                        'rZ': helmert_result.rZ,
                        'dS': helmert_result.dS,
                    },
                    'towgs84': helmert_result.towgs84_string,
                    'towgs84_proj': f'+towgs84={helmert_result.towgs84_string}',
                    'residuals': helmert_result.residuals,
                    'convention': 'Position Vector (EPSG:9606)',
                    'note': 'H=0 approximation, accuracy < 1m'
                }
            )

        except Exception as e:
            log_error(f"Fsm_0_5_4_10: Ошибка расчёта: {e}")
            return self._error_result(initial_lon_0)

    def calculate_helmert_7p_lsq(
        self,
        src_xyz: List[Tuple[float, float, float]],
        dst_xyz: List[Tuple[float, float, float]]
    ) -> Helmert7PResult:
        """
        Расчёт 7 параметров Helmert методом наименьших квадратов.

        Линеаризованная модель:
            X' - X = dX + Y*rZ - Z*rY + X*dS
            Y' - Y = dY - X*rZ + Z*rX + Y*dS
            Z' - Z = dZ + X*rY - Y*rX + Z*dS

        Parameters:
            src_xyz: Исходные точки [(X1,Y1,Z1), ...]
            dst_xyz: Целевые точки [(X1',Y1',Z1'), ...]

        Returns:
            Helmert7PResult с 7 параметрами
        """
        n = len(src_xyz)

        if n < 3:
            return Helmert7PResult(
                dX=0, dY=0, dZ=0, rX=0, rY=0, rZ=0, dS=0,
                rmse=float('inf'), residuals=[], towgs84_string='',
                success=False
            )

        # Построение матрицы коэффициентов A (n*3 x 7) и вектора L (n*3)
        # Без numpy - используем списки

        # Матрица A: каждая точка даёт 3 строки
        A = []
        L = []

        for (X, Y, Z), (Xp, Yp, Zp) in zip(src_xyz, dst_xyz):
            # Уравнение для X: dX + 0*dY + 0*dZ + 0*rX - Z*rY + Y*rZ + X*dS = Xp - X
            A.append([1, 0, 0, 0, -Z, Y, X])
            L.append(Xp - X)

            # Уравнение для Y: 0*dX + dY + 0*dZ + Z*rX + 0*rY - X*rZ + Y*dS = Yp - Y
            A.append([0, 1, 0, Z, 0, -X, Y])
            L.append(Yp - Y)

            # Уравнение для Z: 0*dX + 0*dY + dZ - Y*rX + X*rY + 0*rZ + Z*dS = Zp - Z
            A.append([0, 0, 1, -Y, X, 0, Z])
            L.append(Zp - Z)

        # Решение нормальных уравнений: A^T * A * x = A^T * L
        # x = (A^T * A)^-1 * A^T * L

        # A^T * A (7x7)
        ATA = self._matrix_mult_transpose_left(A, A)

        # A^T * L (7x1)
        ATL = self._matrix_vector_mult_transpose(A, L)

        # Решение системы (обращение матрицы 7x7)
        try:
            ATA_inv = self._matrix_inverse_7x7(ATA)
            x = self._matrix_vector_mult(ATA_inv, ATL)
        except Exception:
            log_warning("Fsm_0_5_4_10: Матрица вырождена, LSQ не сходится")
            return Helmert7PResult(
                dX=0, dY=0, dZ=0, rX=0, rY=0, rZ=0, dS=0,
                rmse=float('inf'), residuals=[], towgs84_string='',
                success=False
            )

        # Извлечение параметров
        dX = x[0]
        dY = x[1]
        dZ = x[2]
        rX_rad = x[3]  # радианы
        rY_rad = x[4]
        rZ_rad = x[5]
        dS_pure = x[6]  # безразмерный

        # Конвертация единиц:
        # rX, rY, rZ: радианы -> угловые секунды
        rX_arcsec = math.degrees(rX_rad) * 3600
        rY_arcsec = math.degrees(rY_rad) * 3600
        rZ_arcsec = math.degrees(rZ_rad) * 3600

        # dS: безразмерный -> ppm
        dS_ppm = dS_pure * 1e6

        # Вычисление остатков
        residuals = []
        for i, ((x, y, z), (xp, yp, zp)) in enumerate(zip(src_xyz, dst_xyz)):
            # Применяем трансформацию
            xt = dX + (1 + dS_pure) * (x - rZ_rad * y + rY_rad * z)
            yt = dY + (1 + dS_pure) * (rZ_rad * x + y - rX_rad * z)
            zt = dZ + (1 + dS_pure) * (-rY_rad * x + rX_rad * y + z)

            residual = math.sqrt((xt - xp)**2 + (yt - yp)**2 + (zt - zp)**2)
            residuals.append(residual)

        rmse = self._calculate_rmse(residuals)

        # Формирование towgs84 строки (Position Vector)
        towgs84_string = (
            f"{dX:.4f},{dY:.4f},{dZ:.4f},"
            f"{rX_arcsec:.6f},{rY_arcsec:.6f},{rZ_arcsec:.6f},"
            f"{dS_ppm:.6f}"
        )

        return Helmert7PResult(
            dX=dX,
            dY=dY,
            dZ=dZ,
            rX=rX_arcsec,
            rY=rY_arcsec,
            rZ=rZ_arcsec,
            dS=dS_ppm,
            rmse=rmse,
            residuals=residuals,
            towgs84_string=towgs84_string,
            success=True
        )

    def _geodetic_to_xyz(
        self,
        lat_deg: float,
        lon_deg: float,
        h: float,
        a: float,
        e2: float
    ) -> Tuple[float, float, float]:
        """
        Конвертация геодезических координат в геоцентрические XYZ.

        Parameters:
            lat_deg: Широта (градусы)
            lon_deg: Долгота (градусы)
            h: Эллипсоидная высота (метры)
            a: Большая полуось эллипсоида
            e2: Квадрат эксцентриситета

        Returns:
            (X, Y, Z): Геоцентрические координаты (метры)
        """
        lat = math.radians(lat_deg)
        lon = math.radians(lon_deg)

        sin_lat = math.sin(lat)
        cos_lat = math.cos(lat)
        sin_lon = math.sin(lon)
        cos_lon = math.cos(lon)

        # Радиус кривизны в первом вертикале
        N = a / math.sqrt(1 - e2 * sin_lat ** 2)

        X = (N + h) * cos_lat * cos_lon
        Y = (N + h) * cos_lat * sin_lon
        Z = (N * (1 - e2) + h) * sin_lat

        return (X, Y, Z)

    def _xyz_to_geodetic(
        self,
        X: float,
        Y: float,
        Z: float,
        a: float,
        e2: float,
        iterations: int = 10
    ) -> Tuple[float, float, float]:
        """
        Конвертация геоцентрических XYZ в геодезические координаты.

        Итерационный алгоритм Боуринга.

        Returns:
            (lat_deg, lon_deg, h): Геодезические координаты
        """
        lon = math.atan2(Y, X)
        p = math.sqrt(X**2 + Y**2)

        # Начальное приближение
        lat = math.atan2(Z, p * (1 - e2))

        for _ in range(iterations):
            sin_lat = math.sin(lat)
            n_radius = a / math.sqrt(1 - e2 * sin_lat**2)
            lat = math.atan2(Z + e2 * n_radius * sin_lat, p)

        sin_lat = math.sin(lat)
        cos_lat = math.cos(lat)
        n_radius = a / math.sqrt(1 - e2 * sin_lat**2)

        if abs(cos_lat) > 1e-10:
            h = p / cos_lat - n_radius
        else:
            h = abs(Z) / abs(sin_lat) - n_radius * (1 - e2)

        return (math.degrees(lat), math.degrees(lon), h)

    # --- Матричные операции без numpy ---

    def _matrix_mult_transpose_left(
        self,
        A: List[List[float]],
        B: List[List[float]]
    ) -> List[List[float]]:
        """Вычисление A^T * B."""
        m = len(A[0])  # столбцы A = строки A^T
        n = len(B[0])  # столбцы B
        k = len(A)     # строки A = столбцы A^T

        result = [[0.0] * n for _ in range(m)]

        for i in range(m):
            for j in range(n):
                for l in range(k):
                    result[i][j] += A[l][i] * B[l][j]

        return result

    def _matrix_vector_mult_transpose(
        self,
        A: List[List[float]],
        v: List[float]
    ) -> List[float]:
        """Вычисление A^T * v."""
        m = len(A[0])  # столбцы A = строки A^T
        k = len(A)     # строки A

        result = [0.0] * m

        for i in range(m):
            for l in range(k):
                result[i] += A[l][i] * v[l]

        return result

    def _matrix_vector_mult(
        self,
        A: List[List[float]],
        v: List[float]
    ) -> List[float]:
        """Вычисление A * v."""
        m = len(A)
        n = len(v)

        result = [0.0] * m

        for i in range(m):
            for j in range(n):
                result[i] += A[i][j] * v[j]

        return result

    def _matrix_inverse_7x7(self, A: List[List[float]]) -> List[List[float]]:
        """
        Обращение матрицы 7x7 методом Гаусса-Жордана.

        Raises:
            ValueError: Если матрица вырождена
        """
        n = 7
        # Создаём расширенную матрицу [A | I]
        aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(A)]

        # Прямой ход
        for col in range(n):
            # Поиск ведущего элемента
            max_row = col
            for row in range(col + 1, n):
                if abs(aug[row][col]) > abs(aug[max_row][col]):
                    max_row = row

            aug[col], aug[max_row] = aug[max_row], aug[col]

            if abs(aug[col][col]) < 1e-12:
                raise ValueError("Матрица вырождена")

            # Нормализация строки
            pivot = aug[col][col]
            for j in range(2 * n):
                aug[col][j] /= pivot

            # Обнуление столбца
            for row in range(n):
                if row != col:
                    factor = aug[row][col]
                    for j in range(2 * n):
                        aug[row][j] -= factor * aug[col][j]

        # Извлечение обратной матрицы
        inv = [row[n:] for row in aug]
        return inv

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
