# -*- coding: utf-8 -*-
"""
Fsm_5_3_1 - Экспорт перечней координат в Excel

Экспортирует координаты слоёв в Excel файл в формате приложений
с уникальной нумерацией точек и поддержкой WGS-84.

Шаблоны: Fsm_5_3_8_template_registry.py (DocumentTemplate)
Форматы: Fsm_5_3_4_format_manager.py (ExcelFormatManager)
"""

import os
import re
from typing import Dict, Any, List, Optional

from qgis.core import (
    Qgis, QgsProject, QgsFeature,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsVectorLayer, QgsWkbTypes
)

from Daman_QGIS.managers import CoordinatePrecisionManager as CPM
from Daman_QGIS.constants import PRECISION_DECIMALS, PRECISION_DECIMALS_WGS84
from Daman_QGIS.utils import log_info, log_warning, log_error, log_debug

from .Fsm_5_3_4_format_manager import ExcelFormatManager
from .Fsm_5_3_5_export_utils import ExportUtils
from .Fsm_5_3_8_template_registry import (
    DocumentTemplate, POINT_NUMBER_FIELDS, POINTS_LAYER_EXCLUSIONS,
    COORD_HEADERS_LOCAL, COORD_HEADERS_WGS84
)


class Fsm_5_3_1_CoordinateList:
    """Экспортёр перечней координат в Excel"""

    def __init__(self, iface, ref_managers=None):
        """
        Инициализация

        Args:
            iface: Интерфейс QGIS
            ref_managers: Reference managers (не используется, сохранён для совместимости)
        """
        self.iface = iface

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
        for exclusion in POINTS_LAYER_EXCLUSIONS:
            if exclusion in layer_name:
                log_debug(f"Fsm_5_3_1: Слой {layer_name} в исключениях для Т_* слоёв")
                return None

        # Формируем имя слоя точек
        # Слои нарезки: Le_2_1_X_Y_Name -> Le_2_5_X_Y_Т_Name
        # Слои этапности: Le_2_7_X_Y_Name -> Le_2_8_X_Y_Т_Name
        points_layer_name = None

        # Паттерн для слоёв нарезки Le_2_1_X_Y_Name или Le_2_2_X_Y_Name
        match_cutting = re.match(r'^(Le_2_)([12])(_\d+_\d+_)(.+)$', layer_name)
        if match_cutting:
            group_map = {'1': '5', '2': '6'}
            new_group = group_map.get(match_cutting.group(2), match_cutting.group(2))
            points_layer_name = f"{match_cutting.group(1)}{new_group}{match_cutting.group(3)}Т_{match_cutting.group(4)}"
        # Паттерн для слоёв этапности Le_2_7_X_Y_Name
        elif layer_name.startswith('Le_2_7_'):
            match_stage = re.match(r'^(Le_2_7_)(\d+_\d+_)(.+)$', layer_name)
            if match_stage:
                points_layer_name = f"Le_2_8_{match_stage.group(2)}Т_{match_stage.group(3)}"
        else:
            # Для других слоёв
            if layer_name.startswith('L_'):
                points_layer_name = 'Т_' + layer_name[2:]
            elif layer_name.startswith('Le_'):
                points_layer_name = 'Т_' + layer_name[3:]
            else:
                points_layer_name = 'Т_' + layer_name

        if not points_layer_name:
            log_debug(f"Fsm_5_3_1: Не удалось сформировать имя слоя точек для {layer_name}")
            return None

        # Ищем слой в проекте
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.name() == points_layer_name:
                if isinstance(lyr, QgsVectorLayer) and lyr.geometryType() == Qgis.GeometryType.Point:
                    log_info(f"Fsm_5_3_1: Найден слой точек: {points_layer_name}")
                    return lyr

        log_debug(f"Fsm_5_3_1: Слой точек {points_layer_name} не найден")
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
        points_index: Dict[tuple, int] = {}

        num_field = None
        for field_name in POINT_NUMBER_FIELDS:
            if points_layer.fields().indexOf(field_name) >= 0:
                num_field = field_name
                break

        if not num_field:
            log_warning("Fsm_5_3_1: В слое точек не найдено поле номера")
            return points_index

        for feature in points_layer.getFeatures():
            if not feature.hasGeometry():
                continue

            point = feature.geometry().asPoint()
            key = CPM.round_point_tuple(point, precision)
            point_num = feature[num_field]

            if point_num is not None:
                points_index[key] = point_num

        log_info(f"Fsm_5_3_1: Загружено {len(points_index)} точек из слоя Т_*")
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
        points_index: Dict[tuple, int] = {}

        num_field = None
        for field_name in POINT_NUMBER_FIELDS:
            if points_layer.fields().indexOf(field_name) >= 0:
                num_field = field_name
                break

        if not num_field:
            log_warning("Fsm_5_3_1: В слое точек не найдено поле номера")
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

        log_info(f"Fsm_5_3_1: Загружено {len(points_index)} точек из слоя Т_* (WGS84)")
        return points_index

    def export_layer(
        self,
        layer: QgsVectorLayer,
        template: DocumentTemplate,
        output_folder: str,
        create_wgs84: bool = False,
        appendix_num: str = 'X',
        extra_context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Экспорт слоя в Excel (перечень координат)

        Args:
            layer: Слой для экспорта
            template: Шаблон документа из TemplateRegistry
            output_folder: Папка для сохранения
            create_wgs84: Создавать версию WGS-84
            appendix_num: Номер приложения
            extra_context: Дополнительный контекст от региональных модификаторов

        Returns:
            bool: Успешность экспорта
        """
        try:
            import xlsxwriter  # noqa: F401
        except ImportError:
            log_error("Fsm_5_3_1: Библиотека xlsxwriter не установлена")
            return False

        extra_context = extra_context or {}

        # Merged export (объединённый перечень SPB) — layer is None
        if extra_context.get('merged_export'):
            return self._export_to_excel_spb_merged(
                template, output_folder, False, extra_context
            )

        success = self._export_to_excel(
            layer, template, output_folder, False, appendix_num, extra_context
        )

        if success and create_wgs84 and template.supports_wgs84:
            self._export_to_excel(
                layer, template, output_folder, True, appendix_num, extra_context
            )

        return success

    def _export_to_excel(
        self,
        layer: QgsVectorLayer,
        template: DocumentTemplate,
        output_folder: str,
        is_wgs84: bool = False,
        appendix_num: str = 'X',
        extra_context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Экспорт одного слоя в Excel

        Args:
            layer: Слой для экспорта
            template: Шаблон документа
            output_folder: Папка для сохранения
            is_wgs84: Экспортировать в WGS-84
            appendix_num: Номер приложения
            extra_context: Дополнительный контекст от региональных модификаторов

        Returns:
            bool: Успешность экспорта
        """
        import xlsxwriter

        extra_context = extra_context or {}

        # SPB формат — отдельный метод
        if extra_context.get('spb_format'):
            return self._export_to_excel_spb(
                layer, template, output_folder, is_wgs84,
                appendix_num, extra_context
            )

        metadata = ExportUtils.get_project_metadata()

        # Формируем имя файла из шаблона
        layer_info = {'layer_name': layer.name(), 'appendix': appendix_num}
        layer_info.update(extra_context)

        if template.filename_template:
            filename_base = ExportUtils.format_template_text(
                template.filename_template, metadata, layer_info
            )
        else:
            filename_base = f"Приложение_{appendix_num}_координаты"

        # Суффикс от региональных модификаторов (например, ЗУ_1)
        feature_name = extra_context.get('feature_name')
        if feature_name:
            filename_base += f'_{feature_name}'

        if is_wgs84:
            filename_base += '_WGS84'

        filename = f"{ExportUtils.sanitize_filename(filename_base)}.xlsx"
        filepath = os.path.join(output_folder, filename)

        workbook = xlsxwriter.Workbook(filepath)
        try:
            worksheet = workbook.add_worksheet('Координаты')
            fmt = ExcelFormatManager(workbook)

            # Настройка ширины колонок
            fmt.set_smart_column_widths(worksheet, ['', '№ Точки', 'X', 'Y', ''])

            # Строка 1: Номер приложения (колонка E)
            appendix_text = f"Приложение {appendix_num}"
            worksheet.write('E1', appendix_text, fmt.get_appendix_format())  # type: ignore[arg-type]

            # Строка 2: Заголовок (объединение A2:E2)
            title_text = ExportUtils.format_template_text(
                template.title_template, metadata, layer_info
            )
            worksheet.merge_range('A2:E2', title_text, fmt.get_title_format())  # type: ignore[call-arg]
            # Высота строки (merged cells не поддерживают auto-fit)
            title_height = ExcelFormatManager.calc_merged_row_height(
                title_text, col_widths=[15, 15, 15, 15, 15],
                font_size=16, bold=True
            )
            worksheet.set_row(1, title_height)  # row index 1 = A2

            # Строка 4: Система координат (объединение D4:E4)
            if is_wgs84:
                crs_text = "Система координат: WGS-84"
            else:
                crs_name = ExportUtils.format_template_text("{crs_name}", metadata)
                crs_text = f"Система координат: {crs_name}"
            worksheet.merge_range('D4:E4', crs_text, fmt.get_crs_format())  # type: ignore[call-arg]

            # Заголовки колонок координат
            headers = COORD_HEADERS_WGS84 if is_wgs84 else COORD_HEADERS_LOCAL

            # Получаем координаты и контуры
            contours_data = self._collect_contours_with_coordinates(layer, is_wgs84)

            # Начинаем с 6 строки (индекс 5)
            current_row = 5
            contour_number = 0
            data_format = fmt.get_data_format(with_border=True)
            header_col_format = fmt.get_header_format(
                with_border=True, bg_color='#FFFFFF'
            )
            coord_format = fmt.get_coordinate_format(is_wgs84, with_border=True)
            subtitle_border_format = fmt.get_data_format(
                align='center', with_border=True
            )

            for contour_info in contours_data:
                contour_type = contour_info['type']
                coordinates = contour_info['coordinates']
                area = contour_info.get('area', 0)
                ring_index = contour_info.get('ring_index', 0)

                if contour_type == 'exterior':
                    contour_number += 1
                    if template.contour_format:
                        contour_title = ExportUtils.format_template_text(
                            template.contour_format, metadata,
                            {'area': area, 'layer_name': layer.name(), '№': contour_number}
                        )
                        worksheet.merge_range(
                            current_row, 1, current_row, 3,
                            contour_title, subtitle_border_format
                        )
                    current_row += 1

                    # Заголовки колонок
                    worksheet.write(current_row, 1, headers['point_num'], header_col_format)
                    worksheet.write(current_row, 2, headers['x'], header_col_format)
                    worksheet.write(current_row, 3, headers['y'], header_col_format)
                    current_row += 1
                else:
                    hole_title = f"Внутренний контур {ring_index}"
                    worksheet.merge_range(
                        current_row, 1, current_row, 3,
                        hole_title, subtitle_border_format
                    )
                    current_row += 1

                    worksheet.write(current_row, 1, headers['point_num'], header_col_format)
                    worksheet.write(current_row, 2, headers['x'], header_col_format)
                    worksheet.write(current_row, 3, headers['y'], header_col_format)
                    current_row += 1

                # Выводим координаты точек
                for coord in coordinates:
                    worksheet.write(current_row, 1, coord[0], data_format)
                    # Геодезический порядок: X=север, Y=восток
                    worksheet.write(current_row, 2, coord[2], coord_format)
                    worksheet.write(current_row, 3, coord[1], coord_format)
                    current_row += 1

            # Настройка области печати
            worksheet.print_area(0, 0, current_row - 1, 4)
        finally:
            workbook.close()

        return True

    def _export_to_excel_spb(
        self,
        layer: QgsVectorLayer,
        template: DocumentTemplate,
        output_folder: str,
        is_wgs84: bool,
        appendix_num: str,
        extra_context: Dict[str, Any]
    ) -> bool:
        """
        Экспорт в Excel формата СПб (3 колонки, без приложения/CRS).

        Layout:
        - Row 0: Заголовок title_override (merge A:C)
        - Row 1: "Номер точки" | "Х (м)" | "Y (м)"
        - Row 2+: Данные (номер сквозной в контуре, X, Y)
        - Разделители "Внутренний контур N" между контурами
        - Последняя строка: "S=... кв. м"

        Args:
            layer: Слой для экспорта
            template: Шаблон документа
            output_folder: Папка для сохранения
            is_wgs84: Экспортировать в WGS-84
            appendix_num: Номер приложения
            extra_context: Контекст от Region78FormatModifier

        Returns:
            bool: Успешность экспорта
        """
        import xlsxwriter

        metadata = ExportUtils.get_project_metadata()

        # Формируем имя файла
        filename_override = extra_context.get('filename_override')
        if filename_override:
            filename_base = filename_override
        else:
            layer_info = {'layer_name': layer.name(), 'appendix': appendix_num}
            layer_info.update(extra_context)

            if template.filename_template:
                filename_base = ExportUtils.format_template_text(
                    template.filename_template, metadata, layer_info
                )
            else:
                filename_base = f"Координаты"

            feature_name = extra_context.get('feature_name')
            if feature_name:
                filename_base += f'_{feature_name}'

        if is_wgs84:
            filename_base += '_WGS84'

        filename = f"{ExportUtils.sanitize_filename(filename_base)}.xlsx"

        # Подпапка из модификатора (например, 'ЗУ' или 'ПС')
        subfolder = extra_context.get('subfolder')
        if subfolder:
            output_folder = os.path.join(output_folder, subfolder)
            os.makedirs(output_folder, exist_ok=True)

        filepath = os.path.join(output_folder, filename)

        # Собираем контуры БЕЗ замыкания
        close_contours = extra_context.get('close_contours', True)
        contours_data = self._collect_contours_with_coordinates(
            layer, is_wgs84, close_contours
        )

        # Площадь из геометрии (в локальных координатах)
        total_area = 0.0
        for feature in layer.getFeatures():
            if feature.hasGeometry():
                total_area += feature.geometry().area()

        workbook = xlsxwriter.Workbook(filepath)
        try:
            worksheet = workbook.add_worksheet('Координаты')
            fmt = ExcelFormatManager(workbook)

            # Ширина 3 колонок
            worksheet.set_column(0, 0, 15)  # Номер точки
            worksheet.set_column(1, 1, 15)  # X
            worksheet.set_column(2, 2, 15)  # Y

            # Форматы
            title_format = fmt.get_title_format(font_size=11)
            header_col_format = fmt.get_header_format(
                with_border=True, bg_color='#FFFFFF'
            )
            data_format = fmt.get_data_format(
                align='center', with_border=True
            )
            coord_format = fmt.get_coordinate_format(is_wgs84, with_border=True)
            separator_format = fmt.get_data_format(
                align='center', with_border=True
            )

            current_row = 0

            # Row 0: Заголовок
            title_text = extra_context.get('title_override', '')
            if not title_text:
                title_text = ExportUtils.format_template_text(
                    template.title_template, metadata, layer_info
                )
            worksheet.merge_range(
                current_row, 0, current_row, 2,
                title_text, title_format
            )
            # Высота строки (merged cells не поддерживают auto-fit)
            title_height = ExcelFormatManager.calc_merged_row_height(
                title_text, col_widths=[15, 15, 15],
                font_size=11, bold=True
            )
            worksheet.set_row(current_row, title_height)
            current_row += 1

            # Row 1: Заголовки колонок
            if is_wgs84:
                col_headers = ['Номер точки', 'Широта', 'Долгота']
            else:
                col_headers = ['Номер точки', 'Х (м)', 'Y (м)']

            for col_idx, header_text in enumerate(col_headers):
                worksheet.write(current_row, col_idx, header_text, header_col_format)
            current_row += 1

            # Данные контуров
            inner_contour_num = 0

            for contour_info in contours_data:
                contour_type = contour_info['type']
                coordinates = contour_info['coordinates']

                if contour_type == 'hole':
                    # Разделитель внутреннего контура
                    inner_contour_num += 1
                    label = f"Внутренний контур {inner_contour_num}"
                    worksheet.merge_range(
                        current_row, 0, current_row, 2,
                        label, separator_format
                    )
                    current_row += 1

                # Координаты с последовательной нумерацией внутри контура
                for idx, coord in enumerate(coordinates, 1):
                    worksheet.write(current_row, 0, idx, data_format)
                    # Геодезический порядок: X=север (coord[2]), Y=восток (coord[1])
                    worksheet.write(current_row, 1, coord[2], coord_format)
                    worksheet.write(current_row, 2, coord[1], coord_format)
                    current_row += 1

            # Последняя строка: площадь (left-aligned, без merge)
            if extra_context.get('show_area') and total_area > 0:
                area_int = round(total_area)
                area_text = f"S={area_int} кв. м"
                area_format = fmt.get_data_format(
                    align='left', with_border=False
                )
                worksheet.write(current_row, 0, area_text, area_format)
                current_row += 1

            # Область печати
            worksheet.print_area(0, 0, current_row - 1, 2)
        finally:
            workbook.close()

        return True

    def _export_to_excel_spb_merged(
        self,
        template: DocumentTemplate,
        output_folder: str,
        is_wgs84: bool,
        extra_context: Dict[str, Any]
    ) -> bool:
        """
        Экспорт объединённого перечня координат формата СПб.

        Все features из всех merged_layers в одном файле.
        Между features — разделитель с типом и ID объекта.
        Опционально — площадь S= после каждого feature.

        Layout:
        - Row 0: Заголовок title_override (merge A:C)
        - Row 1: "Номер точки" | "Х (м)" | "Y (м)"
        - Row 2: 1 | 2 | 3 (номера колонок)
        - Per feature:
          - Separator: "Образуемый земельный участок {ID}" / "Контур ПС {ID}"
          - Координаты (нумерация с 1 для каждого контура)
          - "Внутренний контур N" (если есть holes)
          - S= ... кв. м (если show_area_per_feature)

        Args:
            template: Шаблон документа (для fallback)
            output_folder: Папка для сохранения
            is_wgs84: Экспортировать в WGS-84
            extra_context: Контекст от Region78FormatModifier

        Returns:
            bool: Успешность экспорта
        """
        import xlsxwriter

        merged_layers = extra_context.get('merged_layers', [])
        if not merged_layers:
            log_warning("Fsm_5_3_1: merged_layers пуст, пропуск merged export")
            return False

        show_area = extra_context.get('show_area_per_feature', True)
        is_ps = extra_context.get('subfolder', '') == 'Публичные сервитуты'
        close_contours = extra_context.get('close_contours', False)

        # Имя файла
        filename_override = extra_context.get(
            'filename_override', 'Перечень_координат'
        )
        if is_wgs84:
            filename_override += '_WGS84'
        filename = f"{ExportUtils.sanitize_filename(filename_override)}.xlsx"

        # Подпапка
        subfolder = extra_context.get('subfolder')
        if subfolder:
            output_folder = os.path.join(output_folder, subfolder)
            os.makedirs(output_folder, exist_ok=True)

        filepath = os.path.join(output_folder, filename)

        workbook = xlsxwriter.Workbook(filepath)
        try:
            worksheet = workbook.add_worksheet('Координаты')
            fmt = ExcelFormatManager(workbook)

            # Ширина 3 колонок
            worksheet.set_column(0, 0, 15)  # Номер точки
            worksheet.set_column(1, 1, 15)  # X
            worksheet.set_column(2, 2, 15)  # Y

            # Форматы
            title_format = fmt.get_title_format(font_size=11)
            header_col_format = fmt.get_header_format(
                with_border=True, bg_color='#FFFFFF'
            )
            data_format = fmt.get_data_format(
                align='center', with_border=True
            )
            coord_format = fmt.get_coordinate_format(
                is_wgs84, with_border=True
            )
            separator_format = fmt.get_data_format(
                align='center', with_border=True
            )

            current_row = 0

            # Row 0: Заголовок
            title_text = extra_context.get('title_override', '')
            worksheet.merge_range(
                current_row, 0, current_row, 2,
                title_text, title_format
            )
            title_height = ExcelFormatManager.calc_merged_row_height(
                title_text, col_widths=[15, 15, 15],
                font_size=11, bold=True
            )
            worksheet.set_row(current_row, title_height)
            current_row += 1

            # Row 1: Заголовки колонок
            if is_wgs84:
                col_headers = ['Номер точки', 'Широта', 'Долгота']
            else:
                col_headers = ['Номер точки', 'Х (м)', 'Y (м)']

            for col_idx, header_text in enumerate(col_headers):
                worksheet.write(
                    current_row, col_idx, header_text, header_col_format
                )
            current_row += 1

            # Row 2: Номера колонок (1 | 2 | 3)
            for col_idx in range(3):
                worksheet.write(
                    current_row, col_idx, col_idx + 1, data_format
                )
            current_row += 1

            # Перебираем все features из всех слоёв
            total_features = 0
            for layer in merged_layers:
                for feature in layer.getFeatures():
                    feature_id = feature.attribute('ID')
                    if not feature_id:
                        log_warning(
                            f"Fsm_5_3_1: Пустое поле ID в merged layer "
                            f"'{layer.name()}', пропуск feature"
                        )
                        continue

                    # Разделитель: тип объекта + ID
                    if is_ps:
                        separator_text = (
                            f"Контур публичного сервитута {feature_id}"
                        )
                    else:
                        separator_text = (
                            f"Образуемый земельный участок {feature_id}"
                        )

                    worksheet.merge_range(
                        current_row, 0, current_row, 2,
                        separator_text, separator_format
                    )
                    current_row += 1

                    # Temp memory layer с одним feature
                    temp_layer = self._create_temp_single_feature_layer(
                        layer, feature
                    )
                    if temp_layer is None:
                        log_warning(
                            f"Fsm_5_3_1: Не удалось создать temp layer "
                            f"для feature {feature_id}"
                        )
                        continue

                    # Собираем контуры
                    contours_data = self._collect_contours_with_coordinates(
                        temp_layer, is_wgs84, close_contours
                    )

                    inner_contour_num = 0

                    for contour_info in contours_data:
                        contour_type = contour_info['type']
                        coordinates = contour_info['coordinates']

                        if contour_type == 'hole':
                            # Разделитель внутреннего контура
                            inner_contour_num += 1
                            label = f"Внутренний контур {inner_contour_num}"
                            worksheet.merge_range(
                                current_row, 0, current_row, 2,
                                label, separator_format
                            )
                            current_row += 1

                        # Координаты с нумерацией внутри контура
                        for idx, coord in enumerate(coordinates, 1):
                            worksheet.write(
                                current_row, 0, idx, data_format
                            )
                            # Геодезический порядок: X=север, Y=восток
                            worksheet.write(
                                current_row, 1, coord[2], coord_format
                            )
                            worksheet.write(
                                current_row, 2, coord[1], coord_format
                            )
                            current_row += 1

                    # Площадь после каждого feature (если включена)
                    if show_area and feature.hasGeometry():
                        area_int = round(feature.geometry().area())
                        if area_int > 0:
                            area_text = f"S={area_int} кв. м"
                            area_format = fmt.get_data_format(
                                align='left', with_border=False
                            )
                            worksheet.write(
                                current_row, 0, area_text, area_format
                            )
                            current_row += 1

                    total_features += 1

            # Область печати
            worksheet.print_area(0, 0, current_row - 1, 2)
        finally:
            workbook.close()

        log_info(
            f"Fsm_5_3_1: Merged export ({total_features} features) -> "
            f"{os.path.basename(filepath)}"
        )
        return True

    def _create_temp_single_feature_layer(
        self,
        source_layer: QgsVectorLayer,
        feature: QgsFeature
    ) -> Optional[QgsVectorLayer]:
        """
        Создать temp memory layer с одной feature.

        Используется для merged export — передаём в
        _collect_contours_with_coordinates() для получения координат.

        Args:
            source_layer: Исходный слой (для CRS и полей)
            feature: Feature для копирования

        Returns:
            Memory layer с одной feature или None при ошибке
        """
        try:
            geom_type_str = QgsWkbTypes.displayString(source_layer.wkbType())
            crs_id = source_layer.crs().authid()

            uri = f"{geom_type_str}?crs={crs_id}"
            mem_layer = QgsVectorLayer(uri, "temp_merged_feature", "memory")

            if not mem_layer.isValid():
                log_error(
                    "Fsm_5_3_1: Не удалось создать temp memory layer"
                )
                return None

            provider = mem_layer.dataProvider()
            if provider is None:
                return None

            # Копируем структуру полей
            provider.addAttributes(source_layer.fields().toList())
            mem_layer.updateFields()

            # Добавляем feature
            success = provider.addFeature(feature)
            if not success:
                log_error(
                    "Fsm_5_3_1: Не удалось добавить feature "
                    "в temp memory layer"
                )
                return None

            return mem_layer

        except Exception as e:
            log_error(
                f"Fsm_5_3_1: Ошибка создания temp memory layer: {e}"
            )
            return None

    def _collect_contours_with_coordinates(
        self,
        layer: QgsVectorLayer,
        is_wgs84: bool = False,
        close_contours: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Сбор контуров с координатами и уникальной нумерацией точек

        Приоритет получения номеров точек:
        1. Слой точек Т_* (если существует и не в исключениях)
        2. Автоматическая нумерация

        Args:
            layer: Слой QGIS
            is_wgs84: Нужна ли трансформация в WGS-84
            close_contours: Замыкать контуры первой точкой (False для СПб)

        Returns:
            Список контуров с координатами
        """
        contours: List[Dict[str, Any]] = []
        precision = PRECISION_DECIMALS_WGS84 if is_wgs84 else PRECISION_DECIMALS

        # Создаём трансформацию если нужна
        transform = None
        if is_wgs84:
            wgs84_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            if layer.crs() != wgs84_crs:
                transform = QgsCoordinateTransform(
                    layer.crs(), wgs84_crs, QgsProject.instance()
                )

        layer_geom_type = layer.geometryType()

        # Точечный слой - специальная обработка
        if layer_geom_type == Qgis.GeometryType.Point:
            return self._collect_points_from_point_layer(
                layer, transform, precision, close_contours
            )

        # Для полигональных слоёв пытаемся найти слой точек Т_*
        points_layer = self._find_points_layer(layer.name())
        points_index: Dict[tuple, int] = {}

        if points_layer:
            if is_wgs84 and transform:
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
        unique_points: Dict[tuple, int] = {}
        point_number = 1
        all_raw_contours: List[Dict[str, Any]] = []

        for feature in layer.getFeatures():
            if not feature.hasGeometry():
                continue

            geometry = feature.geometry()

            if transform:
                geometry.transform(transform)

            area_sqm = geometry.area()

            if geometry.type() == Qgis.GeometryType.Polygon:
                polygons = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]

                for polygon_idx, polygon in enumerate(polygons):
                    if polygon:
                        exterior_ring = polygon[0]
                        points = exterior_ring[:-1] if len(exterior_ring) > 1 and exterior_ring[0] == exterior_ring[-1] else exterior_ring

                        for point in points:
                            key = CPM.round_point_tuple(point, precision)
                            if key not in unique_points:
                                if use_points_layer and key in points_index:
                                    unique_points[key] = points_index[key]
                                else:
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
                                        unique_points[key] = points_index[key]
                                    else:
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
            raw_points = raw_contour['points']

            for point in raw_points:
                key = CPM.round_point_tuple(point, precision)
                point_num = unique_points[key]

                contour_coords.append([
                    point_num,
                    CPM.round_coordinate(point.x(), precision),
                    CPM.round_coordinate(point.y(), precision)
                ])

            # Замыкаем контур первой точкой (не для SPB формата)
            if close_contours and len(raw_points) > 1:
                first_point = raw_points[0]
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
        precision: int,
        close_contours: bool = True
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
        point_index_field = None

        field_names = [f.name() for f in layer.fields()]

        # Поле номера точки (глобальный номер)
        for name in POINT_NUMBER_FIELDS:
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
            log_warning("Fsm_5_3_1: В точечном слое не найдено поле номера точки")
            return []

        log_info(f"Fsm_5_3_1: Точечный слой '{layer.name()}': "
                f"id_field={id_field}, contour_id_field={contour_id_field}, "
                f"point_index_field={point_index_field}, ring_type_field={ring_type_field}")

        # Группируем точки по контурам и кольцам
        contour_points: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)

        for feature in layer.getFeatures():
            if not feature.hasGeometry():
                continue

            geometry = feature.geometry()
            if transform:
                geometry.transform(transform)

            point = geometry.asPoint()
            point_num = feature[id_field]

            contour_id = 0
            if contour_id_field:
                contour_id = feature[contour_id_field] or 0

            ring_type = 'exterior'
            if ring_type_field:
                rt = feature[ring_type_field]
                if rt and str(rt).lower() == 'hole':
                    ring_type = 'hole'

            ring_index = 0
            if ring_index_field:
                ri = feature[ring_index_field]
                if ri is not None:
                    ring_index = int(ri)

            point_idx = 0
            if point_index_field:
                pi = feature[point_index_field]
                if pi is not None:
                    point_idx = int(pi)

            key = (contour_id, ring_type, ring_index)
            contour_points[key].append({
                'num': point_num,
                'point_idx': point_idx,
                'x': CPM.round_coordinate(point.x(), precision),
                'y': CPM.round_coordinate(point.y(), precision)
            })

        # Формируем результат
        contours: List[Dict[str, Any]] = []

        sorted_keys = sorted(contour_points.keys(), key=lambda k: (k[0], k[2]))

        for key in sorted_keys:
            contour_id, ring_type, ring_index = key
            points = contour_points[key]

            # Сортируем точки по номеру внутри контура
            points.sort(key=lambda p: p['point_idx'])

            coordinates = []
            for pt in points:
                coordinates.append([pt['num'], pt['x'], pt['y']])

            # Добавляем замыкающую точку (не для SPB формата)
            if close_contours and coordinates:
                first_coord = coordinates[0]
                coordinates.append([first_coord[0], first_coord[1], first_coord[2]])

            contours.append({
                'type': ring_type,
                'contour_id': contour_id,
                'ring_index': ring_index,
                'coordinates': coordinates,
                'area': 0
            })

        log_info(f"Fsm_5_3_1: Собрано {len(contours)} контуров из точечного слоя")
        return contours
