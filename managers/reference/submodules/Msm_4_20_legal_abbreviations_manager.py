# -*- coding: utf-8 -*-
"""
Msm_4_20: Менеджер сокращений организационно-правовых форм юридических лиц

Отвечает за:
- Загрузку базы сокращений из Base_legal_abbreviations.json
- Замену полных наименований на сокращения
- Сортировку по длине для корректной замены

Примеры замен:
    "Общество с ограниченной ответственностью" → "ООО"
    "Публичное акционерное общество" → "ПАО"
    "Акционерное общество" → "АО"
"""

import re
from typing import List, Dict, Optional, Tuple
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
from Daman_QGIS.utils import log_info, log_debug


class LegalAbbreviationsManager(BaseReferenceLoader):
    """Менеджер сокращений организационно-правовых форм"""

    FILE_NAME = 'Base_legal_abbreviations.json'

    def __init__(self):
        """Инициализация менеджера."""
        super().__init__()
        self._sorted_abbreviations: Optional[List[Tuple[str, str]]] = None

    def get_abbreviations(self) -> List[Dict]:
        """
        Получить список всех сокращений

        Returns:
            Список сокращений:
            [
                {
                    'full_form': str,      # Полная форма
                    'abbreviation': str    # Сокращение
                }
            ]
        """
        return self._load_json(self.FILE_NAME) or []

    def get_sorted_abbreviations(self) -> List[Tuple[str, str]]:
        """
        Получить список сокращений, отсортированный по длине full_form (DESC)

        Важно: более длинные формы должны заменяться первыми,
        чтобы "Публичное акционерное общество" заменилось раньше "Акционерное общество"

        Returns:
            Список кортежей (full_form, abbreviation),
            отсортированный по убыванию длины full_form
        """
        if self._sorted_abbreviations is not None:
            return self._sorted_abbreviations

        abbreviations = self.get_abbreviations()

        # Преобразуем в кортежи и сортируем по длине DESC
        sorted_list = [
            (
                item.get('full_form', ''),
                item.get('abbreviation', '')
            )
            for item in abbreviations
            if item.get('full_form') and item.get('abbreviation')
        ]

        # Сортировка по длине full_form (убывание)
        sorted_list.sort(key=lambda x: len(x[0]), reverse=True)

        self._sorted_abbreviations = sorted_list
        return sorted_list

    def abbreviate(self, text: str) -> str:
        """
        Заменить полные наименования организационно-правовых форм на сокращения

        Замена всегда выполняется без учёта регистра (case-insensitive).

        Args:
            text: Исходный текст

        Returns:
            Текст с замененными сокращениями

        Examples:
            >>> abbreviate('Общество с ограниченной ответственностью "Рога и копыта"')
            'ООО "Рога и копыта"'

            >>> abbreviate('Публичное акционерное общество "Сбербанк"')
            'ПАО "Сбербанк"'
        """
        if not text or not isinstance(text, str):
            return text

        result = text
        abbreviations = self.get_sorted_abbreviations()

        for full_form, abbreviation in abbreviations:
            if not full_form:
                continue

            # Замена без учета регистра (IGNORECASE)
            pattern = re.escape(full_form)
            result = re.sub(pattern, abbreviation, result, flags=re.IGNORECASE)

        return result

    def abbreviate_value(self, value: str) -> str:
        """
        Сокращение значения атрибута (с обработкой множественных значений)

        Обрабатывает значения с разделителем " / " (множественные собственники/арендаторы)

        Args:
            value: Значение атрибута (может содержать " / ")

        Returns:
            Значение с сокращенными наименованиями
        """
        if not value or not isinstance(value, str):
            return value

        # Разделяем по " / " для обработки множественных значений
        parts = value.split(' / ')
        abbreviated_parts = [self.abbreviate(part.strip()) for part in parts]

        return ' / '.join(abbreviated_parts)

    def get_abbreviation_for(self, full_form: str) -> Optional[str]:
        """
        Получить сокращение для конкретной полной формы

        Поиск выполняется без учёта регистра (case-insensitive).

        Args:
            full_form: Полная форма организационно-правовой формы

        Returns:
            Сокращение или None если не найдено
        """
        abbreviations = self.get_abbreviations()
        full_form_lower = full_form.lower()

        for item in abbreviations:
            item_full = item.get('full_form', '')
            if item_full.lower() == full_form_lower:
                return item.get('abbreviation')

        return None

    def clear_cache(self):
        """Очистить кэш (включая отсортированный список)"""
        super().clear_cache()
        self._sorted_abbreviations = None

    def reload(self, filename: Optional[str] = None):
        """Перезагрузить данные"""
        super().reload(filename)
        self._sorted_abbreviations = None
