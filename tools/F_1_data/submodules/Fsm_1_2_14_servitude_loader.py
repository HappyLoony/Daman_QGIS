# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_1_2_14: Загрузка публичных сервитутов из НСПД

Загружает публичные сервитуты из НЕСКОЛЬКИХ endpoints (разные категории НСПД)
в ОДИН слой Le_1_2_6_2_WFS_ПС. Все endpoints с layer_name = TARGET_LAYER_NAME
опрашиваются последовательно, результаты объединяются.

Отличие от RedlineLoader (Fsm_1_2_11):
- Поля СИНХРОНИЗИРУЮТСЯ: объединение (UNION) всех полей из всех источников
- Общие поля заполняются значениями из каждого источника
- Уникальные поля одного источника = NULL для объектов другого источника
- RedlineLoader берёт поля от endpoint с MAX полями, остальные = "-"

Источники (категории НСПД):
1. Отдельная категория публичных сервитутов (EP 29, cat_id=39353) - все объекты = ПС
2. Иные ЗОУИТ (EP 30, cat_id=469042) - смешанная категория, содержит ПС + другие ЗОУИТ,
   требуется фильтрация по type_zone/name_by_doc

EP 11 (cat=36940, ЗОУИТ universal) НЕ используется: все его ПС дублируют EP 30.

Используется функцией F_1_2_Загрузка Web карт (main thread callback).
"""

from typing import Dict, List, Optional, Any, Tuple, Set

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsWkbTypes, QgsField
)
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.utils import log_info, log_warning, log_error, log_success


class Fsm_1_2_14_ServitudeLoader:
    """Загрузчик публичных сервитутов из нескольких endpoints в один слой

    Синхронизация полей: UNION всех полей из всех источников.
    Общие поля копируются, уникальные = NULL для чужих объектов.
    """

    # Целевой слой
    TARGET_LAYER_NAME = "Le_1_2_6_2_WFS_ПС"

    # Поле-маркер источника данных
    SOURCE_FIELD = "_source"

    # Категория, содержащая ТОЛЬКО публичные сервитуты (фильтрация не нужна)
    PURE_SERVITUDE_CATEGORY = 39353

    # Категории, содержащие смешанные ЗОУИТ (нужна фильтрация по type_zone/name_by_doc)
    # EP 30 (cat=469042) - "Иные ЗОУИТ" содержит ПС + охранные зоны + иные зоны
    MIXED_ZOUIT_CATEGORIES = {469042}

    # Ключевое слово для фильтрации сервитутов в смешанных категориях
    _SERVITUDE_KEYWORD = "сервитут"

    def __init__(self, iface, egrn_loader, layer_manager, geometry_processor):
        """
        Инициализация загрузчика публичных сервитутов

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

    def load_servitude_layers(self, gpkg_path: str) -> int:
        """
        Загрузить публичные сервитуты из ВСЕХ endpoints в Le_1_2_6_2_WFS_ПС

        Алгоритм:
        1. Найти все endpoints с layer_name = TARGET_LAYER_NAME
        2. Загрузить данные из каждого endpoint
        3. Собрать UNION всех полей (синхронизация)
        4. Объединить features (геометрия + синхронизированные поля + _source)
        5. Сохранить в GPKG и добавить в проект

        Args:
            gpkg_path: Путь к project.gpkg

        Returns:
            int: Общее количество загруженных объектов
        """
        try:
            if not self.egrn_loader:
                log_error("Fsm_1_2_14: egrn_loader не инициализирован")
                return 0

            # Получаем ВСЕ endpoints для публичных сервитутов
            from Daman_QGIS.managers import registry
            api_manager = registry.get('M_14')
            endpoints = api_manager.get_all_endpoints_by_layer(self.TARGET_LAYER_NAME)

            if not endpoints:
                log_warning(
                    f"Fsm_1_2_14: Нет endpoints для '{self.TARGET_LAYER_NAME}' "
                    f"в Base_api_endpoints.json"
                )
                return 0

            log_info(
                f"Fsm_1_2_14: Загрузка публичных сервитутов из {len(endpoints)} источников: "
                + ", ".join(ep.get('category_name', '?') for ep in endpoints)
            )

            # Загрузка из каждого endpoint
            loaded_layers: List[Tuple[QgsVectorLayer, int, str]] = []

            for ep in endpoints:
                ep_name = ep.get('category_name', f"EP_{ep.get('endpoint_id', '?')}")
                ep_id = ep.get('endpoint_id', '?')
                cat_id = ep.get('category_id')

                try:
                    # Определяем geometry_provider по Layer_selector endpoint'а
                    geometry_provider = self._get_geometry_provider(ep)

                    layer, count = self.egrn_loader.load_layer_by_endpoint(
                        endpoint=ep,
                        geometry_provider=geometry_provider,
                        progress_task=None
                    )

                    if not layer or count == 0:
                        log_info(f"Fsm_1_2_14: EP {ep_id} ({ep_name}): 0 объектов")
                        continue

                    log_info(f"Fsm_1_2_14: EP {ep_id} ({ep_name}): {count} объектов")

                    # Фильтрация для смешанных категорий (EP 30 содержит ПС + другие ЗОУИТ)
                    if cat_id in self.MIXED_ZOUIT_CATEGORIES:
                        layer, count = self._filter_servitudes_from_mixed(layer, ep_name)
                        if count == 0:
                            log_info(f"Fsm_1_2_14: EP {ep_id} ({ep_name}): 0 ПС после фильтрации")
                            continue

                    loaded_layers.append((layer, count, ep_name))

                except Exception as e:
                    log_error(f"Fsm_1_2_14: Ошибка загрузки EP {ep_id} ({ep_name}): {str(e)}")

            if not loaded_layers:
                log_info("Fsm_1_2_14: Публичные сервитуты не найдены в данной области")
                return 0

            # Создаём объединённый слой с СИНХРОНИЗИРОВАННЫМИ полями (UNION)
            merged_layer = self._create_merged_layer(loaded_layers)
            if not merged_layer:
                return 0

            total_count = merged_layer.featureCount()

            # Дедупликация геометрий (multi-endpoint слой)
            from .Fsm_1_2_16_deduplicator import Fsm_1_2_16_Deduplicator
            deduplicator = Fsm_1_2_16_Deduplicator(caller_id="Fsm_1_2_14")
            dedup_result = deduplicator.deduplicate(merged_layer)
            total_count = dedup_result['remaining']

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

            # Refresh canvas централизован в sort_all_layers() (M_2)

            log_success(
                f"Fsm_1_2_14: Публичные сервитуты загружены: "
                f"{total_count} объектов в {clean_name}"
            )
            return total_count

        except Exception as e:
            log_error(f"Fsm_1_2_14: Ошибка загрузки публичных сервитутов: {str(e)}")
            return 0

    def _get_geometry_provider(self, endpoint: Dict[str, Any]):
        """
        Определить geometry_provider по Layer_selector endpoint'а

        Args:
            endpoint: Конфигурация endpoint из Base_api_endpoints.json

        Returns:
            Callable для получения extent границ работ
        """
        boundary_selector = endpoint.get('Layer_selector', '')
        if boundary_selector == "L_1_1_3_Границы_работ_500_м":
            egrn_loader = self.egrn_loader
            return lambda: egrn_loader.get_boundary_extent(use_500m_buffer=True)
        return self.egrn_loader.get_boundary_extent

    def _filter_servitudes_from_mixed(
        self, layer: QgsVectorLayer, ep_name: str
    ) -> Tuple[QgsVectorLayer, int]:
        """
        Отфильтровать только публичные сервитуты из слоя смешанной ЗОУИТ категории

        EP 30 (cat=469042) содержит разные типы ЗОУИТ. Фильтруем по:
        - type_zone содержит "сервитут"
        - ИЛИ name_by_doc содержит "сервитут" (для объектов с пустым type_zone)

        Args:
            layer: Загруженный слой с объектами смешанной категории
            ep_name: Имя источника для логирования

        Returns:
            tuple: (отфильтрованный слой, количество объектов)
        """
        keyword = self._SERVITUDE_KEYWORD
        original_count = layer.featureCount()

        # Ищем индексы полей type_zone и name_by_doc
        type_zone_idx = layer.fields().indexOf("type_zone")
        name_by_doc_idx = layer.fields().indexOf("name_by_doc")

        if type_zone_idx < 0 and name_by_doc_idx < 0:
            log_warning(
                f"Fsm_1_2_14: Нет полей type_zone/name_by_doc в '{ep_name}', "
                f"фильтрация невозможна, используем все {original_count} объектов"
            )
            return layer, original_count

        # Создаём отфильтрованный слой (той же структуры)
        geom_type_str = QgsWkbTypes.displayString(layer.wkbType())
        crs = layer.crs().authid()
        filtered = QgsVectorLayer(
            f"{geom_type_str}?crs={crs}", layer.name(), "memory"
        )
        provider = filtered.dataProvider()
        if not provider:
            return layer, original_count

        provider.addAttributes(layer.fields().toList())
        filtered.updateFields()

        servitude_features: List[QgsFeature] = []

        for feat in layer.getFeatures():
            is_servitude = False

            if type_zone_idx >= 0:
                tz = str(feat.attribute(type_zone_idx) or "").lower()
                if keyword in tz:
                    is_servitude = True

            if not is_servitude and name_by_doc_idx >= 0:
                name = str(feat.attribute(name_by_doc_idx) or "").lower()
                if keyword in name:
                    is_servitude = True

            if is_servitude:
                servitude_features.append(feat)

        provider.addFeatures(servitude_features)
        filtered.updateExtents()

        filtered_count = len(servitude_features)
        removed_count = original_count - filtered_count

        if removed_count > 0:
            log_info(
                f"Fsm_1_2_14: Фильтрация '{ep_name}': "
                f"{filtered_count} ПС из {original_count} объектов "
                f"(удалено {removed_count} не-ПС)"
            )
        else:
            log_info(
                f"Fsm_1_2_14: Фильтрация '{ep_name}': "
                f"все {original_count} объектов = ПС"
            )

        return filtered, filtered_count

    def _collect_union_fields(
        self, loaded_layers: List[Tuple[QgsVectorLayer, int, str]]
    ) -> List[QgsField]:
        """
        Собрать UNION всех полей из всех источников, сохраняя порядок

        Первый источник задаёт порядок своих полей, затем добавляются
        уникальные поля из последующих источников.

        Args:
            loaded_layers: Список (layer, count, source_name)

        Returns:
            List[QgsField]: Объединённый список полей (без _source)
        """
        seen_names: Set[str] = set()
        union_fields: List[QgsField] = []

        for layer, _, _ in loaded_layers:
            for field in layer.fields():
                if field.name() not in seen_names:
                    seen_names.add(field.name())
                    union_fields.append(QgsField(field))

        return union_fields

    def _create_merged_layer(
        self,
        loaded_layers: List[Tuple[QgsVectorLayer, int, str]]
    ) -> Optional[QgsVectorLayer]:
        """
        Создать объединённый слой с СИНХРОНИЗИРОВАННЫМИ полями

        В отличие от RedlineLoader (который берёт поля от endpoint с MAX полями):
        - Собираем UNION всех полей из всех источников
        - Общие поля: значения копируются из каждого источника
        - Уникальные поля: заполняются только из своего источника, NULL для чужих

        Args:
            loaded_layers: Список (layer, count, source_name)

        Returns:
            QgsVectorLayer или None
        """
        try:
            # CRS и тип геометрии от первого слоя
            first_layer = loaded_layers[0][0]
            crs = first_layer.crs().authid()
            wkb_type = first_layer.wkbType()

            # Собираем UNION всех полей
            union_fields = self._collect_union_fields(loaded_layers)

            # Создаём memory layer
            geom_type_str = QgsWkbTypes.displayString(wkb_type)
            merged = QgsVectorLayer(
                f"{geom_type_str}?crs={crs}", self.TARGET_LAYER_NAME, "memory"
            )
            provider = merged.dataProvider()
            if not provider:
                log_error("Fsm_1_2_14: Не удалось создать merged layer")
                return None

            # Структура полей = UNION + _source
            fields_list = list(union_fields)
            fields_list.append(QgsField(self.SOURCE_FIELD, QMetaType.Type.QString))
            provider.addAttributes(fields_list)
            merged.updateFields()

            source_field_idx = merged.fields().indexOf(self.SOURCE_FIELD)

            # Копируем features из всех источников с синхронизацией полей
            new_features: List[QgsFeature] = []

            for layer, _count, source_name in loaded_layers:
                for feat in layer.getFeatures():
                    new_feat = QgsFeature(merged.fields())
                    new_feat.setGeometry(feat.geometry())

                    # Синхронизация атрибутов:
                    # - Общие поля: копируются из источника
                    # - Уникальные поля другого источника: остаются NULL
                    # - _source: имя источника
                    for i, field in enumerate(merged.fields()):
                        if i == source_field_idx:
                            new_feat.setAttribute(i, source_name)
                        else:
                            src_idx = feat.fields().indexOf(field.name())
                            if src_idx >= 0:
                                new_feat.setAttribute(i, feat.attribute(src_idx))
                            # else: оставляем NULL (поле не существует в этом источнике)

                    new_features.append(new_feat)

            provider.addFeatures(new_features)
            merged.updateExtents()

            return merged

        except Exception as e:
            log_error(f"Fsm_1_2_14: Ошибка создания объединённого слоя: {str(e)}")
            return None
