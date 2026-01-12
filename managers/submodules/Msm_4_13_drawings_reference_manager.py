# -*- coding: utf-8 -*-
"""
Менеджер справочных данных чертежей проекта.

Отвечает за:
- Получение информации о чертежах
- Фильтрацию по номеру тома
- Фильтрацию по отделу
"""

from typing import List, Dict
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader


class DrawingsReferenceManager(BaseReferenceLoader):
    """Менеджер справочных данных чертежей проекта"""

    FILE_NAME = 'Base_drawings.json'

    def get_drawings(self) -> List[Dict]:
        """
        Получить список всех чертежей проекта

        Returns:
            Список чертежей с информацией:
            {
                'volume_number': str,      # Номер тома
                'department': str,         # Отдел
                'section_title': str,      # Заголовок раздела
                'section': str             # Раздел
            }
        """
        return self._load_json(self.FILE_NAME) or []

    def get_drawings_by_volume(self, volume_number: str) -> List[Dict]:
        """
        Получить чертежи по номеру тома

        Args:
            volume_number: Номер тома (например '1', '2', '3.1')

        Returns:
            Список чертежей указанного тома

        Example:
            >>> drawings = get_drawings_by_volume('1')
            >>> for drawing in drawings:
            ...     print(drawing['section_title'])
        """
        drawings = self.get_drawings()
        return [drw for drw in drawings if str(drw.get('volume_number')) == str(volume_number)]

    def get_drawings_by_department(self, department: str) -> List[Dict]:
        """
        Получить чертежи по отделу

        Args:
            department: Название отдела (например 'ИИ', 'АР', 'КР')

        Returns:
            Список чертежей указанного отдела

        Example:
            >>> drawings = get_drawings_by_department('ИИ')
            >>> for drawing in drawings:
            ...     print(f"Том {drawing['volume_number']}: {drawing['section_title']}")
        """
        drawings = self.get_drawings()
        return [drw for drw in drawings if drw.get('department') == department]
