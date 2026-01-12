# -*- coding: utf-8 -*-
"""
Fsm_6_3_2 - Экспорт ведомостей атрибутов в Excel

Экспортирует таблицу атрибутов слоёв в Excel файл в формате ведомостей
с заголовками, нумерацией колонок и форматированием.

Шаблоны: Base_excel_list_styles.json
"""

import os
from typing import Dict, Any, List, Optional

from qgis.core import QgsProject, QgsVectorLayer

from Daman_QGIS.managers import DataCleanupManager, get_project_structure_manager
from Daman_QGIS.utils import log_info, log_warning, log_error


class Fsm_6_3_2_AttributeList:
    """Экспортёр ведомостей атрибутов в Excel"""

    def __init__(self, iface, ref_managers):
        """
        Инициализация

        Args:
            iface: Интерфейс QGIS
            ref_managers: Reference managers
        """
        self.iface = iface
        self.ref_managers = ref_managers
        self.data_cleanup_manager = DataCleanupManager()

    def export_layer(
        self,
        layer: QgsVectorLayer,
        style: Dict[str, Any],
        output_folder: str
    ) -> bool:
        """
        Экспорт слоя в Excel (ведомость)

        Args:
            layer: Слой для экспорта
            style: Стиль из Base_excel_list_styles.json
            output_folder: Папка для сохранения

        Returns:
            bool: Успешность экспорта
        """
        try:
            import xlsxwriter
        except ImportError:
            log_error("Fsm_6_3_2: Библиотека xlsxwriter не установлена")
            return False

        # Определяем имена колонок
        column_names = self._get_column_names(style, layer)
        if not column_names:
            log_warning(f"Fsm_6_3_2: Не удалось определить колонки для слоя '{layer.name()}'")
            return False

        # Формируем имя файла
        safe_name = self.data_cleanup_manager.sanitize_filename(layer.name())
        filename = f"Ведомость_{safe_name}.xlsx"
        filepath = os.path.join(output_folder, filename)

        # Создаём Excel файл
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
        metadata = self._get_project_metadata()
        formatted_title = self.ref_managers.excel_export_style.format_excel_export_text(
            title,
            metadata,
            {'layer_name': layer.name()}
        )

        last_col = len(column_names) - 1
        worksheet.merge_range(current_row, 0, current_row, last_col, formatted_title, title_format)
        worksheet.set_row(current_row, 30)
        current_row += 1

        # Пустая строка после заголовка
        current_row += 1

        # Получаем поля слоя для сопоставления
        field_indices = {}

        # Заголовки колонок (наименования)
        for col_idx, col_name in enumerate(column_names):
            worksheet.write(current_row, col_idx, col_name, header_format)

            # Находим соответствующее поле в слое
            field_index = self._find_field_index(layer, col_name)
            if field_index >= 0:
                field_indices[col_idx] = field_index

        worksheet.set_row(current_row, 40)
        current_row += 1

        # Номера колонок под заголовками (1, 2, 3, ...)
        for col_idx in range(len(column_names)):
            worksheet.write(current_row, col_idx, col_idx + 1, header_number_format)
        worksheet.set_row(current_row, 20)
        current_row += 1

        # Данные
        row_number = 0
        for feature in layer.getFeatures():
            row_number += 1

            # Добавляем номер строки если первая колонка - номер
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

                    if value is None or value == "":
                        worksheet.write(current_row, col_idx, "-", data_format)
                    elif isinstance(value, (int, float)):
                        if "площадь" in column_names[col_idx].lower():
                            worksheet.write(current_row, col_idx, value, number_format)
                        else:
                            worksheet.write(current_row, col_idx, value, data_format)
                    else:
                        worksheet.write(current_row, col_idx, str(value), data_format)
                else:
                    worksheet.write(current_row, col_idx, "-", data_format)

            current_row += 1

        # Автоподбор ширины колонок
        for col_idx, col_name in enumerate(column_names):
            width = max(15, len(col_name) * 1.2)

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
            last_col_letter = chr(ord('A') + len(column_names) - 1) if len(column_names) <= 26 else 'Z'
            # print_area - метод, а не свойство в xlsxwriter
            worksheet.print_area(0, 0, current_row - 1, len(column_names) - 1)

        workbook.close()

        log_info(f"Fsm_6_3_2: Экспорт ведомости завершён: {filepath}")
        return True

    def _get_column_names(self, style: Dict[str, Any], layer: QgsVectorLayer) -> List[str]:
        """
        Получить имена колонок из стиля

        Args:
            style: Стиль из базы данных
            layer: Слой для экспорта

        Returns:
            Список имён колонок
        """
        column_names_str = style.get('column_names', '')

        # Обработка специальных случаев
        if column_names_str == 'Как в таблице атрибутов':
            names = [field.displayName() or field.name() for field in layer.fields()]
            if names and names[0] not in ["№ п/п", "ID", "№"]:
                names.insert(0, "№ п/п")
            return names

        elif ' из ' in column_names_str:
            parts = column_names_str.split(' из ')
            if len(parts) == 2:
                field_name = parts[0].strip()
                db_name = parts[1].strip()

                if db_name == "Base_cutting":
                    cutting_data = self.ref_managers.layer_field_structure.get_cutting_fields()
                    if cutting_data:
                        names = ["№ п/п"]
                        for item in cutting_data:
                            if field_name == 'full_name':
                                names.append(item.get('full_name', item.get('working_name', '')))
                            elif field_name == 'working_name':
                                names.append(item.get('working_name', ''))
                        return names

                elif db_name == "Base_selection_ZU":
                    selection_data = self.ref_managers.layer_field_structure.get_selection_zu_fields()
                    if selection_data:
                        names = ["№ п/п"]
                        for item in selection_data:
                            if field_name == 'full_name':
                                names.append(item.get('full_name', item.get('name', '')))
                            elif field_name == 'name':
                                names.append(item.get('name', ''))
                        return names

        elif ',' in column_names_str:
            names = [name.strip() for name in column_names_str.split(',')]
            return names

        # По умолчанию
        return [field.displayName() or field.name() for field in layer.fields()]

    def _find_field_index(self, layer: QgsVectorLayer, column_name: str) -> int:
        """
        Найти индекс поля в слое по имени колонки

        Args:
            layer: Слой
            column_name: Имя колонки из базы

        Returns:
            Индекс поля или -1
        """
        name_mapping = {
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
            "Кадастровый номер": ["КН", "kn", "cadastral_number"],
            "Единое землепользование": ["ЕЗ", "ez"],
        }

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

        # Поиск по частичному совпадению
        column_lower = column_name.lower()
        for i, field in enumerate(fields):
            field_lower = field.name().lower()
            if ("кадастр" in column_lower and "кадастр" in field_lower) or \
               ("площадь" in column_lower and "площадь" in field_lower) or \
               ("адрес" in column_lower and "адрес" in field_lower) or \
               ("категория" in column_lower and "категория" in field_lower) or \
               ("ври" in column_lower and "ври" in field_lower):
                return i

        return -1

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
            log_warning(f"Fsm_6_3_2: Ошибка чтения метаданных: {str(e)}")
            return {}
