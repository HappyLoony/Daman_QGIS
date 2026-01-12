# -*- coding: utf-8 -*-
"""
Fsm_0_5_4_8 - Полный перебор: все методы × все СК (FullScanDetector)

Минимум: 1 точка
Определяет: оптимальную комбинацию (метод расчёта + базовая СК)

Алгоритм:
1. Перебирает ВСЕ доступные методы расчёта (1-7)
2. Для КАЖДОГО метода тестирует ВСЕ 4 базовые СК
3. Формирует сводную таблицу результатов (до 28 комбинаций)
4. Выбирает лучшую комбинацию (метод + СК) с минимальной RMSE

Применение:
- Росреестр не раскрывает на какой базе работают МСК регионов
- Некоторые регионы могли тихо перейти с СК-42 на ГСК-2011
- Полный перебор позволяет найти оптимальную комбинацию

ГОСТ 32453-2017 - параметры преобразований
ГОСТ Р 70846.16-2024 - системы координат
"""

import math
from typing import List, Tuple, Dict, Optional, Any
from dataclasses import dataclass

from qgis.core import (
    QgsPointXY,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject
)

from .Fsm_0_5_4_base_method import BaseCalculationMethod, CalculationResult
from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.constants import (
    # Эллипсоиды
    ELLIPSOID_GSK2011_A, ELLIPSOID_GSK2011_F,
    ELLIPSOID_PZ90_A, ELLIPSOID_PZ90_F,
    # PROJ параметры эллипсоидов
    ELLPS_KRASS,
    # Параметры towgs84
    TOWGS84_SK42_PROJ,
    TOWGS84_SK95_PROJ,
    TOWGS84_GSK2011_PROJ,
    TOWGS84_PZ9011_PROJ,
)


@dataclass
class DatumConfig:
    """Конфигурация базовой системы координат"""
    name: str           # Название для отображения
    datum_id: str       # Идентификатор (sk42, sk95, gsk2011, pz9011)
    ellps_param: str    # Параметр эллипсоида для PROJ
    towgs84_param: str  # Параметр towgs84 для PROJ
    description: str    # Описание


# Конфигурации базовых СК (ГОСТ 32453-2017)
DATUM_CONFIGS = [
    DatumConfig(
        name="СК-42",
        datum_id="sk42",
        ellps_param=ELLPS_KRASS,
        towgs84_param=TOWGS84_SK42_PROJ,
        description="Система координат 1942 года (эллипсоид Красовского)"
    ),
    DatumConfig(
        name="СК-95",
        datum_id="sk95",
        ellps_param=ELLPS_KRASS,
        towgs84_param=TOWGS84_SK95_PROJ,
        description="Система координат 1995 года (эллипсоид Красовского)"
    ),
    DatumConfig(
        name="ГСК-2011",
        datum_id="gsk2011",
        ellps_param=f"+a={ELLIPSOID_GSK2011_A} +rf={1/ELLIPSOID_GSK2011_F}",
        towgs84_param=TOWGS84_GSK2011_PROJ,
        description="Геодезическая система координат 2011 года (эллипсоид ЦНИИГАиК)"
    ),
    DatumConfig(
        name="ПЗ-90.11",
        datum_id="pz9011",
        ellps_param=f"+a={ELLIPSOID_PZ90_A} +rf={1/ELLIPSOID_PZ90_F}",
        towgs84_param=TOWGS84_PZ9011_PROJ,
        description="Параметры Земли 1990.11 (эллипсоид ПЗ-90)"
    ),
]


def get_datum_configs() -> List[DatumConfig]:
    """Получить список конфигураций базовых СК"""
    return DATUM_CONFIGS


class Fsm_0_5_4_8_DatumDetector(BaseCalculationMethod):
    """
    Полный перебор: все методы × все СК.

    Тестирует каждый метод расчёта (1-7) с каждой базовой СК (4 штуки),
    формирует сводную таблицу и выбирает лучшую комбинацию.

    Минимум: 1 точка.
    """

    def __init__(self):
        """Инициализация с ленивой загрузкой методов"""
        self._methods_cache: Optional[List[BaseCalculationMethod]] = None

    def _get_calculation_methods(self) -> List[BaseCalculationMethod]:
        """
        Ленивая загрузка методов расчёта (исключая себя).

        Импортируем здесь чтобы избежать циклических импортов.
        """
        if self._methods_cache is None:
            from .Fsm_0_5_4_1_simple_offset import Fsm_0_5_4_1_SimpleOffset
            from .Fsm_0_5_4_2_offset_meridian import Fsm_0_5_4_2_OffsetMeridian
            from .Fsm_0_5_4_3_affine import Fsm_0_5_4_3_Affine
            from .Fsm_0_5_4_4_helmert_7p import Fsm_0_5_4_4_Helmert7P
            from .Fsm_0_5_4_5_scikit_affine import Fsm_0_5_4_5_ScikitAffine
            from .Fsm_0_5_4_6_gdal_gcp import Fsm_0_5_4_6_GdalGcp
            from .Fsm_0_5_4_7_projestions_api import Fsm_0_5_4_7_ProjectionsApi

            self._methods_cache = [
                Fsm_0_5_4_1_SimpleOffset(),
                Fsm_0_5_4_2_OffsetMeridian(),
                Fsm_0_5_4_3_Affine(),
                Fsm_0_5_4_4_Helmert7P(),
                Fsm_0_5_4_5_ScikitAffine(),
                Fsm_0_5_4_6_GdalGcp(),
                Fsm_0_5_4_7_ProjectionsApi(),
            ]
        return self._methods_cache

    @property
    def name(self) -> str:
        return "Полный перебор (все методы × все СК)"

    @property
    def method_id(self) -> str:
        return "full_scan"

    @property
    def min_points(self) -> int:
        return 1

    @property
    def description(self) -> str:
        return (
            "Полный перебор: тестирует ВСЕ методы расчёта с ВСЕМИ базовыми СК "
            "(СК-42, СК-95, ГСК-2011, ПЗ-90.11). Выводит сводную таблицу и "
            "выбирает оптимальную комбинацию."
        )

    def calculate(
        self,
        control_points_wgs84: List[Tuple[QgsPointXY, QgsPointXY]],
        base_params: Dict,
        initial_lon_0: float
    ) -> CalculationResult:
        """
        Полный перебор всех комбинаций.

        Тестирует каждый метод с каждой СК, формирует сводную таблицу.
        """
        if not control_points_wgs84:
            log_error("Fsm_0_5_4_8: Нет контрольных точек")
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

        num_points = len(control_points_wgs84)
        methods = self._get_calculation_methods()

        # Фильтруем методы по доступности и количеству точек
        available_methods = [
            m for m in methods
            if m.is_available() and m.can_run(num_points)
        ]

        if not available_methods:
            log_error("Fsm_0_5_4_8: Нет доступных методов для данного количества точек")
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

        total_combinations = len(available_methods) * len(DATUM_CONFIGS)
        log_info(
            f"Fsm_0_5_4_8: Полный перебор - "
            f"{len(available_methods)} методов × {len(DATUM_CONFIGS)} СК = "
            f"{total_combinations} комбинаций"
        )

        # Результаты: список (method, datum, result)
        all_results: List[Tuple[BaseCalculationMethod, DatumConfig, CalculationResult]] = []

        # Сводная таблица для diagnostics
        results_table: Dict[str, Any] = {}

        for method in available_methods:
            method_results = {}

            for datum_config in DATUM_CONFIGS:
                try:
                    # Модифицируем base_params для текущей СК
                    modified_params = base_params.copy()
                    modified_params['ellps_param'] = datum_config.ellps_param
                    modified_params['towgs84_param'] = datum_config.towgs84_param

                    # Запускаем метод
                    result = method.calculate(
                        control_points_wgs84=control_points_wgs84,
                        base_params=modified_params,
                        initial_lon_0=initial_lon_0
                    )

                    all_results.append((method, datum_config, result))

                    # Сохраняем в таблицу
                    method_results[datum_config.datum_id] = {
                        'datum_name': datum_config.name,
                        'rmse': result.rmse,
                        'x_0': result.x_0,
                        'y_0': result.y_0,
                        'success': result.success
                    }

                    status = "OK" if result.success else "-"
                    log_info(
                        f"  [{method.method_id}] + [{datum_config.datum_id}]: "
                        f"RMSE={result.rmse:.4f}m [{status}]"
                    )

                except Exception as e:
                    log_warning(
                        f"  [{method.method_id}] + [{datum_config.datum_id}]: "
                        f"Ошибка - {e}"
                    )
                    method_results[datum_config.datum_id] = {
                        'datum_name': datum_config.name,
                        'rmse': float('inf'),
                        'x_0': 0.0,
                        'y_0': 0.0,
                        'success': False,
                        'error': str(e)
                    }

            results_table[method.method_id] = {
                'method_name': method.name,
                'results': method_results
            }

        # Выбираем лучшую комбинацию
        if not all_results:
            log_error("Fsm_0_5_4_8: Все расчёты завершились ошибкой")
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

        best_method, best_datum, best_result = min(
            all_results,
            key=lambda x: x[2].rmse
        )

        # Логируем сводку
        log_info("Fsm_0_5_4_8: СВОДНАЯ ТАБЛИЦА РЕЗУЛЬТАТОВ")
        self._log_results_table(results_table)
        log_info(
            f"ЛУЧШАЯ КОМБИНАЦИЯ: {best_method.name} + {best_datum.name} "
            f"(RMSE={best_result.rmse:.4f}m)"
        )

        # Формируем итоговый результат
        return CalculationResult(
            method_name=f"{best_method.name} + {best_datum.name}",
            method_id=self.method_id,
            lon_0=best_result.lon_0,
            x_0=best_result.x_0,
            y_0=best_result.y_0,
            towgs84_param=best_datum.towgs84_param,
            ellps_param=best_datum.ellps_param,
            datum_name=best_datum.name,
            rmse=best_result.rmse,
            min_error=best_result.min_error,
            max_error=best_result.max_error,
            success=best_result.success,
            min_points_required=self.min_points,
            diagnostics={
                'best_method_id': best_method.method_id,
                'best_method_name': best_method.name,
                'best_datum_id': best_datum.datum_id,
                'best_datum_name': best_datum.name,
                'ellps_param': best_datum.ellps_param,
                'towgs84_param': best_datum.towgs84_param,
                'total_combinations': total_combinations,
                'results_table': results_table,
                'original_result': {
                    'lon_0': best_result.lon_0,
                    'x_0': best_result.x_0,
                    'y_0': best_result.y_0,
                    'rmse': best_result.rmse,
                    'diagnostics': best_result.diagnostics
                }
            }
        )

    def _log_results_table(self, results_table: Dict[str, Dict[str, Dict]]) -> None:
        """Выводит сводную таблицу результатов в лог"""
        # Заголовок
        header = "Метод".ljust(20)
        for datum in DATUM_CONFIGS:
            header += datum.name.center(12)
        log_info(header)
        log_info("-" * (20 + 12 * len(DATUM_CONFIGS)))

        # Строки
        for method_id, method_data in results_table.items():
            row = method_data['method_name'][:18].ljust(20)
            for datum in DATUM_CONFIGS:
                datum_result = method_data['results'].get(datum.datum_id, {})
                rmse = datum_result.get('rmse', float('inf'))
                if rmse == float('inf'):
                    cell = "ERR"
                elif rmse < 1.0:
                    cell = f"{rmse:.2f}*"  # Отмечаем успешные
                else:
                    cell = f"{rmse:.2f}"
                row += cell.center(12)
            log_info(row)
