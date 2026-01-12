# -*- coding: utf-8 -*-
"""
Менеджер структуры полей слоев.

Отвечает за:
- Структуру полей слоя выборки земельных участков
- Структуру полей слоев нарезки
- Описание форматов полей MapInfo
"""

from typing import List, Dict, Optional
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader


class LayerFieldStructureManager(BaseReferenceLoader):
    """Менеджер структуры полей специальных слоев"""

    FILE_NAME_SELECTION_ZU = 'Base_selection_ZU.json'
    FILE_NAME_CUTTING = 'Base_cutting.json'

    def get_selection_zu_fields(self) -> List[Dict]:
        """
        Получить структуру полей для слоя выборки земельных участков

        Returns:
            Список полей с описанием структуры:
            {
                'working_name': str,      # Рабочее название поля (например 'КН', 'ЕЗ')
                'full_name': str,         # Полное название поля
                'mapinfo_format': str     # Формат поля в MapInfo (например 'Char(50)')
            }
        """
        return self._load_json(self.FILE_NAME_SELECTION_ZU) or []

    def get_selection_zu_field_by_name(self, field_name: str) -> Optional[Dict]:
        """
        Получить описание поля выборки ЗУ по рабочему названию

        Args:
            field_name: Рабочее название поля (например 'КН', 'ЕЗ')

        Returns:
            Словарь с информацией о поле:
            {
                'working_name': str,
                'full_name': str,
                'mapinfo_format': str
            }
            Или None если поле не найдено

        Example:
            >>> field = get_selection_zu_field_by_name('КН')
            >>> field['full_name']
            'Кадастровый номер'
        """
        fields = self.get_selection_zu_fields()
        for field in fields:
            if field.get('working_name') == field_name:
                return field
        return None

    def get_cutting_fields(self) -> List[Dict]:
        """
        Получить структуру полей для слоев нарезки

        Returns:
            Список полей с описанием структуры:
            {
                'working_name': str,      # Рабочее название поля (например 'ID', 'Услов_КН')
                'full_name': str,         # Полное название поля
                'mapinfo_format': str,    # Формат поля в MapInfo (например 'Integer')
                'data_source': str        # Источник данных для поля (опционально)
            }
        """
        return self._load_json(self.FILE_NAME_CUTTING) or []

    def get_cutting_field_by_name(self, field_name: str) -> Optional[Dict]:
        """
        Получить описание поля нарезки по рабочему названию

        Args:
            field_name: Рабочее название поля (например 'ID', 'Услов_КН')

        Returns:
            Словарь с информацией о поле:
            {
                'working_name': str,
                'full_name': str,
                'mapinfo_format': str,
                'data_source': str (опционально)
            }
            Или None если поле не найдено

        Example:
            >>> field = get_cutting_field_by_name('Услов_КН')
            >>> field['full_name']
            'Условный кадастровый номер'
        """
        fields = self.get_cutting_fields()
        for field in fields:
            if field.get('working_name') == field_name:
                return field
        return None
