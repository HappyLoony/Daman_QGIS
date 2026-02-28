# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_1_2_11: Загрузка красных линий из НСПД

Загружает КЛ из НЕСКОЛЬКИХ endpoints (ЕГРН + МИНСТРОЙ) в ОДИН слой
Le_1_2_7_1_WFS_КЛ_Сущ. Все endpoints с layer_name = TARGET_LAYER_NAME
опрашиваются последовательно, результаты объединяются.

Структура полей берётся от endpoint с наибольшим числом полей (ЕГРН).
Features из остальных источников копируют только геометрию и заполняют
совпадающие поля, остальные = "-".

Все загружаемые КЛ -- существующие. Планируемые КЛ (Le_1_2_7_2_WFS_КЛ_Уст)
создаются пользователем при разработке проекта, НЕ загружаются из НСПД.

Используется функцией F_1_2_Загрузка Web карт (main thread callback).
"""

from typing import Dict, List, Optional, Any, Tuple

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsWkbTypes, QgsField, QgsFields
)
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.utils import log_info, log_warning, log_error, log_success


class Fsm_1_2_11_RedlineLoader:
    """Загрузчик красных линий из нескольких endpoints в один слой"""

    # Целевой слой (все загруженные КЛ -- существующие)
    TARGET_LAYER_NAME = "Le_1_2_7_1_WFS_КЛ_Сущ"

    # Поле-маркер источника данных
    SOURCE_FIELD = "_source"

    def __init__(self, iface, egrn_loader, layer_manager, geometry_processor):
        """
        Инициализация загрузчика красных линий

        Args:
            iface: Интерфейс QGIS
            egrn_loader: Fsm_1_2_1_EgrnLoader для загрузки данных из NSPD
            layer_manager: LayerManager для добавления слоёв в проект
            geometry_processor: Fsm_1_2_8_GeometryProcessor для сохранения в GPKG
        """
        self.iface = iface
        self.egrn_loader = egrn_loader
        self.layer_manager = layer_manager
        self.geometry_processor = geometry_processor

    def load_redline_layers(self, gpkg_path: str) -> int:
        """
        Загрузить красные линии из ВСЕХ endpoints в Le_1_2_7_1_WFS_КЛ_Сущ

        Алгоритм:
        1. Найти все endpoints с layer_name = TARGET_LAYER_NAME
        2. Загрузить данные из каждого endpoint
        3. Определить базовую структуру полей (от endpoint с макс. полями)
        4. Объединить features в одном слое (геометрия + маппинг полей + _source)
        5. Сохранить в GPKG и добавить в проект

        Args:
            gpkg_path: Путь к project.gpkg

        Returns:
            int: Общее количество загруженных объектов
        """
        try:
            if not self.egrn_loader:
                log_error("Fsm_1_2_11: egrn_loader не инициализирован")
                return 0

            # Получаем ВСЕ endpoints для красных линий
            from Daman_QGIS.managers import registry
            api_manager = registry.get('M_14')
            endpoints = api_manager.get_all_endpoints_by_layer(self.TARGET_LAYER_NAME)

            if not endpoints:
                log_warning(
                    f"Fsm_1_2_11: Нет endpoints для '{self.TARGET_LAYER_NAME}' "
                    f"в Base_api_endpoints.json"
                )
                return 0

            log_info(
                f"Fsm_1_2_11: Загрузка красных линий из {len(endpoints)} источников: "
                + ", ".join(ep.get('category_name', '?') for ep in endpoints)
            )

            # Geometry provider стандартный 10м (Layer_selector = L_1_1_2)
            geometry_provider = self.egrn_loader.get_boundary_extent

            # Загрузка из каждого endpoint
            # Каждый результат: (layer, count, ep_name)
            loaded_layers: List[Tuple[QgsVectorLayer, int, str]] = []

            for ep in endpoints:
                ep_name = ep.get('category_name', f"EP_{ep.get('endpoint_id', '?')}")
                ep_id = ep.get('endpoint_id', '?')

                try:
                    layer, count = self.egrn_loader.load_layer_by_endpoint(
                        endpoint=ep,
                        geometry_provider=geometry_provider,
                        progress_task=None
                    )

                    if not layer or count == 0:
                        log_info(f"Fsm_1_2_11: EP {ep_id} ({ep_name}): 0 объектов")
                        continue

                    log_info(f"Fsm_1_2_11: EP {ep_id} ({ep_name}): {count} объектов")
                    loaded_layers.append((layer, count, ep_name))

                except Exception as e:
                    log_error(f"Fsm_1_2_11: Ошибка загрузки EP {ep_id} ({ep_name}): {str(e)}")

            if not loaded_layers:
                log_info("Fsm_1_2_11: Красные линии не найдены в данной области")
                return 0

            total_features = sum(count for _, count, _ in loaded_layers)
            log_info(
                f"Fsm_1_2_11: Всего {total_features} объектов из "
                f"{len(loaded_layers)} источников"
            )

            # Определяем базовую структуру полей: от endpoint с макс. числом полей
            # (ЕГРН имеет больше полей, МИНСТРОЙ меньше)
            base_layer = max(loaded_layers, key=lambda x: x[0].fields().count())[0]
            base_fields = base_layer.fields()
            base_crs = base_layer.crs().authid()
            base_wkb_type = base_layer.wkbType()

            log_info(
                f"Fsm_1_2_11: Базовая структура полей ({base_fields.count()} полей) "
                f"от источника с макс. полями"
            )

            # Создаём объединённый слой со структурой базового endpoint
            merged_layer = self._create_merged_layer(
                loaded_layers, base_fields, base_crs, base_wkb_type
            )
            if not merged_layer:
                return 0

            total_count = merged_layer.featureCount()

            # Сохранение в GeoPackage
            clean_name = self.TARGET_LAYER_NAME
            merged_layer.setName(clean_name)

            saved_layer = self.geometry_processor.save_to_geopackage(
                merged_layer, gpkg_path, clean_name
            )
            if saved_layer:
                merged_layer = saved_layer

            # Добавление в проект
            if self.layer_manager:
                merged_layer.setName(clean_name)
                self.layer_manager.add_layer(
                    merged_layer, make_readonly=False,
                    auto_number=False, check_precision=False
                )

            # Обновление карты
            from Daman_QGIS.utils import safe_refresh_canvas, REFRESH_HEAVY
            safe_refresh_canvas(REFRESH_HEAVY, delay_ms=200)

            log_success(f"Fsm_1_2_11: Красные линии загружены: {total_count} объектов в {clean_name}")
            return total_count

        except Exception as e:
            log_error(f"Fsm_1_2_11: Ошибка загрузки красных линий: {str(e)}")
            return 0

    def _create_merged_layer(
        self,
        loaded_layers: List[Tuple[QgsVectorLayer, int, str]],
        base_fields: QgsFields,
        crs: str,
        wkb_type: int
    ) -> Optional[QgsVectorLayer]:
        """
        Создать объединённый слой со структурой полей от базового endpoint

        Структура полей берётся от endpoint с наибольшим числом полей (ЕГРН).
        Features из других источников (МИНСТРОЙ) копируют геометрию и
        заполняют совпадающие поля, остальные = "-".

        Args:
            loaded_layers: Список (layer, count, source_name)
            base_fields: Структура полей базового слоя (ЕГРН)
            crs: CRS (например "EPSG:3857")
            wkb_type: Тип геометрии

        Returns:
            QgsVectorLayer или None
        """
        try:
            geom_type_str = QgsWkbTypes.displayString(wkb_type)
            merged = QgsVectorLayer(
                f"{geom_type_str}?crs={crs}", self.TARGET_LAYER_NAME, "memory"
            )
            provider = merged.dataProvider()
            if not provider:
                log_error("Fsm_1_2_11: Не удалось создать merged layer")
                return None

            # Структура полей = базовый endpoint + _source
            fields_list = base_fields.toList()
            fields_list.append(QgsField(self.SOURCE_FIELD, QMetaType.Type.QString))
            provider.addAttributes(fields_list)
            merged.updateFields()

            source_field_idx = merged.fields().indexOf(self.SOURCE_FIELD)

            # Копируем features из всех источников
            new_features: List[QgsFeature] = []

            for layer, _count, source_name in loaded_layers:
                for feat in layer.getFeatures():
                    new_feat = QgsFeature(merged.fields())
                    new_feat.setGeometry(feat.geometry())

                    # Маппинг атрибутов: совпадающие по имени копируются,
                    # отсутствующие = "-"
                    for i, field in enumerate(merged.fields()):
                        if i == source_field_idx:
                            new_feat.setAttribute(i, source_name)
                        else:
                            src_idx = feat.fields().indexOf(field.name())
                            if src_idx >= 0:
                                new_feat.setAttribute(i, feat.attribute(src_idx))
                            else:
                                new_feat.setAttribute(i, "-")

                    new_features.append(new_feat)

            provider.addFeatures(new_features)
            merged.updateExtents()

            log_info(
                f"Fsm_1_2_11: Объединённый слой: {len(new_features)} объектов, "
                f"{base_fields.count()} полей + {self.SOURCE_FIELD}"
            )
            return merged

        except Exception as e:
            log_error(f"Fsm_1_2_11: Ошибка создания объединённого слоя: {str(e)}")
            return None
