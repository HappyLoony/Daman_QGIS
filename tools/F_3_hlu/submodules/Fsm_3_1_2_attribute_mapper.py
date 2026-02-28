# -*- coding: utf-8 -*-
"""
Fsm_3_1_2_AttributeMapper - Маппинг атрибутов для лесной нарезки

Выполняет:
- Определение структуры полей Le_3_2_*/Le_3_3_* (24 поля)
- Маппинг атрибутов из Le_2_1_*/Le_2_2_* (7 полей)
- Маппинг атрибутов из Le_3_1_1_1_Лес_Ред_Выделы (17 полей из Base_forest_vydely.json)
- Пересчёт ID и Площадь_ОЗУ
"""

from typing import Dict, List, Any, Optional, Tuple

from qgis.core import QgsFeature, QgsGeometry, QgsFields, QgsField
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers import get_reference_managers


class Fsm_3_1_2_AttributeMapper:
    """Маппер атрибутов для слоёв лесной нарезки Le_3_*"""

    # Поля из Le_2_* которые сохраняются (статичные, не меняются)
    LE3_FIELDS = [
        ('ID', 'Целое'),
        ('КН', 'Символы'),
        ('Услов_КН', 'Символы'),
        ('Собственники', 'Символы'),
        ('Арендаторы', 'Символы'),
        ('Площадь_ОЗУ', 'Целое'),
        ('ЗПР', 'Символы'),
    ]

    def __init__(self) -> None:
        """Инициализация маппера"""
        self._id_counters: Dict[str, int] = {}
        self._forest_fields: Optional[List[Tuple[str, str]]] = None

    def _get_forest_fields(self) -> List[Tuple[str, str]]:
        """
        Получить поля лесных выделов из Base_forest_vydely.json

        Returns:
            List[Tuple[str, str]]: Список кортежей (working_name, тип)
        """
        if self._forest_fields is not None:
            return self._forest_fields

        try:
            ref_manager = get_reference_managers()
            if ref_manager and hasattr(ref_manager, 'layer_field_structure'):
                fields_data = ref_manager.layer_field_structure.get_forest_vydely_fields()

                if fields_data:
                    self._forest_fields = []
                    for field in fields_data:
                        name = field.get('working_name', '')
                        mapinfo_format = field.get('mapinfo_format', '')
                        # Определяем тип по mapinfo_format
                        field_type = 'Целое' if 'Целое' in mapinfo_format else 'Символы'
                        self._forest_fields.append((name, field_type))

                    log_info(f"Fsm_3_1_2: Загружено {len(self._forest_fields)} полей из Base_forest_vydely.json")
                    return self._forest_fields

        except Exception as e:
            log_warning(f"Fsm_3_1_2: Ошибка загрузки Base_forest_vydely.json: {e}")

        # Defensive: пустой список если JSON не загрузился
        log_error("Fsm_3_1_2: Base_forest_vydely.json не загружен, используется пустой список")
        self._forest_fields = []
        return self._forest_fields

    def get_fields(self) -> QgsFields:
        """Получить структуру полей для слоя Le_3_*

        Returns:
            QgsFields: Структура полей (24 поля)
        """
        fields = QgsFields()

        # Добавляем поля из Le_2_*
        for name, field_type in self.LE3_FIELDS:
            if field_type == 'Целое':
                field = QgsField(name, QMetaType.Type.Int)
            else:
                field = QgsField(name, QMetaType.Type.QString)
            fields.append(field)

        # Добавляем лесные поля из JSON
        for name, field_type in self._get_forest_fields():
            if field_type == 'Целое':
                field = QgsField(name, QMetaType.Type.Int)
            else:
                field = QgsField(name, QMetaType.Type.QString)
            fields.append(field)

        return fields

    def get_field_names(self) -> List[str]:
        """Получить список имён полей

        Returns:
            List[str]: Список имён полей
        """
        names = [f[0] for f in self.LE3_FIELDS]
        names.extend([f[0] for f in self._get_forest_fields()])
        return names

    def reset_id_counter(self, layer_name: str) -> None:
        """Сброс счётчика ID для слоя

        Args:
            layer_name: Имя слоя
        """
        self._id_counters[layer_name] = 0

    def generate_id(self, layer_name: str) -> int:
        """Генерация уникального ID для слоя

        Args:
            layer_name: Имя слоя

        Returns:
            int: Следующий ID
        """
        if layer_name not in self._id_counters:
            self._id_counters[layer_name] = 0

        self._id_counters[layer_name] += 1
        return self._id_counters[layer_name]

    def map_le3_attributes(self, le3_feature: QgsFeature) -> Dict[str, Any]:
        """Маппинг атрибутов из объекта Le_2_*

        Args:
            le3_feature: Объект из слоя Le_2_*

        Returns:
            Dict: Словарь атрибутов (7 полей)
        """
        result = {}

        for name, field_type in self.LE3_FIELDS:
            try:
                value = le3_feature[name]
                # Проверка на NULL/пустое значение
                is_empty = value is None or str(value) == 'NULL' or str(value).strip() == ''

                if is_empty:
                    if field_type == 'Целое':
                        result[name] = None
                    else:
                        result[name] = "-"
                else:
                    result[name] = value
            except KeyError:
                # Поле не найдено
                if field_type == 'Целое':
                    result[name] = None
                else:
                    result[name] = "-"

        return result

    def map_forest_attributes(self, forest_feature: QgsFeature) -> Dict[str, Any]:
        """Маппинг атрибутов из объекта L_4_1_1_Лес_Ред_Выделы

        Args:
            forest_feature: Объект из слоя лесных выделов

        Returns:
            Dict: Словарь атрибутов (17 полей)
        """
        result = {}

        for name, field_type in self._get_forest_fields():
            try:
                value = forest_feature[name]
                is_empty = value is None or str(value) == 'NULL' or str(value).strip() == ''

                if is_empty:
                    if field_type == 'Целое':
                        result[name] = None
                    else:
                        result[name] = "-"
                else:
                    result[name] = value
            except KeyError:
                # Поле не найдено
                if field_type == 'Целое':
                    result[name] = None
                else:
                    result[name] = "-"

        return result

    def create_empty_forest_attributes(self) -> Dict[str, Any]:
        """Создание пустых лесных атрибутов

        Returns:
            Dict: Словарь с пустыми значениями (17 полей)
        """
        result = {}
        for name, field_type in self._get_forest_fields():
            if field_type == 'Целое':
                result[name] = None
            else:
                result[name] = "-"
        return result

    def calculate_area(self, geometry: QgsGeometry) -> int:
        """Расчёт площади геометрии

        Args:
            geometry: Геометрия объекта

        Returns:
            int: Площадь в кв.м (округлённая)
        """
        if geometry.isEmpty():
            return 0
        return int(round(geometry.area()))

    def merge_attributes(
        self,
        le3_attrs: Dict[str, Any],
        forest_attrs: Dict[str, Any],
        geometry: QgsGeometry,
        layer_name: str
    ) -> Dict[str, Any]:
        """Объединение атрибутов из Le_2_* и лесных выделов

        Args:
            le3_attrs: Атрибуты из Le_2_*
            forest_attrs: Атрибуты из лесного выдела
            geometry: Новая геометрия (для пересчёта площади)
            layer_name: Имя выходного слоя (для генерации ID)

        Returns:
            Dict: Объединённые атрибуты (24 поля)
        """
        result = {}

        # Копируем атрибуты из Le_2_*
        result.update(le3_attrs)

        # Генерируем новый ID
        result['ID'] = self.generate_id(layer_name)

        # Пересчитываем площадь по новой геометрии
        result['Площадь_ОЗУ'] = self.calculate_area(geometry)

        # Добавляем лесные атрибуты
        result.update(forest_attrs)

        return result

    def attributes_to_list(self, attributes: Dict[str, Any]) -> List[Any]:
        """Преобразование словаря атрибутов в список для QgsFeature

        Args:
            attributes: Словарь атрибутов

        Returns:
            List: Список значений в порядке полей
        """
        result = []

        # Сначала поля из Le_2_*
        for name, field_type in self.LE3_FIELDS:
            value = attributes.get(name)
            if field_type != 'Целое' and value is None:
                value = "-"
            result.append(value)

        # Затем лесные поля из JSON
        for name, field_type in self._get_forest_fields():
            value = attributes.get(name)
            if field_type != 'Целое' and value is None:
                value = "-"
            result.append(value)

        return result

    def validate_forest_layer_fields(self, layer_fields: List[str]) -> Tuple[bool, List[str]]:
        """Проверка наличия всех лесных полей в слое

        Args:
            layer_fields: Список полей слоя

        Returns:
            Tuple[bool, List[str]]: (валидно, список отсутствующих полей)
        """
        missing = []
        for name, _ in self._get_forest_fields():
            if name not in layer_fields:
                missing.append(name)

        return len(missing) == 0, missing
