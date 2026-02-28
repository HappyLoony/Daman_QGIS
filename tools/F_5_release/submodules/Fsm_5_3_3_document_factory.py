# -*- coding: utf-8 -*-
"""
Fsm_5_3_3 - Фабрика документов

Маршрутизирует экспорт документов к нужному экспортёру на основе
doc_type из DocumentTemplate (Fsm_5_3_8_template_registry).

Шаблоны: Fsm_5_3_8_template_registry.py (DocumentTemplate, TemplateRegistry)
"""

from typing import Any, Optional

from qgis.core import QgsVectorLayer

from Daman_QGIS.utils import log_info, log_warning, log_error

from .Fsm_5_3_8_template_registry import DocumentTemplate


class DocumentFactory:
    """
    Фабрика для экспорта документов

    Создаёт экспортёры по типу документа и маршрутизирует вызовы.
    Экспортёры создаются лениво и кэшируются.
    """

    def __init__(self, iface, ref_managers=None):
        """
        Инициализация фабрики

        Args:
            iface: Интерфейс QGIS
            ref_managers: Reference managers (для AttributeList column_source)
        """
        self.iface = iface
        self.ref_managers = ref_managers
        self._coordinate_exporter = None
        self._attribute_exporter = None
        self._cadnum_exporter = None
        self._gpmt_exporter = None

    def export(
        self,
        layer: QgsVectorLayer,
        template: DocumentTemplate,
        output_folder: str,
        create_wgs84: bool = False,
        appendix_num: str = 'X',
        **kwargs: Any
    ) -> bool:
        """
        Экспорт документа через соответствующий экспортёр

        Args:
            layer: Слой для экспорта
            template: Шаблон документа из TemplateRegistry
            output_folder: Папка для сохранения
            create_wgs84: Создать версию в WGS-84
            appendix_num: Номер приложения для перечней координат
            **kwargs: Дополнительные параметры

        Returns:
            bool: Успешность экспорта
        """
        doc_type = template.doc_type

        if doc_type == 'coordinate_list':
            exporter = self._get_coordinate_exporter()
            return exporter.export_layer(
                layer, template, output_folder,
                create_wgs84=create_wgs84,
                appendix_num=appendix_num
            )

        elif doc_type == 'attribute_list':
            exporter = self._get_attribute_exporter()
            return exporter.export_layer(layer, template, output_folder)

        elif doc_type == 'cadnum_list':
            exporter = self._get_cadnum_exporter()
            return exporter.export_layer(
                layer, template, output_folder,
                **kwargs
            )

        elif doc_type in ('gpmt_coordinates', 'gpmt_characteristics'):
            exporter = self._get_gpmt_exporter()
            return exporter.export_layer(
                layer, template, output_folder,
                create_wgs84=create_wgs84
            )

        else:
            log_warning(f"Fsm_5_3_3: Неизвестный тип документа: {doc_type}")
            return False

    def _get_coordinate_exporter(self):
        """Получить экспортёр перечней координат (lazy)"""
        if self._coordinate_exporter is None:
            from .Fsm_5_3_1_coordinate_list import Fsm_5_3_1_CoordinateList
            self._coordinate_exporter = Fsm_5_3_1_CoordinateList(
                self.iface, self.ref_managers
            )
        return self._coordinate_exporter

    def _get_attribute_exporter(self):
        """Получить экспортёр ведомостей (lazy)"""
        if self._attribute_exporter is None:
            from .Fsm_5_3_2_attribute_list import Fsm_5_3_2_AttributeList
            self._attribute_exporter = Fsm_5_3_2_AttributeList(
                self.iface, self.ref_managers
            )
        return self._attribute_exporter

    def _get_cadnum_exporter(self):
        """Получить экспортёр перечней КН (lazy)"""
        if self._cadnum_exporter is None:
            from .Fsm_5_3_6_cadnum_list import Fsm_5_3_6_CadnumList
            self._cadnum_exporter = Fsm_5_3_6_CadnumList(
                self.iface, self.ref_managers
            )
        return self._cadnum_exporter

    def _get_gpmt_exporter(self):
        """Получить экспортёр документов ГПМТ (lazy)"""
        if self._gpmt_exporter is None:
            from .Fsm_5_3_7_gpmt_documents import Fsm_5_3_7_GPMTDocuments
            self._gpmt_exporter = Fsm_5_3_7_GPMTDocuments(
                self.iface, self.ref_managers
            )
        return self._gpmt_exporter

    @staticmethod
    def get_doc_type_name(doc_type: str) -> str:
        """
        Получить человеко-читаемое имя типа документа

        Args:
            doc_type: Тип документа из шаблона

        Returns:
            str: Локализованное имя типа
        """
        names = {
            'coordinate_list': 'Перечень координат',
            'attribute_list': 'Ведомость',
            'cadnum_list': 'Перечень КН',
            'gpmt_coordinates': 'Координаты ГПМТ',
            'gpmt_characteristics': 'Характеристики ГПМТ',
        }
        return names.get(doc_type, doc_type)
