# -*- coding: utf-8 -*-
"""
Менеджер контроля точности координат.
Обеспечивает проверку и округление координат до 0.01 м (сантиметры).

ВАЖНО: Используется классическое математическое округление (round half away from zero),
а НЕ банковское округление Python (round half to even).
Это критично для топологической совместимости между модулями.
"""

import math
from typing import Tuple, Optional
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsWkbTypes, QgsPointXY
)
from Daman_QGIS.constants import PRECISION_DECIMALS, COORDINATE_TOLERANCE, CLOSURE_TOLERANCE
from Daman_QGIS.utils import log_warning


def _math_round(value: float, decimals: int) -> float:
    """
    Классическое математическое округление (round half away from zero).

    Python round() использует банковское округление (round half to even):
    - round(2.5) = 2 (к чётному)
    - round(3.5) = 4 (к чётному)

    Эта функция использует классическое округление:
    - _math_round(2.5, 0) = 3 (от нуля)
    - _math_round(3.5, 0) = 4 (от нуля)

    Это совместимо с QGIS snappedToGrid() и PostGIS ST_SnapToGrid().

    Args:
        value: Значение для округления
        decimals: Количество знаков после запятой

    Returns:
        Округлённое значение
    """
    multiplier = 10 ** decimals
    if value >= 0:
        return math.floor(value * multiplier + 0.5) / multiplier
    else:
        return math.ceil(value * multiplier - 0.5) / multiplier


class CoordinatePrecisionManager:
    """Менеджер контроля точности координат"""

    # ========================================================================
    # WRAPPER ФУНКЦИИ ДЛЯ ОКРУГЛЕНИЯ (Updated 2025-12-12)
    # Используют классическое математическое округление
    # ========================================================================

    @staticmethod
    def round_coordinate(value: float, precision: Optional[int] = None) -> float:
        """
        Округление одной координаты до заданной точности.

        Использует классическое математическое округление (round half away from zero),
        совместимое с QGIS snappedToGrid().

        Args:
            value: Значение координаты
            precision: Количество знаков после запятой (по умолчанию PRECISION_DECIMALS)

        Returns:
            Округлённое значение

        Example:
            >>> round_coordinate(123.456789)  # 0.01м точность
            123.46
            >>> round_coordinate(123.455)  # граничный случай
            123.46  # НЕ 123.46 как в банковском округлении
        """
        decimals = precision if precision is not None else PRECISION_DECIMALS
        return _math_round(value, decimals)

    @staticmethod
    def round_coordinates(x: float, y: float, precision: Optional[int] = None) -> Tuple[float, float]:
        """
        Округление пары координат до заданной точности.

        Использует классическое математическое округление (round half away from zero).

        Args:
            x: Координата X
            y: Координата Y
            precision: Количество знаков после запятой (по умолчанию PRECISION_DECIMALS)

        Returns:
            Tuple (x_rounded, y_rounded)

        Example:
            >>> round_coordinates(123.456, 456.789)  # 0.01м точность
            (123.46, 456.79)
        """
        decimals = precision if precision is not None else PRECISION_DECIMALS
        return (
            _math_round(x, decimals),
            _math_round(y, decimals)
        )

    @staticmethod
    def round_point(point: QgsPointXY, precision: Optional[int] = None) -> QgsPointXY:
        """
        Округление QgsPointXY до заданной точности.

        Использует классическое математическое округление (round half away from zero).

        Args:
            point: Точка QgsPointXY
            precision: Количество знаков после запятой (по умолчанию PRECISION_DECIMALS)

        Returns:
            Новая точка с округлёнными координатами

        Example:
            >>> from qgis.core import QgsPointXY
            >>> p = QgsPointXY(123.456, 456.789)
            >>> rounded = round_point(p)  # 0.01м точность
            >>> (rounded.x(), rounded.y())
            (123.46, 456.79)
        """
        decimals = precision if precision is not None else PRECISION_DECIMALS
        return QgsPointXY(
            _math_round(point.x(), decimals),
            _math_round(point.y(), decimals)
        )

    @staticmethod
    def round_point_tuple(point: QgsPointXY, precision: Optional[int] = None) -> Tuple[float, float]:
        """
        Округление QgsPointXY в tuple (для использования как ключ в dict).

        Использует классическое математическое округление (round half away from zero).

        Args:
            point: Точка QgsPointXY
            precision: Количество знаков после запятой (по умолчанию PRECISION_DECIMALS)

        Returns:
            Tuple (x_rounded, y_rounded)

        Example:
            >>> from qgis.core import QgsPointXY
            >>> p = QgsPointXY(123.456, 456.789)
            >>> key = round_point_tuple(p)  # 0.01м точность
            >>> unique_points = {key: 1}  # Использование как dict key
        """
        decimals = precision if precision is not None else PRECISION_DECIMALS
        return (
            _math_round(point.x(), decimals),
            _math_round(point.y(), decimals)
        )

    @staticmethod
    def is_ring_closed(ring_points: list,
                       tolerance: float = CLOSURE_TOLERANCE,
                       use_optimization: bool = False) -> bool:
        """
        Проверка замкнутости контура (кольца полигона)

        ИСПОЛЬЗОВАНИЕ:
        - Выписки ОН/ЗУ: use_optimization=False (стандартная проверка)
        - КПТ/Зоны: use_optimization=True (оптимизация для больших файлов)

        Args:
            ring_points: Список точек контура (QgsPoint)
            tolerance: Допуск замыкания в метрах (по умолчанию CLOSURE_TOLERANCE)
            use_optimization: Избегать sqrt() для производительности

        Returns:
            True если контур замкнут в пределах допуска

        Examples:
            >>> # Стандартная проверка (выписки ОН, маленькие файлы)
            >>> is_closed = CoordinatePrecisionManager.is_ring_closed(ring_points)

            >>> # Оптимизированная проверка (КПТ, большие файлы >100МБ)
            >>> is_closed = CoordinatePrecisionManager.is_ring_closed(
            ...     ring_points,
            ...     use_optimization=True
            ... )
        """
        if not ring_points or len(ring_points) < 2:
            return False

        start_point = ring_points[0]
        end_point = ring_points[-1]

        if use_optimization:
            # Оптимизированная версия (для КПТ/Зон - большие файлы)
            # Избегает sqrt() - экономия ~25% времени на проверку
            dist_sq = (start_point.x() - end_point.x())**2 + \
                      (start_point.y() - end_point.y())**2
            return dist_sq < (tolerance**2)
        else:
            # Стандартная версия (для выписок ОН - более читаемая)
            return start_point.distance(end_point) < tolerance

    # ========================================================================
    # ОСНОВНЫЕ МЕТОДЫ МЕНЕДЖЕРА
    # ========================================================================

    @staticmethod
    def check_layer_precision(layer: QgsVectorLayer) -> Tuple[bool, int, int]:
        """
        Проверка точности координат в слое
        
        Args:
            layer: Векторный слой для проверки
            
        Returns:
            Tuple (нужно_округление, всего_вершин, вершин_с_избыточной_точностью)
        """
        if layer is None or not isinstance(layer, QgsVectorLayer):
            return False, 0, 0
        
        total_vertices = 0
        imprecise_vertices = 0
        needs_rounding = False

        # Проверяем все объекты в слое
        for feature in layer.getFeatures():
            if not feature.hasGeometry():
                continue

            geometry = feature.geometry()
            if geometry.isEmpty():
                continue

            # Проверяем координаты вершин
            vertices = CoordinatePrecisionManager._get_all_vertices(geometry)

            for vertex in vertices:
                total_vertices += 1

                # Округляем координаты до требуемой точности (используем wrapper)
                x_rounded, y_rounded = CoordinatePrecisionManager.round_coordinates(
                    vertex.x(), vertex.y()
                )

                # Проверяем разницу между исходными и округленными значениями
                # Используем порог для учета погрешности float

                if abs(vertex.x() - x_rounded) > COORDINATE_TOLERANCE or \
                   abs(vertex.y() - y_rounded) > COORDINATE_TOLERANCE:
                    imprecise_vertices += 1
                    needs_rounding = True


        return needs_rounding, total_vertices, imprecise_vertices
    
    @staticmethod
    def show_precision_dialog(layer_name: str, imprecise_count: int, total_count: int) -> bool:
        """
        Показ диалога с вопросом об округлении
        
        Args:
            layer_name: Имя слоя
            imprecise_count: Количество вершин с избыточной точностью
            total_count: Общее количество вершин
            
        Returns:
            True если пользователь выбрал округление
        """
        msg = f"Слой '{layer_name}' содержит координаты с избыточной точностью.\n\n"
        msg += f"Обнаружено вершин с точностью > 0.01 м: {imprecise_count} из {total_count}\n\n"
        msg += "Округлить координаты до 0.01 м (сантиметры)?\n\n"
        msg += "Да - выполнить округление и продолжить импорт\n"
        msg += "Нет - отменить импорт слоя"
        
        reply = QMessageBox.question(
            None,
            "Координаты не округлены",
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        
        return reply == QMessageBox.Yes
    
    @staticmethod
    def round_layer_coordinates(layer: QgsVectorLayer) -> bool:
        """
        Округление всех координат в слое до заданной точности
        
        Args:
            layer: Векторный слой для округления
            
        Returns:
            True если округление выполнено успешно
        """
        if layer is None or not isinstance(layer, QgsVectorLayer):
            return False

        editing_started = False

        try:
            # Начинаем редактирование если нужно
            if not layer.isEditable():
                if not layer.startEditing():
                    raise RuntimeError(f"Не удалось начать редактирование слоя {layer.name()}")
                editing_started = True

            rounded_count = 0

            # Обрабатываем все объекты
            for feature in layer.getFeatures():
                if not feature.hasGeometry():
                    continue

                geometry = feature.geometry()
                if geometry.isEmpty():
                    continue

                # Округляем геометрию
                rounded_geometry = CoordinatePrecisionManager._round_geometry(geometry)

                if rounded_geometry and not rounded_geometry.equals(geometry):
                    # Обновляем геометрию объекта
                    layer.changeGeometry(feature.id(), rounded_geometry)
                    rounded_count += 1

            # Фиксируем изменения если мы начали редактирование
            if editing_started:
                if not layer.commitChanges():
                    raise RuntimeError(f"Не удалось сохранить изменения в слое {layer.name()}")

            return True

        except Exception as e:
            # Откатываем изменения при ошибке
            if editing_started and layer.isEditable():
                layer.rollBack()
            raise
    
    @staticmethod
    def _get_all_vertices(geometry: QgsGeometry) -> list:
        """
        Получение всех вершин геометрии
        
        Args:
            geometry: Геометрия
            
        Returns:
            Список вершин
        """
        vertices = []

        # Получаем вершины в зависимости от типа геометрии
        geom_type = geometry.type()

        if geom_type == QgsWkbTypes.PointGeometry:
            # Для точек
            if geometry.isMultipart():
                # Мультиточка
                multipoint = geometry.asMultiPoint()
                if multipoint:
                    vertices.extend(multipoint)
            else:
                # Одиночная точка
                point = geometry.asPoint()
                if point:
                    vertices.append(point)

        elif geom_type == QgsWkbTypes.LineGeometry:
            # Для линий
            # МИГРАЦИЯ LINESTRING → MULTILINESTRING: упрощённый паттерн
            lines = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
            for line in lines:
                if line:
                    vertices.extend(line)

        elif geom_type == QgsWkbTypes.PolygonGeometry:
            # Для полигонов
            if geometry.isMultipart():
                # Мультиполигон
                multipolygon = geometry.asMultiPolygon()
                if multipolygon:
                    for polygon in multipolygon:
                        for ring in polygon:
                            vertices.extend(ring)
            else:
                # Одиночный полигон
                polygon = geometry.asPolygon()
                if polygon:
                    for ring in polygon:
                        vertices.extend(ring)

        return vertices
    
    @staticmethod
    def _round_geometry(geometry: QgsGeometry) -> Optional[QgsGeometry]:
        """
        Округление координат геометрии с использованием snappedToGrid.

        Использует QGIS snappedToGrid() вместо Python round() для обеспечения
        топологической совместимости (классическое математическое округление
        вместо банковского округления Python).

        Args:
            geometry: Исходная геометрия

        Returns:
            Геометрия с округленными координатами или None при ошибке
        """
        if geometry is None or geometry.isEmpty():
            return geometry

        # Размер сетки: 0.01м (1 см) = 10^(-PRECISION_DECIMALS)
        grid_size = 10 ** (-PRECISION_DECIMALS)  # 0.01

        # snappedToGrid использует классическое математическое округление
        # (round half away from zero), а не банковское (round half to even)
        rounded_geometry = geometry.snappedToGrid(grid_size, grid_size)

        # Проверка результата
        if rounded_geometry is None or rounded_geometry.isEmpty():
            # Fallback: если snappedToGrid вернул пустую геометрию,
            # возвращаем исходную (может произойти в граничных случаях)
            from Daman_QGIS.utils import log_warning
            log_warning("M_6: snappedToGrid вернул пустую геометрию, используем исходную")
            return geometry

        # Проверка валидности
        if not rounded_geometry.isGeosValid():
            rounded_geometry = rounded_geometry.makeValid()
            if rounded_geometry.isEmpty():
                from Daman_QGIS.utils import log_warning
                log_warning("M_6: Не удалось исправить геометрию после округления")
                return geometry

        return rounded_geometry
    
    @staticmethod
    def validate_and_round_layer(layer: QgsVectorLayer, auto_round: bool = False) -> bool:
        """
        Валидация и округление координат слоя с диалогом
        
        Args:
            layer: Векторный слой
            auto_round: Автоматически округлять без диалога
            
        Returns:
            True если слой прошел валидацию или был успешно округлен
        """
        if layer is None:
            return False

        # Проверяем точность координат
        needs_rounding, total_vertices, imprecise_vertices = \
            CoordinatePrecisionManager.check_layer_precision(layer)

        if not needs_rounding:
            # Координаты уже имеют правильную точность
            return True

        # Если требуется округление
        if auto_round:
            # Автоматическое округление
            return CoordinatePrecisionManager.round_layer_coordinates(layer)
        else:
            # Показываем диалог пользователю
            user_choice = CoordinatePrecisionManager.show_precision_dialog(
                layer.name(),
                imprecise_vertices,
                total_vertices
            )

            if user_choice:
                # Пользователь выбрал округление
                return CoordinatePrecisionManager.round_layer_coordinates(layer)
            else:
                # Пользователь отказался от округления
                log_warning(f"M_6_CoordinatePrecisionManager: Импорт слоя '{layer.name()}' отменен пользователем (точность координат)")
                return False
