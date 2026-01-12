# -*- coding: utf-8 -*-
"""
Субмодуль F_1_2: Загрузка растровых подложек
Загрузка Google Satellite, НСПД, ЦОС, Google Labels
"""

from qgis.core import QgsRasterLayer, QgsProject

from Daman_QGIS.utils import log_info, log_warning
from Daman_QGIS.constants import PROVIDER_WMS


class Fsm_1_2_6_RasterLoader:
    """Загрузчик растровых подложек для F_1_2"""

    def __init__(self, iface, layer_manager, api_manager=None):
        """
        Инициализация загрузчика растровых подложек

        Args:
            iface: Интерфейс QGIS
            layer_manager: LayerManager для добавления слоёв
            api_manager: APIManager для получения raster endpoints (опционально)
        """
        self.iface = iface
        self.layer_manager = layer_manager
        self.api_manager = api_manager

    def add_google_satellite(self) -> None:
        """Добавление слоя Google Satellite (только если отсутствует)"""
        layer_name = "L_1_3_1_Google_Satellite"  # Из Base_api_endpoints.json

        # Проверяем существование слоя
        project = QgsProject.instance()
        for existing_layer in project.mapLayers().values():
            if existing_layer.name() == layer_name and existing_layer.isValid():
                log_info(f"Fsm_1_2_6: Слой {layer_name} уже существует, пропускаем")
                return

        # Получаем URI из api_manager (обязательно должен быть в Base_api_endpoints.json)
        assert self.api_manager is not None, "api_manager не инициализирован"
        endpoint = self.api_manager.get_endpoint_by_layer(layer_name)
        assert endpoint is not None, f"Endpoint для {layer_name} не найден в Base_api_endpoints.json"

        base_url = endpoint['base_url']
        # Формируем QGIS XYZ URI для Google
        # Формат: type=xyz&url=https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}&zmax=22&zmin=0
        uri = f"type=xyz&url={base_url}&x={{x}}&y={{y}}&z={{z}}&zmax=22&zmin=0"

        layer = QgsRasterLayer(uri, layer_name, PROVIDER_WMS)

        if layer.isValid():
            # Добавляем в группу функции через layer_manager
            if self.layer_manager:
                self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
        else:
            log_warning(f"Fsm_1_2_6: Не удалось добавить {layer_name}")

    def add_nspd_base_layer(self) -> None:
        """Добавление справочного слоя НСПД - Цифровая объектовая схема (только если отсутствует)"""
        layer_name = "L_1_3_2_Справочный_слой"  # Из Base_api_endpoints.json (category_id 235)

        # Проверяем существование слоя
        project = QgsProject.instance()
        for existing_layer in project.mapLayers().values():
            if existing_layer.name() == layer_name and existing_layer.isValid():
                log_info(f"Fsm_1_2_6: Слой {layer_name} уже существует, пропускаем")
                return

        # Получаем URI из api_manager (обязательно должен быть в Base_api_endpoints.json)
        assert self.api_manager is not None, "api_manager не инициализирован"
        endpoint = self.api_manager.get_endpoint_by_layer(layer_name)
        assert endpoint is not None, f"Endpoint для {layer_name} не найден в Base_api_endpoints.json"

        base_url = endpoint['base_url']
        category_id = endpoint['category_id']
        # Формируем QGIS XYZ URI для НСПД с referer headers
        maphead = f'http-header:referer=https://nspd.gov.ru/map?baseLayerId%3D{category_id}'
        tile_url = f'{base_url}/{{z}}/{{x}}/{{y}}.png'
        uri = f'{maphead}&referer=https://nspd.gov.ru/map?baseLayerId%3D{category_id}&type=xyz&url={tile_url}&zmax=18&zmin=0'

        layer = QgsRasterLayer(uri, layer_name, PROVIDER_WMS)

        if layer.isValid():
            # Добавляем в группу функции через layer_manager
            if self.layer_manager:
                self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
        else:
            log_warning(f"Fsm_1_2_6: Не удалось добавить {layer_name}")

    def add_cos_layer(self) -> None:
        """Добавление слоя ЦОС - Цифровая общегеографическая схема (только если отсутствует)"""
        layer_name = "L_1_3_3_ЦОС"  # Из Base_api_endpoints.json (category_id 849241)

        # Проверяем существование слоя
        project = QgsProject.instance()
        for existing_layer in project.mapLayers().values():
            if existing_layer.name() == layer_name and existing_layer.isValid():
                log_info(f"Fsm_1_2_6: Слой {layer_name} уже существует, пропускаем")
                return

        # Получаем URI из api_manager (обязательно должен быть в Base_api_endpoints.json)
        assert self.api_manager is not None, "api_manager не инициализирован"
        endpoint = self.api_manager.get_endpoint_by_layer(layer_name)
        assert endpoint is not None, f"Endpoint для {layer_name} не найден в Base_api_endpoints.json"

        base_url = endpoint['base_url']
        category_id = endpoint['category_id']
        # Формируем QGIS XYZ URI для ЦОС с referer headers
        maphead = f'http-header:referer=https://nspd.gov.ru/map?baseLayerId%3D{category_id}'
        tile_url = f'{base_url}/{{z}}/{{x}}/{{y}}.png'
        uri = f'{maphead}&referer=https://nspd.gov.ru/map?%26baseLayerId%3D{category_id}&type=xyz&url={tile_url}&zmax=18&zmin=0'

        layer = QgsRasterLayer(uri, layer_name, PROVIDER_WMS)

        if layer.isValid():
            # Добавляем в группу функции через layer_manager
            if self.layer_manager:
                self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
        else:
            log_warning(f"Fsm_1_2_6: Не удалось добавить {layer_name}")

    def add_google_labels(self) -> None:
        """Добавление слоя Google Labels (hybrid)"""
        layer_name = "L_1_3_4_Google_Hybrid"  # Из Base_api_endpoints.json (lyrs=h)

        # Получаем URI из api_manager (обязательно должен быть в Base_api_endpoints.json)
        assert self.api_manager is not None, "api_manager не инициализирован"
        endpoint = self.api_manager.get_endpoint_by_layer(layer_name)
        assert endpoint is not None, f"Endpoint для {layer_name} не найден в Base_api_endpoints.json"

        base_url = endpoint['base_url']
        # Формируем QGIS XYZ URI для Google Hybrid/Labels
        uri = f"type=xyz&url={base_url}&x={{x}}&y={{y}}&z={{z}}&zmax=22&zmin=0"

        layer = QgsRasterLayer(uri, layer_name, PROVIDER_WMS)

        if layer.isValid():
            # Добавляем в группу функции через layer_manager
            # replacement_manager сам управляет удалением старого, добавлением нового, стилем и порядком
            if self.layer_manager:
                self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
        else:
            log_warning("Fsm_1_2_6: Не удалось добавить Google Hybrid")
