# -*- coding: utf-8 -*-
"""
Msm_18_2: Подгонка экстента под соотношение сторон карты

Расширяет экстент чтобы он соответствовал aspect ratio карты в макете.
"""

from qgis.core import QgsRectangle, QgsLayoutItemMap
from Daman_QGIS.utils import log_info


class AspectRatioFitter:
    """
    Подгонка экстента под соотношение сторон карты.

    Расширяет экстент (не сжимает) до нужного aspect ratio.
    """

    def fit_extent_to_ratio(
        self,
        extent: QgsRectangle,
        target_width: float,
        target_height: float,
        expand_only: bool = True
    ) -> QgsRectangle:
        """
        Подгоняет экстент под соотношение сторон.

        Args:
            extent: Исходный экстент
            target_width: Целевая ширина (для расчёта ratio)
            target_height: Целевая высота (для расчёта ratio)
            expand_only: Только расширяет, не сжимает

        Returns:
            QgsRectangle: Экстент с нужным aspect ratio
        """
        if extent.isEmpty():
            return extent

        if extent.height() <= 0 or target_height <= 0:
            return extent

        extent_ratio = extent.width() / extent.height()
        target_ratio = target_width / target_height

        center_x = extent.center().x()
        center_y = extent.center().y()

        if extent_ratio > target_ratio:
            # Экстент шире чем карта - расширяем по высоте
            new_width = extent.width()
            new_height = new_width / target_ratio
            log_info(f"Msm_18_2: Расширение по высоте (extent_ratio={extent_ratio:.2f} > target={target_ratio:.2f})")
        else:
            # Экстент выше чем карта - расширяем по ширине
            new_height = extent.height()
            new_width = new_height * target_ratio
            log_info(f"Msm_18_2: Расширение по ширине (extent_ratio={extent_ratio:.2f} < target={target_ratio:.2f})")

        return QgsRectangle(
            center_x - new_width / 2,
            center_y - new_height / 2,
            center_x + new_width / 2,
            center_y + new_height / 2
        )

    def get_map_item_aspect_ratio(self, map_item: QgsLayoutItemMap) -> float:
        """
        Получить aspect ratio карты в макете.

        Args:
            map_item: Карта в макете

        Returns:
            float: Соотношение ширина/высота
        """
        rect = map_item.rect()
        if rect.height() <= 0:
            return 1.0
        return rect.width() / rect.height()

    def get_map_item_dimensions(self, map_item: QgsLayoutItemMap) -> tuple:
        """
        Получить размеры карты в макете.

        Args:
            map_item: Карта в макете

        Returns:
            tuple: (width, height) в единицах макета (мм)
        """
        rect = map_item.rect()
        return (rect.width(), rect.height())
