# -*- coding: utf-8 -*-
"""
Субмодуль F_1_2: Построитель конфигурации слоёв из Base_layers.json

Отвечает за получение списка ВСЕХ слоёв для загрузки через F_1_2:
- ЕГРН WFS (ЗУ, КК, НП, АТД)
- ОКС (special handler: load_oks_combined)
- ЗОУИТ (special handler: load_zouit_layers)
- ФГИС ЛК, OSM, WMS, растры

НЕ отвечает за загрузку - только за построение конфигурации.
"""

from typing import List, Dict, Any


class Fsm_1_2_0_LayerConfigBuilder:
    """Построитель конфигурации слоёв F_1_2 из Base_layers.json"""

    def __init__(self, api_manager):
        """
        Инициализация построителя конфигурации

        Args:
            api_manager: APIManager для получения endpoint параметров
        """
        self.api_manager = api_manager

    def get_layers_config_from_database(self) -> List[Dict]:
        """
        Получить конфигурацию слоёв для загрузки из Base_layers.json

        Использует M_14_APIManager для получения category_id через endpoint'ы.
        ВАЖНО: ООПТ загружается через load_zouit_layers, ОКС через load_oks_combined.

        Returns:
            List[Dict]: Список конфигураций слоёв, отсортированный по order_layers
        """
        assert self.api_manager is not None  # Type narrowing для Pylance

        from Daman_QGIS.managers import get_reference_managers

        ref_managers = get_reference_managers()
        all_layers = ref_managers.layer.get_base_layers()

        # Специальные маркеры для слоёв с custom загрузчиками
        # ОКС загружается через load_oks_combined (3 category: 36369, 36383, 36384)
        # ЗОУИТ загружается через load_zouit_layers (2 category: 36940, 36948)
        special_handlers = {
            'L_1_2_4_WFS_ОКС': 'oks_combined',
            'Le_1_2_5_21_WFS_ЗОУИТ_ОЗ_ООПТ': 'zouit_layers'
        }

        # Фильтруем слои которые загружаются через F_1_2 и имеют endpoint в api_manager
        f_1_2_layers = []

        for item in all_layers:
            full_name = item.get('full_name', '')

            # Проверяем что это слой для F_1_2
            if item.get('creating_function') != 'F_1_2_Загрузка Web карт':
                continue

            # Проверяем специальные обработчики - добавляем их с маркером!
            # Они загружаются через свои dedicated методы (load_zouit_layers, load_oks_combined)
            if full_name in special_handlers:
                # Добавляем слой с специальным category_id (маркером)
                f_1_2_layers.append({
                    'enabled': True,
                    'category_id': special_handlers[full_name],  # 'oks_combined' или 'zouit_layers'
                    'category_name': full_name,
                    'layer_name': full_name,
                    'order_layers': item.get('order_layers', '999'),
                    'sublayer_num': item.get('sublayer_num'),
                    'layer_num': item.get('layer_num'),
                    'section_num': item.get('section_num'),
                    'group_num': item.get('group_num'),
                    'layer': item.get('layer'),
                })
                continue

            # Пытаемся получить endpoint из api_manager
            endpoint = self.api_manager.get_endpoint_by_layer(full_name)
            if not endpoint:
                # Слой не имеет endpoint в Base_api_endpoints.json - пропускаем
                continue

            # Пропускаем растровые слои - они загружаются через raster_loader
            if endpoint.get('api_type') == 'raster':
                continue

            # Пропускаем non-EGRN слои (FGISLK, OVERPASS, GOOGLE) - они имеют свои loader'ы
            api_group = endpoint.get('api_group', '')
            if api_group not in ('EGRN_WFS', 'EGRN_WMTS'):
                continue

            # Получаем category_id из endpoint
            category_id = endpoint.get('category_id')
            if not category_id:
                from Daman_QGIS.utils import log_warning
                log_warning(f"Fsm_1_2_0: Слой {full_name} имеет endpoint EGRN, но без category_id")
                continue

            f_1_2_layers.append({
                'enabled': True,
                'category_id': category_id,
                'category_name': full_name,  # Используется в load_layer() для имени слоя
                'layer_name': full_name,
                'order_layers': item.get('order_layers', '999'),
                'sublayer_num': item.get('sublayer_num'),
                'layer_num': item.get('layer_num'),
                'section_num': item.get('section_num'),
                'group_num': item.get('group_num'),
                'layer': item.get('layer'),
            })

        # Сортируем по order_layers
        def get_sort_key(layer_config):
            order_layers = str(layer_config['order_layers'])
            # Обрабатываем формат "9_4" или просто "9"
            if '_' in order_layers:
                parts = order_layers.split('_')
                return (int(parts[0]) if parts[0].isdigit() else 999, int(parts[1]) if parts[1].isdigit() else 0)
            elif order_layers.isdigit():
                return (int(order_layers), 0)
            else:
                return (999, 0)

        f_1_2_layers.sort(key=get_sort_key)

        return f_1_2_layers
