# -*- coding: utf-8 -*-
"""
Субмодуль F_1_2: Загрузка слоёв АТД (административно-территориальное деление)
Загрузка слоёв границ, муниципальных образований, районов, населённых пунктов
"""

import time
from typing import Dict, Any, List, Optional

from Daman_QGIS.utils import log_info, log_warning, log_error, log_success


class Fsm_1_2_5_AtdLoader:
    """Загрузчик слоёв административно-территориального деления"""

    def __init__(self, iface, egrn_loader, api_manager):
        """
        Инициализация загрузчика АТД

        Args:
            iface: Интерфейс QGIS
            egrn_loader: Экземпляр Fsm_1_2_1_EgrnLoader для загрузки данных ЕГРН
            api_manager: APIManager для получения endpoint параметров
        """
        self.iface = iface
        self.egrn_loader = egrn_loader
        self.api_manager = api_manager

    def load_single_atd_layer(self, config: Dict[str, Any], progress_task=None) -> Dict[str, Any]:
        """
        Загрузить один АТД слой (для параллельного выполнения)

        Args:
            config: Конфигурация слоя из Base_layers.json
            progress_task: ProgressTask для обновления прогресса

        Returns:
            dict: Результат загрузки {
                'config': config,
                'layer': QgsVectorLayer или None,
                'feature_count': int,
                'success': bool,
                'time': float
            }
        """
        layer_name = config['layer_name']
        start_time = time.time()

        # Проверка отмены пользователем
        if progress_task and progress_task.is_canceled():
            log_warning(f"Fsm_1_2_5: Загрузка АТД {layer_name} отменена пользователем")
            return {
                'config': config,
                'layer': None,
                'feature_count': 0,
                'success': False,
                'time': time.time() - start_time
            }

        try:
            # Проверка что egrn_loader инициализирован
            if not self.egrn_loader:
                log_error(f"Fsm_1_2_5: egrn_loader не инициализирован для {layer_name}")
                return {
                    'config': config,
                    'layer': None,
                    'feature_count': 0,
                    'success': False,
                    'time': time.time() - start_time
                }

            # Буфер 500м для АТД слоев (определяется через Layer_selector в Base_api_endpoints.json)
            # Сохраняем ссылку на egrn_loader для использования в lambda
            egrn_loader = self.egrn_loader
            geometry_provider = lambda: egrn_loader.get_boundary_extent(use_500m_buffer=True)

            # Загрузка слоя АТД
            try:
                log_info(f"Fsm_1_2_5: Загрузка АТД слоя: {layer_name}")
                layer, feature_count = self.egrn_loader.load_layer(
                    layer_name=layer_name,
                    geometry_provider=geometry_provider,
                    progress_task=None
                )

                if layer and feature_count > 0:
                    log_success(f"Fsm_1_2_5: Загружено {feature_count} объектов АТД")
            except Exception as e:
                log_warning(f"Fsm_1_2_5: Не удалось загрузить слой: {e}")
                layer = None
                feature_count = 0

            elapsed = time.time() - start_time
            success = layer is not None and feature_count > 0

            return {
                'config': config,
                'layer': layer,
                'feature_count': feature_count,
                'success': success,
                'time': elapsed
            }

        except Exception as e:
            elapsed = time.time() - start_time
            log_error(f"Fsm_1_2_5: Ошибка загрузки {layer_name}: {str(e)}")
            return {
                'config': config,
                'layer': None,
                'feature_count': 0,
                'success': False,
                'time': elapsed
            }
