# -*- coding: utf-8 -*-
"""
Fsm_5_3_6 - Экспорт перечней кадастровых номеров

Экспортирует списки кадастровых номеров ЗУ, ОКС и Кварталов в Excel.
Поддерживает фильтрацию по границам проекта и сортировку по числовому порядку.

Шаблоны: Fsm_5_3_8_template_registry.py (DocumentTemplate)
Форматы: Fsm_5_3_4_format_manager.py (ExcelFormatManager)
"""

import os
from typing import List, Dict, Any, Optional, Tuple

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsGeometry,
    QgsFeatureRequest, QgsCoordinateTransform
)

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers import registry, FolderType

from .Fsm_5_3_4_format_manager import ExcelFormatManager
from .Fsm_5_3_5_export_utils import ExportUtils
from .Fsm_5_3_8_template_registry import (
    DocumentTemplate, TemplateRegistry, CADNUM_FIELD_ALTERNATIVES,
    BOUNDARIES_LAYER_NAME
)


class Fsm_5_3_6_CadnumList:
    """Экспортёр перечней кадастровых номеров"""

    def __init__(self, iface, ref_managers=None):
        """
        Инициализация экспортёра

        Args:
            iface: Интерфейс QGIS
            ref_managers: Reference managers (опционально)
        """
        self.iface = iface
        self.ref_managers = ref_managers
        self._boundaries_geom: Optional[QgsGeometry] = None
        self._boundaries_crs = None

    def export(
        self,
        output_folder: Optional[str] = None,
        filter_by_boundaries: bool = True
    ) -> Tuple[bool, str]:
        """
        Экспорт перечней кадастровых номеров в Excel

        Автоматически находит все cadnum_list шаблоны и экспортирует данные.

        Args:
            output_folder: Папка для сохранения (если None - папка Документы проекта)
            filter_by_boundaries: Фильтровать по границам L_1_1_1

        Returns:
            Tuple[bool, str]: (успешность, путь к файлу)
        """
        try:
            import xlsxwriter
        except ImportError:
            log_error("Fsm_5_3_6: Библиотека xlsxwriter не установлена")
            return False, ""

        # Определяем папку вывода
        if not output_folder:
            output_folder = self._get_output_folder()
            if not output_folder:
                log_error("Fsm_5_3_6: Не удалось определить папку для сохранения")
                return False, ""

        ExportUtils.ensure_folder_exists(output_folder)

        # Кэшируем геометрию границ если нужна фильтрация
        if filter_by_boundaries:
            self._cache_boundaries_geometry()

        # Получаем все cadnum_list шаблоны
        templates = TemplateRegistry.get_templates_by_type('cadnum_list')

        # Собираем данные по каждому шаблону
        data: Dict[str, Tuple[DocumentTemplate, List[str]]] = {}
        for template in templates:
            cadnums = self._collect_cadnums_for_template(template, filter_by_boundaries)
            if cadnums:
                data[template.template_id] = (template, cadnums)

        # Проверяем что есть данные
        total_count = sum(len(v[1]) for v in data.values())
        if total_count == 0:
            log_warning("Fsm_5_3_6: Нет данных для экспорта")
            return False, ""

        # Создаём Excel файл
        filepath = os.path.join(output_folder, "Перечень_КН.xlsx")

        try:
            workbook = xlsxwriter.Workbook(filepath)
            fmt = ExcelFormatManager(workbook)

            header_format = fmt.get_header_format()
            data_format = fmt.get_data_format(align='left')

            count_format = workbook.add_format({
                'font_name': ExcelFormatManager.FONTS['default'],
                'font_size': 10,
                'italic': True,
                'align': 'right',
                'valign': 'vcenter'
            })

            for template, cadnums in data.values():
                sheet_name = template.cadnum_sheet_name or template.name
                worksheet = workbook.add_worksheet(sheet_name)

                worksheet.set_column(0, 0, 35)

                worksheet.write(0, 0, template.title_template, header_format)

                for row, cadnum in enumerate(cadnums, start=1):
                    worksheet.write(row, 0, cadnum, data_format)

                worksheet.write(len(cadnums) + 2, 0, f"Всего: {len(cadnums)}", count_format)

            workbook.close()

            log_info(f"Fsm_5_3_6: Перечень КН сохранён: {filepath}")
            for template, cadnums in data.values():
                sheet_name = template.cadnum_sheet_name or template.name
                log_info(f"Fsm_5_3_6:   {sheet_name}: {len(cadnums)}")

            return True, filepath

        except Exception as e:
            log_error(f"Fsm_5_3_6: Ошибка создания Excel: {str(e)}")
            return False, ""

    def _get_output_folder(self) -> Optional[str]:
        """Получить папку для сохранения документов"""
        try:
            structure_manager = registry.get('M_19')

            if not structure_manager.is_active():
                project_path = QgsProject.instance().homePath()
                if project_path:
                    structure_manager.project_root = project_path

            if structure_manager.is_active():
                return structure_manager.get_folder(FolderType.DOCUMENTS)

            return None
        except Exception as e:
            log_warning(f"Fsm_5_3_6: Ошибка получения папки: {str(e)}")
            return None

    def _cache_boundaries_geometry(self) -> None:
        """Кэшировать геометрию границ L_1_1_1"""
        try:
            layers = QgsProject.instance().mapLayersByName(BOUNDARIES_LAYER_NAME)
            if not layers:
                log_warning(f"Fsm_5_3_6: Слой {BOUNDARIES_LAYER_NAME} не найден")
                return

            layer = layers[0]
            if not isinstance(layer, QgsVectorLayer):
                return
            self._boundaries_crs = layer.crs()

            geometries = []
            for feature in layer.getFeatures():
                if feature.hasGeometry():
                    geom = feature.geometry()
                    if geom and not geom.isNull():
                        geometries.append(geom)

            if geometries:
                self._boundaries_geom = QgsGeometry.unaryUnion(geometries)
                log_info("Fsm_5_3_6: Геометрия границ загружена")

        except Exception as e:
            log_warning(f"Fsm_5_3_6: Ошибка загрузки границ: {str(e)}")

    def _collect_cadnums_for_template(
        self,
        template: DocumentTemplate,
        filter_by_boundaries: bool
    ) -> List[str]:
        """
        Собрать кадастровые номера для конкретного шаблона

        Args:
            template: Шаблон с определённым source_layers и cadnum_field
            filter_by_boundaries: Фильтровать по границам

        Returns:
            Отсортированный список уникальных КН
        """
        # Ищем слой по паттернам из шаблона
        layer = self._find_layer_for_template(template)
        if layer is None:
            return []

        # Определяем поле КН
        field_name = self._find_cadnum_field(layer, template.cadnum_field)
        if not field_name:
            log_warning(f"Fsm_5_3_6: Поле КН не найдено в слое {layer.name()}")
            return []

        # Собираем КН
        if filter_by_boundaries and self._boundaries_geom:
            cadnums = self._collect_with_filter(layer, field_name)
        else:
            cadnums = self._collect_all(layer, field_name)

        return self._sort_cadastral_numbers(list(cadnums))

    def _find_layer_for_template(self, template: DocumentTemplate) -> Optional[QgsVectorLayer]:
        """Найти слой по паттернам шаблона"""
        for pattern in template.source_layers:
            layers = QgsProject.instance().mapLayersByName(pattern)
            if layers and isinstance(layers[0], QgsVectorLayer):
                return layers[0]

        # Пробуем fallback
        if template.cadnum_fallback_layer:
            layers = QgsProject.instance().mapLayersByName(template.cadnum_fallback_layer)
            if layers and isinstance(layers[0], QgsVectorLayer):
                log_info(f"Fsm_5_3_6: Используется fallback слой {template.cadnum_fallback_layer}")
                return layers[0]

        log_warning(f"Fsm_5_3_6: Слой для шаблона '{template.name}' не найден")
        return None

    def _find_cadnum_field(
        self,
        layer: QgsVectorLayer,
        preferred_field: Optional[str]
    ) -> Optional[str]:
        """Найти поле КН в слое"""
        if preferred_field and layer.fields().indexOf(preferred_field) >= 0:
            return preferred_field

        for alt in CADNUM_FIELD_ALTERNATIVES:
            if layer.fields().indexOf(alt) >= 0:
                return alt

        return None

    def _collect_all(self, layer: QgsVectorLayer, field_name: str) -> set:
        """Собрать все КН из слоя без фильтрации"""
        cadnums: set = set()

        for feature in layer.getFeatures():
            value = feature[field_name]
            if value and str(value).strip() and str(value) not in ['NULL', 'None', '-']:
                cadnums.add(str(value).strip())

        return cadnums

    def _collect_with_filter(self, layer: QgsVectorLayer, field_name: str) -> set:
        """Собрать КН с фильтрацией по границам"""
        cadnums: set = set()

        if not self._boundaries_geom or not self._boundaries_crs:
            return self._collect_all(layer, field_name)

        transform = None
        if layer.crs() != self._boundaries_crs:
            transform = QgsCoordinateTransform(
                layer.crs(), self._boundaries_crs, QgsProject.instance()
            )

        bbox = self._boundaries_geom.boundingBox()
        if transform:
            transform_back = QgsCoordinateTransform(
                self._boundaries_crs, layer.crs(), QgsProject.instance()
            )
            bbox = transform_back.transformBoundingBox(bbox)

        request = QgsFeatureRequest()
        request.setFilterRect(bbox)

        for feature in layer.getFeatures(request):
            if not feature.hasGeometry():
                continue

            geom = feature.geometry()
            if geom.isNull():
                continue

            if transform:
                geom = QgsGeometry(geom)
                geom.transform(transform)

            if geom.intersects(self._boundaries_geom):
                value = feature[field_name]
                if value and str(value).strip() and str(value) not in ['NULL', 'None', '-']:
                    cadnums.add(str(value).strip())

        return cadnums

    def _sort_cadastral_numbers(self, cadnums: List[str]) -> List[str]:
        """
        Сортировка кадастровых номеров по числовому порядку

        КН имеет формат AA:BB:CCCCCC:DD - сортируем по каждой части как числу.
        """
        def parse_cadnum(cadnum: str) -> Tuple:
            try:
                parts = cadnum.split(':')
                return tuple(int(part) for part in parts)
            except (ValueError, AttributeError):
                return (999999, 999999, 999999, 999999)

        return sorted(cadnums, key=parse_cadnum)

    # === API для интеграции с DocumentFactory ===

    def export_layer(
        self,
        layer: QgsVectorLayer,
        template: DocumentTemplate,
        output_folder: str,
        **kwargs: Any
    ) -> bool:
        """
        Метод для совместимости с BaseExporter интерфейсом

        Args:
            layer: Игнорируется (используем фиксированные слои из шаблонов)
            template: Шаблон документа
            output_folder: Папка для сохранения
            **kwargs: Дополнительные параметры

        Returns:
            bool: Успешность экспорта
        """
        success, _ = self.export(
            output_folder=output_folder,
            filter_by_boundaries=kwargs.get('filter_by_boundaries', True)
        )
        return success
