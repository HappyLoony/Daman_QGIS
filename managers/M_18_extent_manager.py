# -*- coding: utf-8 -*-
"""
M_18: Менеджер экстентов для макетов и карт

Вычисляет экстент по крайним точкам полигонов (не по площади).
Программная установка экстента в QgsLayoutItemMap.
Поддержка адаптивного padding для линейных объектов.

Использование:
    from Daman_QGIS.managers import get_extent_manager

    extent_manager = get_extent_manager()

    # Применить экстент слоя к карте в макете
    extent_manager.apply_layer_extent_to_map(
        layout,
        map_id='main_map',
        layer=boundaries_layer,
        padding_percent=10.0,
        adaptive_padding=True
    )
"""

from typing import Optional
from qgis.core import (
    QgsRectangle,
    QgsGeometry,
    QgsVectorLayer,
    QgsPrintLayout,
    QgsLayoutItemMap
)
from Daman_QGIS.utils import log_info, log_warning

from .submodules.Msm_18_1_extent_calculator import ExtentCalculator
from .submodules.Msm_18_2_aspect_ratio_fitter import AspectRatioFitter
from .submodules.Msm_18_3_layout_applier import LayoutExtentApplier


class ExtentManager:
    """
    M_18: Менеджер экстентов для макетов и карт.

    Singleton через get_extent_manager().

    Компоненты:
    - calculator (Msm_18_1): Вычисление экстента по геометриям
    - fitter (Msm_18_2): Подгонка под aspect ratio карты
    - applier (Msm_18_3): Применение к макету
    """

    def __init__(self):
        self.calculator = ExtentCalculator()
        self.fitter = AspectRatioFitter()
        self.applier = LayoutExtentApplier()

    # === Высокоуровневые методы ===

    def apply_layer_extent_to_map(
        self,
        layout: QgsPrintLayout,
        map_id: str,
        layer: QgsVectorLayer,
        padding_percent: float = 10.0,
        adaptive_padding: bool = True,
        fit_to_map_ratio: bool = True,
        feature_filter: Optional[str] = None
    ) -> bool:
        """
        Главный метод: Вычисляет и применяет экстент слоя к карте в макете.

        1. Вычисляет bounding box слоя
        2. Добавляет padding (адаптивный для линейных объектов)
        3. Подгоняет под aspect ratio карты
        4. Применяет к карте (отключая выражения)

        Args:
            layout: Макет печати
            map_id: ID карты в макете (например 'main_map')
            layer: Векторный слой
            padding_percent: Процент расширения (default 10%)
            adaptive_padding: Адаптивный padding для линейных объектов
            fit_to_map_ratio: Подгонять под aspect ratio карты
            feature_filter: Опциональный фильтр объектов

        Returns:
            bool: True если успешно
        """
        log_info(f"M_18: apply_layer_extent_to_map('{map_id}', '{layer.name()}')")

        map_item = self.applier.get_map_item_by_id(layout, map_id)
        if not map_item:
            log_warning(f"M_18: Карта '{map_id}' не найдена в макете")
            return False

        # 1. Базовый экстент
        extent = self.calculator.calculate_from_layer(layer, feature_filter)
        if extent.isEmpty():
            log_warning(f"M_18: Пустой экстент для слоя '{layer.name()}'")
            return False

        # 2. Padding
        extent = self.calculator.add_padding(
            extent,
            padding_percent=padding_percent,
            adaptive=adaptive_padding
        )

        # 3. Подгонка под карту
        if fit_to_map_ratio:
            width, height = self.fitter.get_map_item_dimensions(map_item)
            extent = self.fitter.fit_extent_to_ratio(extent, width, height)

        # 4. Применение
        return self.applier.apply_extent(map_item, extent, clear_data_defined=True)

    def apply_geometry_extent_to_map(
        self,
        layout: QgsPrintLayout,
        map_id: str,
        geometry: QgsGeometry,
        padding_percent: float = 10.0,
        fit_to_map_ratio: bool = True
    ) -> bool:
        """
        Экстент по одной геометрии.

        Args:
            layout: Макет печати
            map_id: ID карты в макете
            geometry: Геометрия
            padding_percent: Процент расширения
            fit_to_map_ratio: Подгонять под aspect ratio карты

        Returns:
            bool: True если успешно
        """
        log_info(f"M_18: apply_geometry_extent_to_map('{map_id}')")

        map_item = self.applier.get_map_item_by_id(layout, map_id)
        if not map_item:
            return False

        extent = self.calculator.calculate_from_geometry(geometry)
        if extent.isEmpty():
            log_warning("M_18: Пустой экстент для геометрии")
            return False

        extent = self.calculator.add_padding(extent, padding_percent, adaptive=True)

        if fit_to_map_ratio:
            width, height = self.fitter.get_map_item_dimensions(map_item)
            extent = self.fitter.fit_extent_to_ratio(extent, width, height)

        return self.applier.apply_extent(map_item, extent)

    def apply_extent_to_reference_map(
        self,
        layout: QgsPrintLayout,
        layer: QgsVectorLayer,
        padding_percent: float = 10.0,
        adaptive_padding: bool = True
    ) -> bool:
        """
        Применить экстент к основной (reference) карте макета.

        Args:
            layout: Макет печати
            layer: Векторный слой
            padding_percent: Процент расширения
            adaptive_padding: Адаптивный padding

        Returns:
            bool: True если успешно
        """
        map_item = self.applier.get_reference_map(layout)
        if not map_item:
            log_warning("M_18: Reference карта не найдена в макете")
            return False

        extent = self.calculator.calculate_from_layer(layer)
        if extent.isEmpty():
            return False

        extent = self.calculator.add_padding(extent, padding_percent, adaptive=adaptive_padding)

        width, height = self.fitter.get_map_item_dimensions(map_item)
        extent = self.fitter.fit_extent_to_ratio(extent, width, height)

        return self.applier.apply_extent(map_item, extent)

    # === Низкоуровневые методы (для прямого доступа) ===

    def calculate_extent(
        self,
        layer: QgsVectorLayer,
        padding_percent: float = 10.0,
        adaptive: bool = True,
        feature_filter: Optional[str] = None
    ) -> QgsRectangle:
        """
        Только вычисление экстента (без применения).

        Args:
            layer: Векторный слой
            padding_percent: Процент расширения
            adaptive: Адаптивный padding для линейных
            feature_filter: Опциональный фильтр

        Returns:
            QgsRectangle: Вычисленный экстент
        """
        extent = self.calculator.calculate_from_layer(layer, feature_filter)
        return self.calculator.add_padding(extent, padding_percent, adaptive=adaptive)

    def fit_to_ratio(
        self,
        extent: QgsRectangle,
        width: float,
        height: float
    ) -> QgsRectangle:
        """
        Только подгонка под ratio (без применения).

        Args:
            extent: Исходный экстент
            width: Целевая ширина
            height: Целевая высота

        Returns:
            QgsRectangle: Подогнанный экстент
        """
        return self.fitter.fit_extent_to_ratio(extent, width, height)

    def apply_extent(
        self,
        map_item: QgsLayoutItemMap,
        extent: QgsRectangle,
        clear_data_defined: bool = True
    ) -> bool:
        """
        Только применение экстента (без вычислений).

        Args:
            map_item: Карта в макете
            extent: Экстент для установки
            clear_data_defined: Отключить data-defined выражения

        Returns:
            bool: True если успешно
        """
        return self.applier.apply_extent(map_item, extent, clear_data_defined)


# === Singleton ===

_extent_manager_instance = None


def get_extent_manager() -> ExtentManager:
    """
    Получить singleton экземпляр ExtentManager.

    Returns:
        ExtentManager: Единственный экземпляр менеджера
    """
    global _extent_manager_instance
    if _extent_manager_instance is None:
        _extent_manager_instance = ExtentManager()
    return _extent_manager_instance


def reset_extent_manager():
    """Сбросить singleton (для тестов)."""
    global _extent_manager_instance
    _extent_manager_instance = None
