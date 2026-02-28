# -*- coding: utf-8 -*-
"""
Msm_18_3: Применение экстента к картам в макете

Устанавливает экстент программно через setExtent().
Управляет data-defined свойствами экстента.

ВАЖНО: Print layouts НЕ потокобезопасны!
Все операции с макетами должны выполняться ТОЛЬКО из main thread.
Не вызывать из QgsTask или background threads.
"""

from typing import Optional
from qgis.core import (
    QgsRectangle,
    QgsPrintLayout,
    QgsLayoutItemMap,
    QgsLayoutObject,
    QgsProperty
)
from Daman_QGIS.utils import log_info, log_warning


class LayoutExtentApplier:
    """
    Применение экстента к картам в макете.

    Методы:
    - apply_extent() - программная установка через setExtent()
    - apply_extent_with_scale() - установка с фиксированным масштабом
    - set_extent_expression() - установка через data-defined выражения
    """

    # Data-defined property keys для экстента
    EXTENT_PROPERTIES = [
        QgsLayoutObject.MapXMin,
        QgsLayoutObject.MapXMax,
        QgsLayoutObject.MapYMin,
        QgsLayoutObject.MapYMax
    ]

    def apply_extent(
        self,
        map_item: QgsLayoutItemMap,
        extent: QgsRectangle,
        clear_data_defined: bool = True
    ) -> bool:
        """
        Применяет экстент к карте в макете.

        Best practice порядок операций:
        1. clear data-defined (если нужно)
        2. setExtent()
        3. refresh()

        Args:
            map_item: Карта в макете
            extent: Экстент для установки
            clear_data_defined: Отключить data-defined выражения для экстента

        Returns:
            bool: True если успешно
        """
        if not map_item:
            log_warning("Msm_18_3: map_item is None")
            return False

        if extent.isEmpty():
            log_warning("Msm_18_3: extent is empty")
            return False

        if clear_data_defined:
            self._clear_extent_expressions(map_item)

        # Основная операция
        map_item.setExtent(extent)

        # Best practice: invalidateCache() + refresh() для надёжного обновления
        # invalidateCache() помечает кэш как невалидный
        # refresh() форсирует немедленную перерисовку
        map_item.invalidateCache()
        map_item.refresh()

        log_info(f"Msm_18_3: Экстент применён: {extent.toString()}")
        return True

    def apply_extent_with_scale(
        self,
        map_item: QgsLayoutItemMap,
        extent: QgsRectangle,
        scale: Optional[float] = None,
        clear_data_defined: bool = True
    ) -> bool:
        """
        Применяет экстент и опционально масштаб.

        Если scale задан - используется setScale() который
        "sets new map scale and changes only the map extent"

        Args:
            map_item: Карта в макете
            extent: Экстент для установки
            scale: Масштаб (например 1000 для 1:1000), None - не менять
            clear_data_defined: Отключить data-defined выражения

        Returns:
            bool: True если успешно
        """
        if not map_item:
            log_warning("Msm_18_3: map_item is None")
            return False

        if clear_data_defined:
            self._clear_extent_expressions(map_item)

        map_item.setExtent(extent)

        if scale:
            # setScale меняет extent сохраняя центр
            map_item.setScale(scale)
            log_info(f"Msm_18_3: Установлен масштаб 1:{scale}")

        map_item.invalidateCache()
        map_item.refresh()
        return True

    def _clear_extent_expressions(self, map_item: QgsLayoutItemMap):
        """
        Отключает data-defined выражения для экстента.

        Best practice: устанавливаем пустой QgsProperty() вместо setActive(False),
        так как "Setting an invalid property will remove the property from the collection".

        Ref: https://gis.stackexchange.com/questions/474164/

        Args:
            map_item: Карта в макете
        """
        props = map_item.dataDefinedProperties()

        # Также очищаем MapScale если установлен
        all_extent_props = self.EXTENT_PROPERTIES + [QgsLayoutObject.MapScale]

        cleared_count = 0
        for prop_key in all_extent_props:
            # Проверяем есть ли свойство и активно ли оно
            if prop_key in props.propertyKeys():
                existing_prop = props.property(prop_key)
                if existing_prop and existing_prop.isActive():
                    # Best practice: устанавливаем пустой QgsProperty вместо setActive(False)
                    props.setProperty(prop_key, QgsProperty())
                    cleared_count += 1

        map_item.setDataDefinedProperties(props)

        if cleared_count > 0:
            log_info(f"Msm_18_3: Очищено {cleared_count} data-defined свойств экстента")

    def set_extent_expression(
        self,
        map_item: QgsLayoutItemMap,
        layer_name: str,
        padding_percent: float = 5.0
    ):
        """
        Устанавливает data-defined выражения для автоматического экстента.

        Альтернатива программному подходу - экстент будет пересчитываться
        при каждом refresh макета.

        Args:
            map_item: Карта в макете
            layer_name: Имя слоя для расчёта bounds
            padding_percent: Процент отступа
        """
        props = map_item.dataDefinedProperties()

        # Формируем выражения для каждой границы экстента
        pad = padding_percent / 100

        expressions = {
            QgsLayoutObject.MapXMin: f"x_min(bounds(aggregate('{layer_name}','collect',$geometry))) - (x_max(bounds(aggregate('{layer_name}','collect',$geometry))) - x_min(bounds(aggregate('{layer_name}','collect',$geometry)))) * {pad}",
            QgsLayoutObject.MapXMax: f"x_max(bounds(aggregate('{layer_name}','collect',$geometry))) + (x_max(bounds(aggregate('{layer_name}','collect',$geometry))) - x_min(bounds(aggregate('{layer_name}','collect',$geometry)))) * {pad}",
            QgsLayoutObject.MapYMin: f"y_min(bounds(aggregate('{layer_name}','collect',$geometry))) - (y_max(bounds(aggregate('{layer_name}','collect',$geometry))) - y_min(bounds(aggregate('{layer_name}','collect',$geometry)))) * {pad}",
            QgsLayoutObject.MapYMax: f"y_max(bounds(aggregate('{layer_name}','collect',$geometry))) + (y_max(bounds(aggregate('{layer_name}','collect',$geometry))) - y_min(bounds(aggregate('{layer_name}','collect',$geometry)))) * {pad}",
        }

        for prop_key, expr in expressions.items():
            props.setProperty(prop_key, QgsProperty.fromExpression(expr))

        map_item.setDataDefinedProperties(props)
        map_item.refreshDataDefinedProperty(QgsLayoutObject.AllProperties)
        log_info(f"Msm_18_3: Data-defined выражения установлены для слоя '{layer_name}'")

    def get_map_item_by_id(
        self,
        layout: QgsPrintLayout,
        map_id: str
    ) -> Optional[QgsLayoutItemMap]:
        """
        Получить карту по ID.

        Args:
            layout: Макет печати
            map_id: ID карты (например 'main_map')

        Returns:
            QgsLayoutItemMap или None
        """
        item = layout.itemById(map_id)
        if isinstance(item, QgsLayoutItemMap):
            return item
        log_warning(f"Msm_18_3: Карта '{map_id}' не найдена или не является QgsLayoutItemMap")
        return None

    def get_reference_map(self, layout: QgsPrintLayout) -> Optional[QgsLayoutItemMap]:
        """
        Получить основную (reference) карту макета.

        Args:
            layout: Макет печати

        Returns:
            QgsLayoutItemMap или None
        """
        return layout.referenceMap()

    def get_all_maps(self, layout: QgsPrintLayout) -> list:
        """
        Получить все карты в макете.

        Args:
            layout: Макет печати

        Returns:
            list[QgsLayoutItemMap]: Список всех карт
        """
        maps = []
        for item in layout.items():
            if isinstance(item, QgsLayoutItemMap):
                maps.append(item)
        return maps
