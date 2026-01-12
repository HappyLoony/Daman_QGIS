# -*- coding: utf-8 -*-
"""
Менеджер стилей экспорта ведомостей в Excel.

Отвечает за:
- Получение стилей экспорта ведомостей для слоев
- Определение заголовков и структуры колонок
- Поддержку шаблонов с метаданными проекта
"""

from typing import List, Dict, Optional
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader


class ExcelListStyleManager(BaseReferenceLoader):
    """Менеджер стилей экспорта ведомостей в Excel"""

    FILE_NAME = 'Base_excel_list_styles.json'

    def get_excel_list_styles(self) -> List[Dict]:
        """
        Получить все стили экспорта ведомостей

        Returns:
            Список стилей экспорта, каждый содержит:
            - layer: название слоя или 'Other' для универсального стиля
            - title: заголовок ведомости (может содержать переменные {variable})
            - column_names: имена колонок или ссылка на базу данных
        """
        return self._load_json(self.FILE_NAME) or []

    def get_excel_list_style_for_layer(self, layer_name: str) -> Optional[Dict]:
        """
        Получить стиль экспорта ведомости для конкретного слоя

        Ищет стиль для указанного слоя. Если не найден, возвращает универсальный
        стиль 'Other' (если существует).

        Args:
            layer_name: Имя слоя (например 'L_3_1_1_Нарезка_ЗПР_ОКС')

        Returns:
            Словарь с настройками экспорта:
            {
                'layer': str,
                'title': str,
                'column_names': str
            }
            Или None если слой не найден и нет стиля 'Other'
        """
        styles = self.get_excel_list_styles()
        other_style = None

        # Ищем точное соответствие или стиль 'Other'
        for style in styles:
            # Проверяем оба возможных ключа: 'layer' и 'style_name'
            layer_pattern = style.get('layer') or style.get('style_name')
            if not layer_pattern:
                continue

            # Точное соответствие
            if layer_pattern == layer_name:
                # Нормализуем ключи для единообразия
                if 'style_name' in style and 'layer' not in style:
                    style['layer'] = style['style_name']
                return style

            # Запоминаем стиль 'Other' как запасной
            if layer_pattern == 'Other':
                other_style = style

        # Нормализуем ключи для стиля 'Other'
        if other_style:
            if 'style_name' in other_style and 'layer' not in other_style:
                other_style['layer'] = other_style['style_name']

        # Возвращаем стиль 'Other' если ничего не найдено
        return other_style
