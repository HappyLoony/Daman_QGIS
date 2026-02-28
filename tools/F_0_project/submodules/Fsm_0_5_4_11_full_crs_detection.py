# -*- coding: utf-8 -*-
"""
Fsm_0_5_4_11 - Полное определение CRS (FullCRSDetection)

Минимум: 3 точки
Оптимизирует: lon_0, x_0, y_0 (сканирование всей России)
Датум: СК-42 (ГОСТ 32453-2017)

Назначение:
===========
Метод для случаев, когда СК объекта ПОЛНОСТЬЮ НЕИЗВЕСТНА.
В отличие от методов 1-4, которые калибруют ИЗВЕСТНУЮ CRS,
этот метод ищет CRS "с нуля".

Алгоритм:
=========
1. Грубый поиск: сканирование lon_0 от 21° до 180° с шагом 3° (зоны МСК)
2. Для каждого lon_0 вычисление x_0, y_0 и RMSE
3. Уточнение: метод золотого сечения вокруг лучшего lon_0
4. Возврат оптимальных lon_0, x_0, y_0

Диапазон поиска:
================
- Россия: 21° - 180° (Калининград - Чукотка)
- Шаг грубого поиска: 3° (ширина зоны МСК)
- Точность уточнения: 1e-6°

Отличие от других методов:
==========================
- Методы 1-4: калибровка известной CRS (small corrections)
- Метод 11: поиск CRS с нуля (full scan)

Изолированность:
================
Метод работает независимо от методов 1-4.
Результаты сравниваются по RMSE наравне со всеми остальными.
"""

import math
from typing import List, Tuple, Dict, Optional

from qgis.core import QgsPointXY

from .Fsm_0_5_4_base_method import BaseCalculationMethod, CalculationResult
from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.constants import ELLPS_KRASS, TOWGS84_SK42_PROJ, RMSE_THRESHOLD_OK


class Fsm_0_5_4_11_FullCRSDetection(BaseCalculationMethod):
    """
    Полное определение CRS путём сканирования lon_0 по России.
    Датум: СК-42. Минимум: 3 точки.
    """

    # Диапазон поиска (Россия)
    LON_0_MIN = 21.0   # Калининград
    LON_0_MAX = 180.0  # Чукотка
    LON_0_STEP = 3.0   # Ширина зоны МСК

    @property
    def name(self) -> str:
        return "Полное определение CRS"

    @property
    def method_id(self) -> str:
        return "full_crs"

    @property
    def min_points(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "Сканирование lon_0 по всей России (21°-180°), СК-42"

    def supports_ldp(self) -> bool:
        """Метод поддерживает LDP-подход с полным сканированием lon_0.

        В отличие от других методов, full_crs в LDP режиме:
        - Сканирует lon_0 по всей России (21°-180°)
        - Использует RAW координаты объектов напрямую
        - Находит lon_0 который минимизирует RMSE между RAW и reference

        Это позволяет найти оптимальную CRS когда исходная CRS неизвестна
        или некорректна (например, USER CRS от предыдущей калибровки).
        """
        return True

    def calculate(
        self,
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        base_params: Dict,
        initial_lon_0: float
    ) -> CalculationResult:
        """
        Полное определение CRS путём сканирования lon_0.

        initial_lon_0 игнорируется - сканируем весь диапазон России.

        Parameters:
        -----------
        control_points_wgs84 : List[Tuple[QgsPointXY, QgsPointXY]]
            Пары (object_wgs84, reference_wgs84)
        base_params : dict
            Базовые параметры (lat_0, k_0)
        initial_lon_0 : float
            Игнорируется (для совместимости интерфейса)

        Returns:
        --------
        CalculationResult : Результат с оптимальными lon_0, x_0, y_0
        """
        if len(control_points_wgs84) < self.min_points:
            log_warning(f"Fsm_0_5_4_11: Нужно минимум {self.min_points} точек")
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
            # Извлекаем параметры (СК-42 по умолчанию)
            lat_0 = base_params.get('lat_0', 0.0)
            k_0 = base_params.get('k_0', 1.0)
            ellps_param = base_params.get('ellps_param', ELLPS_KRASS)
            towgs84_param = base_params.get('towgs84_param', TOWGS84_SK42_PROJ)

            # Шаг 1: Грубый поиск по всему диапазону
            best_lon_0 = self.LON_0_MIN
            best_rmse = float('inf')
            best_x0, best_y0 = 0.0, 0.0
            scan_results = []

            lon_0 = self.LON_0_MIN
            while lon_0 <= self.LON_0_MAX:
                x0, y0, rmse, _ = self._calc_offset(
                    control_points_wgs84, lon_0, lat_0, k_0,
                    ellps_param, towgs84_param
                )
                scan_results.append((lon_0, rmse))

                if rmse < best_rmse:
                    best_lon_0 = lon_0
                    best_rmse = rmse
                    best_x0, best_y0 = x0, y0

                lon_0 += self.LON_0_STEP

            log_info(
                f"Fsm_0_5_4_11 [{self.method_id}]: Грубый поиск завершён. "
                f"Лучший lon_0={best_lon_0:.2f}° RMSE={best_rmse:.4f}m"
            )

            # Шаг 2: Уточнение методом золотого сечения
            search_left = max(self.LON_0_MIN, best_lon_0 - self.LON_0_STEP)
            search_right = min(self.LON_0_MAX, best_lon_0 + self.LON_0_STEP)

            def objective(lon_0_test):
                _, _, rmse_test, _ = self._calc_offset(
                    control_points_wgs84, lon_0_test, lat_0, k_0,
                    ellps_param, towgs84_param
                )
                return rmse_test

            search_result = self._golden_section_search(
                objective,
                search_left,
                search_right,
                tol=1e-6,
                max_iter=50
            )

            optimal_lon_0 = search_result['x']

            # Финальный расчёт с оптимальным lon_0
            final_x0, final_y0, final_rmse, errors = self._calc_offset(
                control_points_wgs84, optimal_lon_0, lat_0, k_0,
                ellps_param, towgs84_param
            )

            # Статистика ошибок
            rmse, min_err, max_err = self._get_error_stats(errors)
            success = rmse < RMSE_THRESHOLD_OK

            # Лог результата
            status = "OK" if success else "WARN"
            log_info(
                f"Fsm_0_5_4_11 [{self.method_id}]: "
                f"lon_0={optimal_lon_0:.4f}° x_0={final_x0:.2f} y_0={final_y0:.2f} "
                f"RMSE={rmse:.4f}m [{status}]"
            )

            # Определение зоны МСК
            zone_number = self._calculate_zone(optimal_lon_0)
            log_info(
                f"Fsm_0_5_4_11: Определена зона МСК: {zone_number} "
                f"(lon_0 сдвиг от стандартной: {optimal_lon_0 - zone_number * 6 + 3:.4f}°)"
            )

            return CalculationResult(
                method_name=self.name,
                method_id=self.method_id,
                lon_0=optimal_lon_0,
                x_0=final_x0,
                y_0=final_y0,
                towgs84_param=towgs84_param,
                datum_name="СК-42",
                rmse=rmse,
                min_error=min_err,
                max_error=max_err,
                success=success,
                min_points_required=self.min_points,
                diagnostics={
                    'errors': errors,
                    'scan_results': scan_results[:10],  # Первые 10 для лога
                    'zone_number': zone_number,
                    'search_iterations': search_result['iterations'],
                    'initial_lon_0_ignored': initial_lon_0
                }
            )

        except Exception as e:
            log_error(f"Fsm_0_5_4_11: Ошибка расчёта: {e}")
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
        LDP-расчёт: полное сканирование lon_0 с RAW координатами.

        ВАЖНО: Использует ПРЯМУЮ трансформацию EPSG:3857 -> test_proj.
        Это критически важно для визуального совпадения, т.к. QGIS OTF
        делает прямую трансформацию WFS (3857) -> Project CRS.

        В отличие от других LDP методов (которые фиксируют lon_0 на центре объекта),
        full_crs сканирует lon_0 по всей России чтобы найти оптимальную CRS.

        Parameters:
        -----------
        raw_wrong_coords : List[Tuple[float, float]]
            RAW координаты объектов (x, y) - используются напрямую
        control_points_wgs84 : List[Tuple[QgsPointXY, QgsPointXY]]
            Пары точек - НЕ ИСПОЛЬЗУЮТСЯ (для совместимости интерфейса)
        base_params : dict
            Базовые параметры. ДОЛЖЕН содержать 'reference_3857' - координаты в EPSG:3857
        initial_lon_0 : float
            Игнорируется - сканируем весь диапазон

        Returns:
        --------
        Optional[CalculationResult] : Результат с approach_type="ldp"
        """
        if len(raw_wrong_coords) < self.min_points:
            log_warning(f"Fsm_0_5_4_11 [LDP]: Нужно минимум {self.min_points} точек")
            return None

        # Получаем reference_3857 из base_params (КРИТИЧЕСКИ ВАЖНО для прямой трансформации)
        reference_3857 = base_params.get('reference_3857')
        if reference_3857 is None:
            # Fallback: используем старый метод через WGS84 (менее точный)
            log_warning("Fsm_0_5_4_11 [LDP]: reference_3857 не передан, используем fallback через WGS84")
            reference_wgs84 = [ref for _, ref in control_points_wgs84]
            use_direct_3857 = False
        else:
            use_direct_3857 = True

        if use_direct_3857 and len(raw_wrong_coords) != len(reference_3857):
            log_error("Fsm_0_5_4_11 [LDP]: Несоответствие количества точек (raw vs 3857)")
            return None
        elif not use_direct_3857 and len(raw_wrong_coords) != len(control_points_wgs84):
            log_error("Fsm_0_5_4_11 [LDP]: Несоответствие количества точек")
            return None

        try:
            # Извлекаем параметры
            lat_0 = base_params.get('lat_0', 0.0)
            k_0 = base_params.get('k_0', 1.0)
            ellps_param = base_params.get('ellps_param', ELLPS_KRASS)
            towgs84_param = base_params.get('towgs84_param', TOWGS84_SK42_PROJ)

            # Шаг 1: Грубый поиск по всему диапазону России
            best_lon_0 = self.LON_0_MIN
            best_rmse = float('inf')
            best_x0, best_y0 = 0.0, 0.0
            scan_results = []

            lon_0 = self.LON_0_MIN
            while lon_0 <= self.LON_0_MAX:
                if use_direct_3857:
                    # ПРЯМАЯ трансформация 3857 -> test_proj
                    x0, y0, rmse, _ = self._calc_offset_ldp_3857(
                        raw_wrong_coords, reference_3857,
                        lon_0, lat_0, k_0, ellps_param, towgs84_param
                    )
                else:
                    # Fallback через WGS84
                    x0, y0, rmse, _ = self._calc_offset_ldp(
                        raw_wrong_coords, reference_wgs84,
                        lon_0, lat_0, k_0, ellps_param, towgs84_param
                    )
                scan_results.append((lon_0, rmse))

                if rmse < best_rmse:
                    best_lon_0 = lon_0
                    best_rmse = rmse
                    best_x0, best_y0 = x0, y0

                lon_0 += self.LON_0_STEP

            transform_method = "3857->proj" if use_direct_3857 else "WGS84->proj"
            log_info(
                f"Fsm_0_5_4_11 [LDP] [{transform_method}]: Грубый поиск завершён. "
                f"Лучший lon_0={best_lon_0:.2f}° RMSE={best_rmse:.4f}m"
            )

            # Шаг 2: Уточнение методом золотого сечения
            search_left = max(self.LON_0_MIN, best_lon_0 - self.LON_0_STEP)
            search_right = min(self.LON_0_MAX, best_lon_0 + self.LON_0_STEP)

            def objective(lon_0_test):
                if use_direct_3857:
                    _, _, rmse_test, _ = self._calc_offset_ldp_3857(
                        raw_wrong_coords, reference_3857,
                        lon_0_test, lat_0, k_0, ellps_param, towgs84_param
                    )
                else:
                    _, _, rmse_test, _ = self._calc_offset_ldp(
                        raw_wrong_coords, reference_wgs84,
                        lon_0_test, lat_0, k_0, ellps_param, towgs84_param
                    )
                return rmse_test

            search_result = self._golden_section_search(
                objective,
                search_left,
                search_right,
                tol=1e-6,
                max_iter=50
            )

            optimal_lon_0 = search_result['x']

            # Финальный расчёт с оптимальным lon_0
            if use_direct_3857:
                final_x0, final_y0, final_rmse, errors = self._calc_offset_ldp_3857(
                    raw_wrong_coords, reference_3857,
                    optimal_lon_0, lat_0, k_0, ellps_param, towgs84_param
                )
            else:
                final_x0, final_y0, final_rmse, errors = self._calc_offset_ldp(
                    raw_wrong_coords, reference_wgs84,
                    optimal_lon_0, lat_0, k_0, ellps_param, towgs84_param
                )

            # Статистика ошибок
            rmse, min_err, max_err = self._get_error_stats(errors)
            success = rmse < RMSE_THRESHOLD_OK

            # Определение зоны МСК
            zone_number = self._calculate_zone(optimal_lon_0)

            # Лог результата
            status = "OK" if success else "WARN"
            log_info(
                f"Fsm_0_5_4_11 [{self.method_id}] [LDP]: "
                f"lon_0={optimal_lon_0:.4f}° x_0={final_x0:.2f} y_0={final_y0:.2f} "
                f"RMSE={rmse:.4f}m [{status}]"
            )
            log_info(
                f"Fsm_0_5_4_11 [LDP]: Определена зона МСК: {zone_number}"
            )

            return CalculationResult(
                method_name=self.name,
                method_id=self.method_id,
                lon_0=optimal_lon_0,
                x_0=final_x0,
                y_0=final_y0,
                towgs84_param=towgs84_param,
                ellps_param=ellps_param,
                datum_name="СК-42",
                rmse=rmse,
                min_error=min_err,
                max_error=max_err,
                success=success,
                min_points_required=self.min_points,
                approach_type="ldp",
                diagnostics={
                    'errors': errors,
                    'scan_results': scan_results[:10],
                    'zone_number': zone_number,
                    'search_iterations': search_result['iterations'],
                    'initial_lon_0_ignored': initial_lon_0
                }
            )

        except Exception as e:
            log_error(f"Fsm_0_5_4_11 [LDP]: Ошибка расчёта: {e}")
            return None

    def _calculate_zone(self, lon_0: float) -> int:
        """
        Определение номера зоны МСК по центральному меридиану.

        Зоны МСК шириной 6° с центральными меридианами:
        - Зона 4: lon_0 = 21° (Калининград)
        - Зона 5: lon_0 = 27°
        - ...
        - Зона 32: lon_0 = 189° (но обычно используется 177° для дальнего востока)

        Parameters:
        -----------
        lon_0 : float
            Центральный меридиан в градусах

        Returns:
        --------
        int : Номер зоны МСК
        """
        # Стандартная формула: зона = (lon_0 + 3) / 6
        # Но учитываем нестандартные зоны
        zone = int((lon_0 + 3) / 6)
        return zone

    # Методы _calc_offset, _calc_offset_ldp, _golden_section_search, _get_error_stats
    # наследуются из BaseCalculationMethod
