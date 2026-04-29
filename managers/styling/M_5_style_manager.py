# -*- coding: utf-8 -*-
"""
Главный менеджер стилей - единая точка входа

Предоставляет унифицированный API для:
- Применения AutoCAD стилей к слоям QGIS (визуализация)
- Получения MapInfo стилей для экспорта TAB

Заменяет UniversalStyleManager и AutoCADVisualStyleManager
"""

from typing import Optional, TYPE_CHECKING
from qgis.core import (
    QgsVectorLayer, QgsRasterLayer, QgsMapLayer,
    QgsSingleSymbolRenderer, QgsMergedFeatureRenderer
)
from Daman_QGIS.constants import LAYER_ZOUIT_PREFIX
from Daman_QGIS.utils import log_warning, log_error
from .submodules.Msm_5_1_autocad_to_qgis_converter import AutoCADToQGISConverter

# Импорты только для type hints (избегаем циклических импортов и runtime overhead)
if TYPE_CHECKING:
    from qgis.PyQt.QtGui import QColor
    from qgis.PyQt.QtCore import Qt

__all__ = ['StyleManager']


class StyleManager:
    """
    Единая точка входа для работы со стилями слоев

    Примеры использования:
        >>> manager = StyleManager()
        >>> manager.apply_qgis_style(layer, "L_1_1_1_Границы_работ")
        >>> mapinfo = manager.get_mapinfo_style("L_1_10_2_КАТ_Сельхоз")
    """

    # Ключи customProperty для AutoCAD стилей (DXF экспорт)
    PROP_LINETYPE = "autocad/linetype"
    PROP_COLOR = "autocad/color"
    PROP_LINEWEIGHT = "autocad/lineweight"
    PROP_TRANSPARENCY = "autocad/transparency"
    PROP_LINE_SCALE = "autocad/line_scale"
    PROP_HATCH = "autocad/hatch"
    PROP_HATCH_SCALE = "autocad/hatch_scale"
    PROP_HATCH_ANGLE = "autocad/hatch_angle"
    PROP_HATCH_COLOR = "autocad/hatch_color"
    PROP_HATCH_TRANSPARENCY = "autocad/hatch_transparency"
    PROP_HATCH_LINEWEIGHT = "autocad/hatch_lineweight"
    # Раздельная заливка (Заливка, Цвет заливки, Прозрачность заливки)
    PROP_FILL = "autocad/fill"
    PROP_FILL_COLOR = "autocad/fill_color"
    PROP_FILL_TRANSPARENCY = "autocad/fill_transparency"

    def __init__(self):
        """Инициализация менеджера стилей"""
        self.converter = AutoCADToQGISConverter()
        self._ref_managers = None  # Lazy init

    @property
    def ref_managers(self):
        """Ленивая инициализация справочных менеджеров"""
        if self._ref_managers is None:
            from Daman_QGIS.managers import get_reference_managers
            self._ref_managers = get_reference_managers()
        return self._ref_managers

    def apply_qgis_style(self, layer: QgsMapLayer, layer_name: str) -> bool:
        """
        Применить AutoCAD стиль к слою QGIS для визуализации

        Алгоритм:
        1. Проверка валидности слоя
        2. Получение AutoCAD стиля из Base_layers.json
        3. Конвертация в QGIS символ (Point/Line/Polygon)
        4. Применение к слою

        Args:
            layer: Векторный или растровый слой QGIS
            layer_name: Полное имя слоя (например "L_1_1_1_Границы_работ")

        Returns:
            True если стиль успешно применен

        Examples:
            >>> manager = StyleManager()
            >>> success = manager.apply_qgis_style(layer, "L_1_10_2_КАТ_Сельхоз")
        """
        # Проверка валидности слоя
        if not layer or not layer.isValid():
            log_warning(f"StyleManager: Невалидный слой '{layer_name}'")
            return False

        # Растровые слои не требуют стилизации AutoCAD
        if isinstance(layer, QgsRasterLayer):
            return True

        # Только векторные слои
        if not isinstance(layer, QgsVectorLayer):
            log_warning(f"StyleManager: Слой '{layer_name}' не является векторным")
            return False

        # Проверка типа геометрии слоя (может быть NoGeometry)
        geom_type = layer.geometryType()

        # geom_type == 4 (или -1 в некоторых версиях) означает NoGeometry
        # Такие слои не требуют визуального стиля
        if geom_type == 4 or geom_type == -1:
            from Daman_QGIS.utils import log_debug
            log_debug(f"StyleManager: Слой '{layer_name}' без геометрии (NoGeometry), стиль не требуется")
            return True

        # Получить AutoCAD стиль из БД
        try:
            style = self.ref_managers.layer_style.get_layer_autocad_style(layer_name)
        except Exception as e:
            log_error(f"StyleManager: Ошибка получения стиля для '{layer_name}': {e}")
            return False

        if not style:
            log_warning(f"StyleManager: Стиль не найден для '{layer_name}'")
            return False

        # Дополнительная проверка: если в Base_layers.json geometry_type = "not", пропускаем стиль
        if style.get('geometry_type', '').lower() == 'not':
            from Daman_QGIS.utils import log_debug
            log_debug(f"StyleManager: Слой '{layer_name}' помечен как 'not' в Base_layers.json, стиль не требуется")
            return True

        # ВАЖНО: Валидация соответствия типа геометрии слоя и ожидаемого типа из Base_layers.json
        expected_geom_type = style.get('geometry_type', '').strip()
        if expected_geom_type and expected_geom_type != '-':
            # Маппинг типов геометрии QGIS на строковые значения из Base_layers.json
            geom_type_map = {
                0: 'Point',     # QgsWkbTypes.PointGeometry
                1: 'LineString', # QgsWkbTypes.LineGeometry (может быть Line или LineString)
                2: 'Polygon'    # QgsWkbTypes.PolygonGeometry (включает Polygon и MultiPolygon)
            }

            actual_geom_str = geom_type_map.get(geom_type, 'Unknown')

            # Проверка соответствия
            # ВАЖНО: Polygon и MultiPolygon оба относятся к категории PolygonGeometry (geom_type=2)
            if expected_geom_type == 'Mixed':
                # Mixed (GeometryCollection) — стилизация через rule-based renderer
                pass
            elif expected_geom_type not in ['Point', 'LineString', 'Line', 'Polygon', 'MultiPolygon']:
                # Если в базе что-то другое (например "not"), пропускаем проверку
                pass
            elif expected_geom_type == 'Line' or expected_geom_type == 'LineString':
                if geom_type != 1:
                    log_warning(
                        f"StyleManager: Несоответствие типа геометрии для '{layer_name}': "
                        f"ожидался {expected_geom_type}, получен {actual_geom_str} ({geom_type})"
                    )
            elif expected_geom_type == 'Polygon' or expected_geom_type == 'MultiPolygon':
                # Оба типа корректны для PolygonGeometry
                if geom_type != 2:
                    log_warning(
                        f"StyleManager: Несоответствие типа геометрии для '{layer_name}': "
                        f"ожидался {expected_geom_type}, получен {actual_geom_str} ({geom_type})"
                    )
            elif expected_geom_type != actual_geom_str:
                log_warning(
                    f"StyleManager: Несоответствие типа геометрии для '{layer_name}': "
                    f"ожидался {expected_geom_type}, получен {actual_geom_str} ({geom_type})"
                )

        # Конвертировать в QGIS символ
        try:
            # Mixed ПЕРЕД обычными проверками — wkbType может быть Polygon после GPKG save
            if expected_geom_type == 'Mixed':
                return self._apply_mixed_style(layer, layer_name, style)
            elif geom_type == 0:  # Point
                symbol = self.converter.convert_point(style)
            elif geom_type == 1:  # Line
                symbol = self.converter.convert_line(style)
            elif geom_type == 2:  # Polygon
                symbol = self.converter.convert_polygon(style)
            else:
                log_warning(f"StyleManager: Неизвестный тип геометрии {geom_type} для '{layer_name}'")
                return False

        except Exception as e:
            log_error(f"StyleManager: Ошибка конвертации стиля для '{layer_name}': {e}")
            import traceback
            log_error(f"StyleManager: Traceback:\n{traceback.format_exc()}")
            return False

        # Применить к слою
        try:
            renderer = QgsSingleSymbolRenderer(symbol)

            # Для ЗОУИТ слоев используем QgsMergedFeatureRenderer (визуальное слияние объектов)
            # В GUI: Свойства слоя → Символизация с автоматическим слиянием объектов
            if layer_name.startswith(LAYER_ZOUIT_PREFIX):
                merged_renderer = QgsMergedFeatureRenderer(renderer)
                layer.setRenderer(merged_renderer)
            else:
                layer.setRenderer(renderer)

            # КРИТИЧЕСКИ ВАЖНО: Сохраняем AutoCAD стиль в customProperty слоя
            # Это необходимо для корректного экспорта в DXF
            self._save_autocad_properties_to_layer(layer, style)

            # Безопасный отложенный refresh через QTimer (предотвращает краши с ЗОУИТ слоями)
            from Daman_QGIS.utils import safe_refresh_layer, safe_refresh_layer_symbology
            safe_refresh_layer(layer)
            safe_refresh_layer_symbology(layer)

            return True

        except Exception as e:
            log_error(f"StyleManager: Ошибка применения renderer для '{layer_name}': {e}")
            return False

    def _apply_mixed_style(self, layer: QgsVectorLayer, layer_name: str, style: dict) -> bool:
        """
        Применить rule-based стиль для Mixed (GeometryCollection) слоя.

        Создает правила по типу геометрии каждого feature:
        - Polygon -> стиль полигона
        - LineString -> стиль линии
        - Point -> стиль точки

        Args:
            layer: Векторный слой
            layer_name: Имя слоя
            style: Словарь стиля из Base_layers.json

        Returns:
            True если успешно
        """
        from qgis.core import (
            Qgis, QgsWkbTypes, QgsRuleBasedRenderer, QgsSymbol,
            QgsSimpleLineSymbolLayer, QgsSimpleFillSymbolLayer, QgsSimpleMarkerSymbolLayer
        )
        from qgis.PyQt.QtGui import QColor
        from qgis.PyQt.QtCore import Qt
        from Daman_QGIS.utils import log_info, safe_refresh_layer, safe_refresh_layer_symbology

        try:
            # Получаем цвет и толщину из AutoCAD стиля
            line_color_str = style.get('line_color', '255,0,0')
            line_weight = float(style.get('line_global_weight', '0.4') or '0.4')

            parts = line_color_str.split(',')
            color = QColor(int(parts[0]), int(parts[1]), int(parts[2]))

            # ВАЖНО: geometry_type($geometry) возвращает ПЕРЕВЕДЁННЫЕ строки
            # В русской локали: "Полигон", "Линия", "Точка" вместо "Polygon", "Line", "Point"
            polygon_str = QgsWkbTypes.geometryDisplayString(Qgis.GeometryType.Polygon)
            line_str = QgsWkbTypes.geometryDisplayString(Qgis.GeometryType.Line)
            point_str = QgsWkbTypes.geometryDisplayString(Qgis.GeometryType.Point)

            log_info(f"StyleManager: Mixed locale strings: polygon='{polygon_str}', line='{line_str}', point='{point_str}'")

            # Определяем какие типы геометрий реально есть в слое
            existing_geom_types = set()
            for feat in layer.getFeatures():
                geom = feat.geometry()
                if geom and not geom.isEmpty():
                    existing_geom_types.add(geom.type())

            log_info(f"StyleManager: Mixed actual geom types: {[t.name for t in existing_geom_types]}")

            # Корневой символ (обязателен для QgsRuleBasedRenderer)
            root_rule = QgsRuleBasedRenderer.Rule(None)

            # Правило для полигонов (только если есть полигоны)
            if Qgis.GeometryType.Polygon in existing_geom_types:
                polygon_symbol = QgsSymbol.defaultSymbol(Qgis.GeometryType.Polygon)
                polygon_symbol.deleteSymbolLayer(0)
                fill_layer = QgsSimpleFillSymbolLayer(
                    color=QColor(color.red(), color.green(), color.blue(), 50),
                    style=Qt.BrushStyle.SolidPattern,
                    strokeColor=color,
                    strokeStyle=Qt.PenStyle.SolidLine,
                    strokeWidth=line_weight
                )
                polygon_symbol.appendSymbolLayer(fill_layer)
                polygon_rule = QgsRuleBasedRenderer.Rule(polygon_symbol)
                polygon_rule.setFilterExpression(f"geometry_type($geometry) = '{polygon_str}'")
                polygon_rule.setLabel(polygon_str)
                root_rule.appendChild(polygon_rule)

            # Правило для линий (только если есть линии)
            if Qgis.GeometryType.Line in existing_geom_types:
                line_symbol = QgsSymbol.defaultSymbol(Qgis.GeometryType.Line)
                line_symbol.deleteSymbolLayer(0)
                line_layer = QgsSimpleLineSymbolLayer(color=color, width=line_weight)
                line_symbol.appendSymbolLayer(line_layer)
                line_rule = QgsRuleBasedRenderer.Rule(line_symbol)
                line_rule.setFilterExpression(f"geometry_type($geometry) = '{line_str}'")
                line_rule.setLabel(line_str)
                root_rule.appendChild(line_rule)

            # Правило для точек (только если есть точки)
            if Qgis.GeometryType.Point in existing_geom_types:
                point_symbol = QgsSymbol.defaultSymbol(Qgis.GeometryType.Point)
                point_symbol.deleteSymbolLayer(0)
                marker_layer = QgsSimpleMarkerSymbolLayer(color=color, size=2.0)
                point_symbol.appendSymbolLayer(marker_layer)
                point_rule = QgsRuleBasedRenderer.Rule(point_symbol)
                point_rule.setFilterExpression(f"geometry_type($geometry) = '{point_str}'")
                point_rule.setLabel(point_str)
                root_rule.appendChild(point_rule)

            renderer = QgsRuleBasedRenderer(root_rule)
            layer.setRenderer(renderer)

            # Сохраняем AutoCAD свойства
            self._save_autocad_properties_to_layer(layer, style)

            safe_refresh_layer(layer)
            safe_refresh_layer_symbology(layer)

            log_info(f"StyleManager: Mixed стиль применен для '{layer_name}' (rule-based)")
            return True

        except Exception as e:
            log_error(f"StyleManager: Ошибка Mixed стиля для '{layer_name}': {e}")
            return False

    def get_mapinfo_style(self, layer_name: str) -> Optional[str]:
        """
        Получить MapInfo стиль для экспорта TAB

        ВАЖНО: MapInfo стили используются ТОЛЬКО для экспорта TAB (F_5_1).
        Для визуализации в QGIS используется apply_qgis_style().

        Args:
            layer_name: Полное имя слоя (например "L_1_10_2_КАТ_Сельхоз")

        Returns:
            Строка MapInfo стиля (например "Brush(1, 255, 16777215) Pen(1, 2, 0)")
            или None если слой не найден

        Examples:
            >>> manager = StyleManager()
            >>> mapinfo = manager.get_mapinfo_style("L_1_10_2_КАТ_Сельхоз")
            >>> print(mapinfo)
            "Brush(1, 255, 16777215) Pen(1, 2, 0)"
        """
        try:
            layer_info = self.ref_managers.layer.get_layer_by_full_name(layer_name)
            if layer_info:
                style = layer_info.get('style_MapInfo')
                if style and style != '-':
                    return style
                return None
            log_warning(f"StyleManager: Слой '{layer_name}' не найден в Base_layers.json")
            return None
        except Exception as e:
            log_error(f"StyleManager: Ошибка получения MapInfo стиля для '{layer_name}': {e}")
            return None

    # ========== Методы для создания простых стилей ==========
    # Используются для служебных слоев (ошибки, координаты и т.д.)

    def create_simple_line_style(self, layer: QgsVectorLayer, color: 'QColor',
                                 width_mm: float = 1.0, pen_style: 'Qt.PenStyle' = None) -> bool:
        """
        Создать и применить простой линейный стиль к слою

        Используется для служебных слоев (границы работ по умолчанию, ошибки и т.д.)

        Args:
            layer: Векторный слой
            color: Цвет линии (QColor)
            width_mm: Толщина линии в миллиметрах (по умолчанию 1.0)
            pen_style: Стиль линии Qt.PenStyle (по умолчанию Qt.SolidLine)

        Returns:
            True если стиль успешно применен

        Examples:
            >>> manager = StyleManager()
            >>> manager.create_simple_line_style(layer, QColor(255, 0, 0), 1.0)
        """
        from qgis.core import QgsLineSymbol, QgsSimpleLineSymbolLayer, Qgis
        from qgis.PyQt.QtCore import Qt

        try:
            if pen_style is None:
                pen_style = Qt.PenStyle.SolidLine

            # Создаем линейный символ
            symbol = QgsLineSymbol.createSimple({})
            line_layer = QgsSimpleLineSymbolLayer()

            line_layer.setColor(color)
            line_layer.setWidth(width_mm)
            line_layer.setWidthUnit(Qgis.RenderUnit.Millimeters)
            line_layer.setPenStyle(pen_style)
            line_layer.setPenJoinStyle(Qt.PenJoinStyle.RoundJoin)
            line_layer.setPenCapStyle(Qt.PenCapStyle.RoundCap)

            symbol.deleteSymbolLayer(0)
            symbol.appendSymbolLayer(line_layer)

            # Применяем к слою
            renderer = QgsSingleSymbolRenderer(symbol)
            layer.setRenderer(renderer)

            return True

        except Exception as e:
            log_error(f"StyleManager: Ошибка создания простого линейного стиля: {e}")
            return False

    def create_simple_marker_style(self, layer: QgsVectorLayer, color: 'QColor',
                                  size_mm: float = 3.0) -> bool:
        """
        Создать и применить простой маркерный стиль к слою

        Используется для служебных слоев (ошибки топологии, контрольные точки и т.д.)

        Args:
            layer: Векторный слой
            color: Цвет маркера (QColor)
            size_mm: Размер маркера в миллиметрах (по умолчанию 3.0)

        Returns:
            True если стиль успешно применен

        Examples:
            >>> manager = StyleManager()
            >>> manager.create_simple_marker_style(layer, QColor(255, 0, 0), 3.0)
        """
        from qgis.core import QgsMarkerSymbol, QgsSimpleMarkerSymbolLayer, Qgis

        try:
            # Создаем маркерный символ
            symbol = QgsMarkerSymbol.createSimple({})
            marker_layer = symbol.symbolLayer(0)

            marker_layer.setColor(color)
            marker_layer.setSize(size_mm)
            marker_layer.setSizeUnit(Qgis.RenderUnit.Millimeters)

            # Применяем к слою
            renderer = QgsSingleSymbolRenderer(symbol)
            layer.setRenderer(renderer)

            return True

        except Exception as e:
            log_error(f"StyleManager: Ошибка создания простого маркерного стиля: {e}")
            return False

    def create_simple_polygon_style(self, layer: QgsVectorLayer, fill_color: 'QColor',
                                   stroke_color: 'QColor', stroke_width_mm: float = 1.0) -> bool:
        """
        Создать и применить простой полигональный стиль к слою

        Используется для служебных слоев (области ошибок, пересечения и т.д.)

        Args:
            layer: Векторный слой
            fill_color: Цвет заливки (QColor, может быть прозрачным)
            stroke_color: Цвет контура (QColor)
            stroke_width_mm: Толщина контура в миллиметрах (по умолчанию 1.0)

        Returns:
            True если стиль успешно применен

        Examples:
            >>> manager = StyleManager()
            >>> manager.create_simple_polygon_style(
            ...     layer,
            ...     QColor(255, 0, 0, 100),  # Полупрозрачная красная заливка
            ...     QColor(255, 0, 0),       # Красный контур
            ...     1.0
            ... )
        """
        from qgis.core import QgsFillSymbol, QgsSimpleFillSymbolLayer, Qgis

        try:
            # Создаем полигональный символ
            symbol = QgsFillSymbol.createSimple({})
            fill_layer = symbol.symbolLayer(0)

            fill_layer.setFillColor(fill_color)
            fill_layer.setStrokeColor(stroke_color)
            fill_layer.setStrokeWidth(stroke_width_mm)
            fill_layer.setStrokeWidthUnit(Qgis.RenderUnit.Millimeters)

            # Применяем к слою
            renderer = QgsSingleSymbolRenderer(symbol)
            layer.setRenderer(renderer)

            return True

        except Exception as e:
            log_error(f"StyleManager: Ошибка создания простого полигонального стиля: {e}")
            return False

    def _save_autocad_properties_to_layer(self, layer: QgsVectorLayer, autocad_style: dict) -> None:
        """
        Сохранение AutoCAD стиля в customProperty слоя для экспорта в DXF

        Args:
            layer: Векторный слой
            autocad_style: Словарь со стилем AutoCAD из Base_layers.json
        """
        # Извлекаем данные из autocad_style
        linetype = autocad_style.get('linetype', 'CONTINUOUS')

        # Конвертируем RGB в AutoCAD color index
        line_color_rgb = autocad_style.get('line_color_RGB', '255,0,0')
        color_index = self._rgb_to_autocad_color(line_color_rgb)

        # Lineweight из line_global_weight (в мм → AutoCAD lineweight в сотых долях мм)
        line_weight_mm = autocad_style.get('line_global_weight', 1.0)
        lineweight = int(line_weight_mm * 100)  # 1.0мм → 100

        transparency = autocad_style.get('line_transparency', 0)

        # line_scale: для линий = ltscale, для точек = диаметр круга (мм)
        line_scale = autocad_style.get('line_scale', 1.0)

        # Hatch: преобразуем "-" в None.
        # Legacy: 'SOLID' в Штриховке больше не поддерживается — заливка
        # теперь управляется отдельной колонкой 'fill'. Игнорируем 'SOLID'.
        hatch = autocad_style.get('hatch', '-')
        if hatch == '-' or not hatch or (isinstance(hatch, str) and not hatch.strip()):
            hatch = None
        elif isinstance(hatch, str) and hatch.upper() == 'SOLID':
            hatch = None

        hatch_scale = autocad_style.get('hatch_scale', 1.0)

        # hatch_angle: 0..360, default 0. '-' / None трактуем как 0.
        hatch_angle_raw = autocad_style.get('hatch_angle', 0)
        try:
            hatch_angle = int(hatch_angle_raw)
        except (ValueError, TypeError):
            hatch_angle = 0

        # hatch_global_lineweight: толщина линий штриховки в мм (float),
        # сохраняется как int сотых мм по аналогии с PROP_LINEWEIGHT.
        hatch_lineweight_mm_raw = autocad_style.get('hatch_global_lineweight', 0)
        try:
            hatch_lineweight_mm = float(hatch_lineweight_mm_raw)
        except (ValueError, TypeError):
            hatch_lineweight_mm = 0.0
        hatch_lineweight = int(hatch_lineweight_mm * 100)

        hatch_color_rgb = autocad_style.get('hatch_color_RGB', '')
        if hatch_color_rgb and hatch_color_rgb != '-':
            hatch_color_index = self._rgb_to_autocad_color(hatch_color_rgb)
        else:
            hatch_color_index = None

        # Прозрачность штриховки (отдельно от line_transparency).
        # '-' / None → 0 (непрозрачно по умолчанию).
        hatch_transparency_raw = autocad_style.get('hatch_transparency', 0)
        try:
            hatch_transparency = int(hatch_transparency_raw)
        except (ValueError, TypeError):
            hatch_transparency = 0

        # Раздельная заливка (новая колонка Заливка / Цвет заливки / Прозрачность заливки)
        fill_value = autocad_style.get('fill', 0)
        if isinstance(fill_value, bool):
            fill_enabled = fill_value
        elif isinstance(fill_value, (int, float)):
            fill_enabled = int(fill_value) == 1
        elif isinstance(fill_value, str):
            fill_enabled = fill_value.strip().lower() in ('1', 'true', 'yes', 'да')
        else:
            fill_enabled = False

        fill_color_rgb = autocad_style.get('fill_color_RGB', '')
        if fill_color_rgb and fill_color_rgb != '-':
            fill_color_index = self._rgb_to_autocad_color(fill_color_rgb)
        else:
            fill_color_index = None

        fill_transparency_raw = autocad_style.get('fill_transparency', 0)
        try:
            fill_transparency = int(fill_transparency_raw)
        except (ValueError, TypeError):
            fill_transparency = 0

        # Сохраняем в customProperty
        layer.setCustomProperty(self.PROP_LINETYPE, linetype)
        layer.setCustomProperty(self.PROP_COLOR, color_index)
        layer.setCustomProperty(self.PROP_LINEWEIGHT, lineweight)
        layer.setCustomProperty(self.PROP_TRANSPARENCY, transparency)
        layer.setCustomProperty(self.PROP_LINE_SCALE, line_scale)

        if hatch:
            layer.setCustomProperty(self.PROP_HATCH, hatch)
            layer.setCustomProperty(self.PROP_HATCH_SCALE, hatch_scale)
            layer.setCustomProperty(self.PROP_HATCH_ANGLE, hatch_angle)
            layer.setCustomProperty(self.PROP_HATCH_TRANSPARENCY, hatch_transparency)
            layer.setCustomProperty(self.PROP_HATCH_LINEWEIGHT, hatch_lineweight)
            if hatch_color_index is not None:
                layer.setCustomProperty(self.PROP_HATCH_COLOR, hatch_color_index)
            else:
                layer.removeCustomProperty(self.PROP_HATCH_COLOR)
        else:
            # Удаляем hatch если его нет
            layer.removeCustomProperty(self.PROP_HATCH)
            layer.removeCustomProperty(self.PROP_HATCH_SCALE)
            layer.removeCustomProperty(self.PROP_HATCH_ANGLE)
            layer.removeCustomProperty(self.PROP_HATCH_COLOR)
            layer.removeCustomProperty(self.PROP_HATCH_TRANSPARENCY)
            layer.removeCustomProperty(self.PROP_HATCH_LINEWEIGHT)

        if fill_enabled:
            layer.setCustomProperty(self.PROP_FILL, 1)
            layer.setCustomProperty(self.PROP_FILL_TRANSPARENCY, fill_transparency)
            if fill_color_index is not None:
                layer.setCustomProperty(self.PROP_FILL_COLOR, fill_color_index)
            else:
                layer.removeCustomProperty(self.PROP_FILL_COLOR)
        else:
            layer.removeCustomProperty(self.PROP_FILL)
            layer.removeCustomProperty(self.PROP_FILL_COLOR)
            layer.removeCustomProperty(self.PROP_FILL_TRANSPARENCY)

    def _rgb_to_autocad_color(self, rgb_string: str) -> int:
        """
        Конвертация RGB строки в AutoCAD color index (упрощенно)

        Args:
            rgb_string: "R,G,B" например "255,0,0"

        Returns:
            int: AutoCAD color index (1-255)
        """
        try:
            r, g, b = map(int, rgb_string.split(','))

            # Упрощенная конвертация основных цветов
            if (r, g, b) == (255, 0, 0):
                return 1  # Красный
            elif (r, g, b) == (255, 255, 0):
                return 2  # Желтый
            elif (r, g, b) == (0, 255, 0):
                return 3  # Зеленый
            elif (r, g, b) == (0, 255, 255):
                return 4  # Циан
            elif (r, g, b) == (0, 0, 255):
                return 5  # Синий
            elif (r, g, b) == (255, 0, 255):
                return 6  # Пурпурный
            elif (r, g, b) == (255, 255, 255):
                return 7  # Белый
            elif (r, g, b) == (0, 0, 0):
                return 7  # Чёрный/белый (AutoCAD использует 7 для обоих)
            else:
                # Для произвольных цветов используем True Color (24-bit RGB)
                # В ezdxf можно установить цвет напрямую через RGB значение
                # Возвращаем отрицательное значение как флаг использования RGB
                # Формат: -(R * 65536 + G * 256 + B)
                # Это будет обработано в dxf_exporter для установки true_color
                return -(r * 65536 + g * 256 + b)
        except (ValueError, TypeError, AttributeError):
            return 1  # По умолчанию красный

    def validate_project_styles(self) -> tuple:
        """
        Валидация всех слоев в проекте на наличие AutoCAD стилей

        Проверяет, что у всех векторных слоев есть сохраненные AutoCAD атрибуты
        в customProperty. Используется для предупреждений при экспорте в DXF.

        Returns:
            tuple: (bool, list) - (все валидны, список проблемных слоёв)

        Examples:
            >>> manager = StyleManager()
            >>> valid, issues = manager.validate_project_styles()
            >>> if not valid:
            >>>     for issue in issues:
            >>>         print(issue)
        """
        from qgis.core import QgsProject

        all_issues = []

        # Проверяем все векторные слои в проекте
        for layer_id, layer in QgsProject.instance().mapLayers().items():
            if isinstance(layer, QgsVectorLayer):
                # Проверяем наличие сохраненного AutoCAD стиля
                linetype = layer.customProperty(self.PROP_LINETYPE)
                if not linetype:
                    all_issues.append(f"Слой '{layer.name()}': не настроен стиль AutoCAD")

        return len(all_issues) == 0, all_issues

    def get_autocad_attributes(self, layer: QgsVectorLayer) -> dict:
        """
        Получение атрибутов AutoCAD из слоя или из базы данных

        Сначала проверяет customProperty слоя (если стиль был применен через apply_qgis_style),
        затем пытается загрузить из Base_layers.json по имени слоя.

        Args:
            layer: Векторный слой QGIS

        Returns:
            dict: Словарь с атрибутами AutoCAD:
                - linetype: Тип линии ('CONTINUOUS', 'DASHED', и т.д.)
                - color: AutoCAD color index (1-255)
                - lineweight: Толщина линии в сотых долях мм (100 = 1.00мм)
                - transparency: Прозрачность (0-100)
                - line_scale: Масштаб типа линии / диаметр круга для точек (мм)
                - hatch: Паттерн штриховки (ANSI31, ANSI32, и т.д.) или None
                - hatch_scale: Масштаб штриховки (по умолчанию 1.0)
                - hatch_angle: Угол штриховки в градусах (0..360, по умолчанию 0)
                - hatch_lineweight: Толщина линий штриховки в сотых мм (0 = BYLAYER)

        Examples:
            >>> manager = StyleManager()
            >>> style = manager.get_autocad_attributes(layer)
            >>> print(style['linetype'], style['color'])
        """
        # Проверяем наличие сохраненных AutoCAD атрибутов в customProperty
        linetype = layer.customProperty(self.PROP_LINETYPE)
        if linetype:
            # Есть сохраненные атрибуты - возвращаем их
            hatch_value = layer.customProperty(self.PROP_HATCH)

            # Преобразуем "-" в None для hatch
            if hatch_value == '-' or (isinstance(hatch_value, str) and not hatch_value.strip()):
                hatch_value = None

            return {
                'linetype': linetype,
                'color': layer.customProperty(self.PROP_COLOR, 1),
                'lineweight': layer.customProperty(self.PROP_LINEWEIGHT, 100),
                'transparency': layer.customProperty(self.PROP_TRANSPARENCY, 0),
                'line_scale': layer.customProperty(self.PROP_LINE_SCALE, 1.0),
                'hatch': hatch_value,
                'hatch_scale': layer.customProperty(self.PROP_HATCH_SCALE, 1.0),
                'hatch_angle': layer.customProperty(self.PROP_HATCH_ANGLE, 0),
                'hatch_color': layer.customProperty(self.PROP_HATCH_COLOR),
                'hatch_transparency': layer.customProperty(self.PROP_HATCH_TRANSPARENCY, 0),
                'hatch_lineweight': layer.customProperty(self.PROP_HATCH_LINEWEIGHT, 0),
                'fill': layer.customProperty(self.PROP_FILL, 0),
                'fill_color': layer.customProperty(self.PROP_FILL_COLOR),
                'fill_transparency': layer.customProperty(self.PROP_FILL_TRANSPARENCY, 0),
            }

        # Если нет сохраненных атрибутов - пытаемся получить из Base_layers.json
        try:
            autocad_style = self.ref_managers.layer_style.get_layer_autocad_style(layer.name())
            if autocad_style:
                # Конвертируем стиль из БД в формат AutoCAD атрибутов
                line_color_rgb = autocad_style.get('line_color_RGB', '255,0,0')
                color_index = self._rgb_to_autocad_color(line_color_rgb)

                line_weight_mm = autocad_style.get('line_global_weight', 1.0)
                lineweight = int(line_weight_mm * 100)

                hatch = autocad_style.get('hatch', '-')
                if hatch == '-' or not hatch:
                    hatch = None
                elif isinstance(hatch, str) and hatch.upper() == 'SOLID':
                    # Legacy: SOLID в Штриховке игнорируется (заливка через 'fill')
                    hatch = None

                hatch_color_rgb_str = autocad_style.get('hatch_color_RGB', '')
                hatch_color = self._rgb_to_autocad_color(hatch_color_rgb_str) if hatch_color_rgb_str and hatch_color_rgb_str != '-' else None

                # Fill (раздельная заливка)
                fill_raw = autocad_style.get('fill', 0)
                if isinstance(fill_raw, bool):
                    fill_value = 1 if fill_raw else 0
                elif isinstance(fill_raw, (int, float)):
                    fill_value = int(fill_raw)
                elif isinstance(fill_raw, str):
                    fill_value = 1 if fill_raw.strip().lower() in ('1', 'true', 'yes', 'да') else 0
                else:
                    fill_value = 0
                fill_color_rgb_str = autocad_style.get('fill_color_RGB', '')
                fill_color = self._rgb_to_autocad_color(fill_color_rgb_str) if fill_color_rgb_str and fill_color_rgb_str != '-' else None

                hatch_transparency_raw = autocad_style.get('hatch_transparency', 0)
                try:
                    hatch_transparency_val = int(hatch_transparency_raw)
                except (ValueError, TypeError):
                    hatch_transparency_val = 0

                fill_transparency_raw = autocad_style.get('fill_transparency', 0)
                try:
                    fill_transparency_val = int(fill_transparency_raw)
                except (ValueError, TypeError):
                    fill_transparency_val = 0

                hatch_angle_raw = autocad_style.get('hatch_angle', 0)
                try:
                    hatch_angle_val = int(hatch_angle_raw)
                except (ValueError, TypeError):
                    hatch_angle_val = 0

                hatch_lineweight_mm_raw = autocad_style.get('hatch_global_lineweight', 0)
                try:
                    hatch_lineweight_mm = float(hatch_lineweight_mm_raw)
                except (ValueError, TypeError):
                    hatch_lineweight_mm = 0.0
                hatch_lineweight_val = int(hatch_lineweight_mm * 100)

                return {
                    'linetype': autocad_style.get('linetype', 'CONTINUOUS'),
                    'color': color_index,
                    'lineweight': lineweight,
                    'transparency': autocad_style.get('line_transparency', 0),
                    'line_scale': autocad_style.get('line_scale', 1.0),
                    'hatch': hatch,
                    'hatch_scale': autocad_style.get('hatch_scale', 1.0),
                    'hatch_angle': hatch_angle_val,
                    'hatch_color': hatch_color,
                    'hatch_transparency': hatch_transparency_val,
                    'hatch_lineweight': hatch_lineweight_val,
                    'fill': fill_value,
                    'fill_color': fill_color,
                    'fill_transparency': fill_transparency_val,
                }
        except Exception as e:
            log_warning(f"StyleManager: Не удалось загрузить стиль для '{layer.name()}': {e}")

        # Стиль по умолчанию (красная линия 1мм)
        return {
            'linetype': 'CONTINUOUS',
            'color': 1,  # Красный
            'lineweight': 100,  # 1.00мм
            'transparency': 0,
            'line_scale': 1.0,
            'hatch': None,
            'hatch_scale': 1.0,
            'hatch_angle': 0,
            'hatch_lineweight': 0,
        }
