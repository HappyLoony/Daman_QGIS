# -*- coding: utf-8 -*-
"""
Менеджер простых справочных данных.

Объединяет загрузку справочников с минимальной логикой:
- Типы работ (Work_types.json)
- Чертежи проекта (Base_drawings.json)

Каждый справочник использует паттерн: загрузка + фильтрация по полю.
"""

from typing import List, Dict, Optional
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader


class SimpleReferenceManager(BaseReferenceLoader):
    """
    Менеджер для простых справочных данных

    Объединяет функциональность:
    - WorkTypeReferenceManager (типы работ)
    - DrawingsReferenceManager (чертежи проекта)
    """

    WORK_TYPES_FILE = 'Work_types.json'
    DRAWINGS_FILE = 'Base_drawings.json'

    # =========================================================================
    # Типы работ (Work_types.json)
    # =========================================================================

    def get_work_types(self) -> List[Dict]:
        """
        Получить список типов работ

        Returns:
            Список типов работ
        """
        return self._load_json(self.WORK_TYPES_FILE) or []

    def get_work_type_by_code(self, code: str) -> Optional[Dict]:
        """
        Получить тип работы по коду

        Args:
            code: Код типа работы

        Returns:
            Словарь с данными типа работы или None
        """
        return self._get_by_key(
            data_getter=self.get_work_types,
            index_key='work_type_by_code',
            field_name='code',
            value=code
        )

    # =========================================================================
    # Чертежи проекта (Base_drawings.json)
    # =========================================================================

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
        return self._load_json(self.DRAWINGS_FILE) or []

    def get_drawings_by_volume(self, volume_number: str) -> List[Dict]:
        """
        Получить чертежи по номеру тома

        Args:
            volume_number: Номер тома (например '1', '2', '3.1')

        Returns:
            Список чертежей указанного тома

        Example:
            >>> drawings = manager.get_drawings_by_volume('1')
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
            >>> drawings = manager.get_drawings_by_department('ИИ')
            >>> for drawing in drawings:
            ...     print(f"Том {drawing['volume_number']}: {drawing['section_title']}")
        """
        drawings = self.get_drawings()
        return [drw for drw in drawings if drw.get('department') == department]


# Алиасы для обратной совместимости (если кто-то импортирует напрямую)
WorkTypeReferenceManager = SimpleReferenceManager
DrawingsReferenceManager = SimpleReferenceManager
