# -*- coding: utf-8 -*-
"""
Сабмодуль экспорта в Excel
Экспортирует координаты слоев в Excel файл в формате приложений
"""

import os
import re
from qgis.core import (
    QgsMessageLog, Qgis, QgsWkbTypes, QgsProject,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsVectorLayer
)
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog, QFileDialog, QCheckBox
from qgis.PyQt.QtCore import Qt

from Daman_QGIS.managers import get_reference_managers, CoordinatePrecisionManager as CPM
from Daman_QGIS.constants import PLUGIN_NAME, PRECISION_DECIMALS, PRECISION_DECIMALS_WGS84
from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers.M_19_project_structure_manager import (
    get_project_structure_manager, FolderType
)


class ExcelExportSubmodule:
    """Сабмодуль для экспорта координат в Excel в формате приложений"""
    
    def __init__(self, iface):
        """
        Инициализация сабмодуля

        Args:
            iface: Интерфейс QGIS
        """
        self.iface = iface
        self.ref_managers = get_reference_managers()
        
    def export(self, **params):
        """
        Экспорт в Excel с использованием базы стилей
        
        Args:
            **params: Параметры экспорта:
                - layer: слой для экспорта (если один)
                - layers: список слоев (для пакетного экспорта)
                - show_dialog: показывать ли диалог выбора
                - create_wgs84: создавать ли версию WGS-84 (по умолчанию False)
            
        Returns:
            dict: Результаты экспорта {layer_name: success}
        """
        # Проверяем наличие xlsxwriter
        try:
            import xlsxwriter
        except RuntimeError:
            if params.get('show_dialog', True):
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Ошибка",
                    "Библиотека xlsxwriter не установлена!\n\n"
                    "Для установки используйте инструмент:\n"
                    "5_1 Проверка зависимостей"
                )
            log_error("Fsm_1_5_2: Библиотека xlsxwriter не установлена")
            return {}
            
        # Получаем слои для экспорта
        if params.get('show_dialog', True):
            layers = self._show_dialog()
            if not layers:
                return {}
            create_wgs84 = self.create_wgs84_checkbox.isChecked() if hasattr(self, 'create_wgs84_checkbox') else False
        else:
            # Используем переданные параметры
            if 'layer' in params:
                layers = [params['layer']]
            elif 'layers' in params:
                layers = params['layers']
            else:
                return {}
            create_wgs84 = params.get('create_wgs84', False)
            
        # Папка для сохранения
        project_path = QgsProject.instance().homePath()
        if not project_path:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Ошибка",
                "Сначала сохраните проект QGIS"
            )
            return {}
            
        structure_manager = get_project_structure_manager()
        structure_manager.project_root = project_path
        output_folder = structure_manager.get_folder(FolderType.APPENDICES, create=True)
        
        # Результаты экспорта
        results = {}
        
        # Экспортируем каждый слой
        for layer in layers:
            if not isinstance(layer, QgsVectorLayer):
                results[layer.name()] = False
                continue
                
            # Получаем стиль из базы
            style = self.ref_managers.excel_export_style.get_excel_export_style_for_layer(layer.name())
            if not style:
                log_warning(f"Fsm_1_5_2: Стиль для слоя '{layer.name()}' не найден в базе")
                results[layer.name()] = False
                continue
                
            # Экспортируем в основной СК
            success = self._export_layer(layer, style, output_folder, False)
            results[layer.name()] = success
            
            # Экспортируем в WGS-84 если нужно
            if success and create_wgs84:
                self._export_layer(layer, style, output_folder, True)
                
        # Показываем результаты
        if params.get('show_dialog', True):
            self._show_results(results, output_folder, create_wgs84)
            
        return results
        
    def _show_dialog(self):
        """Показать диалог выбора слоев"""
        from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QListWidget, QListWidgetItem, QDialogButtonBox, QLabel
        
        dialog = QDialog(self.iface.mainWindow())
        dialog.setWindowTitle("Экспорт координат в Excel")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout()
        
        # Информация
        info_label = QLabel("Выберите слои для экспорта в формате приложений:")
        layout.addWidget(info_label)
        
        # Список слоев
        list_widget = QListWidget()
        
        # Добавляем только векторные слои
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                # Проверяем наличие стиля в базе
                style = self.ref_managers.excel_export_style.get_excel_export_style_for_layer(layer.name())
                if style:
                    item = QListWidgetItem(layer.name())
                    item.setData(Qt.UserRole, layer)
                    item.setCheckState(Qt.Checked if style.get('layer') != 'Other' else Qt.Unchecked)
                    list_widget.addItem(item)
                    
        list_widget.setSelectionMode(QListWidget.MultiSelection)
        layout.addWidget(list_widget)
        
        # Чекбокс для WGS-84
        self.create_wgs84_checkbox = QCheckBox("Создать версию в WGS-84")
        self.create_wgs84_checkbox.setChecked(False)  # По умолчанию выключено
        layout.addWidget(self.create_wgs84_checkbox)
        
        # Кнопки
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        dialog.setLayout(layout)
        
        if dialog.exec_():
            # Собираем выбранные слои
            selected_layers = []
            for i in range(list_widget.count()):
                item = list_widget.item(i)
                if item.checkState() == Qt.Checked:
                    layer = item.data(Qt.UserRole)
                    selected_layers.append(layer)
            return selected_layers
        
        return []
    def _export_layer(self, layer, style, output_folder, is_wgs84=False):
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

        # Формируем имя файла (фиксированное значение номера)
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

        # Форматы (Times New Roman для всего)
        # Формат для номера приложения (строка 1, колонка E)
        appendix_format = workbook.add_format({
            'font_name': 'Times New Roman',
            'font_size': 11,
            'italic': True,
            'bold': True,
            'align': 'right',
            'valign': 'vcenter',
            'text_wrap': True
        })

        # Формат для заголовка (строка 2)
        title_format = workbook.add_format({
            'font_name': 'Times New Roman',
            'font_size': 16,
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True
        })

        # Формат для системы координат (строка 4)
        crs_format = workbook.add_format({
            'font_name': 'Times New Roman',
            'font_size': 12,
            'bold': True,
            'align': 'right',
            'valign': 'vcenter'
        })

        # Формат для наименования контура
        contour_title_format = workbook.add_format({
            'font_name': 'Times New Roman',
            'font_size': 12,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True
        })

        # Формат для заголовков и данных колонок
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

        # Строка 3: пустая

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

        # Строка 5: пустая

        # Получаем координаты и контуры
        contours_data = self._collect_contours_with_coordinates(layer, is_wgs84)

        # Начинаем с 6 строки (индекс 5)
        current_row = 5
        contour_number = 0  # Счетчик контуров

        # Обрабатываем каждый контур
        for contour_idx, contour_info in enumerate(contours_data):
            contour_type = contour_info['type']
            coordinates = contour_info['coordinates']
            area = contour_info.get('area', 0)

            # Для внешних контуров выводим наименование
            if contour_type == 'exterior':
                contour_number += 1  # Увеличиваем счетчик контуров
                # Наименование контура (объединяем B:C:D текущей строки)
                contour_title = style.get('contour_title', '')
                if contour_title:
                    # Добавляем номер контура в переменные
                    formatted_title = self.ref_managers.excel_export_style.format_excel_export_text(
                        contour_title,
                        metadata,
                        {'area': area, 'layer_name': layer.name(), '№': contour_number}
                    )
                    worksheet.merge_range(
                        current_row, 1, current_row, 3,  # Колонки B:D
                        formatted_title,
                        contour_title_format
                    )
                current_row += 1

                # Пустая строка после наименования
                current_row += 1

                # Заголовки колонок
                worksheet.write(current_row, 1, '№ Точки', column_format)  # B
                if is_wgs84:
                    worksheet.write(current_row, 2, 'Широта', column_format)  # C
                    worksheet.write(current_row, 3, 'Долгота', column_format)  # D
                else:
                    worksheet.write(current_row, 2, 'X, м', column_format)  # C
                    worksheet.write(current_row, 3, 'Y, м', column_format)  # D
                current_row += 1
            else:
                # Для внутренних контуров - просто пропуск строки
                current_row += 1

                # Заголовки колонок для внутреннего контура
                worksheet.write(current_row, 1, '№ Точки', column_format)  # B
                if is_wgs84:
                    worksheet.write(current_row, 2, 'Широта', column_format)  # C
                    worksheet.write(current_row, 3, 'Долгота', column_format)  # D
                else:
                    worksheet.write(current_row, 2, 'X, м', column_format)  # C
                    worksheet.write(current_row, 3, 'Y, м', column_format)  # D
                current_row += 1

            # Выводим координаты точек
            for coord in coordinates:
                # coord содержит: [номер_точки, x, y]
                worksheet.write(current_row, 1, coord[0], column_format)  # № точки

                if is_wgs84:
                    # Для WGS-84: широта (Y), долгота (X) с 6 знаками
                    worksheet.write(current_row, 2, f"{coord[2]:.6f}", column_format)  # Широта
                    worksheet.write(current_row, 3, f"{coord[1]:.6f}", column_format)  # Долгота
                else:
                    # ВАЖНО: Меняем местами X и Y при выводе (из-за разницы математической и геодезической систем)
                    # В колонку "X, м" пишем Y координату, в колонку "Y, м" пишем X координату
                    worksheet.write(current_row, 2, f"{coord[2]:.2f}", column_format)  # Y в колонку X
                    worksheet.write(current_row, 3, f"{coord[1]:.2f}", column_format)  # X в колонку Y
                current_row += 1

            # Пустая строка после контура
            current_row += 1

        # Настройка области печати
        worksheet.print_area(0, 0, current_row - 1, 4)  # От A1 до E[последняя строка]

        # Закрываем файл
        workbook.close()

        log_info(f"Fsm_1_5_2: Экспорт завершен: {filepath}")
        return True
    def _collect_contours_with_coordinates(self, layer, is_wgs84=False):
        """
        Сбор контуров с координатами и уникальной нумерацией точек

        Args:
            layer: Слой QGIS
            is_wgs84: Нужна ли трансформация в WGS-84

        Returns:
            Список контуров с координатами
        """
        contours = []

        # Создаем трансформацию если нужна
        transform = None
        if is_wgs84:
            wgs84_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            if layer.crs() != wgs84_crs:
                transform = QgsCoordinateTransform(
                    layer.crs(),
                    wgs84_crs,
                    QgsProject.instance()
                )

        # Проверяем, есть ли стиль для слоя (чтобы понять уникальный он или нет)
        style = self.ref_managers.excel_export_style.get_excel_export_style_for_layer(layer.name())
        is_unique_layer = style and style.get('layer') != 'Other'

        # Первый проход: собираем все уникальные точки
        unique_points = {}  # Ключ: (x округленный, y округленный) -> номер
        point_number = 1
        all_raw_contours = []  # Сырые контуры для обработки

        for feature in layer.getFeatures():
            if not feature.hasGeometry():
                continue

            geometry = feature.geometry()

            # Трансформируем геометрию если нужно
            if transform:
                geometry.transform(transform)

            # Получаем площадь
            area_sqm = geometry.area()

            # Получаем номер точки из атрибутов для уникальных слоев
            point_num_field = None
            if is_unique_layer:
                # Ищем поле с номерами точек (обычно 'point_num', 'num', 'number' и т.д.)
                field_names = [field.name() for field in feature.fields()]
                for possible_field in ['point_num', 'num', 'number', 'point_number', 'n']:
                    if possible_field in field_names:
                        point_num_field = possible_field
                        break

            # Обрабатываем геометрию
            if geometry.type() == QgsWkbTypes.PolygonGeometry:
                # МИГРАЦИЯ POLYGON → MULTIPOLYGON: упрощённый паттерн
                polygons = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]

                for polygon_idx, polygon in enumerate(polygons):
                    # Внешний контур
                    if polygon:
                        exterior_ring = polygon[0]
                        # Убираем дублирующую последнюю точку если есть
                        points = exterior_ring[:-1] if len(exterior_ring) > 1 and exterior_ring[0] == exterior_ring[-1] else exterior_ring

                        # Регистрируем уникальные точки
                        for point in points:
                            precision = PRECISION_DECIMALS_WGS84 if is_wgs84 else PRECISION_DECIMALS
                            key = CPM.round_point_tuple(point, precision)
                            if key not in unique_points:
                                # Если есть номер из атрибутов и это уникальный слой
                                if is_unique_layer and point_num_field:
                                    unique_points[key] = feature[point_num_field]
                                else:
                                    unique_points[key] = point_number
                                    point_number += 1

                        all_raw_contours.append({
                            'type': 'exterior',
                            'points': points,
                            'area': area_sqm if polygon_idx == 0 else 0
                        })

                        # Внутренние контуры (дырки)
                        for hole in polygon[1:]:
                            hole_points = hole[:-1] if len(hole) > 1 and hole[0] == hole[-1] else hole

                            for point in hole_points:
                                precision = PRECISION_DECIMALS_WGS84 if is_wgs84 else PRECISION_DECIMALS
                                key = CPM.round_point_tuple(point, precision)
                                if key not in unique_points:
                                    unique_points[key] = point_number
                                    point_number += 1

                            all_raw_contours.append({
                                'type': 'hole',
                                'points': hole_points,
                                'area': 0
                            })

        # Второй проход: формируем финальные контуры с правильными номерами
        for raw_contour in all_raw_contours:
            contour_coords = []
            points = raw_contour['points']

            # Добавляем все точки с их номерами
            for point in points:
                precision = PRECISION_DECIMALS_WGS84 if is_wgs84 else PRECISION_DECIMALS
                key = CPM.round_point_tuple(point, precision)
                point_num = unique_points[key]

                contour_coords.append([
                    point_num,  # Номер точки
                    CPM.round_coordinate(point.x(), precision),
                    CPM.round_coordinate(point.y(), precision)
                ])

            # ВАЖНО: Замыкаем контур первой точкой
            if len(points) > 1:
                first_point = points[0]
                precision = PRECISION_DECIMALS_WGS84 if is_wgs84 else PRECISION_DECIMALS
                key = CPM.round_point_tuple(first_point, precision)
                point_num = unique_points[key]

                # Добавляем первую точку для замыкания
                contour_coords.append([
                    point_num,
                    CPM.round_coordinate(first_point.x(), precision),
                    CPM.round_coordinate(first_point.y(), precision)
                ])

            contours.append({
                'type': raw_contour['type'],
                'coordinates': contour_coords,
                'area': raw_contour['area']
            })

        return contours
    def _get_project_metadata(self):
        """Получить метаданные проекта из GeoPackage"""
        import sqlite3
        from Daman_QGIS.managers.M_19_project_structure_manager import get_project_structure_manager
        project_path = QgsProject.instance().homePath()
        structure_manager = get_project_structure_manager()
        structure_manager.project_root = project_path
        gpkg_path = structure_manager.get_gpkg_path(create=False)

        if not gpkg_path or not os.path.exists(gpkg_path):
            return {}

        conn = sqlite3.connect(gpkg_path)
        cursor = conn.cursor()

        cursor.execute("SELECT key, value FROM project_metadata")
        rows = cursor.fetchall()

        metadata = {}
        for key, value in rows:
            metadata[key] = value

        conn.close()
        return metadata
            
    def _show_results(self, results, output_folder, create_wgs84):
        """Показать результаты экспорта"""
        success_count = sum(1 for success in results.values() if success)
        error_count = len(results) - success_count
        
        message = f"Экспорт завершен!\n\n"
        message += f"Успешно: {success_count} слоев\n"
        if error_count > 0:
            message += f"Ошибок: {error_count} слоев\n"
        message += f"\nФайлы сохранены в:\n{output_folder}"
        
        if create_wgs84:
            message += "\n\nСозданы версии в WGS-84"
        
        QMessageBox.information(
            self.iface.mainWindow(),
            "Экспорт в Excel",
            message
        )
