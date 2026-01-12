# -*- coding: utf-8 -*-
"""
Субмодуль 2: Экспорт простой геометрии в DXF

Содержит функциональность для:
- Экспорта точек, линий и полигонов напрямую в modelspace (без блоков)
- Применения стилей к геометрии (цвет, толщина, тип линии)
- Экспорта дыр (holes) в полигонах
- Удаления замыкающих точек из контуров полигонов
"""

from typing import Dict, Any, Optional, List, Tuple
from qgis.core import QgsFeature, QgsVectorLayer, QgsCoordinateTransform, QgsWkbTypes

from Daman_QGIS.utils import log_debug
from Daman_QGIS.managers import CoordinatePrecisionManager as CPM


class DxfGeometryExporter:
    """Экспортёр простой геометрии для DXF (без блоков)"""

    def __init__(self, hatch_manager=None, label_exporter=None, ref_managers=None):
        """
        Инициализация экспортёра геометрии

        Args:
            hatch_manager: Менеджер штриховок (опционально)
            label_exporter: Экспортёр подписей (опционально)
            ref_managers: Reference managers для доступа к Base_labels.json
        """
        self.hatch_manager = hatch_manager
        self.label_exporter = label_exporter
        self.ref_managers = ref_managers
        # Множество экспортированных координат точек для дедупликации
        # Ключ: (layer_name, x, y) - чтобы дедупликация была per-layer
        self._exported_points: set = set()

    def clear_point_cache(self):
        """Очистка кэша экспортированных точек. Вызывать перед экспортом нового файла."""
        self._exported_points.clear()

    def export_simple_geometry(self, feature: QgsFeature, layer: QgsVectorLayer,
                              layer_name: str, doc, msp,
                              crs_transform: Optional[QgsCoordinateTransform] = None,
                              style: Optional[Dict[str, Any]] = None,
                              full_name: Optional[str] = None,
                              coordinate_precision: int = 2,
                              label_scale_factor: float = 1.0):
        """
        Экспорт объекта как ПРОСТОЙ ГЕОМЕТРИИ (без блоков)

        Используется для всех слоев КРОМЕ ЗУ, ОКС и ЗОУИТ.
        Геометрия экспортируется напрямую в modelspace без использования блоков.

        Args:
            feature: Объект QGIS
            layer: Слой QGIS
            layer_name: Имя слоя DXF (layer_name_autocad из Base_layers.json)
            doc: Документ DXF
            msp: Modelspace DXF
            crs_transform: Трансформация СК
            style: Стиль из Base_layers.json со значениями:
                - color: цвет (1-255)
                - linetype: тип линии ('CONTINUOUS', 'DASHED', и т.д.)
                - lineweight: толщина линии (100 = 1.00мм)
                - width: глобальная ширина полилиний
                - hatch: паттерн штриховки ('SOLID', 'ANSI31', и т.д.)
            full_name: Полное имя слоя (для поиска подписей в Base_labels.json)
            coordinate_precision: Точность округления координат (2 для МСК, 6 для WGS84)
            label_scale_factor: Масштабный коэффициент для подписей AutoCAD (1.0 для 1:1000)
        """
        # Получаем геометрию
        geometry = feature.geometry()

        if not geometry:
            return

        # Трансформируем СК если нужно
        if crs_transform:
            geometry.transform(crs_transform)

        # Настройки стиля для геометрии
        geom_attribs = {'layer': layer_name, 'color': 256}  # ByLayer
        if style:
            # linetype и lineweight наследуются от слоя через ByLayer
            # Но можем явно задать если нужно
            pass

        geom_type = geometry.type()

        # === ЭКСПОРТ ГЕОМЕТРИИ НАПРЯМУЮ В MODELSPACE ===
        if geom_type == QgsWkbTypes.PointGeometry:
            # Точки экспортируются как CIRCLE (окружность)
            # Параметры из style:
            # - line_scale: диаметр круга (мм), по умолчанию 1.5
            # - line_global_weight: толщина линии окружности (0 = тонкая)
            # - hatch: "SOLID" = заливка, "-" = без заливки
            circle_diameter = style.get('line_scale', 1.5) if style else 1.5
            circle_radius = circle_diameter / 2.0

            # Проверяем нужна ли заливка круга
            hatch_value = style.get('hatch', '-') if style else '-'
            need_solid_fill = hatch_value == 'SOLID'

            if geometry.isMultipart():
                points = geometry.asMultiPoint()
                for point in points:
                    x, y = CPM.round_coordinates(point.x(), point.y(), coordinate_precision)
                    point_key = (layer_name, x, y)
                    if point_key not in self._exported_points:
                        # Экспортируем как CIRCLE вместо POINT
                        msp.add_circle((x, y), radius=circle_radius, dxfattribs=geom_attribs)
                        # Добавляем заливку если hatch="SOLID"
                        if need_solid_fill:
                            self._add_circle_solid_fill(msp, x, y, circle_radius, layer_name)
                        self._exported_points.add(point_key)
            else:
                point = geometry.asPoint()
                x, y = CPM.round_coordinates(point.x(), point.y(), coordinate_precision)
                point_key = (layer_name, x, y)
                if point_key not in self._exported_points:
                    # Экспортируем как CIRCLE вместо POINT
                    msp.add_circle((x, y), radius=circle_radius, dxfattribs=geom_attribs)
                    # Добавляем заливку если hatch="SOLID"
                    if need_solid_fill:
                        self._add_circle_solid_fill(msp, x, y, circle_radius, layer_name)
                    self._exported_points.add(point_key)

        elif geom_type == QgsWkbTypes.LineGeometry:
            # Линии
            # МИГРАЦИЯ LINESTRING → MULTILINESTRING: упрощённый паттерн
            lines = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
            for line in lines:
                coords = [CPM.round_coordinates(pt.x(), pt.y(), coordinate_precision) for pt in line]
                if len(coords) > 1:
                    polyline = msp.add_lwpolyline(coords, dxfattribs=geom_attribs)
                    if style and 'width' in style:
                        polyline.dxf.const_width = style['width']

        elif geom_type == QgsWkbTypes.PolygonGeometry:
            # Полигоны
            # МИГРАЦИЯ POLYGON → MULTIPOLYGON: упрощённый паттерн
            polygons = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]

            for polygon in polygons:
                if polygon:
                    # Внешний контур
                    exterior = polygon[0]
                    coords = [CPM.round_coordinates(pt.x(), pt.y(), coordinate_precision) for pt in exterior]
                    coords = self._remove_closing_point(coords)
                    if len(coords) > 2:
                        polyline = msp.add_lwpolyline(coords, close=True, dxfattribs=geom_attribs)
                        if style and 'width' in style:
                            polyline.dxf.const_width = style['width']

                    # Дыры (holes)
                    for hole in polygon[1:]:
                        hole_coords = [CPM.round_coordinates(pt.x(), pt.y(), coordinate_precision) for pt in hole]
                        hole_coords = self._remove_closing_point(hole_coords)
                        if len(hole_coords) > 2:
                            hole_polyline = msp.add_lwpolyline(hole_coords, close=True, dxfattribs=geom_attribs)
                            if style and 'width' in style:
                                hole_polyline.dxf.const_width = style['width']

        # === ЭКСПОРТ ШТРИХОВКИ (для полигонов) ===
        if geom_type == QgsWkbTypes.PolygonGeometry and style and self.hatch_manager:
            # Проверяем что есть паттерн штриховки в базе данных
            hatch_value = style.get('hatch')

            if hatch_value and hatch_value != '-' and hatch_value.strip():
                # Получаем координаты для штриховки
                # МИГРАЦИЯ POLYGON → MULTIPOLYGON: упрощённый паттерн
                polygons = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]

                for polygon in polygons:
                    if polygon:
                        exterior = polygon[0]
                        coords = [CPM.round_coordinates(pt.x(), pt.y(), coordinate_precision) for pt in exterior]
                        coords = self._remove_closing_point(coords)

                        if len(coords) > 2:
                            # Штриховка с ByLayer (наследует цвет от слоя)
                            hatch_attribs = {'layer': layer_name}
                            self.hatch_manager.apply_hatch(msp, coords, style, hatch_attribs)

        # === ЭКСПОРТ ПОДПИСЕЙ НА СЛОЙ _Номер ===
        if self.label_exporter and self.ref_managers:
            # Проверяем есть ли подписи для этого слоя
            search_name = full_name if full_name else layer_name
            label_config = self.ref_managers.label.get_label_config(search_name)

            if label_config and label_config.get('label_field') and label_config.get('label_field') != '-':
                # Получаем цвет ПОДПИСЕЙ из Base_labels.json (label_font_color_RGB)
                # НЕ используем цвет геометрии слоя - подписи имеют собственный цвет
                label_color_rgb = None
                label_color_str = label_config.get('label_font_color_RGB')
                if label_color_str and label_color_str != '-':
                    try:
                        r, g, b = map(int, label_color_str.split(','))
                        label_color_rgb = (r, g, b)
                    except (ValueError, AttributeError):
                        # Если ошибка парсинга - чёрный цвет по умолчанию
                        label_color_rgb = (0, 0, 0)

                # Все подписи экспортируем как MULTILEADER (выноска со стрелкой)
                # включая точки - стрелка указывает на точку
                self.label_exporter.export_label_as_multileader(
                    msp, feature, layer_name, None, label_config, label_color_rgb,
                    label_scale_factor=label_scale_factor
                )

    def _add_circle_solid_fill(self, msp, x: float, y: float, radius: float, layer_name: str):
        """
        Добавляет заливку круга через HATCH с круговой границей

        Используется для точек с hatch="SOLID" в Base_layers.json.
        HATCH создаётся на том же слое что и CIRCLE, цвет наследуется от слоя (ByLayer).

        Args:
            msp: Modelspace DXF
            x: X-координата центра
            y: Y-координата центра
            radius: Радиус круга
            layer_name: Имя слоя DXF
        """
        try:
            # Создаём HATCH с ByLayer цветом (256)
            hatch = msp.add_hatch(dxfattribs={'layer': layer_name, 'color': 256})
            # Добавляем круговую границу через edge_path с полной дугой (0-360 градусов)
            edge_path = hatch.paths.add_edge_path()
            edge_path.add_arc(center=(x, y), radius=radius, start_angle=0, end_angle=360)
        except Exception as e:
            log_debug(f"Fsm_dxf_2: Не удалось создать заливку круга: {e}")

    def _remove_closing_point(self, coords: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        """
        Удаляет последнюю точку если она совпадает с первой (замыкающая точка)

        В DXF полигоны замыкаются автоматически через параметр close=True,
        поэтому дублирующую последнюю точку нужно убрать.

        Args:
            coords: Список координат [(x1, y1), (x2, y2), ...]

        Returns:
            Список координат без замыкающей точки
        """
        if len(coords) > 1 and coords[0] == coords[-1]:
            return coords[:-1]
        return coords
