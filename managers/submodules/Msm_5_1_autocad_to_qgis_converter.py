# -*- coding: utf-8 -*-
"""
Конвертер AutoCAD стилей в QGIS символы

Преобразует параметры AutoCAD (из Base_layers.json) в QGIS символы
для визуализации слоев в QGIS
"""

from typing import Dict, Any
from qgis.core import (
    QgsVectorLayer, QgsMarkerSymbol, QgsLineSymbol, QgsFillSymbol,
    QgsSimpleLineSymbolLayer, QgsSimpleFillSymbolLayer, QgsSimpleMarkerSymbolLayer,
    QgsSingleSymbolRenderer, QgsLinePatternFillSymbolLayer, QgsUnitTypes
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from Daman_QGIS.constants import ANSI_HATCH_SPACING
from .Msm_5_2_color_utils import parse_rgb_string, autocad_transparency_to_qgis


class AutoCADToQGISConverter:
    """
    Конвертер AutoCAD параметров в QGIS символы

    Поддерживает конвертацию:
    - Point геометрии → QgsMarkerSymbol
    - Line геометрии → QgsLineSymbol
    - Polygon геометрии → QgsFillSymbol (SOLID/ANSI/без заливки)
    """

    def __init__(self):
        """Инициализация конвертера"""
        # Lazy import для избежания циклической зависимости
        from Daman_QGIS.managers.M_4_reference_manager import get_reference_managers
        self.ref_managers = get_reference_managers()

    def convert_point(self, style: Dict[str, Any]) -> QgsMarkerSymbol:
        """
        Создать QgsMarkerSymbol из AutoCAD параметров точки

        Параметры из Base_layers.json (для geometry_type=MultiPoint):
        - line_color_RGB -> цвет окружности
        - line_global_weight -> толщина линии окружности (мм)
        - line_scale -> диаметр окружности (мм), например 1.5
        - line_transparency -> прозрачность
        - hatch -> "-" (без заливки) или "SOLID" (с заливкой)
        - hatch_color_RGB -> цвет заливки (если hatch="SOLID")

        Args:
            style: Словарь AutoCAD стиля

        Returns:
            QgsMarkerSymbol настроенный как окружность
        """
        symbol = QgsMarkerSymbol.createSimple({})
        marker_layer = symbol.symbolLayer(0)

        # Форма маркера - КРУГ
        if isinstance(marker_layer, QgsSimpleMarkerSymbolLayer):
            marker_layer.setShape(QgsSimpleMarkerSymbolLayer.Circle)

        # Цвет контура (line_color_RGB)
        r, g, b = parse_rgb_string(style['line_color_RGB'])
        stroke_color = QColor(r, g, b)

        # Прозрачность контура
        opacity = autocad_transparency_to_qgis(style['line_transparency'])
        stroke_color.setAlphaF(opacity)

        marker_layer.setStrokeColor(stroke_color)

        # Толщина линии окружности (line_global_weight)
        stroke_width = float(style.get('line_global_weight', 0))
        marker_layer.setStrokeWidth(stroke_width)
        marker_layer.setStrokeWidthUnit(QgsUnitTypes.RenderMillimeters)

        # Диаметр окружности (line_scale)
        diameter = float(style.get('line_scale', 1.5))
        marker_layer.setSize(diameter)
        marker_layer.setSizeUnit(QgsUnitTypes.RenderMillimeters)

        # Заливка: hatch="-" -> без заливки, hatch="SOLID" -> заливка hatch_color_RGB
        hatch = style.get('hatch', '-')
        if hatch == 'SOLID':
            # Заливка цветом hatch_color_RGB
            hr, hg, hb = parse_rgb_string(style.get('hatch_color_RGB', '0,0,0'))
            fill_color = QColor(hr, hg, hb)
            hatch_opacity = autocad_transparency_to_qgis(style.get('hatch_transparency', 0))
            fill_color.setAlphaF(hatch_opacity)
            marker_layer.setFillColor(fill_color)
        else:
            # Без заливки - прозрачный
            marker_layer.setFillColor(QColor(0, 0, 0, 0))

        return symbol

    def convert_line(self, style: Dict[str, Any]) -> QgsLineSymbol:
        """
        Создать QgsLineSymbol из AutoCAD параметров линии

        Параметры из Base_layers.json:
        - line_color_RGB → line color
        - line_global_weight → line width (мм)
        - linetype → Qt.PenStyle
        - line_transparency → opacity

        Args:
            style: Словарь AutoCAD стиля

        Returns:
            QgsLineSymbol настроенный для линии
        """
        symbol = QgsLineSymbol.createSimple({})
        line_layer = QgsSimpleLineSymbolLayer()

        # Цвет линии
        r, g, b = parse_rgb_string(style['line_color_RGB'])
        color = QColor(r, g, b)

        # Прозрачность
        opacity = autocad_transparency_to_qgis(style['line_transparency'])
        color.setAlphaF(opacity)

        line_layer.setColor(color)

        # Толщина линии (line_global_weight уже в миллиметрах)
        width_mm = float(style['line_global_weight'])
        line_layer.setWidth(width_mm)
        line_layer.setWidthUnit(QgsUnitTypes.RenderMillimeters)

        # Тип линии
        pen_style = self._linetype_to_pen_style(style['linetype'])
        line_layer.setPenStyle(pen_style)

        # Применяем
        symbol.deleteSymbolLayer(0)
        symbol.appendSymbolLayer(line_layer)

        return symbol

    def convert_polygon(self, style: Dict[str, Any]) -> QgsFillSymbol:
        """
        Создать QgsFillSymbol из AutoCAD параметров полигона

        Логика определения типа заливки (из Base_layers.json):

        1. hatch == "SOLID":
           - Сплошная заливка hatch_color_RGB
           - Контур: line_color_RGB, line_global_weight

        2. hatch == "ANSI37":
           - ДВА слоя QgsLinePatternFillSymbolLayer (углы 45° и 135° + hatch_angle)
           - Используется для сложных кросс-хэтч паттернов

        3. hatch == "ANSI32":
           - ДВА слоя QgsLinePatternFillSymbolLayer (оба угол 45° с разным offset)
           - Steel pattern из AutoCAD

        4. hatch == "ANSI31"/другие одинарные ANSI:
           - ОДИН слой QgsLinePatternFillSymbolLayer (штриховка)
           - Цвет штриховки: hatch_color_RGB
           - Линии штриховки: hatch_global_lineweight
           - Контур: line_color_RGB, line_global_weight

        5. hatch == "-":
           - Без заливки (Qt.NoBrush)
           - Только контур: line_color_RGB, line_global_weight

        Args:
            style: Словарь AutoCAD стиля

        Returns:
            QgsFillSymbol настроенный для полигона
        """
        hatch = style['hatch']

        if hatch == 'SOLID':
            # Сплошная заливка
            fill_layer = QgsSimpleFillSymbolLayer()

            # Цвет заливки
            r, g, b = parse_rgb_string(style['hatch_color_RGB'])
            fill_color = QColor(r, g, b)

            # Прозрачность заливки
            opacity = autocad_transparency_to_qgis(style['hatch_transparency'])
            fill_color.setAlphaF(opacity)

            fill_layer.setFillColor(fill_color)
            fill_layer.setBrushStyle(Qt.SolidPattern)

            # Контур
            self._apply_outline(fill_layer, style)

            # Создаем символ
            symbol = QgsFillSymbol()
            symbol.changeSymbolLayer(0, fill_layer)

        elif hatch != '-' and hatch.startswith('ANSI'):
            # Создаем символ
            symbol = QgsFillSymbol()

            if hatch == 'ANSI37':
                # ANSI37 - два слоя штриховки с базовыми углами 45° и 135° + hatch_angle, контур сверху

                # ВАЖНО: для ANSI37 hatch_angle - это ДОБАВКА к базовым углам (не полное значение)
                # Получаем hatch_angle из стиля (целое число 0-360)
                # Если отсутствует или "-", используем 0 (базовые углы без изменений)
                hatch_angle_offset = 0
                if 'hatch_angle' in style:
                    hatch_angle_value = style['hatch_angle']
                    if isinstance(hatch_angle_value, (int, float)):
                        hatch_angle_offset = int(hatch_angle_value)
                    elif isinstance(hatch_angle_value, str) and hatch_angle_value != '-':
                        try:
                            hatch_angle_offset = int(hatch_angle_value)
                        except ValueError:
                            hatch_angle_offset = 0

                # Базовые углы для ANSI37: 45° и 135°
                base_angle_1 = 45
                base_angle_2 = 135

                # Применяем hatch_angle как ДОБАВКУ к базовым углам
                final_angle_1 = base_angle_1 + hatch_angle_offset  # 45° + offset
                final_angle_2 = base_angle_2 + hatch_angle_offset  # 135° + offset

                hatch_layer_1 = self._create_hatch_layer_fixed_angle(
                    final_angle_1,  # 45° + hatch_angle
                    ANSI_HATCH_SPACING,  # spacing для ANSI37
                    style['hatch_color_RGB'],
                    style['hatch_transparency'],
                    style['hatch_scale'],
                    style['hatch_global_lineweight']
                )

                hatch_layer_2 = self._create_hatch_layer_fixed_angle(
                    final_angle_2,  # 135° + hatch_angle
                    ANSI_HATCH_SPACING,  # spacing для ANSI37
                    style['hatch_color_RGB'],
                    style['hatch_transparency'],
                    style['hatch_scale'],
                    style['hatch_global_lineweight']
                )

                # Добавляем оба слоя штриховки
                symbol.changeSymbolLayer(0, hatch_layer_1)
                symbol.appendSymbolLayer(hatch_layer_2)

            elif hatch == 'ANSI32':
                # ANSI32 - два слоя штриховки с разным offset (Steel pattern)
                # Определение из AutoCAD acad.pat:
                # *ANSI32, ANSI Steel
                # 45, 0,0, 0,.375
                # 45, .176776695,0, 0,.375

                # Базовый угол для обоих слоев
                base_angle = 45

                # ВАЖНО: для ANSI32 hatch_angle - это ПОЛНОЦЕННОЕ значение угла (не добавка)
                # Если hatch_angle задан, используем его ВМЕСТО базового
                hatch_angle_value = style.get('hatch_angle', 0)
                if isinstance(hatch_angle_value, str):
                    try:
                        hatch_angle_value = int(hatch_angle_value) if hatch_angle_value != '-' else 0
                    except ValueError:
                        hatch_angle_value = 0

                # Определяем финальный угол
                if hatch_angle_value and hatch_angle_value != 0:
                    final_angle = hatch_angle_value
                else:
                    final_angle = base_angle

                # Offset для второго слоя (из AutoCAD pattern definition)
                ansi32_offset = 0.176776695

                # Первый слой: угол = hatch_angle (или 45° по умолчанию), без offset
                hatch_layer_1 = self._create_hatch_layer_fixed_angle(
                    final_angle,
                    ANSI_HATCH_SPACING,  # spacing для ANSI32
                    style['hatch_color_RGB'],
                    style['hatch_transparency'],
                    style['hatch_scale'],
                    style['hatch_global_lineweight'],
                    offset=0.0  # Без смещения
                )

                # Второй слой: тот же угол, с offset
                hatch_layer_2 = self._create_hatch_layer_fixed_angle(
                    final_angle,
                    ANSI_HATCH_SPACING,  # spacing для ANSI32
                    style['hatch_color_RGB'],
                    style['hatch_transparency'],
                    style['hatch_scale'],
                    style['hatch_global_lineweight'],
                    offset=ansi32_offset  # Смещение для создания "steel" эффекта
                )

                # Добавляем оба слоя штриховки
                symbol.changeSymbolLayer(0, hatch_layer_1)
                symbol.appendSymbolLayer(hatch_layer_2)

            else:
                # Остальные ANSI штриховки (ANSI31, ANSI35, ANSI36, ANSI38, etc.)
                hatch_layer = self._create_hatch_layer(
                    hatch,
                    style['hatch_color_RGB'],
                    style['hatch_transparency'],
                    style['hatch_angle'],
                    style['hatch_scale'],
                    style['hatch_global_lineweight']
                )
                symbol.changeSymbolLayer(0, hatch_layer)

            # Добавляем контур поверх штриховки
            outline_layer = self._create_outline_layer(style)
            symbol.appendSymbolLayer(outline_layer)

        else:  # hatch == "-" или другие значения
            # Без заливки, только контур
            fill_layer = QgsSimpleFillSymbolLayer()

            # Устанавливаем прозрачную заливку
            fill_layer.setBrushStyle(Qt.NoBrush)
            transparent_color = QColor(255, 255, 255, 0)  # Полностью прозрачный
            fill_layer.setFillColor(transparent_color)

            # Контур
            self._apply_outline(fill_layer, style)

            # Создаем символ
            symbol = QgsFillSymbol()
            symbol.changeSymbolLayer(0, fill_layer)

        return symbol

    # ========== Вспомогательные методы ==========

    def _linetype_to_pen_style(self, linetype: str) -> Qt.PenStyle:
        """
        Конвертация AutoCAD linetype → Qt.PenStyle

        Маппинг:
        CONTINUOUS → Qt.SolidLine
        DASHED → Qt.DashLine
        DOTTED → Qt.DotLine
        DASHDOT → Qt.DashDotLine
        и т.д.

        Args:
            linetype: Имя типа линии AutoCAD

        Returns:
            Qt.PenStyle
        """
        # Маппинг только нативно поддерживаемых стилей AutoCAD <-> Qt
        # ВАЖНО: Qt не поддерживает нативно PHANTOM (длинный-короткий-короткий)
        # и CENTER (длинный-короткий), поэтому они аппроксимируются
        LINETYPE_MAP = {
            'CONTINUOUS': Qt.SolidLine,      # Сплошная: ________
            'DASHED': Qt.DashLine,            # Штриховая: __ __ __
            'HIDDEN': Qt.DashLine,            # Скрытая: __ __ __ (как DASHED)
            'DOTTED': Qt.DotLine,             # Точечная: . . . .
            'DASHDOT': Qt.DashDotLine,        # Штрих-точка: __ . __ .
            'DIVIDE': Qt.DashDotLine,         # AutoCAD: штрих-точка __ . __ . (точное совпадение)
            'CENTER': Qt.DashDotLine,         # AutoCAD: длинный-короткий, Qt: штрих-точка (аппроксимация)
            'PHANTOM': Qt.DashDotDotLine,     # AutoCAD: длинный-короткий-короткий, Qt: штрих-точка-точка (аппроксимация)
        }
        return LINETYPE_MAP.get(linetype.upper(), Qt.SolidLine)

    def _apply_outline(self, fill_layer: QgsSimpleFillSymbolLayer, style: Dict[str, Any]) -> None:
        """
        Применить контур к fill_layer

        Использует поля из Base_layers.json:
        - line_color_RGB для цвета контура
        - line_transparency для прозрачности контура
        - line_global_weight для толщины контура
        - linetype для стиля контура

        Args:
            fill_layer: Слой заливки
            style: Словарь AutoCAD стиля
        """
        # Цвет контура с прозрачностью
        r, g, b = parse_rgb_string(style['line_color_RGB'])
        color = QColor(r, g, b)

        # Применяем прозрачность
        opacity = autocad_transparency_to_qgis(style['line_transparency'])
        color.setAlphaF(opacity)

        fill_layer.setStrokeColor(color)

        # Толщина контура
        width_mm = float(style['line_global_weight'])
        fill_layer.setStrokeWidth(width_mm)
        fill_layer.setStrokeWidthUnit(QgsUnitTypes.RenderMillimeters)

        # Стиль контура (используем linetype вместо Qt.SolidLine)
        pen_style = self._linetype_to_pen_style(style['linetype'])
        fill_layer.setStrokeStyle(pen_style)

    def _create_outline_layer(self, style: Dict[str, Any]) -> QgsSimpleLineSymbolLayer:
        """
        Создать отдельный слой контура для штриховки

        Использует поля из Base_layers.json:
        - line_color_RGB для цвета
        - line_transparency для прозрачности
        - line_global_weight для толщины
        - linetype для стиля линии

        Args:
            style: Словарь AutoCAD стиля

        Returns:
            QgsSimpleLineSymbolLayer для контура
        """
        outline_layer = QgsSimpleLineSymbolLayer()

        # Цвет с прозрачностью (используем line_color_RGB и line_transparency)
        r, g, b = parse_rgb_string(style['line_color_RGB'])
        color = QColor(r, g, b)

        # Применяем прозрачность
        opacity = autocad_transparency_to_qgis(style['line_transparency'])
        color.setAlphaF(opacity)

        outline_layer.setColor(color)

        # Толщина (используем line_global_weight)
        width_mm = float(style['line_global_weight'])
        outline_layer.setWidth(width_mm)
        outline_layer.setWidthUnit(QgsUnitTypes.RenderMillimeters)

        # Стиль линии (используем linetype вместо Qt.SolidLine)
        pen_style = self._linetype_to_pen_style(style['linetype'])
        outline_layer.setPenStyle(pen_style)

        return outline_layer

    def _create_hatch_layer_fixed_angle(
        self,
        angle: float,
        spacing: float,
        color_rgb: str,
        transparency: int,
        hatch_scale: float,
        lineweight: float = 0.25,
        offset: float = 0.0
    ) -> QgsLinePatternFillSymbolLayer:
        """
        Создать штриховку с фиксированным углом (для ANSI32 и ANSI37)

        Args:
            angle: Фиксированный угол штриховки в градусах
            spacing: Базовое расстояние между линиями (мм)
            color_rgb: Цвет в формате "R,G,B" (hatch_color_RGB)
            transparency: Прозрачность 0-100 (hatch_transparency)
            hatch_scale: Масштаб штриховки
            lineweight: Толщина линий штриховки (hatch_global_lineweight)
            offset: Смещение линий (для ANSI32), в долях spacing

        Returns:
            QgsLinePatternFillSymbolLayer
        """
        hatch_layer = QgsLinePatternFillSymbolLayer()

        # Применяем фиксированный угол и масштабированное расстояние
        final_spacing = spacing * hatch_scale

        hatch_layer.setLineAngle(angle)
        hatch_layer.setDistance(final_spacing)
        hatch_layer.setDistanceUnit(QgsUnitTypes.RenderMillimeters)

        # Применяем offset если задан (для ANSI32)
        if offset != 0.0:
            final_offset = offset * final_spacing
            hatch_layer.setOffset(final_offset)
            hatch_layer.setOffsetUnit(QgsUnitTypes.RenderMillimeters)

        # Создаем линию штриховки
        line_symbol = QgsLineSymbol.createSimple({})
        line_layer = QgsSimpleLineSymbolLayer()

        # Цвет с прозрачностью
        r, g, b = parse_rgb_string(color_rgb)
        color = QColor(r, g, b)

        # Применяем прозрачность
        opacity = autocad_transparency_to_qgis(transparency)
        color.setAlphaF(opacity)

        line_layer.setColor(color)
        line_layer.setWidth(lineweight)  # Толщина из hatch_global_lineweight

        line_symbol.deleteSymbolLayer(0)
        line_symbol.appendSymbolLayer(line_layer)
        hatch_layer.setSubSymbol(line_symbol)

        return hatch_layer

    def _create_hatch_layer(
        self,
        hatch_name: str,
        color_rgb: str,
        transparency: int,
        hatch_angle: int,
        hatch_scale: float,
        lineweight: float = 0.25
    ) -> QgsLinePatternFillSymbolLayer:
        """
        Создать штриховку из параметров AutoCAD (для простых ANSI паттернов)

        Поддерживаемые штриховки (один слой):
        ANSI31, ANSI35, ANSI36, ANSI38

        ВАЖНО: ANSI32 и ANSI37 требуют два слоя и обрабатываются отдельно
        в convert_polygon через _create_hatch_layer_fixed_angle

        Args:
            hatch_name: Имя штриховки (ANSI31, ANSI35, ANSI36, ANSI38...)
            color_rgb: Цвет в формате "R,G,B" (hatch_color_RGB)
            transparency: Прозрачность 0-100 (hatch_transparency)
            hatch_angle: Дополнительный угол поворота 0-360°
            hatch_scale: Масштаб штриховки
            lineweight: Толщина линий штриховки (hatch_global_lineweight)

        Returns:
            QgsLinePatternFillSymbolLayer
        """
        hatch_layer = QgsLinePatternFillSymbolLayer()

        # Базовые параметры по типу штриховки
        # ВАЖНО: ANSI32 и ANSI37 обрабатываются отдельно в convert_polygon
        # (требуют два слоя с разными параметрами), сюда не попадают
        if hatch_name == 'ANSI31':
            base_angle = 45
            spacing = ANSI_HATCH_SPACING
        else:
            # По умолчанию диагональ 45° для остальных паттернов (ANSI35, ANSI36, ANSI38...)
            base_angle = 45
            spacing = ANSI_HATCH_SPACING

        # ВАЖНО: для ANSI31/32 hatch_angle - это ПОЛНОЦЕННОЕ значение угла (не добавка)
        # Если hatch_angle задан (не 0 и не None), используем его ВМЕСТО базового
        # Если hatch_angle = 0 или не задан, используем базовый угол
        if hatch_angle and hatch_angle != 0:
            final_angle = hatch_angle % 360
        else:
            final_angle = base_angle

        final_spacing = spacing * hatch_scale

        hatch_layer.setLineAngle(final_angle)
        hatch_layer.setDistance(final_spacing)
        hatch_layer.setDistanceUnit(QgsUnitTypes.RenderMillimeters)

        # Создаем линию штриховки
        line_symbol = QgsLineSymbol.createSimple({})
        line_layer = QgsSimpleLineSymbolLayer()

        # Цвет с прозрачностью
        r, g, b = parse_rgb_string(color_rgb)
        color = QColor(r, g, b)

        # Применяем прозрачность
        opacity = autocad_transparency_to_qgis(transparency)
        color.setAlphaF(opacity)

        line_layer.setColor(color)
        line_layer.setWidth(lineweight)  # Толщина из hatch_global_lineweight

        line_symbol.deleteSymbolLayer(0)
        line_symbol.appendSymbolLayer(line_layer)
        hatch_layer.setSubSymbol(line_symbol)

        return hatch_layer
