# -*- coding: utf-8 -*-
"""Менеджер справочных данных типов работ"""

from typing import List, Dict, Optional
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader


class WorkTypeReferenceManager(BaseReferenceLoader):
    """Менеджер для работы с типами работ"""

    WORK_TYPES_FILE = 'Work_types.json'

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
