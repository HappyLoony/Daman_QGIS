# -*- coding: utf-8 -*-
"""
Fsm_1_1_5_1: Потоковый парсер КПТ (iterparse)

Потоковый парсинг XML через lxml.iterparse для больших файлов (10-100+ MB).
Оптимизирован для КПТ (Кадастровый План Территории).

Ключевые особенности:
- iterparse с events=('start', 'end') для потоковой обработки
- elem.clear() + del elem.getparent()[0] для очистки памяти
- Прогресс по байтам файла
- Поддержка отмены операции
"""

import os
import tempfile
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple, Callable, Optional, Any

from Daman_QGIS.utils import log_info, log_warning, log_error

# lxml импортируется условно
try:
    from lxml import etree as ET
except ImportError:
    ET = None  # type: ignore


class Fsm_1_1_5_1_Parser:
    """Потоковый парсер КПТ с iterparse"""

    # Типы записей с геометрией
    RECORD_TYPES_GEOMETRY = {
        "land_record": ["MultiPolygon", "NoGeometry"],
        "build_record": ["MultiPolygon", "NoGeometry"],
        "construction_record": ["MultiPolygon", "NoGeometry", "MultiLineString", "MultiPoint"],
        "object_under_construction_record": ["MultiPolygon", "NoGeometry"],
        "spatial_data": ["MultiPolygon"],
        "subject_boundary_record": ["MultiPolygon", "MultiLineString"],
        "municipal_boundary_record": ["MultiPolygon"],
        "inhabited_locality_boundary_record": ["MultiPolygon"],
        "coastline_record": ["MultiPolygon", "MultiLineString", "MultiPoint"],
        "zones_and_territories_record": ["MultiPolygon"],
        "surveying_project_record": ["MultiPolygon", "NoGeometry"],
        "public_easement_record": ["MultiPolygon"]
    }

    # Записи с собственным кадастровым номером
    RECORDS_WITH_OWN_CAD_NUMBER = [
        "land_record", "build_record", "construction_record", "object_under_construction_record"
    ]

    def __init__(self, geometry_extractor, attribute_extractor):
        """
        Args:
            geometry_extractor: Функция извлечения геометрии (record) -> dict
            attribute_extractor: Функция извлечения атрибутов (element, attributes) -> None
        """
        self.geometry_extractor = geometry_extractor
        self.attribute_extractor = attribute_extractor

    def parse_files(
        self,
        file_paths: List[str],
        progress_callback: Optional[Callable[[int], None]] = None,
        text_callback: Optional[Callable[[str], None]] = None,
        is_cancelled_callback: Optional[Callable[[], bool]] = None,
        total_batch_size: Optional[int] = None
    ) -> Tuple[Dict, Dict, int]:
        """
        Парсинг списка КПТ файлов с потоковой обработкой

        Args:
            file_paths: Список путей к XML файлам
            progress_callback: Callback для прогресса (0-100)
            text_callback: Callback для текста статуса
            is_cancelled_callback: Callback проверки отмены
            total_batch_size: Общий размер батча (для combined mode)

        Returns:
            (cached_features, schemas, record_count)
        """
        if ET is None:
            log_error("Fsm_1_1_5_1: lxml не установлен")
            return {}, {}, 0

        needs_deduplication = len(file_paths) > 1
        is_combined_mode = total_batch_size is not None

        schemas: Dict[str, set] = {}
        if needs_deduplication:
            cached_features: Dict = defaultdict(lambda: {"keyed": {}, "unkeyed": []})
        else:
            cached_features = defaultdict(list)

        record_counter = 0
        total_bytes_processed = 0

        for i, file_path in enumerate(file_paths):
            temp_file_obj = None
            try:
                # Препроцессинг XML (фикс битых файлов)
                path_to_process, temp_file_obj = self._preprocess_xml(file_path)
                current_file_size = os.path.getsize(path_to_process)
                default_date = datetime(1970, 1, 1)

                with open(path_to_process, 'rb') as file_stream:
                    context = ET.iterparse(file_stream, events=('start', 'end'), recover=True)
                    last_progress = -1
                    current_quarter_number = None

                    for event, elem in context:
                        # Проверка отмены
                        if is_cancelled_callback and is_cancelled_callback():
                            return {}, {}, 0

                        # На start событии запоминаем номер квартала
                        if event == 'start':
                            if elem.tag == 'cadastral_block':
                                cn_elem = elem.find('cadastral_number')
                                if cn_elem is not None and cn_elem.text:
                                    current_quarter_number = cn_elem.text.strip()
                            continue

                        # Прогресс
                        if progress_callback:
                            if is_combined_mode and total_batch_size:
                                current_progress_bytes = total_bytes_processed + file_stream.tell()
                                progress = 5 + int((current_progress_bytes * 90) / total_batch_size)
                            else:
                                progress = 5 + int((file_stream.tell() * 90) / current_file_size) if current_file_size > 0 else 5

                            if progress > last_progress:
                                if text_callback:
                                    if is_combined_mode:
                                        text_callback(f"Обработка файлов... ({i+1}/{len(file_paths)})")
                                    else:
                                        text_callback(f"Обработано {progress}%")
                                progress_callback(min(progress, 95))
                                last_progress = progress

                        # Обработка записей с геометрией
                        if elem.tag in self.RECORD_TYPES_GEOMETRY or elem.tag in ("zones_and_territories", "boundary_record"):
                            record_counter += 1
                            record_type, target_element = None, elem

                            if elem.tag == "zones_and_territories":
                                record_type = "zones_and_territories_record"
                            elif elem.tag == "boundary_record":
                                if len(elem) > 0:
                                    target_element, record_type = elem[0], f"{elem[0].tag}_record"
                            elif elem.tag in self.RECORD_TYPES_GEOMETRY:
                                record_type = elem.tag

                            if record_type:
                                attributes: Dict[str, Any] = {}

                                # Добавляем номер квартала для ЗУ и spatial_data
                                if current_quarter_number and record_type in ("land_record", "spatial_data"):
                                    attributes['cadastral_number'] = current_quarter_number

                                # Извлекаем кадастровый номер объекта
                                if record_type in self.RECORDS_WITH_OWN_CAD_NUMBER:
                                    cad_elem = target_element.find(".//object/common_data/cad_number")
                                    if cad_elem is not None and cad_elem.text:
                                        attributes['cad_number'] = cad_elem.text.strip()

                                # Извлекаем атрибуты
                                self.attribute_extractor(target_element, attributes)

                                # Дополнительная обработка зон
                                if record_type == "zones_and_territories_record":
                                    self._extract_zone_lists(target_element, attributes)

                                # МСК
                                sk_id_elem = target_element.find('.//sk_id')
                                if sk_id_elem is not None and sk_id_elem.text:
                                    attributes['msk'] = sk_id_elem.text.strip()

                                # Извлекаем геометрии
                                geometries = self.geometry_extractor(target_element)

                                # Добавляем в кэш
                                for geom_type, geom in geometries.items():
                                    layer_key = f"{record_type}_{geom_type}"
                                    if layer_key not in schemas:
                                        schemas[layer_key] = set()
                                    schemas[layer_key].update(attributes.keys())

                                    feature_data = (geom, attributes, default_date) if needs_deduplication else (geom, attributes)

                                    if needs_deduplication:
                                        unique_key = self._get_feature_unique_key(attributes)
                                        if unique_key:
                                            existing = cached_features[layer_key]["keyed"].get(unique_key)
                                            if not existing or default_date > existing[2]:
                                                cached_features[layer_key]["keyed"][unique_key] = feature_data
                                        else:
                                            cached_features[layer_key]["unkeyed"].append(feature_data)
                                    else:
                                        cached_features[layer_key].append(feature_data)

                            # Очистка памяти (критически важно для iterparse!)
                            elem.clear()
                            while elem.getprevious() is not None:
                                del elem.getparent()[0]

            except Exception as e:
                log_error(f"Fsm_1_1_5_1: Ошибка парсинга {os.path.basename(file_path)}: {e}")
                import traceback
                log_error(f"Fsm_1_1_5_1: {traceback.format_exc()}")
                continue
            finally:
                # Удаляем временный файл
                if temp_file_obj:
                    try:
                        os.unlink(temp_file_obj.name)
                    except OSError:
                        pass

            total_bytes_processed += current_file_size

        return dict(cached_features), schemas, record_counter

    def filter_files_by_date(self, file_paths: List[str]) -> Tuple[List[str], List[str]]:
        """
        Фильтрация файлов по дате - оставляем только новейшие версии

        Args:
            file_paths: Список путей к файлам

        Returns:
            (files_to_process, skipped_files_info)
        """
        if ET is None:
            return file_paths, []

        grouped_files: Dict[str, List[Dict]] = defaultdict(list)
        default_date = datetime(1970, 1, 1)

        for file_path in file_paths:
            identifier, date_str = None, None
            try:
                with open(file_path, 'rb') as f:
                    context = ET.iterparse(f, events=('start',), recover=True)
                    found_identifier = False

                    for _, elem in context:
                        if elem.tag == "cadastral_number" and elem.text and elem.text.strip():
                            identifier = elem.text.strip()
                            found_identifier = True
                        elif elem.tag == "reg_numb_border" and elem.text and elem.text.strip():
                            identifier = elem.text.strip()
                            found_identifier = True

                        if elem.tag == "date_formation" and elem.text and elem.text.strip():
                            date_str = elem.text.strip()

                        elem.clear()
                        if found_identifier and date_str:
                            break

                    if identifier is None:
                        identifier = os.path.basename(file_path)

                file_date = default_date
                if date_str:
                    try:
                        file_date = datetime.strptime(date_str, '%Y-%m-%d')
                    except ValueError:
                        pass

                grouped_files[identifier].append({'path': file_path, 'date': file_date})

            except Exception as e:
                log_warning(f"Fsm_1_1_5_1: Ошибка предобработки {os.path.basename(file_path)}: {e}")

        files_to_process: List[str] = []
        skipped_files_info: List[str] = []

        for identifier, files in grouped_files.items():
            files.sort(key=lambda x: x['date'], reverse=True)
            newest_file = files[0]
            files_to_process.append(newest_file['path'])

            for old_file in files[1:]:
                skipped_files_info.append(
                    f"{os.path.basename(old_file['path'])} (заменен на {os.path.basename(newest_file['path'])})"
                )

        return files_to_process, skipped_files_info

    def get_file_header_info(self, file_path: str) -> Tuple[str, str]:
        """
        Быстрое получение идентификатора и root tag из заголовка файла

        Args:
            file_path: Путь к файлу

        Returns:
            (suffix, root_tag)
        """
        if ET is None:
            return "", ""

        suffix = ""
        root_tag = ""
        chunk_size = 8 * 1024

        try:
            import io
            with open(file_path, 'rb') as f:
                chunk = f.read(chunk_size)

            context = ET.iterparse(io.BytesIO(chunk), events=('start',), recover=True)

            for _, elem in context:
                if not root_tag:
                    root_tag = elem.tag

                if elem.tag in ("cadastral_number", "reg_numb_border") and elem.text and elem.text.strip():
                    suffix = f"_{elem.text.strip()}"
                    break

                elem.clear()

        except Exception as e:
            log_warning(f"Fsm_1_1_5_1: Ошибка чтения заголовка {os.path.basename(file_path)}: {e}")
            suffix = f"_{os.path.splitext(os.path.basename(file_path))[0]}"
            if not root_tag:
                root_tag = "extract_cadastral_plan_territory"

        return suffix, root_tag

    def _preprocess_xml(self, original_path: str) -> Tuple[str, Optional[Any]]:
        """
        Препроцессинг XML - фикс битых файлов с преждевременным закрытием тега

        Args:
            original_path: Путь к оригинальному файлу

        Returns:
            (path_to_process, temp_file_obj)
        """
        possible_root_tags = ['extract_cadastral_plan_territory', 'extract_about_zone', 'extract_about_boundary']
        root_tag_name = None
        needs_fixing = False

        try:
            with open(original_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                for i, line in enumerate(f):
                    if i < 10 and not root_tag_name:
                        for tag in possible_root_tags:
                            if f'<{tag}' in line:
                                root_tag_name = tag
                                break

                    if root_tag_name:
                        closing_tag = f'</{root_tag_name}>'
                        if closing_tag in line:
                            needs_fixing = True
                            break
        except Exception:
            return original_path, None

        if not needs_fixing:
            return original_path, None

        temp_file = None
        try:
            temp_file = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.xml')
            with open(original_path, 'r', encoding='utf-8-sig', errors='ignore') as source_file:
                for line in source_file:
                    if root_tag_name:
                        cleaned_line = line.replace(f'</{root_tag_name}>', '')
                        temp_file.write(cleaned_line)

            if root_tag_name:
                temp_file.write(f'</{root_tag_name}>')

            temp_file.close()
            return temp_file.name, temp_file

        except Exception as e:
            log_error(f"Fsm_1_1_5_1: Ошибка фикса XML {original_path}: {e}")
            if temp_file:
                temp_file.close()
                try:
                    os.unlink(temp_file.name)
                except OSError:
                    pass
            return original_path, None

    def _get_feature_unique_key(self, attributes: Dict) -> Optional[str]:
        """Получение уникального ключа для дедупликации"""
        return attributes.get('cad_number') or attributes.get('numb_border')

    def _extract_zone_lists(self, record, attributes: Dict):
        """Извлечение списков для zones_and_territories"""
        # Основные виды разрешенного использования
        primary_uses = [
            t.text.strip() for t in record.findall(".//permitted_primary_uses//permitted_use_text")
            if t.text and t.text.strip()
        ]
        if primary_uses:
            attributes['permitted_uses_primary'] = "; ".join(primary_uses)

        # Условно разрешенные виды
        cond_uses = [
            t.text.strip() for t in record.findall(".//permitted_conditionally_uses//permitted_use_text")
            if t.text and t.text.strip()
        ]
        if cond_uses:
            attributes['permitted_uses_cond'] = "; ".join(cond_uses)

        # Входящие участки
        parcels = [
            t.text.strip() for t in record.findall(".//included_parcels/includ_parcel/cad_number")
            if t.text and t.text.strip()
        ]
        if parcels:
            attributes['included_parcels_list'] = "; ".join(parcels)

        # Реквизиты документов
        doc_names, doc_numbers, doc_dates, doc_issuers = [], [], [], []
        for decision in record.findall(".//decisions_requisites/decision_requisites"):
            doc_names.append(decision.findtext("document_name", "").strip())
            doc_numbers.append(decision.findtext("document_number", "").strip())
            doc_dates.append(decision.findtext("document_date", "").strip())
            doc_issuers.append(decision.findtext("document_issuer", "").strip())

        if any(doc_names):
            attributes["doc_name"] = "; ".join(filter(None, doc_names))
        if any(doc_numbers):
            attributes["doc_number"] = "; ".join(filter(None, doc_numbers))
        if any(doc_dates):
            attributes["doc_date"] = "; ".join(filter(None, doc_dates))
        if any(doc_issuers):
            attributes["doc_issuer"] = "; ".join(filter(None, doc_issuers))
