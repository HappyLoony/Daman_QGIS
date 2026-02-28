# -*- coding: utf-8 -*-
"""
Менеджер справочных данных подложек (Base_drawings_background.json).

Отвечает за:
- Получение списка подложек
- Валидацию структуры подложек
"""

from typing import List, Dict, Optional
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader


class BackgroundReferenceManager(BaseReferenceLoader):
    """Менеджер справочных данных подложек"""

    FILE_NAME = 'Base_drawings_background.json'

    def get_backgrounds(self) -> List[Dict]:
        """
        Получить список всех подложек

        Returns:
            Список подложек с информацией:
            {
                'name': str,               # Имя файла подложки
                'layers': List[str] | None # Список слоёв для подложки
            }
        """
        return self._load_json(self.FILE_NAME) or []

    def get_background_by_name(self, name: str) -> Optional[Dict]:
        """
        Получить подложку по имени

        Args:
            name: Имя подложки

        Returns:
            Данные подложки или None
        """
        backgrounds = self.get_backgrounds()
        for bg in backgrounds:
            if bg.get('name') == name:
                return bg
        return None

    def get_valid_backgrounds(self) -> List[Dict]:
        """
        Получить только валидные подложки (с непустым списком слоёв)

        Returns:
            Список подложек, которые содержат слои для экспорта
        """
        backgrounds = self.get_backgrounds()
        return [
            bg for bg in backgrounds
            if (layers := bg.get('layers')) and isinstance(layers, list) and len(layers) > 0
        ]

    def get_export_filename(self, background: Dict) -> Optional[str]:
        """
        Получить имя файла для экспорта подложки

        Args:
            background: Данные подложки

        Returns:
            Имя файла (без расширения .dxf) или None
        """
        name = background.get('name')
        if name and name != '-':
            return name
        return None

    def validate_background(self, background: Dict) -> tuple[bool, str]:
        """
        Валидация структуры подложки

        Args:
            background: Данные подложки

        Returns:
            (valid, error_message): True если валидно, False + сообщение об ошибке
        """
        # Проверка обязательных полей
        if 'name' not in background:
            return False, "Отсутствует поле 'name'"

        if 'layers' not in background:
            return False, "Отсутствует поле 'layers'"

        # Проверка непустого имени
        name = background.get('name')
        if not name or name == '-':
            return False, "Поле 'name' пустое или равно '-'"

        # Проверка слоёв (должен быть либо список, либо null)
        layers = background.get('layers')
        if layers is not None and not isinstance(layers, list):
            return False, "Поле 'layers' должно быть списком или null"

        return True, ""
