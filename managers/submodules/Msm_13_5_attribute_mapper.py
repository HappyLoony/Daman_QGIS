# -*- coding: utf-8 -*-
"""
Msm_13_5: Attribute Mapper - Маппинг атрибутов между слоями

Маппинг полей, нормализация значений, обработка NULL.
Динамическая загрузка маппинга из Base_selection_ZU.json и Base_selection_OKS.json.
"""

import json
import os
import re
from typing import Optional, Dict

from qgis.core import QgsVectorLayer, QgsFeature, QgsFields

from Daman_QGIS.utils import log_debug, log_error, log_info
from Daman_QGIS.managers.submodules.Msm_13_2_attribute_processor import AttributeProcessor


class AttributeMapper:
    """
    Маппер атрибутов между WFS и рабочими слоями

    Загружает маппинг полей из Base_selection_ZU.json и Base_selection_OKS.json,
    выполняет перенос данных с нормализацией значений.

    Примеры использования:
        >>> mapper = AttributeMapper()
        >>> mapper.map_attributes(source_feature, target_feature, source_fields, 'ZU')
        >>> mapper.finalize_layer_null_values(layer, 'L_2_1_1_Земельные_участки')
    """

    # Кэши для маппингов (загружаются один раз при первом использовании)
    _field_mapping_zu_cache: Optional[Dict[str, Optional[str]]] = None
    _field_mapping_oks_cache: Optional[Dict[str, Optional[str]]] = None

    @classmethod
    def _load_field_mapping_zu(cls) -> Dict[str, Optional[str]]:
        """Загрузка маппинга полей для ЗУ из Base_selection_ZU.json

        Returns:
            dict: Словарь {working_name: wfs_zu_field или None}
        """
        if cls._field_mapping_zu_cache is not None:
            return cls._field_mapping_zu_cache

        try:
            # Используем BaseReferenceLoader для remote загрузки
            from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader

            loader = BaseReferenceLoader()
            data = loader._load_json('Base_selection_ZU.json')

            if data is None:
                raise FileNotFoundError("Base_selection_ZU.json не найден ни на remote ни локально")

            # Строим маппинг: working_name -> wfs_zu_field
            mapping = {}
            for record in data:
                working_name = record.get('working_name')
                wfs_field = record.get('wfs_zu_field')

                # Если wfs_field = "-", то поле-заглушка (None)
                if wfs_field == '-' or not wfs_field:
                    mapping[working_name] = None
                else:
                    mapping[working_name] = wfs_field

            cls._field_mapping_zu_cache = mapping
            log_info(f"Msm_13_5_AttributeMapper: Загружен маппинг полей ЗУ из Base_selection_ZU.json: {len(mapping)} полей")
            return mapping

        except Exception as e:
            log_error(f"Msm_13_5_AttributeMapper: Ошибка при загрузке Base_selection_ZU.json: {e}")
            # Возвращаем пустой словарь в случае ошибки
            cls._field_mapping_zu_cache = {}
            return {}

    @classmethod
    def _load_field_mapping_oks(cls) -> Dict[str, Optional[str]]:
        """Загрузка маппинга полей для ОКС из Base_selection_OKS.json

        Returns:
            dict: Словарь {working_name: wfs_oks_field или None}
        """
        if cls._field_mapping_oks_cache is not None:
            return cls._field_mapping_oks_cache

        try:
            # Используем BaseReferenceLoader для remote загрузки
            from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader

            loader = BaseReferenceLoader()
            data = loader._load_json('Base_selection_OKS.json')

            if data is None:
                raise FileNotFoundError("Base_selection_OKS.json не найден ни на remote ни локально")

            # Строим маппинг: working_name -> wfs_oks_field
            mapping = {}
            for record in data:
                working_name = record.get('working_name')
                wfs_field = record.get('wfs_oks_field')

                # Если wfs_field = "-", то поле-заглушка (None)
                if wfs_field == '-' or not wfs_field:
                    mapping[working_name] = None
                else:
                    mapping[working_name] = wfs_field

            cls._field_mapping_oks_cache = mapping
            log_info(f"Msm_13_5_AttributeMapper: Загружен маппинг полей ОКС из Base_selection_OKS.json: {len(mapping)} полей")
            return mapping

        except Exception as e:
            log_error(f"Msm_13_5_AttributeMapper: Ошибка при загрузке Base_selection_OKS.json: {e}")
            # Возвращаем пустой словарь в случае ошибки
            cls._field_mapping_oks_cache = {}
            return {}

    @staticmethod
    def map_attributes(source_feature: QgsFeature, target_feature: QgsFeature,
                      source_fields: QgsFields, object_type: str = 'ZU') -> None:
        """Маппинг атрибутов из исходного объекта в новую структуру

        Args:
            source_feature: Исходный feature
            target_feature: Целевой feature (изменяется in-place)
            source_fields: Поля исходного слоя
            object_type: Тип объекта ('ZU' или 'OKS')
        """
        # Загружаем правильный маппинг из JSON
        if object_type == 'ZU':
            field_mapping = AttributeMapper._load_field_mapping_zu()
        else:
            field_mapping = AttributeMapper._load_field_mapping_oks()

        # Debug: Логируем доступные поля (только один раз для каждого типа)
        log_key = f'_logged_fields_{object_type}'
        if not hasattr(AttributeMapper, log_key):
            field_names = [field.name() for field in source_fields]
            log_info(f"Msm_13_5_AttributeMapper: Доступные поля в исходном слое ({object_type}): {', '.join(field_names)}")
            setattr(AttributeMapper, log_key, True)

        # Получаем список полей целевого объекта
        target_fields = target_feature.fields()
        target_field_names = [field.name() for field in target_fields]

        # Маппим каждое поле
        for target_field, source_field in field_mapping.items():
            # Проверяем что целевое поле существует
            if target_field not in target_field_names:
                continue

            # Определяем тип целевого поля для корректной обработки значений
            from qgis.PyQt.QtCore import QMetaType
            target_field_obj = target_feature.fields().field(target_field)
            is_integer_field = target_field_obj.type() == QMetaType.Type.Int

            # Если source_field = None - поле-заглушка (не маппится)
            if source_field is not None:
                # Проверяем на множественный маппинг (несколько полей через ";")
                if ';' in source_field:
                    # Множественный маппинг - берём первое непустое значение
                    source_field_names = [f.strip() for f in source_field.split(';')]
                    value = None

                    # Оптимизация: создаём список полей один раз (вместо создания на каждой итерации)
                    source_field_list = [f.name() for f in source_fields]
                    for field_name in source_field_names:
                        if field_name in source_field_list:
                            temp_value = source_feature[field_name]
                            # FIX (2025-11-19): Добавлен "0" в список пустых значений для ЕГРН
                            # "0" считается пустым значением - продолжаем поиск в следующих полях
                            if temp_value is not None and str(temp_value).strip() not in ['', '-', 'NULL', '0']:
                                value = temp_value
                                break

                    # Если ничего не нашли, value остаётся None

                    # Специальная обработка для Integer полей
                    if is_integer_field:
                        if value is not None:
                            try:
                                target_feature[target_field] = int(float(value))
                            except (ValueError, TypeError):
                                target_feature[target_field] = 0
                        else:
                            target_feature[target_field] = 0
                    else:
                        # Текстовое поле
                        normalized_value = AttributeMapper.normalize_field_value(value, target_field)
                        target_feature[target_field] = normalized_value

                # Одиночный маппинг
                elif source_field in [f.name() for f in source_fields]:
                    # Получаем значение из исходного feature
                    value = source_feature[source_field]

                    # Специальная обработка для Integer полей (например "Площадь" в ЗУ)
                    if is_integer_field:
                        if value is not None:
                            try:
                                # Преобразуем в целое число
                                target_feature[target_field] = int(float(value))
                            except (ValueError, TypeError):
                                # Некорректное значение - подставляем 0
                                target_feature[target_field] = 0
                        else:
                            # NULL заменяем на 0 для Integer полей
                            target_feature[target_field] = 0
                    else:
                        # Применяем нормализацию для всех текстовых полей
                        normalized_value = AttributeMapper.normalize_field_value(value, target_field)
                        target_feature[target_field] = normalized_value
                else:
                    # Поле не найдено
                    if is_integer_field:
                        # Integer поле - подставляем 0
                        target_feature[target_field] = 0
                    else:
                        # Текстовое поле - применяем нормализацию (вернет "-")
                        normalized_value = AttributeMapper.normalize_field_value(None, target_field)
                        target_feature[target_field] = normalized_value
                    if not hasattr(AttributeMapper, f'_logged_missing_{source_field}'):
                        log_debug(f"Msm_13_5_AttributeMapper: Поле '{source_field}' не найдено в исходном слое")
                        setattr(AttributeMapper, f'_logged_missing_{source_field}', True)
            else:
                # Поле-заглушка
                if is_integer_field:
                    # Integer поле - подставляем 0
                    target_feature[target_field] = 0
                else:
                    # Текстовое поле - применяем нормализацию (вернет "-")
                    normalized_value = AttributeMapper.normalize_field_value(None, target_field)
                    target_feature[target_field] = normalized_value

    @staticmethod
    def normalize_field_value(value, field_name: str) -> str:
        """Нормализация значения поля

        Заменяет ";" на " / " с нормализацией пробелов.
        Обрабатывает специальные поля (Права, Обременения, Собственники, Арендаторы) - возвращает "-" для NULL.

        Args:
            value: Значение поля (может быть None, int, str)
            field_name: Имя поля

        Returns:
            str: Нормализованное значение
        """
        # Используем универсальный обработчик для NULL значений
        processor = AttributeProcessor()
        normalized_value = processor.normalize_null_value(value, field_name)

        # Если вернулась пустая строка или "-", возвращаем как есть
        if normalized_value == '' or normalized_value == '-':
            return normalized_value

        # Заменяем ";" на " / " с нормализацией пробелов
        # Заменяем любое количество пробелов + ";" + любое количество пробелов на " / "
        result = re.sub(r'\s*;\s*', ' / ', normalized_value)

        # Логируем только если произошла реальная замена разделителя
        # if ';' in str(value):
        #     log_debug(f"Msm_13_5_AttributeMapper: Нормализация поля '{field_name}': '{value}' → '{result}'")

        return result

    @staticmethod
    def finalize_layer_null_values(layer: QgsVectorLayer, layer_name: str) -> None:
        """Финальная обработка NULL значений и капитализация перед сохранением в GeoPackage

        ВАЖНО: Этот метод вызывается ДО сохранения в GeoPackage,
        чтобы обработанные данные сохранились в файл.

        Выполняет комплексную обработку:
        1. Заполнение NULL/пустых значений ("-" или "Сведения отсутствуют")
        2. Капитализация первой буквы во всех текстовых полях

        Args:
            layer: Слой для обработки (memory layer перед сохранением)
            layer_name: Имя слоя (для логирования)
        """
        # Делегируем обработку универсальному модулю с капитализацией
        processor = AttributeProcessor()
        processor.finalize_layer_processing(layer, layer_name, capitalize=True)
