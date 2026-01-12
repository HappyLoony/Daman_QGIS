# -*- coding: utf-8 -*-
"""
Субмодуль F_1_2: Загрузка слоёв ЗОУИТ (зоны с особыми условиями использования территории)
Загрузка и распределение ЗОУИТ по type_zone
"""

import re
from qgis.core import QgsVectorLayer

from Daman_QGIS.utils import log_info, log_warning, log_error, log_success


class Fsm_1_2_9_ZouitLoader:
    """Загрузчик слоёв ЗОУИТ"""

    def __init__(self, iface, egrn_loader, layer_manager, geometry_processor, api_manager):
        """
        Инициализация загрузчика ЗОУИТ

        Args:
            iface: Интерфейс QGIS
            egrn_loader: Экземпляр Fsm_1_2_1_EgrnLoader для загрузки данных
            layer_manager: LayerManager для добавления слоёв
            geometry_processor: Fsm_1_2_8_GeometryProcessor для сохранения в GPKG
            api_manager: APIManager для получения endpoint параметров
        """
        self.iface = iface
        self.egrn_loader = egrn_loader
        self.layer_manager = layer_manager
        self.geometry_processor = geometry_processor
        self.api_manager = api_manager

    def load_zouit_layers_final(self, boundary_layer: QgsVectorLayer, gpkg_path: str, progress_task=None) -> int:
        """Загрузка ЗОУИТ слоёв в конце (после всех остальных слоёв)

        Args:
            boundary_layer: Слой границ работ
            gpkg_path: Путь к GeoPackage
            progress_task: ProgressTask для обновления прогресса

        Returns:
            int: Количество загруженных ЗОУИТ объектов
        """
        try:
            # Проверка что egrn_loader инициализирован
            if not self.egrn_loader:
                log_error("Fsm_1_2_9: egrn_loader не инициализирован для загрузки ЗОУИТ")
                return 0

            log_info("Fsm_1_2_9: Загрузка ЗОУИТ слоёв с распределением по type_zone")

            # Создаём geometry provider с буфером 500м для ЗОУИТ
            # Сохраняем ссылку для использования в lambda
            egrn_loader = self.egrn_loader
            geometry_provider = lambda: egrn_loader.get_boundary_extent(use_500m_buffer=True)

            # Загружаем все ЗОУИТ слои через новый метод
            # Параметры (category_id=36940) извлекаются из Base_api_endpoints.json
            zouit_layers, zouit_total = self.egrn_loader.load_zouit_layers(
                layer_name="WFS_ЗОУИТ_UNIVERSAL",
                geometry_provider=geometry_provider,
                layer_manager=self.layer_manager,
                progress_task=None
            )

            log_info(f"Fsm_1_2_9: ЗОУИТ слои загружены: {len(zouit_layers)} слоёв, {zouit_total} объектов")

            # ДОПОЛНИТЕЛЬНО: Загружаем ООПТ отдельным запросом
            # После обновления API Росреестра ООПТ (category_id=36948) - отдельный endpoint
            try:
                oopt_layer_name = "Le_1_2_5_21_WFS_ЗОУИТ_ОЗ_ООПТ"
                log_info(f"Fsm_1_2_9: Загрузка ООПТ (отдельный endpoint) для слоя {oopt_layer_name}")

                # Загружаем ООПТ через отдельный запрос (параметры из Base_api_endpoints.json endpoint_id=14)
                oopt_layer, oopt_count = self.egrn_loader.load_layer(
                    layer_name=oopt_layer_name,
                    geometry_provider=geometry_provider,
                    progress_task=None
                )

                if oopt_layer and oopt_count > 0:
                    log_info(f"Fsm_1_2_9: ООПТ загружено: {oopt_count} объектов")

                    # Проверяем, есть ли уже слой Le_1_2_5_21 в загруженных ЗОУИТ слоях
                    if oopt_layer_name in zouit_layers:
                        # Объединяем features из ООПТ с существующим слоем Le_1_2_5_21
                        target_layer = zouit_layers[oopt_layer_name]
                        log_info(f"Fsm_1_2_9: Объединение {oopt_count} объектов ООПТ со слоем {oopt_layer_name}")

                        # Копируем features из oopt_layer в target_layer
                        target_layer.startEditing()
                        for feature in oopt_layer.getFeatures():
                            target_layer.addFeature(feature)
                        target_layer.commitChanges()

                        log_info(f"Fsm_1_2_9: Слой {oopt_layer_name} теперь содержит {target_layer.featureCount()} объектов")
                    else:
                        # Если слоя Le_1_2_5_21 нет (не было объектов из ЗОУИТ запроса), создаём его
                        log_info(f"Fsm_1_2_9: Слой {oopt_layer_name} не найден в ЗОУИТ, создаём новый из ООПТ")
                        oopt_layer.setName(oopt_layer_name)
                        zouit_layers[oopt_layer_name] = oopt_layer
                        zouit_total += oopt_count
                else:
                    log_info("Fsm_1_2_9: ООПТ объекты не найдены в данной области")

            except Exception as e:
                log_warning(f"Fsm_1_2_9: Ошибка загрузки ООПТ: {str(e)}")

            # Сохраняем каждый слой в GeoPackage и добавляем через layer_manager
            for layer_name, layer in zouit_layers.items():
                try:
                    # Определяем чистое имя
                    clean_name = layer_name.replace(' ', '_')
                    clean_name = re.sub(r'_{2,}', '_', clean_name)

                    # Переименовываем
                    layer.setName(clean_name)

                    # Сохраняем в GeoPackage
                    saved_layer = self.geometry_processor.save_to_geopackage(layer, gpkg_path, clean_name)
                    if saved_layer:
                        layer = saved_layer

                    # Добавляем через layer_manager
                    if self.layer_manager:
                        layer.setName(clean_name)
                        self.layer_manager.add_layer(layer, make_readonly=False, auto_number=False, check_precision=False)

                except Exception as e:
                    log_error(f"Fsm_1_2_9: Ошибка обработки ЗОУИТ слоя {layer_name}: {str(e)}")

            # ОТКЛЮЧЕНО: Python Stack Trace - Windows fatal exception: access violation
            # Проблема: refresh() может вызывать краш при большом количестве слоёв
            # Карта обновится автоматически после завершения функции
            # self.iface.mapCanvas().refresh()

            return zouit_total

        except Exception as e:
            log_error(f"Fsm_1_2_9: Ошибка загрузки ЗОУИТ слоёв: {str(e)}")
            return 0
