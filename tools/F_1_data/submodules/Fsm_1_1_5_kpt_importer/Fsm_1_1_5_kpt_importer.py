# -*- coding: utf-8 -*-
"""
Fsm_1_1_5: Импортер КПТ (Кадастровый План Территории)

Главный класс для импорта КПТ файлов с потоковым парсингом.
Адаптировано из external_modules/kd_kpt для интеграции в Daman_QGIS.

Ключевые особенности:
- Потоковый парсинг через lxml.iterparse (для файлов 10-100+ MB)
- Фильтрация дубликатов по дате
- Сохранение в GeoPackage
- Интеграция с layer_handler для переименования слоев
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsField, QgsFields,
    QgsCoordinateReferenceSystem, QgsVectorFileWriter
)
from qgis.PyQt.QtCore import QVariant, QDate, QDateTime

from Daman_QGIS.utils import log_info, log_warning, log_error

from .Fsm_1_1_5_1_parser import Fsm_1_1_5_1_Parser
from .Fsm_1_1_5_2_geometry import extract_geometry


class Fsm_1_1_5_KptImporter:
    """Импортер КПТ (Кадастровый План Территории)"""

    # Человекочитаемые имена слоев
    CUSTOM_LAYER_NAMES = {
        "land_record": "земельный_участок",
        "build_record": "здание",
        "construction_record": "сооружение",
        "object_under_construction_record": "ОНС",
        "spatial_data": "квартал",
        "subject_boundary_record": "субъект_РФ",
        "municipal_boundary_record": "муниц_образование",
        "inhabited_locality_boundary_record": "населенный_пункт",
        "coastline_record": "береговая_линия",
        "zones_and_territories_record": "зоны_и_территории",
        "surveying_project_record": "проект_межевания",
        "public_easement_record": "сервитут"
    }

    # Сокращения типов геометрии
    GEOM_ABBREVIATIONS = {
        "MultiPolygon": "pl",
        "MultiLineString": "lin",
        "MultiPoint": "pt",
        "NoGeometry": "not"
    }

    # Имена групп
    GROUP_NAMES = {
        "kpt_main": "КП",
        "standalone_boundaries": "ГЗТ"
    }

    def __init__(self, iface, layer_handler: Optional[Callable] = None):
        """
        Args:
            iface: Интерфейс QGIS
            layer_handler: Опциональный обработчик слоев (layer, record_type, geom_abbr) -> layer
        """
        self.iface = iface
        self.layer_handler = layer_handler

        # Загружаем маппинг атрибутов
        self.attribute_map = self._load_attribute_map()
        self._field_type_cache = self._create_field_type_cache()

        # Результаты последнего импорта
        self.skipped_info: List[str] = []
        self.total_records_processed = 0

        # Парсер
        self.parser = Fsm_1_1_5_1_Parser(
            geometry_extractor=extract_geometry,
            attribute_extractor=self._extract_attributes
        )

    def run_import(
        self,
        options: Dict[str, Any],
        progress_callback: Optional[Callable[[int], None]] = None,
        text_callback: Optional[Callable[[str], None]] = None,
        is_cancelled_callback: Optional[Callable[[], bool]] = None
    ) -> List[QgsVectorLayer]:
        """
        Запуск импорта КПТ

        Args:
            options: Опции импорта:
                - files: List[str] - пути к файлам
                - crs: QgsCoordinateReferenceSystem - целевая СК
                - save_to_file: bool - сохранять в GeoPackage
                - output_dir: str - папка для сохранения
                - output_name: str - имя группы/файла
                - split: bool - разбивать по кварталам
                - filter_duplicate: bool - фильтровать дубликаты
            progress_callback: Callback для прогресса
            text_callback: Callback для текста статуса
            is_cancelled_callback: Callback проверки отмены

        Returns:
            Список созданных слоев
        """
        files = options.get("files", [])
        if not files:
            log_warning("Fsm_1_1_5: Нет файлов для импорта")
            return []

        target_crs = options.get("crs", QgsCoordinateReferenceSystem("EPSG:32637"))
        save_to_file = options.get("save_to_file", False)
        output_dir = options.get("output_dir", "")
        output_name = options.get("output_name", "Импорт_КПТ")
        split_by_quarter = options.get("split", False)
        filter_duplicate = options.get("filter_duplicate", True)

        # Фильтрация дубликатов
        if filter_duplicate:
            files_to_process, self.skipped_info = self.parser.filter_files_by_date(files)
            if self.skipped_info:
                log_info(f"Fsm_1_1_5: Пропущено устаревших файлов: {len(self.skipped_info)}")
        else:
            files_to_process = files
            self.skipped_info = []

        if not files_to_process:
            log_warning("Fsm_1_1_5: Нет файлов после фильтрации")
            return []

        created_layers: List[QgsVectorLayer] = []
        self.total_records_processed = 0

        if split_by_quarter:
            # Режим разбивки по файлам
            for i, file_path in enumerate(files_to_process):
                if is_cancelled_callback and is_cancelled_callback():
                    break

                suffix, root_tag = self.parser.get_file_header_info(file_path)
                group_name = self._create_group_name(suffix, root_tag)

                layers = self._process_file_group(
                    [file_path],
                    group_name,
                    target_crs,
                    save_to_file,
                    output_dir,
                    progress_callback,
                    text_callback,
                    is_cancelled_callback
                )
                created_layers.extend(layers)
        else:
            # Сводный режим
            layers = self._process_file_group(
                files_to_process,
                output_name,
                target_crs,
                save_to_file,
                output_dir,
                progress_callback,
                text_callback,
                is_cancelled_callback,
                total_batch_size=sum(os.path.getsize(f) for f in files_to_process)
            )
            created_layers.extend(layers)

        log_info(f"Fsm_1_1_5: Импортировано слоев: {len(created_layers)}, записей: {self.total_records_processed}")
        return created_layers

    def _process_file_group(
        self,
        file_paths: List[str],
        group_name: str,
        target_crs: QgsCoordinateReferenceSystem,
        save_to_file: bool,
        output_dir: str,
        progress_callback: Optional[Callable[[int], None]] = None,
        text_callback: Optional[Callable[[str], None]] = None,
        is_cancelled_callback: Optional[Callable[[], bool]] = None,
        total_batch_size: Optional[int] = None
    ) -> List[QgsVectorLayer]:
        """Обработка группы файлов"""

        # Парсинг файлов
        cached_features, schemas, record_count = self.parser.parse_files(
            file_paths,
            progress_callback,
            text_callback,
            is_cancelled_callback,
            total_batch_size
        )

        self.total_records_processed += record_count

        if not cached_features:
            return []

        created_layers: List[QgsVectorLayer] = []

        # Создаем группу в проекте
        root_group = self._create_unique_group(group_name)

        # Путь к GeoPackage
        gpkg_path = ""
        if save_to_file and output_dir:
            file_system_name = self._sanitize_filename(group_name)
            target_dir = os.path.join(output_dir, file_system_name)
            os.makedirs(target_dir, exist_ok=True)
            gpkg_path = os.path.join(target_dir, f"{file_system_name}.gpkg")

        # Определяем формат данных (с дедупликацией или без)
        is_deduplicated = isinstance(next(iter(cached_features.values()), None), dict)

        # Создаем слои
        for layer_key, layer_cache in cached_features.items():
            fields_set = schemas.get(layer_key, set())
            if not fields_set:
                continue

            # Извлекаем features
            if is_deduplicated:
                keyed_values = list(layer_cache.get("keyed", {}).values()) if isinstance(layer_cache, dict) else []
                unkeyed_values = layer_cache.get("unkeyed", []) if isinstance(layer_cache, dict) else []
                features_to_write = [data[:2] for data in (keyed_values + unkeyed_values)]
            else:
                features_to_write = layer_cache

            if not features_to_write:
                continue

            # Разбираем layer_key
            record_type, geom_str = layer_key.rsplit('_', 1)

            # Создаем поля
            qgs_fields = QgsFields()
            for field_name in sorted(list(fields_set)):
                field_type = self._get_field_type(field_name)
                qgs_fields.append(QgsField(field_name, field_type))

            # Создаем слой
            layer = self._create_layer_and_write_features(
                record_type,
                geom_str,
                qgs_fields,
                features_to_write,
                target_crs,
                save_to_file,
                gpkg_path
            )

            if layer:
                # Применяем layer_handler если есть
                if self.layer_handler:
                    geom_abbr = self.GEOM_ABBREVIATIONS.get(geom_str, "geom")
                    layer = self.layer_handler(layer, record_type, geom_abbr)

                QgsProject.instance().addMapLayer(layer, False)
                root_group.addLayer(layer)
                created_layers.append(layer)

        return created_layers

    def _create_layer_and_write_features(
        self,
        record_type: str,
        geom_type: str,
        fields: QgsFields,
        features_data: List,
        target_crs: QgsCoordinateReferenceSystem,
        save_to_file: bool,
        gpkg_path: str
    ) -> Optional[QgsVectorLayer]:
        """Создание слоя и запись features"""

        layer_name = f"{self.CUSTOM_LAYER_NAMES.get(record_type, record_type)}_{self.GEOM_ABBREVIATIONS.get(geom_type, 'geom')}"
        uri = "None" if geom_type == "NoGeometry" else f"{geom_type}?crs={target_crs.authid()}"

        temp_layer = QgsVectorLayer(uri, layer_name, "memory")
        prov = temp_layer.dataProvider()
        prov.addAttributes(fields.toList())
        temp_layer.updateFields()

        features = []
        for geom, attrs in features_data:
            feature = QgsFeature(temp_layer.fields())
            if geom:
                feature.setGeometry(geom)
            for field_name, value in attrs.items():
                idx = temp_layer.fields().lookupField(field_name)
                if idx != -1:
                    field = temp_layer.fields().field(idx)
                    converted_value = self._convert_value(value, field.type())
                    feature.setAttribute(idx, converted_value)
            features.append(feature)

        prov.addFeatures(features)

        if save_to_file and gpkg_path:
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = layer_name
            options.actionOnExistingFile = (
                QgsVectorFileWriter.CreateOrOverwriteLayer
                if os.path.exists(gpkg_path)
                else QgsVectorFileWriter.CreateOrOverwriteFile
            )

            write_result = QgsVectorFileWriter.writeAsVectorFormatV3(
                temp_layer, gpkg_path, QgsProject.instance().transformContext(), options
            )

            if write_result[0] != QgsVectorFileWriter.NoError:
                log_error(f"Fsm_1_1_5: Ошибка записи слоя {layer_name}: {write_result[1]}")
                return None

            return QgsVectorLayer(f"{gpkg_path}|layername={layer_name}", layer_name, "ogr")

        return temp_layer

    def _extract_attributes(self, element, attributes: Dict):
        """Извлечение атрибутов из XML элемента"""
        tags_to_skip = {
            "contours_location", "b_contours_location", "entity_spatial",
            "permitted_uses", "included_parcels", "decisions_requisites",
            "geopoint_opred", "delta_geopoint", "ord_nmb", "number_pp"
        }

        self._extract_attributes_recursive(element, attributes, "", tags_to_skip)

    def _extract_attributes_recursive(self, element, attributes: Dict, parent_path: str, tags_to_skip: set):
        """Рекурсивное извлечение атрибутов"""
        if element.tag in tags_to_skip:
            return

        for child in element:
            if child.tag in tags_to_skip:
                continue

            full_path = f"{parent_path}_{child.tag}" if parent_path else child.tag

            # Специальная обработка reg_numb_border
            if element.tag == 'b_object' and child.tag == 'reg_numb_border':
                if child.text and child.text.strip():
                    attributes['numb_border'] = child.text.strip()
                continue

            if child.text and child.text.strip():
                short_name = self._shorten_attribute_name(full_path)
                attributes[short_name] = child.text.strip()

            self._extract_attributes_recursive(child, attributes, full_path, tags_to_skip)

    def _shorten_attribute_name(self, full_path: str) -> str:
        """Сокращение имени атрибута по маппингу"""
        mapping = self.attribute_map.get(full_path)
        short_name = ""

        if isinstance(mapping, dict):
            short_name = mapping.get("name")
        elif isinstance(mapping, list) and len(mapping) > 0:
            short_name = mapping[0]
        elif isinstance(mapping, str):
            short_name = mapping

        if not short_name:
            parts = full_path.split("_")
            short_name = "_".join(parts[-2:]) if len(parts) > 2 else full_path

        return short_name

    def _load_attribute_map(self) -> Dict:
        """Загрузка маппинга атрибутов из JSON"""
        map_path = os.path.join(os.path.dirname(__file__), 'attribute_map.json')
        try:
            with open(map_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log_warning(f"Fsm_1_1_5: Не удалось загрузить attribute_map.json: {e}")
            return {}

    def _create_field_type_cache(self) -> Dict[str, str]:
        """Создание кэша типов полей"""
        cache = {}
        for long_name, mapping in self.attribute_map.items():
            short_name = ""
            type_str = "String"

            if isinstance(mapping, dict):
                short_name = mapping.get("name")
                type_str = mapping.get("type", "String")
            elif isinstance(mapping, list):
                if len(mapping) > 0:
                    short_name = mapping[0]
                if len(mapping) > 1:
                    type_str = mapping[1]
            elif isinstance(mapping, str):
                short_name = mapping

            if short_name:
                cache[short_name] = type_str

        return cache

    def _get_field_type(self, short_name: str) -> int:
        """Получение QVariant типа поля"""
        type_map = {
            "Integer": QVariant.Int,
            "Long": QVariant.LongLong,
            "Real": QVariant.Double,
            "String": QVariant.String,
            "Date": QVariant.Date,
            "DateTime": QVariant.DateTime
        }
        type_str = self._field_type_cache.get(short_name, "String")
        return type_map.get(type_str, QVariant.String)

    def _convert_value(self, value: Any, target_type: int) -> Any:
        """Конвертация значения в нужный тип"""
        if value is None or value == "":
            return QVariant()

        try:
            cleaned_value = str(value).strip()

            if target_type in (QVariant.Int, QVariant.LongLong):
                return int(float(cleaned_value))
            elif target_type == QVariant.Double:
                return float(cleaned_value)
            elif target_type == QVariant.Date:
                dt = None
                for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%Y.%m.%d'):
                    try:
                        dt = datetime.strptime(cleaned_value, fmt)
                        break
                    except ValueError:
                        continue
                return QDate(dt.year, dt.month, dt.day) if dt else QVariant()
            elif target_type == QVariant.DateTime:
                dt = None
                for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d.%m.%Y %H:%M:%S', '%d.%m.%Y'):
                    try:
                        dt = datetime.strptime(cleaned_value, fmt)
                        break
                    except ValueError:
                        continue
                return QDateTime(dt) if dt else QVariant()
            else:
                return cleaned_value

        except (ValueError, TypeError):
            return QVariant()

    def _create_group_name(self, suffix: str, root_tag: str) -> str:
        """Создание имени группы из суффикса и root_tag"""
        base_name = self.GROUP_NAMES.get(
            "kpt_main" if root_tag == 'extract_cadastral_plan_territory' else "standalone_boundaries",
            "Импорт"
        )
        raw_number = suffix.strip('_').replace(":", "")

        if raw_number.isdigit() and len(raw_number) > 6:
            return f"{base_name} {raw_number[:2]}:{raw_number[2:4]}:{raw_number[4:]}"
        else:
            return f"{base_name} {raw_number}" if raw_number else base_name

    def _create_unique_group(self, base_name: str):
        """Создание уникальной группы в проекте"""
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(base_name)
        if not group:
            return root.insertGroup(0, base_name)
        return group

    def _sanitize_filename(self, name: str) -> str:
        """Очистка имени для файловой системы"""
        return "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).rstrip()
