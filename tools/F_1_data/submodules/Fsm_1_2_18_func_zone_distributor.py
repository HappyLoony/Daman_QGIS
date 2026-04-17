# -*- coding: utf-8 -*-
"""
Субмодуль F_1_2: Распределение функциональных зон по подслоям Ген_Плана
Копирует объекты из Le_1_2_8_1_Фун_зоны в подслои на основе classid
"""

import re
from qgis.core import QgsVectorLayer, QgsFeature, QgsProject

from Daman_QGIS.utils import log_info, log_warning, log_error, log_success

SOURCE_LAYER_NAME = "Le_1_2_8_1_Фун_зоны"

ZONE_MAPPING = {
    "Жилые зоны": "Le_1_2_8_2_Ген_План_Жилые",
    "Зона застройки индивидуальными жилыми домами": "Le_1_2_8_3_Ген_План_ИЖС",
    "Зона инженерной инфраструктуры": "Le_1_2_8_4_Ген_План_Инж",
    "Зона озелененных территорий общего пользования (лесопарки, парки, сады, скверы, бульвары, городские леса)": "Le_1_2_8_5_Ген_План_Зел",
    "Зона режимных территорий": "Le_1_2_8_6_Ген_План_Режим",
    "Зона садоводческих или огороднических некоммерческих товариществ": "Le_1_2_8_7_Ген_План_Сад",
    "Зона смешанной и общественно-деловой застройки": "Le_1_2_8_8_Ген_План_Смеш",
    "Зона специализированной общественной застройки": "Le_1_2_8_9_Ген_План_Спец",
    "Зона транспортной инфраструктуры": "Le_1_2_8_10_Ген_План_Транспорт",
    "Зоны рекреационного назначения": "Le_1_2_8_11_Ген_План_Рекреац",
    "Иные зоны": "Le_1_2_8_12_Ген_План_Иные",
    "Производственные зоны, зоны инженерной и транспортной инфраструктур": "Le_1_2_8_13_Ген_План_Производ",
}


class Fsm_1_2_18_FuncZoneDistributor:
    """Распределитель функциональных зон по подслоям Ген_Плана"""

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
        """Распределить объекты функциональных зон по подслоям Ген_Плана

        Находит слой Le_1_2_8_1_Фун_зоны, группирует features по classid
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
                log_info(f"Fsm_1_2_18: Слой {SOURCE_LAYER_NAME} не найден, пропуск распределения")
                return 0

            if source.featureCount() == 0:
                log_info(f"Fsm_1_2_18: Слой {SOURCE_LAYER_NAME} пуст, пропуск распределения")
                return 0

            log_info(f"Fsm_1_2_18: Распределение {source.featureCount()} объектов из {SOURCE_LAYER_NAME}")

            # Группировка features по classid
            grouped = {}  # target_name -> list of features
            unmatched_types = {}  # classid -> count

            for feat in source.getFeatures():
                classid = feat["classid"]
                if classid in ZONE_MAPPING:
                    target_name = ZONE_MAPPING[classid]
                    if target_name not in grouped:
                        grouped[target_name] = []
                    grouped[target_name].append(feat)
                else:
                    key = str(classid) if classid is not None else "<NULL>"
                    unmatched_types[key] = unmatched_types.get(key, 0) + 1

            if unmatched_types:
                total_unmatched = sum(unmatched_types.values())
                details = ", ".join(f'"{k}" ({v})' for k, v in sorted(unmatched_types.items()))
                log_warning(
                    f"Fsm_1_2_18: {total_unmatched} объектов не распределены "
                    f"(classid не соответствует маппингу): {details}"
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
                    log_info(f"Fsm_1_2_18: {clean_name} - {len(features)} объектов")

                except Exception as e:
                    log_error(f"Fsm_1_2_18: Ошибка обработки подслоя {target_name}: {str(e)}")

            log_success(f"Fsm_1_2_18: Распределено {total_distributed} объектов по {len(grouped)} подслоям")
            return total_distributed

        except Exception as e:
            log_error(f"Fsm_1_2_18: Ошибка распределения функциональных зон: {str(e)}")
            return 0
