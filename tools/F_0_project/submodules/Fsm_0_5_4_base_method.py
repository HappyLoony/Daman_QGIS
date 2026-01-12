# -*- coding: utf-8 -*-
"""
Fsm_0_5_4 - Базовый класс для методов расчёта параметров проекции

Определяет:
- CalculationResult: dataclass для результатов расчёта
- BaseCalculationMethod: абстрактный базовый класс для всех методов

Методы расчёта (Fsm_0_5_4_X):
1. Fsm_0_5_4_1_simple_offset - Простое смещение x_0, y_0
2. Fsm_0_5_4_2_offset_meridian - Смещение + оптимизация lon_0
3. Fsm_0_5_4_3_affine - Аффинная коррекция + dS
4. Fsm_0_5_4_4_helmert_7p - Helmert 7-параметрический
5. Fsm_0_5_4_5_scikit_affine - scikit-image AffineTransform
6. Fsm_0_5_4_6_gdal_gcp - GDAL GCPsToGeoTransform
7. Fsm_0_5_4_7_projestions_api - Projestions API (онлайн)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
import math

from qgis.core import (
    QgsPointXY,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject
)

from Daman_QGIS.constants import (
    ELLPS_KRASS, TOWGS84_SK42_PROJ, RMSE_THRESHOLD_OK
)
from Daman_QGIS.utils import log_warning

# Ограничение dS (масштабный коэффициент) в ppm
# ГОСТ 32453-2017: типичный диапазон для СК-42 около -4.3..+0.55 ppm
# Допускаем ±10 ppm как разумный максимум
DS_LIMIT_PPM = 10.0


@dataclass
class CalculationResult:
    """
    Результат расчёта одного метода.

    Типы результатов (result_type):
    - "crs_params": Методы 1-8. Возвращают lon_0, x_0, y_0 для модификации CRS.
                    F_0_5 применяет эти параметры напрямую к PROJ-строке.
    - "coordinate_transform": Метод 9 (Helmert 2D). Возвращает dx, dy, scale, rotation
                              для трансформации координат. НЕ для модификации CRS напрямую.
                              Параметры в diagnostics['helmert_2d'].
    - "towgs84_only": Метод 10 (Helmert 7P LSQ). Возвращает новые параметры towgs84.
                      x_0/y_0 остаются без изменений (0.0).
                      Параметры в diagnostics['towgs84'].
    """

    # Идентификация метода
    method_name: str           # "Простое смещение", "Смещение + меридиан", ...
    method_id: str             # "simple", "meridian", "affine", "helmert", ...

    # Параметры проекции
    lon_0: float               # Центральный меридиан (градусы)
    x_0: float                 # False easting (метры)
    y_0: float                 # False northing (метры)
    towgs84_param: Optional[str] = None  # Полная строка +towgs84=... (если изменена)
    ellps_param: Optional[str] = None    # Параметр эллипсоида (если изменён)
    datum_name: Optional[str] = None     # Название определённой СК (СК-42, СК-95, ГСК-2011, ПЗ-90.11)

    # Метрики качества
    rmse: float = 0.0          # СКО (метры)
    max_error: float = 0.0     # Максимальная ошибка (метры)
    min_error: float = 0.0     # Минимальная ошибка (метры)

    # Статус
    success: bool = False      # RMSE < порога
    min_points_required: int = 1  # Минимум точек для метода

    # Тип результата (определяет как F_0_5 должен интерпретировать параметры)
    result_type: str = "crs_params"  # "crs_params" | "coordinate_transform" | "towgs84_only"

    # Диагностика (опционально)
    diagnostics: Dict = field(default_factory=dict)

    def __post_init__(self):
        """Валидация после инициализации"""
        # Проверка допустимых значений result_type
        valid_types = ("crs_params", "coordinate_transform", "towgs84_only")
        if self.result_type not in valid_types:
            raise ValueError(f"result_type должен быть одним из {valid_types}, получено: {self.result_type}")


class BaseCalculationMethod(ABC):
    """
    Базовый класс для всех методов расчёта параметров проекции.

    Каждый метод реализует:
    - name: Название для GUI
    - method_id: Уникальный идентификатор
    - min_points: Минимальное количество контрольных точек
    - description: Описание для tooltip
    - calculate(): Основной расчёт

    Опционально:
    - is_available(): Проверка доступности (для внешних библиотек)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Название метода для GUI"""
        pass

    @property
    @abstractmethod
    def method_id(self) -> str:
        """Уникальный идентификатор метода"""
        pass

    @property
    @abstractmethod
    def min_points(self) -> int:
        """Минимальное количество контрольных точек"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Описание метода для tooltip"""
        pass

    @abstractmethod
    def calculate(
        self,
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        base_params: Dict,
        initial_lon_0: float
    ) -> CalculationResult:
        """
        Выполнить расчёт параметров проекции.

        Parameters:
        -----------
        control_points_wgs84 : List[Tuple[QgsPointXY, QgsPointXY]]
            Пары (object_wgs84, reference_wgs84):
            - object_wgs84: координаты объекта в WGS84 (lon, lat)
            - reference_wgs84: эталонные координаты в WGS84 (lon, lat)
        base_params : dict
            Базовые параметры проекции:
            - lat_0: float - широта начала координат
            - k_0: float - масштабный коэффициент
            - ellps_param: str - параметр эллипсоида ("+ellps=krass")
            - towgs84_param: str - параметры трансформации
        initial_lon_0 : float
            Начальное значение центрального меридиана (градусы)

        Returns:
        --------
        CalculationResult
            Результат расчёта с параметрами проекции и метриками качества
        """
        pass

    def can_run(self, num_points: int) -> bool:
        """
        Проверка возможности запуска метода.

        Parameters:
        -----------
        num_points : int
            Количество доступных контрольных точек

        Returns:
        --------
        bool : True если метод может быть запущен
        """
        return num_points >= self.min_points

    def is_available(self) -> bool:
        """
        Проверка доступности метода.

        Переопределяется в методах, требующих внешние библиотеки
        или интернет-соединение.

        Returns:
        --------
        bool : True если метод доступен
        """
        return True

    def _calculate_rmse(self, errors: List[float]) -> float:
        """
        Вычисление СКО по списку ошибок.

        Parameters:
        -----------
        errors : List[float]
            Список ошибок (расстояний) в метрах

        Returns:
        --------
        float : СКО в метрах
        """
        if not errors:
            return 0.0
        return math.sqrt(sum(e**2 for e in errors) / len(errors))

    def _get_error_stats(self, errors: List[float]) -> Tuple[float, float, float]:
        """
        Получение статистики ошибок.

        Parameters:
        -----------
        errors : List[float]
            Список ошибок в метрах

        Returns:
        --------
        Tuple[float, float, float] : (rmse, min_error, max_error)
        """
        if not errors:
            return (0.0, 0.0, 0.0)
        return (
            self._calculate_rmse(errors),
            min(errors),
            max(errors)
        )

    # =========================================================================
    # Общие методы расчёта (используются в нескольких Fsm_0_5_4_X)
    # =========================================================================

    def _calc_offset(
        self,
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        lon_0: float,
        lat_0: float,
        k_0: float,
        ellps_param: str,
        towgs84_param: str
    ) -> Tuple[float, float, float, List[float]]:
        """
        Вычисление смещения x_0, y_0 для заданного lon_0.

        Обе точки пары трансформируются из WGS84 в тестовую МСК.
        x_0, y_0 = среднее смещение между object и reference.

        Parameters:
        -----------
        control_points_wgs84 : List[Tuple[QgsPointXY, QgsPointXY]]
            Пары (object_wgs84, reference_wgs84)
        lon_0, lat_0, k_0 : float
            Параметры проекции
        ellps_param : str
            Параметр эллипсоида (напр. "+ellps=krass")
        towgs84_param : str
            Параметры трансформации (напр. "+towgs84=...")

        Returns:
        --------
        Tuple[float, float, float, List[float]]: (x_0, y_0, rmse, errors)
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
                return (0.0, 0.0, float('inf'), [])

            transform_to_msk = QgsCoordinateTransform(
                wgs84, test_crs, QgsProject.instance()
            )

            dx_list = []
            dy_list = []
            transformed = []

            for object_wgs, reference_wgs in control_points_wgs84:
                obj_msk = transform_to_msk.transform(object_wgs)
                ref_msk = transform_to_msk.transform(reference_wgs)

                # Смещение для x_0/y_0: object - reference (инвертированный знак!)
                # Логика: x_0 в TM влияет на интерпретацию координат как f(lon) = E - x_0
                # Если obj левее ref, нужно x_0 < 0 чтобы сместить интерпретацию вправо
                dx = obj_msk.x() - ref_msk.x()
                dy = obj_msk.y() - ref_msk.y()

                dx_list.append(dx)
                dy_list.append(dy)
                transformed.append((obj_msk, ref_msk))

            x_0 = sum(dx_list) / len(dx_list)
            y_0 = sum(dy_list) / len(dy_list)

            errors = []
            for obj_msk, ref_msk in transformed:
                # После применения x_0 к CRS, интерпретация координат: f(lon) = E - x_0
                # Проверяем: obj_msk - x_0 должно совпасть с ref_msk
                adjusted_x = obj_msk.x() - x_0
                adjusted_y = obj_msk.y() - y_0
                error = math.sqrt(
                    (adjusted_x - ref_msk.x())**2 +
                    (adjusted_y - ref_msk.y())**2
                )
                errors.append(error)

            rmse = self._calculate_rmse(errors)

            return (x_0, y_0, rmse, errors)

        except Exception:
            return (0.0, 0.0, float('inf'), [])

    def _golden_section_search(
        self,
        func,
        a: float,
        b: float,
        tol: float = 1e-6,
        max_iter: int = 100
    ) -> Dict:
        """
        Поиск минимума функции методом золотого сечения.

        Parameters:
        -----------
        func : callable
            Функция одной переменной для минимизации
        a : float
            Левая граница интервала
        b : float
            Правая граница интервала
        tol : float
            Точность (по умолчанию 1e-6)
        max_iter : int
            Максимальное число итераций

        Returns:
        --------
        dict : {'x': float, 'value': float, 'iterations': int}
        """
        phi = (1 + math.sqrt(5)) / 2
        resphi = 2 - phi

        x1 = a + resphi * (b - a)
        x2 = b - resphi * (b - a)
        f1 = func(x1)
        f2 = func(x2)

        iterations = 0

        while abs(b - a) > tol and iterations < max_iter:
            iterations += 1

            if f1 < f2:
                b = x2
                x2 = x1
                f2 = f1
                x1 = a + resphi * (b - a)
                f1 = func(x1)
            else:
                a = x1
                x1 = x2
                f1 = f2
                x2 = b - resphi * (b - a)
                f2 = func(x2)

        x_min = (a + b) / 2

        return {
            'x': x_min,
            'value': func(x_min),
            'iterations': iterations
        }

    def _extract_dS(self, towgs84_param: str) -> float:
        """
        Извлечение dS (масштабный коэффициент) из строки towgs84.

        Parameters:
        -----------
        towgs84_param : str
            Строка вида "+towgs84=dX,dY,dZ,rX,rY,rZ,dS"

        Returns:
        --------
        float : Значение dS (ppm), по умолчанию -0.22 для СК-42
        """
        if '+towgs84=' in towgs84_param:
            parts = towgs84_param.replace('+towgs84=', '').split(',')
            if len(parts) >= 7:
                return float(parts[6])
        return -0.22

    def _update_towgs84_dS(self, towgs84_param: str, new_dS: float) -> str:
        """
        Обновление dS в строке towgs84 с ограничением ±DS_LIMIT_PPM.

        Parameters:
        -----------
        towgs84_param : str
            Исходная строка towgs84
        new_dS : float
            Новое значение dS (ppm)

        Returns:
        --------
        str : Обновлённая строка towgs84

        Note:
        -----
        Если |new_dS| > DS_LIMIT_PPM, значение ограничивается и выводится warning.
        Типичный диапазон для СК-42: -4.3..+0.55 ppm (ГОСТ 32453-2017).
        """
        # Ограничение dS в пределах ±DS_LIMIT_PPM
        original_dS = new_dS
        if abs(new_dS) > DS_LIMIT_PPM:
            new_dS = max(-DS_LIMIT_PPM, min(DS_LIMIT_PPM, new_dS))
            log_warning(
                f"BaseCalculationMethod: dS={original_dS:.2f}ppm превышает лимит "
                f"±{DS_LIMIT_PPM}ppm, ограничено до {new_dS:.2f}ppm"
            )

        if '+towgs84=' in towgs84_param:
            parts = towgs84_param.replace('+towgs84=', '').split(',')
            if len(parts) >= 7:
                parts[6] = f"{new_dS:.4f}"
                return '+towgs84=' + ','.join(parts)
        # Если towgs84 отсутствует - возвращаем исходную строку
        return towgs84_param

    def _calculate_affine_params(
        self,
        src_points: List[Tuple[float, float]],
        dst_points: List[Tuple[float, float]]
    ) -> Dict:
        """
        Вычисление параметров аффинной трансформации методом наименьших квадратов.

        Similarity transform: rotation + uniform scale + translation.

        Parameters:
        -----------
        src_points : List[Tuple[float, float]]
            Исходные точки (object)
        dst_points : List[Tuple[float, float]]
            Целевые точки (reference)

        Returns:
        --------
        dict : {
            'rotation_deg': float,  # Угол поворота в градусах
            'scale': float,         # Масштабный коэффициент
            'tx': float,            # Смещение по X
            'ty': float             # Смещение по Y
        }
        """
        n = len(src_points)
        if n < 2:
            return {'rotation_deg': 0.0, 'scale': 1.0, 'tx': 0.0, 'ty': 0.0}

        # Центры масс
        src_cx = sum(p[0] for p in src_points) / n
        src_cy = sum(p[1] for p in src_points) / n
        dst_cx = sum(p[0] for p in dst_points) / n
        dst_cy = sum(p[1] for p in dst_points) / n

        # Центрированные координаты
        src_centered = [(p[0] - src_cx, p[1] - src_cy) for p in src_points]
        dst_centered = [(p[0] - dst_cx, p[1] - dst_cy) for p in dst_points]

        # Суммы для ковариации
        sxx = sum(s[0] * d[0] for s, d in zip(src_centered, dst_centered))
        sxy = sum(s[0] * d[1] for s, d in zip(src_centered, dst_centered))
        syx = sum(s[1] * d[0] for s, d in zip(src_centered, dst_centered))
        syy = sum(s[1] * d[1] for s, d in zip(src_centered, dst_centered))

        # Сумма квадратов исходных координат
        ss = sum(s[0]**2 + s[1]**2 for s in src_centered)

        if ss < 1e-10:
            return {'rotation_deg': 0.0, 'scale': 1.0, 'tx': 0.0, 'ty': 0.0}

        # Параметры similarity transform
        a = (sxx + syy) / ss
        b = (syx - sxy) / ss

        # Масштаб и угол
        scale = math.sqrt(a**2 + b**2)
        rotation_rad = math.atan2(b, a)
        rotation_deg = math.degrees(rotation_rad)

        # Смещение
        tx = dst_cx - scale * (math.cos(rotation_rad) * src_cx - math.sin(rotation_rad) * src_cy)
        ty = dst_cy - scale * (math.sin(rotation_rad) * src_cx + math.cos(rotation_rad) * src_cy)

        return {
            'rotation_deg': rotation_deg,
            'scale': scale,
            'tx': tx,
            'ty': ty
        }

    def _calculate_lon0_correction(
        self,
        rotation_deg: float,
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]]
    ) -> float:
        """
        Вычисление коррекции центрального меридиана на основе угла поворота.

        Формула основана на теории сходимости меридианов (grid convergence):
        γ = arctan[tan(λ - λ₀) × sin(φ)]

        Для малых углов: Δλ ≈ γ / sin(φ)

        Parameters:
        -----------
        rotation_deg : float
            Угол поворота в градусах (из аффинной трансформации)
        control_points_wgs84 : List[Tuple[QgsPointXY, QgsPointXY]]
            Контрольные точки в WGS84 для вычисления средней широты

        Returns:
        --------
        float : Коррекция lon_0 в градусах

        References:
        -----------
        - Grid Convergence: https://gis.stackexchange.com/questions/115531
        - Meridian Convergence: https://geomathiks.com/meridian-convergence/
        """
        if not control_points_wgs84:
            return 0.0

        # Вычисляем среднюю широту по reference точкам (более надёжные)
        lat_sum = 0.0
        for _, reference_wgs in control_points_wgs84:
            lat_sum += reference_wgs.y()  # y() = широта в WGS84

        lat_avg_deg = lat_sum / len(control_points_wgs84)
        lat_avg_rad = math.radians(lat_avg_deg)

        # Защита от деления на ноль (экватор)
        sin_lat = math.sin(lat_avg_rad)
        if abs(sin_lat) < 0.1:  # Широты < ~6° - редкость для России
            sin_lat = 0.1

        # Формула: Δλ = -γ / sin(φ)
        # Знак минус: поворот по часовой стрелке требует увеличения lon_0
        lon_0_correction = -rotation_deg / sin_lat

        return lon_0_correction

    def _create_msk_transform(
        self,
        lon_0: float,
        lat_0: float,
        k_0: float,
        ellps_param: str,
        towgs84_param: str
    ) -> Optional[Tuple[QgsCoordinateReferenceSystem, QgsCoordinateTransform]]:
        """
        Создание CRS и трансформа WGS84 -> МСК.

        Parameters:
        -----------
        lon_0, lat_0, k_0 : float
            Параметры проекции
        ellps_param : str
            Параметр эллипсоида (напр. "+ellps=krass")
        towgs84_param : str
            Параметры трансформации (напр. "+towgs84=...")

        Returns:
        --------
        Optional[Tuple[CRS, Transform]] : (test_crs, transform_to_msk) или None если CRS невалидна
        """
        try:
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")

            proj_string = (
                f"+proj=tmerc +lat_0={lat_0} +lon_0={lon_0} +k_0={k_0} "
                f"+x_0=0 +y_0=0 {ellps_param} {towgs84_param} +units=m +no_defs"
            )
            test_crs = QgsCoordinateReferenceSystem()
            test_crs.createFromProj(proj_string)

            if not test_crs.isValid():
                return None

            transform_to_msk = QgsCoordinateTransform(
                wgs84, test_crs, QgsProject.instance()
            )

            return (test_crs, transform_to_msk)

        except Exception:
            return None

    def _transform_points_to_msk(
        self,
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        transform: QgsCoordinateTransform
    ) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
        """
        Трансформация контрольных точек из WGS84 в МСК.

        Parameters:
        -----------
        control_points_wgs84 : List[Tuple[QgsPointXY, QgsPointXY]]
            Пары (object_wgs84, reference_wgs84)
        transform : QgsCoordinateTransform
            Трансформ WGS84 -> МСК

        Returns:
        --------
        Tuple[List, List] : (obj_points_msk, ref_points_msk)
            Списки кортежей (x, y) в метрах
        """
        obj_points = []
        ref_points = []

        for object_wgs, reference_wgs in control_points_wgs84:
            obj_msk = transform.transform(object_wgs)
            ref_msk = transform.transform(reference_wgs)
            obj_points.append((obj_msk.x(), obj_msk.y()))
            ref_points.append((ref_msk.x(), ref_msk.y()))

        return (obj_points, ref_points)
