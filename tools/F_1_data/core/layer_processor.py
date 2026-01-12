# -*- coding: utf-8 -*-
"""
Процессор слоев для импорта
Сохранение в GeoPackage, применение стилей, организация в группы
"""

import os
import re
import json
from typing import Optional, Dict, Any, List
from qgis.core import (
    QgsVectorLayer, QgsProject, QgsMessageLog, Qgis,
    QgsVectorFileWriter, QgsLayerTreeGroup,
    QgsCoordinateReferenceSystem
)
from qgis.PyQt.QtGui import QColor

from Daman_QGIS.managers import LayerReplacementManager, DataCleanupManager
from Daman_QGIS.utils import log_info, log_warning, log_error


class LayerProcessor:
    """Класс для обработки слоев при импорте"""

    def __init__(self, project_manager=None, layer_manager=None):
        """
        Инициализация процессора слоев

        Args:
            project_manager: Менеджер проектов
            layer_manager: Менеджер слоев
        """
        self.project_manager = project_manager
        self.layer_manager = layer_manager
        self._layer_params_cache = None
        self.replacement_manager = LayerReplacementManager()
        self.data_cleanup_manager = DataCleanupManager()
    def _load_layer_params(self):
        """
        Загрузка параметров слоев из Base_layers.json
        """
        # Получаем путь к Base_layers.json
        from Daman_QGIS.constants import DATA_REFERENCE_PATH
        json_path = os.path.join(DATA_REFERENCE_PATH, 'Base_layers.json')

        if os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

                # Base_layers.json содержит массив объектов, преобразуем в словарь
                # где ключ - full_name слоя
                self._layer_params_cache = {}
                if isinstance(data, list):
                    for layer_data in data:
                        full_name = layer_data.get('full_name', '')
                        if full_name:
                            self._layer_params_cache[full_name] = layer_data

            log_info(
                f"Загружено {len(self._layer_params_cache)} параметров слоев из Base_layers.json"
            )
        else:
            log_warning(
                f"Файл параметров слоев не найден: {json_path}"
            )
            self._layer_params_cache = {}
    
    def get_layer_params(self, layer_id: str) -> Dict[str, Any]:
        """
        Получение параметров слоя из базы

        Args:
            layer_id: Идентификатор слоя (например, '1_1_1_Границы_работ')

        Returns:
            Параметры слоя или пустой словарь
        """
        # Загружаем параметры из JSON если еще не загружены
        if self._layer_params_cache is None:
            self._load_layer_params()

        # Проверяем что кэш загружен
        if not self._layer_params_cache:
            return {}

        # Ищем точное совпадение
        if layer_id in self._layer_params_cache:
            return self._layer_params_cache[layer_id]
        
        # Извлекаем базовый идентификатор (без суффиксов типа _point, _line)
        base_id_match = re.match(r'^(\d+_\d+_\d+(?:_\d+)?)', layer_id)
        if base_id_match and self._layer_params_cache:
            base_id_str = base_id_match.group(1)

            # Ищем по базовому ID
            for key in self._layer_params_cache:
                if key.startswith(base_id_str):
                    return self._layer_params_cache[key]
        
        # Возвращаем пустой словарь если не нашли
        return {}
    def save_to_gpkg(self, layer: QgsVectorLayer, layer_name: Optional[str] = None) -> Optional[QgsVectorLayer]:
        """
        Сохранение слоя в GeoPackage проекта

        Args:
            layer: Слой для сохранения
            layer_name: Имя слоя в GeoPackage (если None, используется имя слоя)

        Returns:
            QgsVectorLayer из GeoPackage или None при ошибке
        """
        if not self.project_manager or not self.project_manager.project_db:
            log_warning(
                "База данных проекта не инициализирована"
            )
            return layer

        # Получаем путь к GeoPackage
        gpkg_path = self.project_manager.project_db.gpkg_path

        # Используем переданное имя или имя слоя
        if not layer_name:
            layer_name = layer.name()

        # Проверяем что имя определено
        if not layer_name:
            layer_name = "unnamed_layer"

        # Очищаем имя слоя от недопустимых символов
        layer_name = self._clean_layer_name(layer_name)

        # Логируем
        log_info(
            f"Сохранение слоя в GeoPackage: {layer_name}"
        )

        # Настройки сохранения
        save_options = QgsVectorFileWriter.SaveVectorOptions()
        save_options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        save_options.layerName = layer_name
        save_options.driverName = "GPKG"

        # Сохраняем
        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            gpkg_path,
            QgsProject.instance().transformContext(),
            save_options
        )

        if error[0] != QgsVectorFileWriter.NoError:
            raise ValueError(f"Ошибка сохранения: {error[1]}")

        # Проверяем существование целевого слоя в проекте
        existing_gpkg_layer = self.replacement_manager.find_layer_by_name(layer_name)
        position, parent_group = None, None
        if existing_gpkg_layer:
            # Сохраняем позицию существующего GPKG слоя
            position, parent_group = self.replacement_manager.remove_layer_preserve_position(existing_gpkg_layer)

        # Загружаем слой из GeoPackage
        gpkg_layer = QgsVectorLayer(
            f"{gpkg_path}|layername={layer_name}",
            layer_name,
            "ogr"
        )

        if not gpkg_layer.isValid():
            raise ValueError("Не удалось загрузить слой из GeoPackage")

        # Удаляем временный слой из проекта
        if layer.id() in QgsProject.instance().mapLayers():
            QgsProject.instance().removeMapLayer(layer.id())

        # НЕ добавляем gpkg_layer в проект здесь - это сделает вызывающий код
        # через LayerManager, который правильно организует группировку

        log_info(
            f"Слой '{layer_name}' сохранен в GeoPackage"
        )

        return gpkg_layer
    def apply_style(self, layer: QgsVectorLayer, layer_id: str) -> bool:
        """
        Применение стиля к слою

        Args:
            layer: Слой
            layer_id: Идентификатор слоя для поиска стиля

        Returns:
            True если стиль применен успешно
        """
        # Получаем параметры слоя
        params = self.get_layer_params(layer_id)
        if not params:
            return False

        style_name = params.get('apply_style')

        # Специальные встроенные стили
        if style_name == 'red_line_1mm':
            return self._apply_red_line_style(layer)

        # Используем новый менеджер стилей
        from Daman_QGIS.managers import StyleManager
        from Daman_QGIS.constants import PLUGIN_NAME
        style_manager = StyleManager()
        return style_manager.apply_qgis_style(layer, layer.name())
    def _apply_red_line_style(self, layer: QgsVectorLayer) -> bool:
        """
        Применение стиля красной линии толщиной 1мм (для границ)

        Args:
            layer: Слой

        Returns:
            True если успешно
        """
        # Используем StyleManager для создания простого стиля
        from Daman_QGIS.managers import StyleManager

        style_manager = StyleManager()
        success = style_manager.create_simple_line_style(
            layer,
            QColor(255, 0, 0),  # Красный цвет
            1.0  # Толщина 1 мм
        )

        if success:
            # ВАЖНО: triggerRepaint() может вызвать краш, не вызываем
            log_info(
                f"Применен стиль красной линии к слою {layer.name()}"
            )

        return success
    
    def organize_in_groups(self, layer: QgsVectorLayer, group_name: str) -> QgsVectorLayer:
        """
        Организация слоя в группы дерева слоев
        Использует LayerManager для правильной группировки по Base_layers.json

        Args:
            layer: Слой для добавления
            group_name: Имя группы (игнорируется, используется Base_layers.json)

        Returns:
            QgsVectorLayer: Актуальный слой (может быть новым после замены)
        """
        # Используем LayerManager для правильной группировки
        if self.layer_manager:
            self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
        else:
            # Fallback: простое добавление в проект
            QgsProject.instance().addMapLayer(layer)

        log_info(
            f"Слой {layer.name()} добавлен в проект"
        )
        return layer
    
    def add_layer_to_project(self, layer: QgsVectorLayer, params: Optional[Dict[str, Any]] = None) -> QgsVectorLayer:
        """
        Добавление слоя в проект с учетом всех параметров

        Args:
            layer: Слой для добавления
            params: Параметры добавления

        Returns:
            QgsVectorLayer: Актуальный слой (может быть новым после замены)
        """
        if not params:
            params = self.get_layer_params(layer.name())

        if not params:
            params = {}

        # Сохраняем в GeoPackage если нужно
        if params.get('save_to_gpkg', True):
            gpkg_layer = self.save_to_gpkg(layer)
            if gpkg_layer:
                layer = gpkg_layer

        # ВАЖНО: стиль применяется внутри add_layer через StyleManager, не нужно дублировать!
        # LayerManager автоматически применяет стили через новый StyleManager

        # ВСЕГДА используем LayerManager для организации в группы
        if self.layer_manager:
            # LayerManager автоматически организует в группы по Base_layers.json
            # И применяет стили через новый StyleManager
            self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
        else:
            # Простое добавление без группировки
            QgsProject.instance().addMapLayer(layer)

        # Устанавливаем readonly если нужно
        if params.get('make_readonly', False):
            layer.setReadOnly(True)

        return layer
    
    def _clean_layer_name(self, layer_name: str) -> str:
        """
        Очистка имени слоя от недопустимых символов

        Args:
            layer_name: Исходное имя

        Returns:
            Очищенное имя
        """
        # Шаг 1: Удаляем UUID если есть (специфично для layer_processor)
        layer_name = re.sub(r'_[a-f0-9]{8}_[a-f0-9]{4}_[a-f0-9]{4}_[a-f0-9]{4}_[a-f0-9]{12}$', '', layer_name)

        # Шаг 2: Применяем централизованную очистку имён Windows
        layer_name = self.data_cleanup_manager.sanitize_filename(layer_name)

        return layer_name
    
    def generate_layer_name(self, base_name: str, suffix: Optional[str] = None) -> str:
        """
        Генерация имени слоя по шаблону X_Y_Z_Name
        
        Args:
            base_name: Базовое имя (например, '1_1_1_Границы')
            suffix: Суффикс (например, '_point', '_line')
            
        Returns:
            Полное имя слоя
        """
        if suffix and not base_name.endswith(suffix):
            return f"{base_name}{suffix}"
        return base_name
