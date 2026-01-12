# -*- coding: utf-8 -*-
"""
Fsm_1_1_4 - Импорт XML выписок ЕГРН (DATABASE-DRIVEN VERSION)

Парсит ВСЕ поля согласно Base_field_mapping_EGRN.json:
- Используется Msm_4_field_mapping_manager для ZERO HARDCODE
- Поддержка всех типов записей: land_record, unified_land_record, build_record
- Автоматическая конвертация типов (comma_to_dot, iso_date_truncate, etc.)
- Поддержка массивов (semicolon_join) и альтернативных XPath

Использует модульную структуру субсубмодулей.
"""

import os
import xml.etree.ElementTree as ET
from typing import Union, List, Dict, Any
from datetime import datetime
from collections import defaultdict

from qgis.core import QgsProject
from qgis.PyQt.QtWidgets import QMessageBox

from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.constants import ROOT_TAG_TO_RECORD_MAP
from ...core import BaseImporter

# Импорт субмодулей
from .Fsm_1_1_4_3_geometry import extract_geometry
from .Fsm_1_1_4_4_layer_creator import create_and_save_layer
from .Fsm_1_1_4_6_layer_splitter import split_and_create_layers
from .Fsm_1_1_4_7_unified_land_processor import Fsm_1_1_4_7_UnifiedLandProcessor


class Fsm_1_1_4_VypiskaImporter(BaseImporter):
    """Импортер XML выписок ЕГРН - database-driven версия с ZERO HARDCODE"""

    def __init__(self, iface):
        """
        Инициализация

        Args:
            iface: QGIS interface
        """
        super().__init__(iface)

        # Инициализация FieldMappingManager для ZERO HARDCODE
        from Daman_QGIS.managers.submodules.Msm_4_17_field_mapping_manager import FieldMappingManager
        from Daman_QGIS.constants import DATA_REFERENCE_PATH
        self.field_mapper = FieldMappingManager(DATA_REFERENCE_PATH)

        # Список пропущенных файлов (для автофильтрации дубликатов)
        self.skipped_info = []

        # Статистика обработки частей (для упрощения логов)
        self.total_parts_count = 0
        self.zu_with_parts_count = 0

    def supports_format(self, file_extension: str) -> bool:
        """Проверка поддержки формата"""
        return file_extension.lower() in ['.xml']

    def import_file(self, file_path: Union[str, List[str]], **kwargs) -> Dict[str, Any]:
        """
        Импорт выписок ЕГРН (интерфейс для BaseImporter)

        Args:
            file_path: Путь к XML файлу или список файлов
            **kwargs: Дополнительные параметры
                - gpkg_path: путь к GPKG
                - split_by_geometry: разделять по типам геометрии (bool)

        Returns:
            Dict с результатами импорта
        """
        # Если передан список файлов
        if isinstance(file_path, list):
            files = file_path
        else:
            files = [file_path]

        # Получаем путь к GPKG из параметров или project_manager
        output_gpkg_path = kwargs.get('gpkg_path')
        if not output_gpkg_path:
            if self.project_manager and hasattr(self.project_manager, 'project_db'):
                output_gpkg_path = self.project_manager.project_db.gpkg_path
            else:
                log_error("Fsm_1_1_4: Не указан путь к GPKG")
                return {
                    'success': False,
                    'layers': [],
                    'message': 'Не указан путь к GPKG',
                    'errors': ['gpkg_path отсутствует']
                }

        # Параметр разделения по геометриям (по умолчанию True - разделение по типам)
        split_by_geometry = kwargs.get('split_by_geometry', True)

        return self._import_vypiska_files(files, output_gpkg_path, split_by_geometry)

    def _import_vypiska_files(self, file_paths: List[str], output_gpkg_path: str,
                              split_by_geometry: bool = False) -> Dict[str, Any]:
        """
        Импорт списка XML файлов выписок в GPKG

        Args:
            file_paths: Список путей к XML файлам
            output_gpkg_path: Путь к выходному GPKG файлу
            split_by_geometry: Разделять по типам геометрии

        Returns:
            Dict с результатами импорта
        """
        if not file_paths:
            log_error("Fsm_1_1_4: Не указаны файлы для импорта")
            return {
                'success': False,
                'layers': [],
                'message': 'Не указаны файлы',
                'errors': []
            }

        log_info(f"Fsm_1_1_4: Начало импорта {len(file_paths)} выписок")

        # Фильтрация дубликатов - оставляем только самые новые версии
        file_paths, self.skipped_info = self._filter_newest_files(file_paths)

        if not file_paths:
            log_error("Fsm_1_1_4: После фильтрации не осталось файлов для импорта")
            return {
                'success': False,
                'layers': [],
                'message': 'Нет файлов после фильтрации',
                'errors': []
            }

        log_info(f"Fsm_1_1_4: После фильтрации: {len(file_paths)} актуальных выписок")

        # Сбрасываем счетчики статистики частей
        self.total_parts_count = 0
        self.zu_with_parts_count = 0

        # Собираем все данные из всех файлов
        all_features = []
        success_count = 0
        error_count = 0
        invalid_geometries = []  # Список КН с невалидными геометриями

        for i, file_path in enumerate(file_paths, 1):
            try:
                features = self._parse_vypiska_xml(file_path, output_gpkg_path)

                if features:
                    all_features.extend(features)
                    success_count += 1
                else:
                    log_warning(f"Fsm_1_1_4: Файл {os.path.basename(file_path)} не содержит данных")
                    error_count += 1

            except Exception as e:
                log_error(f"Fsm_1_1_4: Ошибка парсинга {os.path.basename(file_path)}: {e}")
                import traceback
                log_error(f"Fsm_1_1_4: {traceback.format_exc()}")
                error_count += 1

        if not all_features:
            log_error("Fsm_1_1_4: Не удалось извлечь данные ни из одного файла")
            return {
                'success': False,
                'layers': [],
                'message': 'Не удалось извлечь данные',
                'errors': []
            }

        # Проверяем геометрии на валидность и собираем список невалидных
        for feat_data in all_features:
            geom = feat_data.get('geometry')
            cad_number = feat_data.get('КН', feat_data.get('cad_number', 'UNKNOWN'))

            if geom and not geom.isEmpty():
                if hasattr(geom, 'isGeosValid') and not geom.isGeosValid():
                    invalid_geometries.append(cad_number)

        # Создаем слой и записываем в GPKG
        try:
            # Получаем CRS проекта
            project = QgsProject.instance()
            crs = project.crs() if project else None

            # Определяем преобладающий record_type для создания полей
            record_type_counts = {}
            for feat in all_features:
                rt = feat.get('record_type', 'unknown')
                record_type_counts[rt] = record_type_counts.get(rt, 0) + 1

            # Выбираем самый частый record_type
            dominant_record_type = max(record_type_counts, key=lambda k: record_type_counts[k]) if record_type_counts else 'land_record'
            log_info(f"Fsm_1_1_4: Статистика record_type: {record_type_counts}")
            log_info(f"Fsm_1_1_4: Преобладающий record_type: {dominant_record_type} ({record_type_counts.get(dominant_record_type, 0)} объектов)")

            # Проверяем типы геометрий в данных
            geom_types_present = set()
            for feat in all_features:
                if feat.get('geometry'):
                    geom = feat['geometry']
                    if hasattr(geom, 'type'):
                        geom_type = geom.type()  # QgsWkbTypes.GeometryType: 0=Point, 1=Line, 2=Polygon
                        if geom_type == 2:
                            geom_types_present.add('MultiPolygon')
                        elif geom_type == 1:
                            geom_types_present.add('MultiLineString')
                        elif geom_type == 0:
                            geom_types_present.add('MultiPoint')

            # Логируем информацию о типах геометрий
            if len(geom_types_present) > 1:
                log_info(f"Fsm_1_1_4: Обнаружено {len(geom_types_present)} типов геометрий")
            else:
                log_info(f"Fsm_1_1_4: Обнаружен 1 тип геометрии")

            # Выбираем режим создания слоёв
            if split_by_geometry:
                # Разделяем по типам геометрии (несколько слоёв)
                log_info("Fsm_1_1_4: Режим разделения по типам геометрии")
                result = split_and_create_layers(
                    all_features,
                    output_gpkg_path,
                    crs,
                    field_mapper=self.field_mapper,
                    dominant_record_type=dominant_record_type
                )

                if result.get('success'):
                    log_info(f"Fsm_1_1_4: Импорт завершен. Успешно: {success_count}, Ошибок: {error_count}")
                    if invalid_geometries:
                        log_warning(f"Fsm_1_1_4: Невалидная геометрия у {len(invalid_geometries)} объектов: {', '.join(invalid_geometries[:10])}{' ...' if len(invalid_geometries) > 10 else ''}")

                    # Вывод итоговой статистики частей
                    if self.total_parts_count > 0:
                        log_info(f"Fsm_1_1_4: Обработано {self.total_parts_count} частей для {self.zu_with_parts_count} земельных участков")

                    # Показываем диалог с пропущенными файлами (если есть)
                    self._show_skipped_files_dialog()

                    return result
                else:
                    return result

            else:
                # Один слой для всех объектов
                log_info("Fsm_1_1_4: Режим единого слоя")
                success = create_and_save_layer(
                    all_features,
                    output_gpkg_path,
                    crs,
                    field_mapper=self.field_mapper,
                    record_type=dominant_record_type
                )

                if success:
                    log_info(f"Fsm_1_1_4: Импорт завершен. Успешно: {success_count}, Ошибок: {error_count}")
                    if invalid_geometries:
                        log_warning(f"Fsm_1_1_4: Невалидная геометрия у {len(invalid_geometries)} объектов: {', '.join(invalid_geometries[:10])}{' ...' if len(invalid_geometries) > 10 else ''}")

                    # Вывод итоговой статистики частей
                    if self.total_parts_count > 0:
                        log_info(f"Fsm_1_1_4: Обработано {self.total_parts_count} частей для {self.zu_with_parts_count} земельных участков")

                    # Получаем слой из проекта
                    imported_layer = project.mapLayersByName("ЕГРН_выписки")
                    layer_objects = imported_layer if imported_layer else []

                    # Показываем диалог с пропущенными файлами (если есть)
                    self._show_skipped_files_dialog()

                    return {
                        'success': True,
                        'layers': layer_objects,
                        'message': f'Импортировано: {len(all_features)} объектов',
                        'errors': []
                    }
                else:
                    return {
                        'success': False,
                        'layers': [],
                        'message': 'Ошибка создания слоя',
                        'errors': []
                    }

        except Exception as e:
            log_error(f"Fsm_1_1_4: Ошибка создания слоя: {e}")
            return {
                'success': False,
                'layers': [],
                'message': f'Ошибка: {e}',
                'errors': [str(e)]
            }

    def _filter_newest_files(self, file_paths: List[str]) -> tuple[List[str], List[str]]:
        """
        Фильтрация дубликатов выписок - оставляет только самые новые версии

        Алгоритм:
        1. Парсит каждый XML для извлечения КН и даты формирования
        2. Группирует файлы по кадастровому номеру
        3. Для каждого КН выбирает файл с самой новой датой
        4. Возвращает список актуальных файлов и информацию о пропущенных

        Args:
            file_paths: Список путей к XML файлам

        Returns:
            tuple: (список актуальных файлов, список информации о пропущенных)
        """
        grouped_files = defaultdict(list)
        default_date = datetime(1970, 1, 1)

        log_info(f"Fsm_1_1_4: Фильтрация дубликатов для {len(file_paths)} файлов")

        for file_path in file_paths:
            identifier, date_str = None, None

            try:
                # Быстрый парсинг для извлечения КН и даты формирования
                tree = ET.parse(file_path)
                root = tree.getroot()

                # Извлекаем кадастровый номер из основного record
                # (работает для land_record, build_record, construction_record)
                record_type = ROOT_TAG_TO_RECORD_MAP.get(root.tag)
                if record_type:
                    main_record = root.find(record_type)
                    if main_record is not None:
                        identifier = main_record.findtext('.//object/common_data/cad_number')

                # Извлекаем дату формирования из корня XML
                date_elem = root.find('date_formation')
                if date_elem is not None and date_elem.text:
                    date_str = date_elem.text.strip()

            except Exception as e:
                log_warning(f"Fsm_1_1_4: Быстрый парсинг для {os.path.basename(file_path)} не удался: {e}")

            # Fallback: используем имя файла как identifier
            if identifier is None:
                identifier = os.path.basename(file_path)

            # Парсим дату формирования
            file_date = default_date
            if date_str:
                try:
                    # Убираем timezone и время (ISO 8601: 2024-11-19T10:30:00+03:00 → 2024-11-19)
                    if '+' in date_str:
                        date_str = date_str.split('+')[0]
                    if 'T' in date_str:
                        date_str = date_str.split('T')[0]

                    file_date = datetime.strptime(date_str, '%Y-%m-%d')
                except ValueError as e:
                    log_warning(f"Fsm_1_1_4: Не удалось распарсить дату '{date_str}' для {os.path.basename(file_path)}: {e}")

            # Сохраняем информацию о файле
            grouped_files[identifier].append({
                'path': file_path,
                'date': file_date
            })

        # Отбираем самые новые файлы для каждого КН
        files_to_process = []
        skipped_info = []

        for identifier, files in grouped_files.items():
            if len(files) > 1:
                # Сортируем по дате (самая новая первая)
                files.sort(key=lambda x: x['date'], reverse=True)
                newest_file = files[0]
                files_to_process.append(newest_file['path'])

                # Формируем информацию о пропущенных файлах
                for old_file in files[1:]:
                    skipped_info.append(
                        f"{os.path.basename(old_file['path'])} "
                        f"(заменен на версию от {newest_file['date'].strftime('%d.%m.%Y')})"
                    )

                log_info(f"Fsm_1_1_4: {identifier} - выбрана версия от {newest_file['date'].strftime('%d.%m.%Y')} ({len(files)-1} старых пропущено)")
            else:
                # Единственный файл для этого КН
                files_to_process.append(files[0]['path'])

        if skipped_info:
            log_info(f"Fsm_1_1_4: Пропущено {len(skipped_info)} устаревших файлов")

        return files_to_process, skipped_info

    def _show_skipped_files_dialog(self) -> None:
        """
        Показ диалога с информацией о пропущенных файлах

        Отображает QMessageBox со списком файлов, которые были пропущены
        при фильтрации дубликатов (оставлены только самые новые версии).
        """
        if not self.skipped_info:
            # Нет пропущенных файлов - диалог не показываем
            return

        # Формируем HTML сообщение для диалога
        message = "<b>Следующие файлы были пропущены (найдены более новые версии):</b><br><br>"
        message += "<ul style='margin-left: 10px;'>"

        for info in self.skipped_info:
            message += f"<li>{info}</li>"

        message += "</ul>"

        # Показываем диалог
        QMessageBox.information(
            None,
            "Пропущенные файлы",
            message
        )

        log_info(f"Fsm_1_1_4: Показан диалог с {len(self.skipped_info)} пропущенными файлами")

    def _parse_vypiska_xml(self, file_path: str, gpkg_path: str = None) -> List[Dict[str, Any]]:
        """
        Парсинг одного XML файла выписки (DATABASE-DRIVEN)

        Args:
            file_path: Путь к XML файлу
            gpkg_path: Путь к GPKG (для поиска существующих данных WFS)

        Returns:
            List[Dict]: Список словарей с атрибутами и геометрией
        """
        tree = ET.parse(file_path)
        root = tree.getroot()

        features = []

        # Определяем тип выписки по корневому тегу
        root_tag = root.tag
        record_type = ROOT_TAG_TO_RECORD_MAP.get(root_tag)

        if not record_type:
            log_warning(f"Fsm_1_1_4: Неизвестный тип выписки: {root_tag}")
            return features

        # Находим основной record
        main_record = root.find(record_type)
        if main_record is None:
            log_warning(f"Fsm_1_1_4: Не найден {record_type} в {os.path.basename(file_path)}")
            return features

        # КРИТИЧЕСКИ ВАЖНО: Проверка SUBTYPE для разделения ЗУ и ЕЗ
        # Единое землепользование (ЕЗ) имеет subtype.code="02"
        # Обычный земельный участок (ЗУ) имеет subtype.code="01" или отсутствует
        if record_type == 'land_record':
            subtype_elem = main_record.find('.//subtype')
            if subtype_elem is not None:
                subtype_code = subtype_elem.findtext('code', '')
                if subtype_code == '02':  # Единое землепользование
                    record_type = 'unified_land_record'
                    log_info(f"Fsm_1_1_4: {os.path.basename(file_path)} - определен как ЕЗ (subtype=02)")

                    # Создать wrapper для извлечения атрибутов (с правильным root_element)
                    def extract_ez_attributes(record, rec_type):
                        return self._extract_all_attributes(record, rec_type, root_element=root)

                    # ДЕЛЕГИРУЕМ обработку ЕЗ специализированному процессору
                    # FIX (2025-12-17): Передаём gpkg_path для поиска площади из WFS
                    processor = Fsm_1_1_4_7_UnifiedLandProcessor(
                        main_record=main_record,
                        extract_geometry_func=extract_geometry,
                        extract_attributes_func=extract_ez_attributes,
                        gpkg_path=gpkg_path
                    )

                    # Получаем features для ЕЗ (основной ЕЗ + части + обособленные участки)
                    ez_features = processor.process()
                    features.extend(ez_features)

                    # ЕЗ полностью обработан - возвращаем результат
                    return features

        # ИЗВЛЕЧЕНИЕ ВСЕХ АТРИБУТОВ через FieldMappingManager (ZERO HARDCODE)
        # Передаём root для полей уровня корня (Статус и др.)
        attributes = self._extract_all_attributes(main_record, record_type, root_element=root)

        # Проверка обязательного поля КН
        cad_number = attributes.get('КН')
        if not cad_number:
            log_warning(f"Fsm_1_1_4: Не найден кадастровый номер в {os.path.basename(file_path)}")
            return features

        # ГЕОМЕТРИЯ - используем модуль Fsm_1_1_4_3_geometry
        contours_loc = main_record.find('contours_location')
        contours_direct = main_record.find('contours')

        # Проверяем, что элемент не пустой и содержит координаты
        def has_coords(elem):
            """Проверка наличия координат в элементе"""
            if elem is None:
                return False
            # Проверяем наличие <ordinates> внутри
            ordinates = elem.find('.//ordinates')
            return ordinates is not None and len(list(ordinates)) > 0

        # Выбираем источник геометрии только если он содержит координаты
        geometry_source = None
        if has_coords(contours_loc):
            geometry_source = contours_loc
        elif has_coords(contours_direct):
            geometry_source = contours_direct

        # Геометрия основного объекта
        geometries = extract_geometry(geometry_source)

        # Берем первую найденную геометрию основного объекта
        # FIX: Обновлены ключи для поддержки M-координат (delta_geopoint)
        geometry = None
        if geometries and "NoGeometry" not in geometries:
            # Приоритет: полигон > линия > точка
            if "MultiPolygonM" in geometries:
                geometry = geometries["MultiPolygonM"]
            elif "MultiLineStringM" in geometries:
                geometry = geometries["MultiLineStringM"]
            elif "MultiPointM" in geometries:
                geometry = geometries["MultiPointM"]

        # Создаем feature для ОСНОВНОГО объекта с ВСЕМИ атрибутами
        feature_data = attributes.copy()
        feature_data['geometry'] = geometry
        feature_data['record_type'] = record_type
        features.append(feature_data)

        # ЧАСТИ ОБЪЕКТА - каждая часть = отдельный feature
        object_parts = main_record.find('object_parts')
        if object_parts is not None:
            parts_count = 0
            parts_without_number = 0  # Счётчик частей без номера

            for part_elem in object_parts.findall('object_part'):
                # Оригинальный part_number из XML (может быть пустым)
                original_part_number = part_elem.findtext('part_number', '')

                # Генерация уникального ID для частей без номера (для атрибута "Номер_части")
                if not original_part_number:
                    parts_without_number += 1
                    display_part_number = f"NO_NUMBER_{parts_without_number}"
                    log_warning(f"Fsm_1_1_4: Обнаружена часть без номера для {cad_number}, присвоен ID: {display_part_number}")
                else:
                    display_part_number = original_part_number

                # Извлекаем БАЗОВЫЕ атрибуты части через FieldMappingManager
                part_attrs = self._extract_all_attributes(part_elem, 'object_part')

                # Добавляем КН родителя (программно)
                part_attrs['КН_родителя'] = cad_number

                # Добавляем/обновляем Номер_части (оригинальное или генерированное)
                part_attrs['Номер_части'] = display_part_number

                # Извлекаем ОГРАНИЧЕНИЯ для части из main_record
                # ВАЖНО: используем ОРИГИНАЛЬНЫЙ part_number для поиска в XML (может быть пустым)
                restrictions_attrs = self._extract_restrictions_for_part(main_record, original_part_number)
                part_attrs.update(restrictions_attrs)

                # Геометрия части
                part_contours = part_elem.find('contours')
                part_geometries = extract_geometry(part_contours)

                # Берем первую геометрию части
                # FIX: Обновлены ключи для поддержки M-координат (delta_geopoint)
                part_geometry = None
                if part_geometries and "NoGeometry" not in part_geometries:
                    if "MultiPolygonM" in part_geometries:
                        part_geometry = part_geometries["MultiPolygonM"]
                    elif "MultiLineStringM" in part_geometries:
                        part_geometry = part_geometries["MultiLineStringM"]
                    elif "MultiPointM" in part_geometries:
                        part_geometry = part_geometries["MultiPointM"]

                # Создаем feature для ЧАСТИ объекта
                part_feature_data = part_attrs.copy()
                part_feature_data['record_type'] = 'object_part'
                part_feature_data['geometry'] = part_geometry

                features.append(part_feature_data)
                parts_count += 1

            # Накапливаем статистику частей (вместо лога для каждого КН)
            if parts_count > 0:
                self.total_parts_count += parts_count
                self.zu_with_parts_count += 1

        return features

    def _extract_restrictions_for_part(self, main_record, part_number: str) -> Dict[str, Any]:
        """
        Извлечение ограничений для части через FieldMappingManager (ZERO HARDCODE)

        Args:
            main_record: XML элемент main_record (содержит restrictions_encumbrances)
            part_number: Номер части для поиска ограничений

        Returns:
            Dict с атрибутами ограничений {working_name: value}
        """
        restrictions_attrs = {}

        restrictions_container = main_record.find('restrictions_encumbrances')
        if restrictions_container is None:
            return restrictions_attrs

        # Получаем маппинги полей для object_part
        field_mappings = self.field_mapper.get_fields_for_record_type('object_part')
        if not field_mappings:
            return restrictions_attrs

        # Собираем все restriction_encumbrance для данной части
        matching_restrictions = []
        for restr_elem in restrictions_container.findall('restriction_encumbrance'):
            pn = restr_elem.findtext('part_number')
            if pn == part_number:
                matching_restrictions.append(restr_elem)

        if not matching_restrictions:
            return restrictions_attrs

        # Извлекаем атрибуты из ВСЕХ ограничений данной части
        # Для полей с semicolon_join - собираем значения в списки
        field_values = {}

        for restr_elem in matching_restrictions:
            for mapping in field_mappings:
                working_name = mapping.get('working_name')
                if not working_name:
                    continue

                # Пропускаем базовые поля части (они извлекаются из part_elem)
                if working_name in ['КН_родителя', 'Номер_части', 'Площадь_части', 'Дата_внесения_части']:
                    continue

                try:
                    # Извлекаем значение через FieldMappingManager
                    value = self.field_mapper.extract_value(restr_elem, mapping)

                    # Сохраняем значение (собираем все значения от всех ограничений в список)
                    if value is not None and str(value).strip() != '':
                        if working_name not in field_values:
                            field_values[working_name] = []
                        field_values[working_name].append(str(value))

                except Exception as e:
                    log_warning(f"Fsm_1_1_4 (_extract_restrictions_for_part): Ошибка извлечения поля '{working_name}': {e}")

        # Формируем итоговые значения с join через "; "
        for working_name, values in field_values.items():
            if values:
                # Убираем дубликаты и объединяем через "; "
                unique_values = list(dict.fromkeys(values))  # Сохраняем порядок
                restrictions_attrs[working_name] = '; '.join(unique_values)

        return restrictions_attrs

    def _extract_all_attributes(self, xml_element, record_type: str, root_element=None) -> Dict[str, Any]:
        """
        Извлечение ВСЕХ атрибутов из XML через FieldMappingManager (ZERO HARDCODE)

        Args:
            xml_element: XML элемент (main_record)
            record_type: Тип записи (land_record, unified_land_record, build_record)
            root_element: Корневой XML элемент (для полей уровня root, например "Статус")

        Returns:
            Dict с атрибутами {working_name: value}
        """
        attributes = {}

        # Получаем все маппинги для данного типа записи
        field_mappings = self.field_mapper.get_fields_for_record_type(record_type)

        if not field_mappings:
            log_warning(f"Fsm_1_1_4 (_extract_all_attributes): Нет маппингов для record_type='{record_type}'")
            return attributes

        # Извлекаем значение для каждого поля
        for mapping in field_mappings:
            working_name = mapping.get('working_name')
            if not working_name:
                continue

            try:
                # Поля уровня корня (xml_level: "root") извлекаем из root_element
                xml_level = mapping.get('xml_level', 'record')
                xml_xpath_root = mapping.get('xml_xpath_root', '-')

                # CASE 1: xml_level="root" - поле находится в корне XML
                if xml_level == 'root' and root_element is not None:
                    value = self.field_mapper.extract_value(root_element, mapping)

                # CASE 2: xml_xpath_root начинается с right_records/restrict_records - они в корне!
                elif xml_xpath_root and xml_xpath_root not in ('-', 'null', '') and root_element is not None:
                    # Проверяем, что xml_xpath_root указывает на корневые элементы
                    if xml_xpath_root.startswith('right_records') or xml_xpath_root.startswith('restrict_records'):
                        value = self.field_mapper.extract_value(root_element, mapping)
                    else:
                        # Обычное извлечение из main_record
                        value = self.field_mapper.extract_value(xml_element, mapping)

                # CASE 3: Обычное поле внутри main_record
                else:
                    value = self.field_mapper.extract_value(xml_element, mapping)

                # Сохраняем только непустые значения
                if value is not None and str(value).strip() != '':
                    attributes[working_name] = value

            except Exception as e:
                log_warning(f"Fsm_1_1_4 (_extract_all_attributes): Ошибка извлечения поля '{working_name}': {e}")

        return attributes
