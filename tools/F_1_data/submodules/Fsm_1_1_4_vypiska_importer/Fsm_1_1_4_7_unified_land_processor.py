# -*- coding: utf-8 -*-
"""
Fsm_1_1_4_7 - Процессор ЕЗ (Единое землепользование)

Специализированная обработка выписок ЕГРН для объектов типа "Единое землепользование" (subtype.code='02').

НАЗНАЧЕНИЕ:
ЕЗ - устаревший формат, содержащий обособленные/условные участки.
Структура может сильно различаться между выписками (от 2 до 500+ обособленных участков).

АРХИТЕКТУРА:
ЕЗ состоит из ТРЁХ типов объектов:
1. Основной объект ЕЗ (кадастровый номер ЕЗ) → record_type='unified_land_record'
   - БЕЗ геометрии (геометрия в обособленных участках)
   - Все атрибуты (права, собственники, обременения)
   - Слой: Le_1_6_3_3_Выписки_ЕЗ_not
2. Части ЗУ (object_parts) → record_type='object_part'
   - Элементы <object_part part_number="N">
   - Каждая часть имеет свою геометрию
   - Слой: Le_1_6_4_2_Выписки_чзу_poly (или _1_line)
3. Обособленные участки (common_land) → record_type='unified_land_record'
   - Перечислены в <common_land><included_cad_numbers>
   - Геометрия в <contours_location><contour cad_number="...">
   - Атрибуты копируются из родительского ЕЗ (кроме Площади - берётся из WFS)
   - Поле КН_родителя = КН основного ЕЗ
   - Слой: Le_1_6_3_2_Выписки_ЕЗ_poly

КРИТИЧЕСКИЕ ФИКСЫ:
- FIX (2025-11-19): Создан отдельный процессор для ЕЗ
  * Изоляция сложной логики от основного импортера
  * Поддержка вариативной структуры ЕЗ
  * Корректная обработка обособленных участков
- FIX (2025-12-17): Исправлена маршрутизация слоёв
  * Обособленные участки → Le_1_6_3_2 (не Le_1_6_1_1)
  * Части ЗУ → Le_1_6_4_* (было conditional_parcel без маппинга)
  * Копирование атрибутов из родительского ЕЗ
"""

from typing import Dict, List, Optional, Any
from xml.etree.ElementTree import Element
from qgis.core import QgsGeometry, QgsVectorLayer

from Daman_QGIS.utils import log_info, log_warning, log_debug

# Слои с данными ЗУ (содержат площадь из Росреестра)
# Приоритет: 1) WFS слой (основной источник), 2) Выписки ЗУ (дополнение)
AREA_SOURCE_LAYERS = [
    'L_1_2_1_WFS_ЗУ',              # WFS слой - основной источник площадей
    'Le_1_6_1_1_Выписки_ЗУ_poly',  # Слой выписок - дополнение если нет в WFS
]


class Fsm_1_1_4_7_UnifiedLandProcessor:
    """Процессор для обработки ЕЗ (Единое землепользование)

    Обрабатывает выписки ЕГРН с subtype.code='02' (Единое землепользование).
    Разделяет ЕЗ на три типа объектов:
    - Основной объект ЕЗ
    - Части ЕЗ (object_parts)
    - Обособленные/условные участки (common_land)
    """

    def __init__(self, main_record: Element, extract_geometry_func, extract_attributes_func,
                 gpkg_path: str = None):
        """Инициализация процессора ЕЗ

        Args:
            main_record: XML элемент <land_record> для ЕЗ
            extract_geometry_func: Функция extract_geometry из Fsm_1_1_4_3_geometry
            extract_attributes_func: Функция для извлечения атрибутов (callback из основного импортера)
            gpkg_path: Путь к GPKG для поиска существующих данных (площадь из WFS)
        """
        self.main_record = main_record
        self.extract_geometry_func = extract_geometry_func
        self.extract_attributes_func = extract_attributes_func
        self.gpkg_path = gpkg_path

        # Кэш для оптимизации
        self._cad_number = None
        self._common_land_cad_numbers = None
        self._parent_ez_attributes = None  # Атрибуты родительского ЕЗ для копирования
        self._wfs_area_cache = None  # Кэш площадей из WFS слоя

    def process(self) -> List[Dict[str, Any]]:
        """Обработка ЕЗ - создание всех features в едином формате

        Returns:
            List[Dict]: Список словарей с ключами:
                - 'record_type': тип записи ('unified_land_record', 'object_part')
                - 'geometry': QgsGeometry или None
                - остальные атрибуты (КН, площадь и т.д.)
        """
        features = []

        # Получаем кадастровый номер ЕЗ
        self._cad_number = self.main_record.findtext('.//common_data/cad_number')
        if not self._cad_number:
            log_warning("Fsm_1_1_4_7: ЕЗ без кадастрового номера - пропускаем")
            return features

        log_info(f"Fsm_1_1_4_7: Обработка ЕЗ {self._cad_number}")

        # FIX (2025-12-17): Извлекаем атрибуты родительского ЕЗ для копирования в дочерние участки
        # Проблема: обособленные участки создавались без прав/собственников/обременений
        # Решение: копируем эти поля из родительского ЕЗ (кроме Площади и ВРИ)
        self._parent_ez_attributes = self.extract_attributes_func(self.main_record, 'unified_land_record')
        log_info(f"Fsm_1_1_4_7: Извлечено {len(self._parent_ez_attributes)} атрибутов родительского ЕЗ")

        # 1. Обособленные участки (ПРИОРИТЕТ - обрабатываем ПЕРВЫМИ)
        segregated_parcels = self._process_segregated_parcels()
        features.extend(segregated_parcels)
        log_info(f"Fsm_1_1_4_7: Создано {len(segregated_parcels)} обособленных участков")

        # 2. Части ЕЗ (object_parts)
        conditional_parcels = self._process_object_parts()
        features.extend(conditional_parcels)
        log_info(f"Fsm_1_1_4_7: Создано {len(conditional_parcels)} частей ЕЗ")

        # 3. Основной объект ЕЗ (БЕЗ геометрии - геометрия в обособленных участках)
        main_ez_feature = self._create_main_ez_feature()
        if main_ez_feature:
            features.insert(0, main_ez_feature)
            log_info(f"Fsm_1_1_4_7: Создан основной объект ЕЗ {self._cad_number}")

        return features

    def _process_segregated_parcels(self) -> List[Dict[str, Any]]:
        """Обработка обособленных/условных участков из common_land

        АЛГОРИТМ:
        1. Найти <common_land><common_land_parts><included_cad_numbers>
        2. Для каждого <included_cad_number> найти соответствующий <contour> в <contours_location>
        3. Создать feature dict с record_type='unified_land_record' → Le_1_6_3_2_Выписки_ЕЗ_poly
        4. Извлечь геометрию из <contour>
        5. Скопировать атрибуты из родительского ЕЗ (кроме Площади - берётся из WFS)

        Returns:
            List[Dict]: Список словарей с данными обособленных участков
        """
        features = []

        # Шаг 1: Получить список кадастровых номеров обособленных участков
        cad_numbers = self._get_common_land_cad_numbers()
        if not cad_numbers:
            log_debug("Fsm_1_1_4_7: Нет обособленных участков в common_land")
            return features

        log_debug(f"Fsm_1_1_4_7: Найдено {len(cad_numbers)} кадастровых номеров в common_land")

        # Шаг 2: Найти contours_location
        contours_location = self.main_record.find('contours_location/contours')
        if contours_location is None:
            log_warning(f"Fsm_1_1_4_7: ЕЗ {self._cad_number} - нет contours_location, обособленные участки без геометрии")
            return features

        # Шаг 3: Для каждого кадастрового номера найти контур
        for cad_number in cad_numbers:
            feature_dict = self._create_segregated_parcel_feature(cad_number, contours_location)
            if feature_dict:
                features.append(feature_dict)

        return features

    def _create_segregated_parcel_feature(self, cad_number: str, contours_location: Element) -> Optional[Dict[str, Any]]:
        """Создание feature dict для обособленного участка

        Args:
            cad_number: Кадастровый номер обособленного участка
            contours_location: XML элемент <contours_location><contours>

        Returns:
            Dict с атрибутами или None если контур не найден
        """
        # Найти контур с данным кадастровым номером
        contour = None
        for c in contours_location.findall('contour'):
            contour_cad = c.findtext('cad_number')
            if contour_cad == cad_number:
                contour = c
                break

        if contour is None:
            log_warning(f"Fsm_1_1_4_7: Контур для обособленного участка {cad_number} не найден")
            return None

        # Извлечь геометрию
        geometries_dict = self.extract_geometry_func(contour)
        if not geometries_dict:
            log_warning(f"Fsm_1_1_4_7: Не удалось извлечь геометрию для {cad_number}")
            return None

        # Выбрать геометрию (приоритет: MultiPolygonM > MultiLineStringM > MultiPointM)
        # FIX: Обновлены ключи для поддержки M-координат (delta_geopoint)
        geometry = None
        if 'MultiPolygonM' in geometries_dict:
            geometry = geometries_dict['MultiPolygonM']
        elif 'MultiLineStringM' in geometries_dict:
            geometry = geometries_dict['MultiLineStringM']
        elif 'MultiPointM' in geometries_dict:
            geometry = geometries_dict['MultiPointM']

        if not geometry or geometry.isNull():
            log_warning(f"Fsm_1_1_4_7: Пустая геометрия для {cad_number}")
            return None

        # Создать feature dict в формате основного импортера
        # FIX (2025-12-17): record_type='unified_land_record' чтобы обособленные участки
        # попадали в Le_1_6_3_2_Выписки_ЕЗ_poly, а не в Le_1_6_1_1_Выписки_ЗУ_poly
        feature_dict = {
            'record_type': 'unified_land_record',  # Обособленный участок ЕЗ → Le_1_6_3_*
            'geometry': geometry,
            'КН': cad_number,  # Основной атрибут
            'КН_родителя': self._cad_number,  # Связь с основным ЕЗ (поле из Base_field_mapping_EGRN.json)
            'ЕЗ': self._cad_number  # FIX (2025-12-17): КН родительского ЕЗ для выборки (Base_selection_ZU.json)
        }

        # FIX (2025-12-17): Копируем атрибуты из родительского ЕЗ
        # Права, собственники, обременения, арендаторы - общие для всего ЕЗ
        # FIX (2025-12-18): Добавлен Тип_объекта - общий для всего ЕЗ
        # Площадь: приоритет у WFS, но если нет - копируем из родителя как fallback
        COPY_FROM_PARENT_FIELDS = [
            'Адрес_Местоположения',
            'Категория',
            'ВРИ',
            'Тип_объекта',  # FIX (2025-12-18): Добавлено - тип общий для ЕЗ
            'Права',
            'Обременения',
            'Собственники',
            'Арендаторы',
            'Статус',
        ]

        if self._parent_ez_attributes:
            copied_fields = []
            for field_name in COPY_FROM_PARENT_FIELDS:
                parent_value = self._parent_ez_attributes.get(field_name)
                # Копируем только если значение не пустое
                if parent_value is not None and parent_value != '' and parent_value != '-':
                    feature_dict[field_name] = parent_value
                    copied_fields.append(field_name)

            if copied_fields:
                log_debug(f"Fsm_1_1_4_7: Скопированы поля из ЕЗ в {cad_number}: {', '.join(copied_fields)}")

        # FIX (2025-12-18): Извлекаем площадь из нескольких источников
        # Приоритет: 1) XML контур (area/value), 2) WFS кэш, 3) special_notes
        area_value = None
        area_source = None

        # 1. XML контур (area/value)
        contour_area = contour.findtext('area/value')
        if contour_area:
            area_value = contour_area.replace(',', '.')
            area_source = 'XML контур'

        # 2. WFS кэш (если нет в XML)
        if not area_value:
            wfs_cache = self._load_wfs_area_cache()
            if cad_number in wfs_cache:
                area_value = str(wfs_cache[cad_number])
                area_source = 'WFS кэш'

        # 3. special_notes (последний fallback)
        if not area_value:
            special_notes_areas = self._parse_areas_from_special_notes()
            if cad_number in special_notes_areas:
                area_value = special_notes_areas[cad_number]
                area_source = 'special_notes'

        if area_value:
            feature_dict['Площадь'] = area_value
            log_debug(f"Fsm_1_1_4_7: Площадь для {cad_number} из {area_source}: {area_value}")

        log_debug(f"Fsm_1_1_4_7: Создан обособленный участок {cad_number} (geom_type={geometry.type()})")
        return feature_dict

    def _process_object_parts(self) -> List[Dict[str, Any]]:
        """Обработка частей ЕЗ (object_parts)

        ДЕЛЕГИРОВАНИЕ: Части ЕЗ обрабатываются аналогично обычным выпискам.
        Логика взята из основного импортера (строки 344-401).

        Returns:
            List[Dict]: Список словарей с данными частей ЕЗ
        """
        features = []

        object_parts = self.main_record.findall('.//object_parts/object_part')
        if not object_parts:
            log_debug("Fsm_1_1_4_7: Нет object_parts")
            return features

        log_debug(f"Fsm_1_1_4_7: Найдено {len(object_parts)} object_parts")

        for object_part in object_parts:
            part_number = object_part.findtext('part_number')
            if not part_number:
                log_warning("Fsm_1_1_4_7: object_part без part_number - пропускаем")
                continue

            # Извлечь геометрию из object_part
            contours = object_part.find('contours')
            if contours is None:
                log_warning(f"Fsm_1_1_4_7: object_part {part_number} без геометрии - пропускаем")
                continue

            geometries_dict = self.extract_geometry_func(contours)
            if not geometries_dict:
                log_warning(f"Fsm_1_1_4_7: Не удалось извлечь геометрию для part {part_number}")
                continue

            # Выбрать геометрию (приоритет: MultiPolygonM > MultiLineStringM > MultiPointM)
            # FIX: Обновлены ключи для поддержки M-координат (delta_geopoint)
            geometry = None
            if 'MultiPolygonM' in geometries_dict:
                geometry = geometries_dict['MultiPolygonM']
            elif 'MultiLineStringM' in geometries_dict:
                geometry = geometries_dict['MultiLineStringM']
            elif 'MultiPointM' in geometries_dict:
                geometry = geometries_dict['MultiPointM']

            if not geometry or geometry.isNull():
                log_warning(f"Fsm_1_1_4_7: Пустая геометрия для part {part_number}")
                continue

            # Создать feature dict
            # FIX (2025-12-17): record_type='object_part' чтобы части ЗУ попадали в Le_1_6_4_*
            # (было 'conditional_parcel' которого нет в маппинге RECORD_TO_BASE_SUBLAYER)

            # FIX (2025-12-18): Использовать FieldMappingManager для извлечения ВСЕХ атрибутов
            # Было: ручное извлечение только 3 полей (Номер_части, КН_родителя, Площадь)
            # Стало: автоматическое извлечение всех полей для record_type='object_part'
            feature_dict = self.extract_attributes_func(object_part, 'object_part')

            # Обязательные поля (перезаписываем на случай если не извлеклись)
            feature_dict['record_type'] = 'object_part'  # Часть ЗУ → Le_1_6_4_*
            feature_dict['geometry'] = geometry
            feature_dict['Номер_части'] = part_number
            feature_dict['КН_родителя'] = self._cad_number

            features.append(feature_dict)
            log_debug(f"Fsm_1_1_4_7: Создана часть {part_number} с {len(feature_dict)} атрибутами")

        return features

    def _create_main_ez_feature(self) -> Optional[Dict[str, Any]]:
        """Создание основного объекта ЕЗ

        СТРАТЕГИЯ: Основной ЕЗ БЕЗ геометрии.
        Геометрия находится в обособленных участках и частях.
        Атрибуты извлекаются из main_record через FieldMappingManager.

        Returns:
            Dict с атрибутами или None
        """
        # Используем уже закэшированные атрибуты (извлечены в process())
        # Создаём копию чтобы не мутировать кэш
        attributes = dict(self._parent_ez_attributes) if self._parent_ez_attributes else {}

        # КРИТИЧНО: Переопределить геометрию и record_type
        attributes['geometry'] = None  # БЕЗ геометрии
        attributes['record_type'] = 'unified_land_record'  # Основной ЕЗ
        attributes['Это_ЕЗ'] = True  # Флаг ЕЗ

        # КН должен быть извлечен через атрибуты, но проверим
        if attributes.get('КН') != self._cad_number:
            log_warning(f"Fsm_1_1_4_7: Несоответствие КН: {attributes.get('КН')} != {self._cad_number}")
            attributes['КН'] = self._cad_number

        log_debug(f"Fsm_1_1_4_7: Создан основной ЕЗ {self._cad_number} с {len(attributes)} атрибутами")
        return attributes

    def _get_common_land_cad_numbers(self) -> List[str]:
        """Получение списка кадастровых номеров обособленных участков

        Returns:
            List[str]: Список кадастровых номеров из <common_land>
        """
        if self._common_land_cad_numbers is not None:
            return self._common_land_cad_numbers

        cad_numbers = []

        # Найти common_land
        common_land = self.main_record.find('.//common_land/common_land_parts/included_cad_numbers')
        if common_land is None:
            self._common_land_cad_numbers = cad_numbers
            return cad_numbers

        # Извлечь все кадастровые номера
        for included_cad in common_land.findall('included_cad_number/cad_number'):
            cad_number = included_cad.text
            if cad_number:
                cad_numbers.append(cad_number.strip())

        self._common_land_cad_numbers = cad_numbers
        log_debug(f"Fsm_1_1_4_7: Список обособленных участков: {cad_numbers}")
        return cad_numbers

    def _load_wfs_area_cache(self) -> Dict[str, Any]:
        """Загрузка кэша площадей из слоёв с данными ЗУ

        Слои AREA_SOURCE_LAYERS содержат площади из Росреестра.
        Обособленные участки ЕЗ изначально загружаются туда как обычные ЗУ.
        При импорте выписки ЕЗ нужно сохранить эту площадь.

        Приоритет слоёв:
        1. L_1_2_1_WFS_ЗУ - WFS слой (основной источник площадей)
        2. Le_1_6_1_1_Выписки_ЗУ_poly - слой выписок (дополнение если нет в WFS)

        FIX (2025-12-18): Поддержка альтернативных имён полей
        - КН: 'КН', 'cad_num', 'cad_number'
        - Площадь: 'Площадь', 'specified_area', 'area', 'declared_area'

        Returns:
            Dict[str, Any]: Словарь {КН: площадь}
        """
        if self._wfs_area_cache is not None:
            return self._wfs_area_cache

        self._wfs_area_cache = {}

        if not self.gpkg_path:
            log_debug("Fsm_1_1_4_7: gpkg_path не указан, кэш площадей пустой")
            return self._wfs_area_cache

        import os
        if not os.path.exists(self.gpkg_path):
            log_debug(f"Fsm_1_1_4_7: GPKG не найден: {self.gpkg_path}")
            return self._wfs_area_cache

        # FIX (2025-12-18): Альтернативные имена полей для WFS слоёв
        CAD_NUM_FIELDS = ['КН', 'cad_num', 'cad_number']
        AREA_FIELDS = ['Площадь', 'specified_area', 'area', 'declared_area']

        # Пробуем загрузить площади из каждого слоя по приоритету
        for layer_name in AREA_SOURCE_LAYERS:
            layer = QgsVectorLayer(
                f"{self.gpkg_path}|layername={layer_name}",
                layer_name,
                "ogr"
            )

            if not layer.isValid():
                log_debug(f"Fsm_1_1_4_7: Слой {layer_name} не найден в GPKG")
                continue

            # FIX (2025-12-18): Ищем альтернативные имена полей
            field_names = [f.name() for f in layer.fields()]

            cad_field = None
            for f in CAD_NUM_FIELDS:
                if f in field_names:
                    cad_field = f
                    break

            area_field = None
            for f in AREA_FIELDS:
                if f in field_names:
                    area_field = f
                    break

            if not cad_field or not area_field:
                log_debug(f"Fsm_1_1_4_7: Слой {layer_name} не содержит полей КН или Площадь "
                         f"(проверены: {CAD_NUM_FIELDS}, {AREA_FIELDS})")
                continue

            log_debug(f"Fsm_1_1_4_7: Слой {layer_name} использует поля: {cad_field}, {area_field}")

            # Загружаем площади из этого слоя (добавляем только отсутствующие)
            added_count = 0
            for feat in layer.getFeatures():
                cad_num = feat.attribute(cad_field)
                area = feat.attribute(area_field)

                if cad_num and area is not None and area != '' and area != '-':
                    cad_num_str = str(cad_num)
                    # Не перезаписываем если уже есть (приоритет у первого слоя)
                    if cad_num_str not in self._wfs_area_cache:
                        self._wfs_area_cache[cad_num_str] = area
                        added_count += 1

            if added_count > 0:
                log_info(f"Fsm_1_1_4_7: Загружено {added_count} площадей из слоя {layer_name}")

        if self._wfs_area_cache:
            log_info(f"Fsm_1_1_4_7: Итого в кэше {len(self._wfs_area_cache)} площадей")

        return self._wfs_area_cache

    def _parse_areas_from_special_notes(self) -> Dict[str, str]:
        """Парсинг площадей обособленных участков из special_notes

        FIX (2025-12-18): В XML выписки ЕЗ площади обособленных участков указаны
        ТОЛЬКО в special_notes текстом, например:
        "Кадастровые номера обособленных (условных) участков, входящих в единое
        землепользование и их площади: 07:11:1500000:11 - 1999.7 кв.м,
        07:11:1500000:12 - 500.24 кв.м."

        Returns:
            Dict[str, str]: Словарь {КН: площадь}
        """
        import re

        areas = {}
        special_notes = self.main_record.findtext('.//special_notes')
        if not special_notes:
            return areas

        # Regex для поиска: КН - площадь кв.м
        # Формат КН: NN:NN:NNNNNNN:NN (с вариациями количества цифр)
        pattern = r'(\d{2}:\d{2}:\d+:\d+)\s*[-–]\s*([\d.,]+)\s*кв\.?\s*м'
        matches = re.findall(pattern, special_notes)

        for cad_num, area in matches:
            # Нормализуем площадь: запятая → точка
            area_normalized = area.replace(',', '.')
            areas[cad_num] = area_normalized
            log_debug(f"Fsm_1_1_4_7: Площадь из special_notes: {cad_num} = {area_normalized}")

        if areas:
            log_info(f"Fsm_1_1_4_7: Извлечено {len(areas)} площадей из special_notes")

        return areas
