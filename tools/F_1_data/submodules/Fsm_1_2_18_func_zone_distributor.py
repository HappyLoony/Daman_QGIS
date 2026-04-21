# -*- coding: utf-8 -*-
"""
Субмодуль F_1_2: Распределение функциональных зон по подслоям

Копирует объекты из Le_1_2_8_1_Фун_зоны в подслои Le_1_2_8_*_Фун_зоны_*_сущ/_план
на основе пары (classname, status).

Маппинг data-driven из Base_fun_zones_distribution.json
(UrbanPlanningReferenceManager.get_fun_zones_mapping).

Допустимые значения status:
- "Существующий, реконструируемый, строящийся" -> layer с суффиксом _сущ
- "Планируемый к размещению"                    -> layer с суффиксом _план

Любое другое значение (NULL, пустое, неизвестная строка) -> warning + пропуск.
"""

import re
from qgis.core import QgsVectorLayer, QgsFeature, QgsProject

from Daman_QGIS.utils import log_info, log_warning, log_success

SOURCE_LAYER_NAME = "Le_1_2_8_1_Фун_зоны"

# Допустимые значения status в WFS Le_1_2_8_1_Фун_зоны
STATUS_EXISTING = "Существующий, реконструируемый, строящийся"
STATUS_PLANNED = "Планируемый к размещению"
ALLOWED_STATUSES = (STATUS_EXISTING, STATUS_PLANNED)


class Fsm_1_2_18_FuncZoneDistributor:
    """Распределитель функциональных зон по подслоям (с учётом status)"""

    def __init__(self, iface, layer_manager, geometry_processor):
        """
        Инициализация распределителя функциональных зон

        Args:
            iface: Интерфейс QGIS
            layer_manager: LayerManager для добавления слоёв
            geometry_processor: Fsm_1_2_8_GeometryProcessor для сохранения в GPKG
        """
        self.iface = iface
        self.layer_manager = layer_manager
        self.geometry_processor = geometry_processor

    def distribute(self, gpkg_path: str) -> int:
        """Распределить объекты функциональных зон по подслоям.

        Читает маппинг (classname, status) -> layer_name из Base_fun_zones_distribution.json.
        Фильтрует features по двум допустимым status (остальные пропускает с warning).
        Группирует по целевому слою и сохраняет в GPKG.

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
            log_info(f"Fsm_1_2_18: Слой {SOURCE_LAYER_NAME} не найден, пропуск распределения")
            return 0

        if source.featureCount() == 0:
            log_info(f"Fsm_1_2_18: Слой {SOURCE_LAYER_NAME} пуст, пропуск распределения")
            return 0

        log_info(
            f"Fsm_1_2_18: Распределение {source.featureCount()} объектов "
            f"с фильтром по status из {SOURCE_LAYER_NAME}"
        )

        # Группировка features по целевому слою
        grouped = {}  # target_name -> list of features
        unmatched_pairs = {}  # "classname | status" -> count
        skipped_bad_status = 0

        for feat in source.getFeatures():
            # Поле WFS называется 'classid' (исторически NSPD), семантически = название класса зоны
            classname = feat["classid"]
            status = feat["status"]

            # Проверка статуса
            if status not in ALLOWED_STATUSES:
                skipped_bad_status += 1
                log_warning(
                    f"Fsm_1_2_18: Объект FID={feat.id()} имеет status='{status}' - пропущен "
                    f"(ожидается '{STATUS_EXISTING}' или '{STATUS_PLANNED}')"
                )
                continue

            # Lookup в маппинге по (classname, status)
            target_name = ref_managers.urban_planning.get_fun_zone_layer(classname, status)
            if not target_name:
                key = f'"{classname}" | "{status}"'
                unmatched_pairs[key] = unmatched_pairs.get(key, 0) + 1
                continue

            grouped.setdefault(target_name, []).append(feat)

        if unmatched_pairs:
            total_unmatched = sum(unmatched_pairs.values())
            details = ", ".join(f"{k} ({v})" for k, v in sorted(unmatched_pairs.items()))
            log_warning(
                f"Fsm_1_2_18: {total_unmatched} объектов не распределены "
                f"(пара classname+status не найдена в Base_fun_zones_distribution): {details}"
            )

        if skipped_bad_status:
            log_warning(
                f"Fsm_1_2_18: {skipped_bad_status} объектов пропущено из-за недопустимого status"
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
            log_info(f"Fsm_1_2_18: {clean_name} - {len(features)} объектов")

        log_success(
            f"Fsm_1_2_18: Распределено {total_distributed} объектов по {len(grouped)} подслоям"
        )
        return total_distributed
