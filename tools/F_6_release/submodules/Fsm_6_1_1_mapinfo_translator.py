# -*- coding: utf-8 -*-
"""
Субмодуль 6_1_1: Транслятор MapInfo стилей в OGR StyleString

Назначение:
    Сохранение кода конвертации MapInfo стилей из style_manager.py.
    Этот код будет использоваться только для экспорта TAB файлов после того,
    как основная система стилей будет переработана на AutoCAD.

Описание:
    Конвертирует MapInfo стили из Base_layers.json в формат OGR StyleString
    для применения к TAB файлам через ogr_feature.SetStyleString().

Методы:
    - parse_mapinfo_style(): Парсинг строки "Brush(...) Pen(...)"
    - convert_mapinfo_color(): Конвертация MapInfo цветового кода в RGB
    - convert_to_ogr_style(): Конвертация в OGR StyleString
    - get_style_for_layer(): Получение стиля из Base_layers.json
"""

from typing import Dict, Any, Optional, Tuple

from Daman_QGIS.managers import get_reference_managers
from Daman_QGIS.utils import log_warning, log_info


class Fsm_6_1_1_MapInfoTranslator:
    """Транслятор MapInfo стилей в формат OGR StyleString для TAB экспорта"""

    def __init__(self):
        """Инициализация транслятора с доступом к справочным данным"""
        self.ref_managers = get_reference_managers()

    def parse_mapinfo_style(self, style_string: str) -> Optional[Dict[str, Any]]:
        """
        Парсинг строки MapInfo стиля

        Использует существующий парсер из reference_manager.layer_style.
        Это сохранение кода из style_manager.py для будущего использования
        только в экспорте TAB.

        Args:
            style_string: Строка вида "Brush(2, 16777215, 16432316) Pen(2, 2, 0)"

        Returns:
            Словарь с ключами 'brush' и 'pen', или None при ошибке

        Example:
            >>> translator = Fsm_6_1_1_MapInfoTranslator()
            >>> style = "Brush(2, 16777215, 16432316) Pen(2, 2, 0)"
            >>> parsed = translator.parse_mapinfo_style(style)
            >>> print(parsed)
            {
                'brush': {'pattern': 2, 'forecolor': 16777215, 'backcolor': 16432316},
                'pen': {'width': 2, 'pattern': 2, 'color': 0}
            }
        """
        try:
            # Используем существующий парсер из reference_manager
            return self.ref_managers.layer_style.parse_mapinfo_style(style_string)
        except Exception as e:
            log_warning(f"Fsm_6_1_1: Ошибка парсинга MapInfo стиля '{style_string}': {str(e)}")
            return None

    def convert_mapinfo_color(self, color_code: int) -> Tuple[int, int, int]:
        """
        Конвертация MapInfo цветового кода в RGB

        Использует существующий конвертер из reference_manager.
        MapInfo хранит цвета как BGR (Blue-Green-Red) в формате 0xBBGGRR.

        Args:
            color_code: Числовой код цвета MapInfo (например, 16777215 для белого)

        Returns:
            Кортеж (R, G, B) в диапазоне 0-255

        Example:
            >>> translator = Fsm_6_1_1_MapInfoTranslator()
            >>> r, g, b = translator.convert_mapinfo_color(16777215)
            >>> print(f"RGB: {r}, {g}, {b}")
            RGB: 255, 255, 255
        """
        return self.ref_managers.layer_style.convert_mapinfo_color(color_code)

    def convert_to_ogr_style(self,
                            parsed_style: Dict[str, Any],
                            geom_type: str) -> str:
        """
        Конвертация распарсенного MapInfo стиля в OGR StyleString

        OGR StyleString - это текстовый формат для описания стилей,
        используемый GDAL/OGR для применения стилей к векторным данным.

        Форматы OGR StyleString:
            - Полигон: "BRUSH(fc:#RRGGBB,bc:#RRGGBB,id:pattern);PEN(c:#RRGGBB,w:Npx,p:pattern)"
            - Линия: "PEN(c:#RRGGBB,w:Npx,p:pattern)"
            - Точка: "SYMBOL(c:#RRGGBB,s:Npx,id:symbolname)"

        Args:
            parsed_style: Результат parse_mapinfo_style() с ключами 'brush' и 'pen'
            geom_type: Тип геометрии ('Polygon', 'LineString', 'Point')

        Returns:
            Строка OGR StyleString для ogr_feature.SetStyleString()

        Example:
            >>> translator = Fsm_6_1_1_MapInfoTranslator()
            >>> parsed = {
            ...     'brush': {'pattern': 2, 'forecolor': 16777215, 'backcolor': 16432316},
            ...     'pen': {'width': 2, 'pattern': 2, 'color': 0}
            ... }
            >>> style = translator.convert_to_ogr_style(parsed, 'Polygon')
            >>> print(style)
            BRUSH(fc:#FABFAC);PEN(c:#000000,w:2px,p:2)
        """
        style_parts = []

        # Обработка заливки для полигонов
        if geom_type == 'Polygon' and 'brush' in parsed_style:
            brush = parsed_style['brush']
            pattern = brush['pattern']

            if pattern == 1:
                # Без заливки - используем прозрачный цвет
                style_parts.append("BRUSH(fc:#00000000)")

            elif pattern == 2:
                # Сплошная заливка - используем backcolor
                # (в MapInfo для pattern=2 backcolor используется для заливки)
                r, g, b = self.convert_mapinfo_color(brush['backcolor'])
                fc = f"#{r:02X}{g:02X}{b:02X}"
                style_parts.append(f"BRUSH(fc:{fc})")

            elif pattern == 6:
                # Диагональная штриховка - используем forecolor для линий
                r, g, b = self.convert_mapinfo_color(brush['forecolor'])
                fc = f"#{r:02X}{g:02X}{b:02X}"
                # id:6 - диагональная штриховка в OGR
                style_parts.append(f"BRUSH(fc:{fc},id:diagcross)")

            else:
                # Другие паттерны - используем forecolor как основной цвет
                r, g, b = self.convert_mapinfo_color(brush['forecolor'])
                fc = f"#{r:02X}{g:02X}{b:02X}"
                style_parts.append(f"BRUSH(fc:{fc},id:{pattern})")

        # Обработка контура (для всех типов геометрии)
        if 'pen' in parsed_style:
            pen = parsed_style['pen']
            pen_pattern = pen['pattern']

            # pattern=1 означает невидимую линию - не добавляем PEN
            if pen_pattern != 1:
                r, g, b = self.convert_mapinfo_color(pen['color'])
                c = f"#{r:02X}{g:02X}{b:02X}"
                w = pen['width']
                p = pen_pattern

                # Формат: PEN(c:color, w:width, p:pattern)
                style_parts.append(f"PEN(c:{c},w:{w}px,p:{p})")

        # Обработка точечных символов
        if geom_type == 'Point':
            # Для точек используем SYMBOL вместо BRUSH/PEN
            # TODO: Реализовать полную поддержку MapInfo символов
            if 'pen' in parsed_style:
                pen = parsed_style['pen']
                r, g, b = self.convert_mapinfo_color(pen['color'])
                c = f"#{r:02X}{g:02X}{b:02X}"
                size = pen.get('width', 5)
                style_parts = [f"SYMBOL(c:{c},s:{size}px,id:circle)"]

        return ";".join(style_parts)

    def get_style_for_layer(self, layer_name: str) -> Optional[str]:
        """
        Получение MapInfo стиля из Base_layers.json для слоя

        ЗАГЛУШКА: В настоящее время читает из колонки style_MapInfo (fields 12-13).
        В будущем, когда будет добавлена отдельная колонка для TAB стилей,
        этот метод нужно будет обновить.

        TODO: После добавления новой колонки стилей в Base_layers.json
              обновить этот метод для чтения из нее.

        Args:
            layer_name: Полное имя слоя в формате L_X_Y_Z_Название
                       (например, "L_1_1_1_Границы_работ")

        Returns:
            Строка MapInfo стиля ("Brush(...) Pen(...)") или None если не найдено

        Example:
            >>> translator = Fsm_6_1_1_MapInfoTranslator()
            >>> style = translator.get_style_for_layer("L_1_1_1_Границы_работ")
            >>> print(style)
            Brush(1, 16777215, 16777215) Pen(2, 2, 0)
        """
        # Получаем информацию о слое из Base_layers.json
        layer_info = self.ref_managers.layer.get_layer_by_full_name(layer_name)

        if not layer_info:
            log_warning(f"Fsm_6_1_1: Слой {layer_name} не найден в Base_layers.json")
            return None

        # TODO: Заменить на чтение из новой колонки когда она будет добавлена
        # Пример будущего кода:
        # style = layer_info.get('style_TAB')  # Новая колонка
        # if style and style != '-':
        #     return style

        # Сейчас используем существующую колонку style_MapInfo
        style = layer_info.get('style_MapInfo')

        if style and style != '-':
            log_info(f"Fsm_6_1_1: Получен стиль MapInfo для слоя {layer_name}: {style}")
            return style

        log_warning(f"Fsm_6_1_1: Стиль MapInfo не задан для слоя {layer_name}")
        return None

    def get_all_layers_with_styles(self) -> Dict[str, str]:
        """
        Получение всех слоев из Base_layers.json с их MapInfo стилями

        Полезно для пакетного экспорта всех слоев проекта.

        Returns:
            Словарь {layer_name: mapinfo_style_string}

        Example:
            >>> translator = Fsm_6_1_1_MapInfoTranslator()
            >>> layers = translator.get_all_layers_with_styles()
            >>> for name, style in layers.items():
            ...     print(f"{name}: {style}")
            L_1_1_1_Границы_работ: Brush(1, 16777215, 16777215) Pen(2, 2, 0)
            L_1_2_1_WFS_ЗУ: Brush(2, 16777215, 16432316) Pen(2, 2, 0)
            ...
        """
        result = {}

        # Получаем все слои из Base_layers.json
        all_layers = self.ref_managers.layer.get_all_layers()

        for layer_info in all_layers:
            layer_name = layer_info.get('full_name')
            style = layer_info.get('style_MapInfo')

            if layer_name and style and style != '-':
                result[layer_name] = style

        log_info(f"Fsm_6_1_1: Найдено {len(result)} слоев с MapInfo стилями")
        return result
