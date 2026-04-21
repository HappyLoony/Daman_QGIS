# -*- coding: utf-8 -*-
"""
Субмодуль F_1_2: Распределение территориальных зон по подслоям

Копирует объекты из Le_1_2_9_1_Терр_зоны в подслои Le_1_2_9_*_Тер_зоны_*
на основе classname. В отличие от Fsm_1_2_18 не фильтрует по status
(семантика данных WFS не требует разделения сущ/план).

Маппинг data-driven из Base_terr_zones_distribution.json
(UrbanPlanningReferenceManager.get_terr_zones_mapping).
"""

import re
from qgis.core import QgsVectorLayer, QgsFeature, QgsProject

from Daman_QGIS.utils import log_info, log_warning, log_success

SOURCE_LAYER_NAME = "Le_1_2_9_1_Терр_зоны"


class Fsm_1_2_17_TerrZoneDistributor:
    """Распределитель территориальных зон по подслоям"""

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
        """Распределить объекты территориальных зон по подслоям.

        Читает маппинг classname -> layer_name из Base_terr_zones_distribution.json.
        Группирует features по целевому слою и сохраняет в GPKG.

        Args:
            gpkg_path: Путь к GeoPackage

        Returns:
            int: Количество распределённых объектов
        """
        # Lazy import для избежания циклической зависимости
        from Daman_QGIS.managers import get_reference_managers
        ref_managers = get_reference_managers()

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

        # Группировка features по целевому слою
        grouped = {}  # target_name -> list of features
        unmatched_classnames = {}  # classname -> count

        for feat in source.getFeatures():
            # Поле WFS называется 'type_zone' (исторически NSPD), семантически = название класса зоны
            classname = feat["type_zone"]
            target_name = ref_managers.urban_planning.get_terr_zone_layer(classname)
            if not target_name:
                key = str(classname) if classname is not None else "<NULL>"
                unmatched_classnames[key] = unmatched_classnames.get(key, 0) + 1
                continue

            grouped.setdefault(target_name, []).append(feat)

        if unmatched_classnames:
            total_unmatched = sum(unmatched_classnames.values())
            details = ", ".join(f'"{k}" ({v})' for k, v in sorted(unmatched_classnames.items()))
            log_warning(
                f"Fsm_1_2_17: {total_unmatched} объектов не распределены "
                f"(classname не найден в Base_terr_zones_distribution): {details}"
            )

        total_distributed = 0

        # Создание подслоёв и сохранение в GPKG
        for target_name, features in grouped.items():
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

        log_success(
            f"Fsm_1_2_17: Распределено {total_distributed} объектов по {len(grouped)} подслоям"
        )
        return total_distributed
