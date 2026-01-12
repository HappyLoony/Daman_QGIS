# -*- coding: utf-8 -*-
"""
Утилиты для работы с цветом

Содержит функции для конвертации AutoCAD цветов в QGIS
"""

from typing import Tuple
from qgis.PyQt.QtGui import QColor


def parse_rgb_string(rgb_string: str) -> Tuple[int, int, int]:
    """
    Парсинг строки RGB в кортеж (r, g, b)

    Args:
        rgb_string: Строка вида "255,0,128" или "-"

    Returns:
        Кортеж (r, g, b) где каждое значение 0-255

    Examples:
        >>> parse_rgb_string("255,128,0")
        (255, 128, 0)
        >>> parse_rgb_string("-")
        (0, 0, 0)
    """
    if not rgb_string or rgb_string == '-':
        return (0, 0, 0)

    try:
        parts = rgb_string.split(',')
        if len(parts) != 3:
            return (0, 0, 0)

        r = int(parts[0].strip())
        g = int(parts[1].strip())
        b = int(parts[2].strip())

        # Ограничиваем значения диапазоном 0-255
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))

        return (r, g, b)
    except (ValueError, IndexError):
        return (0, 0, 0)


def autocad_transparency_to_qgis(transparency) -> float:
    """
    Конвертация прозрачности AutoCAD в QGIS opacity

    AutoCAD: 0 = непрозрачный, 100 = полностью прозрачный
    QGIS: 0.0 = полностью прозрачный, 1.0 = непрозрачный

    Args:
        transparency: Прозрачность AutoCAD (0-100) или "-"

    Returns:
        Opacity для QGIS (0.0 - 1.0)

    Examples:
        >>> autocad_transparency_to_qgis(0)
        1.0
        >>> autocad_transparency_to_qgis(50)
        0.5
        >>> autocad_transparency_to_qgis(100)
        0.0
        >>> autocad_transparency_to_qgis("-")
        1.0
    """
    if transparency == '-' or transparency is None:
        return 1.0

    try:
        trans_value = int(transparency)
        # Ограничиваем диапазон 0-100
        trans_value = max(0, min(100, trans_value))
        return 1.0 - (trans_value / 100.0)
    except (ValueError, TypeError):
        return 1.0


def rgb_to_qcolor(rgb_string: str, transparency=0) -> QColor:
    """
    Создать QColor из строки RGB с прозрачностью

    Args:
        rgb_string: Строка RGB "R,G,B"
        transparency: Прозрачность AutoCAD (0-100)

    Returns:
        QColor с установленным цветом и прозрачностью

    Examples:
        >>> color = rgb_to_qcolor("255,0,0", 50)
        >>> color.red()
        255
        >>> color.alphaF()
        0.5
    """
    r, g, b = parse_rgb_string(rgb_string)
    color = QColor(r, g, b)
    opacity = autocad_transparency_to_qgis(transparency)
    color.setAlphaF(opacity)
    return color
