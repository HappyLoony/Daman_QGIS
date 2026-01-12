# -*- coding: utf-8 -*-
"""
Субмодуль проверки наличия векторных слоев ЕГРН для бюджета
ВАЖНО: Только проверяет наличие слоев, НЕ загружает их!
Слои должны быть загружены заранее через F_1_2
"""

from qgis.core import QgsProject, QgsVectorLayer
from Daman_QGIS.utils import log_info, log_warning, log_error


class VectorLoader:
    """Проверяльщик наличия векторных слоев ЕГРН (БЕЗ загрузки)"""
    
    def __init__(self, iface, project_manager, layer_manager):
        """Инициализация проверяльщика слоев"""
        self.iface = iface
        self.project = QgsProject.instance()
        self.project_manager = project_manager
        self.layer_manager = layer_manager

    def load_single_layer(self, layer_type, boundaries_geometry):
        """Проверка наличия одного векторного слоя

        Args:
            layer_type: Тип слоя (L_1_2_X)
            boundaries_geometry: Геометрия границ (не используется, для совместимости)

        Returns:
            bool: True если слой существует, False если не найден
        """
        # ВАЖНО: Сначала проверяем родительский слой (созданный через F_1_2)
        # Конфигурация слоев с указанием родительских слоёв
        layers_config = {
            'L_1_2_2_WFS_КК': {
                'parent_layer': 'L_1_2_2_WFS_КК',  # Родительский слой для КК
                'category_name': 'Кадастровые кварталы',
                'category_id': 36381
            },
            'L_1_2_1_WFS_ЗУ': {
                'parent_layer': 'L_1_2_1_WFS_ЗУ',  # Родительский слой для ЗУ
                'category_name': 'Земельные участки из ЕГРН',
                'category_id': 36368
            },
            'Le_1_2_3_5_АТД_НП_poly': {
                'parent_layer': 'Le_1_2_3_5_АТД_НП_poly',  # Родительский слой для НП (АТД полигоны)
                'category_name': 'Населённые пункты',
                'category_id': 36832
            }
        }

        if layer_type not in layers_config:
            return False

        config = layers_config[layer_type]

        # Проверяем существование родительского слоя (приоритет)
        parent_layer_name = config.get('parent_layer')
        if parent_layer_name and self._check_existing_layer(parent_layer_name):
            log_info(f"Fsm_1_3_2: Родительский слой {parent_layer_name} уже существует")
            return True

        # Проверяем существование обычного слоя
        if self._check_existing_layer(layer_type):
            log_info(f"Fsm_1_3_2: Слой {layer_type} уже существует")
            return True

        # Если ни родительский, ни обычный слой не найдены - НЕ загружаем!
        # F_1_3 Бюджет должен только анализировать, а не загружать
        log_warning(f"Fsm_1_3_2: Слой {layer_type} не найден. Загрузите слои через F_1_2 перед запуском бюджета.")
        return False

    def load_capital_objects(self, boundaries_geometry):
        """Проверка наличия слоя выборки ОКС (L_2_1_2_Выборка_ОКС)

        Args:
            boundaries_geometry: Геометрия границ (не используется, для совместимости)

        Returns:
            bool: True если слой выборки ОКС найден, False если отсутствует
        """
        # Проверяем слой выборки ОКС (создаётся через F_2_1)
        selection_oks_layer = 'L_2_1_2_Выборка_ОКС'
        if self._check_existing_layer(selection_oks_layer):
            log_info(f"Fsm_1_3_2: Слой выборки ОКС {selection_oks_layer} найден")
            return True

        # Если слой выборки ОКС не найден - предупреждение (не ошибка)
        log_warning(f"Fsm_1_3_2: Слой {selection_oks_layer} не найден - количество ОКС будет 0")
        return False
    
    def _check_existing_layer(self, layer_name):
        """Проверка существования слоя в project.gpkg
        
        Args:
            layer_name: Имя слоя для проверки
            
        Returns:
            bool: True если слой существует
        """
        # Проверяем в проекте
        for layer in self.project.mapLayers().values():
            if layer.name() == layer_name:
                return True
        
        # Проверяем в GeoPackage через project_manager
        if not self.project_manager or not self.project_manager.project_db:
            return False
            
        gpkg_path = self.project_manager.project_db.gpkg_path
        if not gpkg_path:
            return False
        
        # Пытаемся загрузить слой
        layer = QgsVectorLayer(
            f"{gpkg_path}|layername={layer_name}",
            layer_name,
            "ogr"
        )
        
        if layer.isValid():
            # Добавляем через layer_manager
            if self.layer_manager:
                layer.setName(layer_name)
                self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
            else:
                self.project.addMapLayer(layer)
            return True
        
        return False
