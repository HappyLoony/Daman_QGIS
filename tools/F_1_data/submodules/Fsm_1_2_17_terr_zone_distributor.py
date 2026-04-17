# -*- coding: utf-8 -*-
"""
Субмодуль F_1_2: Распределение территориальных зон по подслоям ПЗЗ
Копирует объекты из Le_1_2_9_1_Терр_зоны в подслои на основе type_zone
"""

import re
from qgis.core import QgsVectorLayer, QgsFeature, QgsProject

from Daman_QGIS.utils import log_info, log_warning, log_error, log_success

SOURCE_LAYER_NAME = "Le_1_2_9_1_Терр_зоны"

ZONE_MAPPING = {
    "Жилая зона": "Le_1_2_9_2_ПЗЗ_Жилая",
    "Зона рекреационного назначения": "Le_1_2_9_3_ПЗЗ_Рекреац",
    "Зона специального назначения": "Le_1_2_9_4_ПЗЗ_Спец",
    "Общественно-деловая зона": "Le_1_2_9_5_ПЗЗ_Общ_делов",
    "Производственная зона, зона инженерной и транспортной инфраструктур": "Le_1_2_9_6_ПЗЗ_Производ",
}


class Fsm_1_2_17_TerrZoneDistributor:
    """Распределитель территориальных зон по подслоям ПЗЗ"""

    def __init__(self, iface, layer_manager, geometry_processor):
        """
        Инициализация распределителя территориальных зон

        Args:
            iface: Интерфейс QGIS
            layer_manager: LayerManager для добавления слоёв
            geometry_processor: Fsm_1_2_8_GeometryProcessor для сохранения в GPKG
        """
        self.iface = iface
        self.layer_manager = layer_manager
        self.geometry_processor = geometry_processor

    def distribute(self, gpkg_path: str) -> int:
        """Распределить объекты территориальных зон по подслоям ПЗЗ

        Находит слой Le_1_2_9_1_Терр_зоны, группирует features по type_zone
        и создаёт подслои для каждого типа зоны из ZONE_MAPPING.
        Оригинальный слой остаётся без изменений.

        Args:
            gpkg_path: Путь к GeoPackage

        Returns:
            int: Количество распределённых объектов
        """
        try:
            # Поиск исходного слоя
            source = None
            for layer in QgsProject.instance().mapLayers().values():
                if layer.name() == SOURCE_LAYER_NAME:
                    source = layer
                    break

            if not source or not isinstance(source, QgsVectorLayer):
                log_info(f"Fsm_1_2_17: Слой {SOURCE_LAYER_NAME} не найден, пропуск распределения")
                return 0

            if source.featureCount() == 0:
                log_info(f"Fsm_1_2_17: Слой {SOURCE_LAYER_NAME} пуст, пропуск распределения")
                return 0

            log_info(f"Fsm_1_2_17: Распределение {source.featureCount()} объектов из {SOURCE_LAYER_NAME}")

            # Группировка features по type_zone
            grouped = {}  # target_name -> list of features
            unmatched_types = {}  # type_zone -> count

            for feat in source.getFeatures():
                type_zone = feat["type_zone"]
                if type_zone in ZONE_MAPPING:
                    target_name = ZONE_MAPPING[type_zone]
                    if target_name not in grouped:
                        grouped[target_name] = []
                    grouped[target_name].append(feat)
                else:
                    key = str(type_zone) if type_zone is not None else "<NULL>"
                    unmatched_types[key] = unmatched_types.get(key, 0) + 1

            if unmatched_types:
                total_unmatched = sum(unmatched_types.values())
                details = ", ".join(f'"{k}" ({v})' for k, v in sorted(unmatched_types.items()))
                log_warning(
                    f"Fsm_1_2_17: {total_unmatched} объектов не распределены "
                    f"(type_zone не соответствует маппингу): {details}"
                )

            total_distributed = 0

            # Создание подслоёв и сохранение в GPKG
            for target_name, features in grouped.items():
                try:
                    # Создание memory layer с полями исходника
                    target = QgsVectorLayer(
                        f"MultiPolygon?crs={source.crs().authid()}",
                        target_name, "memory"
                    )
                    target.startEditing()
                    for field in source.fields():
                        target.addAttribute(field)
                    target.commitChanges()

                    # Копирование features
                    target.startEditing()
                    for feat in features:
                        new_feat = QgsFeature(target.fields())
                        new_feat.setGeometry(feat.geometry())
                        new_feat.setAttributes(feat.attributes())
                        target.addFeature(new_feat)
                    target.commitChanges()

                    # Сохранение в GeoPackage (паттерн из Fsm_1_2_9)
                    clean_name = target_name.replace(' ', '_')
                    clean_name = re.sub(r'_{2,}', '_', clean_name)
                    target.setName(clean_name)

                    saved_layer = self.geometry_processor.save_to_geopackage(target, gpkg_path, clean_name)
                    if saved_layer:
                        target = saved_layer

                    if self.layer_manager:
                        target.setName(clean_name)
                        self.layer_manager.add_layer(
                            target, make_readonly=False, auto_number=False, check_precision=False
                        )

                    total_distributed += len(features)
                    log_info(f"Fsm_1_2_17: {clean_name} - {len(features)} объектов")

                except Exception as e:
                    log_error(f"Fsm_1_2_17: Ошибка обработки подслоя {target_name}: {str(e)}")

            log_success(f"Fsm_1_2_17: Распределено {total_distributed} объектов по {len(grouped)} подслоям")
            return total_distributed

        except Exception as e:
            log_error(f"Fsm_1_2_17: Ошибка распределения территориальных зон: {str(e)}")
            return 0
