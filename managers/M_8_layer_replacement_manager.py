# -*- coding: utf-8 -*-
"""
LayerReplacementManager - Централизованный менеджер замены слоев

Обеспечивает:
- Замену существующих слоев при повторной загрузке
- Сохранение порядка слоев в дереве проекта
- Унифицированный API для всех функций плагина
"""

from typing import Optional, Tuple, List, Dict
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer, QgsMapLayer,
    QgsLayerTreeGroup, QgsLayerTreeLayer, QgsLayerTree
)
from Daman_QGIS.utils import log_info, log_warning


class LayerReplacementManager:
    """
    Менеджер замены слоев с сохранением порядка в дереве проекта

    Использование:
        manager = LayerReplacementManager()
        manager.replace_or_add_layer(new_layer, "L_1_2_1_WFS_ЗУ")
    """

    def __init__(self) -> None:
        """Инициализация менеджера"""
        self.project = QgsProject.instance()
        self.root = None
        self._update_root()

    def _update_root(self) -> None:
        """Обновление ссылки на корень дерева слоев"""
        self.root = self.project.layerTreeRoot()

    def replace_or_add_layer(
        self,
        new_layer: QgsMapLayer,
        layer_name: str,
        preserve_order: bool = False,
        parent_group: Optional[QgsLayerTreeGroup] = None
    ) -> QgsMapLayer:
        """
        Заменяет существующий слой или добавляет новый

        ВАЖНО: preserve_order=False по умолчанию, т.к. порядок должен определяться
        через LayerManager.sort_all_layers() согласно Base_layers.json

        Args:
            new_layer: Новый слой для добавления
            layer_name: Имя слоя для поиска существующего
            preserve_order: Сохранять позицию в дереве (по умолчанию False - порядок по базе)
            parent_group: Родительская группа (если None, используется root)

        Returns:
            Добавленный/замененный слой

        Example:
            >>> manager = LayerReplacementManager()
            >>> new_layer = QgsVectorLayer("path.gpkg", "L_1_1_1_Границы", "ogr")
            >>> layer = manager.replace_or_add_layer(new_layer, "L_1_1_1_Границы")
            >>> # Затем применить порядок всех слоёв:
            >>> layer_manager.sort_all_layers()
        """
        self._update_root()

        # Устанавливаем имя нового слоя
        new_layer.setName(layer_name)

        # Ищем существующий слой
        existing_layer = self.find_layer_by_name(layer_name)

        if existing_layer and preserve_order:
            # Получаем позицию и группу существующего слоя
            position, parent = self.get_layer_tree_position(existing_layer.id())

            # Удаляем старый слой
            self.project.removeMapLayer(existing_layer.id())

            # Вставляем новый на ту же позицию
            self.insert_layer_at_position(new_layer, position, parent or parent_group)

        elif existing_layer and not preserve_order:
            # Просто заменяем без сохранения позиции
            self.project.removeMapLayer(existing_layer.id())
            self.project.addMapLayer(new_layer, False)

            if parent_group:
                parent_group.addLayer(new_layer)
            elif self.root:
                self.root.addLayer(new_layer)

        else:
            # Слой не существует, просто добавляем
            self.project.addMapLayer(new_layer, False)

            if parent_group:
                parent_group.addLayer(new_layer)
            elif self.root:
                self.root.addLayer(new_layer)

        return new_layer

    def find_layer_by_name(self, layer_name: str) -> Optional[QgsMapLayer]:
        """
        Поиск слоя по имени в проекте

        Args:
            layer_name: Имя слоя для поиска

        Returns:
            QgsMapLayer или None если не найден
        """
        for layer_id, layer in self.project.mapLayers().items():
            if layer.name() == layer_name:
                return layer
        return None

    def get_layer_tree_position(
        self,
        layer_id: str
    ) -> Tuple[int, Optional[QgsLayerTreeGroup]]:
        """
        Получение позиции слоя в дереве и его родительской группы

        Args:
            layer_id: ID слоя

        Returns:
            Tuple (позиция, родительская_группа)
            Позиция = -1 если слой не найден в дереве

        Example:
            >>> position, parent_group = manager.get_layer_tree_position(layer.id())
            >>> print(f"Слой на позиции {position} в группе {parent_group.name()}")
        """
        self._update_root()

        if not self.root:
            return -1, None

        # Ищем слой в дереве
        layer_node = self.root.findLayer(layer_id)

        if not layer_node:
            return -1, None

        # Получаем родительскую группу
        parent = layer_node.parent()

        if not parent:
            return -1, None

        # Получаем позицию слоя среди детей родителя
        children = parent.children()
        for idx, child in enumerate(children):
            if isinstance(child, QgsLayerTreeLayer) and child.layerId() == layer_id:
                return idx, parent if isinstance(parent, QgsLayerTreeGroup) else None

        return -1, None

    def remove_layer_preserve_position(
        self,
        layer: Optional[QgsMapLayer]
    ) -> Tuple[Optional[int], Optional[QgsLayerTreeGroup]]:
        """
        Удаление слоя с сохранением информации о его позиции

        Args:
            layer: Слой для удаления (может быть None)

        Returns:
            Tuple (позиция, родительская_группа) или (None, None) если слой не найден

        Example:
            >>> position, parent = manager.remove_layer_preserve_position(old_layer)
            >>> # ... создаем new_layer ...
            >>> manager.insert_layer_at_position(new_layer, position, parent)
        """
        if not layer:
            return None, None

        # Получаем позицию до удаления
        position, parent_group = self.get_layer_tree_position(layer.id())

        if position == -1:
            # Слой не в дереве, просто удаляем из проекта
            self.project.removeMapLayer(layer.id())
            return None, None

        # Удаляем слой
        self.project.removeMapLayer(layer.id())

        return position, parent_group

    def insert_layer_at_position(
        self,
        layer: QgsMapLayer,
        position: Optional[int],
        parent_group: Optional[QgsLayerTreeGroup] = None
    ) -> bool:
        """
        Вставка слоя на конкретную позицию в дереве

        Args:
            layer: Слой для вставки
            position: Позиция для вставки (0-based индекс)
            parent_group: Родительская группа (если None, используется root)

        Returns:
            True если успешно вставлен

        Example:
            >>> manager.insert_layer_at_position(layer, 3, my_group)
        """
        self._update_root()

        if not self.root:
            return False

        # Добавляем слой в проект если его там еще нет
        if layer.id() not in self.project.mapLayers():
            self.project.addMapLayer(layer, False)

        # Если позиция не указана, добавляем в конец
        if position is None:
            if parent_group:
                parent_group.addLayer(layer)
            else:
                self.root.addLayer(layer)
            return True

        # Определяем родителя
        parent = parent_group if parent_group else self.root

        if not parent:
            return False

        # Проверяем границы позиции
        children_count = len(parent.children())
        if position < 0:
            position = 0
        elif position > children_count:
            position = children_count

        # Вставляем слой на позицию
        parent.insertLayer(position, layer)

        return True

    def replace_multiple_layers(
        self,
        layers_map: Dict[str, QgsMapLayer],
        preserve_order: bool = True
    ) -> Dict[str, QgsMapLayer]:
        """
        Пакетная замена нескольких слоев

        Args:
            layers_map: Словарь {имя_слоя: новый_слой}
            preserve_order: Сохранять позиции в дереве

        Returns:
            Словарь {имя_слоя: добавленный_слой}

        Example:
            >>> layers = {
            ...     "L_1_2_1_WFS_ЗУ": new_zu_layer,
            ...     "L_1_2_2_WFS_КК": new_kk_layer
            ... }
            >>> result = manager.replace_multiple_layers(layers)
        """
        result = {}

        for layer_name, new_layer in layers_map.items():
            replaced_layer = self.replace_or_add_layer(
                new_layer,
                layer_name,
                preserve_order=preserve_order
            )
            result[layer_name] = replaced_layer

        return result

    def find_layers_by_prefix(self, prefix: str) -> List[QgsMapLayer]:
        """
        Поиск всех слоев с заданным префиксом

        Args:
            prefix: Префикс для поиска (например, "L_1_2_")

        Returns:
            Список найденных слоев

        Example:
            >>> wms_layers = manager.find_layers_by_prefix("L_1_2_")
        """
        matching_layers = []

        for layer_id, layer in self.project.mapLayers().items():
            if layer.name().startswith(prefix):
                matching_layers.append(layer)

        return matching_layers

    def find_layers_by_pattern(
        self,
        pattern: str,
        layer_type: Optional[type] = None
    ) -> List[QgsMapLayer]:
        """
        Универсальный поиск слоёв по имени или префиксу

        Args:
            pattern: Полное имя слоя ИЛИ префикс (если заканчивается на '_')
                    Примеры:
                    - "L_2_1_2_Выборка_ОКС" - точное совпадение
                    - "Le_1_2_5_" - все слои, начинающиеся с Le_1_2_5_
            layer_type: Опциональный фильтр по типу слоя (QgsVectorLayer, QgsRasterLayer)

        Returns:
            Список найденных слоёв (может быть пустым)

        Example:
            >>> # Найти все ЗОУИТ слои
            >>> zouit_layers = manager.find_layers_by_pattern("Le_1_2_5_")
            >>> # Найти конкретный слой
            >>> layer = manager.find_layers_by_pattern("L_2_1_2_Выборка_ОКС")
            >>> # Только векторные слои
            >>> vectors = manager.find_layers_by_pattern("L_1_", QgsVectorLayer)
        """
        # Определяем режим поиска: префикс или точное совпадение
        is_prefix = pattern.endswith('_')

        if is_prefix:
            # Поиск по префиксу
            matching_layers = self.find_layers_by_prefix(pattern)
        else:
            # Точное совпадение
            layer = self.find_layer_by_name(pattern)
            matching_layers = [layer] if layer else []

        # Фильтруем по типу если указан
        if layer_type and matching_layers:
            matching_layers = [l for l in matching_layers if isinstance(l, layer_type)]

        return matching_layers

    def remove_layers_by_prefix(
        self,
        prefix: str,
        preserve_positions: bool = False
    ) -> Dict[str, Tuple[Optional[int], Optional[QgsLayerTreeGroup]]]:
        """
        Удаление всех слоев с заданным префиксом

        Args:
            prefix: Префикс для поиска
            preserve_positions: Сохранить информацию о позициях

        Returns:
            Словарь {имя_слоя: (позиция, группа)} если preserve_positions=True

        Example:
            >>> # Удалить все WMS слои
            >>> positions = manager.remove_layers_by_prefix("L_1_2_", preserve_positions=True)
        """
        layers = self.find_layers_by_prefix(prefix)
        positions_map = {}

        for layer in layers:
            if preserve_positions:
                pos, group = self.remove_layer_preserve_position(layer)
                positions_map[layer.name()] = (pos, group)
            else:
                self.project.removeMapLayer(layer.id())

        return positions_map if preserve_positions else {}

    def move_layer_to_top(self, layer: QgsMapLayer) -> bool:
        """
        Перемещает слой в самый верх порядка отрисовки (первый в customLayerOrder)

        БЕЗОПАСНЫЙ МЕТОД: Использует setCustomLayerOrder() вместо removeChildNode(),
        который вызывает краши QGIS (см. комментарий в M_2_layer_manager.py)

        Используется для слоёв которые должны быть всегда видны
        (например, слои ошибок топологии)

        Args:
            layer: Слой для перемещения

        Returns:
            True если успешно перемещён

        Example:
            >>> manager.move_layer_to_top(error_layer)
        """
        self._update_root()

        if not self.root or not layer:
            return False

        # Проверяем что слой в проекте
        if layer.id() not in self.project.mapLayers():
            log_warning(f"M_8: Слой '{layer.name()}' не найден в проекте")
            return False

        try:
            # БЕЗОПАСНЫЙ МЕТОД через setCustomLayerOrder()
            # НЕ использует removeChildNode/insertChildNode (которые вызывают краши)

            # 1. Включаем режим кастомного порядка если не включён
            if not self.root.hasCustomLayerOrder():
                self.root.setHasCustomLayerOrder(True)

            # 2. Получаем текущий порядок слоёв
            current_order = self.root.customLayerOrder()

            # 3. Удаляем слой из текущей позиции (если есть)
            new_order = [l for l in current_order if l.id() != layer.id()]

            # 4. Вставляем слой в начало (топ = первый в порядке отрисовки)
            new_order.insert(0, layer)

            # 5. Применяем новый порядок
            self.root.setCustomLayerOrder(new_order)

            log_info(f"M_8: Слой '{layer.name()}' перемещён в топ порядка отрисовки")
            return True

        except Exception as e:
            log_warning(f"M_8: Ошибка перемещения слоя '{layer.name()}' в топ: {e}")
            return False