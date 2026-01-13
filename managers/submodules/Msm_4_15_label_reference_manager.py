# -*- coding: utf-8 -*-
"""Менеджер справочных данных подписей слоёв"""

import os
import json
from typing import List, Dict, Optional
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
from Daman_QGIS.utils import log_warning, log_error


class LabelReferenceManager(BaseReferenceLoader):
    """Менеджер для работы с настройками подписей слоёв"""

    FILE_NAME = 'Base_labels.json'

    def get_all_labels(self) -> List[Dict]:
        """
        Получить все настройки подписей

        Использует BaseReferenceLoader._load_json() для remote/local загрузки.
        Данные кэшируются в памяти после первой загрузки.

        Returns:
            Список настроек подписей для слоёв
        """
        return self._load_json(self.FILE_NAME) or []

    def get_label_config(self, full_name: str) -> Optional[Dict]:
        """
        Получить настройки подписей для конкретного слоя по full_name

        ВАЖНО: Используется ТОЛЬКО точное совпадение имени!
        Если слоя нет в Base_labels.json, возвращается None (подписи отключены).

        Args:
            full_name: Полное имя слоя (например "L_1_2_1_WFS_ЗУ")

        Returns:
            Словарь с настройками подписей или None если подписи не настроены

        Example:
            >>> manager = LabelReferenceManager(reference_dir)
            >>> config = manager.get_label_config("L_1_2_1_WFS_ЗУ")
            >>> if config:
            >>>     print(f"Поле подписи: {config['label_field']}")
            >>>     print(f"Приоритет: {config['label_priority']}")
        """
        labels = self.get_all_labels()
        for label_config in labels:
            # ТОЛЬКО точное совпадение! Не использовать startswith() или in
            if label_config.get('full_name') == full_name:
                return label_config
        return None

    def has_labels_enabled(self, full_name: str) -> bool:
        """
        Проверить включены ли подписи для слоя

        Args:
            full_name: Полное имя слоя

        Returns:
            True если слой найден в Base_labels.json и имеет label_field

        Example:
            >>> if manager.has_labels_enabled("L_1_2_1_WFS_ЗУ"):
            >>>     print("Подписи включены")
        """
        config = self.get_label_config(full_name)
        if not config:
            return False
        # Подписи включены если есть поле для подписи
        return bool(config.get('label_field'))

    def get_label_field(self, full_name: str) -> Optional[str]:
        """
        Получить имя поля для подписи слоя

        Args:
            full_name: Полное имя слоя

        Returns:
            Имя поля (например "cad_num") или None если подписи не настроены

        Example:
            >>> field = manager.get_label_field("L_1_2_1_WFS_ЗУ")
            >>> if field:
            >>>     print(f"Подписывать поле: {field}")
        """
        config = self.get_label_config(full_name)
        if config:
            return config.get('label_field')
        return None

    def get_label_priority(self, full_name: str, default: int = 5) -> int:
        """
        Получить приоритет подписей слоя

        Args:
            full_name: Полное имя слоя
            default: Значение по умолчанию если не указано

        Returns:
            Приоритет (0-10, где 10=максимальный)

        Example:
            >>> priority = manager.get_label_priority("Le_1_2_3_5_АТД_НП_poly")
            >>> print(f"Приоритет: {priority}")  # 10
        """
        config = self.get_label_config(full_name)
        if config and 'label_priority' in config:
            return config['label_priority']
        return default

    def get_layers_with_labels(self) -> List[str]:
        """
        Получить список full_name всех слоёв с настроенными подписями

        Returns:
            Список имён слоёв у которых есть label_field

        Example:
            >>> layers = manager.get_layers_with_labels()
            >>> print(f"Подписи настроены для {len(layers)} слоёв")
        """
        labels = self.get_all_labels()
        result = []
        for label_config in labels:
            full_name = label_config.get('full_name')
            label_field = label_config.get('label_field')
            if full_name and label_field:
                result.append(full_name)
        return result

    def get_default_config(self) -> Dict:
        """
        Получить конфигурацию подписей по умолчанию

        Returns:
            Словарь со стандартными значениями (GOST 2.304, 4мм, черный, буфер 1мм)

        Example:
            >>> defaults = manager.get_default_config()
            >>> print(f"Шрифт по умолчанию: {defaults['label_font_family']}")
        """
        return {
            'label_font_family': 'GOST 2.304',
            'label_font_style': 'Bold Italic',
            'label_font_size': 4.0,
            'label_font_color_RGB': '0,0,0',
            'label_buffer_enabled': True,
            'label_buffer_color_RGB': '255,255,255',
            'label_buffer_size': 1.0,
            'label_priority': 5,
            'label_z_index': 0.0,
            'label_is_obstacle': False,
            'label_auto_wrap_enabled': True,
            'label_auto_wrap_length': 50,
            'label_position_auto': False
        }
