# -*- coding: utf-8 -*-
"""
M_13: Data Cleanup Manager - Менеджер очистки и санитизации данных

Единая точка входа для всех операций очистки, санитизации и валидации данных.

Компоненты:
- Msm_13_1: StringSanitizer - Очистка строк
- Msm_13_2: AttributeProcessor - Обработка атрибутов
- Msm_13_3: FieldCleanup - Очистка полей
- Msm_13_4: DataValidator - Валидация данных
- Msm_13_5: AttributeMapper - Маппинг атрибутов

Примеры использования:
    >>> from Daman_QGIS.managers import DataCleanupManager
    >>> manager = DataCleanupManager()
    >>>
    >>> # Очистка имени файла
    >>> clean_name = manager.sanitize_filename("Файл:Данные")
    >>>
    >>> # Финальная обработка слоя
    >>> manager.finalize_layer(layer, layer_name)
    >>>
    >>> # Удаление пустых полей
    >>> stats = manager.remove_empty_fields(layer)
"""

from typing import List, Dict, Optional, Tuple, Any
from qgis.core import QgsVectorLayer, QgsFeature
from Daman_QGIS.utils import log_info
from .submodules.Msm_13_1_string_sanitizer import StringSanitizer
from .submodules.Msm_13_2_attribute_processor import AttributeProcessor
from .submodules.Msm_13_3_field_cleanup import FieldCleanup
from .submodules.Msm_13_4_data_validator import DataValidator
from .submodules.Msm_13_5_attribute_mapper import AttributeMapper


class DataCleanupManager:
    """
    Главный менеджер очистки и санитизации данных

    Предоставляет унифицированный API для всех операций очистки через делегирование
    к специализированным субменеджерам.
    """

    def __init__(self, metadata_manager=None):
        """
        Инициализация менеджера

        Args:
            metadata_manager: ProjectMetadataManager для валидации (опционально)
        """
        # Инициализация субменеджеров
        self.string_sanitizer = StringSanitizer()
        self.attribute_processor = AttributeProcessor()
        self.field_cleanup = FieldCleanup()
        self.data_validator = DataValidator(metadata_manager)
        self.attribute_mapper = AttributeMapper()

    # ========== Делегирующие методы для StringSanitizer ==========

    def sanitize_filename(self, name: str) -> str:
        """Очистка имени файла для Windows"""
        return self.string_sanitizer.sanitize_filename(name)

    def sanitize_attribute_value(self, value: str) -> str:
        """Очистка значения атрибута"""
        return self.string_sanitizer.sanitize_attribute_value(value)

    def sanitize_layer_name(self, name: str) -> str:
        """Очистка имени слоя"""
        return self.string_sanitizer.sanitize_layer_name(name)

    def remove_line_breaks(self, value: str) -> str:
        """Удаление переносов строк"""
        return self.string_sanitizer.remove_line_breaks(value)

    def normalize_separators(self, value: str, target_separator: str = " / ") -> str:
        """Нормализация разделителей"""
        return self.string_sanitizer.normalize_separators(value, target_separator)

    # ========== Делегирующие методы для AttributeProcessor ==========

    def parse_field(self, value: Optional[str]) -> List[str]:
        """Парсинг поля с множественными значениями"""
        return self.attribute_processor.parse_field(value)

    def join_field(self, values: List[str]) -> str:
        """Объединение списка значений в строку"""
        return self.attribute_processor.join_field(values)

    def capitalize_field(self, field_value: Optional[str]) -> str:
        """Капитализация первой буквы в каждом элементе"""
        return self.attribute_processor.capitalize_field(field_value)

    def normalize_null_value(self, value: Any, field_name: str) -> str:
        """Нормализация NULL значения"""
        return self.attribute_processor.normalize_null_value(value, field_name)

    def normalize_rights_order(self, rights_value: Optional[str],
                               owners_value: Optional[str]) -> Tuple[str, str]:
        """Нормализация порядка прав и собственников"""
        return self.attribute_processor.normalize_rights_order(rights_value, owners_value)

    def finalize_layer(self,
                      layer: QgsVectorLayer,
                      layer_name: str,
                      fields_to_process: Optional[List[str]] = None,
                      capitalize: bool = True,
                      exclude_fields: Optional[List[str]] = None) -> None:
        """Финальная обработка слоя (наведение красоты)"""
        return self.attribute_processor.finalize_layer_processing(
            layer, layer_name, fields_to_process, capitalize, exclude_fields
        )

    # ========== Делегирующие методы для FieldCleanup ==========

    def is_field_empty(self, layer: QgsVectorLayer, field_name: str) -> bool:
        """Проверка пустоты поля"""
        return self.field_cleanup.is_field_empty(layer, field_name)

    def get_empty_fields(self, layer: QgsVectorLayer) -> List[str]:
        """Получение списка пустых полей"""
        return self.field_cleanup.get_empty_fields(layer)

    def remove_empty_fields(self,
                           layer: QgsVectorLayer,
                           exclude_fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """Удаление пустых полей из слоя"""
        return self.field_cleanup.remove_empty_fields(layer, exclude_fields)

    def cleanup_layers_batch(self,
                            layers: List[QgsVectorLayer],
                            exclude_fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """Пакетная очистка полей для нескольких слоёв"""
        return self.field_cleanup.cleanup_layers_batch(layers, exclude_fields)

    def get_cleanup_summary(self, stats: Dict[str, Any]) -> str:
        """Формирование текстовой сводки по очистке"""
        return self.field_cleanup.get_cleanup_summary(stats)

    # ========== Делегирующие методы для DataValidator ==========

    def validate_metadata(self, metadata: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Полная валидация метаданных"""
        return self.data_validator.validate_all(metadata)

    def validate_required_fields(self, metadata: Dict[str, Any]) -> List[str]:
        """Проверка обязательных полей"""
        return self.data_validator.validate_required_fields(metadata)

    def validate_field(self, key: str, value: Any, metadata: Dict[str, Any]) -> Tuple[bool, str]:
        """Валидация одного поля с учетом контекста"""
        return self.data_validator.validate_field(key, value, metadata)

    def validate_attribute_value(self, value: Any, field_schema: Dict) -> Tuple[bool, str]:
        """Валидация значения атрибута по схеме"""
        return self.data_validator.validate_attribute_value(value, field_schema)

    def get_field_info(self, key: str) -> Optional[Dict]:
        """Получение информации о поле из схемы"""
        return self.data_validator.get_field_info(key)

    def is_field_required(self, key: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Проверка обязательности поля с учетом контекста"""
        return self.data_validator.is_field_required(key, metadata)

    # ========== Делегирующие методы для AttributeMapper ==========

    def map_attributes(self,
                      source_feature: QgsFeature,
                      target_feature: QgsFeature,
                      source_fields,
                      object_type: str = 'ZU') -> None:
        """Маппинг атрибутов между объектами"""
        return self.attribute_mapper.map_attributes(
            source_feature, target_feature, source_fields, object_type
        )

    def normalize_field_value(self, value: Any, field_name: str) -> str:
        """Нормализация значения поля с заменой разделителей"""
        return self.attribute_mapper.normalize_field_value(value, field_name)

    def finalize_layer_null_values(self, layer: QgsVectorLayer, layer_name: str) -> None:
        """Финальная обработка NULL значений и капитализация слоя"""
        return self.attribute_mapper.finalize_layer_null_values(layer, layer_name)

    # ========== Утилиты ==========

    def get_statistics(self) -> Dict[str, Any]:
        """
        Получение статистики работы менеджера

        Returns:
            Словарь со статистикой
        """
        return {
            'string_sanitizer': 'active',
            'attribute_processor': 'active',
            'field_cleanup': 'active',
            'data_validator': 'active' if self.data_validator.metadata_manager else 'inactive',
            'attribute_mapper': 'active'
        }
