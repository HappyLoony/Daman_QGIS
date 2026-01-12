# -*- coding: utf-8 -*-
"""Менеджер справочных данных слоев"""

import os
import json
from typing import List, Dict, Optional
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
from Daman_QGIS.utils import log_warning, log_error


class LayerReferenceManager(BaseReferenceLoader):
    """Менеджер для работы с иерархической структурой слоев"""

    FILE_NAME = 'Base_layers.json'

    def get_base_layers(self) -> List[Dict]:
        """
        Получить иерархическую структуру слоев БЕЗ кэширования

        ВАЖНО: Данные всегда загружаются с диска для получения актуальных стилей.
        Любые изменения в Base_layers.json применяются немедленно.

        Returns:
            Список слоев с их параметрами
        """
        filepath = os.path.join(self.reference_dir, self.FILE_NAME)

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            log_warning(f"Msm_4_6: Файл Base_layers.json не найден: {filepath}")
            return []
        except json.JSONDecodeError as e:
            log_error(f"Msm_4_6: Ошибка чтения Base_layers.json: {filepath} - {str(e)}")
            return []

    def get_layer_params(self) -> Dict:
        """
        Получить параметры слоев в виде словаря БЕЗ кэширования

        ВАЖНО: Всегда возвращает актуальные данные из Base_layers.json

        Returns:
            Словарь {full_name: layer_data}
        """
        layers = self.get_base_layers()
        # Преобразуем список слоев в словарь с ключом full_name
        result = {}
        for layer in layers:
            if layer.get('full_name'):
                result[layer['full_name']] = layer
        return result

    def get_layer_param(self, layer_id: str) -> Optional[Dict]:
        """
        Получить параметры конкретного слоя по full_name

        Args:
            layer_id: Полное имя слоя

        Returns:
            Словарь с параметрами слоя или None
        """
        layers = self.get_layer_params()
        return layers.get(layer_id)

    def get_layer_by_full_name(self, full_name: str) -> Optional[Dict]:
        """
        Получить слой по полному рабочему названию

        ВАЖНО: Используется ТОЛЬКО точное совпадение имени!
        Копии слоев (например "3_3_1_ГПМТ_копия") НЕ будут найдены при поиске "3_3_1_ГПМТ".
        Каждый слой строго привязан к своему точному названию.

        Args:
            full_name: Полное имя слоя

        Returns:
            Словарь с данными слоя или None
        """
        layers = self.get_base_layers()
        for layer in layers:
            # ТОЛЬКО точное совпадение! Не использовать startswith() или in
            if layer.get('full_name') == full_name:
                return layer
        return None

    def get_layers_by_section(self, section_num: str) -> List[Dict]:
        """
        Получить слои по номеру раздела

        Args:
            section_num: Номер раздела

        Returns:
            Список слоев раздела
        """
        layers = self.get_base_layers()
        return [layer for layer in layers if layer.get('section_num') == str(section_num)]

    def get_layer_groups(self) -> List[str]:
        """
        Получить список групп слоев

        Returns:
            Отсортированный список уникальных групп
        """
        layers = self.get_base_layers()
        groups = set()
        for layer_data in layers:
            if 'group' in layer_data and layer_data['group']:
                groups.add(layer_data['group'])
        return sorted(list(groups))

    def get_layers_by_creating_function(self, function_name: str) -> List[Dict]:
        """
        Получить слои, созданные определённой функцией

        Используется для определения слоёв, которые не должны менять CRS
        (например, слои F_1_2 хранятся в EPSG:3857)

        Args:
            function_name: Имя функции (например "F_1_2_Загрузка Web карт")

        Returns:
            Список слоёв с указанной creating_function
        """
        layers = self.get_base_layers()
        return [
            layer for layer in layers
            if layer.get('creating_function') == function_name
        ]

    def get_layer_names_by_creating_function(self, function_name: str) -> List[str]:
        """
        Получить имена слоёв (full_name), созданных определённой функцией

        Args:
            function_name: Имя функции (например "F_1_2_Загрузка Web карт")

        Returns:
            Список full_name слоёв
        """
        layers = self.get_layers_by_creating_function(function_name)
        return [name for layer in layers if (name := layer.get('full_name'))]
