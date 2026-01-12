# -*- coding: utf-8 -*-
"""
Fsm_3_1_6_PointLayerCreator - Создание точечных слоёв для нарезки ЗПР

Создаёт слои характерных точек (MultiPoint) с уникальной нумерацией.
Структура полей:
- ID: номер точки (глобальный)
- ID_Точки_контура: номер точки внутри контура (1, 2, 3...)
- ID_Контура: ID контура
- Услов_КН: условный кадастровый номер контура
- КН: кадастровый номер контура
- Тип_контура: Внешний/Внутренний
- Номер_контура: параллельная нумерация (1, 2, 3... отдельно для внешних и внутренних)
- X, Y: геодезические координаты

Слои точек:
- Le_3_5_1_1_Т_Раздел_ЗПР_ОКС
- Le_3_5_1_2_Т_НГС_ЗПР_ОКС
- и аналогично для ЛО, ВО
"""

import os
from typing import List, Optional, Dict, Any

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsCoordinateReferenceSystem,
    QgsFields,
    QgsField,
)
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.constants import COORDINATE_PRECISION


class Fsm_3_1_6_PointLayerCreator:
    """Создатель точечных слоёв для нарезки ЗПР"""

    # Маппинг полигональных слоёв на точечные
    # {polygon_layer_name_suffix: point_layer_name}
    POINT_LAYER_MAPPING = {
        # ОКС
        'Le_3_1_1_1_Раздел_ЗПР_ОКС': 'Le_3_5_1_1_Т_Раздел_ЗПР_ОКС',
        'Le_3_1_1_2_НГС_ЗПР_ОКС': 'Le_3_5_1_2_Т_НГС_ЗПР_ОКС',
        'Le_3_1_1_3_Без_Меж_ЗПР_ОКС': 'Le_3_5_1_3_Т_Без_Меж_ЗПР_ОКС',
        'Le_3_1_1_4_ПС_ЗПР_ОКС': 'Le_3_5_1_4_Т_ПС_ЗПР_ОКС',
        # ПО
        'Le_3_1_2_1_Раздел_ЗПР_ПО': 'Le_3_5_2_1_Т_Раздел_ЗПР_ПО',
        'Le_3_1_2_2_НГС_ЗПР_ПО': 'Le_3_5_2_2_Т_НГС_ЗПР_ПО',
        'Le_3_1_2_3_Без_Меж_ЗПР_ПО': 'Le_3_5_2_3_Т_Без_Меж_ЗПР_ПО',
        'Le_3_1_2_4_ПС_ЗПР_ПО': 'Le_3_5_2_4_Т_ПС_ЗПР_ПО',
        # ВО
        'Le_3_1_3_1_Раздел_ЗПР_ВО': 'Le_3_5_3_1_Т_Раздел_ЗПР_ВО',
        'Le_3_1_3_2_НГС_ЗПР_ВО': 'Le_3_5_3_2_Т_НГС_ЗПР_ВО',
        'Le_3_1_3_3_Без_Меж_ЗПР_ВО': 'Le_3_5_3_3_Т_Без_Меж_ЗПР_ВО',
        'Le_3_1_3_4_ПС_ЗПР_ВО': 'Le_3_5_3_4_Т_ПС_ЗПР_ВО',
    }

    def __init__(self, gpkg_path: str) -> None:
        """Инициализация создателя точечных слоёв

        Args:
            gpkg_path: Путь к GeoPackage проекта
        """
        self.gpkg_path = gpkg_path

    def get_point_layer_name(self, polygon_layer_name: str) -> Optional[str]:
        """Получить имя точечного слоя по имени полигонального

        Args:
            polygon_layer_name: Имя полигонального слоя

        Returns:
            Имя соответствующего точечного слоя или None
        """
        return self.POINT_LAYER_MAPPING.get(polygon_layer_name)

    def create_point_layer(
        self,
        layer_name: str,
        crs: QgsCoordinateReferenceSystem,
        points_data: List[Dict[str, Any]]
    ) -> Optional[QgsVectorLayer]:
        """Создание точечного слоя с данными

        Args:
            layer_name: Имя слоя (например, "Le_3_5_1_1_Т_Раздел_ЗПР_ОКС")
            crs: Система координат
            points_data: Список словарей с данными точек:
                        [{'id': int, 'contour_id': int,
                          'x_geodetic': float, 'y_geodetic': float,
                          'point': QgsPointXY}]

        Returns:
            QgsVectorLayer: Созданный слой или None при ошибке
        """
        if not points_data:
            log_warning(f"Fsm_3_1_6: Нет данных точек для слоя {layer_name}")
            return None

        try:
            # Создаём структуру полей
            fields = self._create_fields()

            # Создаём features
            features = self._create_features(points_data, fields)

            if not features:
                log_warning(f"Fsm_3_1_6: Не удалось создать features для слоя {layer_name}")
                return None

            # Сохраняем в GeoPackage
            success = self._save_to_gpkg(layer_name, crs, fields, features)

            if not success:
                log_error(f"Fsm_3_1_6: Ошибка сохранения слоя {layer_name} в GPKG")
                return None

            # Загружаем слой из GPKG
            layer = self._load_layer_from_gpkg(layer_name)

            if layer is not None and layer.isValid():
                log_info(f"Fsm_3_1_6: Создан точечный слой {layer_name} ({layer.featureCount()} точек)")
                return layer
            else:
                log_error(f"Fsm_3_1_6: Не удалось загрузить слой {layer_name} из GPKG")
                return None

        except Exception as e:
            log_error(f"Fsm_3_1_6: Ошибка создания слоя {layer_name}: {e}")
            return None

    def _create_fields(self) -> QgsFields:
        """Создание структуры полей точечного слоя

        Поля:
        - ID: Номер точки (уникальный в пределах слоя)
        - ID_Точки_контура: Номер точки внутри контура (1, 2, 3...)
        - ID_Контура: ID контура к которому принадлежит точка
        - Услов_КН: Условный кадастровый номер контура
        - КН: Кадастровый номер контура
        - Тип_контура: 'Внешний' или 'Внутренний'
        - Номер_контура: Параллельная нумерация (1, 2, 3... отдельно для внешних и внутренних)
        - X: X координата (геодезический, т.е. Y математический)
        - Y: Y координата (геодезический, т.е. X математический)

        Returns:
            QgsFields: Структура полей
        """
        fields = QgsFields()

        # ID точки (глобальный номер)
        fields.append(QgsField("ID", QMetaType.Type.Int))

        # ID точки внутри контура (локальный номер: 1, 2, 3...)
        fields.append(QgsField("ID_Точки_контура", QMetaType.Type.Int))

        # ID контура
        fields.append(QgsField("ID_Контура", QMetaType.Type.Int))

        # Условный КН контура (для связи с полигональным слоём)
        fields.append(QgsField("Услов_КН", QMetaType.Type.QString))

        # КН контура (для связи с полигональным слоём)
        fields.append(QgsField("КН", QMetaType.Type.QString))

        # Тип контура: Внешний или Внутренний
        fields.append(QgsField("Тип_контура", QMetaType.Type.QString))

        # Номер контура: параллельная нумерация (1, 2, 3...)
        fields.append(QgsField("Номер_контура", QMetaType.Type.Int))

        # X геодезический (Y математический)
        fields.append(QgsField("X", QMetaType.Type.Double))

        # Y геодезический (X математический)
        fields.append(QgsField("Y", QMetaType.Type.Double))

        return fields

    def _create_features(
        self,
        points_data: List[Dict[str, Any]],
        fields: QgsFields
    ) -> List[QgsFeature]:
        """Создание списка QgsFeature из данных точек

        Args:
            points_data: Список словарей с данными точек
            fields: Структура полей

        Returns:
            List[QgsFeature]: Список features
        """
        features = []

        for data in points_data:
            point = data.get('point')
            if not point:
                continue

            feature = QgsFeature(fields)

            # Устанавливаем геометрию с округлением координат
            # ВАЖНО: snappedToGrid() гарантирует точность 0.01м при сохранении в GPKG
            geom = QgsGeometry.fromPointXY(point)
            geom = geom.snappedToGrid(COORDINATE_PRECISION, COORDINATE_PRECISION)
            feature.setGeometry(geom)

            # Устанавливаем атрибуты
            # Порядок: ID, ID_Точки_контура, ID_Контура, Услов_КН, КН, Тип_контура, Номер_контура, X, Y
            feature.setAttributes([
                data.get('id', 0),
                data.get('contour_point_index', 0),  # ID_Точки_контура
                data.get('contour_id', 0),
                data.get('uslov_kn', ''),  # Услов_КН
                data.get('kn', ''),  # КН
                data.get('contour_type', 'Внешний'),  # Тип_контура
                data.get('contour_number', 1),  # Номер_контура
                data.get('x_geodetic', 0.0),
                data.get('y_geodetic', 0.0),
            ])

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

            # Создаём временный memory layer (MultiPoint)
            mem_layer = QgsVectorLayer(
                f"MultiPoint?crs={crs.authid()}",
                layer_name,
                "memory"
            )

            if not mem_layer.isValid():
                log_error(f"Fsm_3_1_6: Не удалось создать memory layer для {layer_name}")
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
                log_error(f"Fsm_3_1_6: Ошибка записи в GPKG: {error[1]}")
                return False

            return True

        except Exception as e:
            log_error(f"Fsm_3_1_6: Исключение при сохранении в GPKG: {e}")
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
            log_error(f"Fsm_3_1_6: Не удалось загрузить слой из {uri}")
            return None

    def create_point_layer_for_polygon(
        self,
        polygon_layer_name: str,
        crs: QgsCoordinateReferenceSystem,
        points_data: List[Dict[str, Any]]
    ) -> Optional[QgsVectorLayer]:
        """Создание точечного слоя для соответствующего полигонального

        Args:
            polygon_layer_name: Имя полигонального слоя
            crs: Система координат
            points_data: Данные точек

        Returns:
            QgsVectorLayer или None
        """
        point_layer_name = self.get_point_layer_name(polygon_layer_name)

        if not point_layer_name:
            log_warning(f"Fsm_3_1_6: Нет соответствия для полигонального слоя {polygon_layer_name}")
            return None

        return self.create_point_layer(point_layer_name, crs, points_data)
