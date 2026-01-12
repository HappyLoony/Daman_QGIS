# -*- coding: utf-8 -*-
"""
Fsm_0_5_3 - Оптимизатор параметров проекции
Расчет оптимальных параметров Transverse Mercator для минимизации искажений

Включает:
- calculate_optimal_meridian() - lon_0 из центра extent
- optimize_lon_0_iterative() - итеративный подбор lon_0 по контрольным точкам
- run_all_methods() - запуск всех доступных методов расчёта

Методы расчёта (Fsm_0_5_4_X):
1. SimpleOffset - простое смещение x_0, y_0 (1+ точка)
2. OffsetMeridian - смещение + оптимизация lon_0 (2+ точки)
3. Affine - аффинная коррекция + dS (3+ точки)
4. Helmert7P - 7-параметрическая трансформация (3+ точки)
5. ScikitAffine - scikit-image AffineTransform (3+ точки, опционально)
6. GdalGcp - GDAL GCPsToGeoTransform (3+ точки, опционально)
7. ProjectionsApi - онлайн API projest.io (1+ точка, опционально)
8. FullScan - полный перебор всех методов × всех СК (до 28 комбинаций)
9. Helmert2D - 2D Helmert (4P): dx, dy, scale, rotation (2+ точки)
10. Helmert7PLSQ - Helmert 7P LSQ: расчёт всех 7 параметров towgs84 (3+ точки)
"""

import math
from typing import Tuple, List, Dict, Optional

from qgis.core import QgsPointXY, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject

from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.constants import (
    ELLIPSOID_KRASS_A, ELLIPSOID_KRASS_F,
    ELLIPSOID_WGS84_A,
    ELLPS_KRASS,
    TOWGS84_SK42, TOWGS84_SK42_PROJ,
    RMSE_THRESHOLD_OK
)

# Импорт методов расчёта
from .Fsm_0_5_4_base_method import BaseCalculationMethod, CalculationResult
from .Fsm_0_5_4_1_simple_offset import Fsm_0_5_4_1_SimpleOffset
from .Fsm_0_5_4_2_offset_meridian import Fsm_0_5_4_2_OffsetMeridian
from .Fsm_0_5_4_3_affine import Fsm_0_5_4_3_Affine
from .Fsm_0_5_4_4_helmert_7p import Fsm_0_5_4_4_Helmert7P
from .Fsm_0_5_4_5_scikit_affine import Fsm_0_5_4_5_ScikitAffine
from .Fsm_0_5_4_6_gdal_gcp import Fsm_0_5_4_6_GdalGcp
from .Fsm_0_5_4_7_projestions_api import Fsm_0_5_4_7_ProjectionsApi
from .Fsm_0_5_4_8_datum_detector import Fsm_0_5_4_8_DatumDetector
from .Fsm_0_5_4_9_helmert_2d import Fsm_0_5_4_9_Helmert2D
from .Fsm_0_5_4_10_helmert_7p_lsq import Fsm_0_5_4_10_Helmert7PLSQ


class ProjectionOptimizer:
    """Оптимизация параметров проекции для межзональных объектов"""

    # Константы из constants.py
    EARTH_RADIUS_KM = ELLIPSOID_WGS84_A / 1000.0  # Большая полуось WGS84 в км
    # ГОСТ 32453-2017: параметры эллипсоида Красовского
    KRASS_A = ELLIPSOID_KRASS_A  # Большая полуось
    KRASS_F = ELLIPSOID_KRASS_F  # Сжатие
    
    def __init__(self):
        """Инициализация оптимизатора"""
        self.krass_b = self.KRASS_A * (1 - self.KRASS_F)  # Малая полуось
        self.krass_e2 = 2 * self.KRASS_F - self.KRASS_F**2  # Квадрат эксцентриситета

        # Инициализация методов расчёта
        self._methods: List[BaseCalculationMethod] = [
            Fsm_0_5_4_1_SimpleOffset(),
            Fsm_0_5_4_2_OffsetMeridian(),
            Fsm_0_5_4_3_Affine(),
            Fsm_0_5_4_4_Helmert7P(),
            Fsm_0_5_4_5_ScikitAffine(),
            Fsm_0_5_4_6_GdalGcp(),
            Fsm_0_5_4_7_ProjectionsApi(),
            Fsm_0_5_4_8_DatumDetector(),
            Fsm_0_5_4_9_Helmert2D(),
            Fsm_0_5_4_10_Helmert7PLSQ(),
        ]

    def get_available_methods(self) -> List[BaseCalculationMethod]:
        """
        Получить список доступных методов.

        Фильтрует методы по is_available() - исключает те,
        для которых нет зависимостей (scikit-image, GDAL, интернет).

        Returns:
        --------
        List[BaseCalculationMethod] : Список доступных методов
        """
        return [m for m in self._methods if m.is_available()]

    def get_runnable_methods(self, num_points: int) -> List[BaseCalculationMethod]:
        """
        Получить список методов, которые можно запустить с данным количеством точек.

        Parameters:
        -----------
        num_points : int
            Количество контрольных точек

        Returns:
        --------
        List[BaseCalculationMethod] : Список методов с min_points <= num_points
        """
        return [m for m in self.get_available_methods() if m.can_run(num_points)]

    def run_all_methods(
        self,
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        base_params: Dict,
        initial_lon_0: float,
        include_optional: bool = True
    ) -> List[CalculationResult]:
        """
        Запуск всех доступных методов расчёта параметров проекции.

        Выполняет все методы, для которых достаточно контрольных точек.
        Результаты сортируются по RMSE (лучший первый).

        Parameters:
        -----------
        control_points_wgs84 : List[Tuple[QgsPointXY, QgsPointXY]]
            Пары (object_wgs84, reference_wgs84):
            - object_wgs84: координаты объекта в WGS84 (lon, lat)
            - reference_wgs84: эталонные координаты в WGS84 (lon, lat)
        base_params : Dict
            Базовые параметры проекции:
            - lat_0: float - широта начала координат
            - k_0: float - масштабный коэффициент
            - ellps_param: str - параметр эллипсоида ("+ellps=krass")
            - towgs84_param: str - параметры трансформации
        initial_lon_0 : float
            Начальное значение центрального меридиана (градусы)
        include_optional : bool
            Включать опциональные методы (scikit, GDAL, API)

        Returns:
        --------
        List[CalculationResult] : Список результатов, отсортированных по RMSE
        """
        num_points = len(control_points_wgs84)
        log_info(f"Fsm_0_5_3: Запуск всех методов, точек: {num_points}")

        if num_points < 1:
            log_error("Fsm_0_5_3: Нет контрольных точек для расчёта")
            return []

        results: List[CalculationResult] = []

        # Определяем какие методы запускать
        if include_optional:
            methods_to_run = self.get_runnable_methods(num_points)
        else:
            # Только базовые методы (первые 4)
            methods_to_run = [
                m for m in self._methods[:4]
                if m.can_run(num_points)
            ]

        log_info(f"Fsm_0_5_3: Методов к запуску: {len(methods_to_run)}")

        for method in methods_to_run:
            try:
                result = method.calculate(
                    control_points_wgs84,
                    base_params,
                    initial_lon_0
                )
                results.append(result)
            except Exception as e:
                log_error(f"Fsm_0_5_3: Ошибка в методе {method.name}: {e}")
                # Добавляем результат с ошибкой
                results.append(CalculationResult(
                    method_name=method.name,
                    method_id=method.method_id,
                    lon_0=initial_lon_0,
                    x_0=0.0,
                    y_0=0.0,
                    rmse=float('inf'),
                    success=False,
                    min_points_required=method.min_points,
                    diagnostics={'error': str(e)}
                ))

        # Сортируем по RMSE (лучший первый)
        results.sort(key=lambda r: r.rmse)

        # Выводим сводку
        log_info("Fsm_0_5_3: Результаты всех методов:")
        for i, r in enumerate(results):
            status = "OK" if r.success else "WARN"
            log_info(
                f"  {i+1}. {r.method_name} ({r.method_id}): "
                f"RMSE={r.rmse:.4f}m [{status}]"
            )

        return results

    def get_best_result(
        self,
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        base_params: Dict,
        initial_lon_0: float,
        include_optional: bool = True
    ) -> Optional[CalculationResult]:
        """
        Получить лучший результат из всех методов.

        Parameters:
        -----------
        (см. run_all_methods)

        Returns:
        --------
        CalculationResult или None если нет успешных результатов
        """
        results = self.run_all_methods(
            control_points_wgs84, base_params, initial_lon_0, include_optional
        )

        if not results:
            return None

        # Возвращаем лучший (первый после сортировки по RMSE)
        best = results[0]

        if best.success:
            log_info(
                f"Fsm_0_5_3: Лучший метод: {best.method_name} "
                f"(RMSE={best.rmse:.4f}m)"
            )
        else:
            log_warning(
                f"Fsm_0_5_3: Нет успешных результатов. "
                f"Лучший: {best.method_name} (RMSE={best.rmse:.4f}m)"
            )

        return best
        
    def calculate_optimal_meridian(self, min_lon: float, max_lon: float) -> float:
        """
        Расчет оптимального центрального меридиана
        
        Parameters:
        -----------
        min_lon : float
            Минимальная долгота объекта (градусы)
        max_lon : float
            Максимальная долгота объекта (градусы)
            
        Returns:
        --------
        float : Оптимальный центральный меридиан (градусы)
        """
        # Обработка пересечения 180-го меридиана
        if max_lon < min_lon:
            central_lon = ((min_lon + max_lon + 360) / 2) % 360
            if central_lon > 180:
                central_lon -= 360
        else:
            central_lon = (min_lon + max_lon) / 2
            
        log_info(f"Fsm_0_5_3: Оптимальный центральный меридиан: {central_lon:.6f}°")
        return central_lon
        
    def calculate_optimal_scale_factor(self, extent_from_meridian_km: float) -> float:
        """
        Расчет оптимального масштабного коэффициента для минимизации искажений
        
        Parameters:
        -----------
        extent_from_meridian_km : float
            Максимальное расстояние от центрального меридиана в км
            
        Returns:
        --------
        float : Оптимальный масштабный коэффициент k_0
        """
        # Для малых объектов (<50 км) используем k_0 = 1.0
        if extent_from_meridian_km < 50:
            return 1.0
            
        # Для средних объектов (50-200 км) - слабая оптимизация
        if extent_from_meridian_km < 200:
            # Формула для двух стандартных линий
            # k_0 выбирается так, чтобы линии истинного масштаба
            # находились примерно на 2/3 расстояния от центра
            extent_degrees = math.degrees(extent_from_meridian_km / self.EARTH_RADIUS_KM)
            k_optimal = math.cos(math.radians(extent_degrees * 0.67))
            return max(0.9996, k_optimal)  # Не меньше стандартного UTM
            
        # Для больших объектов (>200 км) - стандартный UTM коэффициент
        return 0.9996

    def estimate_distortion(
        self,
        central_meridian: float,
        scale_factor: float,
        bounds: Tuple[float, float],
        central_latitude: float
    ) -> float:
        """
        Оценка максимального искажения для заданных параметров проекции
        
        Parameters:
        -----------
        central_meridian : float
            Центральный меридиан (градусы)
        scale_factor : float
            Масштабный коэффициент k_0
        bounds : Tuple[float, float]
            (min_lon, max_lon) границы объекта
        central_latitude : float
            Средняя широта объекта (градусы)
            
        Returns:
        --------
        float : Максимальное искажение в ppm (частей на миллион)
        """
        # Максимальное отклонение от центрального меридиана
        max_delta_lon = max(
            abs(bounds[0] - central_meridian),
            abs(bounds[1] - central_meridian)
        )
        
        # Преобразуем в радианы
        delta_lon_rad = math.radians(max_delta_lon)
        lat_rad = math.radians(central_latitude)
        
        # Упрощенная формула искажения для Transverse Mercator
        # k = k_0 * (1 + (delta_lon^2 * cos^2(lat)) / 2)
        cos_lat = math.cos(lat_rad)
        k_at_edge = scale_factor * (1 + (delta_lon_rad**2 * cos_lat**2) / 2)
        
        # Искажение в ppm
        distortion_ppm = abs(k_at_edge - 1.0) * 1e6

        return distortion_ppm

    # =========================================================================
    # Итеративный подбор lon_0 по контрольным точкам
    # =========================================================================

    def _analyze_transformation(
        self,
        control_points: List[Tuple[QgsPointXY, QgsPointXY]]
    ) -> Optional[Dict]:
        """
        Анализ трансформации по контрольным точкам (алгоритм VectorBender).

        Определяет scale, rotation, translation между парами точек.
        Если rotation != 0 - нужна корректировка lon_0.

        Parameters:
        -----------
        control_points : List[Tuple[QgsPointXY, QgsPointXY]]
            Список пар (wrong_msk, correct_msk)
            wrong_msk - координаты из WFS (пересчитанные в МСК текущей CRS)
            correct_msk - эталонные координаты в МСК

        Returns:
        --------
        dict : {
            'scale': float,           # Масштабный коэффициент
            'rotation': float,        # Угол поворота (радианы)
            'rotation_deg': float,    # Угол поворота (градусы)
            'translation': Tuple,     # Смещение (dx, dy)
            'is_pure_translation': bool,  # True если только смещение
            'rmse': float,            # СКО до оптимизации
            'errors': List[float]     # Список ошибок по точкам
        }
        """
        if len(control_points) < 2:
            # Одна точка - можно определить только translation
            if len(control_points) == 1:
                wrong, correct = control_points[0]
                # Смещение для x_0/y_0: wrong - correct (инвертированный знак!)
                dx = wrong.x() - correct.x()
                dy = wrong.y() - correct.y()
                return {
                    'scale': 1.0,
                    'rotation': 0.0,
                    'rotation_deg': 0.0,
                    'translation': (dx, dy),
                    'is_pure_translation': True,
                    'rmse': 0.0,
                    'errors': [0.0]
                }
            return None

        # Для 2+ точек используем алгоритм LinearTransformer из VectorBender
        src_points = [pair[0] for pair in control_points]  # wrong
        dst_points = [pair[1] for pair in control_points]  # correct

        # Расчет по первым двум точкам (определяет scale и rotation)
        src1, src2 = src_points[0], src_points[1]
        dst1, dst2 = dst_points[0], dst_points[1]

        # Расстояния
        dist_src = math.sqrt(
            (src2.x() - src1.x())**2 + (src2.y() - src1.y())**2
        )
        dist_dst = math.sqrt(
            (dst2.x() - dst1.x())**2 + (dst2.y() - dst1.y())**2
        )

        # Scale
        scale = dist_dst / dist_src if dist_src > 0 else 1.0

        # Углы направлений
        angle_src = math.atan2(src2.y() - src1.y(), src2.x() - src1.x())
        angle_dst = math.atan2(dst2.y() - dst1.y(), dst2.x() - dst1.x())

        # Rotation
        rotation = angle_dst - angle_src

        # Нормализация угла в диапазон [-pi, pi]
        while rotation > math.pi:
            rotation -= 2 * math.pi
        while rotation < -math.pi:
            rotation += 2 * math.pi

        # Translation - по алгоритму VectorBender LinearTransformer
        # VectorBender: translate to origin -> scale -> rotate -> translate to target
        # dx1, dy1 = src1 (origin)
        # dx2, dy2 = dst1 (target)
        cos_r = math.cos(rotation)
        sin_r = math.sin(rotation)

        # Параметры трансформации как в VectorBender
        dx1, dy1 = src1.x(), src1.y()  # origin point
        dx2, dy2 = dst1.x(), dst1.y()  # target point

        # Расчет ошибок по всем точкам используя алгоритм VectorBender
        errors = []
        for src, dst in control_points:
            # 1. Смещение к началу координат (translate to origin)
            px = src.x() - dx1
            py = src.y() - dy1

            # 2. Масштабирование (scale)
            px = scale * px
            py = scale * py

            # 3. Поворот (rotation)
            rx = cos_r * px - sin_r * py
            ry = sin_r * px + cos_r * py

            # 4. Смещение к целевой позиции (translate to target)
            tx = rx + dx2
            ty = ry + dy2

            error = math.sqrt((tx - dst.x())**2 + (ty - dst.y())**2)
            errors.append(error)

        # Для возврата translation используем простую разницу первых точек
        # (это приблизительное значение, используется только для диагностики)
        # Смещение для x_0/y_0: src - dst (wrong - correct)
        dx = src1.x() - dst1.x()
        dy = src1.y() - dst1.y()

        rmse = math.sqrt(sum(e**2 for e in errors) / len(errors))

        # Определяем, является ли трансформация чистым смещением
        is_pure_translation = (
            abs(scale - 1.0) < 0.0001 and
            abs(rotation) < 0.00017  # ~0.01 градуса в радианах
        )

        log_info(
            f"Fsm_0_5_3: Анализ трансформации: "
            f"scale={scale:.6f}, rotation={math.degrees(rotation):.4f} deg, "
            f"translation=({dx:.2f}, {dy:.2f}), RMSE={rmse:.4f} m"
        )

        return {
            'scale': scale,
            'rotation': rotation,
            'rotation_deg': math.degrees(rotation),
            'translation': (dx, dy),
            'is_pure_translation': is_pure_translation,
            'rmse': rmse,
            'errors': errors
        }

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
        # Золотое сечение
        phi = (1 + math.sqrt(5)) / 2
        resphi = 2 - phi  # 1/phi

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

    def _fit_translation(
        self,
        control_points: List[Tuple[QgsPointXY, QgsPointXY]],
        lon_0: float,
        base_params: Dict,
        object_layer_crs: QgsCoordinateReferenceSystem
    ) -> Tuple[float, float, float]:
        """
        Подбор x_0, y_0 для заданного lon_0.

        НОВЫЙ WORKFLOW (2024-12):
        - wrong_point: координаты в CRS слоя объекта (исходная МСК)
        - correct_point: координаты в EPSG:3857 (WFS эталон)

        Алгоритм:
        1. Wrong (МСК объекта) → WGS84
        2. Correct (3857) → WGS84
        3. Оба WGS84 → test_МСК (с тестируемым lon_0, x_0=0, y_0=0)
        4. Смещение dx = correct_new.x - wrong_new.x
        5. x_0, y_0 = среднее смещение

        Parameters:
        -----------
        control_points : List[Tuple[QgsPointXY, QgsPointXY]]
            Пары (wrong_msk, correct_3857):
            - wrong_msk в координатах CRS слоя объекта (МСК)
            - correct_3857 в EPSG:3857
        lon_0 : float
            Центральный меридиан для тестирования
        base_params : Dict
            Базовые параметры CRS (lat_0, k_0, ellps_param, towgs84_param)
        object_layer_crs : QgsCoordinateReferenceSystem
            CRS слоя объекта (исходная МСК, из которой wrong точки)

        Returns:
        --------
        Tuple[float, float, float] : (x_0, y_0, rmse)
        """
        try:
            # WGS84 для промежуточного пересчёта
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            epsg_3857 = QgsCoordinateReferenceSystem("EPSG:3857")

            # Трансформатор: МСК слоя объекта → WGS84
            transform_wrong_to_wgs = QgsCoordinateTransform(
                object_layer_crs, wgs84, QgsProject.instance()
            )

            # Трансформатор: 3857 → WGS84
            transform_correct_to_wgs = QgsCoordinateTransform(
                epsg_3857, wgs84, QgsProject.instance()
            )

            # Создаём временную CRS с новым lon_0 (x_0=0, y_0=0)
            proj_string = (
                f"+proj=tmerc "
                f"+lat_0={base_params.get('lat_0', 0)} "
                f"+lon_0={lon_0} "
                f"+k_0={base_params.get('k_0', 1.0)} "
                f"+x_0=0 +y_0=0 "
                f"{base_params.get('ellps_param', ELLPS_KRASS)} "
                f"{base_params.get('towgs84_param', TOWGS84_SK42_PROJ)}"
            )

            temp_crs = QgsCoordinateReferenceSystem()
            temp_crs.createFromProj(proj_string)

            if not temp_crs.isValid():
                log_error(f"Fsm_0_5_3: Не удалось создать CRS с lon_0={lon_0}")
                return (0.0, 0.0, float('inf'))

            # Трансформатор: WGS84 → новая test_МСК
            transform_to_new = QgsCoordinateTransform(
                wgs84, temp_crs, QgsProject.instance()
            )

            # Пересчитываем обе точки и считаем смещения
            dx_list = []
            dy_list = []
            transformed_points = []

            for wrong_msk, correct_3857 in control_points:
                # 1. Wrong МСК → WGS84 → test_МСК
                wrong_wgs = transform_wrong_to_wgs.transform(wrong_msk)
                wrong_new = transform_to_new.transform(wrong_wgs)

                # 2. Correct 3857 → WGS84 → test_МСК
                correct_wgs = transform_correct_to_wgs.transform(correct_3857)
                correct_new = transform_to_new.transform(correct_wgs)

                # 3. Смещение для x_0/y_0: wrong - correct (инвертированный знак!)
                # x_0 в TM влияет на интерпретацию как f(lon) = E - x_0
                dx = wrong_new.x() - correct_new.x()
                dy = wrong_new.y() - correct_new.y()

                dx_list.append(dx)
                dy_list.append(dy)
                transformed_points.append((wrong_new, correct_new))

            # Среднее смещение = x_0, y_0
            x_0 = sum(dx_list) / len(dx_list) if dx_list else 0.0
            y_0 = sum(dy_list) / len(dy_list) if dy_list else 0.0

            # RMSE после применения смещения
            # x_0 применяется как: интерпретация координат = E - x_0
            errors = []
            for wrong_new, correct_new in transformed_points:
                adjusted_x = wrong_new.x() - x_0
                adjusted_y = wrong_new.y() - y_0
                error = math.sqrt(
                    (adjusted_x - correct_new.x())**2 +
                    (adjusted_y - correct_new.y())**2
                )
                errors.append(error)

            rmse = math.sqrt(sum(e**2 for e in errors) / len(errors)) if errors else 0.0

            return (x_0, y_0, rmse)

        except Exception as e:
            log_error(f"Fsm_0_5_3: Ошибка в _fit_translation: {e}")
            return (0.0, 0.0, float('inf'))

    def optimize_lon_0_iterative(
        self,
        control_points: List[Tuple[QgsPointXY, QgsPointXY]],
        base_proj_params: Dict,
        initial_lon_0: float,
        object_layer_crs: Optional[QgsCoordinateReferenceSystem] = None
    ) -> Dict:
        """
        Итеративный подбор lon_0 методом минимизации СКО.

        НОВЫЙ WORKFLOW (2024-12):
        - wrong точки в CRS слоя объекта (МСК)
        - correct точки в EPSG:3857 (WFS)

        Алгоритм:
        1. Анализ трансформации (scale, rotation)
        2. Если rotation == 0 - возвращаем только translation
        3. Иначе - итеративный подбор lon_0 методом золотого сечения
        4. Подбор x_0, y_0 для найденного lon_0

        Parameters:
        -----------
        control_points : List[Tuple[QgsPointXY, QgsPointXY]]
            Список пар (wrong_msk, correct_3857):
            - wrong_msk в координатах CRS слоя объекта (МСК)
            - correct_3857 в EPSG:3857
        base_proj_params : Dict
            Базовые параметры CRS:
            - lat_0: float (широта начала координат)
            - k_0: float (масштабный коэффициент)
            - ellps_param: str (параметр эллипсоида, напр. "+ellps=krass")
            - towgs84_param: str (параметры трансформации)
        initial_lon_0 : float
            Начальное приближение lon_0 (градусы)
        object_layer_crs : QgsCoordinateReferenceSystem, optional
            CRS слоя объекта (исходная МСК). Если None - берётся из проекта

        Returns:
        --------
        dict : {
            'lon_0': float,          # Оптимальный центральный меридиан
            'x_0': float,            # Оптимальное смещение X
            'y_0': float,            # Оптимальное смещение Y
            'rmse': float,           # СКО после оптимизации (м)
            'iterations': int,       # Количество итераций
            'diagnostics': dict,     # Диагностика (rotation, scale)
            'success': bool          # Успешность оптимизации
        }
        """
        log_info(f"Fsm_0_5_3: Начало итеративного подбора lon_0, "
                 f"начальное значение: {initial_lon_0:.6f}")

        if not control_points:
            log_error("Fsm_0_5_3: Нет контрольных точек для оптимизации")
            return {
                'lon_0': initial_lon_0,
                'x_0': 0.0,
                'y_0': 0.0,
                'rmse': float('inf'),
                'iterations': 0,
                'diagnostics': {},
                'success': False
            }

        # Шаг 1: Анализ трансформации
        diagnostics = self._analyze_transformation(control_points)

        if diagnostics is None:
            log_error("Fsm_0_5_3: Недостаточно точек для анализа")
            return {
                'lon_0': initial_lon_0,
                'x_0': 0.0,
                'y_0': 0.0,
                'rmse': float('inf'),
                'iterations': 0,
                'diagnostics': {},
                'success': False
            }

        # Шаг 2: Если чистое смещение - lon_0 корректен
        if diagnostics['is_pure_translation']:
            log_info("Fsm_0_5_3: Трансформация = чистое смещение, "
                     "lon_0 корректен")
            dx, dy = diagnostics['translation']
            return {
                'lon_0': initial_lon_0,
                'x_0': dx,
                'y_0': dy,
                'rmse': diagnostics['rmse'],
                'iterations': 0,
                'diagnostics': diagnostics,
                'success': True
            }

        # Шаг 3: Итеративный подбор lon_0
        log_info(f"Fsm_0_5_3: Обнаружен поворот {diagnostics['rotation_deg']:.4f} deg, "
                 f"запуск итеративного подбора lon_0")

        # CRS слоя объекта (для пересчёта wrong точек в WGS84)
        if object_layer_crs is None:
            object_layer_crs = QgsProject.instance().crs()
            log_warning("Fsm_0_5_3: object_layer_crs не указан, используется Project CRS")

        assert object_layer_crs is not None  # Гарантировано не None после if выше
        crs_authid = object_layer_crs.authid() if object_layer_crs.isValid() else "Unknown"
        log_info(f"Fsm_0_5_3: CRS слоя объекта: {crs_authid}")

        # Функция для минимизации
        def objective(lon_0):
            _, _, rmse = self._fit_translation(
                control_points, lon_0, base_proj_params, object_layer_crs
            )
            return rmse

        # Диапазон поиска: initial_lon_0 +/- 3 градуса
        search_result = self._golden_section_search(
            objective,
            initial_lon_0 - 3.0,
            initial_lon_0 + 3.0,
            tol=1e-6,
            max_iter=100
        )

        optimal_lon_0 = search_result['x']
        iterations = search_result['iterations']

        log_info(f"Fsm_0_5_3: Найден оптимальный lon_0 = {optimal_lon_0:.6f} "
                 f"за {iterations} итераций")

        # Шаг 4: Финальный подбор x_0, y_0
        final_x0, final_y0, final_rmse = self._fit_translation(
            control_points, optimal_lon_0, base_proj_params, object_layer_crs
        )

        log_info(f"Fsm_0_5_3: Финальные параметры: "
                 f"lon_0={optimal_lon_0:.6f}, x_0={final_x0:.2f}, y_0={final_y0:.2f}, "
                 f"RMSE={final_rmse:.4f} м")

        # Проверка успешности
        success = final_rmse < 0.01  # Цель: < 1 см

        if not success:
            log_warning(f"Fsm_0_5_3: RMSE = {final_rmse:.4f} м превышает целевые 0.01 м. "
                        f"Возможно неверные параметры towgs84 или k_0")

        return {
            'lon_0': optimal_lon_0,
            'x_0': final_x0,
            'y_0': final_y0,
            'rmse': final_rmse,
            'iterations': iterations,
            'diagnostics': diagnostics,
            'success': success
        }

    def _fit_with_towgs84_scale(
        self,
        control_points: List[Tuple[QgsPointXY, QgsPointXY]],
        lon_0: float,
        base_params: Dict,
        object_layer_crs: QgsCoordinateReferenceSystem,
        towgs84_scale: float
    ) -> Tuple[float, float, float]:
        """
        Подбор x_0, y_0 для заданного lon_0 с модифицированным масштабом towgs84.

        Parameters:
        -----------
        towgs84_scale : float
            Масштабный коэффициент dS в towgs84 (ppm), например -0.22

        Returns:
        --------
        Tuple[float, float, float] : (x_0, y_0, rmse)
        """
        # Модифицируем towgs84 с новым масштабом
        # Извлекаем первые 6 параметров
        towgs84_str = base_params.get('towgs84_param', TOWGS84_SK42_PROJ)

        # Парсим параметры
        if '+towgs84=' in towgs84_str:
            params_str = towgs84_str.replace('+towgs84=', '')
            parts = params_str.split(',')
            if len(parts) >= 7:
                # Заменяем последний параметр (dS)
                parts[6] = str(towgs84_scale)
                new_towgs84 = '+towgs84=' + ','.join(parts)
            else:
                new_towgs84 = towgs84_str
        else:
            new_towgs84 = towgs84_str

        # Создаём модифицированные параметры
        modified_params = base_params.copy()
        modified_params['towgs84_param'] = new_towgs84

        return self._fit_translation(
            control_points, lon_0, modified_params, object_layer_crs
        )

    def optimize_towgs84_scale(
        self,
        control_points: List[Tuple[QgsPointXY, QgsPointXY]],
        base_params: Dict,
        lon_0: float,
        object_layer_crs: QgsCoordinateReferenceSystem,
        initial_scale: float = -0.22
    ) -> Dict:
        """
        Подбор оптимального масштаба dS в параметрах towgs84.

        Параметр dS (ppm) влияет на общий масштаб трансформации из СК-95 в WGS84.
        Стандартное значение для России: -0.22 ppm.

        Parameters:
        -----------
        control_points : List[Tuple[QgsPointXY, QgsPointXY]]
            Контрольные точки (wrong_msk, correct_3857)
        base_params : Dict
            Базовые параметры проекции
        lon_0 : float
            Центральный меридиан (уже оптимизированный)
        object_layer_crs : QgsCoordinateReferenceSystem
            CRS слоя объекта
        initial_scale : float
            Начальное значение dS (по умолчанию -0.22)

        Returns:
        --------
        dict : {
            'optimal_scale': float,      # Оптимальный dS
            'x_0': float,
            'y_0': float,
            'rmse': float,
            'improvement': float,        # Улучшение RMSE в %
            'tested_values': List[dict]  # Результаты тестирования
        }
        """
        log_info("Fsm_0_5_3: ПОДБОР МАСШТАБА towgs84 (dS)")

        # Тестируем диапазон значений dS
        # От -1.0 до +1.0 с шагом 0.1
        test_scales = [
            initial_scale,  # Исходное значение
            -1.0, -0.8, -0.6, -0.5, -0.4, -0.3, -0.25, -0.22, -0.2, -0.15, -0.1, -0.05,
            0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0
        ]
        # Убираем дубликаты и сортируем
        test_scales = sorted(set(test_scales))

        results = []
        best_result = None
        initial_rmse = None

        for dS in test_scales:
            x_0, y_0, rmse = self._fit_with_towgs84_scale(
                control_points, lon_0, base_params, object_layer_crs, dS
            )

            result = {
                'dS': dS,
                'x_0': x_0,
                'y_0': y_0,
                'rmse': rmse
            }
            results.append(result)

            if dS == initial_scale:
                initial_rmse = rmse

            if best_result is None or rmse < best_result['rmse']:
                best_result = result

            log_info(f"  dS={dS:+.4f}: RMSE={rmse:.4f} м, x_0={x_0:.2f}, y_0={y_0:.2f}")

        # Точный подбор вокруг лучшего значения
        if best_result and best_result['rmse'] < float('inf'):
            best_dS = best_result['dS']

            # Поиск в узком диапазоне
            def objective(dS):
                _, _, rmse = self._fit_with_towgs84_scale(
                    control_points, lon_0, base_params, object_layer_crs, dS
                )
                return rmse

            fine_search = self._golden_section_search(
                objective,
                best_dS - 0.1,
                best_dS + 0.1,
                tol=1e-6,
                max_iter=50
            )

            optimal_dS = fine_search['x']
            x_0, y_0, rmse = self._fit_with_towgs84_scale(
                control_points, lon_0, base_params, object_layer_crs, optimal_dS
            )

            log_info("-" * 60)
            log_info(f"Fsm_0_5_3: Оптимальный dS = {optimal_dS:.6f}")
            log_info(f"  RMSE = {rmse:.4f} м")
            log_info(f"  x_0 = {x_0:.2f} м, y_0 = {y_0:.2f} м")

            if initial_rmse and initial_rmse > 0:
                improvement = (initial_rmse - rmse) / initial_rmse * 100
                log_info(f"  Улучшение: {improvement:.1f}% (было {initial_rmse:.4f} м)")
            else:
                improvement = 0.0

            return {
                'optimal_scale': optimal_dS,
                'x_0': x_0,
                'y_0': y_0,
                'rmse': rmse,
                'improvement': improvement,
                'tested_values': results,
                'initial_rmse': initial_rmse
            }

        return {
            'optimal_scale': initial_scale,
            'x_0': 0.0,
            'y_0': 0.0,
            'rmse': float('inf'),
            'improvement': 0.0,
            'tested_values': results,
            'initial_rmse': initial_rmse
        }

    def optimize_full(
        self,
        control_points: List[Tuple[QgsPointXY, QgsPointXY]],
        base_proj_params: Dict,
        initial_lon_0: float,
        object_layer_crs: QgsCoordinateReferenceSystem
    ) -> Dict:
        """
        Полная оптимизация: lon_0 + towgs84 dS + x_0/y_0.

        Выполняет последовательную оптимизацию:
        1. Подбор lon_0
        2. Подбор dS (масштаб towgs84)
        3. Финальный подбор x_0, y_0

        Returns:
        --------
        dict : {
            'lon_0': float,
            'towgs84_scale': float,
            'towgs84_param': str,   # Полная строка +towgs84=...
            'x_0': float,
            'y_0': float,
            'rmse': float,
            'success': bool
        }
        """
        log_info("Fsm_0_5_3: ПОЛНАЯ ОПТИМИЗАЦИЯ ПАРАМЕТРОВ ПРОЕКЦИИ")

        # Шаг 1: Оптимизация lon_0
        lon_result = self.optimize_lon_0_iterative(
            control_points, base_proj_params, initial_lon_0, object_layer_crs
        )

        optimal_lon_0 = lon_result['lon_0']
        log_info(f"Fsm_0_5_3: После оптимизации lon_0: RMSE = {lon_result['rmse']:.4f} м")

        # Если RMSE уже хорошее - не оптимизируем dS
        if lon_result['rmse'] < 0.5:
            log_info("Fsm_0_5_3: RMSE < 0.5 м, оптимизация dS не требуется")
            return {
                'lon_0': optimal_lon_0,
                'towgs84_scale': None,
                'towgs84_param': base_proj_params.get('towgs84_param'),
                'x_0': lon_result['x_0'],
                'y_0': lon_result['y_0'],
                'rmse': lon_result['rmse'],
                'success': lon_result['success'],
                'diagnostics': lon_result.get('diagnostics', {})
            }

        # Шаг 2: Оптимизация dS
        # Извлекаем текущий dS из параметров
        towgs84_str = base_proj_params.get('towgs84_param', TOWGS84_SK42_PROJ)
        if '+towgs84=' in towgs84_str:
            parts = towgs84_str.replace('+towgs84=', '').split(',')
            initial_dS = float(parts[6]) if len(parts) >= 7 else -0.22
        else:
            initial_dS = -0.22

        dS_result = self.optimize_towgs84_scale(
            control_points, base_proj_params, optimal_lon_0,
            object_layer_crs, initial_dS
        )

        # Формируем финальную строку towgs84
        if '+towgs84=' in towgs84_str:
            parts = towgs84_str.replace('+towgs84=', '').split(',')
            if len(parts) >= 7:
                parts[6] = f"{dS_result['optimal_scale']:.6f}"
                final_towgs84 = '+towgs84=' + ','.join(parts)
            else:
                final_towgs84 = towgs84_str
        else:
            final_towgs84 = towgs84_str

        log_info("Fsm_0_5_3: ИТОГОВЫЕ ПАРАМЕТРЫ:")
        log_info(f"  lon_0 = {optimal_lon_0:.6f}°")
        log_info(f"  dS = {dS_result['optimal_scale']:.6f} ppm")
        log_info(f"  x_0 = {dS_result['x_0']:.2f} м")
        log_info(f"  y_0 = {dS_result['y_0']:.2f} м")
        log_info(f"  RMSE = {dS_result['rmse']:.4f} м")
        log_info(f"  {final_towgs84}")

        return {
            'lon_0': optimal_lon_0,
            'towgs84_scale': dS_result['optimal_scale'],
            'towgs84_param': final_towgs84,
            'x_0': dS_result['x_0'],
            'y_0': dS_result['y_0'],
            'rmse': dS_result['rmse'],
            'success': dS_result['rmse'] < RMSE_THRESHOLD_OK,  # < 1 м считаем успехом
            'diagnostics': lon_result.get('diagnostics', {})
        }

    def diagnose_crs_mismatch(self, analysis: Dict) -> str:
        """
        Диагностика несоответствия CRS на основе анализа трансформации.

        Parameters:
        -----------
        analysis : Dict
            Результат _analyze_transformation()

        Returns:
        --------
        str : Текстовая диагностика и рекомендации
        """
        if analysis.get('is_pure_translation'):
            return (
                "lon_0 корректен. Нужно только смещение x_0, y_0.\n"
                f"dx = {analysis['translation'][0]:.2f} м\n"
                f"dy = {analysis['translation'][1]:.2f} м"
            )

        rotation_deg = analysis.get('rotation_deg', 0)
        scale = analysis.get('scale', 1)

        messages = []

        if abs(rotation_deg) > 0.001:
            messages.append(
                f"Поворот {rotation_deg:.4f} deg - нужна корректировка lon_0"
            )

        if abs(scale - 1) > 0.001:
            scale_ppm = (scale - 1) * 1e6
            messages.append(
                f"Масштаб {scale:.6f} ({scale_ppm:.1f} ppm) - проверить k_0 или towgs84"
            )

        if not messages:
            messages.append("Трансформация близка к идентичной")

        return "\n".join(messages)

    # =========================================================================
    # НОВЫЙ АЛГОРИТМ: Расчёт проекции напрямую из WGS84 координат
    # =========================================================================

    def calculate_projection_from_wgs84(
        self,
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        base_params: Dict,
        initial_lon_0: Optional[float] = None
    ) -> Dict:
        """
        Расчёт параметров проекции напрямую из WGS84 координат.

        НОВЫЙ ПОДХОД (2024-12):
        - Входные данные: пары (object_wgs84, reference_wgs84) - обе в WGS84
        - object_wgs84: координаты объекта (из МСК → WGS84)
        - reference_wgs84: эталонные координаты (из 3857 → WGS84)

        Алгоритм:
        1. Вычисляем среднюю долготу эталонных точек → lon_0
        2. Создаём тестовую проекцию с lon_0, x_0=0, y_0=0
        3. Трансформируем обе точки в тестовую МСК
        4. Вычисляем смещение (x_0, y_0) чтобы object совпал с reference
        5. Итеративно уточняем lon_0 для минимизации RMSE

        Parameters:
        -----------
        control_points_wgs84 : List[Tuple[QgsPointXY, QgsPointXY]]
            Пары (object_wgs84, reference_wgs84):
            - object_wgs84: lon, lat объекта в WGS84
            - reference_wgs84: lon, lat эталона в WGS84
        base_params : Dict
            Базовые параметры:
            - lat_0: широта начала (обычно 0)
            - k_0: масштабный коэффициент (обычно 1)
            - ellps_param: "+ellps=krass"
            - towgs84_param: ГОСТ 32453-2017 параметры СК-42 -> WGS-84
        initial_lon_0 : float, optional
            Начальное приближение lon_0. Если None - вычисляется из центра данных

        Returns:
        --------
        dict : {
            'lon_0': float,          # Центральный меридиан
            'x_0': float,            # False easting
            'y_0': float,            # False northing
            'rmse': float,           # СКО (м)
            'success': bool,
            'diagnostics': dict
        }
        """
        if not control_points_wgs84:
            log_error("Fsm_0_5_3: Нет контрольных точек")
            return {
                'lon_0': initial_lon_0 or 0.0,
                'x_0': 0.0, 'y_0': 0.0,
                'rmse': float('inf'),
                'success': False,
                'diagnostics': {}
            }

        # Шаг 1: Определяем lon_0 из центра ЭТАЛОННЫХ точек
        if initial_lon_0 is None:
            ref_lons = [ref.x() for _, ref in control_points_wgs84]
            initial_lon_0 = sum(ref_lons) / len(ref_lons)

        # Извлекаем параметры
        lat_0 = base_params.get('lat_0', 0.0)
        k_0 = base_params.get('k_0', 1.0)
        ellps_param = base_params.get('ellps_param', ELLPS_KRASS)
        towgs84_param = base_params.get('towgs84_param', TOWGS84_SK42_PROJ)

        # Шаг 2: Функция для расчёта RMSE при заданном lon_0
        def calc_rmse_for_lon0(lon_0: float) -> Tuple[float, float, float, List[float]]:
            """Возвращает (x_0, y_0, rmse, errors)"""
            return self._calc_offset_from_wgs84(
                control_points_wgs84, lon_0, lat_0, k_0, ellps_param, towgs84_param
            )

        # Шаг 3: Грубый поиск оптимального lon_0
        # Тестируем диапазон вокруг начального значения
        best_lon_0 = initial_lon_0
        best_rmse = float('inf')
        best_x0, best_y0 = 0.0, 0.0

        # Сначала проверяем начальное значение
        x0, y0, rmse, _ = calc_rmse_for_lon0(initial_lon_0)
        if rmse < best_rmse:
            best_lon_0 = initial_lon_0
            best_rmse = rmse
            best_x0, best_y0 = x0, y0

        # Тестируем смещения от -2° до +2° с шагом 0.5°
        for delta in [-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0]:
            test_lon_0 = initial_lon_0 + delta
            x0, y0, rmse, _ = calc_rmse_for_lon0(test_lon_0)
            if rmse < best_rmse:
                best_lon_0 = test_lon_0
                best_rmse = rmse
                best_x0, best_y0 = x0, y0

        # Шаг 4: Точный поиск методом золотого сечения
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

        success = final_rmse < RMSE_THRESHOLD_OK  # < 1 м считаем успехом

        # Компактный вывод результатов
        status = "OK" if success else "WARN"
        err_range = f"[{min(errors):.2f}-{max(errors):.2f}]" if errors else "[]"
        log_info(f"Fsm_0_5_3: lon_0={optimal_lon_0:.4f}° x_0={final_x0:.2f} y_0={final_y0:.2f} "
                 f"RMSE={final_rmse:.2f}м {err_range} [{status}]")

        return {
            'lon_0': optimal_lon_0,
            'x_0': final_x0,
            'y_0': final_y0,
            'rmse': final_rmse,
            'success': success,
            'diagnostics': {
                'errors': errors,
                'initial_lon_0': initial_lon_0,
                'search_iterations': search_result['iterations']
            }
        }

    def _calc_offset_from_wgs84(
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

        Returns:
        --------
        Tuple[float, float, float, List[float]]: (x_0, y_0, rmse, errors)
        """
        try:
            # WGS84
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")

            # Создаём тестовую CRS с x_0=0, y_0=0
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
                log_error(f"Fsm_0_5_3: Невалидная CRS для lon_0={lon_0}")
                return (0.0, 0.0, float('inf'), [])

            # Трансформатор WGS84 → тестовая МСК
            transform_to_msk = QgsCoordinateTransform(
                wgs84, test_crs, QgsProject.instance()
            )

            # Вычисляем смещения
            dx_list = []
            dy_list = []
            transformed = []

            for object_wgs, reference_wgs in control_points_wgs84:
                # Трансформируем обе точки в тестовую МСК
                obj_msk = transform_to_msk.transform(object_wgs)
                ref_msk = transform_to_msk.transform(reference_wgs)

                # Смещение = reference - object
                # (чтобы object + offset = reference)
                dx = ref_msk.x() - obj_msk.x()
                dy = ref_msk.y() - obj_msk.y()

                dx_list.append(dx)
                dy_list.append(dy)
                transformed.append((obj_msk, ref_msk))

            # Среднее смещение
            x_0 = sum(dx_list) / len(dx_list)
            y_0 = sum(dy_list) / len(dy_list)

            # RMSE после применения смещения
            errors = []
            for obj_msk, ref_msk in transformed:
                adjusted_x = obj_msk.x() + x_0
                adjusted_y = obj_msk.y() + y_0
                error = math.sqrt(
                    (adjusted_x - ref_msk.x())**2 +
                    (adjusted_y - ref_msk.y())**2
                )
                errors.append(error)

            rmse = math.sqrt(sum(e**2 for e in errors) / len(errors)) if errors else 0.0

            return (x_0, y_0, rmse, errors)

        except Exception as e:
            log_error(f"Fsm_0_5_3: Ошибка в _calc_offset_from_wgs84: {e}")
            return (0.0, 0.0, float('inf'), [])

    # =========================================================================
    # АФФИННЫЙ АНАЛИЗ: Расчёт параметров трансформации для корректировки проекции
    # =========================================================================

    def calculate_affine_correction(
        self,
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        base_params: Dict,
        initial_lon_0: float
    ) -> Dict:
        """
        Расчёт аффинных параметров и корректировка параметров проекции.

        ПОДХОД:
        1. Вычисляем аффинную трансформацию (rotation, scale, translation)
        2. Корректируем параметры проекции на основе анализа:
           - rotation → корректировка lon_0
           - scale → корректировка dS в towgs84
           - translation → x_0, y_0

        Исходные координаты НЕ меняются. Меняются только параметры проекции.

        Parameters:
        -----------
        control_points_wgs84 : List[Tuple[QgsPointXY, QgsPointXY]]
            Пары (object_wgs84, reference_wgs84)
        base_params : Dict
            Базовые параметры проекции
        initial_lon_0 : float
            Начальный центральный меридиан

        Returns:
        --------
        dict : {
            'lon_0': float,           # Скорректированный центральный меридиан
            'x_0': float,             # False easting
            'y_0': float,             # False northing
            'dS_correction': float,   # Корректировка масштаба towgs84 (ppm)
            'towgs84_param': str,     # Полная строка +towgs84=...
            'rmse': float,            # RMSE после коррекции
            'affine_params': dict,    # rotation, scale для диагностики
            'success': bool
        }
        """
        if len(control_points_wgs84) < 3:
            log_warning("Fsm_0_5_3: Аффинный анализ: нужно минимум 3 точки")
            # Возвращаем простой расчёт без аффинной коррекции
            simple_result = self.calculate_projection_from_wgs84(
                control_points_wgs84, base_params, initial_lon_0
            )
            return {
                **simple_result,
                'dS_correction': 0.0,
                'towgs84_param': base_params.get('towgs84_param'),
                'affine_params': {'rotation': 0.0, 'scale': 1.0}
            }

        # Извлекаем параметры
        lat_0 = base_params.get('lat_0', 0.0)
        k_0 = base_params.get('k_0', 1.0)
        ellps_param = base_params.get('ellps_param', ELLPS_KRASS)
        towgs84_param = base_params.get('towgs84_param', TOWGS84_SK42_PROJ)

        # Шаг 1: Трансформируем точки в МСК с начальными параметрами
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")

        proj_string = (
            f"+proj=tmerc +lat_0={lat_0} +lon_0={initial_lon_0} +k_0={k_0} "
            f"+x_0=0 +y_0=0 {ellps_param} {towgs84_param} +units=m +no_defs"
        )
        test_crs = QgsCoordinateReferenceSystem()
        test_crs.createFromProj(proj_string)

        if not test_crs.isValid():
            log_error("Fsm_0_5_3: Невалидная CRS для аффинного анализа")
            return {
                'lon_0': initial_lon_0, 'x_0': 0.0, 'y_0': 0.0,
                'dS_correction': 0.0, 'towgs84_param': towgs84_param,
                'rmse': float('inf'), 'affine_params': {}, 'success': False
            }

        transform_to_msk = QgsCoordinateTransform(wgs84, test_crs, QgsProject.instance())

        # Собираем пары точек в МСК
        obj_points = []  # object точки
        ref_points = []  # reference точки

        for object_wgs, reference_wgs in control_points_wgs84:
            obj_msk = transform_to_msk.transform(object_wgs)
            ref_msk = transform_to_msk.transform(reference_wgs)
            obj_points.append((obj_msk.x(), obj_msk.y()))
            ref_points.append((ref_msk.x(), ref_msk.y()))

        # Шаг 2: Вычисляем аффинные параметры
        affine = self._calculate_affine_params(obj_points, ref_points)

        rotation_deg = affine['rotation_deg']
        scale = affine['scale']
        scale_ppm = (scale - 1) * 1e6

        # Компактный вывод аффинных параметров
        log_info(f"Fsm_0_5_3: Аффинные параметры: rot={rotation_deg:.4f}° scale={scale_ppm:.2f}ppm")

        # Шаг 3: Корректируем параметры проекции
        # Корректировка lon_0 на основе поворота (теория сходимости меридианов)
        lon_0_correction = self._calculate_lon0_correction(
            rotation_deg, control_points_wgs84
        )
        corrected_lon_0 = initial_lon_0 + lon_0_correction

        # Корректировка dS на основе масштаба
        if '+towgs84=' in towgs84_param:
            parts = towgs84_param.replace('+towgs84=', '').split(',')
            current_dS = float(parts[6]) if len(parts) >= 7 else -0.22
        else:
            current_dS = -0.22

        dS_correction = -scale_ppm
        corrected_dS = current_dS + dS_correction

        # Формируем новый towgs84
        if '+towgs84=' in towgs84_param:
            parts = towgs84_param.replace('+towgs84=', '').split(',')
            if len(parts) >= 7:
                parts[6] = f"{corrected_dS:.4f}"
            corrected_towgs84 = '+towgs84=' + ','.join(parts)
        else:
            # СК-42 -> WGS-84 (Position Vector для PROJ) - используем константу с изменённым dS
            base_parts = TOWGS84_SK42.split(',')
            base_parts[6] = f"{corrected_dS:.4f}"
            corrected_towgs84 = '+towgs84=' + ','.join(base_parts)

        # Шаг 4: Пересчитываем x_0, y_0 с новыми параметрами
        final_x0, final_y0, final_rmse, errors = self._calc_offset_from_wgs84(
            control_points_wgs84, corrected_lon_0, lat_0, k_0, ellps_param, corrected_towgs84
        )

        success = final_rmse < RMSE_THRESHOLD_OK

        # Компактный вывод результатов
        status = "OK" if success else "WARN"
        log_info(f"Fsm_0_5_3: После коррекции: lon_0={corrected_lon_0:.4f}° dS={corrected_dS:.2f}ppm "
                 f"RMSE={final_rmse:.2f}м [{status}]")

        return {
            'lon_0': corrected_lon_0,
            'x_0': final_x0,
            'y_0': final_y0,
            'dS_correction': dS_correction,
            'towgs84_param': corrected_towgs84,
            'rmse': final_rmse,
            'affine_params': {
                'rotation_deg': rotation_deg,
                'scale': scale,
                'scale_ppm': scale_ppm,
                'tx': affine['tx'],
                'ty': affine['ty']
            },
            'success': success,
            'diagnostics': {
                'errors': errors,
                'original_lon_0': initial_lon_0,
                'original_dS': current_dS
            }
        }

    def _calculate_affine_params(
        self,
        src_points: List[Tuple[float, float]],
        dst_points: List[Tuple[float, float]]
    ) -> Dict:
        """
        Вычисление параметров аффинной трансформации методом наименьших квадратов.

        Аффинная трансформация:
        x' = a*x + b*y + tx
        y' = c*x + d*y + ty

        Для similarity (rotation + uniform scale + translation):
        x' = s*cos(θ)*x - s*sin(θ)*y + tx
        y' = s*sin(θ)*x + s*cos(θ)*y + ty

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

        # Вычисляем параметры similarity transform
        # Используем SVD-подобный подход через ковариационную матрицу

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
        # a = s*cos(θ), b = -s*sin(θ)
        a = (sxx + syy) / ss
        b = (syx - sxy) / ss

        # Масштаб и угол
        scale = math.sqrt(a**2 + b**2)
        rotation_rad = math.atan2(b, a)
        rotation_deg = math.degrees(rotation_rad)

        # Смещение (после поворота и масштаба)
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
        """
        if not control_points_wgs84:
            return 0.0

        # Вычисляем среднюю широту по reference точкам
        lat_sum = 0.0
        for _, reference_wgs in control_points_wgs84:
            lat_sum += reference_wgs.y()  # y() = широта в WGS84

        lat_avg_deg = lat_sum / len(control_points_wgs84)
        lat_avg_rad = math.radians(lat_avg_deg)

        # Защита от деления на ноль (экватор)
        sin_lat = math.sin(lat_avg_rad)
        if abs(sin_lat) < 0.1:  # Широты < ~6°
            sin_lat = 0.1

        # Формула: Δλ = -γ / sin(φ)
        lon_0_correction = -rotation_deg / sin_lat

        return lon_0_correction
