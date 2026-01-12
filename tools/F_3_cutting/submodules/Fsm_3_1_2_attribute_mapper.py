# -*- coding: utf-8 -*-
"""
Fsm_3_1_2_AttributeMapper - Маппинг и генерация атрибутов для нарезки ЗПР

Выполняет:
- Загрузка схемы атрибутов из Base_cutting.json
- Маппинг атрибутов из Выборка_ЗУ
- Генерация расчётных полей (ID, Услов_КН, Площадь_ОЗУ)
- Создание пустых атрибутов для НГС
"""

import json
import os
from typing import Dict, List, Any, Optional

from qgis.core import QgsFeature, QgsGeometry, QgsFields, QgsField
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.utils import log_info, log_warning, log_error


class Fsm_3_1_2_AttributeMapper:
    """Маппер атрибутов для слоёв нарезки"""

    # Маппинг полей Выборка_ЗУ -> Base_cutting
    ZU_FIELD_MAPPING = {
        'КН': 'КН',
        'ЕЗ': 'ЕЗ',
        'Тип_объекта': 'Тип_объекта',
        'Адрес_Местоположения': 'Адрес_Местоположения',
        'Категория': 'Категория',
        'ВРИ': 'ВРИ',
        'Площадь': 'Площадь',
        'Права': 'Права',
        'Обременения': 'Обременение',  # Разные имена в источнике и назначении
        'Собственники': 'Собственники',
        'Арендаторы': 'Арендаторы',
    }

    def __init__(self, plugin_dir: str) -> None:
        """Инициализация маппера

        Args:
            plugin_dir: Путь к папке плагина
        """
        self.plugin_dir = plugin_dir
        self._schema: Optional[List[Dict]] = None
        self._id_counter: Dict[str, int] = {}  # Счётчики ID по слоям (deprecated)
        self._zpr_id_counter: Dict[str, int] = {}  # Счётчики ID по типу ЗПР (ОКС, ЛО, ВО)
        self._kn_counter: Dict[str, int] = {}  # Счётчики по базовому КН
        self._ez_counter: Dict[str, int] = {}  # Счётчики по базовому ЕЗ

    def load_schema(self) -> List[Dict]:
        """Загрузка схемы атрибутов из Base_cutting.json

        Returns:
            List[Dict]: Схема полей
        """
        if self._schema is not None:
            return self._schema

        from Daman_QGIS.constants import DATA_REFERENCE_PATH
        json_path = os.path.join(DATA_REFERENCE_PATH, 'Base_cutting.json')

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                self._schema = json.load(f)
            if self._schema is not None:
                log_info(f"Fsm_3_1_2: Загружена схема из Base_cutting.json ({len(self._schema)} полей)")
                return self._schema
            else:
                log_error("Fsm_3_1_2: Base_cutting.json пуст или некорректен")
                return []
        except Exception as e:
            log_error(f"Fsm_3_1_2: Ошибка загрузки Base_cutting.json: {e}")
            return []

    def get_fields(self) -> QgsFields:
        """Получить структуру полей для слоя нарезки

        Returns:
            QgsFields: Структура полей
        """
        schema = self.load_schema()
        fields = QgsFields()

        for field_def in schema:
            name = field_def.get('working_name', '')
            format_str = field_def.get('mapinfo_format', '')

            # Определение типа поля по формату MapInfo
            if 'Целое' in format_str:
                field = QgsField(name, QMetaType.Type.Int)
            else:
                # Символьное поле
                field = QgsField(name, QMetaType.Type.QString)

            fields.append(field)

        return fields

    def map_zu_attributes(self, zu_feature: QgsFeature) -> Dict[str, Any]:
        """Маппинг атрибутов из объекта Выборка_ЗУ

        Args:
            zu_feature: Объект из слоя Выборка_ЗУ

        Returns:
            Dict: Словарь атрибутов для слоя нарезки
        """
        result = self._create_empty_dict()
        schema = self.load_schema()

        # Создаём маппинг имя_поля -> тип (Целое или нет)
        field_is_integer = {}
        for field_def in schema:
            name = field_def.get('working_name', '')
            format_str = field_def.get('mapinfo_format', '')
            field_is_integer[name] = 'Целое' in format_str

        for zu_field, cutting_field in self.ZU_FIELD_MAPPING.items():
            try:
                value = zu_feature[zu_field]
                # Проверка на NULL/пустое значение
                is_empty = value is None or str(value) == 'NULL' or str(value).strip() == ''

                if is_empty:
                    # Для INTEGER полей оставляем None, для текстовых - "-"
                    if field_is_integer.get(cutting_field, False):
                        result[cutting_field] = None
                    else:
                        result[cutting_field] = "-"
                else:
                    result[cutting_field] = value
            except KeyError:
                # Поле не найдено в источнике - оставляем значение из _create_empty_dict
                pass
            except Exception:
                # Ошибка доступа - оставляем значение из _create_empty_dict
                pass

        return result

    def create_empty_attributes(self) -> Dict[str, Any]:
        """Создание пустых атрибутов для НГС (без ЗУ)

        Returns:
            Dict: Словарь с NULL значениями
        """
        return self._create_empty_dict()

    def generate_id(self, layer_name: str) -> int:
        """Генерация уникального ID для слоя

        Args:
            layer_name: Имя слоя

        Returns:
            int: Следующий ID
        """
        if layer_name not in self._id_counter:
            self._id_counter[layer_name] = 0

        self._id_counter[layer_name] += 1
        return self._id_counter[layer_name]

    def reset_id_counter(self, layer_name: str) -> None:
        """Сброс счётчика ID для слоя (deprecated, используйте reset_zpr_id_counter)

        Args:
            layer_name: Имя слоя
        """
        self._id_counter[layer_name] = 0

    def generate_zpr_id(self, zpr_type: str) -> int:
        """Генерация сквозного ID для типа ЗПР

        ID уникален в пределах типа ЗПР (ОКС, ЛО, ВО).
        Используется для сквозной нумерации: Раздел -> НГС -> Без_Меж

        Args:
            zpr_type: Тип ЗПР (ОКС, ЛО, ВО)

        Returns:
            int: Следующий ID
        """
        if zpr_type not in self._zpr_id_counter:
            self._zpr_id_counter[zpr_type] = 0

        self._zpr_id_counter[zpr_type] += 1
        return self._zpr_id_counter[zpr_type]

    def reset_zpr_id_counter(self, zpr_type: str) -> None:
        """Сброс счётчика ID для типа ЗПР

        Args:
            zpr_type: Тип ЗПР (ОКС, ЛО, ВО)
        """
        self._zpr_id_counter[zpr_type] = 0

    def get_current_zpr_id(self, zpr_type: str) -> int:
        """Получить текущее значение счётчика ID для типа ЗПР

        Args:
            zpr_type: Тип ЗПР (ОКС, ЛО, ВО)

        Returns:
            int: Текущее значение счётчика (последний выданный ID)
        """
        return self._zpr_id_counter.get(zpr_type, 0)

    def reset_kn_counters(self) -> None:
        """Сброс счётчиков КН и ЕЗ (вызывать перед обработкой нового слоя)"""
        self._kn_counter.clear()
        self._ez_counter.clear()

    def generate_conditional_kn(self, base_kn: Optional[str]) -> str:
        """Генерация условного кадастрового номера

        Формат: "КН:ЗУ{index}" где index уникален для каждого базового КН

        Примеры:
            91:01:012001:106 -> 91:01:012001:106:ЗУ1, 91:01:012001:106:ЗУ2, ...
            91:01:012001:35 -> 91:01:012001:35:ЗУ1, ...

        Args:
            base_kn: Базовый КН (из ЗУ)

        Returns:
            str: Условный КН
        """
        if base_kn and str(base_kn).strip() and str(base_kn).strip() != '-':
            kn_key = str(base_kn).strip()
            # Инкрементируем счётчик для этого КН
            if kn_key not in self._kn_counter:
                self._kn_counter[kn_key] = 0
            self._kn_counter[kn_key] += 1
            return f"{kn_key}:ЗУ{self._kn_counter[kn_key]}"
        else:
            # Для НГС без базового КН - используем placeholder
            placeholder = "00:00:000000:0000"
            if placeholder not in self._kn_counter:
                self._kn_counter[placeholder] = 0
            self._kn_counter[placeholder] += 1
            return f"{placeholder}:ЗУ{self._kn_counter[placeholder]}"

    def generate_conditional_ez(self, base_ez: Optional[str]) -> str:
        """Генерация условного номера единого землепользования

        Формат: "ЕЗ:ЗУ{index}" где index уникален для каждого базового ЕЗ

        Args:
            base_ez: Базовый ЕЗ

        Returns:
            str: Условный ЕЗ или "-" если ЕЗ пустой
        """
        if base_ez and str(base_ez).strip() and str(base_ez).strip() != '-':
            ez_key = str(base_ez).strip()
            # Инкрементируем счётчик для этого ЕЗ
            if ez_key not in self._ez_counter:
                self._ez_counter[ez_key] = 0
            self._ez_counter[ez_key] += 1
            return f"{ez_key}:ЗУ{self._ez_counter[ez_key]}"
        else:
            return "-"

    def calculate_area(self, geometry: QgsGeometry) -> int:
        """Расчёт площади геометрии

        Args:
            geometry: Геометрия объекта

        Returns:
            int: Площадь в кв.м (округлённая)
        """
        if geometry.isEmpty():
            return 0

        area = geometry.area()
        return int(round(area))

    def fill_generated_fields(
        self,
        attributes: Dict[str, Any],
        geometry: QgsGeometry,
        layer_name: str,
        zpr_type: str,
        explicit_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Заполнение генерируемых полей

        Args:
            attributes: Базовые атрибуты (из ЗУ или пустые)
            geometry: Геометрия объекта
            layer_name: Имя выходного слоя
            zpr_type: Тип ЗПР (ОКС, ЛО, ВО)
            explicit_id: Явно заданный ID (если None, генерируется автоматически)

        Returns:
            Dict: Обновлённые атрибуты
        """
        result = attributes.copy()

        # ID - явный или автоинкремент
        if explicit_id is not None:
            result['ID'] = explicit_id
        else:
            # Fallback на старую логику (по имени слоя)
            result['ID'] = self.generate_id(layer_name)

        # Услов_КН - счётчик уникален для каждого базового КН
        base_kn = attributes.get('КН')
        result['Услов_КН'] = self.generate_conditional_kn(base_kn)

        # Услов_ЕЗ - счётчик уникален для каждого базового ЕЗ
        base_ez = attributes.get('ЕЗ')
        result['Услов_ЕЗ'] = self.generate_conditional_ez(base_ez)

        # Площадь_ОЗУ
        result['Площадь_ОЗУ'] = self.calculate_area(geometry)

        # ЗПР - тип исходного слоя
        result['ЗПР'] = zpr_type

        # ЗАГЛУШКИ - TODO реализовать позже
        result['План_категория'] = "-"  # TODO: из справочника Land_categories
        result['План_ВРИ'] = "-"  # TODO: из справочника VRI
        result['Вид_Работ'] = "-"  # TODO: из справочника Work_types
        result['Точки'] = "-"  # TODO: нумерация вершин
        result['Общая_земля'] = "-"  # TODO: проверка ВРИ (12.0.1, 12.0.2, 5.0)

        # ОКС_на_ЗУ - заглушки, будут заполнены через M_23.analyze_cutting_geometry()
        # после создания контуров (в cutting_engine или при финализации слоя)
        # Для НГС: выписка = "-" (нет выписки), факт = пересчитать геометрически
        # Для обычных ЗУ: выписка = из выписки ОКС, факт = пересчитать геометрически
        result['ОКС_на_ЗУ_выписка'] = "-"
        result['ОКС_на_ЗУ_факт'] = "-"

        # Поля наложений - заглушки
        result['НП'] = "-"  # TODO: маппинг названия НП
        result['МО'] = "-"  # TODO: маппинг названия МО
        result['Лес'] = "-"  # TODO: маппинг названия лесничества
        result['Вода'] = "-"  # TODO: маппинг названия водного объекта

        return result

    def set_overlay_value(
        self,
        attributes: Dict[str, Any],
        overlay_type: str,
        value: Optional[str]
    ) -> Dict[str, Any]:
        """Установка значения поля наложения

        Args:
            attributes: Словарь атрибутов
            overlay_type: Тип наложения (НП, МО, Лес, Вода)
            value: Значение для установки

        Returns:
            Dict: Обновлённые атрибуты
        """
        result = attributes.copy()

        if overlay_type in ['НП', 'МО', 'Лес', 'Вода']:
            result[overlay_type] = value if value else "-"

        return result

    def set_oks_zu_values(
        self,
        attributes: Dict[str, Any],
        oks_vypiska: Optional[str] = None,
        oks_fact: Optional[str] = None
    ) -> Dict[str, Any]:
        """Установка значений полей ОКС_на_ЗУ

        Вызывается из cutting_engine после анализа через M_23.

        Args:
            attributes: Словарь атрибутов
            oks_vypiska: Значение ОКС_на_ЗУ_выписка
            oks_fact: Значение ОКС_на_ЗУ_факт

        Returns:
            Dict: Обновлённые атрибуты
        """
        result = attributes.copy()

        result['ОКС_на_ЗУ_выписка'] = oks_vypiska if oks_vypiska and str(oks_vypiska).strip() not in ('', 'NULL', 'None') else "-"
        result['ОКС_на_ЗУ_факт'] = oks_fact if oks_fact and str(oks_fact).strip() not in ('', 'NULL', 'None') else "-"

        return result

    def _create_empty_dict(self) -> Dict[str, Any]:
        """Создание словаря с пустыми значениями для всех полей

        Returns:
            Dict: Словарь с None для целочисленных и "-" для текстовых полей
        """
        schema = self.load_schema()
        result = {}

        for field_def in schema:
            name = field_def.get('working_name', '')
            format_str = field_def.get('mapinfo_format', '')

            # Целочисленные поля -> None
            # Текстовые поля -> "-"
            if 'Целое' in format_str:
                result[name] = None
            else:
                result[name] = "-"

        return result

    def attributes_to_list(self, attributes: Dict[str, Any]) -> List[Any]:
        """Преобразование словаря атрибутов в список для QgsFeature

        Args:
            attributes: Словарь атрибутов

        Returns:
            List: Список значений в порядке полей схемы
        """
        schema = self.load_schema()
        result = []

        for field_def in schema:
            name = field_def.get('working_name', '')
            value = attributes.get(name)

            # Преобразование None в "-" для текстовых полей
            format_str = field_def.get('mapinfo_format', '')
            if 'Целое' not in format_str and value is None:
                value = "-"

            result.append(value)

        return result
