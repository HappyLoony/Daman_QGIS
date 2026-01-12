# -*- coding: utf-8 -*-
"""
Msm_13_4: Data Validator - Валидация данных

Валидация метаданных и атрибутивных данных:
- Проверка обязательных полей
- Проверка типов данных
- Проверка допустимых значений (enum)
- Проверка зависимостей между полями
"""

from typing import Dict, List, Tuple, Any, Optional
from Daman_QGIS.utils import log_warning, log_info


class DataValidator:
    """
    Валидатор метаданных и данных проекта

    Выполняет валидацию метаданных на основе структуры из Project_Metadata.json:
    - Проверка обязательных полей
    - Проверка типов данных
    - Проверка допустимых значений (enum)
    - Проверка зависимостей между полями

    Примеры использования:
        >>> validator = DataValidator(metadata_manager)
        >>> valid, errors = validator.validate_all(metadata)
        >>> if not valid:
        ...     for error in errors:
        ...         print(error)
    """

    def __init__(self, metadata_manager=None):
        """
        Инициализация валидатора

        Args:
            metadata_manager: ProjectMetadataManager для доступа к структуре
        """
        self.metadata_manager = metadata_manager
        self.metadata_structure = None
        self.fields_by_key = {}

        if metadata_manager:
            self.metadata_structure = metadata_manager.get_project_metadata_structure()
            # Индексируем поля по ключам для быстрого доступа
            self.fields_by_key = {
                field['key']: field for field in self.metadata_structure
            }

    def validate_all(self, metadata: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Полная валидация всех метаданных

        Args:
            metadata: Словарь метаданных для проверки

        Returns:
            Tuple[bool, List[str]]: (valid, list_of_errors)
                - valid: True если все проверки прошли
                - list_of_errors: Список сообщений об ошибках
        """
        if not self.metadata_manager:
            log_warning("Msm_13_4_DataValidator: metadata_manager не установлен, валидация пропущена")
            return True, []

        errors = []

        # 1. Проверка обязательных полей
        required_errors = self.validate_required_fields(metadata)
        errors.extend(required_errors)

        # 2. Проверка типов и значений для заполненных полей
        for key, value in metadata.items():
            # Пропускаем пустые значения и служебные поля
            if not value or key.startswith('_') or key.endswith('_name'):
                continue

            # Проверка существования поля в схеме
            if key not in self.fields_by_key:
                continue  # Служебные поля (crs, project_path и т.д.)

            field_schema = self.fields_by_key[key]

            # Проверка типа
            type_valid, type_error = self.validate_type(key, value, field_schema)
            if not type_valid:
                errors.append(type_error)

            # Проверка enum значений
            if field_schema.get('type') == 'enum':
                enum_valid, enum_error = self.validate_enum(key, value, field_schema)
                if not enum_valid:
                    errors.append(enum_error)

        # 3. Проверка зависимостей между полями
        dependency_errors = self.validate_dependencies(metadata)
        errors.extend(dependency_errors)

        is_valid = len(errors) == 0

        if is_valid:
            log_info("Msm_13_4_DataValidator: Валидация метаданных прошла успешно")
        else:
            log_warning(f"Msm_13_4_DataValidator: Найдено {len(errors)} ошибок валидации метаданных")

        return is_valid, errors

    def validate_required_fields(self, metadata: Dict[str, Any]) -> List[str]:
        """
        Проверка наличия всех обязательных полей

        Args:
            metadata: Словарь метаданных

        Returns:
            List[str]: Список ошибок (пустой если все ОК)
        """
        if not self.metadata_manager:
            return []

        errors = []
        required_fields = self.metadata_manager.get_required_metadata_fields()

        for field in required_fields:
            key = field['key']
            name = field['name']

            # Особая логика для условно-обязательных полей
            # Проверяем специфичные ключи условных полей
            if key == '1_2_1_object_type_value':
                # Это условное поле (значение линейного объекта)
                # Проверяем только если родительское поле активно
                if not self._is_conditional_field_required(key, metadata):
                    continue

            # Проверяем наличие и непустоту значения
            value = metadata.get(key)
            # Считаем поле незаполненным если:
            # - Значение None (отсутствует)
            # - Пустая строка для строковых полей
            is_empty = value is None or (isinstance(value, str) and not value.strip())

            if is_empty:
                errors.append(f"Обязательное поле '{name}' ({key}) не заполнено")

        return errors

    def validate_type(self, key: str, value: Any, field_schema: Dict) -> Tuple[bool, str]:
        """
        Проверка типа данных поля

        Args:
            key: Ключ поля
            value: Значение для проверки
            field_schema: Схема поля из Project_Metadata.json

        Returns:
            Tuple[bool, str]: (valid, error_message)
        """
        field_type = field_schema.get('type')
        field_name = field_schema.get('name', key)

        if not field_type:
            return True, ""  # Нет требований к типу

        # Проверка для string
        if field_type == 'string':
            if not isinstance(value, str):
                return False, f"Поле '{field_name}' должно быть строкой"

        # Проверка для enum
        elif field_type == 'enum':
            if not isinstance(value, str):
                return False, f"Поле '{field_name}' должно быть строкой (enum)"

        # Проверка для crs (система координат)
        elif field_type == 'crs':
            # CRS передается как объект, проверяем его валидность
            if hasattr(value, 'isValid'):
                if not value.isValid():
                    return False, f"Система координат '{field_name}' невалидна"
            elif not value:
                return False, f"Система координат '{field_name}' не задана"

        return True, ""

    def validate_enum(self, key: str, value: str, field_schema: Dict) -> Tuple[bool, str]:
        """
        Проверка что значение соответствует допустимым значениям enum

        Args:
            key: Ключ поля
            value: Значение для проверки
            field_schema: Схема поля

        Returns:
            Tuple[bool, str]: (valid, error_message)
        """
        field_name = field_schema.get('name', key)
        values_str = field_schema.get('values')

        if not values_str:
            return True, ""  # Нет ограничений

        # Парсим допустимые значения (формат: "Значение1/Значение2/Значение3")
        allowed_values = [v.strip() for v in values_str.split('/')]

        # Проверяем что значение в списке допустимых
        if value not in allowed_values:
            return False, f"Недопустимое значение для '{field_name}': '{value}'. Допустимые: {', '.join(allowed_values)}"

        return True, ""

    def validate_dependencies(self, metadata: Dict[str, Any]) -> List[str]:
        """
        Проверка зависимостей между полями

        Например: 1_2_1_object_type_value должно быть заполнено только для линейных объектов

        Args:
            metadata: Словарь метаданных

        Returns:
            List[str]: Список ошибок
        """
        errors = []

        # Проверка: значение линейного объекта только для линейных объектов
        # Используем полные ключи и отображаемые значения (Линейный, Площадной)
        object_type = metadata.get('1_2_object_type', '')
        object_type_value = metadata.get('1_2_1_object_type_value')

        # Проверяем по отображаемому значению
        is_linear = 'Линейный' in str(object_type)

        if object_type_value and not is_linear:
            errors.append(
                "Поле 'Значение линейного объекта' может быть заполнено только для линейных объектов"
            )

        if is_linear and not object_type_value:
            errors.append(
                "Для линейных объектов обязательно укажите 'Значение линейного объекта'"
            )

        return errors

    def validate_attribute_value(self, value: Any, field_schema: Dict) -> Tuple[bool, str]:
        """
        Валидация значения атрибута по схеме

        Args:
            value: Значение для проверки
            field_schema: Схема поля

        Returns:
            Tuple[bool, str]: (valid, error_message)
        """
        if not field_schema:
            return True, ""

        # Базовая валидация типа
        field_type = field_schema.get('type')
        if field_type == 'string' and value is not None:
            if not isinstance(value, str):
                return False, "Значение должно быть строкой"

        # Валидация enum
        if field_type == 'enum' and value:
            values_str = field_schema.get('values', '')
            allowed = [v.strip() for v in values_str.split('/')]
            if value not in allowed:
                return False, f"Недопустимое значение. Допустимые: {', '.join(allowed)}"

        return True, ""

    def _is_conditional_field_required(self, key: str, metadata: Dict[str, Any]) -> bool:
        """
        Проверка требуется ли условно-обязательное поле в текущем контексте

        Args:
            key: Ключ условного поля (например '1_2_1_object_type_value')
            metadata: Словарь метаданных с контекстом

        Returns:
            bool: True если поле требуется в текущем контексте
        """
        # Логика для 1_2_1_object_type_value (значение линейного объекта)
        if key == '1_2_1_object_type_value':
            # Используем полный ключ и отображаемое значение
            object_type = metadata.get('1_2_object_type', '')
            is_linear = 'Линейный' in str(object_type)
            # Требуется только для линейных объектов
            return is_linear

        # Для других условных полей можно добавить логику здесь

        return True  # По умолчанию требуется

    def validate_field(self, key: str, value: Any, metadata: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Валидация одного поля с учетом контекста

        Args:
            key: Ключ поля
            value: Значение
            metadata: Полный контекст метаданных (для проверки зависимостей)

        Returns:
            Tuple[bool, str]: (valid, error_message)
        """
        # Получаем схему поля
        if key not in self.fields_by_key:
            # Служебное поле или поле _name
            return True, ""

        field_schema = self.fields_by_key[key]
        field_name = field_schema.get('name', key)

        # 1. Проверка обязательности
        if field_schema.get('status_fields') == 'required_fields':
            if not value:
                # Проверяем условную обязательность для конкретных полей
                if key == '1_2_1_object_type_value':
                    if self._is_conditional_field_required(key, metadata):
                        return False, f"Обязательное поле '{field_name}' не заполнено"
                else:
                    return False, f"Обязательное поле '{field_name}' не заполнено"

        # 2. Проверка типа (если значение заполнено)
        if value:
            type_valid, type_error = self.validate_type(key, value, field_schema)
            if not type_valid:
                return False, type_error

            # 3. Проверка enum
            if field_schema.get('type') == 'enum':
                enum_valid, enum_error = self.validate_enum(key, value, field_schema)
                if not enum_valid:
                    return False, enum_error

        return True, ""

    def get_field_info(self, key: str) -> Optional[Dict]:
        """
        Получение информации о поле из схемы

        Args:
            key: Ключ поля

        Returns:
            Dict или None: Схема поля
        """
        return self.fields_by_key.get(key)

    def is_field_required(self, key: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Проверка обязательности поля с учетом контекста

        Args:
            key: Ключ поля
            metadata: Контекст метаданных (для условных полей)

        Returns:
            bool: True если поле обязательно
        """
        if key not in self.fields_by_key:
            return False

        field_schema = self.fields_by_key[key]

        if field_schema.get('status_fields') != 'required_fields':
            return False

        # Проверка условной обязательности для конкретных полей
        if metadata and key == '1_2_1_object_type_value':
            return self._is_conditional_field_required(key, metadata)

        return True
