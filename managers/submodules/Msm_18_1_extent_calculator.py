# -*- coding: utf-8 -*-
"""
Msm_18_1: Калькулятор экстентов по геометриям

Вычисляет bounding box по крайним точкам геометрий.
Поддерживает адаптивный padding для вытянутых bounding box.
"""

from typing import List, Optional
from qgis.core import (
    QgsRectangle,
    QgsGeometry,
    QgsVectorLayer,
    QgsFeatureRequest
)
from Daman_QGIS.utils import log_info


class ExtentCalculator:
    """
    Вычисление экстента по геометриям слоя.

    Методы padding:
    - add_padding_simple() - равномерный через scale()
    - add_padding_adaptive() - больше по короткой стороне для вытянутых bbox
    - add_padding_fixed() - фиксированное расстояние в метрах
    - add_padding() - унифицированный метод
    """

    def calculate_from_layer(
        self,
        layer: QgsVectorLayer,
        feature_filter: Optional[str] = None
    ) -> QgsRectangle:
        """
        Вычисляет bounding box по всем геометриям слоя.

        Args:
            layer: Векторный слой
            feature_filter: Опционально - выражение фильтра

        Returns:
            QgsRectangle: Bounding box слоя
        """
        if feature_filter:
            # Вычисляем extent только по отфильтрованным объектам
            request = QgsFeatureRequest().setFilterExpression(feature_filter)
            combined_extent = QgsRectangle()
            for feature in layer.getFeatures(request):
                if feature.hasGeometry():
                    combined_extent.combineExtentWith(feature.geometry().boundingBox())
            log_info(f"Msm_18_1: Экстент по фильтру '{feature_filter}': {combined_extent.toString()}")
            return combined_extent

        extent = layer.extent()
        log_info(f"Msm_18_1: Экстент слоя '{layer.name()}': {extent.toString()}")
        return extent

    def calculate_from_geometry(self, geometry: QgsGeometry) -> QgsRectangle:
        """
        Экстент одной геометрии.

        Args:
            geometry: Геометрия

        Returns:
            QgsRectangle: Bounding box геометрии
        """
        return geometry.boundingBox()

    def calculate_from_geometries(self, geometries: List[QgsGeometry]) -> QgsRectangle:
        """
        Объединённый экстент нескольких геометрий.

        Args:
            geometries: Список геометрий

        Returns:
            QgsRectangle: Объединённый bounding box
        """
        combined = QgsRectangle()
        for geom in geometries:
            if geom and not geom.isNull():
                combined.combineExtentWith(geom.boundingBox())
        return combined

    def add_padding_simple(
        self,
        extent: QgsRectangle,
        padding_percent: float = 10.0
    ) -> QgsRectangle:
        """
        Простой padding через встроенный метод scaled().

        Best practice: использовать scaled() для равномерного padding.
        scaled(1.1) = +10% вокруг центра

        Args:
            extent: Исходный экстент
            padding_percent: Процент расширения (10.0 = 10%)

        Returns:
            QgsRectangle: Расширенный экстент
        """
        factor = 1 + (padding_percent / 100)
        return extent.scaled(factor)

    def add_padding_adaptive(
        self,
        extent: QgsRectangle,
        padding_percent: float = 10.0,
        min_padding_meters: float = 50.0
    ) -> QgsRectangle:
        """
        Адаптивный padding для вытянутых bounding box.

        Анализирует соотношение сторон bounding box (не тип объекта!):
        - ratio > 2: bbox вытянут горизонтально - больше padding по Y
        - ratio < 0.5: bbox вытянут вертикально - больше padding по X
        - 0.5 <= ratio <= 2: компактный bbox - равномерный padding

        Args:
            extent: Исходный экстент
            padding_percent: Базовый процент расширения
            min_padding_meters: Минимальный padding в метрах

        Returns:
            QgsRectangle: Расширенный экстент
        """
        width = extent.width()
        height = extent.height()

        if width <= 0 or height <= 0:
            return extent.scaled(1 + padding_percent / 100)

        ratio = width / height

        if ratio > 2:  # Вытянут горизонтально - больше padding по Y
            pad_x = max(width * padding_percent / 100, min_padding_meters)
            pad_y = max(height * padding_percent * 2 / 100, min_padding_meters)
            log_info(f"Msm_18_1: Вытянутый bbox (ratio={ratio:.2f}), adaptive padding по Y")
        elif ratio < 0.5:  # Вытянут вертикально - больше padding по X
            pad_x = max(width * padding_percent * 2 / 100, min_padding_meters)
            pad_y = max(height * padding_percent / 100, min_padding_meters)
            log_info(f"Msm_18_1: Вытянутый bbox (ratio={ratio:.2f}), adaptive padding по X")
        else:  # Компактный bbox - равномерный padding
            return extent.scaled(1 + padding_percent / 100)

        return QgsRectangle(
            extent.xMinimum() - pad_x,
            extent.yMinimum() - pad_y,
            extent.xMaximum() + pad_x,
            extent.yMaximum() + pad_y
        )

    def add_padding_fixed(
        self,
        extent: QgsRectangle,
        buffer_meters: float = 100.0
    ) -> QgsRectangle:
        """
        Фиксированный padding в метрах.

        Использует buffered() - добавляет фиксированное расстояние.

        Args:
            extent: Исходный экстент
            buffer_meters: Буфер в единицах карты (метры для метрических CRS)

        Returns:
            QgsRectangle: Расширенный экстент
        """
        return extent.buffered(buffer_meters)

    def add_padding(
        self,
        extent: QgsRectangle,
        padding_percent: float = 10.0,
        adaptive: bool = True,
        min_padding_meters: float = 50.0
    ) -> QgsRectangle:
        """
        Унифицированный метод добавления padding.

        Args:
            extent: Исходный экстент
            padding_percent: Процент расширения
            adaptive: True - адаптивный для линейных, False - равномерный
            min_padding_meters: Минимальный padding в метрах (для adaptive)

        Returns:
            QgsRectangle: Расширенный экстент
        """
        if adaptive:
            return self.add_padding_adaptive(extent, padding_percent, min_padding_meters)
        return self.add_padding_simple(extent, padding_percent)
