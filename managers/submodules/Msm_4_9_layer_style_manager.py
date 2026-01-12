# -*- coding: utf-8 -*-
"""
Менеджер стилей слоев (MapInfo и AutoCAD).

Отвечает за:
- Парсинг стилей MapInfo (Pen, Brush, Symbol)
- Получение стилей для слоев
- Конвертацию цветов MapInfo в RGB
- Словари стилей линий и заливок
"""

import re
import json
from typing import Dict, Optional, Tuple
from Daman_QGIS.managers.submodules.Msm_4_6_layer_reference_manager import LayerReferenceManager


class LayerStyleManager:
    """Менеджер для работы со стилями слоев MapInfo и AutoCAD"""

    def __init__(self, reference_dir: str, layer_manager: LayerReferenceManager):
        """
        Инициализация менеджера стилей

        Args:
            reference_dir: Путь к директории со справочными данными (не используется напрямую)
            layer_manager: Экземпляр LayerReferenceManager для получения данных слоев
        """
        self.reference_dir = reference_dir
        self.layer_manager = layer_manager

    def parse_mapinfo_style(self, style_string: str) -> Optional[Dict]:
        """
        Парсинг строки стиля MapInfo

        Поддерживаемые форматы:
        - Pen(width, pattern, color) - стиль линии
        - Brush(pattern, forecolor, backcolor) - стиль заливки
        - Symbol(shape, color, size) - стиль символа

        Args:
            style_string: Строка вида "Brush(1, 0, 16777215) Pen(5, 5, 7864440)"

        Returns:
            Словарь с распарсенными компонентами стиля:
            {
                'pen': {'width': int, 'pattern': int, 'color': int},
                'brush': {'pattern': int, 'forecolor': int, 'backcolor': int},
                'symbol': {'shape': int, 'color': int, 'size': int}
            }
            Или None если строка пустая
        """
        if not style_string:
            return None

        result = {}

        # Парсинг Pen(width, pattern, color)
        pen_match = re.search(r'Pen\s*\((\d+),\s*(\d+),\s*(\d+)\)', style_string)
        if pen_match:
            result['pen'] = {
                'width': int(pen_match.group(1)),
                'pattern': int(pen_match.group(2)),
                'color': int(pen_match.group(3))
            }

        # Парсинг Brush(pattern, forecolor, backcolor)
        brush_match = re.search(r'Brush\s*\((\d+),\s*(\d+),\s*(-?\d+)\)', style_string)
        if brush_match:
            result['brush'] = {
                'pattern': int(brush_match.group(1)),
                'forecolor': int(brush_match.group(2)),
                'backcolor': int(brush_match.group(3))
            }

        # Парсинг Symbol(shape, color, size)
        symbol_match = re.search(r'Symbol\s*\((\d+),\s*(\d+),\s*(\d+)\)', style_string)
        if symbol_match:
            result['symbol'] = {
                'shape': int(symbol_match.group(1)),
                'color': int(symbol_match.group(2)),
                'size': int(symbol_match.group(3))
            }

        return result if result else None

    def get_layer_style(self, full_name: str) -> Optional[Dict]:
        """
        Получить распарсенный стиль слоя

        Args:
            full_name: Полное имя слоя (например "3_3_1_ГПМТ")

        Returns:
            Словарь с распарсенным стилем или None
        """
        layer = self.layer_manager.get_layer_by_full_name(full_name)
        if layer and layer.get('style'):
            return self.parse_mapinfo_style(layer['style'])
        return None

    def get_layer_autocad_style(self, full_name: str) -> Optional[Dict]:
        """
        Получить стиль AutoCAD для слоя из Base_layers.json

        Поддерживает две структуры:
        - НОВАЯ (приоритет): line_color_RGB, line_global_weight, line_transparency, hatch_color_RGB, hatch_global_lineweight, hatch_transparency
        - СТАРАЯ (fallback): color_RGB, global_weight, transparency, outline_color_RGB, outline_global_lineweight

        Args:
            full_name: Полное имя слоя (например "L_1_1_1_Границы_работ")

        Returns:
            Словарь со стилем AutoCAD (унифицированный формат с новыми полями):
            {
                'layer_name_autocad': str,
                'geometry_type': str,  # "MultiPoint", "Polygon", "LineString" и т.д.
                'linetype': str,
                'line_color_RGB': str,  # "255,0,0"
                'line_global_weight': float,  # Толщина линии (для точек: толщина окружности)
                'line_transparency': int,
                'line_scale': float,  # Для линий: ltscale, для точек: диаметр круга
                'hatch': str,  # "SOLID"/"ANSI31"/"HEX"/"-"
                'hatch_scale': float,
                'hatch_angle': int,
                'hatch_color_RGB': str,  # "R,G,B"/"-"
                'hatch_global_lineweight': float,
                'hatch_transparency': str,  # int или "-"
                'not_print': str  # "1"/"0"/"-"
            }
            Или None если слой не найден
        """
        layer = self.layer_manager.get_layer_by_full_name(full_name)
        if not layer:
            return None

        # Читаем из новых полей с fallback на старые
        # ВАЖНО: используем 'is not None' вместо 'or', чтобы корректно обработать 0
        line_color_RGB = layer.get('line_color_RGB') if layer.get('line_color_RGB') is not None else layer.get('color_RGB', '255,255,255')
        line_global_weight = layer.get('line_global_weight') if layer.get('line_global_weight') is not None else layer.get('global_weight', 1)
        line_transparency = layer.get('line_transparency') if layer.get('line_transparency') is not None else layer.get('transparency', 0)

        # Аналогично для hatch - защита от нулевых значений
        hatch_color_RGB = layer.get('hatch_color_RGB') if layer.get('hatch_color_RGB') is not None else layer.get('color_RGB', '255,255,255')
        hatch_global_lineweight = layer.get('hatch_global_lineweight') if layer.get('hatch_global_lineweight') is not None else 0.7
        hatch_transparency = layer.get('hatch_transparency', '-')

        return {
            'layer_name_autocad': layer.get('layer_name_autocad', 'ИМЯ НЕ ЗАДАНО'),
            'geometry_type': layer.get('geometry_type', ''),  # MultiPoint, Polygon, LineString и т.д.
            'linetype': layer.get('linetype', 'CONTINUOUS'),
            'line_color_RGB': line_color_RGB,
            'line_global_weight': self._parse_float(line_global_weight, default=1.0),
            'line_transparency': self._parse_int(line_transparency, default=0),
            # line_scale: для линий = масштаб типа линии (ltscale), для точек = диаметр круга
            'line_scale': self._parse_float(layer.get('line_scale', 1), default=1.0),
            'hatch': layer.get('hatch', '-'),
            'hatch_scale': self._parse_float(layer.get('hatch_scale', '-'), default=1.0),
            'hatch_angle': self._parse_int(layer.get('hatch_angle', '-'), default=0),
            'hatch_color_RGB': hatch_color_RGB,
            'hatch_global_lineweight': self._parse_float(hatch_global_lineweight, default=0.7),
            'hatch_transparency': hatch_transparency,
            'not_print': layer.get('not_print', '-')
        }

    def convert_mapinfo_color(self, mapinfo_color: int) -> Tuple[int, int, int]:
        """
        Конвертация цвета MapInfo в RGB

        MapInfo хранит цвет как 24-битное целое число в формате BGR.
        -1 означает прозрачный цвет (возвращается как черный).

        Args:
            mapinfo_color: Цвет в формате MapInfo (24-bit integer)

        Returns:
            Кортеж (R, G, B) со значениями 0-255
        """
        if mapinfo_color == -1:
            # -1 означает прозрачный цвет
            return (0, 0, 0)

        # MapInfo хранит цвет в формате BGR (Blue-Green-Red) - 24-битное число
        # Младшие 8 бит = Blue, средние 8 бит = Green, старшие 8 бит = Red
        # Извлекаем компоненты BGR и возвращаем в порядке RGB
        b = mapinfo_color & 0xFF          # Младшие биты (0-7)
        g = (mapinfo_color >> 8) & 0xFF   # Средние биты (8-15)
        r = (mapinfo_color >> 16) & 0xFF  # Старшие биты (16-23)
        return (r, g, b)

    def get_mapinfo_pen_style_name(self, pattern: int) -> str:
        """
        Получить название типа линии по коду MapInfo

        Стандартные коды MapInfo для типов линий (1-118):
        1 - Невидимая
        2 - Сплошная
        3 - Точечная
        4 - Пунктирная
        5 - Штриховая
        6 - Штрихпунктирная
        7+ - Различные специальные стили

        Args:
            pattern: Код типа линии MapInfo (1-118)

        Returns:
            Название типа линии
        """
        pen_patterns = {
            1: 'Невидимая',
            2: 'Сплошная',
            3: 'Точечная',
            4: 'Пунктирная',
            5: 'Штриховая',
            6: 'Штрихпунктирная'
        }
        return pen_patterns.get(pattern, f'Стиль_{pattern}')

    def get_mapinfo_brush_style_name(self, pattern: int) -> str:
        """
        Получить название типа заливки по коду MapInfo

        Стандартные коды MapInfo для типов заливок (1-71):
        1 - Без заливки
        2 - Сплошная
        3-8 - Штриховки различных направлений
        12-14 - Точечные заливки
        15+ - Специальные узоры

        Args:
            pattern: Код типа заливки MapInfo (1-71)

        Returns:
            Название типа заливки
        """
        brush_patterns = {
            1: 'Без заливки',
            2: 'Сплошная',
            3: 'Вертикальная штриховка',
            4: 'Горизонтальная штриховка',
            5: 'Диагональ вправо',
            6: 'Диагональ влево',
            7: 'Крест',
            8: 'Плотная сетка',
            12: 'Редкие точки',
            13: 'Средние точки',
            14: 'Плотные точки',
            15: 'Специальный узор'
        }
        return brush_patterns.get(pattern, f'Узор_{pattern}')

    def get_layer_opacity(self, full_name: str) -> Optional[int]:
        """
        Получить значение прозрачности слоя из Base_layers.json

        Args:
            full_name: Полное имя слоя (например "L_1_1_2_Границы_работ_10_м")

        Returns:
            Значение opacity (0-100) или None если не задано
            0 = непрозрачный, 100 = полностью прозрачный
        """
        layer = self.layer_manager.get_layer_by_full_name(full_name)
        if not layer:
            return None

        opacity = layer.get('opacity')
        if not opacity or opacity == '-':
            return None

        # Конвертация в int с валидацией
        try:
            opacity_value = int(opacity)
            if 0 <= opacity_value <= 100:
                return opacity_value
        except (ValueError, TypeError):
            pass

        return None

    def parse_rgb_string(self, rgb_str: str) -> Tuple[int, int, int]:
        """
        Парсинг RGB строки "255,0,0" в кортеж (255, 0, 0)

        Обрабатывает "-" как белый цвет (255,255,255)

        Args:
            rgb_str: Строка формата "R,G,B" или "-"

        Returns:
            Кортеж (R, G, B) со значениями 0-255

        Example:
            >>> parse_rgb_string("255,0,0")
            (255, 0, 0)
            >>> parse_rgb_string("-")
            (255, 255, 255)
        """
        if not rgb_str or rgb_str == '-':
            return (255, 255, 255)  # Белый по умолчанию

        try:
            parts = [int(x.strip()) for x in rgb_str.split(',')]
            if len(parts) != 3:
                raise ValueError(f"Expected 3 values, got {len(parts)}")
            if not all(0 <= x <= 255 for x in parts):
                raise ValueError("RGB values must be 0-255")
            return (parts[0], parts[1], parts[2])
        except (ValueError, AttributeError) as e:
            from Daman_QGIS.utils import log_warning
            log_warning(f"Msm_4_9: Invalid RGB format '{rgb_str}': {e}, using white")
            return (255, 255, 255)

    def _parse_int(self, value, default=0) -> int:
        """
        Безопасный парсинг int с обработкой '-'

        Args:
            value: Значение для парсинга
            default: Значение по умолчанию

        Returns:
            Целое число или default

        Example:
            >>> _parse_int("10")
            10
            >>> _parse_int("-", default=5)
            5
            >>> _parse_int(None, default=0)
            0
        """
        if value == '-' or value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    def _parse_float(self, value, default=1.0) -> float:
        """
        Безопасный парсинг float с обработкой '-'

        Args:
            value: Значение для парсинга
            default: Значение по умолчанию

        Returns:
            Вещественное число или default

        Example:
            >>> _parse_float("1.5")
            1.5
            >>> _parse_float("-", default=2.0)
            2.0
            >>> _parse_float(None, default=1.0)
            1.0
        """
        if value == '-' or value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
