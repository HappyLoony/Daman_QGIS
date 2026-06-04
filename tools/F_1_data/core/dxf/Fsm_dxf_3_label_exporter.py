# -*- coding: utf-8 -*-
"""
Субмодуль 3: Экспорт подписей в DXF

Содержит функциональность для:
- Экспорта подписей как MULTILEADER (выноски) с bold italic форматированием
- Определения позиции подписи в зависимости от типа геометрии
- Применения параметров стиля текста из Base_labels.json
"""

from typing import Dict, Any, Optional, Tuple
from qgis.core import Qgis, QgsFeature, QgsCoordinateTransform, QgsGeometry, QgsPointXY
from ezdxf.render import mleader
from ezdxf.render.arrows import ARROWS  # Стрелки для MULTILEADER
from ezdxf.math import Vec2, Vec3

from Daman_QGIS.utils import log_debug

# Имя текстового стиля выносок MULTILEADER (создаётся в dxf_exporter.py).
# Имя честное (Bold Italic = "тип Б наклонный"), чтобы НЕ занимать имя
# "GOST 2.304" - оно остаётся свободным для прямого начертания, если
# пользователю понадобится обычный текст на чертеже
GOST_MLEADER_TEXT_STYLE = 'GOST 2.304 Type B italic'


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

            if geom_type == Qgis.GeometryType.Point:
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

            elif geom_type == Qgis.GeometryType.Line:
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

            elif geom_type == Qgis.GeometryType.Polygon:
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

            # КРИТИЧНО: текст ВСЕГДА справа от точки привязки (left-attachment).
            # Right-attachment в AutoCAD рендерится корректно ТОЛЬКО при точном
            # совпадении координат llp/base_point с фактической метрикой шрифта
            # AutoCAD, которую ezdxf воспроизвести не может (движки измерения
            # расходятся ~5%). Эмпирика матриц вариантов v4-v8 (2026-06-04):
            # left-attachment устойчив к промаху оценки ширины текста (полка
            # рисуется от точки прихода выноски), right - разрыв полки/выноски.
            # Поэтому горизонтальная компонента смещения зеркалируется вправо
            # (как у точечных слоёв, у которых выноски всегда были идеальны).
            if text_position[0] <= leader_start[0] + 0.01:
                mirrored_dx = leader_start[0] - text_position[0]
                new_x = leader_start[0] + (mirrored_dx if mirrored_dx > 1.0 else 10.0)
                text_position = (new_x, text_position[1])

            # Получаем параметры выноски из label_config
            # Базовая высота текста из конфига
            base_char_height = label_config.get('label_font_size', 4.0)
            # Применяем масштабный коэффициент для AutoCAD
            # (1:500 -> 0.5, 1:1000 -> 1.0, 1:2000 -> 2.0)
            char_height = base_char_height * label_scale_factor
            font_family = label_config.get('label_font_family', 'GOST 2.304')
            landing_gap = 0.0  # Отступ от текста = 0 (ненулевой ломает рендер выноски)
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

            # Стиль мультивыноски - Standard: все свойства переопределяются
            # на уровне entity (ezdxf ставит property_override_flags=0x7FFFFFFF),
            # отдельный стиль GOST_MLEADER не давал ничего и удалён 2026-06-04
            #
            # ПРИМЕЧАНИЕ: ezdxf 1.4.2 не поддерживает line_spacing атрибуты для MLEADERSTYLE
            # Атрибуты устанавливаются только в MTEXT (см. ниже)

            # Создаём MULTILEADER builder с использованием стиля
            # Передаём layer через dxfattribs чтобы избежать post-build query
            ml_builder = msp.add_multileader_mtext(
                style="Standard",
                dxfattribs={'layer': label_layer_name}
            )

            # Определяем сторону присоединения выноски
            # Если текст правее точки начала - присоединяем слева, иначе справа
            connection_side = mleader.ConnectionSide.left if text_position[0] > leader_start[0] else mleader.ConnectionSide.right

            # Настраиваем текст со стилем выносок (GOST_MLEADER_TEXT_STYLE)
            # Текст подписи используется напрямую без MTEXT-форматирования
            # Выравнивание center - подтверждено матрицей вариантов в AutoCAD
            # 2026-06-04 (вариант K1_center_dl0): с комбо has_dogleg=1 +
            # dogleg_length=0 + landing_gap=0 центр работает корректно
            ml_builder.set_content(
                label_text,
                style=GOST_MLEADER_TEXT_STYLE,  # Стиль создаётся в dxf_exporter
                char_height=char_height,
                alignment=mleader.TextAlignment.center  # Выравнивание по центру
            )

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

            # Настраиваем параметры выноски.
            # КРИТИЧНО (комбо подтверждено матрицей вариантов в AutoCAD 2026-06-04,
            # вариант K1_center_dl0): рабочая запись = has_dogleg=1 + dogleg_length=0
            # + landing_gap=0. Полка при этом - ДИНАМИЧЕСКОЕ подчёркивание по ширине
            # текста (underline connection type), отдельный сегмент полки не нужен.
            #
            # Ловушки ezdxf, из-за которых была "разорванная полка" (выноска
            # приходила в середину полки / по диагонали сквозь текст, лечилась
            # только ручным touch свойств в AutoCAD):
            # 1. set_connection_properties(dogleg_length=0) ставит has_dogleg=0 -
            #    с этим флагом AutoCAD рендерит выноску с разрывом. Поэтому передаём
            #    ненулевую длину (только ради has_dogleg=1)...
            # 2. ...и затем явно зануляем dxf.dogleg_length (величина полки 0),
            #    т.к. ezdxf сам её не зануляет (остаётся 8.0 из стиля Standard)
            ml_builder.set_connection_properties(
                dogleg_length=8.0,  # ТОЛЬКО для установки has_dogleg=1, см. ниже
                landing_gap=landing_gap  # 0.0 - ненулевой отступ ломает рендер
            )
            ml_builder.multileader.dxf.dogleg_length = 0.0  # Величина полки = 0

            # Настраиваем типы присоединения текста (подчёркивание первой строки)
            ml_builder.set_connection_types(
                left=mleader.HorizontalConnection.bottom_of_top_line_underline,
                right=mleader.HorizontalConnection.bottom_of_top_line_underline
            )

            # Настраиваем свойства линий выноски - всё ByLayer
            ml_builder.set_leader_properties(
                leader_type=mleader.LeaderType.straight_lines,
                color=256,  # ByLayer - цвет по слою
                linetype="BYLAYER",  # Тип линии по слою (default ezdxf - BYBLOCK)
                lineweight=-1  # LINEWEIGHT_BYLAYER - вес линии по слою (default - BYBLOCK)
            )

            # ВАЖНО: build() ничего не возвращает (возвращает None), но создаёт объект в документе
            # Строим MULTILEADER с указанием позиции текста
            ml_builder.build(insert=Vec2(text_position[0], text_position[1]))

            # Получаем MULTILEADER напрямую через свойство builder (O(1) вместо O(n) query)
            multileader = ml_builder.multileader

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
                # КРИТИЧНО: word_break=0 - как пишет AutoCAD при пересчёте
                # (найдено raw-диффом против AutoCAD-recompute, 2026-06-04)
                object.__setattr__(mtext, 'use_word_break', 0)

            # КРИТИЧНО: пост-build фиксы CONTEXT_DATA (эмпирика AutoCAD 2026-06-04).
            # ezdxf builder НЕ выставляет context.text_align_type (группа 176),
            # остаётся 0 (left) при center-выравнивании текста - внутренне
            # противоречивая запись: AutoCAD при редактировании (перетаскивание
            # текста) пересчитывал привязку по left-правилам и текст съезжал
            # с полки без возможности вернуть. С 176=1 (center) перетаскивание
            # пересчитывается корректно.
            context = multileader.context
            context.text_align_type = 1  # center
            # dogleg_vector без отрицательных нулей (-0.0) - как пишет AutoCAD
            for leader_data in context.leaders:
                dv = leader_data.dogleg_vector
                leader_data.dogleg_vector = Vec3(dv.x + 0.0, dv.y + 0.0, dv.z + 0.0)

            return True

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

            if geom_type == Qgis.GeometryType.Polygon:
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
