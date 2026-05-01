# -*- coding: utf-8 -*-
"""
Процессор слоев для импорта
Сохранение в GeoPackage, применение стилей
"""

import os
import re
import json
from typing import Optional, Dict, Any, List, Callable
from qgis.core import (
    QgsVectorLayer, QgsProject, QgsMessageLog, Qgis,
    QgsVectorFileWriter, QgsCoordinateReferenceSystem
)
from qgis.PyQt.QtGui import QColor
import processing

from Daman_QGIS.managers import LayerReplacementManager, DataCleanupManager
from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.constants import ZPR_PREFIXES


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
        Загрузка параметров слоев из Base_layers.json через LayerReferenceManager
        """
        from Daman_QGIS.managers import LayerReferenceManager

        layer_manager = LayerReferenceManager()
        data = layer_manager.get_base_layers()

        # Base_layers.json содержит массив объектов, преобразуем в словарь
        # где ключ - full_name слоя
        self._layer_params_cache = {}
        if data and isinstance(data, list):
            for layer_data in data:
                full_name = layer_data.get('full_name', '')
                if full_name:
                    self._layer_params_cache[full_name] = layer_data

            log_info(
                f"Загружено {len(self._layer_params_cache)} параметров слоев из Base_layers.json"
            )
        else:
            log_warning("Параметры слоев не найдены")
    
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

        # Дополняем обязательные поля для слоёв ЗПР
        # ПЕРЕД сохранением в GPKG, чтобы F_2_1 мог работать со слоем
        self._ensure_zpr_fields(layer, layer_name)

        # Дополняем обязательные поля для слоя лесных выделов (Le_3_1_1_1_*)
        self._ensure_forest_vydely_fields(layer, layer_name)

        # Дополняем обязательные поля для слоёв нарезки (Le_2_1_*, Le_2_2_*)
        self._ensure_cutting_fields(layer, layer_name)

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

        # Проверяем существование целевого слоя в проекте и удаляем его
        existing_gpkg_layer = self.replacement_manager.find_layer_by_name(layer_name)
        if existing_gpkg_layer:
            self.replacement_manager.remove_layer_preserve_position(existing_gpkg_layer)

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

        return gpkg_layer

    def create_buffer_layers(
        self,
        source_layer: QgsVectorLayer,
        log_func: Callable[[str, "Qgis.MessageLevel"], None],
    ) -> List[QgsVectorLayer]:
        """
        Создание буферных слоёв L_1_1_2/3/4 для L_1_1_1_Границы_работ.

        Слои:
        - L_1_1_2_Границы_работ_10_м (буфер +10 метров)
        - L_1_1_3_Границы_работ_500_м (буфер +500 метров)
        - L_1_1_4_Границы_работ_-2_см (буфер -2 сантиметра)

        Args:
            source_layer: Исходный слой L_1_1_1_Границы_работ.
            log_func: Метод `self.log_message` вызывающего импортёра — сохраняет
                per-importer префиксы при логировании.

        Returns:
            Список успешно созданных буферных слоёв.
        """
        buffer_configs = [
            ('L_1_1_2_Границы_работ_10_м', 10.0),
            ('L_1_1_3_Границы_работ_500_м', 500.0),
            ('L_1_1_4_Границы_работ_-2_см', -0.02),
        ]

        created: List[QgsVectorLayer] = []

        for layer_name, distance in buffer_configs:
            try:
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
                    log_func(f"Ошибка создания буферного слоя {layer_name}", Qgis.Warning)
                    continue

                buffer_layer.setName(layer_name)
                buffer_layer.setCrs(source_layer.crs())

                if buffer_layer.dataProvider().name() == 'memory':
                    saved_layer = self.save_to_gpkg(buffer_layer, layer_name)
                    if saved_layer:
                        buffer_layer = saved_layer

                if self.layer_manager:
                    if buffer_layer.id() in QgsProject.instance().mapLayers():
                        QgsProject.instance().removeMapLayer(buffer_layer.id())
                    self.layer_manager.add_layer(
                        buffer_layer,
                        make_readonly=False,
                        auto_number=False,
                        check_precision=False,
                    )
                else:
                    QgsProject.instance().addMapLayer(buffer_layer)

                created.append(buffer_layer)

                log_func(
                    f"Слой {layer_name} успешно создан ({buffer_layer.featureCount()} объектов)",
                    Qgis.Info,
                )

            except Exception as e:
                log_func(
                    f"Ошибка при создании буферного слоя {layer_name}: {str(e)}",
                    Qgis.Critical,
                )

        return created

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
            # Безопасный отложенный refresh через QTimer
            from Daman_QGIS.utils import safe_refresh_layer
            safe_refresh_layer(layer)
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

    def _ensure_zpr_fields(self, layer: QgsVectorLayer, layer_name: str) -> None:
        """
        Дополнение обязательных полей для слоёв ЗПР

        Проверяет, является ли слой слоем ЗПР,
        и если да - добавляет недостающие обязательные поля.

        Обязательные поля ЗПР (схема 'ZPR' в M_28):
        - ID, ID_KV, VRI, MIN_AREA_VRI

        Args:
            layer: Слой для проверки и дополнения
            layer_name: Имя слоя
        """
        # Проверяем, является ли слой слоем ЗПР
        if not layer_name.startswith(ZPR_PREFIXES):
            return

        try:
            from Daman_QGIS.managers import LayerSchemaValidator

            validator = LayerSchemaValidator()

            # Проверяем, входит ли слой в схему ZPR
            if not validator.is_layer_in_schema(layer_name, 'ZPR'):
                log_info(f"LayerProcessor: Слой {layer_name} не в схеме ZPR, пропускаем дополнение полей")
                return

            # Дополняем недостающие поля
            result = validator.ensure_required_fields(layer, 'ZPR')

            if result['success'] and result['fields_added']:
                log_info(
                    f"LayerProcessor: Слой {layer_name} дополнен полями: "
                    f"{', '.join(result['fields_added'])}"
                )
            elif not result['success']:
                log_warning(
                    f"LayerProcessor: Ошибка дополнения полей слоя {layer_name}: "
                    f"{result.get('error', 'unknown')}"
                )

        except Exception as e:
            log_warning(f"LayerProcessor: Ошибка проверки полей ЗПР для {layer_name}: {e}")

    def _ensure_forest_vydely_fields(self, layer: QgsVectorLayer, layer_name: str) -> None:
        """
        Дополнение обязательных полей для слоя лесных выделов

        Проверяет, является ли слой слоем лесных выделов (Le_3_1_1_1_Лес_Ред_Выделы),
        и если да - добавляет недостающие обязательные поля с правильными типами
        (Int для Номер_квартала/Номер_выдела, String с разной длиной для остальных).

        17 обязательных полей загружаются из Base_forest_vydely.json.

        Args:
            layer: Слой для проверки и дополнения
            layer_name: Имя слоя
        """
        from Daman_QGIS.constants import LAYER_FOREST_VYDELY

        if layer_name != LAYER_FOREST_VYDELY:
            return

        try:
            from Daman_QGIS.managers import LayerSchemaValidator

            validator = LayerSchemaValidator()

            # Дополняем недостающие поля (с типами из динамического провайдера)
            result = validator.ensure_required_fields(layer, 'FOREST_VYDELY')

            if result['success'] and result['fields_added']:
                log_info(
                    f"LayerProcessor: Слой {layer_name} дополнен полями: "
                    f"{', '.join(result['fields_added'])}"
                )
            elif not result['success']:
                log_warning(
                    f"LayerProcessor: Ошибка дополнения полей слоя {layer_name}: "
                    f"{result.get('error', 'unknown')}"
                )

        except Exception as e:
            log_warning(f"LayerProcessor: Ошибка проверки полей лесных выделов для {layer_name}: {e}")

    def _ensure_cutting_fields(self, layer: QgsVectorLayer, layer_name: str) -> None:
        """
        Дополнение обязательных полей для слоёв нарезки

        Проверяет, является ли слой слоем нарезки (Le_2_1_*, Le_2_2_*),
        и если да - добавляет недостающие поля из Base_cutting.json (27 полей).
        Существующие поля НЕ удаляются. Поле пропускается при совпадении имени и типа.
        При конфликте типов (имя совпадает, тип нет) - warning в лог.

        Args:
            layer: Слой для проверки и дополнения
            layer_name: Имя слоя
        """
        from Daman_QGIS.constants import CUTTING_PREFIXES

        if not layer_name.startswith(CUTTING_PREFIXES):
            return

        try:
            from Daman_QGIS.managers import LayerSchemaValidator

            validator = LayerSchemaValidator()

            result = validator.ensure_required_fields(layer, 'CUTTING')

            if result['success'] and result['fields_added']:
                log_info(
                    f"LayerProcessor: Слой {layer_name} дополнен полями нарезки: "
                    f"{', '.join(result['fields_added'])}"
                )
            elif not result['success']:
                log_warning(
                    f"LayerProcessor: Ошибка дополнения полей нарезки слоя {layer_name}: "
                    f"{result.get('error', 'unknown')}"
                )

        except Exception as e:
            log_warning(f"LayerProcessor: Ошибка проверки полей нарезки для {layer_name}: {e}")
