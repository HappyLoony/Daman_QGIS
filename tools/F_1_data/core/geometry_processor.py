# -*- coding: utf-8 -*-
"""
Процессор геометрии для импорта
Обработка, валидация и преобразование геометрии
"""

from typing import Optional, List, Dict, Any
from qgis.core import (
    QgsGeometry, QgsFeature, QgsVectorLayer, QgsWkbTypes,
    QgsMessageLog, Qgis, QgsCoordinateTransform,
    QgsProject, QgsField, QgsFields, QgsMemoryProviderUtils,
    QgsCoordinateReferenceSystem, QgsPoint
)
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.managers import CoordinatePrecisionManager
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error


class GeometryProcessor:
    """Класс для обработки геометрии при импорте"""
    
    
    @staticmethod
    def fix_geometry(geometry: QgsGeometry) -> Optional[QgsGeometry]:
        """
        Исправление геометрии
        
        Args:
            geometry: Исходная геометрия
            
        Returns:
            Исправленная геометрия или None при ошибке
        """
        if not geometry or geometry.isEmpty():
            return None
        
        # Проверка валидности
        if not geometry.isGeosValid():
            # Пытаемся исправить
            fixed = geometry.makeValid()
            if fixed and fixed.isGeosValid():
                return fixed
            return None
        
        return geometry
    
    @staticmethod
    def convert_lines_to_polygons(layer: QgsVectorLayer, layer_name: str) -> Optional[QgsVectorLayer]:
        """
        Преобразование линий в полигоны с правильной обработкой внутренних контуров
        Код из Tool_2_3_ZprImport

        Args:
            layer: Слой с линиями
            layer_name: Имя результирующего слоя

        Returns:
            Слой с полигонами или None при ошибке
        """
        # Проверяем тип геометрии
        geom_type = layer.wkbType()

        # Если уже полигоны - возвращаем как есть
        if QgsWkbTypes.geometryType(geom_type) == QgsWkbTypes.PolygonGeometry:
            return layer

        # Если не линии - возвращаем None
        if QgsWkbTypes.geometryType(geom_type) != QgsWkbTypes.LineGeometry:
            log_warning(
                f"Слой не содержит линейную геометрию для преобразования"
            )
            return None

        # Шаг 1: Собираем все замкнутые линии и преобразуем их в полигоны
        all_polygons = []

        for feature in layer.getFeatures():
            if not feature.hasGeometry():
                continue

            geom = feature.geometry()
            # МИГРАЦИЯ LINESTRING → MULTILINESTRING: упрощённый паттерн
            lines = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
            for line in lines:
                if len(line) > 2:  # Минимум 3 точки для полигона
                    # Проверяем замкнутость (допуск 0.01м)
                    # FIX (2025-11-19): Используем централизованную проверку is_ring_closed()
                    ring_points = [QgsPoint(pt) for pt in line]
                    if not CoordinatePrecisionManager.is_ring_closed(ring_points):
                        # Замыкаем линию
                        line.append(line[0])

                    # Создаем полигон из замкнутой линии
                    polygon = QgsGeometry.fromPolygonXY([line])
                    if polygon.isGeosValid():
                        all_polygons.append({
                            'geometry': polygon,
                            'attributes': feature.attributes()
                        })

        if not all_polygons:
            log_warning(
                "Не найдено замкнутых линий для преобразования в полигоны"
            )
            return None

        # Шаг 2: Определяем иерархию полигонов (внешние и внутренние контуры)
        processed_polygons = GeometryProcessor.process_inner_rings(all_polygons)

        # Шаг 3: Создаем результирующий слой
        # МИГРАЦИЯ POLYGON → MULTIPOLYGON: временный слой
        crs_string = layer.crs().authid()
        polygon_layer = QgsVectorLayer(
            f"MultiPolygon?crs={crs_string}",
            layer_name,
            "memory"
        )
        polygon_layer.startEditing()

        # Копируем поля из исходного слоя
        for field in layer.fields():
            polygon_layer.addAttribute(field)

        # Добавляем дополнительные атрибуты
        polygon_layer.addAttribute(QgsField("contour_num", QMetaType.Type.Int))
        polygon_layer.addAttribute(QgsField("area_sqm", QMetaType.Type.Int))

        # Добавляем полигоны в слой
        contour_id = 1
        for poly_data in processed_polygons:
            feature = QgsFeature(polygon_layer.fields())
            feature.setGeometry(poly_data['geometry'])

            # Копируем атрибуты
            attrs = list(poly_data['attributes'])
            attrs.append(contour_id)  # contour_num
            attrs.append(int(round(poly_data['geometry'].area())))  # area_sqm
            feature.setAttributes(attrs)

            polygon_layer.addFeature(feature)
            contour_id += 1

        polygon_layer.commitChanges()

        log_info(
            f"Преобразовано {len(processed_polygons)} полигонов с учетом внутренних контуров"
        )

        return polygon_layer
    
    @staticmethod
    def process_inner_rings(all_polygons: List[Dict]) -> List[Dict]:
        """
        Обработка внутренних контуров (дырок) в полигонах
        
        Args:
            all_polygons: Список полигонов с атрибутами
            
        Returns:
            Список полигонов с обработанными дырками
        """
        # Сортируем полигоны по площади (от большего к меньшему)
        all_polygons.sort(key=lambda x: x['geometry'].area(), reverse=True)
        
        # Список для финальных полигонов
        final_polygons = []
        used_indices = set()
        
        for i, outer_poly_data in enumerate(all_polygons):
            if i in used_indices:
                continue
            
            outer_poly = outer_poly_data['geometry']
            holes = []
            
            # Ищем полигоны, которые полностью содержатся в текущем
            for j, inner_poly_data in enumerate(all_polygons):
                if i == j or j in used_indices:
                    continue
                
                inner_poly = inner_poly_data['geometry']
                
                # Проверяем, содержится ли внутренний полигон в внешнем
                if outer_poly.contains(inner_poly):
                    # Проверяем, что этот полигон не содержится в другом внутреннем полигоне
                    is_nested = False
                    for k, check_poly_data in enumerate(all_polygons):
                        if k == i or k == j or k in used_indices:
                            continue
                        check_poly = check_poly_data['geometry']
                        if outer_poly.contains(check_poly) and check_poly.contains(inner_poly):
                            is_nested = True
                            break
                    
                    if not is_nested:
                        # Это дырка в текущем полигоне
                        holes.append(inner_poly)
                        used_indices.add(j)
            
            # Создаем полигон с дырками если они есть
            if holes:
                # Вычитаем все дырки из внешнего полигона
                result_poly = outer_poly
                for hole in holes:
                    result_poly = result_poly.difference(hole)
                
                if result_poly.isGeosValid() and not result_poly.isEmpty():
                    final_polygons.append({
                        'geometry': result_poly,
                        'attributes': outer_poly_data['attributes']
                    })
                    used_indices.add(i)
            else:
                # Полигон без дырок
                final_polygons.append(outer_poly_data)
                used_indices.add(i)
        
        return final_polygons
    
    @staticmethod
    def transform_geometry(geometry: QgsGeometry, 
                         source_crs: QgsCoordinateReferenceSystem,
                         target_crs: QgsCoordinateReferenceSystem) -> QgsGeometry:
        """
        Трансформация геометрии между СК
        
        Args:
            geometry: Исходная геометрия
            source_crs: Исходная СК
            target_crs: Целевая СК
            
        Returns:
            Трансформированная геометрия
        """
        if source_crs == target_crs:
            return geometry
        
        transform = QgsCoordinateTransform(
            source_crs,
            target_crs,
            QgsProject.instance()
        )
        
        geom_copy = QgsGeometry(geometry)
        geom_copy.transform(transform)
        return geom_copy
    
    @staticmethod
    def filter_by_geometry_type(layer: QgsVectorLayer, 
                              geom_type: QgsWkbTypes.GeometryType) -> List[QgsFeature]:
        """
        Фильтрация объектов по типу геометрии
        
        Args:
            layer: Исходный слой
            geom_type: Тип геометрии для фильтрации
            
        Returns:
            Список отфильтрованных объектов
        """
        filtered_features = []
        
        for feature in layer.getFeatures():
            if not feature.hasGeometry():
                continue
            
            feat_geom = feature.geometry()
            if QgsWkbTypes.geometryType(feat_geom.wkbType()) == geom_type:
                filtered_features.append(feature)
        
        return filtered_features
    
    @staticmethod
    def calculate_geometry_metrics(layer: QgsVectorLayer) -> Dict[str, Any]:
        """
        Вычисление метрик геометрии слоя
        
        Args:
            layer: Слой для анализа
            
        Returns:
            Словарь с метриками
        """
        metrics = {
            'feature_count': layer.featureCount(),
            'geometry_type': QgsWkbTypes.displayString(layer.wkbType()),
            'total_area': 0,
            'total_length': 0,
            'invalid_geometries': 0,
            'empty_geometries': 0
        }
        
        for feature in layer.getFeatures():
            if not feature.hasGeometry():
                metrics['empty_geometries'] += 1
                continue
            
            geom = feature.geometry()
            
            if not geom.isGeosValid():
                metrics['invalid_geometries'] += 1
            
            # Вычисляем площадь/длину в зависимости от типа
            geom_type = QgsWkbTypes.geometryType(geom.wkbType())
            if geom_type == QgsWkbTypes.PolygonGeometry:
                metrics['total_area'] += geom.area()
            elif geom_type == QgsWkbTypes.LineGeometry:
                metrics['total_length'] += geom.length()
        
        return metrics
