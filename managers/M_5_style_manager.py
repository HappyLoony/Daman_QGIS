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
from Daman_QGIS.managers.M_4_reference_manager import get_reference_managers
from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers.submodules.Msm_5_1_autocad_to_qgis_converter import AutoCADToQGISConverter

# Импорты только для type hints (избегаем циклических импортов и runtime overhead)
if TYPE_CHECKING:
    from qgis.PyQt.QtGui import QColor
    from qgis.PyQt.QtCore import Qt


class StyleManager:
    """
    Единая точка входа для работы со стилями слоев

    Примеры использования:
        >>> manager = StyleManager()
        >>> manager.apply_qgis_style(layer, "L_1_1_1_Границы_работ")
        >>> mapinfo = manager.get_mapinfo_style("L_2_2_1_КАТ_Сельхоз")
    """

    def __init__(self):
        """Инициализация менеджера стилей"""
        self.converter = AutoCADToQGISConverter()
        self.ref_managers = get_reference_managers()

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
            >>> success = manager.apply_qgis_style(layer, "L_2_2_1_КАТ_Сельхоз")
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
            if expected_geom_type not in ['Point', 'LineString', 'Line', 'Polygon', 'MultiPolygon']:
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
            if geom_type == 0:  # Point
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
            if 'ЗОУИТ' in layer_name or layer_name.startswith('Le_1_2_5_'):
                merged_renderer = QgsMergedFeatureRenderer(renderer)
                layer.setRenderer(merged_renderer)
            else:
                layer.setRenderer(renderer)

            # КРИТИЧЕСКИ ВАЖНО: Сохраняем AutoCAD стиль в customProperty слоя
            # Это необходимо для корректного экспорта в DXF
            self._save_autocad_properties_to_layer(layer, style)

            # ПРИМЕЧАНИЕ: triggerRepaint() НЕ вызываем из-за краша с ЗОУИТ слоями
            # Слой обновится автоматически при следующей перерисовке карты

            return True

        except Exception as e:
            log_error(f"StyleManager: Ошибка применения renderer для '{layer_name}': {e}")
            return False

    def get_mapinfo_style(self, layer_name: str) -> Optional[str]:
        """
        Получить MapInfo стиль для экспорта TAB

        ВАЖНО: MapInfo стили используются ТОЛЬКО для экспорта TAB (F_6_1).
        Для визуализации в QGIS используется apply_qgis_style().

        Args:
            layer_name: Полное имя слоя (например "L_2_2_1_КАТ_Сельхоз")

        Returns:
            Строка MapInfo стиля (например "Brush(1, 255, 16777215) Pen(1, 2, 0)")
            или None если слой не найден

        Examples:
            >>> manager = StyleManager()
            >>> mapinfo = manager.get_mapinfo_style("L_2_2_1_КАТ_Сельхоз")
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
        from qgis.core import QgsLineSymbol, QgsSimpleLineSymbolLayer, QgsUnitTypes
        from qgis.PyQt.QtCore import Qt

        try:
            if pen_style is None:
                pen_style = Qt.SolidLine

            # Создаем линейный символ
            symbol = QgsLineSymbol.createSimple({})
            line_layer = QgsSimpleLineSymbolLayer()

            line_layer.setColor(color)
            line_layer.setWidth(width_mm)
            line_layer.setWidthUnit(QgsUnitTypes.RenderMillimeters)
            line_layer.setPenStyle(pen_style)
            line_layer.setPenJoinStyle(Qt.RoundJoin)
            line_layer.setPenCapStyle(Qt.RoundCap)

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
        from qgis.core import QgsMarkerSymbol, QgsSimpleMarkerSymbolLayer, QgsUnitTypes

        try:
            # Создаем маркерный символ
            symbol = QgsMarkerSymbol.createSimple({})
            marker_layer = symbol.symbolLayer(0)

            marker_layer.setColor(color)
            marker_layer.setSize(size_mm)
            marker_layer.setSizeUnit(QgsUnitTypes.RenderMillimeters)

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
        from qgis.core import QgsFillSymbol, QgsSimpleFillSymbolLayer, QgsUnitTypes

        try:
            # Создаем полигональный символ
            symbol = QgsFillSymbol.createSimple({})
            fill_layer = symbol.symbolLayer(0)

            fill_layer.setFillColor(fill_color)
            fill_layer.setStrokeColor(stroke_color)
            fill_layer.setStrokeWidth(stroke_width_mm)
            fill_layer.setStrokeWidthUnit(QgsUnitTypes.RenderMillimeters)

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
        # Ключи для customProperty (для совместимости с DXF экспортом)
        PROP_LINETYPE = "autocad/linetype"
        PROP_COLOR = "autocad/color"
        PROP_LINEWEIGHT = "autocad/lineweight"
        PROP_TRANSPARENCY = "autocad/transparency"
        PROP_LINE_SCALE = "autocad/line_scale"
        PROP_HATCH = "autocad/hatch"
        PROP_HATCH_SCALE = "autocad/hatch_scale"

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

        # Hatch: преобразуем "-" в None
        hatch = autocad_style.get('hatch', '-')
        if hatch == '-' or not hatch or (isinstance(hatch, str) and not hatch.strip()):
            hatch = None

        hatch_scale = autocad_style.get('hatch_scale', 1.0)

        # Сохраняем в customProperty
        layer.setCustomProperty(PROP_LINETYPE, linetype)
        layer.setCustomProperty(PROP_COLOR, color_index)
        layer.setCustomProperty(PROP_LINEWEIGHT, lineweight)
        layer.setCustomProperty(PROP_TRANSPARENCY, transparency)
        layer.setCustomProperty(PROP_LINE_SCALE, line_scale)

        if hatch:
            layer.setCustomProperty(PROP_HATCH, hatch)
            layer.setCustomProperty(PROP_HATCH_SCALE, hatch_scale)
        else:
            # Удаляем hatch если его нет
            layer.removeCustomProperty(PROP_HATCH)
            layer.removeCustomProperty(PROP_HATCH_SCALE)

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

        # Константы для customProperty (должны совпадать с _save_autocad_properties_to_layer)
        PROP_LINETYPE = 'autocad/linetype'

        # Проверяем все векторные слои в проекте
        for layer_id, layer in QgsProject.instance().mapLayers().items():
            if isinstance(layer, QgsVectorLayer):
                # Проверяем наличие сохраненного AutoCAD стиля
                linetype = layer.customProperty(PROP_LINETYPE)
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

        Examples:
            >>> manager = StyleManager()
            >>> style = manager.get_autocad_attributes(layer)
            >>> print(style['linetype'], style['color'])
        """
        # Константы для customProperty (должны совпадать с _save_autocad_properties_to_layer)
        PROP_LINETYPE = "autocad/linetype"
        PROP_COLOR = "autocad/color"
        PROP_LINEWEIGHT = "autocad/lineweight"
        PROP_TRANSPARENCY = "autocad/transparency"
        PROP_LINE_SCALE = "autocad/line_scale"
        PROP_HATCH = "autocad/hatch"
        PROP_HATCH_SCALE = "autocad/hatch_scale"

        # Проверяем наличие сохраненных AutoCAD атрибутов в customProperty
        linetype = layer.customProperty(PROP_LINETYPE)
        if linetype:
            # Есть сохраненные атрибуты - возвращаем их
            hatch_value = layer.customProperty(PROP_HATCH)

            # Преобразуем "-" в None для hatch
            if hatch_value == '-' or (isinstance(hatch_value, str) and not hatch_value.strip()):
                hatch_value = None

            return {
                'linetype': linetype,
                'color': layer.customProperty(PROP_COLOR, 1),
                'lineweight': layer.customProperty(PROP_LINEWEIGHT, 100),
                'transparency': layer.customProperty(PROP_TRANSPARENCY, 0),
                'line_scale': layer.customProperty(PROP_LINE_SCALE, 1.0),
                'hatch': hatch_value,
                'hatch_scale': layer.customProperty(PROP_HATCH_SCALE, 1.0)
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

                return {
                    'linetype': autocad_style.get('linetype', 'CONTINUOUS'),
                    'color': color_index,
                    'lineweight': lineweight,
                    'transparency': autocad_style.get('line_transparency', 0),
                    'line_scale': autocad_style.get('line_scale', 1.0),
                    'hatch': hatch,
                    'hatch_scale': autocad_style.get('hatch_scale', 1.0)
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
            'hatch_scale': 1.0
        }
