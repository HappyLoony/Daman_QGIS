# -*- coding: utf-8 -*-
"""
Fsm_6_3_3 - Фабрика документов

Создаёт экспортёры документов по типу из Base_documents.json.
Предоставляет унифицированный интерфейс для получения списка
доступных документов для слоя.
"""

from typing import Dict, Any, List, Optional, Type
import re

from qgis.core import QgsVectorLayer

from Daman_QGIS.utils import log_info, log_debug, log_warning


class BaseExporter:
    """Базовый класс экспортёра документов"""

    def __init__(self, iface, ref_managers):
        """
        Инициализация базового экспортёра

        Args:
            iface: Интерфейс QGIS
            ref_managers: Reference managers
        """
        self.iface = iface
        self.ref_managers = ref_managers

    def export(
        self,
        layer: QgsVectorLayer,
        style: Dict[str, Any],
        output_folder: str,
        **kwargs
    ) -> bool:
        """
        Экспорт слоя в документ

        Args:
            layer: Слой для экспорта
            style: Стиль из базы данных
            output_folder: Папка для сохранения
            **kwargs: Дополнительные параметры

        Returns:
            bool: Успешность экспорта
        """
        raise NotImplementedError("Метод export() должен быть реализован в подклассе")

    def get_output_filename(self, layer: QgsVectorLayer, style: Dict[str, Any]) -> str:
        """
        Получить имя выходного файла

        Args:
            layer: Слой
            style: Стиль

        Returns:
            str: Имя файла
        """
        raise NotImplementedError("Метод get_output_filename() должен быть реализован в подклассе")


class DocumentFactory:
    """
    Фабрика для создания экспортёров документов

    Использует Base_documents.json для определения доступных документов
    и создаёт соответствующие экспортёры по типу.
    """

    def __init__(self, iface, ref_managers):
        """
        Инициализация фабрики

        Args:
            iface: Интерфейс QGIS
            ref_managers: Reference managers
        """
        self.iface = iface
        self.ref_managers = ref_managers
        self._exporter_cache: Dict[str, BaseExporter] = {}

    def get_exporter(self, document_type: str) -> Optional[BaseExporter]:
        """
        Получить экспортёр по типу документа

        Args:
            document_type: Тип документа ('coordinate_list', 'attribute_list', 'cadnum_list')

        Returns:
            Экземпляр экспортёра или None если тип не поддерживается
        """
        # Используем кэш для повторного использования экспортёров
        if document_type in self._exporter_cache:
            return self._exporter_cache[document_type]

        exporter = None

        if document_type == 'coordinate_list':
            from .Fsm_6_3_1_coordinate_list import Fsm_6_3_1_CoordinateList
            exporter = CoordinateListExporterAdapter(
                Fsm_6_3_1_CoordinateList(self.iface, self.ref_managers)
            )

        elif document_type == 'attribute_list':
            from .Fsm_6_3_2_attribute_list import Fsm_6_3_2_AttributeList
            exporter = AttributeListExporterAdapter(
                Fsm_6_3_2_AttributeList(self.iface, self.ref_managers)
            )

        elif document_type == 'cadnum_list':
            from .Fsm_6_3_6_cadnum_list import Fsm_6_3_6_CadnumList
            exporter = CadnumListExporterAdapter(
                Fsm_6_3_6_CadnumList(self.iface, self.ref_managers)
            )

        elif document_type == 'gpmt_coordinates':
            from .Fsm_6_3_7_gpmt_documents import Fsm_6_3_7_GPMTDocuments
            exporter = GPMTExporterAdapter(
                Fsm_6_3_7_GPMTDocuments(self.iface, self.ref_managers),
                doc_type='coordinates'
            )

        elif document_type == 'gpmt_characteristics':
            from .Fsm_6_3_7_gpmt_documents import Fsm_6_3_7_GPMTDocuments
            exporter = GPMTExporterAdapter(
                Fsm_6_3_7_GPMTDocuments(self.iface, self.ref_managers),
                doc_type='characteristics'
            )

        elif document_type == 'custom':
            log_warning("Fsm_6_3_3: Тип 'custom' требует специальной реализации")
            return None

        else:
            log_warning(f"Fsm_6_3_3: Неизвестный тип документа: {document_type}")
            return None

        if exporter:
            self._exporter_cache[document_type] = exporter

        return exporter

    def get_available_documents(self, layer: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Получить список доступных документов для слоя

        Ищет в Base_documents.json документы, чьи source_layers
        соответствуют имени слоя (поддерживает wildcard через *)

        Args:
            layer: Слой QGIS

        Returns:
            Список документов [{document_id, document_name, document_type, ...}, ...]
        """
        if layer is None:
            return []

        layer_name = layer.name()
        available = []

        # Загружаем документы из Base_documents.json
        documents = self._load_documents_config()

        for doc in documents:
            source_layers = doc.get('source_layers', [])

            # Проверяем соответствие имени слоя
            if self._matches_layer(layer_name, source_layers):
                available.append(doc)
                log_debug(f"Fsm_6_3_3: Документ '{doc.get('document_name')}' доступен для слоя '{layer_name}'")

        log_info(f"Fsm_6_3_3: Найдено {len(available)} документов для слоя '{layer_name}'")
        return available

    def get_document_by_id(self, document_id: str) -> Optional[Dict[str, Any]]:
        """
        Получить конфигурацию документа по ID

        Args:
            document_id: ID документа из Base_documents.json

        Returns:
            Конфигурация документа или None
        """
        documents = self._load_documents_config()

        for doc in documents:
            if doc.get('document_id') == document_id:
                return doc

        return None

    def get_all_document_types(self) -> List[str]:
        """
        Получить список всех поддерживаемых типов документов

        Returns:
            Список типов ['coordinate_list', 'attribute_list', ...]
        """
        return [
            'coordinate_list',
            'attribute_list',
            'cadnum_list',
            'gpmt_coordinates',
            'gpmt_characteristics',
            'custom'
        ]

    def _load_documents_config(self) -> List[Dict[str, Any]]:
        """
        Загрузить конфигурацию документов из Base_documents.json

        Returns:
            Список документов
        """
        try:
            # Используем ref_managers для загрузки Base_documents.json
            if hasattr(self.ref_managers, 'documents') and self.ref_managers.documents:
                return self.ref_managers.documents.get_all_documents()

            # Fallback: используем BaseReferenceLoader для remote загрузки
            from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader

            loader = BaseReferenceLoader()
            data = loader._load_json('Base_documents.json')

            if data is not None:
                return data

            log_warning("Fsm_6_3_3: Base_documents.json не найден")
            return []

        except Exception as e:
            log_warning(f"Fsm_6_3_3: Ошибка загрузки Base_documents.json: {str(e)}")
            return []

    def _matches_layer(self, layer_name: str, source_layers: List[str]) -> bool:
        """
        Проверить соответствие имени слоя списку source_layers

        Поддерживает:
        - Точное совпадение: "L_2_1_1_Выборка_ЗУ"
        - Префикс с wildcard: "Le_3_1_" (соответствует Le_3_1_1_*, Le_3_1_2_*, ...)
        - Полный wildcard: "L_3_*_Нарезка_*"

        Args:
            layer_name: Имя слоя
            source_layers: Список паттернов из Base_documents.json

        Returns:
            True если слой соответствует хотя бы одному паттерну
        """
        for pattern in source_layers:
            # Точное совпадение
            if pattern == layer_name:
                return True

            # Паттерн с wildcard (*)
            if '*' in pattern:
                # Конвертируем wildcard в regex
                regex_pattern = pattern.replace('*', '.*')
                if re.match(f'^{regex_pattern}$', layer_name):
                    return True

            # Паттерн как префикс (без *)
            elif layer_name.startswith(pattern):
                return True

        return False

    def clear_cache(self):
        """Очистить кэш экспортёров"""
        self._exporter_cache.clear()


class CoordinateListExporterAdapter(BaseExporter):
    """Адаптер для Fsm_6_3_1_CoordinateList к интерфейсу BaseExporter"""

    def __init__(self, coordinate_exporter):
        """
        Args:
            coordinate_exporter: Экземпляр Fsm_6_3_1_CoordinateList
        """
        self._exporter = coordinate_exporter
        self.iface = coordinate_exporter.iface
        self.ref_managers = coordinate_exporter.ref_managers

    def export(
        self,
        layer: QgsVectorLayer,
        style: Dict[str, Any],
        output_folder: str,
        **kwargs
    ) -> bool:
        """Экспорт через Fsm_6_3_1"""
        create_wgs84 = kwargs.get('create_wgs84', False)
        return self._exporter.export_layer(layer, style, output_folder, create_wgs84)

    def get_output_filename(self, layer: QgsVectorLayer, style: Dict[str, Any]) -> str:
        """Имя файла для перечня координат"""
        return f"Приложение_X_координаты.xlsx"


class AttributeListExporterAdapter(BaseExporter):
    """Адаптер для Fsm_6_3_2_AttributeList к интерфейсу BaseExporter"""

    def __init__(self, attribute_exporter):
        """
        Args:
            attribute_exporter: Экземпляр Fsm_6_3_2_AttributeList
        """
        self._exporter = attribute_exporter
        self.iface = attribute_exporter.iface
        self.ref_managers = attribute_exporter.ref_managers

    def export(
        self,
        layer: QgsVectorLayer,
        style: Dict[str, Any],
        output_folder: str,
        **kwargs
    ) -> bool:
        """Экспорт через Fsm_6_3_2"""
        return self._exporter.export_layer(layer, style, output_folder)

    def get_output_filename(self, layer: QgsVectorLayer, style: Dict[str, Any]) -> str:
        """Имя файла для ведомости"""
        from Daman_QGIS.managers import DataCleanupManager
        safe_name = DataCleanupManager().sanitize_filename(layer.name())
        return f"Ведомость_{safe_name}.xlsx"


class CadnumListExporterAdapter(BaseExporter):
    """Адаптер для Fsm_6_3_6_CadnumList к интерфейсу BaseExporter"""

    def __init__(self, cadnum_exporter):
        """
        Args:
            cadnum_exporter: Экземпляр Fsm_6_3_6_CadnumList
        """
        self._exporter = cadnum_exporter
        self.iface = cadnum_exporter.iface
        self.ref_managers = cadnum_exporter.ref_managers

    def export(
        self,
        layer: QgsVectorLayer,
        style: Dict[str, Any],
        output_folder: str,
        **kwargs
    ) -> bool:
        """Экспорт через Fsm_6_3_6"""
        return self._exporter.export_layer(layer, style, output_folder, **kwargs)

    def get_output_filename(self, layer: QgsVectorLayer, style: Dict[str, Any]) -> str:
        """Имя файла для перечня КН"""
        return "Перечень_КН.xlsx"


class GPMTExporterAdapter(BaseExporter):
    """Адаптер для Fsm_6_3_7_GPMTDocuments к интерфейсу BaseExporter"""

    def __init__(self, gpmt_exporter, doc_type: str = 'coordinates'):
        """
        Args:
            gpmt_exporter: Экземпляр Fsm_6_3_7_GPMTDocuments
            doc_type: Тип документа ('coordinates' или 'characteristics')
        """
        self._exporter = gpmt_exporter
        self._doc_type = doc_type
        self.iface = gpmt_exporter.iface
        self.ref_managers = gpmt_exporter.ref_managers

    def export(
        self,
        layer: QgsVectorLayer,
        style: Dict[str, Any],
        output_folder: str,
        **kwargs
    ) -> bool:
        """Экспорт через Fsm_6_3_7"""
        kwargs['gpmt_doc_type'] = self._doc_type
        return self._exporter.export_layer(layer, style, output_folder, **kwargs)

    def get_output_filename(self, layer: QgsVectorLayer, style: Dict[str, Any]) -> str:
        """Имя файла для документа ГПМТ"""
        if self._doc_type == 'characteristics':
            return "ГПМТ_характеристики.xlsx"
        return "ГПМТ_координаты.xlsx"
