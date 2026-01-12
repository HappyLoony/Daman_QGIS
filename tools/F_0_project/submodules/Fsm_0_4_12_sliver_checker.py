# -*- coding: utf-8 -*-
"""
Модуль проверки sliver-полигонов через формулу Polsby-Popper (Isoperimetric Quotient)

Sliver (щепка) - тонкий вытянутый полигон, обычно артефакт overlay операций.

Формула Polsby-Popper (Thinness Ratio):
    T = 4 * pi * Area / Perimeter^2

Диапазон: 0 до 1
- 1 = идеальный круг (максимальная компактность)
- -> 0 = вытянутые/тонкие формы (slivers)

Источники:
- ArcGIS Pro: https://pro.arcgis.com/en/pro-app/latest/help/data/validating-data/polygon-sliver.htm
- Alex Tereshenkov: https://tereshenkov.wordpress.com/2014/04/08/fighting-sliver-polygons-in-arcgis-thinness-ratio/
"""

import math
from typing import List, Dict, Any, Tuple, Optional
from qgis.core import (
    QgsVectorLayer, QgsGeometry, QgsPointXY, QgsWkbTypes
)
from Daman_QGIS.utils import log_info, log_warning


class Fsm_0_4_12_SliverChecker:
    """
    Проверка sliver-полигонов через формулу Polsby-Popper

    Использует нормализованный индекс компактности (0-1),
    не зависящий от размера полигона.
    """

    # Порог thinness ratio для определения sliver
    # Значения < 0.3 считаются sliver-кандидатами (ArcGIS best practice)
    # Более строгий порог: 0.1 (явные slivers)
    DEFAULT_THINNESS_THRESHOLD = 0.3

    # Максимальная площадь для проверки (м²)
    # Крупные полигоны с низким thinness ratio могут быть легитимными
    # (например, длинные узкие участки вдоль дорог)
    # 0 = проверять все полигоны
    DEFAULT_MAX_AREA = 0.0

    # Минимальная площадь для проверки (м²)
    # Слишком маленькие полигоны могут давать некорректные результаты
    MIN_AREA = 0.01  # 1 см² - артефакты округления

    def __init__(self,
                 thinness_threshold: Optional[float] = None,
                 max_area: Optional[float] = None):
        """
        Инициализация checker'а

        Args:
            thinness_threshold: Порог thinness ratio (0-1). По умолчанию 0.3
            max_area: Максимальная площадь для проверки (м²). 0 = все
        """
        self.thinness_threshold = thinness_threshold or self.DEFAULT_THINNESS_THRESHOLD
        self.max_area = max_area if max_area is not None else self.DEFAULT_MAX_AREA
        self.slivers_found = 0

    def check(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Проверка слоя на sliver-полигоны

        Args:
            layer: Полигональный слой для проверки

        Returns:
            Список найденных slivers с метаданными
        """
        errors = []

        # Проверяем что слой полигональный
        if layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            log_info(f"Fsm_0_4_12: Слой '{layer.name()}' не полигональный, пропуск")
            return errors

        log_info(f"Fsm_0_4_12: Проверка sliver-полигонов (Polsby-Popper) для '{layer.name()}'")
        log_info(f"Fsm_0_4_12: Порог thinness: {self.thinness_threshold}, макс. площадь: {self.max_area}")

        checked_count = 0
        skipped_small = 0
        skipped_large = 0

        for feature in layer.getFeatures():
            fid = feature.id()
            geom = feature.geometry()

            if not geom or geom.isEmpty():
                continue

            area = geom.area()
            perimeter = geom.length()

            # Пропускаем слишком маленькие полигоны
            if area < self.MIN_AREA:
                skipped_small += 1
                continue

            # Пропускаем слишком большие полигоны (если задан лимит)
            if self.max_area > 0 and area > self.max_area:
                skipped_large += 1
                continue

            # Защита от деления на ноль
            if perimeter == 0:
                continue

            checked_count += 1

            # Вычисляем Polsby-Popper thinness ratio
            # T = 4 * pi * Area / Perimeter^2
            thinness = self._calculate_thinness_ratio(area, perimeter)

            # Проверяем порог
            if thinness < self.thinness_threshold:
                # Определяем центроид для визуализации
                centroid = geom.centroid()

                errors.append({
                    'type': 'sliver_polsby_popper',
                    'geometry': centroid if centroid and not centroid.isEmpty() else geom,
                    'feature_id': fid,
                    'description': (
                        f'Sliver-полигон (Polsby-Popper): thinness={thinness:.4f} '
                        f'(порог {self.thinness_threshold}), '
                        f'площадь={area:.2f} м², периметр={perimeter:.2f} м'
                    ),
                    'thinness_ratio': thinness,
                    'area': area,
                    'perimeter': perimeter
                })

        self.slivers_found = len(errors)

        # Логирование результатов
        log_info(f"Fsm_0_4_12: Проверено {checked_count} полигонов")
        if skipped_small > 0:
            log_info(f"Fsm_0_4_12: Пропущено мелких (< {self.MIN_AREA} м²): {skipped_small}")
        if skipped_large > 0:
            log_info(f"Fsm_0_4_12: Пропущено крупных (> {self.max_area} м²): {skipped_large}")

        if self.slivers_found > 0:
            log_warning(f"Fsm_0_4_12: Найдено {self.slivers_found} sliver-полигонов")
        else:
            log_info("Fsm_0_4_12: Sliver-полигоны не обнаружены")

        return errors

    def _calculate_thinness_ratio(self, area: float, perimeter: float) -> float:
        """
        Вычисление Polsby-Popper thinness ratio

        Formula: T = 4 * pi * Area / Perimeter^2

        Args:
            area: Площадь полигона
            perimeter: Периметр полигона

        Returns:
            Thinness ratio (0-1), где 1 = круг
        """
        if perimeter == 0:
            return 0.0

        return (4.0 * math.pi * area) / (perimeter ** 2)

    def get_sliver_count(self) -> int:
        """Возвращает количество найденных slivers"""
        return self.slivers_found

    @staticmethod
    def get_threshold_recommendations() -> Dict[str, float]:
        """
        Рекомендации по порогам thinness ratio

        Returns:
            Словарь с рекомендованными порогами
        """
        return {
            'strict': 0.1,      # Только явные slivers
            'normal': 0.3,      # Стандартный порог (ArcGIS)
            'relaxed': 0.5,     # Мягкий порог
            'circle': 1.0       # Идеальный круг
        }
