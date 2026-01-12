# -*- coding: utf-8 -*-
"""
M_20_PointNumberingManager - Менеджер нумерации точек контуров

Формирует уникальную нумерацию характерных точек для полигональных слоёв.
Нумерация всегда начинается с 1 в пределах каждого слоя.

Алгоритм:
1. Первый проход: собираем уникальные точки (ключ = округлённые координаты)
2. Присваиваем номера в порядке обхода
3. Второй проход: формируем данные для точечного слоя

Особенности:
- Замыкающая точка НЕ отображается на графике (только для перечней координат)
- Дубликаты координат между контурами допустимы (общие точки)
- X/Y выводятся в геодезическом порядке (Y в графе X, X в графе Y)
"""

from typing import Dict, List, Tuple, Any

from qgis.core import (
    QgsPointXY,
    QgsGeometry,
    QgsWkbTypes,
    QgsVectorLayer,
)

from Daman_QGIS.managers import CoordinatePrecisionManager as CPM
from Daman_QGIS.constants import PRECISION_DECIMALS
from Daman_QGIS.utils import log_info, log_warning


class PointNumberingManager:
    """Менеджер нумерации точек контуров"""

    def __init__(self) -> None:
        """Инициализация менеджера"""
        self._unique_points: Dict[Tuple[float, float], int] = {}
        self._point_counter: int = 0

    def reset(self) -> None:
        """Сброс счётчика и словаря уникальных точек"""
        self._unique_points.clear()
        self._point_counter = 0

    def process_polygon_layer(
        self,
        features_data: List[Dict[str, Any]],
        precision: int = PRECISION_DECIMALS,
        auto_reset: bool = True
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Обработка полигональных объектов и формирование точечных данных

        Args:
            features_data: Список словарей с данными объектов:
                          - 'geometry': QgsGeometry (полигон)
                          - 'contour_id': int (ID контура)
                          - 'attributes': dict (атрибуты объекта)
            precision: Точность округления координат
            auto_reset: Сбросить счётчик перед обработкой (default=True).
                       При False нумерация продолжается с текущего значения.
                       Используется для сквозной нумерации Раздел+НГС из одной ЗПР.

        Returns:
            Tuple:
            - Обновлённый features_data с добавленным полем 'Точки'
            - Список точек для точечного слоя:
              [{'id': int, 'contour_point_index': int, 'contour_id': int,
                'uslov_kn': str, 'kn': str,
                'contour_type': str ('Внешний'/'Внутренний'),
                'contour_number': int (параллельная нумерация),
                'x_geodetic': float, 'y_geodetic': float, 'point': QgsPointXY}]
        """
        if auto_reset:
            self.reset()
        points_data: List[Dict[str, Any]] = []

        # Первый проход: собираем уникальные точки (включая внутренние контуры)
        for item in features_data:
            geom = item.get('geometry')
            if not geom or geom.isEmpty():
                continue

            # Используем новый метод для получения точек по кольцам
            rings_data = self._extract_polygon_points_by_ring(geom, precision)
            for ring_info in rings_data:
                for point_tuple in ring_info['points']:
                    if point_tuple not in self._unique_points:
                        self._point_counter += 1
                        self._unique_points[point_tuple] = self._point_counter

        # Второй проход: формируем данные точек и строки номеров
        for item in features_data:
            geom = item.get('geometry')
            # ВАЖНО: .get() возвращает None если ключ существует но значение None
            contour_id = item.get('contour_id')
            if contour_id is None:
                contour_id = 0

            # Извлекаем Услов_КН и КН из атрибутов контура
            attributes = item.get('attributes', {})
            uslov_kn = attributes.get('Услов_КН', '') or ''
            kn = attributes.get('КН', '') or ''

            if not geom or geom.isEmpty():
                item['point_numbers_str'] = ""
                continue

            # Получаем точки с разделением по кольцам
            rings_data = self._extract_polygon_points_by_ring(geom, precision)

            # Собираем номера для внешних и внутренних контуров отдельно
            # Для MultiPolygon может быть несколько внешних контуров
            exterior_numbers_list = []  # Список списков для каждого внешнего контура
            holes_numbers = []  # Список списков для каждой дырки

            for ring_info in rings_data:
                contour_type = ring_info['contour_type']
                contour_number = ring_info['contour_number']
                ring_numbers = []

                for contour_point_idx, point_tuple in enumerate(ring_info['points'], start=1):
                    point_num = self._unique_points.get(point_tuple, 0)
                    ring_numbers.append(point_num)

                    # Добавляем данные для точечного слоя
                    # X и Y в геодезическом порядке (Y -> X графы, X -> Y графы)
                    points_data.append({
                        'id': point_num,
                        'contour_point_index': contour_point_idx,  # Номер точки внутри контура
                        'contour_id': contour_id,
                        'uslov_kn': uslov_kn,  # Условный КН контура
                        'kn': kn,  # КН контура
                        'contour_type': contour_type,  # 'Внешний' или 'Внутренний'
                        'contour_number': contour_number,  # Параллельная нумерация
                        'x_geodetic': point_tuple[1],  # Y математический = X геодезический
                        'y_geodetic': point_tuple[0],  # X математический = Y геодезический
                        'point': QgsPointXY(point_tuple[0], point_tuple[1])
                    })

                if contour_type == 'Внешний':
                    exterior_numbers_list.append(ring_numbers)
                else:
                    holes_numbers.append(ring_numbers)

            # Формируем строку номеров точек с учётом внутренних контуров
            # Формат зависит от количества внешних контуров:
            # - Простой: "1, 2, 3, 4, 5"
            # - С дырками: "1, 2, 3, 4, 5; Внутренний контур 1: 6-10"
            # - Многоконтурный: "Внешний контур 1: 1-5; Внешний контур 2: 6-10"
            # - Многоконтурный с дырками: "Внешний контур 1: 1-5; Внешний контур 2: 6-10; Внутренний контур 1: 11-15"
            item['point_numbers_str'] = self._format_point_numbers_with_holes(
                exterior_numbers_list, holes_numbers
            )

        log_info(f"M_20: Обработано точек: {self._point_counter} уникальных, "
                f"{len(points_data)} всего (с дубликатами)")

        return features_data, points_data

    def _extract_polygon_points(
        self,
        geometry: QgsGeometry,
        precision: int
    ) -> List[Tuple[float, float]]:
        """
        Извлечение точек из полигона (без замыкающей точки)

        Args:
            geometry: Полигональная геометрия
            precision: Точность округления

        Returns:
            Список кортежей (x, y) округлённых координат
        """
        points: List[Tuple[float, float]] = []

        if geometry.type() != QgsWkbTypes.PolygonGeometry:
            return points

        # Нормализация: всегда обрабатываем как MultiPolygon
        polygons = (geometry.asMultiPolygon()
                   if geometry.isMultipart()
                   else [geometry.asPolygon()])

        for polygon in polygons:
            if not polygon:
                continue

            for ring in polygon:
                if not ring:
                    continue

                # Убираем замыкающую точку (если первая == последняя)
                # ВАЖНО: сравниваем округлённые координаты, а не QgsPointXY напрямую,
                # так как из-за float погрешности точки могут отличаться на ~1e-10
                ring_points = ring
                if len(ring) > 1:
                    first_rounded = CPM.round_point_tuple(ring[0], precision)
                    last_rounded = CPM.round_point_tuple(ring[-1], precision)
                    if first_rounded == last_rounded:
                        ring_points = ring[:-1]

                for point in ring_points:
                    point_tuple = CPM.round_point_tuple(point, precision)
                    points.append(point_tuple)

        return points

    def _extract_polygon_points_by_ring(
        self,
        geometry: QgsGeometry,
        precision: int
    ) -> List[Dict[str, Any]]:
        """
        Извлечение точек из полигона с разделением по контурам (внешние/внутренние)

        Реализует параллельную нумерацию:
        - Внешние контуры нумеруются отдельно: 1, 2, 3...
        - Внутренние контуры нумеруются отдельно: 1, 2, 3...

        Args:
            geometry: Полигональная геометрия
            precision: Точность округления

        Returns:
            Список словарей:
            [{'contour_type': 'Внешний'|'Внутренний',
              'contour_number': int (параллельная нумерация с 1),
              'points': [(x,y), ...]}]
        """
        rings_data: List[Dict[str, Any]] = []

        if geometry.type() != QgsWkbTypes.PolygonGeometry:
            return rings_data

        # Нормализация: всегда обрабатываем как MultiPolygon
        polygons = (geometry.asMultiPolygon()
                   if geometry.isMultipart()
                   else [geometry.asPolygon()])

        # Счётчики для параллельной нумерации
        exterior_counter = 0
        hole_counter = 0

        for polygon in polygons:
            if not polygon:
                continue

            for ring_idx, ring in enumerate(polygon):
                if not ring:
                    continue

                # Определяем тип и номер контура
                if ring_idx == 0:
                    # Внешний контур полигона
                    exterior_counter += 1
                    contour_type = 'Внешний'
                    contour_number = exterior_counter
                else:
                    # Внутренний контур (дырка)
                    hole_counter += 1
                    contour_type = 'Внутренний'
                    contour_number = hole_counter

                # Убираем замыкающую точку
                ring_points = ring
                if len(ring) > 1:
                    first_rounded = CPM.round_point_tuple(ring[0], precision)
                    last_rounded = CPM.round_point_tuple(ring[-1], precision)
                    if first_rounded == last_rounded:
                        ring_points = ring[:-1]

                points = []
                for point in ring_points:
                    point_tuple = CPM.round_point_tuple(point, precision)
                    points.append(point_tuple)

                if points:
                    rings_data.append({
                        'contour_type': contour_type,
                        'contour_number': contour_number,
                        'points': points
                    })

        return rings_data

    def _format_point_numbers(self, numbers: List[int]) -> str:
        """
        Форматирование списка номеров точек в строку с выделением диапазонов

        ВАЖНО: Сохраняет порядок обхода контура! Учитывает как возрастающие (+1),
        так и убывающие (-1) последовательности.

        Алгоритм:
        1. Определяем направление (шаг) между соседними числами
        2. Группируем числа с одинаковым шагом (+1 или -1)
        3. Диапазон записывается как "start-end" если содержит 3+ последовательных числа

        Примеры:
            [1, 2, 3, 4, 5] -> "1-5" (возрастающая)
            [5, 4, 3, 2, 1] -> "5-1" (убывающая)
            [171, 170, 229, 230, 231, 232] -> "171, 170, 229-232"
            [145, 144, 143, 142] -> "145-142" (убывающая)
            [1, 2, 3, 7, 8, 9, 10, 15] -> "1-3, 7-10, 15"

        Args:
            numbers: Список номеров точек (в порядке обхода контура)

        Returns:
            Форматированная строка
        """
        if not numbers:
            return ""

        if len(numbers) == 1:
            return str(numbers[0])

        # Разбиваем на группы последовательных чисел (учитываем +1 и -1)
        groups = []
        current_group = [numbers[0]]
        current_step = None  # Направление: +1 (возрастающая) или -1 (убывающая)

        for i in range(1, len(numbers)):
            diff = numbers[i] - current_group[-1]

            if diff == 1 or diff == -1:
                # Последовательность (+1 или -1)
                if current_step is None:
                    # Первый шаг - определяем направление
                    current_step = diff
                    current_group.append(numbers[i])
                elif diff == current_step:
                    # Продолжаем в том же направлении
                    current_group.append(numbers[i])
                else:
                    # Смена направления - новая группа
                    groups.append((current_group, current_step))
                    current_group = [numbers[i]]
                    current_step = None
            else:
                # Разрыв последовательности
                groups.append((current_group, current_step))
                current_group = [numbers[i]]
                current_step = None

        # Добавляем последнюю группу
        groups.append((current_group, current_step))

        # Форматируем каждую группу
        parts = []
        for group, step in groups:
            if len(group) >= 3:
                # Диапазон: 3+ последовательных числа -> "start-end"
                # Сохраняем порядок: первый-последний (независимо от направления)
                parts.append(f"{group[0]}-{group[-1]}")
            elif len(group) == 2:
                # Два числа: "a, b"
                parts.append(f"{group[0]}, {group[1]}")
            else:
                # Одно число
                parts.append(str(group[0]))

        return ", ".join(parts)

    def _format_point_numbers_with_holes(
        self,
        exterior_numbers_list: List[List[int]],
        holes_numbers: List[List[int]]
    ) -> str:
        """
        Форматирование номеров точек с учётом внутренних контуров (дырок)

        Формат зависит от количества внешних контуров:
        - Простой контур (1 внешний, нет дырок): "1, 2, 3, 4, 5"
        - С дырками (1 внешний): "1, 2, 3, 4, 5; Внутренний контур 1: 6-10"
        - Многоконтурный (>1 внешних): "Внешний контур 1: 1-5; Внешний контур 2: 6-10"
        - Многоконтурный с дырками: "Внешний контур 1: 1-5; Внешний контур 2: 6-10; Внутренний контур 1: 11-15"

        Args:
            exterior_numbers_list: Список списков номеров точек для каждого внешнего контура
            holes_numbers: Список списков номеров точек для каждой дырки

        Returns:
            Форматированная строка
        """
        parts = []
        is_multicontour = len(exterior_numbers_list) > 1

        # Внешние контуры
        for ext_idx, exterior_numbers in enumerate(exterior_numbers_list, start=1):
            if exterior_numbers:
                ext_str = self._format_point_numbers(exterior_numbers)
                if is_multicontour:
                    # Многоконтурный: добавляем префикс "Внешний контур N:"
                    parts.append(f"Внешний контур {ext_idx}: {ext_str}")
                else:
                    # Простой контур: просто номера
                    parts.append(ext_str)

        # Внутренние контуры (дырки)
        for hole_idx, hole_numbers in enumerate(holes_numbers, start=1):
            if hole_numbers:
                hole_str = self._format_point_numbers(hole_numbers)
                parts.append(f"Внутренний контур {hole_idx}: {hole_str}")

        return "; ".join(parts)

    def get_unique_points_count(self) -> int:
        """Получить количество уникальных точек"""
        return self._point_counter

    def get_unique_points_dict(self) -> Dict[Tuple[float, float], int]:
        """Получить словарь уникальных точек"""
        return self._unique_points.copy()


def number_layer_points(
    layer: QgsVectorLayer,
    contour_id_field: str = 'ID',
    precision: int = PRECISION_DECIMALS
) -> Tuple[Dict[int, str], List[Dict[str, Any]]]:
    """
    Утилита для нумерации точек существующего слоя

    Args:
        layer: Векторный слой (полигональный)
        contour_id_field: Имя поля с ID контура
        precision: Точность округления координат

    Returns:
        Tuple:
        - Dict[fid, point_numbers_str]: словарь {feature_id: строка_номеров}
        - List[Dict]: список точек для точечного слоя
    """
    if not layer or not layer.isValid():
        log_warning("M_20: Слой недействителен")
        return {}, []

    if layer.geometryType() != QgsWkbTypes.PolygonGeometry:
        log_warning(f"M_20: Слой {layer.name()} не полигональный")
        return {}, []

    # Собираем данные объектов
    features_data = []
    fid_mapping = {}  # {index: fid}

    for idx, feature in enumerate(layer.getFeatures()):
        if not feature.hasGeometry():
            continue

        contour_id = feature[contour_id_field] if contour_id_field in layer.fields().names() else feature.id()

        features_data.append({
            'geometry': feature.geometry(),
            'contour_id': contour_id,
            'attributes': dict(zip(layer.fields().names(), feature.attributes()))
        })
        fid_mapping[idx] = feature.id()

    # Обрабатываем через менеджер
    manager = PointNumberingManager()
    processed_data, points_data = manager.process_polygon_layer(features_data, precision)

    # Формируем результат
    result_dict = {}
    for idx, item in enumerate(processed_data):
        if idx in fid_mapping:
            result_dict[fid_mapping[idx]] = item.get('point_numbers_str', '')

    return result_dict, points_data
