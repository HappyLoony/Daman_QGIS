# -*- coding: utf-8 -*-
"""
Модуль проверки sliver-полигонов через native QGIS Processing алгоритм

Использует встроенный алгоритм qgis:checkgeometry -> Sliver polygons

Формула QGIS Thinness:
    Thinness = Area_of_MBR / Area_of_Polygon

Где MBR = Minimum Bounding Rectangle (минимальный ограничивающий прямоугольник)

Диапазон: 1 до infinity
- 1 = квадрат (идеальная форма)
- -> infinity = вытянутые формы

Источник: https://docs.qgis.org/testing/en/docs/user_manual/processing_algs/qgis/checkgeometry.html
"""

from typing import List, Dict, Any, Optional
from qgis.core import (
    QgsVectorLayer, QgsGeometry, QgsWkbTypes,
    QgsProcessingContext, QgsProcessingFeedback
)
from Daman_QGIS.utils import log_info, log_warning, log_error


class Fsm_0_4_13_SliverNativeChecker:
    """
    Проверка sliver-полигонов через native QGIS Processing

    Использует алгоритм qgis:checkgeometry с проверкой Sliver polygons.
    Thinness = MBR_Area / Polygon_Area (чем больше - тем тоньше полигон)
    """

    # Порог thinness по умолчанию (QGIS default = 20)
    # Полигоны с thinness > порога считаются slivers
    DEFAULT_THINNESS_THRESHOLD = 20.0

    # Максимальная площадь для проверки (м²)
    # 0 = проверять все полигоны
    DEFAULT_MAX_AREA = 0.0

    def __init__(self,
                 thinness_threshold: Optional[float] = None,
                 max_area: Optional[float] = None,
                 processing_context: Optional[QgsProcessingContext] = None):
        """
        Инициализация checker'а

        Args:
            thinness_threshold: Порог thinness (1+). По умолчанию 20
            max_area: Максимальная площадь для проверки (м²). 0 = все
            processing_context: Контекст для processing.run() (thread-safe)
        """
        self.thinness_threshold = thinness_threshold or self.DEFAULT_THINNESS_THRESHOLD
        self.max_area = max_area if max_area is not None else self.DEFAULT_MAX_AREA
        self.processing_context = processing_context
        self.feedback = QgsProcessingFeedback()
        self.slivers_found = 0

    def check(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Проверка слоя на sliver-полигоны через native QGIS

        Args:
            layer: Полигональный слой для проверки

        Returns:
            Список найденных slivers с метаданными
        """
        errors = []

        # Проверяем что слой полигональный
        if layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            log_info(f"Fsm_0_4_13: Слой '{layer.name()}' не полигональный, пропуск")
            return errors

        log_info(f"Fsm_0_4_13: Проверка sliver-полигонов (QGIS native) для '{layer.name()}'")
        log_info(f"Fsm_0_4_13: Порог thinness: {self.thinness_threshold}, макс. площадь: {self.max_area}")

        # Используем метод MBR (Minimum Bounding Rectangle) для вычисления thinness
        # Формула: Thinness = MBR_Area / Polygon_Area
        # Чем больше значение - тем более вытянутый полигон (sliver)
        errors = self._check_slivers_via_mbr(layer)

        self.slivers_found = len(errors)

        if self.slivers_found > 0:
            log_warning(f"Fsm_0_4_13: Найдено {self.slivers_found} sliver-полигонов (QGIS thinness)")
        else:
            log_info("Fsm_0_4_13: Sliver-полигоны не обнаружены")

        return errors

    def _check_slivers_via_mbr(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Проверка slivers через MBR (Minimum Bounding Rectangle)

        QGIS thinness = MBR_Area / Polygon_Area
        Чем больше значение - тем тоньше полигон

        Args:
            layer: Полигональный слой

        Returns:
            Список sliver-ошибок
        """
        errors = []
        checked_count = 0
        skipped_large = 0

        for feature in layer.getFeatures():
            fid = feature.id()
            geom = feature.geometry()

            if not geom or geom.isEmpty():
                continue

            area = geom.area()

            # Пропускаем полигоны с нулевой площадью
            if area <= 0:
                continue

            # Пропускаем слишком большие полигоны (если задан лимит)
            if self.max_area > 0 and area > self.max_area:
                skipped_large += 1
                continue

            checked_count += 1

            # Получаем Oriented Minimum Bounding Box
            # orientedMinimumBoundingBox() возвращает (геометрия, площадь, угол, ширина, высота)
            obb_result = geom.orientedMinimumBoundingBox()

            if obb_result and len(obb_result) >= 2:
                mbr_area = obb_result[1]  # Площадь MBR

                if mbr_area > 0:
                    # Вычисляем QGIS thinness
                    thinness = mbr_area / area

                    # Проверяем порог (чем больше thinness - тем тоньше)
                    if thinness > self.thinness_threshold:
                        centroid = geom.centroid()

                        # Получаем размеры MBR для описания
                        width = obb_result[3] if len(obb_result) > 3 else 0
                        height = obb_result[4] if len(obb_result) > 4 else 0
                        aspect_ratio = max(width, height) / min(width, height) if min(width, height) > 0 else 0

                        errors.append({
                            'type': 'sliver_qgis_native',
                            'geometry': centroid if centroid and not centroid.isEmpty() else geom,
                            'feature_id': fid,
                            'description': (
                                f'Sliver-полигон (QGIS native): thinness={thinness:.2f} '
                                f'(порог {self.thinness_threshold}), '
                                f'площадь={area:.2f} м², '
                                f'MBR={mbr_area:.2f} м², '
                                f'соотношение сторон={aspect_ratio:.1f}:1'
                            ),
                            'thinness_ratio': thinness,
                            'area': area,
                            'mbr_area': mbr_area,
                            'aspect_ratio': aspect_ratio
                        })

        log_info(f"Fsm_0_4_13: Проверено {checked_count} полигонов")
        if skipped_large > 0:
            log_info(f"Fsm_0_4_13: Пропущено крупных (> {self.max_area} м²): {skipped_large}")

        return errors

    def get_sliver_count(self) -> int:
        """Возвращает количество найденных slivers"""
        return self.slivers_found

    @staticmethod
    def get_threshold_recommendations() -> Dict[str, float]:
        """
        Рекомендации по порогам QGIS thinness

        QGIS thinness = MBR_Area / Polygon_Area
        Чем больше - тем тоньше полигон

        Returns:
            Словарь с рекомендованными порогами
        """
        return {
            'strict': 50.0,     # Только очень тонкие slivers
            'normal': 20.0,     # Стандартный порог (QGIS default)
            'relaxed': 10.0,    # Мягкий порог (больше ложных срабатываний)
            'square': 1.0       # Идеальный квадрат (невозможно быть меньше)
        }

    @staticmethod
    def convert_polsby_popper_to_qgis(pp_threshold: float) -> float:
        """
        Приблизительная конвертация порога Polsby-Popper в QGIS thinness

        Polsby-Popper: 0-1 (1 = круг)
        QGIS thinness: 1+ (1 = квадрат)

        Приблизительная формула (эмпирическая):
        QGIS_thinness ≈ 1 / (PP_ratio * factor)

        Args:
            pp_threshold: Порог Polsby-Popper (0-1)

        Returns:
            Приблизительный порог QGIS thinness
        """
        if pp_threshold <= 0:
            return 100.0  # Очень строгий порог

        # Эмпирический коэффициент (круг vs квадрат)
        # Круг: PP=1, QGIS≈1.27 (pi/4 * 4/pi = 1 для круга в квадратном MBR)
        # Очень тонкий: PP=0.1, QGIS≈50+

        # Приблизительная обратная зависимость
        return 1.0 / (pp_threshold * 0.8)
