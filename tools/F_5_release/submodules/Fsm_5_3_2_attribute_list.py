# -*- coding: utf-8 -*-
"""
Fsm_5_3_2 - Экспорт ведомостей атрибутов в Excel

Экспортирует таблицу атрибутов слоёв в Excel файл в формате ведомостей
с заголовками, нумерацией колонок и форматированием.

Шаблоны: Fsm_5_3_8_template_registry.py (DocumentTemplate)
Форматы: Fsm_5_3_4_format_manager.py (ExcelFormatManager)
"""

import os
from typing import Dict, Any, List, Optional

from qgis.core import QgsVectorLayer

from Daman_QGIS.utils import log_info, log_warning, log_error

from .Fsm_5_3_4_format_manager import ExcelFormatManager
from .Fsm_5_3_5_export_utils import ExportUtils
from .Fsm_5_3_8_template_registry import DocumentTemplate


class Fsm_5_3_2_AttributeList:
    """Экспортёр ведомостей атрибутов в Excel"""

    def __init__(self, iface, ref_managers=None):
        """
        Инициализация

        Args:
            iface: Интерфейс QGIS
            ref_managers: Reference managers (для доступа к LayerFieldStructureManager)
        """
        self.iface = iface
        self.ref_managers = ref_managers
        # Lazy-кэш маппинга full_name -> working_name из Base_cutting
        self._cutting_name_map: Optional[Dict[str, str]] = None

    def export_layer(
        self,
        layer: QgsVectorLayer,
        template: DocumentTemplate,
        output_folder: str,
        extra_context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Экспорт слоя в Excel (ведомость)

        Args:
            layer: Слой для экспорта
            template: Шаблон документа из TemplateRegistry
            output_folder: Папка для сохранения
            extra_context: Дополнительный контекст (продуктовый слой / региональные
                модификаторы). При extra_context['vedomost_merged'] = True экспорт
                идёт по объединённому пути (_export_vedomost_merged); иначе —
                обычный single-layer путь (обратная совместимость по default=None)

        Returns:
            bool: Успешность экспорта
        """
        # Диспетч: объединённая ведомость ОЗУ (несколько слоёв в одну таблицу)
        if extra_context and extra_context.get('vedomost_merged'):
            return self._export_vedomost_merged(template, output_folder, extra_context)

        try:
            import xlsxwriter
        except ImportError:
            log_error("Fsm_5_3_2: Библиотека xlsxwriter не установлена")
            return False

        # Определяем имена колонок
        column_names = self._get_column_names(template, layer)
        if not column_names:
            log_warning(f"Fsm_5_3_2: Не удалось определить колонки для слоя '{layer.name()}'")
            return False

        metadata = ExportUtils.get_project_metadata()
        layer_info = {'layer_name': layer.name()}

        # Формируем имя файла из шаблона
        if template.filename_template:
            filename_base = ExportUtils.format_template_text(
                template.filename_template, metadata, layer_info
            )
        else:
            filename_base = f"Ведомость_{layer.name()}"

        filename = f"{ExportUtils.sanitize_filename(filename_base)}.xlsx"
        filepath = os.path.join(output_folder, filename)

        # Создаём Excel файл
        workbook = xlsxwriter.Workbook(filepath)
        worksheet = workbook.add_worksheet('Ведомость')
        fmt = ExcelFormatManager(workbook)

        current_row = 0

        # Заголовок ведомости
        formatted_title = ExportUtils.format_template_text(
            template.title_template, metadata, layer_info
        )

        last_col = len(column_names) - 1
        worksheet.merge_range(
            current_row, 0, current_row, last_col,
            formatted_title, fmt.get_title_format(font_size=14)
        )
        worksheet.set_row(current_row, 30)
        current_row += 1

        # Пустая строка после заголовка
        current_row += 1

        # Получаем поля слоя для сопоставления
        field_indices: Dict[int, int] = {}

        # Заголовки колонок (наименования)
        header_format = fmt.get_header_format()
        for col_idx, col_name in enumerate(column_names):
            worksheet.write(current_row, col_idx, col_name, header_format)

            field_index = self._find_field_index(layer, col_name)
            if field_index >= 0:
                field_indices[col_idx] = field_index

        worksheet.set_row(current_row, 40)
        current_row += 1

        # Номера колонок под заголовками (1, 2, 3, ...)
        col_num_format = fmt.get_column_number_format()
        for col_idx in range(len(column_names)):
            worksheet.write(current_row, col_idx, col_idx + 1, col_num_format)
        worksheet.set_row(current_row, 20)
        current_row += 1

        # Данные
        data_format = fmt.get_data_format()
        number_format = fmt.get_number_format()
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

        # Автоподбор ширины колонок через FormatManager
        fmt.set_smart_column_widths(worksheet, column_names)

        # Настройка области печати
        if current_row > 0:
            worksheet.print_area(0, 0, current_row - 1, len(column_names) - 1)

        workbook.close()

        log_info(f"Fsm_5_3_2: Экспорт ведомости завершён: {filepath}")
        return True

    def _export_vedomost_merged(
        self,
        template: DocumentTemplate,
        output_folder: str,
        extra_context: Dict[str, Any]
    ) -> bool:
        """
        Экспорт объединённой ведомости ОЗУ (строки нескольких слоёв в одну таблицу)

        Строки берутся из всех слоёв extra_context['merged_layers'] в переданном
        порядке (Раздел -> НГС -> Без_Меж -> Изм). Внутри каждого слоя строки
        сортируются по полю ID (числовая сортировка, нечисловые в конец).
        Колонки определяются как в single-layer пути — через column_source
        (Base_cutting full_name). Отсутствующие поля/значения -> "-".

        Args:
            template: Шаблон документа (VEDOMOST_OZU)
            output_folder: Папка для сохранения
            extra_context: Контекст продукта. Ожидаемые ключи:
                merged_layers: List[QgsVectorLayer] — слои состава в порядке
                group_name: str — имя ЗПР-группы (для имени файла / лога)
                filename_override: Optional[str] — шаблон имени файла с {group_name}

        Returns:
            bool: Успешность экспорта
        """
        try:
            import xlsxwriter
        except ImportError:
            log_error("Fsm_5_3_2: Библиотека xlsxwriter не установлена")
            return False

        merged_layers: List[QgsVectorLayer] = extra_context.get('merged_layers') or []
        if not merged_layers:
            log_warning("Fsm_5_3_2: Объединённая ведомость без слоёв (merged_layers пуст)")
            return False

        group_name = extra_context.get('group_name', '')

        # Колонки — тот же механизм, что и в single-layer пути.
        # Для column_source = Base_cutting слой не используется при определении
        # колонок; первый слой передаётся для совместимости сигнатуры.
        column_names = self._get_column_names(template, merged_layers[0])
        if not column_names:
            log_warning(
                f"Fsm_5_3_2: Не удалось определить колонки объединённой ведомости "
                f"(группа '{group_name}')"
            )
            return False

        metadata = ExportUtils.get_project_metadata()

        # Формируем имя файла: filename_override (с {group_name}) приоритетнее
        # статичного filename_template шаблона. Без override merged-ведомости
        # всех ЗПР получили бы одно имя и перезаписали бы друг друга.
        filename_override = extra_context.get('filename_override')
        if filename_override:
            filename_base = ExportUtils.format_template_text(
                filename_override, metadata, {'group_name': group_name}
            )
        elif template.filename_template:
            filename_base = ExportUtils.format_template_text(
                template.filename_template, metadata, {'group_name': group_name}
            )
        else:
            filename_base = f"Ведомость_ОЗУ_{group_name}" if group_name else "Ведомость_ОЗУ"

        filename = f"{ExportUtils.sanitize_filename(filename_base)}.xlsx"
        filepath = os.path.join(output_folder, filename)

        workbook = xlsxwriter.Workbook(filepath)
        worksheet = workbook.add_worksheet('Ведомость')
        fmt = ExcelFormatManager(workbook)

        current_row = 0

        # Заголовок документа из шаблона
        formatted_title = ExportUtils.format_template_text(
            template.title_template, metadata, {'group_name': group_name}
        )
        last_col = len(column_names) - 1
        worksheet.merge_range(
            current_row, 0, current_row, last_col,
            formatted_title, fmt.get_title_format(font_size=14)
        )
        worksheet.set_row(current_row, 30)
        current_row += 1

        # Пустая строка после заголовка
        current_row += 1

        # Заголовки колонок (наименования)
        header_format = fmt.get_header_format()
        for col_idx, col_name in enumerate(column_names):
            worksheet.write(current_row, col_idx, col_name, header_format)
        worksheet.set_row(current_row, 40)
        current_row += 1

        # Номера колонок под заголовками (1, 2, 3, ...)
        col_num_format = fmt.get_column_number_format()
        for col_idx in range(len(column_names)):
            worksheet.write(current_row, col_idx, col_idx + 1, col_num_format)
        worksheet.set_row(current_row, 20)
        current_row += 1

        data_format = fmt.get_data_format()
        number_format = fmt.get_number_format()
        row_number = 0
        has_row_number_col = column_names[0] in ["№ п/п", "ID", "№"]

        # Строки из всех слоёв в переданном порядке
        for layer in merged_layers:
            # Сопоставление колонок с полями текущего слоя (схемы слоёв могут
            # различаться — у НГС/Без_Меж/Изм состав полей отличается от Раздела)
            field_indices: Dict[int, int] = {}
            for col_idx, col_name in enumerate(column_names):
                field_index = self._find_field_index(layer, col_name)
                if field_index >= 0:
                    field_indices[col_idx] = field_index

            for feature in self._sorted_features_by_id(layer):
                row_number += 1

                if has_row_number_col:
                    worksheet.write(current_row, 0, row_number, data_format)
                    start_col = 1
                else:
                    start_col = 0

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
        fmt.set_smart_column_widths(worksheet, column_names)

        # Настройка области печати
        if current_row > 0:
            worksheet.print_area(0, 0, current_row - 1, len(column_names) - 1)

        workbook.close()

        log_info(
            f"Fsm_5_3_2: Экспорт объединённой ведомости завершён "
            f"(группа '{group_name}', строк {row_number}): {filepath}"
        )
        return True

    def _sorted_features_by_id(self, layer: QgsVectorLayer) -> List[Any]:
        """
        Получить фичи слоя, отсортированные по полю ID

        Числовые значения ID — по возрастанию, нечисловые/отсутствующие — в конец
        (стабильно, в порядке исходного чтения слоя).

        Args:
            layer: Слой

        Returns:
            Список фич в порядке сортировки
        """
        id_index = self._find_field_index(layer, "ID")
        features = list(layer.getFeatures())

        if id_index < 0:
            return features

        def sort_key(feature: Any) -> Any:
            value = feature.attribute(id_index)
            try:
                return (0, float(value))
            except (TypeError, ValueError):
                # Нечисловые / None -> в конец
                return (1, 0.0)

        return sorted(features, key=sort_key)

    def _get_column_names(
        self,
        template: DocumentTemplate,
        layer: QgsVectorLayer
    ) -> List[str]:
        """
        Получить имена колонок из шаблона

        Логика:
        1. Если template.column_source задан - загрузить из справочника
        2. Иначе - использовать поля слоя

        Args:
            template: Шаблон документа
            layer: Слой для экспорта

        Returns:
            Список имён колонок
        """
        if template.column_source and self.ref_managers:
            db_name = template.column_source.get('database', '')
            field_name = template.column_source.get('field', 'full_name')

            if db_name == 'Base_cutting':
                cutting_data = self.ref_managers.layer_field_structure.get_cutting_fields()
                if cutting_data:
                    names = ["№ п/п"]
                    for item in cutting_data:
                        names.append(item.get(field_name, item.get('working_name', '')))
                    return names

            elif db_name == 'Base_selection_ZU':
                selection_data = self.ref_managers.layer_field_structure.get_selection_zu_fields()
                if selection_data:
                    names = ["№ п/п"]
                    for item in selection_data:
                        names.append(item.get(field_name, item.get('name', '')))
                    return names

        # По умолчанию - поля из слоя
        names = [field.displayName() or field.name() for field in layer.fields()]
        if names and names[0] not in ["№ п/п", "ID", "№"]:
            names.insert(0, "№ п/п")
        return names

    def _cutting_full_name_map(self) -> Dict[str, str]:
        """
        Маппинг full_name -> working_name из справочника Base_cutting

        Источник истины для связи "колонка ведомости -> поле слоя": слои
        нарезки/этапности создаются с полями working_name из той же базы.
        Хвостовые пробелы full_name справочника игнорируются (strip).
        Кэшируется на время жизни экспортёра.

        Returns:
            Словарь {full_name_stripped: working_name}; пустой при недоступном
            справочнике (fallback на name_mapping/partial-match сохраняется)
        """
        if self._cutting_name_map is None:
            mapping: Dict[str, str] = {}
            try:
                if self.ref_managers:
                    cutting_data = (
                        self.ref_managers.layer_field_structure.get_cutting_fields()
                    )
                    for item in cutting_data or []:
                        full = (item.get('full_name') or '').strip()
                        working = (item.get('working_name') or '').strip()
                        if full and working:
                            mapping[full] = working
            except Exception as e:
                log_warning(
                    f"Fsm_5_3_2: не удалось построить маппинг Base_cutting "
                    f"full_name -> working_name: {e}"
                )
            self._cutting_name_map = mapping
        return self._cutting_name_map

    def _find_field_index(self, layer: QgsVectorLayer, column_name: str) -> int:
        """
        Найти индекс поля в слое по имени колонки

        Args:
            layer: Слой
            column_name: Имя колонки из базы

        Returns:
            Индекс поля или -1
        """
        # Маппинг полных названий -> рабочие имена полей (бизнес-логика)
        name_mapping = {
            "ID": ["ID", "id", "fid"],
            "Условный кадастровый номер": ["Услов_КН", "uslov_kn"],
            "Кадастровый номер существующего земельного участка": ["КН", "kn", "cadastral_number"],
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
            "Обременения": ["Обременения", "encumbrance"],
            "Собственники": ["Собственники", "owners"],
            "Арендаторы": ["Арендаторы", "tenants"],
            "Статус": ["Статус", "status"],
            "Вид работ": ["Вид_Работ", "work_type"],
            "Способ образования земельного участка/ вид работ": ["Вид_Работ", "work_type"],
            "ЗПР": ["ЗПР", "zpr"],
            "Кадастровый номер": ["КН", "kn", "cadastral_number"],
            "Единое землепользование": ["ЕЗ", "ez"],
        }

        fields = layer.fields()

        # Сначала ищем точное совпадение
        for i, field in enumerate(fields):
            if field.name() == column_name or field.displayName() == column_name:
                return i

        # Справочный маппинг Base_cutting: full_name -> working_name (источник
        # истины — слои нарезки/этапности создаются с полями working_name из той
        # же базы). Чинит колонки ведомости, отсутствующие в name_mapping ниже:
        # ручной словарь не совпадал с реальными full_name справочника, из-за
        # чего большинство колонок merged-ведомости рендерилось "-".
        working_name = self._cutting_full_name_map().get(column_name.strip())
        if working_name:
            idx = fields.indexOf(working_name)
            if idx >= 0:
                return idx

        # Затем ищем по маппингу
        if column_name in name_mapping:
            possible_names = name_mapping[column_name]
            for i, field in enumerate(fields):
                field_name_lower = field.name().lower()
                for possible in possible_names:
                    if field_name_lower == possible.lower():
                        return i

        # Поиск по частичному совпадению (ключевые слова)
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
