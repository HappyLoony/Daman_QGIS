# -*- coding: utf-8 -*-
"""
Сабмодуль экспорта ведомостей атрибутов в Excel
Экспортирует таблицу атрибутов слоев в Excel файл в формате ведомостей
"""

import os
import re
from typing import List, Dict, Any
from qgis.core import (
    QgsMessageLog, Qgis, QgsProject, QgsVectorLayer,
    QgsFeature, QgsField
)
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog, QCheckBox
from qgis.PyQt.QtCore import Qt

from Daman_QGIS.managers import get_reference_managers, DataCleanupManager
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers.M_19_project_structure_manager import (
    get_project_structure_manager, FolderType
)


class ExcelListExportSubmodule:
    """Сабмодуль для экспорта ведомостей атрибутов в Excel"""
    
    def __init__(self, iface):
        """
        Инициализация сабмодуля

        Args:
            iface: Интерфейс QGIS
        """
        self.iface = iface
        self.ref_managers = get_reference_managers()
        self.data_cleanup_manager = DataCleanupManager()
        
    def export(self, **params):
        """
        Экспорт ведомости в Excel с использованием базы стилей
        
        Args:
            **params: Параметры экспорта:
                - layer: слой для экспорта (если один)
                - layers: список слоев (для пакетного экспорта)
                - show_dialog: показывать ли диалог выбора
                - output_folder: папка для сохранения (опционально)
            
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
            log_error("Fsm_1_5_8: Библиотека xlsxwriter не установлена")
            return {}
            
        # Получаем слои для экспорта
        if params.get('show_dialog', True):
            layers = self._show_dialog()
            if not layers:
                return {}
        else:
            # Используем переданные параметры
            if 'layer' in params:
                layers = [params['layer']]
            elif 'layers' in params:
                layers = params['layers']
            else:
                return {}
                
        # Папка для сохранения
        if params.get('output_folder'):
            output_folder = params['output_folder']
        else:
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
            output_folder = structure_manager.get_folder(FolderType.REGISTERS, create=True)
            
        os.makedirs(output_folder, exist_ok=True)
        
        # Результаты экспорта
        results = {}
        
        # Создаем прогресс-диалог
        if params.get('show_progress', True):
            progress = QProgressDialog(
                "Экспорт ведомостей...",
                "Отмена",
                0,
                len(layers),
                self.iface.mainWindow()
            )
            progress.setWindowModality(Qt.WindowModal)
            progress.setAutoClose(True)
            progress.show()
        else:
            progress = None
            
        # Экспортируем каждый слой
        for idx, layer in enumerate(layers):
            if progress:
                if progress.wasCanceled():
                    break
                progress.setValue(idx)
                progress.setLabelText(f"Экспорт: {layer.name()}")
                
            if not isinstance(layer, QgsVectorLayer):
                results[layer.name()] = False
                continue
                
            # Экспортируем слой
            success = self._export_layer(layer, output_folder)
            results[layer.name()] = success
            
        if progress:
            progress.close()
            
        # Показываем результаты
        if params.get('show_dialog', True):
            self._show_results(results, output_folder)
            
        return results
        
    def _show_dialog(self):
        """Показать диалог выбора слоев"""
        from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QListWidget, QListWidgetItem, QDialogButtonBox, QLabel
        
        dialog = QDialog(self.iface.mainWindow())
        dialog.setWindowTitle("Экспорт ведомостей в Excel")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout()
        
        # Информация
        info_label = QLabel("Выберите слои для экспорта ведомостей:")
        layout.addWidget(info_label)
        
        # Список слоев
        list_widget = QListWidget()
        
        # Добавляем только векторные слои с атрибутами
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.featureCount() > 0:
                item = QListWidgetItem(layer.name())
                item.setData(Qt.UserRole, layer)
                # Проверяем, есть ли стиль в базе
                style = self.ref_managers.excel_list_style.get_excel_list_style_for_layer(layer.name())
                item.setCheckState(Qt.Checked if style and style.get('layer') != 'Other' else Qt.Unchecked)
                list_widget.addItem(item)
                
        list_widget.setSelectionMode(QListWidget.MultiSelection)
        layout.addWidget(list_widget)
        
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
    def _export_layer(self, layer: QgsVectorLayer, output_folder: str) -> bool:
        """
        Экспорт одного слоя в Excel

        Args:
            layer: Слой для экспорта
            output_folder: Папка для сохранения

        Returns:
            bool: Успешность экспорта
        """
        import xlsxwriter

        # Получаем стиль из базы
        style = self.ref_managers.excel_list_style.get_excel_list_style_for_layer(layer.name())
        if not style:
            # Используем стиль Other по умолчанию
            style = {
                'layer': 'Other',
                'title': f'Ведомость {layer.name()}',
                'column_names': 'Как в таблице атрибутов'
            }

        # Определяем имена колонок
        column_names = self._get_column_names(style, layer)
        if not column_names:
            log_warning(f"Fsm_1_5_8: Не удалось определить колонки для слоя '{layer.name()}'")
            return False

        # Формируем имя файла
        # DEPRECATED: 2025-10-28 - Заменено на централизованную функцию sanitize_filename()
        # Старая реализация заменяла недопустимые символы, но без проверки зарезервированных имен Windows
        # safe_name = "".join(c if c.isalnum() or c in "_- " else "_" for c in layer.name())
        safe_name = self.data_cleanup_manager.sanitize_filename(layer.name())
        filename = f"Ведомость_{safe_name}.xlsx"
        filepath = os.path.join(output_folder, filename)

        # Создаем Excel файл
        workbook = xlsxwriter.Workbook(filepath)
        worksheet = workbook.add_worksheet('Ведомость')

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
            'font_size': 11,
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'text_wrap': True,
            'bg_color': '#DDEBF7'
        })

        # Формат для номеров колонок (под заголовками)
        header_number_format = workbook.add_format({
            'font_name': 'Times New Roman',
            'font_size': 11,
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'bg_color': '#DDEBF7'
        })

        data_format = workbook.add_format({
            'font_name': 'Times New Roman',
            'font_size': 11,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'text_wrap': True
        })

        number_format = workbook.add_format({
            'font_name': 'Times New Roman',
            'font_size': 11,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'num_format': '#,##0'
        })

        current_row = 0

        # Заголовок ведомости
        title = style.get('title', f'Ведомость {layer.name()}')
        # Форматируем заголовок с переменными
        metadata = self._get_project_metadata()
        formatted_title = self.ref_managers.excel_export_style.format_excel_export_text(
            title,
            metadata,
            {'layer_name': layer.name()}
        )
        # Объединяем ячейки для заголовка
        last_col = len(column_names) - 1
        worksheet.merge_range(current_row, 0, current_row, last_col, formatted_title, title_format)
        worksheet.set_row(current_row, 30)
        current_row += 1

        # Пустая строка после заголовка
        current_row += 1

        # Получаем поля слоя для сопоставления
        field_names = [field.name() for field in layer.fields()]
        field_indices = {}

        # Заголовки колонок (наименования)
        for col_idx, col_name in enumerate(column_names):
            worksheet.write(current_row, col_idx, col_name, header_format)

            # Находим соответствующее поле в слое
            # Сначала ищем по рабочему названию из баз
            field_index = self._find_field_index(layer, col_name)
            if field_index >= 0:
                field_indices[col_idx] = field_index

        worksheet.set_row(current_row, 40)  # Высота строки заголовков
        current_row += 1

        # Номера колонок под заголовками (1, 2, 3, ...)
        for col_idx in range(len(column_names)):
            worksheet.write(current_row, col_idx, col_idx + 1, header_number_format)
        worksheet.set_row(current_row, 20)  # Высота строки номеров
        current_row += 1

        # Данные
        row_number = 0
        for feature in layer.getFeatures():
            row_number += 1

            # Добавляем номер строки если первая колонка - "№ п/п" или "ID"
            if column_names[0] in ["№ п/п", "ID", "№"]:
                worksheet.write(current_row, 0, row_number, data_format)
                start_col = 1
            else:
                start_col = 0

            # Выводим атрибуты
            for col_idx in range(start_col, len(column_names)):
                if col_idx in field_indices:
                    field_idx = field_indices[col_idx]
                    value = feature.attribute(field_idx)

                    # Форматируем значение
                    if value is None or value == "":
                        worksheet.write(current_row, col_idx, "-", data_format)
                    elif isinstance(value, (int, float)):
                        # Числовые значения с форматированием
                        if "площадь" in column_names[col_idx].lower():
                            worksheet.write(current_row, col_idx, value, number_format)
                        else:
                            worksheet.write(current_row, col_idx, value, data_format)
                    else:
                        # Текстовые значения
                        worksheet.write(current_row, col_idx, str(value), data_format)
                else:
                    # Если поле не найдено
                    worksheet.write(current_row, col_idx, "-", data_format)

            current_row += 1

        # Автоподбор ширины колонок
        for col_idx, col_name in enumerate(column_names):
            # Базовая ширина на основе названия колонки
            width = max(15, len(col_name) * 1.2)

            # Специальные случаи
            if "кадастровый номер" in col_name.lower():
                width = 25
            elif "адрес" in col_name.lower() or "местоположение" in col_name.lower():
                width = 40
            elif "категория" in col_name.lower() or "ври" in col_name.lower():
                width = 35
            elif "собственник" in col_name.lower() or "правообладатель" in col_name.lower():
                width = 40
            elif col_name in ["№ п/п", "ID", "№"]:
                width = 8

            worksheet.set_column(col_idx, col_idx, width)

        # Настройка области печати
        if current_row > 0:
            last_col_letter = chr(ord('A') + len(column_names) - 1)
            print_area = f'A1:{last_col_letter}{current_row}'
            worksheet.set_print_area(print_area)  # type: ignore[attr-defined]

        # Закрываем файл
        workbook.close()

        log_info(f"Fsm_1_5_8: Экспорт ведомости завершен: {filepath}")
        return True
            
    def _get_column_names(self, style: Dict[str, Any], layer: QgsVectorLayer) -> List[str]:
        """
        Получить имена колонок из стиля
        
        Args:
            style: Стиль из базы данных
            layer: Слой для экспорта
            
        Returns:
            Список имен колонок
        """
        column_names_str = style.get('column_names', '')
        
        # Обработка специальных случаев
        if column_names_str == 'Как в таблице атрибутов':
            # Берем все поля слоя
            names = [field.displayName() or field.name() for field in layer.fields()]
            # Добавляем номер в начало если его нет
            if names and names[0] not in ["№ п/п", "ID", "№"]:
                names.insert(0, "№ п/п")
            return names
            
        elif ' из ' in column_names_str:
            # Парсим ссылку на базу данных
            # Форматы: "full_name из Base_cutting" или "working_name из Base_cutting"
            parts = column_names_str.split(' из ')
            if len(parts) == 2:
                field_name = parts[0].strip()
                db_name = parts[1].strip()
                
                # Загружаем соответствующую базу
                if db_name == "Base_cutting":
                    # Получаем структуру из Base_cutting
                    cutting_data = self.ref_managers.layer_field_structure.get_cutting_fields()
                    if cutting_data:
                        names = []
                        # Добавляем № п/п в начало для ведомости
                        names.append("№ п/п")
                        for item in cutting_data:
                            if field_name == 'full_name':
                                names.append(item.get('full_name', item.get('working_name', '')))
                            elif field_name == 'working_name':
                                names.append(item.get('working_name', ''))
                        return names
                        
                elif db_name == "Base_selection_ZU":
                    # Получаем структуру из Base_selection_ZU
                    selection_data = self.ref_managers.layer_field_structure.get_selection_zu_fields()
                    if selection_data:
                        names = []
                        # Добавляем № п/п в начало
                        names.append("№ п/п")
                        for item in selection_data:
                            if field_name == 'full_name':
                                names.append(item.get('full_name', item.get('name', '')))
                            elif field_name == 'name':
                                names.append(item.get('name', ''))
                        return names
                        
        elif ',' in column_names_str:
            # Простой список через запятую
            names = [name.strip() for name in column_names_str.split(',')]
            return names
            
        # По умолчанию берем все поля
        return [field.displayName() or field.name() for field in layer.fields()]
        
    def _find_field_index(self, layer: QgsVectorLayer, column_name: str) -> int:
        """
        Найти индекс поля в слое по имени колонки
        
        Args:
            layer: Слой
            column_name: Имя колонки из базы
            
        Returns:
            Индекс поля или -1 если не найдено
        """
        # Словарь соответствий полных имен и рабочих имен
        name_mapping = {
            # Из Base_cutting
            "ID": ["ID", "id", "fid"],
            "Условный кадастровый номер": ["Услов_КН", "uslov_kn"],
            "Кадастровый номер существующего земельного участка": ["КН", "kn", "cadastral_number"],
            "Условный кадастровый номер единого землепользования": ["Услов_ЕЗ", "uslov_ez"],
            "Кадастровый номер единого землепользования существующего земельного участка": ["ЕЗ", "ez"],
            "Тип объекта": ["Тип_объекта", "type", "object_type"],
            "Адрес местоположения": ["Адрес_Местоположения", "address", "location"],
            "Категория земель": ["Категория", "category"],
            "Планируемая категория земель": ["План_категория", "plan_category"],
            "Вид разрешенного использования": ["ВРИ", "vri", "permitted_use"],
            "Планируемый вид разрешенного использования": ["План_ВРИ", "plan_vri"],
            "Площадь существующего земельного участка": ["Площадь", "area", "area_sqm"],
            "Площадь образуемого земельного участка": ["Площадь_ОЗУ", "area_ozu"],
            "Права": ["Права", "rights"],
            "Обременение": ["Обременение", "encumbrance"],
            "Собственники": ["Собственники", "owners"],
            "Арендаторы": ["Арендаторы", "tenants"],
            "Статус": ["Статус", "status"],
            "Вид работ": ["Вид_Работ", "work_type"],
            "ЗПР": ["ЗПР", "zpr"],
            # Из Base_selection_ZU (дополнительно)
            "Кадастровый номер": ["КН", "kn", "cadastral_number"],
            "Единое землепользование": ["ЕЗ", "ez"],
        }
        
        # Получаем все поля слоя
        fields = layer.fields()
        
        # Сначала ищем точное совпадение
        for i, field in enumerate(fields):
            if field.name() == column_name or field.displayName() == column_name:
                return i
                
        # Затем ищем по маппингу
        if column_name in name_mapping:
            possible_names = name_mapping[column_name]
            for i, field in enumerate(fields):
                field_name_lower = field.name().lower()
                for possible in possible_names:
                    if field_name_lower == possible.lower():
                        return i
                        
        # Поиск по частичному совпадению (последняя попытка)
        column_lower = column_name.lower()
        for i, field in enumerate(fields):
            field_lower = field.name().lower()
            # Проверяем вхождение ключевых слов
            if ("кадастр" in column_lower and "кадастр" in field_lower) or \
               ("площадь" in column_lower and "площадь" in field_lower) or \
               ("адрес" in column_lower and "адрес" in field_lower) or \
               ("категория" in column_lower and "категория" in field_lower) or \
               ("ври" in column_lower and "ври" in field_lower):
                return i
                
        return -1
        
    def _get_project_metadata(self) -> Dict[str, Any]:
        """Получить метаданные проекта из GeoPackage"""
        try:
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

        except Exception as e:
            log_warning(f"Fsm_1_5_8: Ошибка чтения метаданных: {str(e)}")
            return {}
            
    def _show_results(self, results: Dict[str, bool], output_folder: str):
        """Показать результаты экспорта"""
        success_count = sum(1 for success in results.values() if success)
        error_count = len(results) - success_count
        
        message = f"Экспорт ведомостей завершен!\n\n"
        message += f"Успешно: {success_count} слоев\n"
        if error_count > 0:
            message += f"Ошибок: {error_count} слоев\n"
        message += f"\nФайлы сохранены в:\n{output_folder}"
        
        QMessageBox.information(
            self.iface.mainWindow(),
            "Экспорт ведомостей",
            message
        )
