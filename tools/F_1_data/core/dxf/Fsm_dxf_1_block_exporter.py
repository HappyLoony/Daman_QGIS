# -*- coding: utf-8 -*-
"""
Субмодуль 1: Экспорт блоков с атрибутами в DXF

Содержит функциональность для:
- Создания блоков (BLOCK) с геометрией и атрибутами (ATTDEF)
- Вставки блоков в modelspace с заполненными атрибутами
- Экспорта объектов ЗУ, ОКС, ЗОУИТ через блоки
- Расчёта высоты текста атрибутов на основе масштаба проекта
"""

import random
import string
from typing import Dict, Any, Optional
from qgis.core import QgsFeature, QgsVectorLayer, QgsCoordinateTransform, QgsWkbTypes

from Daman_QGIS.utils import log_debug, log_warning
from Daman_QGIS.managers import CoordinatePrecisionManager as CPM
from Daman_QGIS.constants import DXF_BLOCK_ATTR_TEXT_HEIGHT


class DxfBlockExporter:
    """Экспортёр блоков с атрибутами для DXF"""

    def __init__(self, hatch_manager=None, label_exporter=None, ref_managers=None):
        """
        Инициализация экспортёра блоков

        Args:
            hatch_manager: Менеджер штриховок (опционально)
            label_exporter: Экспортёр подписей (опционально)
            ref_managers: Reference managers для доступа к базам данных (опционально)
        """
        self.hatch_manager = hatch_manager
        self.label_exporter = label_exporter
        self.ref_managers = ref_managers

    def export_feature_as_block(self, feature: QgsFeature, layer: QgsVectorLayer,
                               layer_name: str, doc, msp,
                               crs_transform: Optional[QgsCoordinateTransform] = None,
                               style: Optional[Dict[str, Any]] = None,
                               full_name: Optional[str] = None,
                               coordinate_precision: int = 2,
                               label_scale_factor: float = 1.0):
        """
        Экспорт одного объекта через BLOCK с атрибутами

        ЛОГИКА:
        1. Создаём уникальный блок с геометрией и ATTDEF
        2. Вставляем блок в центроид с атрибутами (ByLayer)
        3. Экспортируем штриховку на основной слой (ByLayer)
        4. Экспортируем MTEXT на слой _Номер (если есть)

        Args:
            feature: Объект QGIS
            layer: Слой QGIS
            layer_name: Имя слоя DXF (layer_name_autocad из Base_layers.json)
            doc: Документ DXF
            msp: Modelspace DXF
            crs_transform: Трансформация СК
            style: Стиль из Base_layers.json
            full_name: Полное имя слоя (для поиска подписей в Base_labels.json)
            coordinate_precision: Точность округления координат (2 для МСК, 6 для WGS84)
            label_scale_factor: Масштабный коэффициент для подписей AutoCAD (1.0 для 1:1000)
        """
        # Получаем геометрию
        geometry = feature.geometry()

        if not geometry:
            return

        # Трансформируем СК ОДИН РАЗ (если нужно)
        if crs_transform:
            geometry.transform(crs_transform)

        # === 1. СОЗДАЁМ БЛОК С ГЕОМЕТРИЕЙ И ATTDEF ===
        # Передаём УЖЕ трансформированную геометрию (crs_transform=None)
        block_name = self._create_block_for_feature(
            doc, feature, layer, layer_name, None, style or {}, coordinate_precision  # None - геометрия уже трансформирована!
        )

        if not block_name:
            log_warning(f"Fsm_dxf_1: Не удалось создать блок для объекта")
            return

        # === 2. ВСТАВЛЯЕМ БЛОК В ЦЕНТРОИД ГЕОМЕТРИИ ===
        # Вычисляем центроид геометрии для точки вставки блока
        # ВАЖНО: Округляем insert_point для согласованности с координатами в блоке
        # Иначе после EXPLODE в AutoCAD координаты будут неокруглёнными
        centroid = geometry.centroid().asPoint()
        insert_x, insert_y = CPM.round_coordinates(centroid.x(), centroid.y(), coordinate_precision)
        insert_point = (insert_x, insert_y)

        # Собираем значения атрибутов
        attribute_values = {}
        fields = layer.fields()
        for field in fields:
            field_name = field.name()
            value = feature[field_name]
            # Конвертируем в строку (as-is)
            if value is None:
                attribute_values[field_name] = ""
            else:
                attribute_values[field_name] = str(value)

        # Вставляем блок с ByLayer стилем в центроид
        blockref = msp.add_blockref(
            block_name,
            insert=insert_point,
            dxfattribs={
                'layer': layer_name,
                'color': 256,  # ByLayer
                'linetype': 'ByLayer'
            }
        )

        # Автоматически заполняем атрибуты
        try:
            # Проверяем наличие ATTDEF в блоке
            block = doc.blocks.get(block_name)
            attdefs = list(block.query('ATTDEF'))

            if len(attdefs) > 0:
                # Метод 1: Попробуем add_auto_attribs
                blockref.add_auto_attribs(attribute_values)
                attribs = blockref.attribs

                # Если add_auto_attribs не сработал, используем ручное добавление
                if len(attribs) == 0:
                    # Метод 2: Ручное добавление через add_attrib
                    for attdef in attdefs:
                        tag = attdef.dxf.tag
                        value = attribute_values.get(tag, "")
                        # Получаем позицию из ATTDEF
                        insert = attdef.dxf.insert
                        height = attdef.dxf.height

                        # Создаём ATTRIB вручную
                        blockref.add_attrib(
                            tag=tag,
                            text=value,
                            insert=insert,
                            dxfattribs={
                                'height': height,
                                'color': 256,  # ByLayer
                                'flags': 1  # Невидимый
                            }
                        )

        except Exception as e:
            log_warning(f"Fsm_dxf_1: Ошибка заполнения атрибутов блока: {str(e)}")

        # === 3. ШТРИХОВКА ТЕПЕРЬ ДОБАВЛЯЕТСЯ ВНУТРЬ БЛОКА ===
        # См. _create_block_for_feature() - штриховка добавляется там же, где и геометрия
        # Это гарантирует что штриховка перемещается вместе с блоком при вставке

        # === 4. ЭКСПОРТИРУЕМ MULTILEADER (ВЫНОСКУ) НА СЛОЙ _Номер (ЕСЛИ ЕСТЬ) ===
        if self.label_exporter and self.ref_managers:
            # Проверяем есть ли подписи для этого слоя (используем full_name)
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

                self.label_exporter.export_label_as_multileader(
                    msp, feature, layer_name, None, label_config, label_color_rgb,
                    label_scale_factor=label_scale_factor
                )

    def _create_block_for_feature(self, doc, feature: QgsFeature, layer: QgsVectorLayer,
                                  layer_name: str, crs_transform: Optional[QgsCoordinateTransform],
                                  style: Dict[str, Any], coordinate_precision: int = 2) -> Optional[str]:
        """
        Создать блок для объекта с геометрией и атрибутами

        Структура:
        1. Создаётся уникальный блок BLOCK_{layer_name}_{ID}
        2. В блок помещается геометрия относительно (0,0) - смещённая к центроиду
        3. В блок добавляются ATTDEF для всех атрибутов (невидимые, с отступом вниз)
        4. Блок вставляется в центроид объекта

        Args:
            doc: Документ DXF
            feature: Объект QGIS
            layer: Слой QGIS
            layer_name: Имя слоя DXF
            crs_transform: Трансформация координат
            style: Стиль из Base_layers.json
            coordinate_precision: Точность округления координат (2 для МСК, 6 для WGS84)

        Returns:
            Имя созданного блока или None если ошибка
        """
        try:
            # Получаем геометрию
            geometry = feature.geometry()
            if not geometry:
                return None

            # Трансформируем СК если нужно
            if crs_transform:
                geometry.transform(crs_transform)

            # ВАЖНО: Вычисляем центроид для смещения координат
            # Геометрия в блоке должна быть относительно (0,0)
            # КРИТИЧНО: Округляем offset для согласованности с insert_point в export_feature_as_block()
            # Иначе после EXPLODE в AutoCAD: insert_point + геометрия = неокруглённые координаты
            centroid = geometry.centroid().asPoint()
            offset_x, offset_y = CPM.round_coordinates(centroid.x(), centroid.y(), coordinate_precision)

            # Генерируем уникальное имя блока
            block_name = self._generate_unique_block_id(layer_name)

            # Создаём блок
            block = doc.blocks.new(block_name)

            # Определяем размер текста атрибутов на основе масштаба проекта
            text_height = self._get_attribute_text_height()

            # === ДОБАВЛЯЕМ ГЕОМЕТРИЮ В БЛОК (ОТНОСИТЕЛЬНО 0,0) ===
            geom_type = geometry.type()

            # Настройки стиля для геометрии (явно из Base_layers.json)
            # Геометрия в блоке видимая, атрибуты будут невидимыми
            geom_attribs = {}
            if style:
                if 'color' in style:
                    geom_attribs['color'] = style['color']
                if 'linetype' in style and style['linetype'] != 'CONTINUOUS':
                    geom_attribs['linetype'] = style['linetype']
                if 'lineweight' in style:
                    geom_attribs['lineweight'] = style['lineweight']

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
                        x, y = CPM.round_coordinates(point.x() - offset_x, point.y() - offset_y, coordinate_precision)
                        # Экспортируем как CIRCLE вместо POINT
                        block.add_circle((x, y), radius=circle_radius, dxfattribs=geom_attribs)
                        # Добавляем заливку если hatch="SOLID"
                        if need_solid_fill:
                            self._add_circle_solid_fill_to_block(block, x, y, circle_radius, geom_attribs.get('layer', '0'))
                else:
                    point = geometry.asPoint()
                    x, y = CPM.round_coordinates(point.x() - offset_x, point.y() - offset_y, coordinate_precision)
                    # Экспортируем как CIRCLE вместо POINT
                    block.add_circle((x, y), radius=circle_radius, dxfattribs=geom_attribs)
                    # Добавляем заливку если hatch="SOLID"
                    if need_solid_fill:
                        self._add_circle_solid_fill_to_block(block, x, y, circle_radius, geom_attribs.get('layer', '0'))

            elif geom_type == QgsWkbTypes.LineGeometry:
                # Линии (смещаем относительно центроида)
                # МИГРАЦИЯ LINESTRING → MULTILINESTRING: упрощённый паттерн
                lines = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
                for line in lines:
                    coords = [CPM.round_coordinates(pt.x() - offset_x, pt.y() - offset_y, coordinate_precision) for pt in line]
                    if len(coords) > 1:
                        polyline = block.add_lwpolyline(coords, dxfattribs=geom_attribs)
                        if style and 'width' in style:
                            polyline.dxf.const_width = style['width']
                        # ВАЖНО: Добавляем lineweight для полилинии
                        if 'lineweight' in geom_attribs:
                            polyline.dxf.lineweight = geom_attribs['lineweight']

            elif geom_type == QgsWkbTypes.PolygonGeometry:
                # Полигоны (смещаем относительно центроида)
                # МИГРАЦИЯ POLYGON → MULTIPOLYGON: упрощённый паттерн
                polygons = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]

                for polygon in polygons:
                    if polygon:
                        # Внешний контур
                        exterior = polygon[0]
                        coords = [CPM.round_coordinates(pt.x() - offset_x, pt.y() - offset_y, coordinate_precision) for pt in exterior]
                        coords = self._remove_closing_point(coords)
                        if len(coords) > 2:
                            polyline = block.add_lwpolyline(coords, close=True, dxfattribs=geom_attribs)
                            if style and 'width' in style:
                                polyline.dxf.const_width = style['width']
                            # ВАЖНО: Добавляем lineweight для полилинии
                            if 'lineweight' in geom_attribs:
                                polyline.dxf.lineweight = geom_attribs['lineweight']

                            # === ШТРИХОВКА ВНУТРИ БЛОКА ===
                            # Добавляем штриховку прямо в блок со смещёнными координатами
                            # Это гарантирует что штриховка будет перемещаться вместе с блоком
                            hatch_value = style.get('hatch') if style else None
                            if hatch_value and hatch_value != '-' and hatch_value.strip():
                                self._add_hatch_to_block(block, coords, style)

                        # Дыры (holes) - тоже смещаем
                        for hole in polygon[1:]:
                            hole_coords = [CPM.round_coordinates(pt.x() - offset_x, pt.y() - offset_y, coordinate_precision) for pt in hole]
                            hole_coords = self._remove_closing_point(hole_coords)
                            if len(hole_coords) > 2:
                                hole_polyline = block.add_lwpolyline(hole_coords, close=True, dxfattribs=geom_attribs)
                                if style and 'width' in style:
                                    hole_polyline.dxf.const_width = style['width']
                                # ВАЖНО: Добавляем lineweight для полилинии
                                if 'lineweight' in geom_attribs:
                                    hole_polyline.dxf.lineweight = geom_attribs['lineweight']

            # === ДОБАВЛЯЕМ ATTDEF ДЛЯ ВСЕХ АТРИБУТОВ ===
            # Атрибуты НЕВИДИМЫЕ на чертеже, но доступны в свойствах блока AutoCAD
            # Размещаем атрибуты с отступом вниз от геометрии
            fields = layer.fields()
            attdef_count = 0
            y_offset = -text_height * 2  # Начальный отступ вниз (две высоты текста)
            text_spacing = text_height * 1.2  # Интервал между строками (1.2 высоты)

            for field_idx, field in enumerate(fields):
                field_name = field.name()
                try:
                    # Позиционируем атрибуты вертикально с интервалом
                    attdef = block.add_attdef(
                        tag=field_name,
                        insert=(0, y_offset - (field_idx * text_spacing)),  # Смещение вниз пропорционально размеру текста
                        dxfattribs={
                            'color': 256     # ByLayer - цвет по слою
                            # НЕ указываем layer - ATTDEF в блоке не должны иметь слой
                        }
                    )
                    # Устанавливаем текст по умолчанию и высоту через свойства
                    attdef.dxf.text = ""  # Пустое значение по умолчанию
                    attdef.dxf.height = text_height  # Высота текста
                    attdef.dxf.flags = 1  # 1 = невидимый атрибут (не отображается на чертеже, но есть в свойствах)

                    attdef_count += 1
                except Exception as e:
                    log_warning(f"Fsm_dxf_1:   Ошибка создания ATTDEF для {field_name}: {str(e)}")

            return block_name

        except Exception as e:
            log_warning(f"Fsm_dxf_1: Ошибка создания блока для объекта: {str(e)}")
            return None

    def _generate_unique_block_id(self, layer_name: str) -> str:
        """
        Генерация уникального ID для блока

        Формат: BLOCK_{layer_name}_{10-значный_код}
        Пример: BLOCK_L_1_2_1_WFS_ЗУ_A7K3M9P2X1

        Args:
            layer_name: Полное имя слоя

        Returns:
            Уникальное имя блока
        """
        # Генерация 10-значного кода (буквы + цифры)
        random_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
        block_name = f"BLOCK_{layer_name}_{random_id}"
        return block_name

    def _get_attribute_text_height(self) -> float:
        """
        Определение высоты текста атрибутов на основе масштаба проекта

        Масштаб -> Высота текста (м):
        - 1:500   -> 1.0м
        - 1:1000  -> 2.0м
        - 1:2000  -> 4.0м
        - 1:5000  -> 10.0м
        - 1:10000 -> 20.0м

        Returns:
            Высота текста в метрах
        """
        try:
            # Получаем масштаб из метаданных проекта
            from Daman_QGIS.database.project_db import ProjectDB
            from qgis.core import QgsProject
            import os

            # Находим GeoPackage
            from Daman_QGIS.managers.M_19_project_structure_manager import get_project_structure_manager
            project_home = QgsProject.instance().homePath()
            structure_manager = get_project_structure_manager()
            structure_manager.project_root = project_home
            gpkg_path = structure_manager.get_gpkg_path(create=False)

            if not gpkg_path or not os.path.exists(gpkg_path):
                raise Exception("GeoPackage не найден")

            project_db = ProjectDB(gpkg_path)
            scale_data = project_db.get_metadata('2_10_main_scale')

            if scale_data:
                scale_value = scale_data['value']
                # Преобразуем строку "1:500" в число 500
                if isinstance(scale_value, str) and ':' in scale_value:
                    scale_number = int(scale_value.split(':')[1])
                else:
                    scale_number = int(scale_value)

                # Высота текста атрибутов из constants.py
                if scale_number in DXF_BLOCK_ATTR_TEXT_HEIGHT:
                    return DXF_BLOCK_ATTR_TEXT_HEIGHT[scale_number]
                else:
                    # Для других масштабов - вычисляем пропорционально
                    # Формула: высота = масштаб / 500 (м)
                    return scale_number / 500

        except Exception as e:
            log_warning(f"Fsm_dxf_1: Не удалось определить масштаб для атрибутов: {str(e)}")

        # Значение по умолчанию
        return 2.5

    def _remove_closing_point(self, coords: list) -> list:
        """
        Удаление замыкающей точки если она дублирует первую

        Args:
            coords: Список координат [(x, y), ...]

        Returns:
            Список координат без дубля замыкающей точки
        """
        if len(coords) > 2:
            # Проверяем, совпадает ли последняя точка с первой
            if coords[0] == coords[-1]:
                return coords[:-1]  # Удаляем последнюю точку
        return coords

    def _add_hatch_to_block(self, block, coords: list, style: Dict[str, Any]) -> None:
        """
        Добавление штриховки внутрь блока

        ВАЖНО: Штриховка добавляется в блок (не в msp!), чтобы она
        перемещалась вместе с геометрией при вставке блока.

        Args:
            block: Объект блока DXF (doc.blocks.new())
            coords: Координаты контура (уже смещённые относительно 0,0)
            style: Стиль из Base_layers.json с параметрами штриховки
        """
        try:
            hatch_type = style.get('hatch', 'SOLID')
            hatch_scale = style.get('hatch_scale', 1.0)

            # Получаем цвет из стиля
            color_value = style.get('color', 256)  # 256 = ByLayer по умолчанию

            # Создаём штриховку в блоке
            hatch = block.add_hatch()

            # Устанавливаем цвет штриховки
            if color_value < 0:
                # True Color (отрицательное значение = RGB)
                rgb_value = -color_value
                r = (rgb_value >> 16) & 0xFF
                g = (rgb_value >> 8) & 0xFF
                b = rgb_value & 0xFF
                hatch.rgb = (r, g, b)
                log_debug(f"Fsm_dxf_1: Штриховка цвет RGB({r},{g},{b})")
            else:
                # ACI индекс или ByLayer
                hatch.dxf.color = color_value

            # Устанавливаем паттерн
            if hatch_type == 'SOLID':
                hatch.set_pattern_fill('SOLID')
            else:
                hatch.set_pattern_fill(hatch_type, scale=hatch_scale)

            # Добавляем контур как границу штриховки
            hatch.paths.add_polyline_path(coords, is_closed=True)

            log_debug(f"Fsm_dxf_1: Штриховка {hatch_type} добавлена в блок")

        except Exception as e:
            log_warning(f"Fsm_dxf_1: Ошибка добавления штриховки в блок: {str(e)}")

    def _add_circle_solid_fill_to_block(self, block, x: float, y: float, radius: float, layer_name: str):
        """
        Добавляет заливку круга через HATCH с круговой границей внутрь блока

        Используется для точек с hatch="SOLID" в Base_layers.json.
        HATCH создаётся в блоке, цвет наследуется от слоя (ByLayer).

        Args:
            block: Объект блока DXF
            x: X-координата центра (относительно центроида блока)
            y: Y-координата центра (относительно центроида блока)
            radius: Радиус круга
            layer_name: Имя слоя DXF
        """
        try:
            # Создаём HATCH с ByLayer цветом (256) в блоке
            hatch = block.add_hatch(dxfattribs={'layer': layer_name, 'color': 256})
            # Добавляем круговую границу через edge_path с полной дугой (0-360 градусов)
            edge_path = hatch.paths.add_edge_path()
            edge_path.add_arc(center=(x, y), radius=radius, start_angle=0, end_angle=360)
        except Exception as e:
            log_debug(f"Fsm_dxf_1: Не удалось создать заливку круга в блоке: {e}")
