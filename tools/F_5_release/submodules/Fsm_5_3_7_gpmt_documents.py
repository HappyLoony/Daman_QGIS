# -*- coding: utf-8 -*-
"""
Fsm_5_3_7 - Экспорт документов ГПМТ

Экспортирует документы для границ проекта межевания территории:
- Перечень координат характерных точек границ ГПМТ
- Ведомость характеристик ГПМТ (площади, периметры)

Шаблоны: Fsm_5_3_8_template_registry.py (DocumentTemplate)
Форматы: Fsm_5_3_4_format_manager.py (ExcelFormatManager)
"""

import os
from typing import List, Dict, Any, Optional, Tuple

from qgis.core import (
    Qgis, QgsProject, QgsVectorLayer,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform
)

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers import (
    registry, FolderType,
    CoordinatePrecisionManager as CPM
)
from Daman_QGIS.constants import PRECISION_DECIMALS, PRECISION_DECIMALS_WGS84

from .Fsm_5_3_4_format_manager import ExcelFormatManager
from .Fsm_5_3_5_export_utils import ExportUtils
from .Fsm_5_3_8_template_registry import (
    DocumentTemplate, TemplateRegistry,
    COORD_HEADERS_LOCAL, COORD_HEADERS_WGS84
)


class Fsm_5_3_7_GPMTDocuments:
    """Экспортёр документов ГПМТ"""

    def __init__(self, iface, ref_managers=None):
        """
        Инициализация экспортёра

        Args:
            iface: Интерфейс QGIS
            ref_managers: Reference managers (не используется)
        """
        self.iface = iface

    def export_coordinates(
        self,
        template: DocumentTemplate,
        output_folder: Optional[str] = None,
        create_wgs84: bool = False
    ) -> Tuple[bool, str]:
        """
        Экспорт перечня координат ГПМТ

        Args:
            template: Шаблон документа (gpmt_coordinates)
            output_folder: Папка для сохранения
            create_wgs84: Создать версию в WGS-84

        Returns:
            Tuple[bool, str]: (успешность, путь к файлу)
        """
        try:
            import xlsxwriter  # noqa: F401
        except ImportError:
            log_error("Fsm_5_3_7: Библиотека xlsxwriter не установлена")
            return False, ""

        layer = self._find_gpmt_layer(template)
        if layer is None:
            log_error("Fsm_5_3_7: Слой ГПМТ не найден")
            return False, ""

        if not output_folder:
            output_folder = self._get_output_folder()
            if not output_folder:
                return False, ""

        ExportUtils.ensure_folder_exists(output_folder)

        metadata = ExportUtils.get_project_metadata()

        # Экспорт в основной СК
        filepath = os.path.join(output_folder, f"{template.filename_template}.xlsx")
        success = self._export_coordinates_to_excel(layer, filepath, template, metadata, False)

        # Экспорт в WGS-84 если нужно
        if success and create_wgs84 and template.supports_wgs84:
            filepath_wgs = os.path.join(output_folder, f"{template.filename_template}_WGS84.xlsx")
            self._export_coordinates_to_excel(layer, filepath_wgs, template, metadata, True)

        return success, filepath

    def export_characteristics(
        self,
        template: DocumentTemplate,
        output_folder: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Экспорт ведомости характеристик ГПМТ

        Args:
            template: Шаблон документа (gpmt_characteristics)
            output_folder: Папка для сохранения

        Returns:
            Tuple[bool, str]: (успешность, путь к файлу)
        """
        try:
            import xlsxwriter
        except ImportError:
            log_error("Fsm_5_3_7: Библиотека xlsxwriter не установлена")
            return False, ""

        layer = self._find_gpmt_layer(template)
        if layer is None:
            log_error("Fsm_5_3_7: Слой ГПМТ не найден")
            return False, ""

        if not output_folder:
            output_folder = self._get_output_folder()
            if not output_folder:
                return False, ""

        ExportUtils.ensure_folder_exists(output_folder)

        filepath = os.path.join(output_folder, f"{template.filename_template}.xlsx")

        try:
            workbook = xlsxwriter.Workbook(filepath)
            worksheet = workbook.add_worksheet('Характеристики')
            fmt = ExcelFormatManager(workbook)

            # Заголовки
            headers = ['№ п/п', 'Наименование', 'Площадь, кв.м', 'Периметр, м', 'Кол-во точек']
            widths = [8, 40, 15, 15, 12]

            header_format = fmt.get_header_format()
            data_format = fmt.get_data_format()
            num_format = fmt.get_number_format(decimals=2)

            for col, (header, width) in enumerate(zip(headers, widths)):
                worksheet.set_column(col, col, width)
                worksheet.write(0, col, header, header_format)

            # Данные
            row = 1
            total_area = 0.0
            total_perimeter = 0.0

            for feature in layer.getFeatures():
                if not feature.hasGeometry():
                    continue

                geom = feature.geometry()
                if geom.isEmpty():
                    continue

                area = geom.area()
                perimeter = geom.length()
                point_count = self._count_points(geom)

                name_field_idx = layer.fields().indexOf('Наименование')
                if name_field_idx >= 0:
                    name = feature.attribute(name_field_idx)
                else:
                    name = None

                worksheet.write(row, 0, row, data_format)
                worksheet.write(row, 1, str(name) if name else f"Контур {row}", data_format)
                worksheet.write(row, 2, area, num_format)
                worksheet.write(row, 3, perimeter, num_format)
                worksheet.write(row, 4, point_count, data_format)

                total_area += area
                total_perimeter += perimeter
                row += 1

            # Итого
            if row > 1:
                total_format = workbook.add_format({
                    'font_name': ExcelFormatManager.FONTS['default'],
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
            log_info(f"Fsm_5_3_7: Характеристики ГПМТ сохранены: {filepath}")
            return True, filepath

        except Exception as e:
            log_error(f"Fsm_5_3_7: Ошибка создания Excel: {str(e)}")
            return False, ""

    def _find_gpmt_layer(self, template: DocumentTemplate) -> Optional[QgsVectorLayer]:
        """Найти слой ГПМТ по паттернам шаблона"""
        for pattern in template.source_layers:
            layers = QgsProject.instance().mapLayersByName(pattern)
            if layers and isinstance(layers[0], QgsVectorLayer):
                if layers[0].featureCount() > 0:
                    return layers[0]
                log_warning(f"Fsm_5_3_7: Слой {pattern} пуст")

        return None

    def _get_output_folder(self) -> Optional[str]:
        """Получить папку для сохранения"""
        try:
            structure_manager = registry.get('M_19')

            if not structure_manager.is_active():
                project_path = QgsProject.instance().homePath()
                if project_path:
                    structure_manager.project_root = project_path

            if structure_manager.is_active():
                return structure_manager.get_folder(FolderType.DOCUMENTS)

            return None
        except Exception:
            return None

    def _export_coordinates_to_excel(
        self,
        layer: QgsVectorLayer,
        filepath: str,
        template: DocumentTemplate,
        metadata: Dict[str, Any],
        is_wgs84: bool
    ) -> bool:
        """Экспорт координат в Excel файл"""
        import xlsxwriter

        precision = PRECISION_DECIMALS_WGS84 if is_wgs84 else PRECISION_DECIMALS
        headers = COORD_HEADERS_WGS84 if is_wgs84 else COORD_HEADERS_LOCAL

        transform = None
        if is_wgs84:
            wgs84_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            if layer.crs() != wgs84_crs:
                transform = QgsCoordinateTransform(
                    layer.crs(), wgs84_crs, QgsProject.instance()
                )

        try:
            workbook = xlsxwriter.Workbook(filepath)
            worksheet = workbook.add_worksheet('Координаты')
            fmt = ExcelFormatManager(workbook)

            # Настройка колонок
            worksheet.set_column(0, 0, 5)
            worksheet.set_column(1, 1, 12)
            worksheet.set_column(2, 2, 18)
            worksheet.set_column(3, 3, 18)

            # Заголовок из шаблона
            layer_info = {'layer_name': layer.name()}
            title_text = ExportUtils.format_template_text(
                template.title_template, metadata, layer_info
            )
            worksheet.merge_range('A1:D1', title_text, fmt.get_title_format(font_size=14))  # type: ignore[call-arg]
            worksheet.set_row(0, 45)

            # Система координат
            if is_wgs84:
                crs_text = "Система координат: WGS-84"
            else:
                crs_name = ExportUtils.format_template_text("{crs_name}", metadata)
                crs_text = f"Система координат: {crs_name}"
            worksheet.merge_range('C3:D3', crs_text, fmt.get_crs_format())  # type: ignore[call-arg]

            # Заголовки колонок
            row = 4
            header_format = fmt.get_header_format(bg_color=None)
            worksheet.write(row, 1, headers['point_num'], header_format)
            worksheet.write(row, 2, headers['x'], header_format)
            worksheet.write(row, 3, headers['y'], header_format)

            row += 1

            # Форматы данных
            data_format = fmt.get_data_format()
            coord_format = fmt.get_coordinate_format(is_wgs84)

            # Собираем координаты
            point_number = 1
            for feature in layer.getFeatures():
                if not feature.hasGeometry():
                    continue

                geometry = feature.geometry()
                if transform:
                    geometry.transform(transform)

                if geometry.type() == Qgis.GeometryType.Polygon:
                    polygons = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]

                    for polygon in polygons:
                        if not polygon:
                            continue

                        exterior = polygon[0]
                        points = exterior[:-1] if len(exterior) > 1 and exterior[0] == exterior[-1] else exterior

                        for point in points:
                            x = CPM.round_coordinate(point.x(), precision)
                            y = CPM.round_coordinate(point.y(), precision)

                            worksheet.write(row, 1, point_number, data_format)
                            # Геодезический порядок: X=север, Y=восток
                            worksheet.write(row, 2, y, coord_format)
                            worksheet.write(row, 3, x, coord_format)

                            row += 1
                            point_number += 1

                        # Замыкающая точка
                        if points:
                            first = points[0]
                            x = CPM.round_coordinate(first.x(), precision)
                            y = CPM.round_coordinate(first.y(), precision)

                            worksheet.write(row, 1, 1, data_format)
                            worksheet.write(row, 2, y, coord_format)
                            worksheet.write(row, 3, x, coord_format)
                            row += 1

            workbook.close()
            log_info(f"Fsm_5_3_7: Координаты ГПМТ сохранены: {filepath}")
            return True

        except Exception as e:
            log_error(f"Fsm_5_3_7: Ошибка экспорта координат: {str(e)}")
            return False

    def _count_points(self, geometry: Any) -> int:
        """Подсчитать количество точек в геометрии"""
        if geometry.type() != Qgis.GeometryType.Polygon:
            return 0

        count = 0
        polygons = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]

        for polygon in polygons:
            for ring in polygon:
                count += len(ring) - 1 if len(ring) > 1 and ring[0] == ring[-1] else len(ring)

        return count

    # === API для интеграции с DocumentFactory ===

    def export_layer(
        self,
        layer: QgsVectorLayer,
        template: DocumentTemplate,
        output_folder: str,
        **kwargs: Any
    ) -> bool:
        """
        Метод для совместимости с BaseExporter интерфейсом

        Args:
            layer: Слой ГПМТ (может быть проигнорирован)
            template: Шаблон документа
            output_folder: Папка для сохранения
            **kwargs: create_wgs84

        Returns:
            bool: Успешность экспорта
        """
        create_wgs84 = kwargs.get('create_wgs84', False)

        if template.doc_type == 'gpmt_characteristics':
            success, _ = self.export_characteristics(template, output_folder)
        else:
            success, _ = self.export_coordinates(template, output_folder, create_wgs84)

        return success
