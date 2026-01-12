# -*- coding: utf-8 -*-
"""
Msm_26_3 - Создание выходных слоёв для нарезки ЗПР

Выполняет:
- Создание слоёв в GeoPackage
- Установка структуры полей из Base_cutting.json
- Сохранение features в слой
- Добавление слоя в проект QGIS

Перенесено из Fsm_3_1_3_layer_creator
"""

import os
from typing import List, Optional, Dict, Any

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsFeature,
    QgsGeometry,
    QgsCoordinateReferenceSystem,
    QgsWkbTypes,
    Qgis,
    QgsFields,
)

from Daman_QGIS.utils import log_info, log_warning, log_error

# Импорт типа для аннотаций
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .Msm_26_2_attribute_mapper import Msm_26_2_AttributeMapper


class Msm_26_3_LayerCreator:
    """Создатель слоёв для нарезки ЗПР"""

    def __init__(
        self,
        gpkg_path: str,
        attribute_mapper: 'Msm_26_2_AttributeMapper'
    ) -> None:
        """Инициализация создателя слоёв

        Args:
            gpkg_path: Путь к GeoPackage проекта
            attribute_mapper: Маппер атрибутов (для получения структуры полей)
        """
        self.gpkg_path = gpkg_path
        self.attribute_mapper = attribute_mapper

    def create_cutting_layer(
        self,
        layer_name: str,
        crs: QgsCoordinateReferenceSystem,
        features_data: List[Dict[str, Any]]
    ) -> Optional[QgsVectorLayer]:
        """Создание слоя нарезки с данными

        Args:
            layer_name: Имя слоя (например, "Le_3_1_1_1_Раздел_ЗПР_ОКС")
            crs: Система координат
            features_data: Список словарей с данными
                          [{'geometry': QgsGeometry, 'attributes': dict}, ...]

        Returns:
            QgsVectorLayer: Созданный слой или None при ошибке
        """
        if not features_data:
            log_warning(f"Msm_26_3: Нет данных для слоя {layer_name}")
            return None

        try:
            # Получаем структуру полей
            fields = self.attribute_mapper.get_fields()

            # Создаём features
            features = self._create_features(features_data, fields)

            if not features:
                log_warning(f"Msm_26_3: Не удалось создать features для слоя {layer_name}")
                return None

            # Сохраняем в GeoPackage
            success = self._save_to_gpkg(layer_name, crs, fields, features)

            if not success:
                log_error(f"Msm_26_3: Ошибка сохранения слоя {layer_name} в GPKG")
                return None

            # Загружаем слой из GPKG
            layer = self._load_layer_from_gpkg(layer_name)

            if layer and layer.isValid():
                log_info(f"Msm_26_3: Создан слой {layer_name} ({layer.featureCount()} объектов)")
                return layer
            else:
                log_error(f"Msm_26_3: Не удалось загрузить слой {layer_name} из GPKG")
                return None

        except Exception as e:
            log_error(f"Msm_26_3: Ошибка создания слоя {layer_name}: {e}")
            return None

    def _create_features(
        self,
        features_data: List[Dict[str, Any]],
        fields: QgsFields
    ) -> List[QgsFeature]:
        """Создание списка QgsFeature из данных

        Использует WKB deep copy для безопасной передачи геометрий
        между слоями и избежания проблем с указателями.

        Args:
            features_data: Список словарей с geometry и attributes
            fields: Структура полей

        Returns:
            List[QgsFeature]: Список features
        """
        features = []

        for data in features_data:
            geometry = data.get('geometry')
            attributes = data.get('attributes', {})

            if not geometry or geometry.isEmpty():
                continue

            feature = QgsFeature(fields)

            # WKB deep copy - безопасная передача геометрии
            # Избегает проблем с указателями при передаче между слоями
            wkb = geometry.asWkb()
            new_geom = QgsGeometry()
            new_geom.fromWkb(wkb)
            feature.setGeometry(new_geom)

            # Устанавливаем атрибуты
            attr_list = self.attribute_mapper.attributes_to_list(attributes)
            feature.setAttributes(attr_list)

            features.append(feature)

        return features

    def _save_to_gpkg(
        self,
        layer_name: str,
        crs: QgsCoordinateReferenceSystem,
        fields: QgsFields,
        features: List[QgsFeature]
    ) -> bool:
        """Сохранение features в GeoPackage

        Args:
            layer_name: Имя слоя/таблицы
            crs: Система координат
            fields: Структура полей
            features: Список features

        Returns:
            bool: True если успешно
        """
        try:
            # Параметры сохранения
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = layer_name

            # Если GPKG существует - добавляем слой, иначе создаём
            if os.path.exists(self.gpkg_path):
                options.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
            else:
                options.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile

            # Создаём временный memory layer
            mem_layer = QgsVectorLayer(
                f"MultiPolygon?crs={crs.authid()}",
                layer_name,
                "memory"
            )

            if not mem_layer.isValid():
                log_error(f"Msm_26_3: Не удалось создать memory layer для {layer_name}")
                return False

            # Добавляем поля
            mem_layer.dataProvider().addAttributes(fields.toList())
            mem_layer.updateFields()

            # Добавляем features
            mem_layer.dataProvider().addFeatures(features)

            # Сохраняем в GPKG
            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                mem_layer,
                self.gpkg_path,
                QgsProject.instance().transformContext(),
                options
            )

            if error[0] != QgsVectorFileWriter.WriterError.NoError:
                log_error(f"Msm_26_3: Ошибка записи в GPKG: {error[1]}")
                return False

            return True

        except Exception as e:
            log_error(f"Msm_26_3: Исключение при сохранении в GPKG: {e}")
            return False

    def _load_layer_from_gpkg(self, layer_name: str) -> Optional[QgsVectorLayer]:
        """Загрузка слоя из GeoPackage

        Args:
            layer_name: Имя слоя/таблицы

        Returns:
            QgsVectorLayer: Загруженный слой или None
        """
        uri = f"{self.gpkg_path}|layername={layer_name}"
        layer = QgsVectorLayer(uri, layer_name, "ogr")

        if layer.isValid():
            return layer
        else:
            log_error(f"Msm_26_3: Не удалось загрузить слой из {uri}")
            return None

    def delete_existing_layer(self, layer_name: str) -> bool:
        """Удаление существующего слоя из GPKG

        Args:
            layer_name: Имя слоя

        Returns:
            bool: True если успешно (или слой не существовал)
        """
        if not os.path.exists(self.gpkg_path):
            return True

        try:
            from osgeo import ogr

            ds = ogr.Open(self.gpkg_path, update=True)
            if ds is None:
                return True

            # Ищем слой
            layer_idx = -1
            for i in range(ds.GetLayerCount()):
                if ds.GetLayerByIndex(i).GetName() == layer_name:
                    layer_idx = i
                    break

            if layer_idx >= 0:
                ds.DeleteLayer(layer_idx)
                log_info(f"Msm_26_3: Удалён существующий слой {layer_name}")

            ds = None
            return True

        except Exception as e:
            log_warning(f"Msm_26_3: Не удалось удалить слой {layer_name}: {e}")
            return False
