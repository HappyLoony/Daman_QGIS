# -*- coding: utf-8 -*-
"""
Утилиты для работы с системами координат
"""

import re
from typing import Dict, Optional, List

from Daman_QGIS.utils import log_info, log_warning


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


def normalize_proj4(proj4: str) -> str:
    """Нормализовать PROJ4 строку для надёжного сравнения.

    Разбивает на параметры, убирает пробелы, сортирует, склеивает.
    Гарантирует что две PROJ4 строки одной и той же CRS будут равны
    вне зависимости от порядка параметров.

    Args:
        proj4: PROJ4 строка ("+proj=tmerc +lat_0=0 +lon_0=45 ...")

    Returns:
        Нормализованная строка или '' если вход пуст.
    """
    if not proj4:
        return ''
    params = proj4.strip().split()
    params = [p.strip() for p in params if p.strip()]
    params.sort()
    return ' '.join(params)


def find_existing_user_crs(crs) -> Optional[int]:
    """Найти существующую USER CRS, эквивалентную данной, по normalized PROJ4.

    Сканирует registry.userCrsList() и сравнивает .crs.toProj()
    через normalize_proj4().

    Args:
        crs: QgsCoordinateReferenceSystem для поиска.

    Returns:
        srsid (int) совпавшей USER CRS, или None если не найдена.
    """
    from qgis.core import QgsApplication

    target_proj = normalize_proj4(crs.toProj())
    if not target_proj:
        return None

    try:
        registry = QgsApplication.coordinateReferenceSystemRegistry()
        for user_crs_details in registry.userCrsList():
            existing_proj = normalize_proj4(user_crs_details.crs.toProj())
            if existing_proj == target_proj:
                return user_crs_details.id
    except Exception:
        pass

    return None


def find_existing_user_crs_by_name(name: str) -> Optional[int]:
    """Найти существующую USER CRS по точному совпадению имени.

    Используется для кастомных CRS (с префиксом '_'), где имя привязано
    к проекту и является основным идентификатором.
    PROJ4-based поиск (find_existing_user_crs) не подходит, т.к. может
    вернуть reference CRS с совпадающими параметрами, которая будет
    удалена при синхронизации профиля.

    Args:
        name: Имя CRS для поиска (например, '_Эльбрус_МСК-07 КБР').

    Returns:
        srsid (int) совпавшей USER CRS, или None если не найдена.
    """
    if not name:
        return None

    from qgis.core import QgsApplication

    try:
        registry = QgsApplication.coordinateReferenceSystemRegistry()
        for user_crs_details in registry.userCrsList():
            if user_crs_details.name.strip() == name.strip():
                return user_crs_details.id
    except Exception:
        pass

    return None


def is_custom_crs(name: str) -> bool:
    """Проверить является ли CRS кастомной (проектной).

    Конвенция: кастомные CRS начинаются с '_'.
    Reference CRS (из qgis.db профиля) начинаются без '_'.

    Args:
        name: Имя CRS (details.name).

    Returns:
        True если кастомная (проектная), False если reference.
    """
    return bool(name and name.startswith('_'))


def deduplicate_by_name() -> List[int]:
    """Удалить дубли USER CRS по точному совпадению имени.

    При совпадении имени оставляет первую запись, удаляет остальные.

    Returns:
        Список удалённых srsid.
    """
    from qgis.core import QgsApplication

    removed: List[int] = []
    try:
        registry = QgsApplication.coordinateReferenceSystemRegistry()
        seen_names: dict = {}

        for details in list(registry.userCrsList()):
            name = details.name.strip()
            if not name:
                continue
            if name in seen_names:
                log_info(
                    f"crs_utils: Дубль удален: USER:{details.id} '{name}' "
                    f"(оставлен USER:{seen_names[name]})"
                )
                registry.removeUserCrs(details.id)
                removed.append(details.id)
            else:
                seen_names[name] = details.id
    except Exception as e:
        log_warning(f"crs_utils (deduplicate_by_name): {e}")

    return removed


def cleanup_user_crs() -> Dict[str, int]:
    """Очистка USER CRS реестра.

    Порядок операций:
    1. Дедупликация по имени (deduplicate_by_name)
    2. Лог состояния: сколько custom ('_'), сколько reference

    Reference CRS (без '_') управляются через qgis.db профиля.
    Замена qgis.db при обновлении профиля (M_37) -- основной
    механизм синхронизации reference CRS.

    Returns:
        Словарь со статистикой: {duplicates_removed, custom, reference, total}.
    """
    from qgis.core import QgsApplication

    stats: Dict[str, int] = {
        'duplicates_removed': 0,
        'custom': 0,
        'reference': 0,
        'total': 0,
    }

    # 1. Дедупликация
    removed = deduplicate_by_name()
    stats['duplicates_removed'] = len(removed)
    if removed:
        log_info(
            f"crs_utils: Дедупликация -- удалено {len(removed)} дублей"
        )

    # 2. Лог состояния реестра
    try:
        registry = QgsApplication.coordinateReferenceSystemRegistry()
        all_user_crs = list(registry.userCrsList())
        stats['total'] = len(all_user_crs)

        for details in all_user_crs:
            name = details.name.strip()
            if not name:
                continue
            if is_custom_crs(name):
                stats['custom'] += 1
            else:
                stats['reference'] += 1

    except Exception as e:
        log_warning(f"crs_utils (cleanup_user_crs): {e}")

    log_info(
        f"crs_utils: cleanup_user_crs -- итого: "
        f"total={stats['total']}, "
        f"custom('_')={stats['custom']}, "
        f"reference={stats['reference']}, "
        f"дублей удалено={stats['duplicates_removed']}"
    )

    return stats
