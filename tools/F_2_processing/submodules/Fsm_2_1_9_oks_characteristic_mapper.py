# -*- coding: utf-8 -*-
"""
Fsm_2_1_9: Маппер характеристик ОКС - определение типа и значения основной характеристики
Заполняет поля "Значение" и "Характеристика" для ОКС на основе данных WFS
"""

from typing import Optional, Tuple
from qgis.core import QgsFeature, QgsFields

from Daman_QGIS.utils import log_debug, log_warning


class Fsm_2_1_9_OKSCharacteristicMapper:
    """Маппер характеристик ОКС для выборки 2_1

    Определяет тип основной характеристики и её значение по данным из WFS слоя.
    Поддерживает 6 вариантов полей для 3 типов ОКС (Сооружение, Здание, ОНС).
    """

    # Маппинг: WFS поле → Тип характеристики
    # Порядок КРИТИЧЕСКИ ВАЖЕН - проверяется строго в этой последовательности
    CHARACTERISTIC_MAPPING = [
        ('params_area', 'Площадь'),
        ('params_built_up_area', 'Площадь застройки'),
        ('params_extension', 'Протяженность'),
        ('build_record_area', 'Площадь'),
        ('built_up_area', 'Площадь'),
        ('extension', 'Протяженность'),
    ]

    # Значения считающиеся пустыми (включая "0" для ЕГРН)
    EMPTY_VALUES = ['', '-', 'NULL', '0']

    @classmethod
    def map_characteristic_and_value(cls, source_feature: QgsFeature,
                                      target_feature: QgsFeature,
                                      source_fields: QgsFields) -> None:
        """Заполняет поля "Значение" и "Характеристика" для ОКС

        Ищет первое непустое значение из 6 полей в строгом порядке:
        1. params_area (Площадь - Сооружение)
        2. params_built_up_area (Площадь застройки - Сооружение)
        3. params_extension (Протяженность - Сооружение)
        4. build_record_area (Площадь - Здание)
        5. built_up_area (Площадь - ОНС)
        6. extension (Протяженность - ОНС)

        Заполняет:
        - "Значение": найденное число (String, может быть дробным)
        - "Характеристика": тип характеристики соответствующего поля

        Если все поля пусты или содержат "0":
        - "Значение" = "-"
        - "Характеристика" = "-"

        Args:
            source_feature: Исходный feature из WFS слоя
            target_feature: Целевой feature (изменяется in-place)
            source_fields: Поля исходного слоя
        """
        # Проверяем наличие целевых полей
        if 'Значение' not in [f.name() for f in target_feature.fields()]:
            log_warning("Fsm_2_1_9: Поле 'Значение' не найдено в целевом слое")
            return

        if 'Характеристика' not in [f.name() for f in target_feature.fields()]:
            log_warning("Fsm_2_1_9: Поле 'Характеристика' не найдено в целевом слое")
            return

        # Создаём список доступных полей один раз (оптимизация)
        source_field_names = [f.name() for f in source_fields]

        # Ищем первое непустое значение в строгом порядке
        found_value, found_characteristic = cls._find_first_valid_value(
            source_feature, source_field_names
        )

        # Заполняем целевые поля
        if found_value is not None:
            target_feature['Значение'] = str(found_value)
            target_feature['Характеристика'] = found_characteristic
            log_debug(f"Fsm_2_1_9: Найдена характеристика '{found_characteristic}' = '{found_value}'")
        else:
            # Все поля пусты
            target_feature['Значение'] = '-'
            target_feature['Характеристика'] = '-'
            log_debug("Fsm_2_1_9: Все поля характеристик пусты - установлены '-'")

    @classmethod
    def _find_first_valid_value(cls, source_feature: QgsFeature,
                                source_field_names: list) -> Tuple[Optional[str], Optional[str]]:
        """Поиск первого непустого значения характеристики

        Args:
            source_feature: Исходный feature
            source_field_names: Список доступных полей

        Returns:
            tuple: (значение, тип_характеристики) или (None, None) если все пусты
        """
        for field_name, characteristic_type in cls.CHARACTERISTIC_MAPPING:
            # Проверяем существование поля в исходном слое
            if field_name not in source_field_names:
                continue

            # Получаем значение
            value = source_feature[field_name]

            # Проверяем на пустоту (включая "0")
            if value is None:
                continue

            value_str = str(value).strip()
            if value_str in cls.EMPTY_VALUES:
                continue

            # Найдено первое непустое значение
            return (value_str, characteristic_type)

        # Все поля пусты
        return (None, None)
