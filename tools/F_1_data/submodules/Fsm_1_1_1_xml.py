# -*- coding: utf-8 -*-
"""
Сабмодуль импорта XML файлов Росреестра (КПТ)
Использует Fsm_1_1_5_KptImporter для обработки XML
"""

import os
from typing import Dict, Any, List, Optional, Union
from qgis.core import (
    QgsProject, QgsVectorLayer,
    QgsCoordinateReferenceSystem
)

from ..core import BaseImporter
from Daman_QGIS.utils import log_info, log_warning, log_error


class XmlImportSubmodule(BaseImporter):
    """Сабмодуль для импорта XML файлов Росреестра"""

    # Маппинг типов слоев из kd_kpt на слои Base_layers.json
    # Слои КПТ: L_1_5_* (комплексные кадастровые планы территории)
    LAYER_NUMBERING = {
        'land_record': 'L_1_5_1_ЗУ',
        'build_record': 'L_1_5_2_ОКС',
        'construction_record': 'L_1_5_2_ОКС',
        'object_under_construction_record': 'L_1_5_2_ОКС',
        'spatial_data': 'L_1_5_3_КК',
        'inhabited_locality_boundary_record': 'L_1_5_4_НП',
        'zones_and_territories_record': 'L_1_5_5_ЗОУИТ',
        'surveying_project_record': 'L_1_5_6_ТерЗоны',
        'public_easement_record': 'L_1_5_7_ПС',
        'coastline_record': 'L_1_5_8_Вода',
        'subject_boundary_record': 'L_1_5_4_НП',
        'municipal_boundary_record': 'L_1_5_4_НП'
    }

    # Суффиксы для типов геометрии
    GEOMETRY_SUFFIXES = {
        'pl': '_poly',
        'lin': '_line',
        'pt': '_point',
        'not': '_not'
    }

    def __init__(self, iface):
        """Инициализация сабмодуля"""
        super().__init__(iface)

        # Параметры по умолчанию
        self.default_params = {
            'filter_duplicate': True,
            'save_to_gpkg': True,
            'load_styles': True,
            'check_precision': True,
            'split': False,
            'organize_groups': True
        }

        self.kpt_importer = None
        self.gpkg_path = None
        self.parsing_errors: List[str] = []
        self.created_layers: List[QgsVectorLayer] = []

    def supports_format(self, file_extension: str) -> bool:
        """Проверка поддержки формата"""
        return file_extension.lower() in ['.xml']

    def import_file(self, file_path: Union[str, List[str]], **custom_params) -> Dict[str, Any]:
        """
        Импорт XML файла

        Args:
            file_path: Путь к XML файлу или список файлов
            **custom_params: Дополнительные параметры

        Returns:
            Результаты импорта
        """
        # Объединяем параметры
        params = self.merge_params(custom_params)

        # Если передан список файлов
        if isinstance(file_path, list):
            files = file_path
        else:
            files = [file_path]

        # Валидация
        for f in files:
            valid, msg = self.validate_import(f)
            if not valid:
                return {
                    'success': False,
                    'layers': [],
                    'message': msg,
                    'errors': [msg]
                }

        # Проверяем наличие lxml
        if not self._check_lxml():
            return {
                'success': False,
                'layers': [],
                'message': 'Требуется библиотека lxml для импорта XML',
                'errors': ['lxml не установлен']
            }

        # Инициализируем модуль
        if not self._init_kpt_importer():
            return {
                'success': False,
                'layers': [],
                'message': 'Не удалось инициализировать модуль импорта КПТ',
                'errors': ['Ошибка инициализации Fsm_1_1_5_KptImporter']
            }

        # Получаем СК проекта
        project_crs = self.get_project_crs()
        if not project_crs:
            project_crs = QgsCoordinateReferenceSystem("EPSG:32637")

        # Настраиваем пути для сохранения
        output_dir = ""
        if self.project_manager and self.project_manager.project_db:
            self.gpkg_path = self.project_manager.project_db.gpkg_path
            output_dir = os.path.dirname(self.gpkg_path)

        # Формируем опции для импортера
        kpt_options = {
            "files": files,
            "filter_duplicate": params.get('filter_duplicate', True),
            "save_to_file": params.get('save_to_gpkg', True),
            "output_dir": output_dir,
            "crs": project_crs,
            "split": params.get('split', False),
            "output_name": params.get('output_name', 'Импорт_КПТ')
        }

        # Список созданных слоев
        self.created_layers = []
        self.parsing_errors = []

        # Запускаем импорт
        try:
            imported_layers = self.kpt_importer.run_import(kpt_options)

            # Обрабатываем созданные слои
            for layer in imported_layers:
                self._handle_kpt_layer(layer)

        except Exception as e:
            self._handle_parsing_error(str(e))
            import traceback
            log_error(f"Fsm_1_1_1: {traceback.format_exc()}")

        # Собираем информацию из модуля
        skipped_files = self.kpt_importer.skipped_info if self.kpt_importer else []
        total_records = self.kpt_importer.total_records_processed if self.kpt_importer else 0

        # Логируем пропущенные файлы
        if skipped_files:
            log_info(f"Fsm_1_1_1: Пропущено устаревших XML файлов: {len(skipped_files)}")
            for skipped in skipped_files[:5]:
                log_info(f"Fsm_1_1_1:   {skipped}")
            if len(skipped_files) > 5:
                log_info(f"Fsm_1_1_1:   ... и еще {len(skipped_files) - 5}")

        # Формируем сообщение
        message_parts = [f'Импортировано слоев: {len(self.created_layers)}']
        if total_records > 0:
            message_parts.append(f'Обработано записей: {total_records}')
        if skipped_files:
            message_parts.append(f'Пропущено устаревших файлов: {len(skipped_files)}')

        # Логируем ошибки парсинга
        if self.parsing_errors:
            log_warning(f"Fsm_1_1_1: Обнаружено ошибок парсинга XML: {len(self.parsing_errors)}")
            for error in self.parsing_errors[:3]:
                log_warning(f"Fsm_1_1_1:   {error}")

        # Сортируем слои
        if self.created_layers and self.layer_manager:
            log_info("Fsm_1_1_1: Сортировка всех слоёв по order_layers из Base_layers.json")
            self.layer_manager.sort_all_layers()
            log_info("Fsm_1_1_1: Слои отсортированы по order_layers")

        return {
            'success': len(self.created_layers) > 0,
            'layers': self.created_layers,
            'message': ', '.join(message_parts),
            'errors': self.parsing_errors,
            'skipped_files': skipped_files,
            'total_records': total_records
        }

    def _init_kpt_importer(self) -> bool:
        """Инициализация модуля Fsm_1_1_5_KptImporter"""
        try:
            from .Fsm_1_1_5_kpt_importer import Fsm_1_1_5_KptImporter

            self.kpt_importer = Fsm_1_1_5_KptImporter(self.iface)
            log_info("Fsm_1_1_1: Модуль Fsm_1_1_5_KptImporter успешно инициализирован")
            return True

        except Exception as e:
            log_error(f"Fsm_1_1_1: Ошибка инициализации Fsm_1_1_5_KptImporter: {str(e)}")
            import traceback
            log_error(f"Fsm_1_1_1: {traceback.format_exc()}")
            return False

    def _check_lxml(self) -> bool:
        """Проверка наличия lxml"""
        try:
            from lxml import etree  # type: ignore[import-not-found]
            return True
        except (ImportError, RuntimeError):
            log_error("Fsm_1_1_1: Библиотека lxml не установлена")
            log_error("Fsm_1_1_1: Установите lxml через F_5_1 (Проверка зависимостей)")

            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.critical(
                self.iface.mainWindow() if self.iface else None,
                "Требуется lxml",
                "Для импорта XML файлов требуется библиотека lxml.\n\n"
                "Установите её через:\n"
                "5. Плагин -> 5_1 Проверка зависимостей\n\n"
                "После установки потребуется перезапуск QGIS."
            )
            return False

    def _handle_kpt_layer(self, layer: QgsVectorLayer):
        """
        Обработчик слоев из импортера КПТ

        Args:
            layer: Созданный слой
        """
        # Извлекаем record_type и geom_abbr из имени слоя
        layer_name = layer.name()
        parts = layer_name.rsplit('_', 1)

        if len(parts) == 2:
            base_name, geom_abbr = parts
        else:
            base_name = layer_name
            geom_abbr = "pl"

        # Ищем record_type по base_name в CUSTOM_LAYER_NAMES импортера
        record_type = None
        if self.kpt_importer:
            for rt, name in self.kpt_importer.CUSTOM_LAYER_NAMES.items():
                if name == base_name:
                    record_type = rt
                    break

        # Получаем стандартное имя слоя
        if record_type:
            standard_name = self.LAYER_NUMBERING.get(record_type)
            if standard_name:
                geom_suffix = self.GEOMETRY_SUFFIXES.get(geom_abbr, "")
                new_name = f"{standard_name}{geom_suffix}"
                layer.setName(new_name)

        # Сохраняем в GeoPackage если memory layer
        if layer.dataProvider().name() == 'memory' and self.project_manager:
            from ..core import LayerProcessor
            processor = LayerProcessor(self.project_manager, self.layer_manager)
            saved_layer = processor.save_to_gpkg(layer, layer.name())
            if saved_layer:
                layer = saved_layer

        # Удаляем из проекта если уже есть
        if layer.id() in QgsProject.instance().mapLayers():
            QgsProject.instance().removeMapLayer(layer.id())

        # Добавляем через LayerManager
        if self.layer_manager:
            self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
        else:
            QgsProject.instance().addMapLayer(layer)

        self.created_layers.append(layer)

    def _handle_parsing_error(self, error_message: str):
        """Обработчик ошибок парсинга XML"""
        self.parsing_errors.append(error_message)
        log_warning(f"Fsm_1_1_1: Ошибка парсинга XML: {error_message}")
