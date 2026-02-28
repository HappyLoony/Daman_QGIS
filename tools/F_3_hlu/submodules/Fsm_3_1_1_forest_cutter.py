# -*- coding: utf-8 -*-
"""
Fsm_3_1_1_ForestCutter - Движок нарезки ЗПР по лесным выделам

Выполняет:
- Поиск пересечений Le_2_* с Le_3_1_1_1_Лес_Ред_Выделы
- Нарезку по границам выделов (intersection)
- Фильтрацию микрополигонов
- Подготовку данных для создания слоёв Le_3_2_* (стандартные) и Le_3_3_* (РЕК)
"""

import time
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsCoordinateReferenceSystem,
    QgsSpatialIndex,
    QgsFields,
    QgsVectorFileWriter,
    QgsWkbTypes,
    QgsProject,
)

from Daman_QGIS.utils import log_info, log_warning, log_error
from .Fsm_3_1_2_attribute_mapper import Fsm_3_1_2_AttributeMapper

# Минимальная площадь полигона (м²) - фильтрация артефактов
MIN_POLYGON_AREA = 0.10


class Fsm_3_1_1_ForestCutter:
    """Движок нарезки ЗПР по лесным выделам"""

    def __init__(self, gpkg_path: str) -> None:
        """Инициализация движка

        Args:
            gpkg_path: Путь к GeoPackage проекта
        """
        self.gpkg_path = gpkg_path
        self.attribute_mapper = Fsm_3_1_2_AttributeMapper()

        # Кэш пространственного индекса лесных выделов
        self._forest_index: Optional[QgsSpatialIndex] = None
        self._forest_features: Dict[int, QgsFeature] = {}

        # Статистика
        self.statistics: Dict[str, Any] = {}

    def _reset_statistics(self) -> None:
        """Сброс статистики"""
        self.statistics = {
            'input_features': 0,
            'output_features': 0,
            'skipped_no_intersection': 0,
            'filtered_small': 0,
            'processing_time': 0.0,
        }

    def build_forest_index(self, forest_layer: QgsVectorLayer) -> bool:
        """Построение пространственного индекса для слоя лесных выделов

        Args:
            forest_layer: Слой L_4_1_1_Лес_Ред_Выделы

        Returns:
            bool: Успех построения
        """
        try:
            self._forest_index = QgsSpatialIndex()
            self._forest_features = {}

            for feature in forest_layer.getFeatures():
                geom = feature.geometry()
                if geom and not geom.isEmpty():
                    self._forest_index.addFeature(feature)
                    self._forest_features[feature.id()] = QgsFeature(feature)

            log_info(f"Fsm_3_1_1: Построен индекс лесных выделов "
                    f"({len(self._forest_features)} объектов)")
            return True

        except Exception as e:
            log_error(f"Fsm_3_1_1: Ошибка построения индекса: {e}")
            return False

    def _find_intersecting_vydels(self, geometry: QgsGeometry) -> List[QgsFeature]:
        """Поиск выделов, пересекающих геометрию

        Args:
            geometry: Геометрия для поиска

        Returns:
            List[QgsFeature]: Список пересекающихся выделов
        """
        if self._forest_index is None:
            return []

        result = []
        bbox = geometry.boundingBox()

        # Быстрый поиск по bbox
        candidate_ids = self._forest_index.intersects(bbox)

        for fid in candidate_ids:
            feature = self._forest_features.get(fid)
            if feature is None:
                continue

            feature_geom = feature.geometry()
            if feature_geom.isEmpty():
                continue

            # Точная проверка пересечения
            if geometry.intersects(feature_geom):
                result.append(feature)

        return result

    def _validate_and_fix_geometry(self, geometry: QgsGeometry) -> QgsGeometry:
        """Валидация и исправление геометрии

        Args:
            geometry: Исходная геометрия

        Returns:
            QgsGeometry: Исправленная геометрия
        """
        if geometry.isEmpty():
            return geometry

        if not geometry.isGeosValid():
            geometry = geometry.makeValid()

        return geometry

    def _extract_polygons(self, geometry: QgsGeometry) -> List[QgsGeometry]:
        """Извлечение отдельных полигонов из геометрии

        Args:
            geometry: Геометрия (может быть Multi*)

        Returns:
            List[QgsGeometry]: Список полигонов
        """
        result = []

        if geometry.isEmpty():
            return result

        geom_type = geometry.type()
        if geom_type != QgsWkbTypes.GeometryType.PolygonGeometry:
            return result

        if geometry.isMultipart():
            for part in geometry.asGeometryCollection():
                if not part.isEmpty() and part.type() == QgsWkbTypes.GeometryType.PolygonGeometry:
                    result.append(part)
        else:
            result.append(geometry)

        return result

    def process_layer(
        self,
        le3_layer: QgsVectorLayer,
        forest_layer: QgsVectorLayer,
        output_layer_name: str,
        crs: QgsCoordinateReferenceSystem
    ) -> Optional[QgsVectorLayer]:
        """Обработка одного слоя Le_2_*

        Args:
            le3_layer: Входной слой Le_2_*
            forest_layer: Слой лесных выделов
            output_layer_name: Имя выходного слоя Le_3_*
            crs: Система координат

        Returns:
            QgsVectorLayer: Созданный слой или None
        """
        start_time = time.time()
        self._reset_statistics()
        self.attribute_mapper.reset_id_counter(output_layer_name)

        log_info(f"Fsm_3_1_1: Обработка {le3_layer.name()} -> {output_layer_name}")

        # Построение индекса если ещё не построен
        if self._forest_index is None:
            if not self.build_forest_index(forest_layer):
                return None

        self.statistics['input_features'] = le3_layer.featureCount()

        # Собираем данные для создания слоя
        output_data: List[Dict[str, Any]] = []

        for le3_feature in le3_layer.getFeatures():
            le3_geom = le3_feature.geometry()

            if not le3_geom or le3_geom.isEmpty():
                continue

            le3_geom = self._validate_and_fix_geometry(le3_geom)
            if le3_geom.isEmpty():
                continue

            # Находим пересекающиеся выделы
            intersecting_vydels = self._find_intersecting_vydels(le3_geom)

            if not intersecting_vydels:
                self.statistics['skipped_no_intersection'] += 1
                continue

            # Маппинг атрибутов из Le_2_*
            le3_attrs = self.attribute_mapper.map_le3_attributes(le3_feature)

            # Обработка каждого пересечения
            for vydel_feature in intersecting_vydels:
                vydel_geom = vydel_feature.geometry()

                if vydel_geom.isEmpty():
                    continue

                vydel_geom = self._validate_and_fix_geometry(vydel_geom)

                # Вычисляем пересечение
                intersection = le3_geom.intersection(vydel_geom)

                if intersection.isEmpty():
                    continue

                # Извлекаем отдельные полигоны
                for poly_geom in self._extract_polygons(intersection):
                    if poly_geom.isEmpty():
                        continue

                    # Фильтрация микрополигонов
                    area = poly_geom.area()
                    if area < MIN_POLYGON_AREA:
                        self.statistics['filtered_small'] += 1
                        continue

                    # Маппинг лесных атрибутов
                    forest_attrs = self.attribute_mapper.map_forest_attributes(vydel_feature)

                    # Объединение атрибутов
                    merged_attrs = self.attribute_mapper.merge_attributes(
                        le3_attrs, forest_attrs, poly_geom, output_layer_name
                    )

                    output_data.append({
                        'geometry': poly_geom,
                        'attributes': merged_attrs
                    })

        self.statistics['output_features'] = len(output_data)
        self.statistics['processing_time'] = time.time() - start_time

        log_info(f"Fsm_3_1_1: {le3_layer.name()}: "
                f"вход={self.statistics['input_features']}, "
                f"выход={self.statistics['output_features']}, "
                f"пропущено={self.statistics['skipped_no_intersection']}, "
                f"отфильтровано={self.statistics['filtered_small']}")

        # Если нет данных - не создаём слой
        if not output_data:
            log_info(f"Fsm_3_1_1: Нет данных для {output_layer_name}, слой не создаётся")
            return None

        # Создаём слой
        result_layer = self._create_layer(output_layer_name, crs, output_data)

        return result_layer

    def _create_layer(
        self,
        layer_name: str,
        crs: QgsCoordinateReferenceSystem,
        data: List[Dict[str, Any]]
    ) -> Optional[QgsVectorLayer]:
        """Создание слоя в GeoPackage

        Args:
            layer_name: Имя слоя
            crs: Система координат
            data: Данные (geometry + attributes)

        Returns:
            QgsVectorLayer: Созданный слой или None
        """
        try:
            fields = self.attribute_mapper.get_fields()

            # Опции для GPKG
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = layer_name
            options.fileEncoding = "UTF-8"

            # Проверяем существует ли GPKG
            gpkg_exists = Path(self.gpkg_path).exists()

            if gpkg_exists:
                options.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
            else:
                options.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile

            # Создаём writer
            writer = QgsVectorFileWriter.create(
                self.gpkg_path,
                fields,
                QgsWkbTypes.Type.Polygon,
                crs,
                QgsProject.instance().transformContext(),
                options
            )

            if writer.hasError() != QgsVectorFileWriter.WriterError.NoError:
                log_error(f"Fsm_3_1_1: Ошибка создания слоя {layer_name}: {writer.errorMessage()}")
                del writer
                return None

            # Записываем объекты
            for item in data:
                feature = QgsFeature(fields)
                feature.setGeometry(item['geometry'])
                feature.setAttributes(
                    self.attribute_mapper.attributes_to_list(item['attributes'])
                )
                writer.addFeature(feature)

            del writer

            # Загружаем созданный слой
            uri = f"{self.gpkg_path}|layername={layer_name}"
            result_layer = QgsVectorLayer(uri, layer_name, "ogr")

            if not result_layer.isValid():
                log_error(f"Fsm_3_1_1: Слой {layer_name} невалиден после создания")
                return None

            log_info(f"Fsm_3_1_1: Создан слой {layer_name} ({result_layer.featureCount()} объектов)")
            return result_layer

        except Exception as e:
            log_error(f"Fsm_3_1_1: Ошибка создания слоя {layer_name}: {e}")
            return None

    def get_statistics(self) -> Dict[str, Any]:
        """Получить статистику последней обработки

        Returns:
            Dict: Статистика
        """
        return self.statistics.copy()

    def clear_cache(self) -> None:
        """Очистка кэша пространственного индекса"""
        self._forest_index = None
        self._forest_features.clear()
