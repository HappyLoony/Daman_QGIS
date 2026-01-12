# -*- coding: utf-8 -*-
"""
Утилиты для работы с системами координат
"""

import re
from typing import Optional
from Daman_QGIS.utils import log_info
def extract_crs_short_name(crs_description: str) -> Optional[str]:
    """
    Извлекает короткое название СК из полного описания

    Правила:
    1. Ищем текст после "USER:XXXXXX - " (где XXXXXX - любые 6 цифр)
    2. Извлекаем МСК-XX или СК-XX (XX - любое количество цифр до пробела)
    3. Если есть "(зона N)" сразу после - добавляем _N
    4. Игнорируем все после закрывающей скобки зоны

    Примеры:
    - "USER:100023 - МСК-23 (зона 2) Краснодарский край" -> "МСК-23_2"
    - "USER:100007 - МСК-07 Кабардино-Балкарская Республика" -> "МСК-07"
    - "USER:100063 - СК-63 (зона 4) (район X) МСК-90" -> "СК-63_4"
    - "МСК-39 (зона 1)" -> "МСК-39_1"
    - "МСК-39" -> "МСК-39"
    - "МСК-05" -> "МСК-05"
    - "Чижик_МСК-1964 города Санкт-Петербург" -> "МСК-1964"

    Args:
        crs_description: Полное описание системы координат

    Returns:
        str: Короткое название СК или None если не удалось извлечь
    """
    if not crs_description:
        log_info(f"crs_utils: Пустое описание СК")
        return None

    # Сначала пытаемся найти часть после "USER:XXXXXX - "
    user_pattern = r'USER:\d{6}\s*-\s*(.+)'
    user_match = re.search(user_pattern, crs_description)

    if user_match:
        # Работаем с текстом после USER:XXXXXX -
        working_text = user_match.group(1)
    else:
        # Если нет USER, работаем со всем описанием
        working_text = crs_description

    # Ищем паттерн МСК-XX или СК-XX (с возможными пробелами)
    # Поддерживаем варианты: МСК-23, МСК-1964, СК-63, СК 63
    # ВАЖНО: \d+ захватывает ВСЕ цифры до пробела/скобки/конца строки
    crs_pattern = r'(МСК|СК|MSK|SK)[\s-]?(\d+)'
    crs_match = re.search(crs_pattern, working_text, re.IGNORECASE)

    if not crs_match:
        log_info(f"crs_utils: Паттерн МСК/СК не найден в '{working_text}'")
        return None

    # Формируем базовое короткое название
    prefix = crs_match.group(1).upper()
    # Приводим к стандартному виду МСК/СК
    if prefix in ['MSK', 'МСК']:
        prefix = 'МСК'
    elif prefix in ['SK', 'СК']:
        prefix = 'СК'

    number = crs_match.group(2)
    short_name = f"{prefix}-{number}"

    # Ищем зону сразу после МСК/СК
    # Проверяем текст после найденного паттерна
    text_after = working_text[crs_match.end():]

    # Паттерн для зоны: (зона N) или (zone N)
    zone_pattern = r'^\s*\((?:зона|zone)\s+(\d+)\)'
    zone_match = re.search(zone_pattern, text_after, re.IGNORECASE)

    if zone_match:
        zone_number = zone_match.group(1)
        short_name = f"{short_name}_{zone_number}"

    log_info(f"Извлечено короткое название СК: {short_name} из '{crs_description}'")

    return short_name


def validate_crs_short_name(short_name: str) -> bool:
    """
    Проверяет корректность короткого названия СК

    Args:
        short_name: Короткое название СК

    Returns:
        bool: True если название корректно
    """
    if not short_name:
        return False

    # Паттерн для проверки: МСК-XX или СК-XX с опциональной _N для зоны
    # XX - любое количество цифр (1-4 для реальных СК)
    pattern = r'^(МСК|СК)-\d+(_\d+)?$'
    return bool(re.match(pattern, short_name))


def format_crs_short_name_for_filename(short_name: str) -> str:
    """
    Форматирует короткое название СК для использования в имени файла

    Заменяет пробелы на подчеркивания, убирает недопустимые символы

    Args:
        short_name: Короткое название СК

    Returns:
        str: Отформатированное название для файла
    """
    if not short_name:
        return ""
    
    # Заменяем пробелы на подчеркивания
    formatted = short_name.replace(' ', '_')
    
    # Убираем недопустимые символы для имени файла
    # Оставляем только буквы, цифры, дефис и подчеркивание
    formatted = re.sub(r'[^А-Яа-яA-Za-z0-9_-]', '', formatted)
    
    return formatted
