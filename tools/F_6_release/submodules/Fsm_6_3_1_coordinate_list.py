# -*- coding: utf-8 -*-
"""
Fsm_6_3_1 - Экспорт перечней координат в Excel

Экспортирует координаты слоёв в Excel файл в формате приложений
с уникальной нумерацией точек и поддержкой WGS-84.

Шаблоны: Base_excel_export_styles.json
"""

import os
from typing import Dict, Any, List, Optional

from qgis.core import (
    QgsWkbTypes, QgsProject,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsVectorLayer
)

from Daman_QGIS.managers import CoordinatePrecisionManager as CPM, get_project_structure_manager
from Daman_QGIS.constants import PRECISION_DECIMALS, PRECISION_DECIMALS_WGS84
from Daman_QGIS.utils import log_info, log_warning, log_error, log_debug

# Исключения для слоёв точек (пока слои 1_4 не используют Т_* слои)
POINTS_LAYER_EXCLUSIONS = ['1_4']


class Fsm_6_3_1_CoordinateList:
    """Экспортёр перечней координат в Excel"""

    def __init__(self, iface, ref_managers):
        """
        Инициализация

        Args:
            iface: Интерфейс QGIS
            ref_managers: Reference managers
        """
        self.iface = iface
        self.ref_managers = ref_managers

    def _find_points_layer(self, layer_name: str) -> Optional[QgsVectorLayer]:
        """
        Найти слой точек Т_* для заданного слоя

        Логика поиска:
        - Для слоя L_X_Y_Z_Name ищем Т_X_Y_Z_Name
        - Для слоя Le_X_Y_Z_A_Name ищем Т_X_Y_Z_A_Name
        - Исключения: слои из POINTS_LAYER_EXCLUSIONS

        Args:
            layer_name: Имя исходного слоя

        Returns:
            Слой точек или None
        """
        # Проверяем исключения
        for exclusion in POINTS_LAYER_EXCLUSIONS:
            if exclusion in layer_name:
                log_debug(f"Fsm_6_3_1: Слой {layer_name} в исключениях для Т_* слоёв")
                return None

        # Формируем имя слоя точек
        # L_X_Y_Z_Name -> Т_X_Y_Z_Name
        # Le_X_Y_Z_A_Name -> Т_X_Y_Z_A_Name
        if layer_name.startswith('L_'):
            points_layer_name = 'Т_' + layer_name[2:]
        elif layer_name.startswith('Le_'):
            points_layer_name = 'Т_' + layer_name[3:]
        else:
            # Для других слоёв пробуем добавить Т_ к индексу
            points_layer_name = 'Т_' + layer_name

        # Ищем слой в проекте
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.name() == points_layer_name:
                if isinstance(lyr, QgsVectorLayer) and lyr.geometryType() == QgsWkbTypes.PointGeometry:
                    log_info(f"Fsm_6_3_1: Найден слой точек: {points_layer_name}")
                    return lyr

        log_debug(f"Fsm_6_3_1: Слой точек {points_layer_name} не найден")
        return None

    def _build_points_index(
        self,
        points_layer: QgsVectorLayer,
        precision: int = PRECISION_DECIMALS
    ) -> Dict[tuple, int]:
        """
        Построить индекс точек из слоя Т_*

        Args:
            points_layer: Слой точек
            precision: Точность округления координат

        Returns:
            Словарь {(x_rounded, y_rounded): номер_точки}
        """
        points_index = {}

        # Ищем поле с номером точки
        num_field = None
        for field_name in ['n', 'num', 'point_num', 'number', 'ID', 'id']:
            if points_layer.fields().indexOf(field_name) >= 0:
                num_field = field_name
                break

        if not num_field:
            log_warning(f"Fsm_6_3_1: В слое точек не найдено поле номера")
            return points_index

        for feature in points_layer.getFeatures():
            if not feature.hasGeometry():
                continue

            point = feature.geometry().asPoint()
            key = CPM.round_point_tuple(point, precision)
            point_num = feature[num_field]

            if point_num is not None:
                points_index[key] = point_num

        log_info(f"Fsm_6_3_1: Загружено {len(points_index)} точек из слоя Т_*")
        return points_index

    def _build_points_index_with_transform(
        self,
        points_layer: QgsVectorLayer,
        transform: QgsCoordinateTransform,
        precision: int = PRECISION_DECIMALS_WGS84
    ) -> Dict[tuple, int]:
        """
        Построить индекс точек из слоя Т_* с трансформацией координат

        Args:
            points_layer: Слой точек
            transform: Трансформация координат
            precision: Точность округления координат

        Returns:
            Словарь {(x_rounded, y_rounded): номер_точки}
        """
        points_index = {}

        # Ищем поле с номером точки
        num_field = None
        for field_name in ['n', 'num', 'point_num', 'number', 'ID', 'id']:
            if points_layer.fields().indexOf(field_name) >= 0:
                num_field = field_name
                break

        if not num_field:
            log_warning(f"Fsm_6_3_1: В слое точек не найдено поле номера")
            return points_index

        for feature in points_layer.getFeatures():
            if not feature.hasGeometry():
                continue

            geom = feature.geometry()
            geom.transform(transform)
            point = geom.asPoint()

            key = CPM.round_point_tuple(point, precision)
            point_num = feature[num_field]

            if point_num is not None:
                points_index[key] = point_num

        log_info(f"Fsm_6_3_1: Загружено {len(points_index)} точек из слоя Т_* (WGS84)")
        return points_index

    def export_layer(
        self,
        layer: QgsVectorLayer,
        style: Dict[str, Any],
        output_folder: str,
        create_wgs84: bool = False
    ) -> bool:
        """
        Экспорт слоя в Excel (перечень координат)

        Args:
            layer: Слой для экспорта
            style: Стиль из Base_excel_export_styles.json
            output_folder: Папка для сохранения
            create_wgs84: Создавать версию WGS-84

        Returns:
            bool: Успешность экспорта
        """
        try:
            import xlsxwriter
        except ImportError:
            log_error("Fsm_6_3_1: Библиотека xlsxwriter не установлена")
            return False

        # Экспорт в основной СК
        success = self._export_to_excel(layer, style, output_folder, False)

        # Экспорт в WGS-84 если нужно
        if success and create_wgs84:
            self._export_to_excel(layer, style, output_folder, True)

        return success

    def _export_to_excel(
        self,
        layer: QgsVectorLayer,
        style: Dict[str, Any],
        output_folder: str,
        is_wgs84: bool = False
    ) -> bool:
        """
        Экспорт одного слоя в Excel

        Args:
            layer: Слой для экспорта
            style: Стиль из базы данных
            output_folder: Папка для сохранения
            is_wgs84: Экспортировать в WGS-84

        Returns:
            bool: Успешность экспорта
        """
        import xlsxwriter

        # Получаем метаданные проекта
        metadata = self._get_project_metadata()

        # Формируем имя файла
        appendix_num = 'X'  # Фиксированный номер приложения
        if is_wgs84:
            filename = f"Приложение_{appendix_num}_координаты_WGS84.xlsx"
        else:
            filename = f"Приложение_{appendix_num}_координаты.xlsx"
        filepath = os.path.join(output_folder, filename)

        # Создаем Excel файл
        workbook = xlsxwriter.Workbook(filepath)
        worksheet = workbook.add_worksheet('Координаты')

        # Настройка ширины колонок (все по 30)
        for col in range(5):  # A-E
            worksheet.set_column(col, col, 30)

        # Форматы
        appendix_format = workbook.add_format({
            'font_name': 'Times New Roman',
            'font_size': 11,
            'italic': True,
            'bold': True,
            'align': 'right',
            'valign': 'vcenter',
            'text_wrap': True
        })

        title_format = workbook.add_format({
            'font_name': 'Times New Roman',
            'font_size': 16,
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True
        })

        crs_format = workbook.add_format({
            'font_name': 'Times New Roman',
            'font_size': 12,
            'bold': True,
            'align': 'right',
            'valign': 'vcenter'
        })

        contour_title_format = workbook.add_format({
            'font_name': 'Times New Roman',
            'font_size': 12,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True
        })

        column_format = workbook.add_format({
            'font_name': 'Times New Roman',
            'font_size': 12,
            'align': 'center',
            'valign': 'vcenter'
        })

        # Строка 1: Номер приложения (колонка E)
        appendix_text = f"Приложение {appendix_num}"
        worksheet.write('E1', appendix_text, appendix_format)  # type: ignore[arg-type]

        # Строка 2: Заголовок (объединение A2:E2)
        title_text = self.ref_managers.excel_export_style.format_excel_export_text(
            style.get('title', ''),
            metadata,
            {'layer_name': layer.name()}
        )
        worksheet.merge_range('A2:E2', title_text, title_format)  # type: ignore[call-arg]

        # Строка 4: Система координат (объединение D4:E4)
        if is_wgs84:
            crs_text = "Система координат: WGS-84"
        else:
            crs_name = self.ref_managers.excel_export_style.format_excel_export_text(
                "{crs_name}",
                metadata
            )
            crs_text = f"Система координат: {crs_name}"
        worksheet.merge_range('D4:E4', crs_text, crs_format)  # type: ignore[call-arg]

        # Получаем координаты и контуры
        contours_data = self._collect_contours_with_coordinates(layer, style, is_wgs84)

        # Начинаем с 6 строки (индекс 5)
        current_row = 5
        contour_number = 0

        # Обрабатываем каждый контур
        for contour_info in contours_data:
            contour_type = contour_info['type']
            coordinates = contour_info['coordinates']
            area = contour_info.get('area', 0)
            ring_index = contour_info.get('ring_index', 0)

            # Для внешних контуров выводим наименование
            if contour_type == 'exterior':
                contour_number += 1
                contour_title = style.get('contour_title', '')
                if contour_title:
                    formatted_title = self.ref_managers.excel_export_style.format_excel_export_text(
                        contour_title,
                        metadata,
                        {'area': area, 'layer_name': layer.name(), '№': contour_number}
                    )
                    worksheet.merge_range(
                        current_row, 1, current_row, 3,
                        formatted_title,
                        contour_title_format
                    )
                current_row += 1
                current_row += 1  # Пустая строка

                # Заголовки колонок
                worksheet.write(current_row, 1, '№ Точки', column_format)
                if is_wgs84:
                    worksheet.write(current_row, 2, 'Широта', column_format)
                    worksheet.write(current_row, 3, 'Долгота', column_format)
                else:
                    worksheet.write(current_row, 2, 'X, м', column_format)
                    worksheet.write(current_row, 3, 'Y, м', column_format)
                current_row += 1
            else:
                # Для внутренних контуров (дырок) - заголовок с номером
                current_row += 1
                hole_title = f"Внутренний контур {ring_index}"
                worksheet.merge_range(
                    current_row, 1, current_row, 3,
                    hole_title,
                    contour_title_format
                )
                current_row += 1

                # Заголовки колонок
                worksheet.write(current_row, 1, '№ Точки', column_format)
                if is_wgs84:
                    worksheet.write(current_row, 2, 'Широта', column_format)
                    worksheet.write(current_row, 3, 'Долгота', column_format)
                else:
                    worksheet.write(current_row, 2, 'X, м', column_format)
                    worksheet.write(current_row, 3, 'Y, м', column_format)
                current_row += 1

            # Выводим координаты точек
            for coord in coordinates:
                worksheet.write(current_row, 1, coord[0], column_format)

                if is_wgs84:
                    worksheet.write(current_row, 2, f"{coord[2]:.6f}", column_format)
                    worksheet.write(current_row, 3, f"{coord[1]:.6f}", column_format)
                else:
                    # Меняем X и Y (математическая vs геодезическая)
                    worksheet.write(current_row, 2, f"{coord[2]:.2f}", column_format)
                    worksheet.write(current_row, 3, f"{coord[1]:.2f}", column_format)
                current_row += 1

            current_row += 1  # Пустая строка после контура

        # Настройка области печати
        worksheet.print_area(0, 0, current_row - 1, 4)

        workbook.close()

        log_info(f"Fsm_6_3_1: Экспорт завершён: {filepath}")
        return True

    def _collect_contours_with_coordinates(
        self,
        layer: QgsVectorLayer,
        style: Dict[str, Any],
        is_wgs84: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Сбор контуров с координатами и уникальной нумерацией точек

        Приоритет получения номеров точек:
        1. Слой точек Т_* (если существует и не в исключениях)
        2. Автоматическая нумерация

        Args:
            layer: Слой QGIS
            style: Стиль из базы
            is_wgs84: Нужна ли трансформация в WGS-84

        Returns:
            Список контуров с координатами
        """
        contours = []
        precision = PRECISION_DECIMALS_WGS84 if is_wgs84 else PRECISION_DECIMALS

        # Создаём трансформацию если нужна
        transform = None
        if is_wgs84:
            wgs84_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            if layer.crs() != wgs84_crs:
                transform = QgsCoordinateTransform(
                    layer.crs(),
                    wgs84_crs,
                    QgsProject.instance()
                )

        # Пытаемся найти слой точек Т_*
        points_layer = self._find_points_layer(layer.name())
        points_index = {}

        if points_layer:
            # Строим индекс точек из слоя Т_*
            # Для WGS84 нужно трансформировать точки из слоя
            if is_wgs84 and transform:
                # Создаём трансформацию для слоя точек
                points_transform = QgsCoordinateTransform(
                    points_layer.crs(),
                    QgsCoordinateReferenceSystem("EPSG:4326"),
                    QgsProject.instance()
                )
                points_index = self._build_points_index_with_transform(
                    points_layer, points_transform, precision
                )
            else:
                points_index = self._build_points_index(points_layer, precision)

        use_points_layer = bool(points_index)

        # Собираем уникальные точки и контуры
        unique_points = {}
        point_number = 1
        all_raw_contours = []

        # Определяем тип геометрии слоя
        layer_geom_type = layer.geometryType()

        # Если это точечный слой - используем специальную обработку
        if layer_geom_type == QgsWkbTypes.PointGeometry:
            return self._collect_points_from_point_layer(layer, transform, precision)

        for feature in layer.getFeatures():
            if not feature.hasGeometry():
                continue

            geometry = feature.geometry()

            if transform:
                geometry.transform(transform)

            area_sqm = geometry.area()

            if geometry.type() == QgsWkbTypes.PolygonGeometry:
                polygons = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]

                for polygon_idx, polygon in enumerate(polygons):
                    if polygon:
                        exterior_ring = polygon[0]
                        points = exterior_ring[:-1] if len(exterior_ring) > 1 and exterior_ring[0] == exterior_ring[-1] else exterior_ring

                        for point in points:
                            key = CPM.round_point_tuple(point, precision)
                            if key not in unique_points:
                                if use_points_layer and key in points_index:
                                    # Берём номер из слоя точек
                                    unique_points[key] = points_index[key]
                                else:
                                    # Автоматическая нумерация
                                    unique_points[key] = point_number
                                    point_number += 1

                        all_raw_contours.append({
                            'type': 'exterior',
                            'ring_index': 0,
                            'points': points,
                            'area': area_sqm if polygon_idx == 0 else 0
                        })

                        # Внутренние контуры (дырки)
                        for hole_idx, hole in enumerate(polygon[1:], start=1):
                            hole_points = hole[:-1] if len(hole) > 1 and hole[0] == hole[-1] else hole

                            for point in hole_points:
                                key = CPM.round_point_tuple(point, precision)
                                if key not in unique_points:
                                    if use_points_layer and key in points_index:
                                        # Берём номер из слоя точек
                                        unique_points[key] = points_index[key]
                                    else:
                                        # Автоматическая нумерация
                                        unique_points[key] = point_number
                                        point_number += 1

                            all_raw_contours.append({
                                'type': 'hole',
                                'ring_index': hole_idx,
                                'points': hole_points,
                                'area': 0
                            })

        # Второй проход: формируем финальные контуры
        for raw_contour in all_raw_contours:
            contour_coords = []
            points = raw_contour['points']

            for point in points:
                precision = PRECISION_DECIMALS_WGS84 if is_wgs84 else PRECISION_DECIMALS
                key = CPM.round_point_tuple(point, precision)
                point_num = unique_points[key]

                contour_coords.append([
                    point_num,
                    CPM.round_coordinate(point.x(), precision),
                    CPM.round_coordinate(point.y(), precision)
                ])

            # Замыкаем контур первой точкой
            if len(points) > 1:
                first_point = points[0]
                precision = PRECISION_DECIMALS_WGS84 if is_wgs84 else PRECISION_DECIMALS
                key = CPM.round_point_tuple(first_point, precision)
                point_num = unique_points[key]

                contour_coords.append([
                    point_num,
                    CPM.round_coordinate(first_point.x(), precision),
                    CPM.round_coordinate(first_point.y(), precision)
                ])

            contours.append({
                'type': raw_contour['type'],
                'ring_index': raw_contour.get('ring_index', 0),
                'coordinates': contour_coords,
                'area': raw_contour['area']
            })

        return contours

    def _collect_points_from_point_layer(
        self,
        layer: QgsVectorLayer,
        transform: Optional[QgsCoordinateTransform],
        precision: int
    ) -> List[Dict[str, Any]]:
        """
        Сбор точек из точечного слоя (Т_*)

        Точечные слои уже содержат структуру с номерами точек и ID контуров.
        Группируем точки по ID_Контура и типу кольца (exterior/hole).

        Args:
            layer: Точечный слой
            transform: Трансформация координат (для WGS84)
            precision: Точность округления

        Returns:
            Список контуров с координатами
        """
        from collections import defaultdict

        # Ищем необходимые поля
        id_field = None
        contour_id_field = None
        ring_type_field = None
        ring_index_field = None
        point_index_field = None  # Номер точки внутри контура (для сортировки)

        field_names = [f.name() for f in layer.fields()]

        # Поле номера точки (глобальный номер)
        for name in ['ID', 'id', 'n', 'num', 'point_num', 'number']:
            if name in field_names:
                id_field = name
                break

        # Поле номера точки внутри контура (для сортировки)
        for name in ['ID_Точки_контура', 'contour_point_index', 'point_index']:
            if name in field_names:
                point_index_field = name
                break

        # Поле ID контура
        for name in ['ID_Контура', 'contour_id', 'ID_контура']:
            if name in field_names:
                contour_id_field = name
                break

        # Поле типа кольца
        for name in ['Тип_кольца', 'ring_type']:
            if name in field_names:
                ring_type_field = name
                break

        # Поле индекса кольца
        for name in ['Индекс_кольца', 'ring_index']:
            if name in field_names:
                ring_index_field = name
                break

        if not id_field:
            log_warning(f"Fsm_6_3_1: В точечном слое не найдено поле номера точки")
            return []

        log_info(f"Fsm_6_3_1: Точечный слой '{layer.name()}': "
                f"id_field={id_field}, contour_id_field={contour_id_field}, "
                f"point_index_field={point_index_field}, ring_type_field={ring_type_field}")

        # Группируем точки по контурам и кольцам
        # Ключ: (contour_id, ring_type, ring_index)
        # Значение: список точек [(номер, x, y), ...]
        contour_points = defaultdict(list)

        for feature in layer.getFeatures():
            if not feature.hasGeometry():
                continue

            geometry = feature.geometry()
            if transform:
                geometry.transform(transform)

            point = geometry.asPoint()
            point_num = feature[id_field]

            # Получаем ID контура
            contour_id = 0
            if contour_id_field:
                contour_id = feature[contour_id_field] or 0

            # Получаем тип кольца
            ring_type = 'exterior'
            if ring_type_field:
                rt = feature[ring_type_field]
                if rt:
                    ring_type = str(rt).lower()
                    if ring_type == 'hole':
                        ring_type = 'hole'
                    else:
                        ring_type = 'exterior'

            # Получаем индекс кольца
            ring_index = 0
            if ring_index_field:
                ri = feature[ring_index_field]
                if ri is not None:
                    ring_index = int(ri)

            # Получаем индекс точки внутри контура (для сортировки)
            point_idx = 0
            if point_index_field:
                pi = feature[point_index_field]
                if pi is not None:
                    point_idx = int(pi)

            key = (contour_id, ring_type, ring_index)
            contour_points[key].append({
                'num': point_num,
                'point_idx': point_idx,  # Для сортировки внутри контура
                'x': CPM.round_coordinate(point.x(), precision),
                'y': CPM.round_coordinate(point.y(), precision)
            })

        # Формируем результат
        contours = []

        # Сортируем ключи: сначала по contour_id, потом по ring_index
        # Это гарантирует что exterior идёт перед hole для каждого контура
        sorted_keys = sorted(contour_points.keys(), key=lambda k: (k[0], k[2]))

        for key in sorted_keys:
            contour_id, ring_type, ring_index = key
            points = contour_points[key]

            # Сортируем точки по номеру внутри контура (ID_Точки_контура)
            # Это гарантирует правильный порядок обхода контура
            points.sort(key=lambda p: p['point_idx'])

            coordinates = []
            for pt in points:
                coordinates.append([pt['num'], pt['x'], pt['y']])

            # Добавляем замыкающую точку (первая = последняя)
            if coordinates:
                first_coord = coordinates[0]
                coordinates.append([first_coord[0], first_coord[1], first_coord[2]])

            contours.append({
                'type': ring_type,
                'contour_id': contour_id,  # Добавляем ID контура для группировки
                'ring_index': ring_index,  # Индекс кольца (0=exterior, 1+=hole)
                'coordinates': coordinates,
                'area': 0  # Площадь неизвестна для точечного слоя
            })

        log_info(f"Fsm_6_3_1: Собрано {len(contours)} контуров из точечного слоя")
        return contours

    def _get_project_metadata(self) -> Dict[str, Any]:
        """Получить метаданные проекта из GeoPackage"""
        import sqlite3

        # Используем M_19 для получения пути к GPKG
        structure_manager = get_project_structure_manager()
        project_path = QgsProject.instance().homePath()
        if project_path:
            structure_manager.project_root = project_path
        gpkg_path = structure_manager.get_gpkg_path(create=False)

        if not gpkg_path or not os.path.exists(gpkg_path):
            return {}

        try:
            conn = sqlite3.connect(gpkg_path)
            cursor = conn.cursor()

            cursor.execute("SELECT key, value FROM project_metadata")
            rows = cursor.fetchall()

            metadata = {}
            for key, value in rows:
                metadata[key] = value

            conn.close()
            return metadata
        except Exception as e:
            log_warning(f"Fsm_6_3_1: Ошибка чтения метаданных: {str(e)}")
            return {}
