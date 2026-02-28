# -*- coding: utf-8 -*-
"""
Fsm_1_1_5_ShpImporter - Импортер файлов Shapefile

Использует OGR провайдер QGIS для чтения данных.
Поддерживает кодировку cp1251 для русских данных.
"""

import os
from typing import Optional, List, Dict, Any
from qgis.core import (
    QgsVectorLayer, Qgis,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
)
import processing

from ..core.base_importer import BaseImporter
from Daman_QGIS.database.schemas import ImportSettings
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error


class ShpImporter(BaseImporter):
    """
    Импортер Shapefile файлов.
    Реализует все абстрактные методы базового класса: import_file, supports_format
    """

    def __init__(self, iface=None):
        """Инициализация импортера"""
        super().__init__(iface)
        self.settings: Optional[ImportSettings] = None

    def log_message(self, message: str, level: Qgis.MessageLevel = Qgis.Info):
        """Логирование сообщений"""
        if level == Qgis.Info:
            log_info(f"ShpImporter: {message}")
        elif level == Qgis.Warning:
            log_warning(f"ShpImporter: {message}")
        elif level == Qgis.Critical:
            log_error(f"ShpImporter: {message}")
        else:
            log_info(f"ShpImporter: {message}")

    def apply_encoding(self, layer: QgsVectorLayer, encoding: str = "cp1251"):
        """Применение кодировки к атрибутам слоя"""
        layer.setProviderEncoding(encoding)

    def supports_format(self, file_extension: str) -> bool:
        """Проверка поддержки формата"""
        return file_extension.lower() in self.get_supported_formats()

    def get_supported_formats(self) -> List[str]:
        """
        Получение списка поддерживаемых форматов

        Returns:
            Список расширений
        """
        return ['.shp']

    def can_import(self, file_path: str) -> bool:
        """
        Проверка возможности импорта файла

        Args:
            file_path: Путь к файлу

        Returns:
            True если можно импортировать
        """
        if not os.path.exists(file_path):
            return False

        # Проверяем расширение
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.get_supported_formats():
            return False

        # Проверяем наличие сопутствующих файлов Shapefile
        base_path = os.path.splitext(file_path)[0]

        # Shapefile формат включает несколько файлов
        # .shx - индекс геометрии (обязательный)
        # .dbf - атрибуты (обязательный)
        # .prj - проекция (опциональный, но рекомендуемый)
        # .cpg - кодировка (опциональный)

        required_files = [
            base_path + '.shx',
            base_path + '.dbf'
        ]

        for req_file in required_files:
            # Проверяем оба регистра
            if not (os.path.exists(req_file) or
                    os.path.exists(req_file.upper()) or
                    os.path.exists(req_file.lower())):
                self.log_message(
                    f"Не найден обязательный файл: {req_file}",
                    Qgis.Warning
                )
                return False

        return True

    def import_file(self, file_path: str, **custom_params) -> Dict[str, Any]:
        """
        Импорт Shapefile файла (переопределяет абстрактный метод базового класса)

        Args:
            file_path: Путь к SHP файлу
            **custom_params: Дополнительные параметры (может содержать 'settings')

        Returns:
            Словарь с результатами импорта
        """
        settings = custom_params.get('settings')
        layer = self._import_file_internal(file_path, settings)

        if layer:
            return {
                'success': True,
                'layers': [layer],
                'message': f'Успешно импортирован файл {os.path.basename(file_path)}',
                'errors': []
            }
        else:
            return {
                'success': False,
                'layers': [],
                'message': f'Не удалось импортировать файл {os.path.basename(file_path)}',
                'errors': ['Import failed']
            }

    def _import_file_internal(
        self,
        file_path: str,
        settings: Optional[ImportSettings] = None
    ) -> Optional[QgsVectorLayer]:
        """
        Внутренний метод импорта Shapefile файла

        Args:
            file_path: Путь к SHP файлу
            settings: Настройки импорта

        Returns:
            Импортированный слой или None
        """
        self.settings = settings or ImportSettings(
            source_format='SHP',
            target_layer_name=os.path.basename(file_path)
        )

        # Логируем начало импорта
        self.log_message(f"Начало импорта: {os.path.basename(file_path)}")

        # Определяем имя слоя
        layer_name = self.settings.target_layer_name if self.settings else None
        if not layer_name:
            layer_name = os.path.splitext(os.path.basename(file_path))[0]

        # Создаем слой через OGR
        # OGR автоматически обработает все сопутствующие файлы Shapefile
        layer = QgsVectorLayer(file_path, layer_name, "ogr")

        if not layer.isValid():
            raise RuntimeError(f"Не удалось загрузить слой из файла: {file_path}")

        self.log_message(f"Слой загружен: {layer.featureCount()} объектов")

        # Определяем кодировку
        # Сначала проверяем файл .cpg
        encoding = self._detect_encoding(file_path)
        if self.settings and self.settings.encoding:
            encoding = self.settings.encoding
        if not encoding:
            encoding = 'cp1251'  # Дефолт для русских данных

        self.apply_encoding(layer, encoding)
        self.log_message(f"Применена кодировка: {encoding}")

        # Применяем маппинг атрибутов если задан
        if self.settings and self.settings.attributes_mapping:
            self._apply_attributes_mapping(layer)

        # Логируем информацию о слое
        self.log_message(
            f"Импортирован слой '{layer_name}': "
            f"{layer.featureCount()} объектов, "
            f"тип геометрии: {layer.wkbType()}, "
            f"СК: {layer.crs().authid()}, "
            f"атрибутов: {len(layer.fields())}",
            Qgis.Info
        )

        self.result_layer = layer

        # Добавляем слой в проект через LayerManager (автоматическое применение стилей)
        if self.layer_manager:
            self.layer_manager.add_layer(
                layer,
                make_readonly=False,
                auto_number=False,
                check_precision=False
            )
            self.log_message(f"Слой '{layer.name()}' добавлен в проект через LayerManager")
        else:
            QgsProject.instance().addMapLayer(layer)
            self.log_message(
                f"Слой '{layer.name()}' добавлен в проект напрямую "
                "(LayerManager не доступен)"
            )

        # Создаём буферные слои если импортировали L_1_1_1_Границы_работ
        if layer.name() == 'L_1_1_1_Границы_работ':
            self._create_buffer_layers(layer)

        return layer

    def _detect_encoding(self, file_path: str) -> Optional[str]:
        """
        Определение кодировки из файла .cpg

        Args:
            file_path: Путь к SHP файлу

        Returns:
            Кодировка или None
        """
        base_path = os.path.splitext(file_path)[0]
        cpg_path = base_path + '.cpg'

        # Проверяем разные регистры
        for path in [cpg_path, cpg_path.upper(), cpg_path.lower()]:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        encoding = f.read().strip()
                        self.log_message(f"Кодировка из .cpg: {encoding}")
                        return encoding
                except Exception as e:
                    self.log_message(f"Ошибка чтения .cpg: {e}", Qgis.Warning)

        return None

    def _apply_attributes_mapping(self, layer: QgsVectorLayer):
        """
        Применение маппинга атрибутов

        Args:
            layer: Слой для обработки
        """
        if not self.settings or not self.settings.attributes_mapping:
            return

        mapping = self.settings.attributes_mapping

        layer.startEditing()

        for old_name, new_name in mapping.items():
            field_idx = layer.fields().indexOf(old_name)
            if field_idx >= 0:
                layer.renameAttribute(field_idx, new_name)

        layer.commitChanges()

        self.log_message(f"Применен маппинг для {len(mapping)} атрибутов")

    def _create_buffer_layers(self, source_layer: QgsVectorLayer) -> None:
        """
        Создание буферных слоёв для L_1_1_1_Границы_работ

        Автоматически создаёт три буферных слоя:
        - L_1_1_2_Границы_работ_10_м (буфер +10 метров)
        - L_1_1_3_Границы_работ_500_м (буфер +500 метров)
        - L_1_1_4_Границы_работ_-2_см (буфер -2 сантиметра)

        Args:
            source_layer: Исходный слой L_1_1_1_Границы_работ
        """
        self.log_message("Создание буферных слоёв для границ работ...")

        # Определяем буферные слои: (имя, расстояние в метрах, описание)
        buffer_configs = [
            ('L_1_1_2_Границы_работ_10_м', 10.0, 'буфер +10 метров'),
            ('L_1_1_3_Границы_работ_500_м', 500.0, 'буфер +500 метров'),
            ('L_1_1_4_Границы_работ_-2_см', -0.02, 'буфер -2 см (внутренний)')
        ]

        for layer_name, distance, description in buffer_configs:
            try:
                self.log_message(f"Создание слоя {layer_name} ({description})...")

                # Создаём буферный слой через processing
                buffer_result = processing.run("native:buffer", {
                    'INPUT': source_layer,
                    'DISTANCE': distance,
                    'SEGMENTS': 25,
                    'END_CAP_STYLE': 0,
                    'JOIN_STYLE': 0,
                    'MITER_LIMIT': 2,
                    'DISSOLVE': False,
                    'OUTPUT': 'memory:'
                })

                buffer_layer = buffer_result['OUTPUT']

                if not buffer_layer or not buffer_layer.isValid():
                    self.log_message(
                        f"Ошибка создания буферного слоя {layer_name}",
                        Qgis.Warning
                    )
                    continue

                buffer_layer.setName(layer_name)
                buffer_layer.setCrs(source_layer.crs())

                if self.layer_manager:
                    self.layer_manager.add_layer(
                        buffer_layer,
                        make_readonly=False,
                        auto_number=False,
                        check_precision=False
                    )
                    self.log_message(f"Буферный слой '{layer_name}' добавлен через LayerManager")
                else:
                    QgsProject.instance().addMapLayer(buffer_layer)
                    self.log_message(f"Буферный слой '{layer_name}' добавлен напрямую")

                self.log_message(
                    f"Слой {layer_name} успешно создан ({buffer_layer.featureCount()} объектов)"
                )

            except Exception as e:
                self.log_message(
                    f"Ошибка при создании буферного слоя {layer_name}: {str(e)}",
                    Qgis.Critical
                )
                log_error(f"ShpImporter: Ошибка создания буферного слоя {layer_name}: {str(e)}")

        self.log_message("Создание буферных слоёв завершено")
