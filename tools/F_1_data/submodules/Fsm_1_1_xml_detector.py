# -*- coding: utf-8 -*-
"""
Fsm_1_1_xml_detector - Определение типа XML файла (КПТ vs Выписка vs Уведомление о границах)
"""

import os
import re
from typing import Optional
from Daman_QGIS.utils import log_info, log_warning
from Daman_QGIS.constants import ROOT_TAG_TO_RECORD_MAP


# Regex для извлечения localname из Clark-notation lxml tag ("{ns}localname" -> "localname")
_CLARK_NS_RE = re.compile(r'^\{[^}]*\}')


def _strip_namespace(tag: str) -> str:
    """
    Удалить namespace prefix из lxml Clark-notation tag.

    Поддерживает оба варианта:
    - '{urn://...}interact_entry_boundaries' -> 'interact_entry_boundaries' (с default xmlns)
    - 'extract_cadastral_plan_territory' -> 'extract_cadastral_plan_territory' (без xmlns)

    Args:
        tag: lxml tag (Clark notation или чистое имя)

    Returns:
        Локальное имя элемента
    """
    if not tag:
        return tag
    return _CLARK_NS_RE.sub('', tag)


class XmlTypeDetector:
    """Детектор типа XML файла"""

    # Root tag для КПТ
    KPT_ROOT_TAG = 'extract_cadastral_plan_territory'

    # Root tag для уведомлений о внесении сведений в реестр границ
    # interact_entry_boundaries v2.0.1 (Приказ Росреестра П/0104/25 от 27.02.2026)
    IBOUNDARY_ROOT_TAG = 'interact_entry_boundaries'

    # Root tags для выписок ЕГРН - автоматически синхронизируется с ROOT_TAG_TO_RECORD_MAP
    # Исключаем 'extract_about_zone' (зоны, не выписки)
    VYPISKA_ROOT_TAGS = {
        tag for tag in ROOT_TAG_TO_RECORD_MAP.keys()
        if tag != 'extract_about_zone'
    }

    @staticmethod
    def detect_xml_type(file_path: str) -> Optional[str]:
        """
        Определить тип XML файла (оптимизировано через iterparse)

        Args:
            file_path: Путь к XML файлу

        Returns:
            'KPT' - кадастровый план территории
            'VYPISKA' - выписка ЕГРН
            'IBOUNDARY' - уведомление о внесении сведений в реестр границ
            None - неизвестный тип
        """
        if not os.path.exists(file_path):
            return None

        try:
            # Пытаемся использовать lxml для быстрого парсинга
            try:
                from lxml import etree as ET  # type: ignore[import-not-found]
                use_lxml = True
            except ImportError:
                # Fallback на xml.etree
                import xml.etree.ElementTree as ET
                use_lxml = False

            root_tag = None

            if use_lxml:
                # Оптимизированный путь с lxml iterparse - не загружает все дерево
                with open(file_path, 'rb') as f:
                    for event, elem in ET.iterparse(f, events=('start',)):
                        root_tag = elem.tag
                        break  # Получили root tag - прерываем парсинг
            else:
                # Fallback для xml.etree - полный парсинг
                with open(file_path, 'rb') as f:
                    tree = ET.parse(f)
                    root_tag = tree.getroot().tag

            if not root_tag:
                return None

            # КРИТИЧНО: lxml возвращает Clark-notation для элементов с xmlns
            # ('{urn://...}interact_entry_boundaries' вместо 'interact_entry_boundaries').
            # КПТ-XML не имеют default xmlns, выписки не имеют, interact_entry_boundaries имеет.
            # Универсальное решение - стрипать namespace prefix всегда.
            local_name = _strip_namespace(root_tag)

            if local_name == XmlTypeDetector.KPT_ROOT_TAG:
                return 'KPT'
            elif local_name == XmlTypeDetector.IBOUNDARY_ROOT_TAG:
                return 'IBOUNDARY'
            elif local_name in XmlTypeDetector.VYPISKA_ROOT_TAGS:
                return 'VYPISKA'
            else:
                log_warning(f"Fsm_1_1_detector: Неизвестный root tag в XML: {root_tag}")
                return None

        except Exception as e:
            log_warning(f"Fsm_1_1_detector: Ошибка определения типа XML файла {os.path.basename(file_path)}: {e}")
            return None

    @staticmethod
    def classify_files(file_paths: list) -> dict:
        """
        Классифицировать список XML файлов

        Args:
            file_paths: Список путей к файлам

        Returns:
            {
                'KPT': [file1, file2, ...],
                'VYPISKA': [file3, file4, ...],
                'IBOUNDARY': [file6, ...],
                'UNKNOWN': [file5, ...]
            }
        """
        classified = {
            'KPT': [],
            'VYPISKA': [],
            'IBOUNDARY': [],
            'UNKNOWN': []
        }

        for file_path in file_paths:
            xml_type = XmlTypeDetector.detect_xml_type(file_path)
            if xml_type == 'KPT':
                classified['KPT'].append(file_path)
            elif xml_type == 'VYPISKA':
                classified['VYPISKA'].append(file_path)
            elif xml_type == 'IBOUNDARY':
                classified['IBOUNDARY'].append(file_path)
            else:
                classified['UNKNOWN'].append(file_path)

        return classified
