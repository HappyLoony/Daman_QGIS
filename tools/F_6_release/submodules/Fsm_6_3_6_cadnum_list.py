# -*- coding: utf-8 -*-
"""
Fsm_6_3_6 - Экспорт перечней кадастровых номеров

Экспортирует списки кадастровых номеров ЗУ, ОКС и Кварталов в Excel.
Поддерживает фильтрацию по границам проекта и сортировку по числовому порядку.
"""

import os
from typing import List, Dict, Any, Optional, Tuple

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsGeometry,
    QgsFeatureRequest, QgsCoordinateTransform
)

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers import get_project_structure_manager, FolderType


class Fsm_6_3_6_CadnumList:
    """Экспортёр перечней кадастровых номеров"""

    # Конфигурация слоёв для сбора КН
    LAYER_CONFIG = {
        'zu': {
            'layer_name': 'Le_2_1_1_1_Выборка_ЗУ',
            'fallback': 'L_2_1_1_Выборка_ЗУ',
            'field': 'cad_num',
            'sheet_name': 'Земельные участки',
            'title': 'Кадастровый номер ЗУ'
        },
        'oks': {
            'layer_name': 'L_1_2_4_WFS_ОКС',
            'fallback': None,
            'field': 'cad_num',
            'sheet_name': 'ОКС',
            'title': 'Кадастровый номер ОКС'
        },
        'kk': {
            'layer_name': 'L_1_2_2_WFS_КК',
            'fallback': None,
            'field': 'cad_num',
            'sheet_name': 'Кадастровые кварталы',
            'title': 'Кадастровый номер КК'
        }
    }

    def __init__(self, iface, ref_managers=None):
        """
        Инициализация экспортёра

        Args:
            iface: Интерфейс QGIS
            ref_managers: Reference managers (опционально)
        """
        self.iface = iface
        self.ref_managers = ref_managers
        self._boundaries_geom = None
        self._boundaries_crs = None

    def export(
        self,
        output_folder: Optional[str] = None,
        include_zu: bool = True,
        include_oks: bool = True,
        include_kk: bool = True,
        filter_by_boundaries: bool = True
    ) -> Tuple[bool, str]:
        """
        Экспорт перечней кадастровых номеров в Excel

        Args:
            output_folder: Папка для сохранения (если None - папка Документы проекта)
            include_zu: Включить земельные участки
            include_oks: Включить объекты капитального строительства
            include_kk: Включить кадастровые кварталы
            filter_by_boundaries: Фильтровать по границам L_1_1_1

        Returns:
            Tuple[bool, str]: (успешность, путь к файлу)
        """
        try:
            import xlsxwriter
        except ImportError:
            log_error("Fsm_6_3_6: Библиотека xlsxwriter не установлена")
            return False, ""

        # Определяем папку вывода
        if not output_folder:
            output_folder = self._get_output_folder()
            if not output_folder:
                log_error("Fsm_6_3_6: Не удалось определить папку для сохранения")
                return False, ""

        os.makedirs(output_folder, exist_ok=True)

        # Кэшируем геометрию границ если нужна фильтрация
        if filter_by_boundaries:
            self._cache_boundaries_geometry()

        # Собираем данные
        data = {}
        if include_zu:
            data['zu'] = self._collect_cadnums('zu', filter_by_boundaries)
        if include_oks:
            data['oks'] = self._collect_cadnums('oks', filter_by_boundaries)
        if include_kk:
            data['kk'] = self._collect_cadnums('kk', filter_by_boundaries)

        # Проверяем что есть данные
        total_count = sum(len(v) for v in data.values())
        if total_count == 0:
            log_warning("Fsm_6_3_6: Нет данных для экспорта")
            return False, ""

        # Создаём Excel файл
        filepath = os.path.join(output_folder, "Перечень_КН.xlsx")

        try:
            workbook = xlsxwriter.Workbook(filepath)

            # Форматы
            header_format = workbook.add_format({
                'font_name': 'Times New Roman',
                'font_size': 12,
                'bold': True,
                'align': 'center',
                'valign': 'vcenter',
                'border': 1,
                'bg_color': '#DDEBF7'
            })

            cell_format = workbook.add_format({
                'font_name': 'Times New Roman',
                'font_size': 11,
                'align': 'left',
                'valign': 'vcenter',
                'border': 1
            })

            count_format = workbook.add_format({
                'font_name': 'Times New Roman',
                'font_size': 10,
                'italic': True,
                'align': 'right',
                'valign': 'vcenter'
            })

            # Создаём листы для каждого типа
            for key, cadnums in data.items():
                if not cadnums:
                    continue

                config = self.LAYER_CONFIG[key]
                worksheet = workbook.add_worksheet(config['sheet_name'])

                # Настройка ширины колонки
                worksheet.set_column(0, 0, 35)

                # Заголовок
                worksheet.write(0, 0, config['title'], header_format)

                # Данные
                for row, cadnum in enumerate(cadnums, start=1):
                    worksheet.write(row, 0, cadnum, cell_format)

                # Количество записей
                worksheet.write(len(cadnums) + 2, 0, f"Всего: {len(cadnums)}", count_format)

            workbook.close()

            # Логируем результат
            log_info(f"Fsm_6_3_6: Перечень КН сохранён: {filepath}")
            for key, cadnums in data.items():
                if cadnums:
                    config = self.LAYER_CONFIG[key]
                    log_info(f"Fsm_6_3_6:   {config['sheet_name']}: {len(cadnums)}")

            return True, filepath

        except Exception as e:
            log_error(f"Fsm_6_3_6: Ошибка создания Excel: {str(e)}")
            return False, ""

    def _get_output_folder(self) -> Optional[str]:
        """Получить папку для сохранения документов"""
        try:
            structure_manager = get_project_structure_manager()

            if not structure_manager.is_active():
                project_path = QgsProject.instance().homePath()
                if project_path:
                    structure_manager.project_root = project_path

            if structure_manager.is_active():
                return structure_manager.get_folder(FolderType.DOCUMENTS)

            return None
        except Exception as e:
            log_warning(f"Fsm_6_3_6: Ошибка получения папки: {str(e)}")
            return None

    def _cache_boundaries_geometry(self) -> None:
        """Кэшировать геометрию границ L_1_1_1"""
        try:
            layers = QgsProject.instance().mapLayersByName('L_1_1_1_Границы_работ')
            if not layers:
                log_warning("Fsm_6_3_6: Слой L_1_1_1_Границы_работ не найден")
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
                log_info(f"Fsm_6_3_6: Геометрия границ загружена")

        except Exception as e:
            log_warning(f"Fsm_6_3_6: Ошибка загрузки границ: {str(e)}")

    def _collect_cadnums(self, layer_type: str, filter_by_boundaries: bool) -> List[str]:
        """
        Собрать кадастровые номера из слоя

        Args:
            layer_type: Тип слоя ('zu', 'oks', 'kk')
            filter_by_boundaries: Фильтровать по границам

        Returns:
            Отсортированный список уникальных КН
        """
        config = self.LAYER_CONFIG.get(layer_type)
        if not config:
            return []

        # Ищем слой
        layer = self._find_layer(config['layer_name'], config.get('fallback'))
        if layer is None:
            return []

        # Проверяем поле
        field_name = config['field']
        if layer.fields().indexOf(field_name) < 0:
            # Пробуем альтернативные имена полей
            alt_names = ['КН', 'cad_num', 'cadnum', 'cadastral_number']
            field_name = None
            for alt in alt_names:
                if layer.fields().indexOf(alt) >= 0:
                    field_name = alt
                    break

            if not field_name:
                log_warning(f"Fsm_6_3_6: Поле КН не найдено в слое {layer.name()}")
                return []

        # Собираем КН
        cadnums = set()

        if filter_by_boundaries and self._boundaries_geom:
            cadnums = self._collect_with_filter(layer, field_name)
        else:
            cadnums = self._collect_all(layer, field_name)

        # Сортируем и возвращаем
        return self._sort_cadastral_numbers(list(cadnums))

    def _find_layer(self, layer_name: str, fallback: Optional[str]) -> Optional[QgsVectorLayer]:
        """Найти слой по имени с fallback"""
        layers = QgsProject.instance().mapLayersByName(layer_name)
        if layers and isinstance(layers[0], QgsVectorLayer):
            return layers[0]

        if fallback:
            layers = QgsProject.instance().mapLayersByName(fallback)
            if layers and isinstance(layers[0], QgsVectorLayer):
                log_info(f"Fsm_6_3_6: Используется fallback слой {fallback}")
                return layers[0]

        log_warning(f"Fsm_6_3_6: Слой {layer_name} не найден")
        return None

    def _collect_all(self, layer: QgsVectorLayer, field_name: str) -> set:
        """Собрать все КН из слоя без фильтрации"""
        cadnums = set()

        for feature in layer.getFeatures():
            value = feature[field_name]
            if value and str(value).strip() and str(value) not in ['NULL', 'None', '-']:
                cadnums.add(str(value).strip())

        return cadnums

    def _collect_with_filter(self, layer: QgsVectorLayer, field_name: str) -> set:
        """Собрать КН с фильтрацией по границам"""
        cadnums = set()

        if not self._boundaries_geom or not self._boundaries_crs:
            return self._collect_all(layer, field_name)

        # Трансформация координат если нужно
        transform = None
        if layer.crs() != self._boundaries_crs:
            transform = QgsCoordinateTransform(
                layer.crs(),
                self._boundaries_crs,
                QgsProject.instance()
            )

        # Получаем bbox для оптимизации
        bbox = self._boundaries_geom.boundingBox()
        if transform:
            transform_back = QgsCoordinateTransform(
                self._boundaries_crs,
                layer.crs(),
                QgsProject.instance()
            )
            bbox = transform_back.transformBoundingBox(bbox)

        # Запрос с фильтрацией по bbox
        request = QgsFeatureRequest()
        request.setFilterRect(bbox)

        for feature in layer.getFeatures(request):
            if not feature.hasGeometry():
                continue

            geom = feature.geometry()
            if geom.isNull():
                continue

            # Трансформируем если нужно
            if transform:
                geom = QgsGeometry(geom)
                geom.transform(transform)

            # Проверяем пересечение
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
        style: Dict[str, Any],
        output_folder: str,
        **kwargs
    ) -> bool:
        """
        Метод для совместимости с BaseExporter интерфейсом

        Args:
            layer: Игнорируется (используем фиксированные слои)
            style: Стиль (опционально)
            output_folder: Папка для сохранения
            **kwargs: Дополнительные параметры

        Returns:
            bool: Успешность экспорта
        """
        success, _ = self.export(
            output_folder=output_folder,
            include_zu=kwargs.get('include_zu', True),
            include_oks=kwargs.get('include_oks', True),
            include_kk=kwargs.get('include_kk', True),
            filter_by_boundaries=kwargs.get('filter_by_boundaries', True)
        )
        return success
