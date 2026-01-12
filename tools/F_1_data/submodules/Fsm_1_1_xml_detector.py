# -*- coding: utf-8 -*-
"""
Fsm_1_1_xml_detector - Определение типа XML файла (КПТ vs Выписка)
"""

import os
from typing import Optional
from Daman_QGIS.utils import log_info, log_warning
from Daman_QGIS.constants import ROOT_TAG_TO_RECORD_MAP


class XmlTypeDetector:
    """Детектор типа XML файла"""

    # Root tag для КПТ
    KPT_ROOT_TAG = 'extract_cadastral_plan_territory'

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

            if root_tag == XmlTypeDetector.KPT_ROOT_TAG:
                return 'KPT'
            elif root_tag in XmlTypeDetector.VYPISKA_ROOT_TAGS:
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
                'UNKNOWN': [file5, ...]
            }
        """
        classified = {
            'KPT': [],
            'VYPISKA': [],
            'UNKNOWN': []
        }

        for file_path in file_paths:
            xml_type = XmlTypeDetector.detect_xml_type(file_path)
            if xml_type == 'KPT':
                classified['KPT'].append(file_path)
            elif xml_type == 'VYPISKA':
                classified['VYPISKA'].append(file_path)
            else:
                classified['UNKNOWN'].append(file_path)

        return classified
