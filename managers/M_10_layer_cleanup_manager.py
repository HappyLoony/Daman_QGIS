# -*- coding: utf-8 -*-
"""
Централизованный менеджер очистки слоев перед запуском функций
"""

import json
import os
from typing import List, Optional
from qgis.core import QgsProject, QgsVectorLayer
from Daman_QGIS.utils import log_info, log_warning


class LayerCleanupManager:
    """Менеджер для удаления слоев перед повторным запуском функций"""

    # Singleton: общий экземпляр для всех инструментов плагина
    _instance = None
    _layers_db = None
    _base_layers_path = None

    def __new__(cls) -> 'LayerCleanupManager':
        """Singleton pattern для использования одного экземпляра"""
        if cls._instance is None:
            cls._instance = super(LayerCleanupManager, cls).__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Инициализация менеджера"""
        # Загружаем БД только один раз при первой инициализации
        if LayerCleanupManager._base_layers_path is None:
            LayerCleanupManager._base_layers_path = self._get_base_layers_path()
            LayerCleanupManager._layers_db = self._load_layers_database()

    @property
    def base_layers_path(self) -> Optional[str]:
        """
        Путь к файлу Base_layers.json.

        Returns:
            Абсолютный путь к файлу базы слоев или None
        """
        return LayerCleanupManager._base_layers_path

    @property
    def layers_db(self) -> Optional[List[dict]]:
        """
        База данных слоев из Base_layers.json.

        Returns:
            Список словарей с информацией о слоях или None
        """
        return LayerCleanupManager._layers_db

    def _get_base_layers_path(self) -> Optional[str]:
        """Получение пути к Base_layers.json"""
        from Daman_QGIS.constants import DATA_REFERENCE_PATH
        return os.path.join(DATA_REFERENCE_PATH, 'Base_layers.json')

    def _load_layers_database(self) -> List[dict]:
        """Загрузка базы данных слоев из Base_layers.json

        Returns:
            List[dict]: Список словарей с информацией о слоях
        """
        if self.base_layers_path is None:
            raise ValueError("Путь к Base_layers.json не определён")

        if not os.path.exists(self.base_layers_path):
            raise ValueError(f"Base_layers.json не найден: {self.base_layers_path}")

        with open(self.base_layers_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _remove_layer(self, layer: QgsVectorLayer, log_detail: bool = False) -> None:
        """Удаление слоя из проекта

        Args:
            layer: Слой для удаления
            log_detail: Логировать детали удаления каждого слоя
        """
        project = QgsProject.instance()
        layer_name = layer.name()
        project.removeMapLayer(layer.id())

        if log_detail:
            log_info(f"M_10_LayerCleanupManager: Удален слой: {layer_name}")

    def cleanup_for_function(self, function_name: str) -> int:
        """Удаление всех слоев, которые создает указанная функция

        Args:
            function_name: Имя функции (например, "F_1_2_Загрузка Web карт", "F_2_2_Категории ЗУ")

        Returns:
            int: Количество удаленных слоев
        """
        if not self.layers_db:
            return 0

        # Находим все слои, которые создает эта функция
        layers_to_remove = []
        for layer_info in self.layers_db:
            if layer_info.get('creating_function') == function_name:
                full_name = layer_info.get('full_name')
                if full_name:
                    layers_to_remove.append(full_name)

        if not layers_to_remove:
            log_info(f"M_10_LayerCleanupManager: Функция '{function_name}' не создает слоев согласно Base_layers.json")
            return 0

        # Удаляем слои из проекта (только векторные, растровые WMS обновляются динамически)
        removed_count = 0
        project = QgsProject.instance()

        for layer in list(project.mapLayers().values()):
            if isinstance(layer, QgsVectorLayer) and layer.isValid() and layer.name() in layers_to_remove:
                self._remove_layer(layer, log_detail=False)
                removed_count += 1

        if removed_count > 0:
            log_info(f"M_10_LayerCleanupManager: Функция '{function_name}': удалено {removed_count} слоев перед выполнением")

        return removed_count

    def cleanup_layers_by_prefix(self, prefix: str) -> int:
        """Удаление слоев по префиксу имени

        Args:
            prefix: Префикс слоя (например, "L_1_2_", "L_2_2_")

        Returns:
            int: Количество удаленных слоев
        """
        removed_count = 0
        project = QgsProject.instance()

        for layer in list(project.mapLayers().values()):
            if isinstance(layer, QgsVectorLayer) and layer.name().startswith(prefix):
                self._remove_layer(layer, log_detail=False)
                removed_count += 1

        if removed_count > 0:
            log_info(f"M_10_LayerCleanupManager: Удалено {removed_count} слоев с префиксом '{prefix}'")

        return removed_count

    def cleanup_layer_by_name(self, layer_name: str) -> bool:
        """Удаление конкретного слоя по имени

        Args:
            layer_name: Точное имя слоя

        Returns:
            bool: True если слой был найден и удален
        """
        project = QgsProject.instance()

        for layer in list(project.mapLayers().values()):
            if layer.name() == layer_name:
                self._remove_layer(layer, log_detail=True)
                return True

        return False

    def get_function_layers(self, function_name: str) -> List[str]:
        """Получение списка слоев, которые создает функция

        Args:
            function_name: Имя функции

        Returns:
            List[str]: Список имен слоев (full_name)
        """
        if not self.layers_db:
            return []

        layers = []
        for layer_info in self.layers_db:
            if layer_info.get('creating_function') == function_name:
                full_name = layer_info.get('full_name')
                if full_name:
                    layers.append(full_name)

        return layers

    def cleanup_empty_layers(self, prefix: Optional[str] = None) -> int:
        """
        Удаление полностью пустых слоёв (без геометрий И без атрибутов).

        Слой удаляется ТОЛЬКО если:
        - Нет ни одного объекта (featureCount == 0)

        Слой НЕ удаляется если:
        - Есть хотя бы один объект (даже без геометрии, но с атрибутами)
        - Есть хотя бы одна геометрия (даже без атрибутов)

        Args:
            prefix: Опциональный префикс для фильтрации слоёв (например "L_3_1_").
                   Если None - проверяются все векторные слои проекта.

        Returns:
            int: Количество удалённых слоёв
        """
        removed_count = 0
        project = QgsProject.instance()
        removed_names = []

        for layer in list(project.mapLayers().values()):
            # Только векторные слои
            if not isinstance(layer, QgsVectorLayer):
                continue

            # Фильтр по префиксу если указан
            if prefix and not layer.name().startswith(prefix):
                continue

            # Проверяем: слой пустой если нет объектов вообще
            if layer.featureCount() == 0:
                removed_names.append(layer.name())
                self._remove_layer(layer, log_detail=False)
                removed_count += 1

        if removed_count > 0:
            if prefix:
                log_info(
                    f"M_10: Удалено {removed_count} пустых слоёв "
                    f"с префиксом '{prefix}': {', '.join(removed_names)}"
                )
            else:
                log_info(
                    f"M_10: Удалено {removed_count} пустых слоёв: "
                    f"{', '.join(removed_names)}"
                )

        return removed_count

    def is_layer_empty(self, layer: QgsVectorLayer) -> bool:
        """
        Проверка, является ли слой полностью пустым.

        Args:
            layer: Векторный слой для проверки

        Returns:
            True если слой не содержит ни одного объекта
        """
        if not isinstance(layer, QgsVectorLayer):
            return False

        return layer.featureCount() == 0
