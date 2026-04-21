# -*- coding: utf-8 -*-
"""
Конвертер AutoCAD стилей в QGIS символы

Преобразует параметры AutoCAD (из Base_layers.json) в QGIS символы
для визуализации слоев в QGIS
"""

from typing import Dict, Any, List
from qgis.core import (
    QgsVectorLayer, QgsMarkerSymbol, QgsLineSymbol, QgsFillSymbol,
    QgsSimpleLineSymbolLayer, QgsSimpleFillSymbolLayer, QgsSimpleMarkerSymbolLayer,
    QgsSingleSymbolRenderer, QgsLinePatternFillSymbolLayer, Qgis
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from Daman_QGIS.constants import ANSI_HATCH_SPACING
from Daman_QGIS.utils import log_warning
from .Msm_5_2_color_utils import parse_rgb_string, autocad_transparency_to_qgis


def _is_fill_enabled(style: Dict[str, Any]) -> bool:
    """Толерантный парсер поля 'fill' (bool / int / строка '1'/'0'/'true'/'false')."""
    value = style.get('fill', 0)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) == 1
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'да')
    return False


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
        from Daman_QGIS.managers import get_reference_managers
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
        marker_layer.setStrokeWidthUnit(Qgis.RenderUnit.Millimeters)

        # Диаметр окружности (line_scale)
        diameter = float(style.get('line_scale', 1.5))
        marker_layer.setSize(diameter)
        marker_layer.setSizeUnit(Qgis.RenderUnit.Millimeters)

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
        line_layer.setWidthUnit(Qgis.RenderUnit.Millimeters)

        # Тип линии
        pen_style = self._linetype_to_pen_style(style['linetype'])
        line_layer.setPenStyle(pen_style)

        # Применяем
        symbol.deleteSymbolLayer(0)
        symbol.appendSymbolLayer(line_layer)

        return symbol

    def convert_polygon(self, style: Dict[str, Any]) -> QgsFillSymbol:
        """
        Создать QgsFillSymbol из AutoCAD параметров полигона.

        Архитектура двух независимых слоёв (три уровня):
        - Нижний: ЗАЛИВКА (fill=1 в Base_layers) — QgsSimpleFillSymbolLayer
          с цветом fill_color_RGB и прозрачностью fill_transparency,
          stroke=NoPen (контур рисуется отдельным слоем)
        - Средний: ШТРИХОВКА (hatch=ANSI*) — QgsLinePatternFillSymbolLayer
          (один или два слоя для ANSI32/ANSI37) с цветом hatch_color_RGB
        - Верхний: КОНТУР (line_color_RGB + linetype) — QgsSimpleLineSymbolLayer

        Оба независимы: Заливка и Штриховка могут быть заданы как раздельно,
        так и одновременно. При одновременной — штриховка рисуется поверх.

        Legacy: если Штриховка='SOLID' — warning + трактуется как отсутствие
        штриховки (теперь заливка управляется отдельной колонкой 'fill').

        Args:
            style: Словарь AutoCAD стиля из Base_layers.json

        Returns:
            QgsFillSymbol с порядком слоёв fill -> hatch -> stroke.
        """
        fill_enabled = _is_fill_enabled(style)
        hatch = style.get('hatch', '-')

        # Legacy: SOLID в hatch больше не поддерживается — заливка задаётся отдельно
        if hatch == 'SOLID':
            log_warning(
                "Msm_5_1: Штриховка='SOLID' больше не поддерживается - "
                "используй колонку 'Заливка' (fill) в Base_layers. Обрабатываем как без штриховки."
            )
            hatch = '-'

        symbol = QgsFillSymbol()
        # Удаляем дефолтный layer (пустой SimpleFill), добавлять будем свои
        symbol.deleteSymbolLayer(0)

        # ===== НИЖНИЙ СЛОЙ: ЗАЛИВКА =====
        if fill_enabled:
            fill_layer = self._create_fill_layer(style)
            symbol.appendSymbolLayer(fill_layer)

        # ===== СРЕДНИЙ СЛОЙ(И): ШТРИХОВКА =====
        if hatch not in ('-', '', None) and hatch.startswith('ANSI'):
            for hatch_layer in self._create_hatch_layers(hatch, style):
                symbol.appendSymbolLayer(hatch_layer)

        # ===== ВЕРХНИЙ СЛОЙ: КОНТУР =====
        outline_layer = self._create_outline_layer(style)
        symbol.appendSymbolLayer(outline_layer)

        return symbol

    def _create_fill_layer(self, style: Dict[str, Any]) -> QgsSimpleFillSymbolLayer:
        """
        Создать слой сплошной заливки из полей 'fill_color_RGB' + 'fill_transparency'.

        Контур внутри fill_layer отключён (stroke=NoPen) — контур рисуется
        отдельным верхним слоем через _create_outline_layer.
        """
        fill_layer = QgsSimpleFillSymbolLayer()
        r, g, b = parse_rgb_string(style.get('fill_color_RGB', '255,255,255'))
        color = QColor(r, g, b)
        opacity = autocad_transparency_to_qgis(style.get('fill_transparency', 0))
        color.setAlphaF(opacity)
        fill_layer.setFillColor(color)
        fill_layer.setBrushStyle(Qt.BrushStyle.SolidPattern)
        fill_layer.setStrokeStyle(Qt.PenStyle.NoPen)
        return fill_layer

    def _create_hatch_layers(self, hatch: str, style: Dict[str, Any]) -> List[QgsLinePatternFillSymbolLayer]:
        """
        Построить 1-2 слоя штриховки в зависимости от типа ANSI.

        Возвращает список (1 элемент для простых ANSI, 2 для ANSI32/ANSI37).
        """
        layers: List[QgsLinePatternFillSymbolLayer] = []

        if hatch == 'ANSI37':
            # ANSI37 - два слоя с базовыми углами 45° и 135° + hatch_angle (добавка)
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

            layers.append(self._create_hatch_layer_fixed_angle(
                45 + hatch_angle_offset,
                ANSI_HATCH_SPACING,
                style['hatch_color_RGB'],
                style['hatch_transparency'],
                style['hatch_scale'],
                style['hatch_global_lineweight']
            ))
            layers.append(self._create_hatch_layer_fixed_angle(
                135 + hatch_angle_offset,
                ANSI_HATCH_SPACING,
                style['hatch_color_RGB'],
                style['hatch_transparency'],
                style['hatch_scale'],
                style['hatch_global_lineweight']
            ))

        elif hatch == 'ANSI32':
            # ANSI32 - Steel pattern: два слоя с тем же углом, разный offset
            hatch_angle_value = style.get('hatch_angle', 0)
            if isinstance(hatch_angle_value, str):
                try:
                    hatch_angle_value = int(hatch_angle_value) if hatch_angle_value != '-' else 0
                except ValueError:
                    hatch_angle_value = 0
            final_angle = hatch_angle_value if hatch_angle_value else 45
            ansi32_offset = 0.176776695

            layers.append(self._create_hatch_layer_fixed_angle(
                final_angle,
                ANSI_HATCH_SPACING,
                style['hatch_color_RGB'],
                style['hatch_transparency'],
                style['hatch_scale'],
                style['hatch_global_lineweight'],
                offset=0.0
            ))
            layers.append(self._create_hatch_layer_fixed_angle(
                final_angle,
                ANSI_HATCH_SPACING,
                style['hatch_color_RGB'],
                style['hatch_transparency'],
                style['hatch_scale'],
                style['hatch_global_lineweight'],
                offset=ansi32_offset
            ))

        else:
            # Остальные одинарные ANSI (ANSI31, ANSI35, ANSI36, ANSI38, etc.)
            layers.append(self._create_hatch_layer(
                hatch,
                style['hatch_color_RGB'],
                style['hatch_transparency'],
                style['hatch_angle'],
                style['hatch_scale'],
                style['hatch_global_lineweight']
            ))

        return layers

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
            'CONTINUOUS': Qt.PenStyle.SolidLine,      # Сплошная: ________
            'DASHED': Qt.PenStyle.DashLine,            # Штриховая: __ __ __
            'HIDDEN': Qt.PenStyle.DashLine,            # Скрытая: __ __ __ (как DASHED)
            'DOTTED': Qt.PenStyle.DotLine,             # Точечная: . . . .
            'DASHDOT': Qt.PenStyle.DashDotLine,        # Штрих-точка: __ . __ .
            'DIVIDE': Qt.PenStyle.DashDotLine,         # AutoCAD: штрих-точка __ . __ . (точное совпадение)
            'CENTER': Qt.PenStyle.DashDotLine,         # AutoCAD: длинный-короткий, Qt: штрих-точка (аппроксимация)
            'PHANTOM': Qt.PenStyle.DashDotDotLine,     # AutoCAD: длинный-короткий-короткий, Qt: штрих-точка-точка (аппроксимация)
        }
        return LINETYPE_MAP.get(linetype.upper(), Qt.PenStyle.SolidLine)

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
        fill_layer.setStrokeWidthUnit(Qgis.RenderUnit.Millimeters)

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
        outline_layer.setWidthUnit(Qgis.RenderUnit.Millimeters)

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
        hatch_layer.setDistanceUnit(Qgis.RenderUnit.Millimeters)

        # Применяем offset если задан (для ANSI32)
        if offset != 0.0:
            final_offset = offset * final_spacing
            hatch_layer.setOffset(final_offset)
            hatch_layer.setOffsetUnit(Qgis.RenderUnit.Millimeters)

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
        hatch_layer.setDistanceUnit(Qgis.RenderUnit.Millimeters)

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
