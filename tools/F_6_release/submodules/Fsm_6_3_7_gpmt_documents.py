# -*- coding: utf-8 -*-
"""
Fsm_6_3_7 - Экспорт документов ГПМТ

Экспортирует документы для границ проекта межевания территории:
- Перечень координат характерных точек границ ГПМТ
- Ведомость характеристик ГПМТ (площади, периметры)
"""

import os
from typing import List, Dict, Any, Optional, Tuple

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsWkbTypes,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform
)

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers import (
    get_project_structure_manager, FolderType,
    CoordinatePrecisionManager as CPM
)
from Daman_QGIS.constants import PRECISION_DECIMALS, PRECISION_DECIMALS_WGS84


class Fsm_6_3_7_GPMTDocuments:
    """Экспортёр документов ГПМТ"""

    # Слои ГПМТ
    GPMT_LAYERS = [
        'L_2_6_1_ГПМТ',
        'L_2_5_1_ГПМТ',  # Альтернативное имя
    ]

    def __init__(self, iface, ref_managers=None):
        """
        Инициализация экспортёра

        Args:
            iface: Интерфейс QGIS
            ref_managers: Reference managers
        """
        self.iface = iface
        self.ref_managers = ref_managers

    def export_coordinates(
        self,
        output_folder: Optional[str] = None,
        create_wgs84: bool = False
    ) -> Tuple[bool, str]:
        """
        Экспорт перечня координат ГПМТ

        Args:
            output_folder: Папка для сохранения
            create_wgs84: Создать версию в WGS-84

        Returns:
            Tuple[bool, str]: (успешность, путь к файлу)
        """
        try:
            import xlsxwriter
        except ImportError:
            log_error("Fsm_6_3_7: Библиотека xlsxwriter не установлена")
            return False, ""

        # Находим слой ГПМТ
        layer = self._find_gpmt_layer()
        if layer is None:
            log_error("Fsm_6_3_7: Слой ГПМТ не найден")
            return False, ""

        # Определяем папку
        if not output_folder:
            output_folder = self._get_output_folder()
            if not output_folder:
                return False, ""

        os.makedirs(output_folder, exist_ok=True)

        # Получаем метаданные
        metadata = self._get_project_metadata()

        # Экспорт в основной СК
        filepath = os.path.join(output_folder, "ГПМТ_координаты.xlsx")
        success = self._export_coordinates_to_excel(layer, filepath, metadata, False)

        # Экспорт в WGS-84 если нужно
        if success and create_wgs84:
            filepath_wgs = os.path.join(output_folder, "ГПМТ_координаты_WGS84.xlsx")
            self._export_coordinates_to_excel(layer, filepath_wgs, metadata, True)

        return success, filepath

    def export_characteristics(
        self,
        output_folder: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Экспорт ведомости характеристик ГПМТ

        Args:
            output_folder: Папка для сохранения

        Returns:
            Tuple[bool, str]: (успешность, путь к файлу)
        """
        try:
            import xlsxwriter
        except ImportError:
            log_error("Fsm_6_3_7: Библиотека xlsxwriter не установлена")
            return False, ""

        layer = self._find_gpmt_layer()
        if layer is None:
            log_error("Fsm_6_3_7: Слой ГПМТ не найден")
            return False, ""

        if not output_folder:
            output_folder = self._get_output_folder()
            if not output_folder:
                return False, ""

        os.makedirs(output_folder, exist_ok=True)

        filepath = os.path.join(output_folder, "ГПМТ_характеристики.xlsx")

        try:
            workbook = xlsxwriter.Workbook(filepath)
            worksheet = workbook.add_worksheet('Характеристики')

            # Форматы
            header_format = workbook.add_format({
                'font_name': 'Times New Roman',
                'font_size': 12,
                'bold': True,
                'align': 'center',
                'valign': 'vcenter',
                'border': 1,
                'bg_color': '#DDEBF7',
                'text_wrap': True
            })

            cell_format = workbook.add_format({
                'font_name': 'Times New Roman',
                'font_size': 11,
                'align': 'center',
                'valign': 'vcenter',
                'border': 1
            })

            num_format = workbook.add_format({
                'font_name': 'Times New Roman',
                'font_size': 11,
                'align': 'center',
                'valign': 'vcenter',
                'border': 1,
                'num_format': '#,##0.00'
            })

            # Заголовки
            headers = ['№ п/п', 'Наименование', 'Площадь, кв.м', 'Периметр, м', 'Кол-во точек']
            widths = [8, 40, 15, 15, 12]

            for col, (header, width) in enumerate(zip(headers, widths)):
                worksheet.set_column(col, col, width)
                worksheet.write(0, col, header, header_format)

            # Данные
            row = 1
            total_area = 0
            total_perimeter = 0

            for feature in layer.getFeatures():
                if not feature.hasGeometry():
                    continue

                geom = feature.geometry()
                if geom.isEmpty():
                    continue

                # Получаем характеристики
                area = geom.area()
                perimeter = geom.length()
                point_count = self._count_points(geom)

                # Наименование из атрибутов или номер
                name = feature['Наименование'] if 'Наименование' in [f.name() for f in layer.fields()] else f"Контур {row}"

                worksheet.write(row, 0, row, cell_format)
                worksheet.write(row, 1, str(name) if name else f"Контур {row}", cell_format)
                worksheet.write(row, 2, area, num_format)
                worksheet.write(row, 3, perimeter, num_format)
                worksheet.write(row, 4, point_count, cell_format)

                total_area += area
                total_perimeter += perimeter
                row += 1

            # Итого
            if row > 1:
                total_format = workbook.add_format({
                    'font_name': 'Times New Roman',
                    'font_size': 11,
                    'bold': True,
                    'align': 'center',
                    'valign': 'vcenter',
                    'border': 1,
                    'num_format': '#,##0.00'
                })

                worksheet.write(row, 0, '', total_format)
                worksheet.write(row, 1, 'ИТОГО', total_format)
                worksheet.write(row, 2, total_area, total_format)
                worksheet.write(row, 3, total_perimeter, total_format)
                worksheet.write(row, 4, '', total_format)

            workbook.close()
            log_info(f"Fsm_6_3_7: Характеристики ГПМТ сохранены: {filepath}")
            return True, filepath

        except Exception as e:
            log_error(f"Fsm_6_3_7: Ошибка создания Excel: {str(e)}")
            return False, ""

    def _find_gpmt_layer(self) -> Optional[QgsVectorLayer]:
        """Найти слой ГПМТ в проекте"""
        for layer_name in self.GPMT_LAYERS:
            layers = QgsProject.instance().mapLayersByName(layer_name)
            if layers and isinstance(layers[0], QgsVectorLayer):
                if layers[0].featureCount() > 0:
                    return layers[0]

        # Поиск по частичному совпадению
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and 'ГПМТ' in layer.name():
                if layer.featureCount() > 0:
                    return layer

        return None

    def _get_output_folder(self) -> Optional[str]:
        """Получить папку для сохранения"""
        try:
            structure_manager = get_project_structure_manager()

            if not structure_manager.is_active():
                project_path = QgsProject.instance().homePath()
                if project_path:
                    structure_manager.project_root = project_path

            if structure_manager.is_active():
                return structure_manager.get_folder(FolderType.DOCUMENTS)

            return None
        except Exception:
            return None

    def _get_project_metadata(self) -> Dict[str, Any]:
        """Получить метаданные проекта"""
        import sqlite3

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
            conn.close()

            return {key: value for key, value in rows}
        except Exception:
            return {}

    def _export_coordinates_to_excel(
        self,
        layer: QgsVectorLayer,
        filepath: str,
        metadata: Dict[str, Any],
        is_wgs84: bool
    ) -> bool:
        """Экспорт координат в Excel файл"""
        import xlsxwriter

        precision = PRECISION_DECIMALS_WGS84 if is_wgs84 else PRECISION_DECIMALS

        # Трансформация для WGS-84
        transform = None
        if is_wgs84:
            wgs84_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            if layer.crs() != wgs84_crs:
                transform = QgsCoordinateTransform(
                    layer.crs(),
                    wgs84_crs,
                    QgsProject.instance()
                )

        try:
            workbook = xlsxwriter.Workbook(filepath)
            worksheet = workbook.add_worksheet('Координаты')

            # Настройка колонок
            worksheet.set_column(0, 0, 5)   # Пустая
            worksheet.set_column(1, 1, 12)  # № точки
            worksheet.set_column(2, 2, 18)  # X
            worksheet.set_column(3, 3, 18)  # Y

            # Форматы
            title_format = workbook.add_format({
                'font_name': 'Times New Roman',
                'font_size': 14,
                'bold': True,
                'align': 'center',
                'valign': 'vcenter',
                'text_wrap': True
            })

            header_format = workbook.add_format({
                'font_name': 'Times New Roman',
                'font_size': 12,
                'bold': True,
                'align': 'center',
                'valign': 'vcenter',
                'border': 1
            })

            cell_format = workbook.add_format({
                'font_name': 'Times New Roman',
                'font_size': 11,
                'align': 'center',
                'valign': 'vcenter',
                'border': 1
            })

            crs_format = workbook.add_format({
                'font_name': 'Times New Roman',
                'font_size': 11,
                'bold': True,
                'align': 'right',
                'valign': 'vcenter'
            })

            # Заголовок
            object_type = metadata.get('1_3_object_type', 'линейного')
            title = f"Перечень координат характерных точек границ территории, применительно к которой осуществляется подготовка проекта межевания территории {object_type} объекта"
            worksheet.merge_range('A1:D1', title, title_format)  # type: ignore[call-arg]
            worksheet.set_row(0, 45)

            # Система координат
            if is_wgs84:
                crs_text = "Система координат: WGS-84"
            else:
                crs_name = metadata.get('1_4_crs_short', 'МСК')
                crs_text = f"Система координат: {crs_name}"
            worksheet.merge_range('C3:D3', crs_text, crs_format)  # type: ignore[call-arg]

            # Заголовки колонок
            row = 4
            worksheet.write(row, 1, '№ Точки', header_format)
            if is_wgs84:
                worksheet.write(row, 2, 'Широта', header_format)
                worksheet.write(row, 3, 'Долгота', header_format)
            else:
                worksheet.write(row, 2, 'X, м', header_format)
                worksheet.write(row, 3, 'Y, м', header_format)

            row += 1

            # Собираем координаты
            point_number = 1
            for feature in layer.getFeatures():
                if not feature.hasGeometry():
                    continue

                geometry = feature.geometry()
                if transform:
                    geometry.transform(transform)

                if geometry.type() == QgsWkbTypes.PolygonGeometry:
                    polygons = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]

                    for polygon in polygons:
                        if not polygon:
                            continue

                        # Внешнее кольцо
                        exterior = polygon[0]
                        points = exterior[:-1] if len(exterior) > 1 and exterior[0] == exterior[-1] else exterior

                        for point in points:
                            x = CPM.round_coordinate(point.x(), precision)
                            y = CPM.round_coordinate(point.y(), precision)

                            worksheet.write(row, 1, point_number, cell_format)
                            if is_wgs84:
                                worksheet.write(row, 2, f"{y:.6f}", cell_format)
                                worksheet.write(row, 3, f"{x:.6f}", cell_format)
                            else:
                                worksheet.write(row, 2, f"{y:.2f}", cell_format)
                                worksheet.write(row, 3, f"{x:.2f}", cell_format)

                            row += 1
                            point_number += 1

                        # Замыкающая точка
                        if points:
                            first = points[0]
                            x = CPM.round_coordinate(first.x(), precision)
                            y = CPM.round_coordinate(first.y(), precision)

                            worksheet.write(row, 1, 1, cell_format)  # Возврат к первой точке
                            if is_wgs84:
                                worksheet.write(row, 2, f"{y:.6f}", cell_format)
                                worksheet.write(row, 3, f"{x:.6f}", cell_format)
                            else:
                                worksheet.write(row, 2, f"{y:.2f}", cell_format)
                                worksheet.write(row, 3, f"{x:.2f}", cell_format)
                            row += 1

            workbook.close()
            log_info(f"Fsm_6_3_7: Координаты ГПМТ сохранены: {filepath}")
            return True

        except Exception as e:
            log_error(f"Fsm_6_3_7: Ошибка экспорта координат: {str(e)}")
            return False

    def _count_points(self, geometry) -> int:
        """Подсчитать количество точек в геометрии"""
        if geometry.type() != QgsWkbTypes.PolygonGeometry:
            return 0

        count = 0
        polygons = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]

        for polygon in polygons:
            for ring in polygon:
                # Не считаем замыкающую точку
                count += len(ring) - 1 if len(ring) > 1 and ring[0] == ring[-1] else len(ring)

        return count

    # === API для интеграции с DocumentFactory ===

    def export_layer(
        self,
        layer: QgsVectorLayer,
        style: Dict[str, Any],
        output_folder: str,
        **kwargs
    ) -> bool:
        """
        Метод для совместимости с BaseExporter интерфейсом

        Args:
            layer: Слой ГПМТ (может быть проигнорирован)
            style: Стиль
            output_folder: Папка для сохранения
            **kwargs: Дополнительные параметры

        Returns:
            bool: Успешность экспорта
        """
        doc_type = kwargs.get('gpmt_doc_type', 'coordinates')
        create_wgs84 = kwargs.get('create_wgs84', False)

        if doc_type == 'characteristics':
            success, _ = self.export_characteristics(output_folder)
        else:
            success, _ = self.export_coordinates(output_folder, create_wgs84)

        return success
