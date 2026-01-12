# -*- coding: utf-8 -*-
"""
Fsm_1_1_3: Импорт координат из текста
Субмодуль для ручного ввода/вставки координат из буфера обмена

Best practices применены из:
- lat-lon-parser: парсинг DMS форматов
- QgsProjectionSelectionWidget: нативный выбор CRS
- gis-ops tutorials: интерактивный ввод координат
- NumericalDigitize: подсветка вершин, редактирование существующих объектов
"""

import re
from typing import List, Optional, Tuple, Dict, Any

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QGroupBox, QPlainTextEdit, QRadioButton,
    QButtonGroup, QMessageBox, QSizePolicy, QApplication,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QToolButton, QFrame, QSplitter, QWidget
)
from qgis.PyQt.QtCore import Qt, QMimeData
from qgis.PyQt.QtGui import QFont, QColor, QTextCursor, QIcon
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsPointXY, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsWkbTypes, QgsSymbol,
    QgsFillSymbol, QgsSimpleFillSymbolLayer, QgsPoint,
    QgsFeatureRequest, QgsRectangle
)
from qgis.gui import QgsProjectionSelectionWidget, QgsRubberBand, QgsMapToolEmitPoint
from qgis.utils import iface

from Daman_QGIS.utils import log_info, log_error, log_warning


class VertexHighlighter:
    """
    Подсветка вершин геометрии на карте.

    Паттерн из NumericalDigitize:
    - Контуры отображаются красной линией (QgsRubberBand LineGeometry)
    - Вершины отображаются точками (QgsRubberBand PointGeometry)
    - Текущая вершина выделяется квадратом (ICON_FULL_BOX, darkRed)
    - Остальные вершины - ромбами (ICON_FULL_DIAMOND, darkBlue)
    """

    def __init__(self, canvas, close_contour: bool = True):
        """
        Инициализация подсветки.

        Args:
            canvas: QgsMapCanvas
            close_contour: Замыкать контур (для полигонов)
        """
        self.canvas = canvas
        self.close_contour = close_contour
        self.line_highlights: List[QgsRubberBand] = []
        self.node_highlights: List[QgsRubberBand] = []
        self.feature_crs = None
        self.project_crs = canvas.mapSettings().destinationCrs()

    def create_highlight(self, points: List[QgsPointXY],
                        feature_crs: QgsCoordinateReferenceSystem,
                        current_vertex: int = 0):
        """
        Создание подсветки геометрии.

        Args:
            points: Список точек QgsPointXY
            feature_crs: CRS координат
            current_vertex: Индекс текущей вершины для выделения
        """
        self.remove_highlight()
        self.feature_crs = feature_crs

        if not points:
            return

        # Трансформация если нужна
        transform = None
        if feature_crs != self.project_crs:
            transform = QgsCoordinateTransform(
                feature_crs, self.project_crs, QgsProject.instance()
            )

        # Создаём RubberBand для контура (LineGeometry)
        line_rb = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)

        for point in points:
            display_point = self._transform_point(point, transform)
            line_rb.addPoint(display_point, True, 0)

        # Замыкание контура
        if self.close_contour and len(points) > 2:
            line_rb.closePoints(True)

        line_rb.setColor(Qt.red)
        line_rb.setWidth(2)
        self.line_highlights.append(line_rb)

        # Создаём RubberBand для каждой вершины (PointGeometry)
        for i, point in enumerate(points):
            node_rb = QgsRubberBand(self.canvas, QgsWkbTypes.PointGeometry)
            display_point = self._transform_point(point, transform)
            node_rb.addPoint(display_point, True, 0)

            # Стиль в зависимости от текущей вершины
            if i == current_vertex:
                node_rb.setIcon(QgsRubberBand.ICON_FULL_BOX)
                node_rb.setColor(Qt.darkRed)
            else:
                node_rb.setIcon(QgsRubberBand.ICON_FULL_DIAMOND)
                node_rb.setColor(Qt.darkBlue)

            node_rb.setIconSize(10)
            self.node_highlights.append(node_rb)

        self.canvas.refresh()

    def change_current_vertex(self, current_vertex: int):
        """
        Переключение текущей выделенной вершины.

        Args:
            current_vertex: Индекс новой текущей вершины
        """
        for i, rb in enumerate(self.node_highlights):
            if i == current_vertex:
                rb.setIcon(QgsRubberBand.ICON_FULL_BOX)
                rb.setColor(Qt.darkRed)
            else:
                rb.setIcon(QgsRubberBand.ICON_FULL_DIAMOND)
                rb.setColor(Qt.darkBlue)

        self.canvas.refresh()

    def remove_highlight(self):
        """Удаление всей подсветки."""
        for rb in self.line_highlights:
            self.canvas.scene().removeItem(rb)
            rb.reset(QgsWkbTypes.LineGeometry)
        self.line_highlights.clear()

        for rb in self.node_highlights:
            self.canvas.scene().removeItem(rb)
            rb.reset(QgsWkbTypes.PointGeometry)
        self.node_highlights.clear()

        self.canvas.refresh()

    def _transform_point(self, point: QgsPointXY,
                        transform: Optional[QgsCoordinateTransform]) -> QgsPointXY:
        """Трансформация точки если нужно."""
        if transform:
            qgs_point = QgsPoint(point.x(), point.y())
            qgs_point.transform(transform)
            return QgsPointXY(qgs_point)
        return point


class FeatureSelector(QgsMapToolEmitPoint):
    """
    Инструмент выбора объекта на карте для редактирования.

    Паттерн из NumericalDigitize FeatureFinderTool:
    - Клик на карте выбирает объект под курсором
    - Координаты объекта загружаются в диалог для редактирования
    """

    def __init__(self, canvas, callback):
        """
        Инициализация инструмента.

        Args:
            canvas: QgsMapCanvas
            callback: Функция обратного вызова (feature) -> None
        """
        super().__init__(canvas)
        self.canvas = canvas
        self.callback = callback

    def canvasReleaseEvent(self, event):
        """Обработка клика на карте."""
        point = self.toMapCoordinates(event.pos())

        layer = self.canvas.currentLayer()
        if not layer or not isinstance(layer, QgsVectorLayer):
            return

        # Создаём небольшой прямоугольник вокруг точки клика
        # Размер зависит от масштаба карты
        map_units_per_pixel = self.canvas.mapUnitsPerPixel()
        tolerance = map_units_per_pixel * 10  # 10 пикселей

        search_rect = QgsRectangle(
            point.x() - tolerance, point.y() - tolerance,
            point.x() + tolerance, point.y() + tolerance
        )

        # Трансформация в CRS слоя если нужно
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        layer_crs = layer.crs()

        if canvas_crs != layer_crs:
            transform = QgsCoordinateTransform(
                canvas_crs, layer_crs, QgsProject.instance()
            )
            search_rect = transform.transformBoundingBox(search_rect)

        # Поиск объектов
        request = QgsFeatureRequest()
        request.setFilterRect(search_rect)
        request.setFlags(QgsFeatureRequest.ExactIntersect)

        features = list(layer.getFeatures(request))

        if features:
            # Берём первый найденный объект
            self.callback(features[0], layer)
        else:
            log_warning("Fsm_1_1_3: Объект не найден под курсором")


class Fsm_1_1_3_CoordinateInput:
    """
    Класс для импорта координат из текстового ввода.

    Поддерживает:
    - Различные форматы координат (десятичные, градусы-минуты-секунды, метры)
    - Выбор CRS через нативный виджет QGIS
    - Переключение порядка X/Y
    - Выбор разделителя между координатами
    - Создание точек или полигонов
    - Замыкание координат для полигонов
    - Просмотр на временном слое
    - Сохранение в целевой слой
    - Копирование координат в буфер обмена
    - Подсветка текущей вершины на карте
    - Редактирование координат существующих объектов
    """

    PREVIEW_LAYER_NAME = "_preview_coordinates"

    def __init__(self, parent_dialog, plugin_dir: str):
        """
        Инициализация субмодуля.

        Args:
            parent_dialog: Родительский диалог UniversalImportDialog
            plugin_dir: Путь к директории плагина
        """
        self.parent_dialog = parent_dialog
        self.plugin_dir = plugin_dir
        self.preview_layer = None
        self.current_geometries = []
        self.current_points: List[QgsPointXY] = []
        self.vertex_highlighter: Optional[VertexHighlighter] = None
        self.edit_feature: Optional[QgsFeature] = None
        self.edit_layer: Optional[QgsVectorLayer] = None

    def show_dialog(self, edit_mode: bool = False) -> bool:
        """
        Показать диалог импорта координат.

        Args:
            edit_mode: True для режима редактирования существующего объекта

        Returns:
            True если данные сохранены, False если отменено
        """
        dialog = CoordinateInputDialog(self.parent_dialog, self, edit_mode=edit_mode)
        result = dialog.exec_()

        # Очищаем при закрытии
        self._remove_preview_layer()
        self._remove_vertex_highlight()
        self.edit_feature = None
        self.edit_layer = None

        return result == QDialog.Accepted

    def copy_to_clipboard(self, points: List[QgsPointXY], delimiter: str = '\t') -> bool:
        """
        Копирование координат в буфер обмена.

        Args:
            points: Список точек для копирования
            delimiter: Разделитель между X и Y (по умолчанию табуляция)

        Returns:
            True если успешно
        """
        if not points:
            log_warning("Fsm_1_1_3: Нет координат для копирования")
            return False

        lines = []
        for point in points:
            # Формат с высокой точностью для кадастра (8 знаков)
            lines.append(f"{point.x():.8f}{delimiter}{point.y():.8f}")

        text = '\n'.join(lines)
        QApplication.clipboard().setText(text)

        log_info(f"Fsm_1_1_3: Скопировано {len(points)} координат в буфер обмена")
        return True

    def highlight_vertex(self, points: List[QgsPointXY],
                        crs: QgsCoordinateReferenceSystem,
                        current_index: int = 0,
                        is_polygon: bool = True):
        """
        Подсветка вершин на карте.

        Args:
            points: Список точек
            crs: CRS координат
            current_index: Индекс текущей вершины
            is_polygon: True для замыкания контура
        """
        if not self.vertex_highlighter:
            self.vertex_highlighter = VertexHighlighter(
                iface.mapCanvas(),
                close_contour=is_polygon
            )

        self.vertex_highlighter.close_contour = is_polygon
        self.vertex_highlighter.create_highlight(points, crs, current_index)
        self.current_points = points

    def change_highlighted_vertex(self, index: int):
        """Переключение подсвеченной вершины."""
        if self.vertex_highlighter:
            self.vertex_highlighter.change_current_vertex(index)

    def _remove_vertex_highlight(self):
        """Удаление подсветки вершин."""
        if self.vertex_highlighter:
            self.vertex_highlighter.remove_highlight()
            self.vertex_highlighter = None
        self.current_points = []

    def extract_coords_from_feature(self, feature: QgsFeature,
                                    layer: QgsVectorLayer) -> List[QgsPointXY]:
        """
        Извлечение координат из существующего объекта.

        Args:
            feature: Объект для редактирования
            layer: Слой объекта

        Returns:
            Список точек QgsPointXY
        """
        self.edit_feature = feature
        self.edit_layer = layer

        geom = feature.geometry()
        if not geom or geom.isEmpty():
            return []

        points = []
        geom_type = layer.geometryType()

        if geom_type == QgsWkbTypes.PointGeometry:
            # Точка или мультиточка
            if geom.isMultipart():
                for part in geom.constParts():
                    for vertex in part.vertices():
                        points.append(QgsPointXY(vertex.x(), vertex.y()))
            else:
                point = geom.asPoint()
                points.append(QgsPointXY(point.x(), point.y()))

        elif geom_type == QgsWkbTypes.PolygonGeometry:
            # Полигон - берём только внешний контур
            if geom.isMultipart():
                # Для MultiPolygon берём первый полигон
                multi = geom.asMultiPolygon()
                if multi and multi[0]:
                    exterior = multi[0][0]  # Внешний контур первого полигона
                    for pt in exterior:
                        points.append(pt)
            else:
                polygon = geom.asPolygon()
                if polygon:
                    exterior = polygon[0]  # Внешний контур
                    for pt in exterior:
                        points.append(pt)

            # Удаляем замыкающую точку (дубликат первой)
            if len(points) > 1 and points[0] == points[-1]:
                points = points[:-1]

        elif geom_type == QgsWkbTypes.LineGeometry:
            # Линия
            if geom.isMultipart():
                for part in geom.constParts():
                    for vertex in part.vertices():
                        points.append(QgsPointXY(vertex.x(), vertex.y()))
            else:
                line = geom.asPolyline()
                for pt in line:
                    points.append(pt)

        log_info(f"Fsm_1_1_3: Извлечено {len(points)} вершин из объекта")
        return points

    def update_feature_geometry(self, points: List[QgsPointXY],
                               source_crs: QgsCoordinateReferenceSystem) -> bool:
        """
        Обновление геометрии существующего объекта.

        Args:
            points: Новые координаты
            source_crs: CRS координат

        Returns:
            True если успешно
        """
        if not self.edit_feature or not self.edit_layer:
            log_error("Fsm_1_1_3: Нет объекта для обновления")
            return False

        if not points:
            log_error("Fsm_1_1_3: Нет координат для обновления")
            return False

        # Трансформация если нужно
        target_crs = self.edit_layer.crs()
        if source_crs != target_crs:
            transform = QgsCoordinateTransform(
                source_crs, target_crs, QgsProject.instance()
            )
            points = [self._transform_point_xy(p, transform) for p in points]

        # Создаём геометрию в зависимости от типа слоя
        geom_type = self.edit_layer.geometryType()

        if geom_type == QgsWkbTypes.PolygonGeometry:
            # Замыкаем полигон
            if points[0] != points[-1]:
                points = points + [points[0]]
            new_geom = QgsGeometry.fromPolygonXY([points])
        elif geom_type == QgsWkbTypes.LineGeometry:
            new_geom = QgsGeometry.fromPolylineXY(points)
        else:
            # Точки - берём первую
            new_geom = QgsGeometry.fromPointXY(points[0])

        if not new_geom.isGeosValid():
            log_warning("Fsm_1_1_3: Создана невалидная геометрия")
            # Пытаемся исправить
            new_geom = new_geom.makeValid()

        # Обновляем объект
        if not self.edit_layer.isEditable():
            self.edit_layer.startEditing()

        self.edit_layer.beginEditCommand("Update geometry from coordinates")
        self.edit_feature.setGeometry(new_geom)

        if self.edit_layer.updateFeature(self.edit_feature):
            self.edit_layer.endEditCommand()
            if self.edit_layer.commitChanges():
                log_info("Fsm_1_1_3: Геометрия объекта обновлена")
                return True
            else:
                log_error(f"Fsm_1_1_3: Ошибка сохранения: {self.edit_layer.commitErrors()}")
                self.edit_layer.rollBack()
                return False
        else:
            self.edit_layer.destroyEditCommand()
            log_error("Fsm_1_1_3: Не удалось обновить объект")
            return False

    def _transform_point_xy(self, point: QgsPointXY,
                           transform: QgsCoordinateTransform) -> QgsPointXY:
        """Трансформация QgsPointXY."""
        qgs_point = QgsPoint(point.x(), point.y())
        qgs_point.transform(transform)
        return QgsPointXY(qgs_point)

    def parse_coordinates(self, text: str, delimiter: str, swap_xy: bool) -> List[List[QgsPointXY]]:
        """
        Парсинг текста с координатами.

        Args:
            text: Текст с координатами
            delimiter: Разделитель между X и Y
            swap_xy: Поменять местами X и Y

        Returns:
            Список объектов, каждый объект - список точек QgsPointXY
        """
        objects = []
        current_object = []

        lines = text.strip().split('\n')

        for line in lines:
            line = line.strip()

            # Пустая строка - разделитель объектов
            if not line:
                if current_object:
                    objects.append(current_object)
                    current_object = []
                continue

            # Парсим координаты из строки
            point = self._parse_line(line, delimiter, swap_xy)
            if point:
                current_object.append(point)

        # Добавляем последний объект
        if current_object:
            objects.append(current_object)

        return objects

    def _parse_line(self, line: str, delimiter: str, swap_xy: bool) -> Optional[QgsPointXY]:
        """
        Парсинг одной строки с координатами.

        Args:
            line: Строка с координатами
            delimiter: Разделитель
            swap_xy: Поменять местами

        Returns:
            QgsPointXY или None
        """
        try:
            # Разделяем по выбранному разделителю
            if delimiter == 'tab':
                parts = line.split('\t')
            elif delimiter == 'space':
                parts = line.split()
            elif delimiter == ';':
                parts = line.split(';')
            elif delimiter == ',':
                parts = line.split(',')
            else:
                # Авто - пробуем разные разделители
                parts = self._auto_split(line)

            if len(parts) < 2:
                return None

            # Очищаем части от лишних пробелов
            parts = [p.strip() for p in parts]

            # Парсим координаты (поддержка разных форматов)
            coord1 = self._parse_coordinate(parts[0])
            coord2 = self._parse_coordinate(parts[1])

            if coord1 is None or coord2 is None:
                return None

            if swap_xy:
                return QgsPointXY(coord2, coord1)
            else:
                return QgsPointXY(coord1, coord2)

        except Exception as e:
            log_warning(f"Fsm_1_1_3: Ошибка парсинга строки '{line}': {e}")
            return None

    def _auto_split(self, line: str) -> List[str]:
        """
        Автоматическое определение разделителя и разбиение строки.

        Args:
            line: Строка для разбиения

        Returns:
            Список частей
        """
        # Приоритет разделителей: tab, ;, множественные пробелы
        if '\t' in line:
            return line.split('\t')
        elif ';' in line:
            return line.split(';')
        else:
            # Пробелы (один или несколько)
            return line.split()

    def _parse_coordinate(self, value: str) -> Optional[float]:
        """
        Парсинг одной координаты (поддержка разных форматов).

        Поддерживаемые форматы (на основе lat-lon-parser best practices):
        - Десятичные: 55.7558, 55,7558
        - Метры: 2190000.00
        - Градусы-минуты-секунды: 55°45'20.9"N, 55 45 20.9
        - Градусы-минуты: 55°45.35'N
        - С направлением в начале: N55°45'20.9"

        Формула DMS -> DD: degrees + (minutes / 60) + (seconds / 3600)
        Если направление S или W, результат отрицательный.

        Args:
            value: Строка с координатой

        Returns:
            Числовое значение или None
        """
        value = value.strip()

        if not value:
            return None

        # Удаляем направление (N, S, E, W) - может быть в начале или в конце
        direction = None
        if value and value[-1] in 'NSEWnsew':
            direction = value[-1].upper()
            value = value[:-1].strip()
        elif value and value[0] in 'NSEWnsew':
            direction = value[0].upper()
            value = value[1:].strip()

        # Пробуем разные форматы

        # 1. Градусы-минуты-секунды: 55°45'20.9" или 55d45m20.9s
        # Расширенный паттерн для разных символов (°, d, º)
        dms_pattern = r"(\d+)[°dº]\s*(\d+)[\'`'m]\s*([\d.,]+)[\"″s]?"
        match = re.match(dms_pattern, value, re.IGNORECASE)
        if match:
            degrees = float(match.group(1))
            minutes = float(match.group(2))
            seconds = float(match.group(3).replace(',', '.'))
            result = degrees + minutes / 60 + seconds / 3600
            if direction in ('S', 'W'):
                result = -result
            return result

        # 2. Градусы-минуты (без секунд): 55°45.35'
        dm_pattern = r"(\d+)[°dº]\s*([\d.,]+)[\'`'m]?"
        match = re.match(dm_pattern, value, re.IGNORECASE)
        if match:
            degrees = float(match.group(1))
            minutes = float(match.group(2).replace(',', '.'))
            result = degrees + minutes / 60
            if direction in ('S', 'W'):
                result = -result
            return result

        # 3. Градусы минуты секунды через пробел: 55 45 20.9
        parts = value.split()
        if len(parts) == 3:
            try:
                degrees = float(parts[0])
                minutes = float(parts[1])
                seconds = float(parts[2].replace(',', '.'))
                result = degrees + minutes / 60 + seconds / 3600
                if direction in ('S', 'W'):
                    result = -result
                return result
            except ValueError:
                pass

        # 4. Градусы минуты через пробел: 55 45.35
        if len(parts) == 2:
            try:
                degrees = float(parts[0])
                minutes = float(parts[1].replace(',', '.'))
                result = degrees + minutes / 60
                if direction in ('S', 'W'):
                    result = -result
                return result
            except ValueError:
                pass

        # 5. Десятичные градусы или метры
        try:
            # Заменяем запятую на точку для десятичного разделителя
            value = value.replace(',', '.')
            # Удаляем пробелы внутри числа (разделители тысяч)
            value = value.replace(' ', '')
            result = float(value)
            if direction in ('S', 'W'):
                result = -result
            return result
        except ValueError:
            return None

    def build_geometries(self, objects: List[List[QgsPointXY]],
                         geometry_type: str, close_polygon: bool) -> List[QgsGeometry]:
        """
        Построение геометрий из списка точек.

        Args:
            objects: Список объектов (каждый - список точек)
            geometry_type: 'point' или 'polygon'
            close_polygon: Замкнуть полигон

        Returns:
            Список QgsGeometry
        """
        geometries = []

        for points in objects:
            if not points:
                continue

            if geometry_type == 'point':
                # Каждая точка - отдельный объект
                for point in points:
                    geom = QgsGeometry.fromPointXY(point)
                    geometries.append(geom)
            else:
                # Полигон
                if len(points) < 3:
                    log_warning(f"Fsm_1_1_3: Пропущен объект с {len(points)} точками (минимум 3 для полигона)")
                    continue

                # Замыкание если нужно
                if close_polygon and points[0] != points[-1]:
                    points = points + [points[0]]

                # Создаем полигон
                try:
                    geom = QgsGeometry.fromPolygonXY([points])
                    if geom.isGeosValid():
                        geometries.append(geom)
                    else:
                        log_warning("Fsm_1_1_3: Создан невалидный полигон, пропущен")
                except Exception as e:
                    log_warning(f"Fsm_1_1_3: Ошибка создания полигона: {e}")

        return geometries

    def create_preview(self, geometries: List[QgsGeometry],
                       crs: QgsCoordinateReferenceSystem,
                       geometry_type: str) -> bool:
        """
        Создание временного слоя для просмотра.

        Args:
            geometries: Список геометрий
            crs: Система координат
            geometry_type: 'point' или 'polygon'

        Returns:
            True если успешно
        """
        self._remove_preview_layer()

        if not geometries:
            log_warning("Fsm_1_1_3: Нет геометрий для просмотра")
            return False

        # Определяем тип геометрии для слоя
        if geometry_type == 'point':
            wkb_type = "Point"
        else:
            wkb_type = "Polygon"

        # Создаем временный слой
        uri = f"{wkb_type}?crs={crs.authid()}"
        self.preview_layer = QgsVectorLayer(uri, self.PREVIEW_LAYER_NAME, "memory")

        if not self.preview_layer.isValid():
            log_error("Fsm_1_1_3: Не удалось создать временный слой")
            return False

        # Добавляем объекты
        provider = self.preview_layer.dataProvider()
        features = []

        for geom in geometries:
            feat = QgsFeature()
            feat.setGeometry(geom)
            features.append(feat)

        provider.addFeatures(features)

        # Применяем стиль (красная обводка)
        self._apply_preview_style(geometry_type)

        # Добавляем в проект
        QgsProject.instance().addMapLayer(self.preview_layer, False)

        # Добавляем в корень дерева слоёв
        root = QgsProject.instance().layerTreeRoot()
        root.insertLayer(0, self.preview_layer)

        # Центрируем на слое
        self.preview_layer.updateExtents()
        extent = self.preview_layer.extent()
        if not extent.isEmpty():
            # Добавляем буфер 10%
            extent.scale(1.1)
            iface.mapCanvas().setExtent(extent)
            iface.mapCanvas().refresh()

        self.current_geometries = geometries

        log_info(f"Fsm_1_1_3: Создан preview слой с {len(geometries)} объектами")
        return True

    def _apply_preview_style(self, geometry_type: str):
        """
        Применение стиля для preview слоя (красная обводка).

        Args:
            geometry_type: 'point' или 'polygon'
        """
        if not self.preview_layer:
            return

        if geometry_type == 'polygon':
            # Красная обводка, полупрозрачная заливка
            symbol = QgsFillSymbol.createSimple({
                'color': '255,0,0,50',  # Полупрозрачный красный
                'outline_color': '255,0,0,255',  # Красная обводка
                'outline_width': '1.0'
            })
        else:
            # Красные точки
            symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.PointGeometry)
            symbol.setColor(QColor(255, 0, 0))
            symbol.setSize(3)

        self.preview_layer.renderer().setSymbol(symbol)
        self.preview_layer.triggerRepaint()

    def _remove_preview_layer(self):
        """Удаление временного слоя просмотра."""
        if self.preview_layer:
            try:
                QgsProject.instance().removeMapLayer(self.preview_layer.id())
            except Exception:
                pass
            self.preview_layer = None
            self.current_geometries = []
            iface.mapCanvas().refresh()

    def save_to_layer(self, target_layer_name: str,
                      geometries: List[QgsGeometry],
                      source_crs: QgsCoordinateReferenceSystem) -> bool:
        """
        Сохранение геометрий в целевой слой.

        Args:
            target_layer_name: Имя целевого слоя
            geometries: Список геометрий
            source_crs: CRS исходных координат

        Returns:
            True если успешно
        """
        if not geometries:
            log_error("Fsm_1_1_3: Нет геометрий для сохранения")
            return False

        # Ищем целевой слой в проекте
        layers = QgsProject.instance().mapLayersByName(target_layer_name)
        if not layers:
            # Пробуем с префиксом L_
            if not target_layer_name.startswith('L_'):
                layers = QgsProject.instance().mapLayersByName(f"L_{target_layer_name}")

        if not layers:
            log_error(f"Fsm_1_1_3: Целевой слой '{target_layer_name}' не найден")
            return False

        target_layer = layers[0]
        if not isinstance(target_layer, QgsVectorLayer):
            log_error(f"Fsm_1_1_3: Слой '{target_layer_name}' не является векторным")
            return False

        if not target_layer.isEditable():
            target_layer.startEditing()

        # Трансформация координат если нужно
        target_crs = target_layer.crs()
        transform = None
        if source_crs != target_crs:
            transform = QgsCoordinateTransform(
                source_crs, target_crs, QgsProject.instance()
            )

        # Добавляем объекты
        added_count = 0
        for geom in geometries:
            if transform:
                geom.transform(transform)

            feat = QgsFeature(target_layer.fields())
            feat.setGeometry(geom)

            if target_layer.addFeature(feat):
                added_count += 1
            else:
                log_warning("Fsm_1_1_3: Не удалось добавить объект")

        # Сохраняем изменения
        if target_layer.commitChanges():
            log_info(f"Fsm_1_1_3: Сохранено {added_count} объектов в слой '{target_layer_name}'")
            return True
        else:
            log_error(f"Fsm_1_1_3: Ошибка сохранения: {target_layer.commitErrors()}")
            target_layer.rollBack()
            return False


class CoordinateInputDialog(QDialog):
    """Диалог для ввода координат."""

    def __init__(self, parent, handler: Fsm_1_1_3_CoordinateInput, edit_mode: bool = False):
        """
        Инициализация диалога.

        Args:
            parent: Родительский виджет (UniversalImportDialog)
            handler: Обработчик координат
            edit_mode: True для режима редактирования существующего объекта
        """
        super().__init__(parent)
        self.handler = handler
        self.parent_dialog = parent
        self.edit_mode = edit_mode
        self.current_parsed_points: List[QgsPointXY] = []
        self.feature_selector: Optional[FeatureSelector] = None
        self.prev_map_tool = None

        title = "Редактирование координат" if edit_mode else "Импорт координат"
        self.setWindowTitle(title)
        self.setFixedSize(500, 600)
        # Убираем кнопку помощи и держим диалог поверх родителя (Qt best practice)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowContextHelpButtonHint
            | Qt.WindowStaysOnTopHint
        )

        self._setup_ui()
        self._connect_signals()

        # Если режим редактирования - активируем инструмент выбора
        if edit_mode:
            self._activate_feature_selector()

    def _setup_ui(self):
        """Создание интерфейса."""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # === CRS ===
        crs_group = QGroupBox("Система координат")
        crs_layout = QHBoxLayout()

        self.crs_widget = QgsProjectionSelectionWidget()
        self.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        crs_layout.addWidget(self.crs_widget)

        crs_group.setLayout(crs_layout)
        layout.addWidget(crs_group)

        # === Настройки ===
        settings_group = QGroupBox("Настройки")
        settings_layout = QVBoxLayout()

        # Тип геометрии
        type_layout = QHBoxLayout()
        type_label = QLabel("Тип:")
        type_label.setMinimumWidth(80)
        type_layout.addWidget(type_label)

        self.type_group = QButtonGroup(self)
        self.type_points = QRadioButton("Точки")
        self.type_polygon = QRadioButton("Полигон")
        self.type_polygon.setChecked(True)

        self.type_group.addButton(self.type_points, 0)
        self.type_group.addButton(self.type_polygon, 1)

        type_layout.addWidget(self.type_points)
        type_layout.addWidget(self.type_polygon)
        type_layout.addStretch()

        settings_layout.addLayout(type_layout)

        # Порядок координат
        order_layout = QHBoxLayout()
        order_label = QLabel("Порядок:")
        order_label.setMinimumWidth(80)
        order_layout.addWidget(order_label)

        self.order_group = QButtonGroup(self)
        self.order_xy = QRadioButton("X, Y")
        self.order_yx = QRadioButton("Y, X")
        self.order_xy.setChecked(True)

        self.order_group.addButton(self.order_xy, 0)
        self.order_group.addButton(self.order_yx, 1)

        order_layout.addWidget(self.order_xy)
        order_layout.addWidget(self.order_yx)
        order_layout.addStretch()

        settings_layout.addLayout(order_layout)

        # Разделитель
        delimiter_layout = QHBoxLayout()
        delimiter_label = QLabel("Разделитель:")
        delimiter_label.setMinimumWidth(80)
        delimiter_layout.addWidget(delimiter_label)

        self.delimiter_combo = QComboBox()
        self.delimiter_combo.addItem("Авто", "auto")
        self.delimiter_combo.addItem("Табуляция", "tab")
        self.delimiter_combo.addItem("Пробел", "space")
        self.delimiter_combo.addItem("Точка с запятой (;)", ";")
        self.delimiter_combo.addItem("Запятая (,)", ",")
        self.delimiter_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        delimiter_layout.addWidget(self.delimiter_combo)

        settings_layout.addLayout(delimiter_layout)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        # === Ввод координат ===
        coords_group = QGroupBox("Координаты")
        coords_layout = QVBoxLayout()

        # Примечание
        note_label = QLabel("Пустая строка - разделитель между объектами")
        note_label.setStyleSheet("color: #666; font-size: 9pt; font-style: italic;")
        coords_layout.addWidget(note_label)

        # Текстовое поле
        self.coords_edit = QPlainTextEdit()
        self.coords_edit.setPlaceholderText(
            "Вставьте координаты сюда...\n\n"
            "Поддерживаемые форматы:\n"
            "  55.7558  37.6173\n"
            "  55°45'20.9\"N  37°37'02.3\"E\n"
            "  2190000.00  1310000.00"
        )
        font = QFont("Consolas", 9)
        self.coords_edit.setFont(font)
        coords_layout.addWidget(self.coords_edit)

        # Статистика
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("color: #0066cc; font-size: 9pt;")
        coords_layout.addWidget(self.stats_label)

        # Кнопки действий с координатами
        action_layout = QHBoxLayout()

        self.close_btn = QPushButton("Замкнуть")
        self.close_btn.setToolTip("Добавить первую точку в конец (замкнуть полигон)")
        self.close_btn.setEnabled(False)  # Активна только для полигона
        action_layout.addWidget(self.close_btn)

        self.copy_btn = QPushButton("Копировать")
        self.copy_btn.setToolTip("Копировать координаты в буфер обмена")
        self.copy_btn.clicked.connect(self._on_copy)
        action_layout.addWidget(self.copy_btn)

        # Кнопка выбора объекта для редактирования (только в edit_mode)
        self.select_feature_btn = QPushButton("Выбрать объект")
        self.select_feature_btn.setToolTip("Кликните на объект на карте для загрузки координат")
        self.select_feature_btn.clicked.connect(self._on_select_feature)
        self.select_feature_btn.setVisible(self.edit_mode)
        action_layout.addWidget(self.select_feature_btn)

        action_layout.addStretch()
        coords_layout.addLayout(action_layout)

        coords_group.setLayout(coords_layout)
        layout.addWidget(coords_group)

        # === Подсветка вершин ===
        highlight_group = QGroupBox("Подсветка вершин")
        highlight_layout = QHBoxLayout()

        self.highlight_check = QPushButton("Показать вершины")
        self.highlight_check.setCheckable(True)
        self.highlight_check.setToolTip("Подсветить вершины на карте")
        self.highlight_check.clicked.connect(self._on_toggle_highlight)
        highlight_layout.addWidget(self.highlight_check)

        self.vertex_label = QLabel("Вершина:")
        highlight_layout.addWidget(self.vertex_label)

        self.vertex_combo = QComboBox()
        self.vertex_combo.setMinimumWidth(100)
        self.vertex_combo.currentIndexChanged.connect(self._on_vertex_changed)
        highlight_layout.addWidget(self.vertex_combo)

        highlight_layout.addStretch()
        highlight_group.setLayout(highlight_layout)
        layout.addWidget(highlight_group)

        # === Кнопки ===
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        self.preview_btn = QPushButton("Просмотр")
        self.preview_btn.setToolTip("Создать временный слой для проверки")
        self.preview_btn.clicked.connect(self._on_preview)
        buttons_layout.addWidget(self.preview_btn)

        # В режиме редактирования - кнопка "Обновить", иначе "Сохранить"
        if self.edit_mode:
            self.save_btn = QPushButton("Обновить")
            self.save_btn.setToolTip("Обновить геометрию выбранного объекта")
        else:
            self.save_btn = QPushButton("Сохранить")
            self.save_btn.setToolTip("Сохранить как новый объект")

        self.save_btn.clicked.connect(self._on_save)
        self.save_btn.setEnabled(False)
        buttons_layout.addWidget(self.save_btn)

        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_btn)

        layout.addLayout(buttons_layout)

    def _connect_signals(self):
        """Подключение сигналов."""
        # Изменение типа геометрии
        self.type_group.buttonClicked.connect(self._on_type_changed)

        # Изменение текста - очищаем preview
        self.coords_edit.textChanged.connect(self._on_text_changed)

        # Изменение настроек - очищаем preview
        self.delimiter_combo.currentIndexChanged.connect(self._on_settings_changed)
        self.order_group.buttonClicked.connect(self._on_settings_changed)
        self.crs_widget.crsChanged.connect(self._on_settings_changed)

        # Замкнуть координаты
        self.close_btn.clicked.connect(self._on_close_coords)

    def _on_type_changed(self):
        """Обработка изменения типа геометрии."""
        is_polygon = self.type_polygon.isChecked()
        self.close_btn.setEnabled(is_polygon)
        self._on_settings_changed()

    def _on_text_changed(self):
        """Обработка изменения текста."""
        self._clear_preview()
        self.save_btn.setEnabled(False)
        self._update_stats()

    def _on_settings_changed(self):
        """Обработка изменения настроек."""
        self._clear_preview()
        self.save_btn.setEnabled(False)

    def _clear_preview(self):
        """Очистка preview слоя."""
        self.handler._remove_preview_layer()

    def _update_stats(self):
        """Обновление статистики по введённым координатам."""
        text = self.coords_edit.toPlainText().strip()
        if not text:
            self.stats_label.setText("")
            return

        lines = text.split('\n')
        non_empty_lines = [l for l in lines if l.strip()]
        empty_lines = len([l for l in lines if not l.strip()])

        # Количество объектов = количество блоков, разделённых пустыми строками
        objects_count = 1 if non_empty_lines else 0
        for i, line in enumerate(lines):
            if not line.strip() and i > 0 and i < len(lines) - 1:
                # Пустая строка между непустыми
                if any(lines[j].strip() for j in range(i)):
                    if any(lines[j].strip() for j in range(i + 1, len(lines))):
                        objects_count += 1

        # Упрощённый подсчёт
        blocks = text.split('\n\n')
        objects_count = len([b for b in blocks if b.strip()])

        self.stats_label.setText(
            f"Строк: {len(non_empty_lines)} | Объектов: {objects_count}"
        )

    def _on_close_coords(self):
        """Добавление первой точки в конец списка (замыкание)."""
        text = self.coords_edit.toPlainText().strip()
        if not text:
            return

        lines = text.split('\n')

        # Обрабатываем каждый объект (разделённый пустой строкой)
        result_lines = []
        current_block = []
        first_line = None

        for line in lines:
            stripped = line.strip()

            if not stripped:
                # Конец блока - замыкаем если нужно
                if current_block and first_line:
                    # Проверяем, не замкнут ли уже
                    if current_block[-1].strip() != first_line:
                        current_block.append(first_line)
                    result_lines.extend(current_block)
                    result_lines.append('')
                current_block = []
                first_line = None
            else:
                if first_line is None:
                    first_line = stripped
                current_block.append(line)

        # Последний блок
        if current_block and first_line:
            if current_block[-1].strip() != first_line:
                current_block.append(first_line)
            result_lines.extend(current_block)

        self.coords_edit.setPlainText('\n'.join(result_lines))

    def _on_preview(self):
        """Обработка кнопки Просмотр."""
        text = self.coords_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Предупреждение", "Введите координаты")
            return

        # Получаем параметры
        delimiter = self.delimiter_combo.currentData()
        swap_xy = self.order_yx.isChecked()
        geometry_type = 'point' if self.type_points.isChecked() else 'polygon'
        crs = self.crs_widget.crs()

        # Парсим координаты
        objects = self.handler.parse_coordinates(text, delimiter, swap_xy)

        if not objects:
            QMessageBox.warning(self, "Ошибка", "Не удалось распознать координаты")
            return

        # Подсчитываем точки
        total_points = sum(len(obj) for obj in objects)
        log_info(f"Fsm_1_1_3: Распознано {len(objects)} объектов, {total_points} точек")

        # Строим геометрии
        close_polygon = geometry_type == 'polygon'
        geometries = self.handler.build_geometries(objects, geometry_type, close_polygon)

        if not geometries:
            QMessageBox.warning(self, "Ошибка", "Не удалось создать геометрии")
            return

        # Создаём preview
        if self.handler.create_preview(geometries, crs, geometry_type):
            self.save_btn.setEnabled(True)
            QMessageBox.information(
                self, "Просмотр",
                f"Создано {len(geometries)} объектов.\n"
                "Проверьте положение на карте."
            )
        else:
            QMessageBox.warning(self, "Ошибка", "Не удалось создать preview")

    def _on_save(self):
        """Обработка кнопки Сохранить/Обновить."""
        crs = self.crs_widget.crs()

        if self.edit_mode:
            # Режим редактирования - обновляем существующий объект
            if not self.handler.edit_feature:
                QMessageBox.warning(
                    self, "Ошибка",
                    "Сначала выберите объект для редактирования"
                )
                return

            if not self.current_parsed_points:
                QMessageBox.warning(self, "Ошибка", "Нет координат для обновления")
                return

            if self.handler.update_feature_geometry(self.current_parsed_points, crs):
                QMessageBox.information(
                    self, "Успешно",
                    f"Геометрия объекта обновлена\n"
                    f"({len(self.current_parsed_points)} вершин)"
                )
                self.accept()
            else:
                QMessageBox.critical(
                    self, "Ошибка",
                    "Не удалось обновить геометрию объекта"
                )
        else:
            # Режим создания - сохраняем новый объект
            target_layer_name = self.parent_dialog.selected_full_name

            if not target_layer_name or target_layer_name == "AUTO_XML":
                QMessageBox.warning(
                    self, "Ошибка",
                    "Выберите целевой слой в основном окне импорта"
                )
                return

            if not self.handler.current_geometries:
                QMessageBox.warning(self, "Ошибка", "Сначала выполните Просмотр")
                return

            # Добавляем префикс L_ если его нет
            if not target_layer_name.startswith('L_') and not target_layer_name.startswith('Le_'):
                full_layer_name = f"L_{target_layer_name}"
            else:
                full_layer_name = target_layer_name

            if self.handler.save_to_layer(full_layer_name, self.handler.current_geometries, crs):
                QMessageBox.information(
                    self, "Успешно",
                    f"Сохранено {len(self.handler.current_geometries)} объектов\n"
                    f"в слой '{full_layer_name}'"
                )
                self.accept()
            else:
                QMessageBox.critical(
                    self, "Ошибка",
                    f"Не удалось сохранить в слой '{full_layer_name}'"
                )

    def _on_copy(self):
        """Копирование координат в буфер обмена."""
        text = self.coords_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Предупреждение", "Нет координат для копирования")
            return

        # Парсим координаты
        delimiter = self.delimiter_combo.currentData()
        swap_xy = self.order_yx.isChecked()
        objects = self.handler.parse_coordinates(text, delimiter, swap_xy)

        if not objects:
            QMessageBox.warning(self, "Ошибка", "Не удалось распознать координаты")
            return

        # Собираем все точки
        all_points = []
        for obj in objects:
            all_points.extend(obj)

        # Определяем разделитель для экспорта
        export_delimiter = '\t'  # По умолчанию табуляция
        if self.delimiter_combo.currentData() == ';':
            export_delimiter = ';'
        elif self.delimiter_combo.currentData() == ',':
            export_delimiter = ','

        if self.handler.copy_to_clipboard(all_points, export_delimiter):
            QMessageBox.information(
                self, "Скопировано",
                f"Скопировано {len(all_points)} координат в буфер обмена"
            )

    def _on_toggle_highlight(self):
        """Включение/выключение подсветки вершин."""
        if self.highlight_check.isChecked():
            # Парсим координаты и подсвечиваем
            text = self.coords_edit.toPlainText().strip()
            if not text:
                self.highlight_check.setChecked(False)
                return

            delimiter = self.delimiter_combo.currentData()
            swap_xy = self.order_yx.isChecked()
            objects = self.handler.parse_coordinates(text, delimiter, swap_xy)

            if not objects or not objects[0]:
                self.highlight_check.setChecked(False)
                return

            # Берём первый объект для подсветки
            self.current_parsed_points = objects[0]

            # Заполняем комбобокс вершин
            self.vertex_combo.clear()
            for i in range(len(self.current_parsed_points)):
                pt = self.current_parsed_points[i]
                self.vertex_combo.addItem(f"{i+1}: ({pt.x():.2f}, {pt.y():.2f})", i)

            # Подсветка
            crs = self.crs_widget.crs()
            is_polygon = self.type_polygon.isChecked()
            self.handler.highlight_vertex(self.current_parsed_points, crs, 0, is_polygon)

            self.highlight_check.setText("Скрыть вершины")
        else:
            # Выключаем подсветку
            self.handler._remove_vertex_highlight()
            self.vertex_combo.clear()
            self.highlight_check.setText("Показать вершины")

    def _on_vertex_changed(self, index):
        """Переключение текущей вершины."""
        if index >= 0 and self.highlight_check.isChecked():
            self.handler.change_highlighted_vertex(index)

    def _on_select_feature(self):
        """Активация инструмента выбора объекта."""
        self._activate_feature_selector()
        QMessageBox.information(
            self, "Выбор объекта",
            "Кликните на объект на карте.\n"
            "Убедитесь, что нужный слой активен."
        )

    def _activate_feature_selector(self):
        """Активация инструмента выбора объекта на карте."""
        canvas = iface.mapCanvas()
        self.prev_map_tool = canvas.mapTool()
        self.feature_selector = FeatureSelector(canvas, self._on_feature_selected)
        canvas.setMapTool(self.feature_selector)

    def _on_feature_selected(self, feature: QgsFeature, layer: QgsVectorLayer):
        """Обработка выбора объекта на карте."""
        # Восстанавливаем предыдущий инструмент
        if self.prev_map_tool:
            iface.mapCanvas().setMapTool(self.prev_map_tool)

        # Извлекаем координаты
        points = self.handler.extract_coords_from_feature(feature, layer)

        if not points:
            QMessageBox.warning(self, "Ошибка", "Объект не содержит геометрии")
            return

        # Устанавливаем CRS слоя
        self.crs_widget.setCrs(layer.crs())

        # Определяем тип геометрии
        geom_type = layer.geometryType()
        if geom_type == QgsWkbTypes.PointGeometry:
            self.type_points.setChecked(True)
        else:
            self.type_polygon.setChecked(True)

        # Заполняем текстовое поле координатами
        lines = []
        for pt in points:
            lines.append(f"{pt.x():.8f}\t{pt.y():.8f}")

        self.coords_edit.setPlainText('\n'.join(lines))
        self.current_parsed_points = points

        # Активируем подсветку
        self.highlight_check.setChecked(True)
        self._on_toggle_highlight()

        # Активируем кнопку сохранения
        self.save_btn.setEnabled(True)

        log_info(f"Fsm_1_1_3: Загружен объект с {len(points)} вершинами из слоя '{layer.name()}'")

    def closeEvent(self, event):
        """Обработка закрытия диалога."""
        # Восстанавливаем предыдущий инструмент карты
        if self.prev_map_tool:
            iface.mapCanvas().setMapTool(self.prev_map_tool)

        # Очищаем подсветку
        self.handler._remove_vertex_highlight()

        super().closeEvent(event)

    def reject(self):
        """Обработка отмены."""
        # Восстанавливаем предыдущий инструмент карты
        if self.prev_map_tool:
            iface.mapCanvas().setMapTool(self.prev_map_tool)

        super().reject()
