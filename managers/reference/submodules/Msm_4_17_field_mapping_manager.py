# -*- coding: utf-8 -*-
"""
Msm_4_17_FieldMappingManager - Менеджер маппинга полей выписок ЕГРН

Загрузка и управление маппингом XML XPath → рабочие поля для импорта выписок.
Поддержка альтернативных путей (физлицо/юрлицо), массивов, конвертации типов.

Детектор непокрытых веток холдера: при массивном извлечении по контейнеру
правообладателей холдер, чью ветку не покрывает ни один xpath маппинга, молча
выпадает из значения поля. Детектор делает потерю видимой в логе (пофайловое
предупреждение + сводка за прогон), извлекаемые значения не меняет.
Спецификация: documentation/plans/PLAN_rights_3axis_I5_branch_coverage_detector_2026-07-27.md
"""

from typing import List, Dict, Optional, Any, Set
from qgis.core import QgsField
from qgis.PyQt.QtCore import QMetaType, QDate
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
from Daman_QGIS.utils import log_error, log_info, log_warning
from Daman_QGIS.constants import MAX_FIELD_LEN

# ДЕТЕКТОР НЕПОКРЫТЫХ ВЕТОК ХОЛДЕРА
#
# Суффикс xml_xpath_root, по которому распознаётся массивное извлечение по
# контейнеру правообладателей. Признак СТРУКТУРНЫЙ - берётся из данных маппинга
# (xml_xpath_root), а не из имён полей: сейчас суффиксу отвечают «Собственники»
# (right_records/right_record/right_holders/right_holder) и «Арендаторы»
# (restrict_records/restrict_record/right_holders/right_holder); новое поле по
# тому же контейнеру попадёт под детектор без правки кода.
HOLDER_CONTAINER_SUFFIX = 'right_holders/right_holder'

# Максимальная глубина метки ветки холдера. XSD tRightHolderOut = xsd:choice
# { public_formation | individual | legal_entity | another }, где ветки-обёртки
# несут дискриминатор типа на третьем уровне: another/another_type/<тип>,
# legal_entity/entity/<тип>, public_formation/public_formation_type/<тип>.
# Прямые ветки (individual, undefined) остаются одноуровневыми.
BRANCH_LABEL_MAX_DEPTH = 3

# Подстановка идентификатора объекта, если вызывающий не передал КН в context
UNKNOWN_OBJECT_ID = 'КН не определён'

# Метка холдера без единого дочернего элемента (пустой <right_holder/>)
EMPTY_BRANCH_LABEL = 'ветка отсутствует'


def _element_children(element) -> List:
    """
    Дочерние ЭЛЕМЕНТЫ узла (без комментариев и processing instructions)

    У comment/PI-узлов ElementTree tag - функция, а не строка; попадание такого
    узла в метку ветки дало бы нечитаемый мусор вместо имени тега.

    Args:
        element: XML элемент

    Returns:
        Список дочерних элементов с текстовым тегом
    """
    return [child for child in element if isinstance(child.tag, str)]


class FieldMappingManager(BaseReferenceLoader):
    """
    Менеджер маппинга полей выписок ЕГРН (XML XPath → рабочие поля)

    ZERO HARDCODE PRINCIPLE: Все маппинги загружаются из Base_field_mapping_EGRN.json
    """

    FIELD_MAPPING_FILE = 'Base_field_mapping_EGRN.json'

    def __init__(self):
        """Инициализация менеджера."""
        super().__init__()
        self._mappings = None
        self._by_record_type = {}
        self._by_working_name = {}

        # Агрегат детектора непокрытых веток холдера за прогон импорта.
        # {метка ветки: {'holders': int, 'objects': set(КН)}}
        self._uncovered_branches: Dict[str, Dict[str, Any]] = {}
        self._checked_holders: int = 0
        self._checked_objects: Set[str] = set()

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

    @staticmethod
    def _findtext_composite(xml_element, xpath: str) -> Optional[str]:
        """
        Извлечь значение по одиночному или композитному XPath

        Композитный XPath: "pathA+pathB+pathC" — под-значения извлекаются
        по порядку, непустые соединяются пробелом. Применяется для сборки
        ФИО физлица из individual/surname+individual/name+individual/patronymic
        («Капкин Дмитрий Сергеевич» вместо потери фамилии/отчества при
        одиночном individual/name — дефект, найденный владельцем 2026-07-17).
        Символ "+" в тегах XML-схем ЕГРН не встречается — разделитель безопасен.

        Args:
            xml_element: XML элемент
            xpath: Одиночный ("a/b") или композитный ("a/b+a/c") XPath

        Returns:
            Значение (для композита — собранное через пробел) или None
        """
        if '+' not in xpath:
            return xml_element.findtext(xpath)

        parts = []
        for sub_xpath in xpath.split('+'):
            sub_xpath = sub_xpath.strip()
            if not sub_xpath:
                continue
            value = xml_element.findtext(sub_xpath)
            if value and value.strip():
                parts.append(value.strip())

        return ' '.join(parts) if parts else None

    def extract_value(self, xml_element, mapping: Dict, context: Optional[Dict[str, Any]] = None) -> Any:
        """
        Извлечь значение из XML элемента согласно маппингу

        Поддерживает:
        - Простой XPath: xml_xpath
        - Массивы: xml_xpath_root + xml_xpath
        - Альтернативные пути: xml_xpath_alternatives ИЛИ xml_xpath с ";"

        Args:
            xml_element: XML элемент (lxml или ElementTree)
            mapping: Маппинг поля
            context: Контекст вызова для диагностики (ключ 'cad_number' - КН
                     объекта, к которому относится элемент). На извлекаемое
                     значение НЕ влияет, используется только детектором
                     непокрытых веток холдера

        Returns:
            Извлечённое и сконвертированное значение
        """
        # CASE 1: Массив (xml_xpath_root указан)
        if mapping.get('xml_xpath_root') and mapping['xml_xpath_root'] not in ('-', 'null', ''):
            return self._extract_array_value(xml_element, mapping, context)

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

    def _extract_array_value(self, xml_element, mapping: Dict,
                             context: Optional[Dict[str, Any]] = None) -> Any:
        """
        Извлечь множественные значения из XML (массив)

        Args:
            xml_element: XML элемент
            mapping: Маппинг поля
            context: Контекст вызова для детектора непокрытых веток холдера

        Returns:
            Объединённая строка значений через "; " или None
        """
        xml_xpath_root = mapping.get('xml_xpath_root')
        if not xml_xpath_root:
            return None

        # Парсим альтернативные XPath (из xml_xpath_alternatives ИЛИ из xml_xpath с ";")
        alternatives = self._parse_xpath_alternatives(mapping)

        values = []
        # Элементы контейнера, не давшие значения НИ ПО ОДНОМУ xpath маппинга.
        # Наблюдение для детектора - на values не влияет.
        uncovered_elements = []
        elements = xml_element.findall(xml_xpath_root)

        # Итерация по корневому контейнеру (например, right_records/right_record)
        for elem in elements:
            matched = False

            # ПОДДЕРЖКА АЛЬТЕРНАТИВНЫХ XPATH (для физлиц/юрлиц/муниципалитетов)
            if alternatives:
                # Пробуем каждый XPath по порядку (одиночный или композитный "a+b+c")
                for alt_xpath in alternatives:
                    if not alt_xpath or alt_xpath in ('-', 'null', ''):
                        continue
                    value = self._findtext_composite(elem, alt_xpath)
                    if value and value.strip():
                        values.append(value.strip())
                        matched = True
                        break  # Нашли значение - переходим к следующему элементу
            # Обычный XPath (без альтернатив и без ";")
            else:
                xml_xpath = mapping.get('xml_xpath')
                if xml_xpath and xml_xpath not in ('-', 'null', ''):
                    value = elem.findtext(xml_xpath)
                    if value and value.strip():
                        values.append(value.strip())
                        matched = True

            if not matched:
                uncovered_elements.append(elem)

        # ДЕТЕКТОР непокрытых веток холдера: расхождение между числом элементов
        # контейнера и числом извлечённых значений становится видимым в логе.
        # Значения полей не меняет - только наблюдает.
        if self._is_holder_container(xml_xpath_root):
            self._register_holder_coverage(elements, uncovered_elements, mapping, context)

        # Применение конвертации для массивов
        conversion = mapping.get('conversion')
        if conversion == 'semicolon_join' and values:
            # RAW IMPORT: сохраняем ВСЕ значения в порядке XML
            # БЕЗ дедупликации - позиционное соответствие между полями критично
            # (Обременения[i] ↔ Арендаторы[i])
            return "; ".join(values)

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
                # RAW IMPORT: сохраняем ВСЕ документы в порядке XML
                # БЕЗ дедупликации - позиционное соответствие с обременениями
                return "; ".join(documents)

        return None

    @staticmethod
    def _is_holder_container(xml_xpath_root: str) -> bool:
        """
        Проверка: корень маппинга указывает на контейнер правообладателей

        Признак структурный (суффикс xml_xpath_root), не по имени поля.

        Args:
            xml_xpath_root: Корневой XPath из маппинга

        Returns:
            True для полей с массивным извлечением по контейнеру холдеров
        """
        return xml_xpath_root.rstrip('/').endswith(HOLDER_CONTAINER_SUFFIX)

    @staticmethod
    def _holder_branch_label(holder_element) -> str:
        """
        Определить фактическую ветку одного правообладателя

        Спуск по первому дочернему элементу, пока следующий уровень остаётся
        контейнером (у него есть собственные дочерние элементы), но не глубже
        BRANCH_LABEL_MAX_DEPTH. Тег-обёртка (legal_entity, public_formation,
        another) содержит контейнер-дискриминатор, за которым идёт тип; прямая
        ветка (individual, undefined) сразу упирается в лист со значением и
        остаётся одноуровневой.

        Args:
            holder_element: XML элемент <right_holder>

        Returns:
            Метка ветки, например "legal_entity/entity/government_entity",
            "public_formation/public_formation_type/russia", "individual"
        """
        children = _element_children(holder_element)
        if not children:
            return EMPTY_BRANCH_LABEL

        node = children[0]
        parts = [node.tag]

        while len(parts) < BRANCH_LABEL_MAX_DEPTH:
            node_children = _element_children(node)
            if not node_children:
                break
            first_child = node_children[0]
            if not _element_children(first_child):
                # Первый потомок - лист со значением: текущий узел и есть тип
                break
            node = first_child
            parts.append(node.tag)

        return '/'.join(parts)

    def _register_holder_coverage(self, elements: List, uncovered_elements: List,
                                  mapping: Dict, context: Optional[Dict[str, Any]]) -> None:
        """
        Учесть покрытие холдеров и предупредить о непокрытых ветках

        Наблюдение: значения поля не меняются, подстановок нет. Непокрытый
        холдер - тот, для которого не сработал ни один xpath маппинга; без
        предупреждения его потеря неотличима от честного отсутствия сведений.

        Args:
            elements: Все элементы контейнера холдеров
            uncovered_elements: Элементы, не давшие значения ни по одному xpath
            mapping: Маппинг поля
            context: Контекст вызова (ключ 'cad_number')
        """
        cad_number = context.get('cad_number') if context else None
        object_id = str(cad_number).strip() if cad_number else UNKNOWN_OBJECT_ID

        if elements:
            self._checked_holders += len(elements)
            self._checked_objects.add(object_id)

        if not uncovered_elements:
            return

        branch_counts: Dict[str, int] = {}
        for elem in uncovered_elements:
            label = self._holder_branch_label(elem)
            branch_counts[label] = branch_counts.get(label, 0) + 1

            stats = self._uncovered_branches.setdefault(label, {'holders': 0, 'objects': set()})
            stats['holders'] += 1
            stats['objects'].add(object_id)

        working_name = mapping.get('working_name', 'без имени')
        branches = ', '.join(f"{label} - {count}" for label, count in sorted(branch_counts.items()))
        log_warning(
            f"Msm_4_17 (_register_holder_coverage): Объект {object_id}, поле '{working_name}': "
            f"{len(uncovered_elements)} из {len(elements)} холдеров не покрыты ни одним xpath маппинга. "
            f"Непокрытые ветки: {branches}"
        )

    def reset_uncovered_branch_stats(self) -> None:
        """Сбросить агрегат детектора непокрытых веток холдера (начало прогона)"""
        self._uncovered_branches = {}
        self._checked_holders = 0
        self._checked_objects = set()

    def get_uncovered_branch_stats(self) -> Dict[str, Dict[str, int]]:
        """
        Агрегат детектора за текущий прогон

        Returns:
            {метка ветки: {'holders': число холдеров, 'objects': число объектов}}
        """
        return {
            label: {'holders': stats['holders'], 'objects': len(stats['objects'])}
            for label, stats in self._uncovered_branches.items()
        }

    def log_uncovered_branch_summary(self) -> None:
        """
        Итоговая сводка детектора непокрытых веток холдера за прогон

        Вызывается потребителем на границе прогона (окончание разбора файлов).
        Обе стороны видимы: при пустом агрегате пишется число проверенных
        холдеров - молчание детектора отличимо от его незапуска.
        """
        if not self._checked_holders:
            return

        checked = (f"проверено {self._checked_holders} холдеров "
                   f"в {len(self._checked_objects)} объектах")

        if not self._uncovered_branches:
            log_info(f"Msm_4_17: Непокрытых веток холдеров нет ({checked})")
            return

        log_warning(f"Msm_4_17: Непокрытые ветки холдеров за прогон ({checked}):")
        for label, stats in sorted(self._uncovered_branches.items(),
                                   key=lambda item: (-item[1]['holders'], item[0])):
            log_warning(
                f"Msm_4_17: {label} - {stats['holders']} холдеров "
                f"в {len(stats['objects'])} объектах"
            )

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

            value = self._findtext_composite(xml_element, xpath)
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
