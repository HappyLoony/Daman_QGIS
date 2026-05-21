# -*- coding: utf-8 -*-
"""
Fsm_1_1_8_1 - Парсер XML interact_entry_boundaries v2.0.1

MVP: обрабатывается ТОЛЬКО ветка public_easement (граница публичного сервитута,
type_boundary=18). Остальные 7 типов границ (zones_and_territories,
forestry_boundaries, охранные зоны и т.д.) на этом этапе пропускаются.

Структура XML (упрощённая):

  interact_entry_boundaries[@guid, @version="02"]
    information_registry_boundaries
      information_registry_boundary
        type_boundary                       (значение "18" = публичный сервитут)
        name_object
        all_border_or_part_border
        information_boundary
          public_easement
            establishment_public_easement | changing_public_easement
              [reg_numb_border]             (только в changing_*)
              object_public_easement
                quarter_cad_number
                locations/location/{AdrCi2:fias, okato, kladr, oktmo, region}
                name_by_doc
                authority_decision
              parameter_public_easement
                purpose_public_easement     (код dPurposePublicEasement)
                period_type/{deal_validity_time | start_date/end_date | indefinitely}
                holder_public_easement      (Holder: legal_entity | individual)
                purpose_other
              contours_location             (EnSpa2:BoundContoursLocation)
                contours/contour/entity_spatial/{sk_code, spatials_elements/...}

ПРИНЦИП РАБОТЫ С NAMESPACES:
- Сразу после парсинга XML переписываем tag на localname для всех элементов:
    elem.tag = etree.QName(elem.tag).localname
- Это позволяет искать через findall('.//public_easement') без явных ns-dict.
- Тот же приём нужен для геометрии (extract_geometry ищет './/contour'
  и './/spatial_element' без префиксов namespace).

ПРИНЦИП РАБОТЫ С ОТСУТСТВУЮЩИМИ ДАННЫМИ:
- CLAUDE.md: "Данные отсутствуют в XML -> возвращать None, НЕ писать fallback'и."
- Все optional-поля при отсутствии в XML записываются как None (NULL в GPKG).
"""

import os
from typing import Optional, Dict, Any, List

from Daman_QGIS.utils import log_info, log_warning, log_error


# type_boundary=18 = граница публичного сервитута (Приказ Росреестра П/0104/25)
TYPE_BOUNDARY_PUBLIC_EASEMENT = '18'


def _strip_all_namespaces(root) -> None:
    """
    Переписать tag всех элементов дерева на localname.

    После этой операции lxml/ElementTree-поиск через './/tag' работает
    без явных namespaces-dict, что упрощает парсинг прикладных XML с
    несколькими namespaces (default + 6 prefixed в interact_entry_boundaries).

    Args:
        root: корневой XML элемент (lxml.etree._Element или xml.etree.Element)
    """
    try:
        from lxml import etree
        for elem in root.iter():
            tag = elem.tag
            if isinstance(tag, str) and tag.startswith('{'):
                elem.tag = etree.QName(tag).localname
    except ImportError:
        # Fallback на xml.etree - переписываем через regex
        import re
        ns_pattern = re.compile(r'^\{[^}]*\}')
        for elem in root.iter():
            tag = elem.tag
            if isinstance(tag, str) and tag.startswith('{'):
                elem.tag = ns_pattern.sub('', tag)


def _findtext(elem, path: str) -> Optional[str]:
    """Безопасная обёртка над findtext, возвращающая None для пустых/отсутствующих строк."""
    if elem is None:
        return None
    value = elem.findtext(path)
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def _parse_holder(holder_root) -> Dict[str, Optional[str]]:
    """
    Извлечь атрибуты держателя сервитута.

    Поддерживает только legal_entity (юрлицо) в этом MVP.
    Для individual (физлицо) возвращает holder_type='individual', остальные поля=None.

    Args:
        holder_root: XML элемент <holder_public_easement>

    Returns:
        Dict с ключами holder_type, holder_name, holder_inn, holder_ogrn
    """
    result = {
        'holder_type': None,
        'holder_name': None,
        'holder_inn': None,
        'holder_ogrn': None,
    }

    if holder_root is None:
        return result

    legal = holder_root.find('legal_entity')
    if legal is not None:
        result['holder_type'] = 'legal_entity'
        # Имя/ИНН/ОГРН лежат под entity_govement/resident или entity_business/resident
        # На MVP-уровне ищем рекурсивно - данные не дублируются в одном holder'е.
        result['holder_name'] = _findtext(legal, './/full_name')
        result['holder_inn'] = _findtext(legal, './/inn')
        result['holder_ogrn'] = _findtext(legal, './/ogrn')
        return result

    individual = holder_root.find('individual')
    if individual is not None:
        result['holder_type'] = 'individual'
        # MVP: individual оставляем без детальной разборки ФИО
        # (Holder schema 2.0.1 имеет несколько вариантов представления physical_person).
        return result

    return result


def _parse_period(parameter_root) -> Dict[str, Any]:
    """
    Извлечь параметры срока действия сервитута.

    period_type может содержать ОДНО из:
    - deal_validity_time (свободная строка, например "10 лет")
    - start_date + end_date (явные даты ISO)
    - indefinitely (флаг "бессрочно")

    Args:
        parameter_root: XML элемент <parameter_public_easement>

    Returns:
        Dict с ключами period_text, period_start, period_end, period_indefinite
    """
    result = {
        'period_text': None,
        'period_start': None,
        'period_end': None,
        'period_indefinite': False,
    }

    if parameter_root is None:
        return result

    period = parameter_root.find('period_type')
    if period is None:
        return result

    deal_time = _findtext(period, 'deal_validity_time')
    if deal_time:
        result['period_text'] = deal_time

    start = _findtext(period, 'start_date')
    if start:
        result['period_start'] = start

    end = _findtext(period, 'end_date')
    if end:
        result['period_end'] = end

    indefinite = period.find('indefinitely')
    if indefinite is not None:
        result['period_indefinite'] = True

    return result


def _extract_public_easement_attributes(
    information_boundary_record,
    file_path: str,
) -> Optional[Dict[str, Any]]:
    """
    Извлечь все атрибуты public_easement из одного information_registry_boundary.

    Args:
        information_boundary_record: XML элемент <information_registry_boundary>
        file_path: путь к исходному XML (для source_file)

    Returns:
        Dict с атрибутами слоя или None если ветка public_easement отсутствует.
    """
    info_boundary = information_boundary_record.find('information_boundary')
    if info_boundary is None:
        return None

    pe_root = info_boundary.find('public_easement')
    if pe_root is None:
        # Этот information_registry_boundary имеет другой тип (не сервитут)
        return None

    # public_easement содержит ровно одно из: establishment_public_easement | changing_public_easement
    is_changing = False
    pe_branch = pe_root.find('establishment_public_easement')
    if pe_branch is None:
        pe_branch = pe_root.find('changing_public_easement')
        if pe_branch is not None:
            is_changing = True

    if pe_branch is None:
        log_warning(
            f"Fsm_1_1_8_1: В {os.path.basename(file_path)} не найдена ветка "
            f"establishment_public_easement / changing_public_easement"
        )
        return None

    # type_boundary, name_object - на уровне information_registry_boundary
    type_boundary_str = _findtext(information_boundary_record, 'type_boundary')
    type_boundary_int: Optional[int] = None
    if type_boundary_str:
        try:
            type_boundary_int = int(type_boundary_str)
        except ValueError:
            log_warning(
                f"Fsm_1_1_8_1: некорректный type_boundary='{type_boundary_str}' "
                f"в {os.path.basename(file_path)}"
            )

    name_object = _findtext(information_boundary_record, 'name_object')

    # reg_numb_border - только в changing_*
    reg_numb_border = _findtext(pe_branch, 'reg_numb_border') if is_changing else None

    # object_public_easement
    object_pe = pe_branch.find('object_public_easement')
    quarter_cad_number = _findtext(object_pe, 'quarter_cad_number')
    name_by_doc = _findtext(object_pe, 'name_by_doc')
    authority_decision = _findtext(object_pe, 'authority_decision')

    # parameter_public_easement
    parameter_pe = pe_branch.find('parameter_public_easement')
    purpose_pe = _findtext(parameter_pe, 'purpose_public_easement')
    purpose_other = _findtext(parameter_pe, 'purpose_other')

    period_attrs = _parse_period(parameter_pe)
    holder_attrs = _parse_holder(
        parameter_pe.find('holder_public_easement') if parameter_pe is not None else None
    )

    # sk_code - из contours_location/contours/contour/entity_spatial
    sk_code: Optional[str] = None
    contours_loc = pe_branch.find('contours_location')
    if contours_loc is not None:
        entity_spatial = contours_loc.find('.//entity_spatial')
        if entity_spatial is not None:
            sk_code = _findtext(entity_spatial, 'sk_code')

    attributes: Dict[str, Any] = {
        'type_boundary': type_boundary_int,
        'name_object': name_object,
        'is_changing': is_changing,
        'reg_numb_border': reg_numb_border,
        'quarter_cad_number': quarter_cad_number,
        'name_by_doc': name_by_doc,
        'authority_decision': authority_decision,
        'purpose_public_easement': purpose_pe,
        'purpose_other': purpose_other,
        'sk_code': sk_code,
        'source_file': os.path.basename(file_path),
    }
    attributes.update(period_attrs)
    attributes.update(holder_attrs)

    # Сохраняем ссылку на ветку для последующего извлечения геометрии
    attributes['_pe_branch_element'] = pe_branch

    return attributes


def parse_iboundary_xml(file_path: str) -> List[Dict[str, Any]]:
    """
    Распарсить один XML interact_entry_boundaries.

    На MVP-уровне: обходит все information_registry_boundary, обрабатывает только те,
    у которых information_boundary содержит ветку public_easement. Остальные
    логируются как warning и пропускаются.

    Args:
        file_path: путь к XML файлу

    Returns:
        Список словарей с атрибутами + 'guid' + '_pe_branch_element' для геометрии.
        Пустой список если файл не содержит ни одной ветки public_easement.
    """
    if not os.path.exists(file_path):
        log_error(f"Fsm_1_1_8_1: Файл не найден: {file_path}")
        return []

    # Парсим XML через lxml (или fallback на xml.etree)
    try:
        from lxml import etree as ET  # type: ignore[import-not-found]
    except ImportError:
        import xml.etree.ElementTree as ET  # type: ignore[no-redef]

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
    except Exception as e:
        log_error(f"Fsm_1_1_8_1: Ошибка парсинга XML {os.path.basename(file_path)}: {e}")
        return []

    # GUID документа - атрибут root до strip namespaces (атрибуты без namespace
    # обычно не имеют prefix, но безопасно прочитать ДО переписывания tag).
    doc_guid = root.get('guid')

    # Стрипаем namespaces для упрощения поиска
    _strip_all_namespaces(root)

    info_registry = root.find('information_registry_boundaries')
    if info_registry is None:
        log_warning(
            f"Fsm_1_1_8_1: В {os.path.basename(file_path)} не найден "
            f"information_registry_boundaries"
        )
        return []

    boundaries = info_registry.findall('information_registry_boundary')
    if not boundaries:
        log_warning(
            f"Fsm_1_1_8_1: В {os.path.basename(file_path)} не найдено ни одного "
            f"information_registry_boundary"
        )
        return []

    features: List[Dict[str, Any]] = []
    skipped_non_pe = 0

    for boundary in boundaries:
        type_boundary_str = _findtext(boundary, 'type_boundary')

        # MVP: обрабатываем только публичный сервитут (type_boundary=18)
        # Для других типов попробуем извлечь, но в parser логике public_easement
        # вернёт None если ветки нет - тогда пропускаем.
        attrs = _extract_public_easement_attributes(boundary, file_path)
        if attrs is None:
            skipped_non_pe += 1
            log_info(
                f"Fsm_1_1_8_1: Пропущена граница типа {type_boundary_str or '?'} в "
                f"{os.path.basename(file_path)} (MVP обрабатывает только public_easement)"
            )
            continue

        # Sanity-check: если type_boundary != 18, но ветка public_easement всё же
        # присутствует - логируем warning, но обрабатываем (схема допускает).
        if attrs['type_boundary'] != int(TYPE_BOUNDARY_PUBLIC_EASEMENT):
            log_warning(
                f"Fsm_1_1_8_1: Ветка public_easement найдена с неожиданным "
                f"type_boundary={attrs['type_boundary']} в {os.path.basename(file_path)}"
            )

        attrs['guid'] = doc_guid
        features.append(attrs)

    if not features:
        log_warning(
            f"Fsm_1_1_8_1: В {os.path.basename(file_path)} нет ни одной "
            f"границы public_easement (пропущено границ других типов: {skipped_non_pe})"
        )
    else:
        log_info(
            f"Fsm_1_1_8_1: {os.path.basename(file_path)} - извлечено "
            f"{len(features)} public_easement (пропущено других типов: {skipped_non_pe})"
        )

    return features
