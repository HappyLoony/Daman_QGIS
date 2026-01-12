# -*- coding: utf-8 -*-
"""
Субмодуль 3: Экспорт подписей в DXF

Содержит функциональность для:
- Экспорта подписей как MULTILEADER (выноски) с bold italic форматированием
- Определения позиции подписи в зависимости от типа геометрии
- Применения параметров стиля текста из Base_labels.json
"""

from typing import Dict, Any, Optional, Tuple
from qgis.core import QgsFeature, QgsCoordinateTransform, QgsWkbTypes, QgsGeometry, QgsPointXY
from ezdxf.render import mleader
from ezdxf.render.arrows import ARROWS  # Стрелки для MULTILEADER
from ezdxf.math import Vec2

from Daman_QGIS.utils import log_debug


class DxfLabelExporter:
    """Экспортёр подписей для DXF как выносок (MULTILEADER)"""

    def __init__(self):
        """Инициализация экспортёра подписей"""
        pass

    def _get_label_position(self, geometry) -> Optional[Tuple[float, float]]:
        """
        Определяет позицию подписи в зависимости от типа геометрии

        Args:
            geometry: Геометрия QGIS

        Returns:
            Кортеж (x, y) с координатами позиции подписи или None
        """
        try:
            geom_type = geometry.type()

            if geom_type == QgsWkbTypes.PointGeometry:
                # Для точек - сама точка
                if geometry.isMultipart():
                    points = geometry.asMultiPoint()
                    if points:
                        return (points[0].x(), points[0].y())
                    else:
                        return None
                else:
                    point = geometry.asPoint()
                    return (point.x(), point.y())

            elif geom_type == QgsWkbTypes.LineGeometry:
                # Для линий - середина линии
                # МИГРАЦИЯ LINESTRING → MULTILINESTRING: упрощённый паттерн
                lines = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
                if lines and len(lines[0]) > 0:
                    # Берём первую линию, середину
                    line = lines[0]
                    mid_idx = len(line) // 2
                    return (line[mid_idx].x(), line[mid_idx].y())
                else:
                    return None

            elif geom_type == QgsWkbTypes.PolygonGeometry:
                # Для полигонов - центроид
                centroid = geometry.centroid()
                point = centroid.asPoint()
                return (point.x(), point.y())
            else:
                return None

        except Exception as e:
            log_debug(f"Ошибка определения позиции подписи: {str(e)}")
            return None

    def export_label_as_multileader(self, msp, feature: QgsFeature, layer_name: str,
                                   crs_transform: Optional[QgsCoordinateTransform],
                                   label_config: Dict[str, Any],
                                   layer_color_rgb: Optional[tuple] = None,
                                   label_scale_factor: float = 1.0) -> bool:
        """
        Экспорт подписи как MULTILEADER (выноска) на слой {layer_name}_Номер

        Args:
            msp: Пространство модели DXF
            feature: Объект QGIS
            layer_name: Имя слоя DXF (например, "_ЗУ_КПТ")
            crs_transform: Трансформация координат (или None)
            label_config: Конфигурация подписей из Base_labels.json со значениями:
                - label_field: имя поля с текстом подписи
                - label_font_size: размер шрифта и стрелки (по умолчанию 4.0)
                - label_font_family: семейство шрифта (по умолчанию 'GOST 2.304')
                - label_auto_wrap_length: длина автопереноса (по умолчанию 50)
                - label_dogleg_length: длина полки выноски (по умолчанию 5.0)
                - label_landing_gap: отступ от текста (по умолчанию 2.0)
            layer_color_rgb: RGB tuple (r, g, b) основного слоя для применения к слою надписей
            label_scale_factor: Масштабный коэффициент для высоты текста AutoCAD
                                (0.5 для 1:500, 1.0 для 1:1000, 2.0 для 1:2000)

        Returns:
            True если успешно экспортирована выноска, False в противном случае
        """
        try:
            # Проверяем что есть поле для подписи
            label_field = label_config.get('label_field')
            if not label_field or label_field == '-':
                return False

            # Проверяем существование поля в объекте
            field_names = feature.fields().names()
            if label_field not in field_names:
                log_debug(f"MULTILEADER: Поле '{label_field}' не найдено в объекте. Доступные поля: {', '.join(field_names)}")
                return False

            # Получаем текст подписи из атрибута
            label_text = str(feature[label_field]) if feature[label_field] else ""
            if not label_text:
                return False

            # Получаем геометрию
            geometry = feature.geometry()
            if not geometry:
                return False

            # Трансформируем СК если нужно
            if crs_transform:
                geometry.transform(crs_transform)

            # Определяем позицию центроида (базовая точка - КУДА УКАЗЫВАЕТ СТРЕЛКА)
            centroid_position = self._get_label_position(geometry)
            if not centroid_position:
                return False

            # Стрелка указывает на центроид
            leader_start = centroid_position

            # Определяем ближайшую вершину границы (для вычисления направления смещения текста)
            boundary_vertex = self._get_nearest_boundary_vertex(geometry, centroid_position)

            # Смещаем текст от центроида НАРУЖУ (в противоположную сторону от границы)
            if boundary_vertex:
                # Вектор ОТ границы К центроиду
                dx = centroid_position[0] - boundary_vertex[0]
                dy = centroid_position[1] - boundary_vertex[1]
                length = (dx**2 + dy**2)**0.5

                if length < 1.0:  # Если центроид очень близко к границе
                    # Смещаем текст на фиксированное расстояние (10 метров) вправо
                    text_position = (centroid_position[0] + 10.0, centroid_position[1])
                else:
                    # Смещаем текст ОТ центроида НАРУЖУ (в направлении от границы)
                    offset = 10.0
                    text_position = (
                        centroid_position[0] + (dx / length) * offset,
                        centroid_position[1] + (dy / length) * offset
                    )
            else:
                # Если не удалось найти границу - смещаем вправо
                text_position = (centroid_position[0] + 10.0, centroid_position[1])

            # Получаем параметры выноски из label_config
            # Базовая высота текста из конфига
            base_char_height = label_config.get('label_font_size', 4.0)
            # Применяем масштабный коэффициент для AutoCAD
            # (1:500 -> 0.5, 1:1000 -> 1.0, 1:2000 -> 2.0)
            char_height = base_char_height * label_scale_factor
            font_family = label_config.get('label_font_family', 'GOST 2.304')
            dogleg_length = 0.0  # Длина полки = 0 (без полки)
            landing_gap = 0.0  # Отступ от текста = 0
            arrow_size = char_height  # Размер стрелки равен высоте текста

            # Ширина текстового блока для автопереноса
            auto_wrap_length = label_config.get('label_auto_wrap_length', 50)
            text_width = auto_wrap_length * char_height * 0.6

            # Имя слоя выноски
            label_layer_name = f"{layer_name}_Номер"

            # Проверяем/создаём слой надписей
            doc = msp.doc
            if label_layer_name not in doc.layers:
                # Создаём новый слой
                label_layer = doc.layers.add(label_layer_name)
            else:
                # Получаем существующий слой
                label_layer = doc.layers.get(label_layer_name)

            # Настраиваем цвет слоя из Base_labels.json (label_font_color_RGB)
            if layer_color_rgb is not None:
                label_layer.rgb = layer_color_rgb

            # Создаём или модифицируем стиль MULTILEADER с правильными настройками line spacing
            mleader_style_name = "GOST_MLEADER"

            if mleader_style_name not in doc.mleader_styles:
                # Создаём новый стиль на основе Standard
                mleader_style = doc.mleader_styles.duplicate_entry("Standard", mleader_style_name)
            else:
                mleader_style = doc.mleader_styles.get(mleader_style_name)

            # ПРИМЕЧАНИЕ: ezdxf 1.4.2 не поддерживает line_spacing атрибуты для MLEADERSTYLE
            # Атрибуты устанавливаются только в MTEXT (см. ниже), но AutoCAD читает их из стиля
            # Пользователю потребуется вручную изменить стиль "GOST_MLEADER" в AutoCAD:
            # Формат -> Стили мультивыносок -> GOST_MLEADER -> Изменить ->
            # Содержимое -> Стиль межстрочного интервала: "Точный", Межстрочный интервал: 1

            # Создаём MULTILEADER builder с использованием стиля
            ml_builder = msp.add_multileader_mtext(style=mleader_style_name)

            # Настраиваем текст со стилем "GOST 2.304"
            # Текст подписи используется напрямую без MTEXT-форматирования
            ml_builder.set_content(
                label_text,
                style="GOST 2.304",  # Используем стиль текста GOST (имя должно совпадать с созданным в dxf_exporter)
                char_height=char_height,
                alignment=mleader.TextAlignment.center  # Выравнивание по центру
            )

            # Определяем сторону присоединения выноски
            # Если текст правее точки начала - присоединяем слева, иначе справа
            connection_side = mleader.ConnectionSide.left if text_position[0] > leader_start[0] else mleader.ConnectionSide.right

            # Добавляем линию выноски (от геометрии к тексту)
            ml_builder.add_leader_line(
                connection_side,
                [Vec2(leader_start[0], leader_start[1])]  # Начальная точка выноски
            )

            # Настраиваем стрелку (ПОСЛЕ add_leader_line)
            ml_builder.set_arrow_properties(
                name=ARROWS.closed_filled,  # Заполненная стрелка (стандартная)
                size=arrow_size
            )

            # Настраиваем параметры выноски (без полки)
            ml_builder.set_connection_properties(
                dogleg_length=0.0,  # Без полки
                landing_gap=landing_gap
            )

            # Настраиваем типы присоединения текста (подчёркивание первой строки)
            ml_builder.set_connection_types(
                left=mleader.HorizontalConnection.bottom_of_top_line_underline,
                right=mleader.HorizontalConnection.bottom_of_top_line_underline
            )

            # Настраиваем свойства линий выноски
            ml_builder.set_leader_properties(
                leader_type=mleader.LeaderType.straight_lines,
                color=256  # ByLayer - цвет по слою
            )

            # ВАЖНО: build() ничего не возвращает (возвращает None), но создаёт объект в документе
            # Строим MULTILEADER с указанием позиции текста
            ml_builder.build(insert=Vec2(text_position[0], text_position[1]))

            # Получаем созданный MULTILEADER из последнего добавленного объекта
            # (build() автоматически добавляет его в msp)
            created_entities = list(msp.query('MULTILEADER'))
            if created_entities:
                multileader = created_entities[-1]  # Последний созданный
                multileader.dxf.layer = label_layer_name

                # Настраиваем MTEXT внутри MULTILEADER
                if hasattr(multileader, 'context') and hasattr(multileader.context, 'mtext'):
                    mtext = multileader.context.mtext
                    # Направление текста "По стилю" (by text style)
                    object.__setattr__(mtext, 'flow_direction', 6)
                    # Межстрочный интервал "Точный" (exact), а не "Минимальный" (at least)
                    # Используем object.__setattr__() для обхода frozen dataclass
                    object.__setattr__(mtext, 'line_spacing_style', 2)  # 1 = at least, 2 = exact
                    # Коэффициент межстрочного интервала:
                    # 1.0 = одинарный интервал (6.6667 единиц при высоте 4)
                    # 2.0 = двойной интервал (13.3333 единиц при высоте 4)
                    object.__setattr__(mtext, 'line_spacing_factor', 1.0)

                return True
            else:
                return False

        except Exception as e:
            log_debug(f"Не удалось экспортировать MULTILEADER: {str(e)}")
            return False

    def _get_nearest_boundary_vertex(self, geometry, centroid_position: Tuple[float, float]) -> Optional[Tuple[float, float]]:
        """
        Находит ближайшую вершину на границе полигона к центроиду

        Используется для определения направления смещения текста выноски

        Args:
            geometry: Геометрия QGIS
            centroid_position: Кортеж (x, y) с координатами центроида

        Returns:
            Кортеж (x, y) с координатами ближайшей вершины границы или None
        """
        try:
            geom_type = geometry.type()

            if geom_type == QgsWkbTypes.PolygonGeometry:
                # Для полигонов - ближайшая вершина на границе к центроиду
                # МИГРАЦИЯ POLYGON → MULTIPOLYGON: упрощённый паттерн
                polygons = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]
                if polygons and len(polygons[0]) > 0:
                    boundary_ring = polygons[0][0]  # Внешнее кольцо первого полигона
                else:
                    return None

                # Находим ближайшую вершину к центроиду
                min_dist = float('inf')
                closest_vertex = None

                for vertex in boundary_ring:
                    dist = ((vertex.x() - centroid_position[0])**2 + (vertex.y() - centroid_position[1])**2)**0.5
                    if dist < min_dist:
                        min_dist = dist
                        closest_vertex = vertex

                if closest_vertex:
                    return (closest_vertex.x(), closest_vertex.y())
                return None
            else:
                # Для линий и точек - возвращаем None (выноска не нужна)
                return None

        except Exception as e:
            log_debug(f"Ошибка определения ближайшей вершины границы: {str(e)}")
            return None
