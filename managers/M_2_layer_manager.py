# -*- coding: utf-8 -*-
"""
Менеджер слоев Daman_QGIS.
Управление слоями с автоматической нумерацией и категоризацией.
"""

from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
import os
import re

from qgis.core import (
    QgsVectorLayer, QgsRasterLayer, QgsProject,
    QgsLayerTreeLayer, QgsLayerTreeGroup,
    QgsSimpleLineSymbolLayer, QgsSimpleFillSymbolLayer,
    QgsLineSymbol, QgsFillSymbol, QgsSingleSymbolRenderer,
    QgsVectorSimplifyMethod
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

from Daman_QGIS.utils import log_info, log_warning, log_error, log_debug
from Daman_QGIS.constants import DEFAULT_LAYER_ORDER
from Daman_QGIS.database.schemas import LayerInfo
from Daman_QGIS.managers.M_6_coordinate_precision import CoordinatePrecisionManager
from Daman_QGIS.managers.M_5_style_manager import StyleManager
from Daman_QGIS.managers.M_8_layer_replacement_manager import LayerReplacementManager
from Daman_QGIS.managers.M_4_reference_manager import get_reference_managers
from Daman_QGIS.managers.M_12_label_manager import LabelManager

class LayerManager:
    """Менеджер слоев с автоматической нумерацией"""

    def __init__(self, iface, plugin_dir: Optional[str] = None) -> None:
        """
        Инициализация менеджера слоев

        Args:
            iface: Интерфейс QGIS
            plugin_dir: Путь к директории плагина
        """
        self.iface = iface
        self.layer_registry = {}  # Реестр слоев с метаданными

        # Единый менеджер стилей (замена AutoCADVisualStyleManager и UniversalStyleManager)
        self.style_manager = StyleManager()

        # Инициализируем менеджер замены слоев
        self.replacement_manager = LayerReplacementManager()

        # Менеджер подписей (создаётся один раз для всех слоёв)
        self.label_manager = None

        # ОТКЛЮЧЕНО: Автоматическая сортировка при добавлении слоёв
        # Причина: Во время массовой загрузки (F_1_2, F_1_1) автоматическая сортировка
        # вызывается многократно и может вызывать краши или замедление
        # Решение: Сортировка вызывается ВРУЧНУЮ один раз в конце каждого инструмента
        # через явный вызов sort_all_layers()
        # QgsProject.instance().legendLayersAdded.connect(self._on_layers_added)

    def add_layer(self,
                 layer: QgsVectorLayer,
                 make_readonly: bool = False,
                 auto_number: bool = True,
                 check_precision: bool = True) -> bool:
        """
        Добавление слоя с автоматической нумерацией

        Args:
            layer: Слой для добавления
            make_readonly: Сделать слой только для чтения
            auto_number: Применить автоматическую нумерацию
            check_precision: Проверять точность координат

        Returns:
            True если добавление успешно
        """
        # Проверяем точность координат если это векторный слой
        if check_precision and isinstance(layer, QgsVectorLayer):
            if not CoordinatePrecisionManager.validate_and_round_layer(layer, auto_round=False):
                log_warning(f"M_2_LayerManager: Слой '{layer.name()}' отклонен из-за точности координат")
                return False
        # Определяем префикс динамически из имени слоя или не добавляем
        layer_name = layer.name()
        prefix = ""

        # Извлекаем существующий префикс из имени слоя если есть
        match = re.match(r'^([\d_]+)(?:_|$)', layer_name)
        if match:
            prefix = match.group(1).rstrip('_') + '_'

        # Делаем слой только для чтения если нужно
        if make_readonly:
            # В QGIS 3.40 нет прямого метода setReadOnly для слоев
            # Пробуем установить через провайдер данных
            # Для векторных слоев устанавливаем флаг редактирования
            if isinstance(layer, QgsVectorLayer):
                # Запрещаем редактирование через возможности провайдера
                capabilities = layer.dataProvider().capabilities()
                # Удаляем возможности редактирования
                if hasattr(layer, 'setReadOnly'):
                    layer.setReadOnly(True)


        # Создаем информацию о слое
        layer_info = LayerInfo(
            id=layer.id(),
            name=layer_name,
            type="vector" if isinstance(layer, QgsVectorLayer) else "raster",
            geometry_type=str(layer.geometryType()) if isinstance(layer, QgsVectorLayer) else "",
            source_path=layer.source(),
            prefix=prefix,
            created=datetime.now(),
            modified=datetime.now(),
            readonly=make_readonly
        )

        # Сохраняем в реестре
        self.layer_registry[layer.id()] = layer_info

        # Добавляем в проект QGIS
        QgsProject.instance().addMapLayer(layer)

        # Применяем AutoCAD стиль
        self.style_manager.apply_qgis_style(layer, layer_name)

        # Сохраняем метаданные из Base_layers.json в слой
        self._save_layer_metadata(layer, layer_name)

        # Применяем подписи из Base_labels.json (если настроены для этого слоя)
        if isinstance(layer, QgsVectorLayer):
            try:
                # Создаём LabelManager один раз (lazy initialization)
                if self.label_manager is None:
                    self.label_manager = LabelManager()

                if self.label_manager.apply_labels(layer, layer_name):
                    log_debug(f"M_2_LayerManager: Подписи применены автоматически для {layer_name}")
            except Exception as e:
                log_warning(f"M_2_LayerManager: Не удалось применить подписи к {layer_name}: {str(e)}")

        # ВАЖНО: Отключаем видимость по масштабу и упрощение геометрии
        # Это предотвращает проблемы с исчезновением слоёв при зуме и перемещении
        if isinstance(layer, QgsVectorLayer):
            layer.setScaleBasedVisibility(False)

            # Отключаем упрощение геометрии (может вызывать исчезновение объектов)
            layer.setSimplifyMethod(QgsVectorSimplifyMethod())
            simplify_method = layer.simplifyMethod()
            simplify_method.setSimplifyHints(QgsVectorSimplifyMethod.NoSimplification)
            simplify_method.setThreshold(0)
            layer.setSimplifyMethod(simplify_method)

            # Принудительное обновление отображения
            layer.triggerRepaint()

        # Организуем в группы по функциям (0_5_, 1_1_, etc.)
        self._organize_in_function_groups(layer)

        # Применяем видимость слоя из поля hidden в Base_layers.json
        self._apply_layer_visibility(layer)

        return True

    def _organize_in_function_groups(self, layer: QgsVectorLayer) -> None:
        """
        ОТКЛЮЧЕНО: Организация слоёв в группы
        Теперь все слои добавляются плоско в корень проекта без группировки
        Сортировка по order_layers выполняется вручную через sort_all_layers()

        Args:
            layer: Слой (не используется, добавляется в корень автоматически)
        """
        # ПОЛНОСТЬЮ ПЛОСКАЯ СТРУКТУРА - НЕ СОЗДАЁМ ГРУППЫ
        # Слой уже добавлен в проект через QgsProject.instance().addMapLayer()
        # Ничего не делаем - слой остаётся в корне
        pass

    def sort_all_layers(self) -> None:
        """
        Сортирует ВСЕ слои в проекте по полю order_layers из Base_layers.json
        Используется для плоской структуры (все слои в корне без групп)
        Вызывать ОДИН РАЗ после загрузки всех слоёв

        ВАЖНО: Вызывать только когда все слои уже загружены!

        БЕЗОПАСНЫЙ МЕТОД через setCustomLayerOrder():
        - НЕ использует removeChildNode/insertChildNode (которые вызывают краши)
        - Устанавливает ПОРЯДОК ОТРИСОВКИ на карте через customLayerOrder
        - Порядок в Layers Panel остаётся как при загрузке
        - Порядок отрисовки и Layer Order Panel будут соответствовать order_layers

        Пользователь может включить View → Panels → Layer Order (Ctrl+9)
        чтобы видеть и управлять порядком отрисовки отдельно от панели слоёв
        """
        try:
            log_info("M_2_LayerManager: Начало безопасной сортировки через setCustomLayerOrder")

            root = QgsProject.instance().layerTreeRoot()
            ref_managers = get_reference_managers()

            # 1. Включаем режим кастомного порядка отрисовки
            root.setHasCustomLayerOrder(True)
            log_info("M_2_LayerManager: Режим customLayerOrder включён")

            # 2. Получаем все слои проекта
            all_layers = list(QgsProject.instance().mapLayers().values())
            log_info(f"M_2_LayerManager: Всего слоёв в проекте: {len(all_layers)}")

            if len(all_layers) == 0:
                log_info("M_2_LayerManager: Нет слоёв для сортировки")
                return

            # 3. Создаем список (слой, order_layers) для сортировки
            layers_with_order = []
            layers_without_order = 0

            for layer in all_layers:
                layer_name = layer.name()
                layer_info = ref_managers.layer.get_layer_by_full_name(layer_name)

                if layer_info and layer_info.get('order_layers'):
                    try:
                        order_str = str(layer_info['order_layers'])
                        if order_str != '-':
                            order_value = int(order_str)
                        else:
                            order_value = DEFAULT_LAYER_ORDER
                    except (ValueError, TypeError):
                        order_value = DEFAULT_LAYER_ORDER
                        layers_without_order += 1
                else:
                    # Слой не найден в Base_layers.json или order_layers не задан
                    order_value = DEFAULT_LAYER_ORDER
                    layers_without_order += 1

                layers_with_order.append((layer, order_value, layer_name))

            log_info(f"M_2_LayerManager: Слоёв без order_layers: {layers_without_order}")

            # 4. Сортируем по order_layers (меньшее значение = выше приоритет)
            # В customLayerOrder первый слой в списке (index 0) рисуется СВЕРХУ (drawn last),
            # последний слой в списке рисуется СНИЗУ (drawn first)
            # Поэтому:
            #   order_layers = 1 → должен быть СВЕРХУ → должен быть первым в списке (index 0)
            #   order_layers = 100 → должен быть СНИЗУ → должен быть последним в списке
            # Сортируем в ПРЯМОМ порядке: меньший order_layers → раньше в списке
            layers_with_order.sort(key=lambda x: x[1])

            # 5. Извлекаем только слои (без order_value и имени)
            sorted_layers = [layer for layer, _, _ in layers_with_order]

            # 6. Применяем новый порядок отрисовки
            root.setCustomLayerOrder(sorted_layers)

            log_info(f"M_2_LayerManager: Успешно отсортировано {len(sorted_layers)} слоёв по order_layers")

        except Exception as e:
            log_error(f"M_2_LayerManager: Ошибка при сортировке: {str(e)}")
            import traceback
            log_error(f"M_2_LayerManager: Traceback:\n{traceback.format_exc()}")

    def _save_layer_metadata(self, layer: QgsVectorLayer, layer_name: str) -> None:
        """
        Сохранение метаданных из Base_layers.json в слой QGIS

        Записывает в слой:
        - description → layer.setAbstract()
        - creating_function → customProperty('creating_function')
        - geometry_type → customProperty('expected_geometry_type')
        - order_layers → customProperty('order_layers')

        Args:
            layer: Слой QGIS
            layer_name: Полное имя слоя (например "L_1_1_1_Границы_работ")
        """
        ref_managers = get_reference_managers()

        # Получаем информацию о слое из базы
        layer_info = ref_managers.layer.get_layer_by_full_name(layer_name)

        if not layer_info:
            # Слой не найден в базе, ничего не делаем
            log_debug(f"M_2_LayerManager: Метаданные для '{layer_name}' не найдены в Base_layers.json")
            return

        # Сохраняем description в metadata слоя
        description = layer_info.get('description', '')
        if description and description != '-':
            # QGIS 3.40: используем metadata() вместо deprecated setAbstract()
            metadata = layer.metadata()
            metadata.setAbstract(description)
            layer.setMetadata(metadata)

        # Сохраняем creating_function в customProperty
        creating_function = layer_info.get('creating_function', '')
        if creating_function and creating_function != '-':
            layer.setCustomProperty('creating_function', creating_function)

        # Сохраняем ожидаемый geometry_type из базы
        expected_geom_type = layer_info.get('geometry_type', '')
        if expected_geom_type and expected_geom_type != '-':
            layer.setCustomProperty('expected_geometry_type', expected_geom_type)

        # Сохраняем order_layers для сортировки
        order_layers = layer_info.get('order_layers', '')
        if order_layers and order_layers != '-':
            layer.setCustomProperty('order_layers', order_layers)

        # Сохраняем section, group для организации
        section = layer_info.get('section', '')
        if section and section != '-':
            layer.setCustomProperty('section', section)

        group = layer_info.get('group', '')
        if group and group != '-':
            layer.setCustomProperty('group', group)

    def _apply_layer_visibility(self, layer: QgsVectorLayer) -> None:
        """
        Применяет видимость слоя на основе поля 'hidden' из Base_layers.json

        Args:
            layer: Слой QGIS
        """
        from Daman_QGIS.managers import get_reference_managers

        layer_name = layer.name()
        ref_managers = get_reference_managers()

        # Получаем информацию о слое из базы
        layer_info = ref_managers.layer.get_layer_by_full_name(layer_name)

        if not layer_info:
            # Слой не найден в базе, не меняем видимость
            return

        hidden = layer_info.get('hidden', '-')

        # hidden == 1 означает скрытый слой, "-" означает видимый
        if hidden == 1 or hidden == "1":
            # Скрываем слой в дереве слоев
            root = QgsProject.instance().layerTreeRoot()
            layer_node = root.findLayer(layer.id())
            if layer_node:
                layer_node.setItemVisibilityChecked(False)

    def get_layer_info(self, layer_id: str) -> Optional[LayerInfo]:
        """
        Получение информации о слое
        
        Args:
            layer_id: ID слоя
            
        Returns:
            LayerInfo или None
        """
        return self.layer_registry.get(layer_id)
    
    def update_layer_name(self, layer: QgsVectorLayer, new_name: str, keep_prefix: bool = True) -> None:
        """
        Обновление имени слоя с сохранением префикса

        Args:
            layer: Слой
            new_name: Новое имя
            keep_prefix: Сохранять префикс
        """
        current_name = layer.name()

        # Извлекаем префикс если нужно сохранить
        if keep_prefix:
            # Ищем префикс вида "N_"
            match = re.match(r'^(\d+_)', current_name)
            if match:
                prefix = match.group(1)
                if not new_name.startswith(prefix):
                    new_name = f"{prefix}{new_name}"

        layer.setName(new_name)

        # Обновляем в реестре
        if layer.id() in self.layer_registry:
            self.layer_registry[layer.id()].name = new_name
            self.layer_registry[layer.id()].modified = datetime.now()

    
    def remove_layer(self, layer_id: str) -> bool:
        """
        Удаление слоя

        Args:
            layer_id: ID слоя

        Returns:
            True если удаление успешно
        """
        # Удаляем из проекта
        QgsProject.instance().removeMapLayer(layer_id)

        # Удаляем из реестра
        if layer_id in self.layer_registry:
            del self.layer_registry[layer_id]

        return True
    
    def clear_registry(self) -> None:
        """Очистка реестра слоев"""
        self.layer_registry.clear()
    
    def validate_autocad_styles(self) -> Tuple[bool, List[str]]:
        """
        Проверка всех слоев на совместимость с AutoCAD (для экспорта DXF)

        Returns:
            (все валидны, список проблем)
        """
        return self.style_manager.validate_project_styles()

    # Методы save_layer_style() и clear_style_cache() удалены
    # Кэширование отключено для Base_layers.json (всегда актуальные данные)
