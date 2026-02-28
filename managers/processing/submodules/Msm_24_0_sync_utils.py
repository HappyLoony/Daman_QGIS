# -*- coding: utf-8 -*-
"""
Msm_24_0 - Общие утилиты для модулей синхронизации M_24

Содержит функции сравнения и форматирования значений,
используемые в Msm_24_3 (SyncEngine) и Msm_24_4 (EzProcessor).

Перенесено из Fsm_2_2_0_sync_utils.py согласно DRY principle.
"""

from typing import Any, Optional


def values_differ(value1: Any, value2: Any) -> bool:
    """
    Проверить различаются ли два значения (для кадастровых данных)

    Особенности:
    - "-" считается пустым значением
    - Числа сравниваются с погрешностью 0.01 (1 см)
    - Поддержка запятой как десятичного разделителя

    Args:
        value1: Первое значение
        value2: Второе значение

    Returns:
        bool: True если значения различаются
    """
    # Приводим к строкам для сравнения
    str1 = str(value1).strip() if value1 is not None else ""
    str2 = str(value2).strip() if value2 is not None else ""

    # "-" считается пустым значением (стандарт кадастровых данных)
    if str1 == "-":
        str1 = ""
    if str2 == "-":
        str2 = ""

    # Для чисел сравниваем с погрешностью 0.01 м (1 см)
    try:
        float1 = float(str1.replace(',', '.')) if str1 else None
        float2 = float(str2.replace(',', '.')) if str2 else None
        if float1 is not None and float2 is not None:
            return abs(float1 - float2) > 0.01
    except (ValueError, AttributeError):
        pass

    return str1 != str2


def is_empty(value: Any) -> bool:
    """
    Проверить пусто ли значение (для кадастровых данных)

    Пустыми считаются:
    - None
    - Пустая строка
    - "NULL"
    - "-"
    - "0" и "0.0" (артефакт систем ввода кадастровых данных)

    Args:
        value: Проверяемое значение

    Returns:
        bool: True если значение пустое
    """
    if value is None:
        return True

    str_value = str(value).strip()
    return str_value in ('', 'NULL', '-', '0', '0.0')


def find_cadnum_field(layer) -> Optional[str]:
    """
    Найти поле кадастрового номера в слое

    После рефакторинга импорта (DATABASE-DRIVEN):
    - Выписки используют 'КН' (working_name из Base_field_mapping_EGRN.json)
    - Выборка использует 'КН' (working_name из Base_selection_ZU/OKS.json)
    - Названия полей ИДЕНТИЧНЫ

    Args:
        layer: QgsVectorLayer

    Returns:
        str: Имя поля кадастрового номера или None
    """
    if layer.fields().indexOf('КН') != -1:
        return 'КН'
    return None


def format_value_for_log(value: Any, max_length: int = 50) -> str:
    """
    Форматировать значение для логирования

    Args:
        value: Значение для форматирования
        max_length: Максимальная длина строки (по умолчанию 50)

    Returns:
        str: Отформатированная строка
    """
    if value is None or value == '' or value == '-':
        return '(пусто)'

    str_value = str(value)
    if len(str_value) > max_length:
        return str_value[:max_length - 3] + "..."

    return str_value
