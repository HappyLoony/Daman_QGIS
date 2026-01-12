# -*- coding: utf-8 -*-
"""
Msm_4_17_FieldMappingManager - Менеджер маппинга полей выписок ЕГРН

Загрузка и управление маппингом XML XPath → рабочие поля для импорта выписок.
Поддержка альтернативных путей (физлицо/юрлицо), массивов, конвертации типов.
"""

from typing import List, Dict, Optional, Any
from qgis.core import QgsField
from qgis.PyQt.QtCore import QMetaType, QDate
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
from Daman_QGIS.utils import log_error, log_warning
from Daman_QGIS.constants import MAX_FIELD_LEN


class FieldMappingManager(BaseReferenceLoader):
    """
    Менеджер маппинга полей выписок ЕГРН (XML XPath → рабочие поля)

    ZERO HARDCODE PRINCIPLE: Все маппинги загружаются из Base_field_mapping_EGRN.json
    """

    FIELD_MAPPING_FILE = 'Base_field_mapping_EGRN.json'

    def __init__(self, plugin_dir: str):
        """
        Инициализация менеджера

        Args:
            plugin_dir: Путь к директории плагина
        """
        super().__init__(plugin_dir)
        self._mappings = None
        self._by_record_type = {}
        self._by_working_name = {}

    def get_all_mappings(self) -> List[Dict]:
        """
        Получить все маппинги полей

        Returns:
            Список всех маппингов
        """
        if self._mappings is None:
            self._mappings = self._load_json(self.FIELD_MAPPING_FILE) or []
            self._index_mappings()
        return self._mappings

    def _index_mappings(self):
        """Индексация маппингов по record_type и working_name для быстрого доступа"""
        self._by_record_type = {}
        self._by_working_name = {}

        if not self._mappings:
            return

        for mapping in self._mappings:
            # Индекс по working_name
            working_name = mapping.get('working_name')
            if working_name:
                self._by_working_name[working_name] = mapping

            # Индекс по record_types (может быть несколько через запятую)
            record_types_str = mapping.get('record_types', '')
            if record_types_str:
                # Парсинг "land_record, unified_land_record" → ["land_record", "unified_land_record"]
                record_types = [rt.strip() for rt in record_types_str.split(',')]
                for record_type in record_types:
                    if record_type not in self._by_record_type:
                        self._by_record_type[record_type] = []
                    self._by_record_type[record_type].append(mapping)

    def get_fields_for_record_type(self, record_type: str) -> List[Dict]:
        """
        Получить все маппинги полей для указанного типа записи

        Args:
            record_type: Тип записи (land_record, unified_land_record, build_record)

        Returns:
            Список маппингов для данного типа записи
        """
        if not self._mappings:
            self.get_all_mappings()

        return self._by_record_type.get(record_type, [])

    def get_mapping(self, working_name: str, record_type: Optional[str] = None) -> Optional[Dict]:
        """
        Получить маппинг по рабочему имени поля

        Args:
            working_name: Рабочее имя поля (например, "КН", "Площадь")
            record_type: Опционально - тип записи для валидации

        Returns:
            Маппинг поля или None
        """
        if not self._mappings:
            self.get_all_mappings()

        mapping = self._by_working_name.get(working_name)

        # Если указан record_type, проверяем что поле применимо к этому типу
        if mapping and record_type:
            record_types = [rt.strip() for rt in mapping.get('record_types', '').split(',')]
            if record_type not in record_types:
                return None

        return mapping

    def _parse_xpath_alternatives(self, mapping: Dict) -> Optional[List[str]]:
        """
        Парсинг альтернативных XPath из маппинга

        Поддерживает два формата:
        1. xml_xpath_alternatives: ["path1", "path2"] - массив (приоритет)
        2. xml_xpath: "path1; path2; path3" - строка с разделителем

        Args:
            mapping: Маппинг поля

        Returns:
            Список альтернативных XPath или None
        """
        # ПРИОРИТЕТ 1: Явный массив xml_xpath_alternatives
        xml_xpath_alternatives = mapping.get('xml_xpath_alternatives')
        if xml_xpath_alternatives and isinstance(xml_xpath_alternatives, list):
            return xml_xpath_alternatives

        # ПРИОРИТЕТ 2: xml_xpath с разделителем ";"
        xml_xpath = mapping.get('xml_xpath', '')
        if xml_xpath and isinstance(xml_xpath, str) and ';' in xml_xpath:
            # Разбиваем по ";" и убираем пробелы
            return [path.strip() for path in xml_xpath.split(';') if path.strip() and path.strip() not in ('-', 'null', '')]

        return None

    def extract_value(self, xml_element, mapping: Dict) -> Any:
        """
        Извлечь значение из XML элемента согласно маппингу

        Поддерживает:
        - Простой XPath: xml_xpath
        - Массивы: xml_xpath_root + xml_xpath
        - Альтернативные пути: xml_xpath_alternatives ИЛИ xml_xpath с ";"

        Args:
            xml_element: XML элемент (lxml или ElementTree)
            mapping: Маппинг поля

        Returns:
            Извлечённое и сконвертированное значение
        """
        # CASE 1: Массив (xml_xpath_root указан)
        if mapping.get('xml_xpath_root') and mapping['xml_xpath_root'] not in ('-', 'null', ''):
            return self._extract_array_value(xml_element, mapping)

        # CASE 2: Альтернативные XPath (физлицо/юрлицо или ";"-список)
        alternatives = self._parse_xpath_alternatives(mapping)
        if alternatives:
            return self._extract_alternative_value(xml_element, mapping, alternatives)

        # CASE 3: Простой XPath
        xml_xpath = mapping.get('xml_xpath')
        if not xml_xpath or xml_xpath in ('-', 'null', ''):
            return None

        value = xml_element.findtext(xml_xpath)
        return self._convert_value(value, mapping)

    def _extract_array_value(self, xml_element, mapping: Dict) -> Any:
        """
        Извлечь множественные значения из XML (массив)

        Args:
            xml_element: XML элемент
            mapping: Маппинг поля

        Returns:
            Объединённая строка значений через "; " или None
        """
        xml_xpath_root = mapping.get('xml_xpath_root')
        if not xml_xpath_root:
            return None

        # Парсим альтернативные XPath (из xml_xpath_alternatives ИЛИ из xml_xpath с ";")
        alternatives = self._parse_xpath_alternatives(mapping)

        values = []
        # Итерация по корневому контейнеру (например, right_records/right_record)
        for elem in xml_element.findall(xml_xpath_root):
            # ПОДДЕРЖКА АЛЬТЕРНАТИВНЫХ XPATH (для физлиц/юрлиц/муниципалитетов)
            if alternatives:
                # Пробуем каждый XPath по порядку
                for alt_xpath in alternatives:
                    if not alt_xpath or alt_xpath in ('-', 'null', ''):
                        continue
                    value = elem.findtext(alt_xpath)
                    if value and value.strip():
                        values.append(value.strip())
                        break  # Нашли значение - переходим к следующему элементу
            # Обычный XPath (без альтернатив и без ";")
            else:
                xml_xpath = mapping.get('xml_xpath')
                if xml_xpath and xml_xpath not in ('-', 'null', ''):
                    value = elem.findtext(xml_xpath)
                    if value and value.strip():
                        values.append(value.strip())

        # Применение конвертации для массивов
        conversion = mapping.get('conversion')
        if conversion == 'semicolon_join' and values:
            # Удаляем дубликаты с сохранением порядка, затем разворачиваем
            # (записи в XML идут от новых к старым, нужен хронологический порядок)
            unique_values = list(dict.fromkeys(values))  # Удаление дубликатов с сохранением порядка
            unique_values.reverse()  # Разворачиваем: от новых→старым → от старых→новым
            return "; ".join(unique_values)

        elif conversion == 'document_concat' and alternatives:
            # Специальная обработка для документов-оснований (underlying_document)
            # alternatives = ["document_name", "document_number", "document_date"]
            documents = []
            for elem in xml_element.findall(xml_xpath_root):
                # Собираем все три поля из каждого underlying_document
                doc_parts = {}
                for xpath in alternatives:
                    if not xpath or xpath in ('-', 'null', ''):
                        continue
                    value = elem.findtext(xpath)
                    if value and value.strip():
                        # Определяем тип поля по ключевым словам в XPath
                        xpath_lower = xpath.lower()
                        if 'name' in xpath_lower and 'number' not in xpath_lower:
                            doc_parts['name'] = value.strip()
                        elif 'number' in xpath_lower:
                            doc_parts['number'] = value.strip()
                        elif 'date' in xpath_lower:
                            doc_parts['date'] = value.strip()

                # Формируем строку документа: "Наименование №Номер от Дата"
                if doc_parts:
                    doc_str = doc_parts.get('name', '')
                    if doc_parts.get('number'):
                        doc_str += f" №{doc_parts['number']}"
                    if doc_parts.get('date'):
                        doc_str += f" от {doc_parts['date']}"
                    if doc_str.strip():
                        documents.append(doc_str.strip())

            if documents:
                # Удаляем дубликаты и сортируем
                unique_docs = sorted(list(set(documents)))
                return "; ".join(unique_docs)

        return None

    def _extract_alternative_value(self, xml_element, mapping: Dict, alternatives: Optional[List[str]] = None) -> Any:
        """
        Извлечь значение используя альтернативные XPath

        Применяется для полей с разными путями (физлицо/юрлицо/неопределено)

        Args:
            xml_element: XML элемент
            mapping: Маппинг поля
            alternatives: Список альтернативных XPath (опционально)

        Returns:
            Первое найденное непустое значение
        """
        # Если альтернативы не переданы, парсим их
        if alternatives is None:
            alternatives = self._parse_xpath_alternatives(mapping) or []

        for xpath in alternatives:
            if not xpath or xpath in ('-', 'null', ''):
                continue

            value = xml_element.findtext(xpath)
            if value and value.strip():
                return self._convert_value(value, mapping)

        return None

    def _convert_value(self, value: Any, mapping: Dict) -> Any:
        """
        Конвертация значения согласно типу данных и правилам конвертации

        Поддерживаемые конвертации:
        - comma_to_dot: "1234,56" → 1234.56 (для Real)
        - iso_date_truncate: "2024-11-16T10:30:00" → "2024-11-16" (для Date)
        - null: без конвертации

        Args:
            value: Исходное значение
            mapping: Маппинг поля

        Returns:
            Сконвертированное значение с fallback к строке при ошибках
        """
        # Пустое значение
        if value is None or str(value).strip() == '':
            return None

        conversion = mapping.get('conversion')
        data_type = mapping.get('data_type')

        try:
            # Конвертация comma_to_dot для Real
            if conversion == 'comma_to_dot' and data_type == 'Real':
                return float(str(value).replace(',', '.'))

            # Конвертация iso_date_truncate для Date
            elif conversion == 'iso_date_truncate' and data_type == 'Date':
                # "2024-11-16T10:30:00+04:00" → "2024-11-16"
                date_str = str(value).split('T')[0]
                return date_str

            # Конвертация для Integer
            elif data_type == 'Integer':
                # Обрабатываем "123.0" string → 123
                return int(float(str(value)))

            # Конвертация для Real (без comma_to_dot)
            elif data_type == 'Real':
                return float(str(value))

            # Без конвертации (String или null)
            else:
                return str(value)

        except (ValueError, TypeError) as e:
            # Fallback к строке при ошибках конвертации
            log_warning(f"Msm_4_17 (_convert_value): Ошибка конвертации значения '{value}' для поля '{mapping.get('working_name')}': {e}")
            return str(value) if value else None

    def create_qgs_field(self, mapping: Dict) -> QgsField:
        """
        Создать QgsField из маппинга

        Args:
            mapping: Маппинг поля

        Returns:
            QgsField с правильным типом и длиной
        """
        working_name = mapping.get('working_name', 'unknown')
        data_type = mapping.get('data_type', 'String')

        # Конвертация типа
        if data_type == 'String':
            return QgsField(working_name, QMetaType.Type.QString, len=MAX_FIELD_LEN)

        elif data_type == 'Integer':
            return QgsField(working_name, QMetaType.Type.Int)

        elif data_type == 'Real':
            return QgsField(working_name, QMetaType.Type.Double)

        elif data_type == 'Date':
            return QgsField(working_name, QMetaType.Type.QDate)

        else:
            # Fallback к String с максимальной длиной
            log_warning(f"Msm_4_17 (create_qgs_field): Неизвестный тип данных '{data_type}' для поля '{working_name}', используется String")
            return QgsField(working_name, QMetaType.Type.QString, len=MAX_FIELD_LEN)

    def create_fields_for_record_type(self, record_type: str):
        """
        Создать все QgsField для указанного типа записи

        Args:
            record_type: Тип записи (land_record, unified_land_record, build_record)

        Returns:
            Список QgsField
        """
        from qgis.core import QgsFields

        fields = QgsFields()
        field_mappings = self.get_fields_for_record_type(record_type)

        for mapping in field_mappings:
            field = self.create_qgs_field(mapping)
            fields.append(field)

        return fields
