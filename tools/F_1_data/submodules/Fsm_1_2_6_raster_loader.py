# -*- coding: utf-8 -*-
"""
Субмодуль F_1_2: Загрузка растровых подложек НСПД
Загрузка:
- ЕЭКО ортофото (L_1_3_1_NSPD_Ortho, cat=36346) — ортофотоснимки РФ
- ЦОС справочный (L_1_3_2_NSPD_Ref, cat=235) — Цифровая объектовая схема (кадастр)
- ЕЭКО основной (L_1_3_3_NSPD_Base, cat=849241) — общегеографическая базовая карта
"""

from qgis.core import QgsRasterLayer, QgsProject

from Daman_QGIS.utils import log_info, log_warning
from Daman_QGIS.constants import (
    PROVIDER_WMS, NSPD_L_1_3_1_ZMIN, NSPD_L_1_3_2_ZMIN, NSPD_L_1_3_3_ZMIN,
)


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

    def add_nspd_ortho(self) -> None:
        """Добавление слоя ЕЭКО ортофото (L_1_3_1_NSPD_Ortho, category_id=36346).

        Единая электронная картографическая основа (ортофото) от НСПД —
        актуальные ортофотоснимки по всей территории РФ.
        По умолчанию видимость отключена, включается явно через F_1_4.
        """
        layer_name = "L_1_3_1_NSPD_Ortho"  # Из Base_api_endpoints.json (endpoint_id=20)

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
        # XYZ URI без кастомных headers — Referer и User-Agent
        # инжектируются через QgsNetworkAccessManager preprocessor (main_plugin.py)
        # zmin=6: ортофото осмысленно от уровня района. См. constants.NSPD_L_1_3_1_ZMIN.
        tile_url = f'{base_url}/{{z}}/{{x}}/{{y}}.png'
        uri = f'type=xyz&url={tile_url}&zmax=18&zmin={NSPD_L_1_3_1_ZMIN}'

        layer = QgsRasterLayer(uri, layer_name, PROVIDER_WMS)

        if layer.isValid():
            # Добавляем в группу функции через layer_manager
            if self.layer_manager:
                self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
                # Отключаем видимость по умолчанию — ортофото тяжёлое,
                # включается явно через F_1_4 (переключение подложки)
                root = QgsProject.instance().layerTreeRoot()
                layer_node = root.findLayer(layer.id())
                if layer_node:
                    layer_node.setItemVisibilityChecked(False)
                    log_info(f"Fsm_1_2_6: Слой {layer_name} добавлен (видимость отключена)")
        else:
            log_warning(f"Fsm_1_2_6: Не удалось добавить {layer_name}")

    def add_nspd_ref(self) -> None:
        """Добавление справочного слоя НСПД — ЦОС, Цифровая объектовая схема (только если отсутствует).

        Семантика НСПД: кадастровые объекты (ЗУ, ОКС, границы) в виде условных знаков.
        Используется как основная подложка для главной карты (F_1_4_1_main_map).
        """
        layer_name = "L_1_3_2_NSPD_Ref"  # Из Base_api_endpoints.json (category_id=235, endpoint_id=16)

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
        # XYZ URI без кастомных headers — Referer и User-Agent
        # инжектируются через QgsNetworkAccessManager preprocessor (main_plugin.py)
        # zmin=10: кадастровые данные осмысленны от масштаба улицы; на меньших зумах
        # НСПД отдаёт 404 за пределами РФ → burst retry. См. constants.NSPD_L_1_3_2_ZMIN.
        tile_url = f'{base_url}/{{z}}/{{x}}/{{y}}.png'
        uri = f'type=xyz&url={tile_url}&zmax=18&zmin={NSPD_L_1_3_2_ZMIN}'

        layer = QgsRasterLayer(uri, layer_name, PROVIDER_WMS)

        if layer.isValid():
            # Добавляем в группу функции через layer_manager
            if self.layer_manager:
                self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
        else:
            log_warning(f"Fsm_1_2_6: Не удалось добавить {layer_name}")

    def add_nspd_base(self) -> None:
        """Добавление базовой карты НСПД — ЕЭКО основной слой (только если отсутствует).

        Семантика НСПД: общегеографическая основа (дороги, реки, рельеф, НП) —
        Единая электронная картографическая основа, основной слой.
        Используется в обзорной карте (F_1_4_2_overview_map).
        """
        layer_name = "L_1_3_3_NSPD_Base"  # Из Base_api_endpoints.json (category_id=849241, endpoint_id=17)

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
        # XYZ URI без кастомных headers — Referer и User-Agent
        # инжектируются через QgsNetworkAccessManager preprocessor (main_plugin.py)
        # zmin=6: общегеографический фон осмыслен от уровня района; на меньших зумах
        # НСПД отдаёт 404 вне РФ → burst retry. См. constants.NSPD_L_1_3_3_ZMIN.
        tile_url = f'{base_url}/{{z}}/{{x}}/{{y}}.png'
        uri = f'type=xyz&url={tile_url}&zmax=18&zmin={NSPD_L_1_3_3_ZMIN}'

        layer = QgsRasterLayer(uri, layer_name, PROVIDER_WMS)

        if layer.isValid():
            # Добавляем в группу функции через layer_manager
            if self.layer_manager:
                self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)
        else:
            log_warning(f"Fsm_1_2_6: Не удалось добавить {layer_name}")

