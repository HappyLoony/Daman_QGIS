# -*- coding: utf-8 -*-
"""Менеджер справочных данных метаданных проекта"""

from typing import List, Dict, Optional, Tuple
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader


class ProjectMetadataManager(BaseReferenceLoader):
    """Менеджер для работы с метаданными проекта"""

    FILE_NAME = 'Project_Metadata.json'

    def get_project_metadata_structure(self) -> List[Dict]:
        """
        Получить структуру метаданных проекта

        Returns:
            Список полей метаданных
        """
        return self._load_json(self.FILE_NAME) or []

    def get_required_metadata_fields(self) -> List[Dict]:
        """
        Получить обязательные поля метаданных

        Returns:
            Список обязательных полей
        """
        metadata = self.get_project_metadata_structure()
        return [field for field in metadata if field.get('status_fields') == 'required_fields']

    def get_optional_metadata_fields(self) -> List[Dict]:
        """
        Получить необязательные поля метаданных

        Returns:
            Список необязательных полей
        """
        metadata = self.get_project_metadata_structure()
        return [field for field in metadata if field.get('status_fields') == 'optional_fields']

    def get_object_types(self) -> List[str]:
        """
        Получить список доступных типов объектов

        Returns:
            Список типов объектов (например ['Линейный', 'Площадной'])
        """
        metadata = self.get_project_metadata_structure()
        for field in metadata:
            if field.get('key') == '1_2_object_type' and field.get('values'):
                # Разбиваем строку values по слэшу
                return [v.strip() for v in field['values'].split('/')]
        # Fallback на значения по умолчанию
        return ['Площадной', 'Линейный']

    def validate_object_type(self, object_type: str) -> bool:
        """
        Проверить корректность типа объекта

        Args:
            object_type: Тип объекта для проверки

        Returns:
            True если тип корректен, False иначе
        """
        return object_type in self.get_object_types()

    def get_field_by_key(self, key: str) -> Optional[Dict]:
        """
        Получить схему поля по ключу

        Args:
            key: Ключ поля (например '1_6_stage')

        Returns:
            Схема поля или None если не найдено
        """
        metadata = self.get_project_metadata_structure()
        for field in metadata:
            if field.get('key') == key:
                return field
        return None

    def get_field_values(self, key: str) -> List[str]:
        """
        Получить список допустимых значений для enum поля

        Args:
            key: Ключ поля

        Returns:
            Список значений или пустой список
        """
        field = self.get_field_by_key(key)
        if not field or not field.get('values'):
            return []

        # Парсим строку values (формат: "Значение1/Значение2/Значение3")
        values_str = field['values']
        return [v.strip() for v in values_str.split('/')]

    def get_field_values_with_codes(self, key: str) -> List[Tuple[str, str]]:
        """
        Получить список значений с кодами для enum поля

        Args:
            key: Ключ поля

        Returns:
            Список кортежей (label, code)
        """
        values = self.get_field_values(key)
        result = []

        for value in values:
            # Генерируем код из значения (lowercase, транслит)
            code = self._generate_code_from_label(value)
            result.append((value, code))

        return result

    def _generate_code_from_label(self, label: str) -> str:
        """
        Генерация кода из русского названия

        Args:
            label: Русское название (например "Федеральный")

        Returns:
            Код (например "federal")
        """
        # Словарь транслитерации для распространенных значений
        transliteration = {
            'Федеральный': 'federal',
            'Региональный': 'regional',
            'Местный': 'local',
            'Линейный': 'linear',
            'Площадной': 'area',
            'ДПТ': 'dpt',
            'Мастер-план': 'masterplan',
            'Мастер-План': 'masterplan',
            'Первичная': 'initial',
            'Внесение изменений': 'changes',
            'Наша': 'ours',
            'Заказчика': 'customer',
            'ООО «КРТ Система»': 'krt',
            'ООО «БТИиК»': 'btiik',
            'Санкт-Петербург': 'spb',
            'Симферополь': 'simferopol',
            'Москва': 'moscow',
            'А.В. Сердюков': 'serdyukov',
            'Р.С. Левицкий': 'levitsky',
            '500': '500',
            '1000': '1000',
            '2000': '2000',
            '1:500': '500',
            '1:1000': '1000',
            '1:2000': '2000',
        }

        # Проверяем есть ли в словаре
        if label in transliteration:
            return transliteration[label]

        # Иначе делаем lowercase и заменяем пробелы на underscores
        return label.lower().replace(' ', '_').replace('-', '_')

    def get_field_name(self, key: str) -> str:
        """
        Получить название поля по ключу

        Args:
            key: Ключ поля

        Returns:
            Название поля или ключ если не найдено
        """
        field = self.get_field_by_key(key)
        return field.get('name', key) if field else key

    def get_field_type(self, key: str) -> Optional[str]:
        """
        Получить тип поля

        Args:
            key: Ключ поля

        Returns:
            Тип поля ('string', 'enum', 'crs') или None
        """
        field = self.get_field_by_key(key)
        return field.get('type') if field else None

    def is_field_enum(self, key: str) -> bool:
        """
        Проверка является ли поле enum

        Args:
            key: Ключ поля

        Returns:
            True если поле типа enum
        """
        return self.get_field_type(key) == 'enum'
