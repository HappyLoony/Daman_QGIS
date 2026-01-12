# -*- coding: utf-8 -*-
"""
Модуль построения полигонов с внутренними контурами (дырками).
Автоматически определяет внешние и внутренние контуры по площади и вложенности.
"""

from typing import List, Dict, Any, Tuple, Optional
from qgis.core import (
    QgsGeometry, QgsFeature, QgsVectorLayer,
    QgsField, QgsFields, QgsSpatialIndex,
    QgsWkbTypes, QgsPoint, QgsPointXY,
    QgsCoordinateReferenceSystem, QgsProject
)
from qgis.PyQt.QtCore import QMetaType
from Daman_QGIS.constants import MIN_POLYGON_AREA
from Daman_QGIS.managers.M_6_coordinate_precision import CoordinatePrecisionManager
from Daman_QGIS.utils import log_info, log_warning, log_error


# Threshold для использования spatial index (best practice)
SPATIAL_INDEX_THRESHOLD = 50


class PolygonBuilder:
    """
    Построитель полигонов с внутренними контурами из замкнутых полилиний.
    
    Алгоритм:
    1. Конвертация полилиний в полигоны
    2. Определение внешних контуров по максимальной площади
    3. Группировка внутренних контуров по принадлежности
    4. Создание полигонов с дырками
    """
    
    def __init__(self) -> None:
        """Инициализация построителя"""
        self.statistics = {
            'total_polylines': 0,
            'closed_polylines': 0,
            'polygons_created': 0,
            'holes_created': 0,
            'invalid_geometries': 0,
            'processing_time': 0.0
        }
    
    def build_polygons_with_holes(self,
                                 polylines: List[QgsGeometry],
                                 min_area: float = MIN_POLYGON_AREA,
                                 validate: bool = True,
                                 progress_callback: Optional[Any] = None,
                                 remove_largest_outer: bool = False) -> List[QgsGeometry]:
        """
        Построение полигонов с внутренними контурами из полилиний.

        Args:
            polylines: Список геометрий полилиний
            min_area: Минимальная площадь для обработки (игнорировать меньшие)
            validate: Выполнять ли валидацию результата
            progress_callback: Функция для отображения прогресса (0-100)
            remove_largest_outer: Удалить ли самый большой внешний контур (для границ работ)

        Returns:
            Список полигонов с внутренними контурами
        """
        import time
        start_time = time.time()

        # Сброс статистики
        self.statistics = {
            'total_polylines': len(polylines),
            'closed_polylines': 0,
            'polygons_created': 0,
            'holes_created': 0,
            'invalid_geometries': 0,
            'processing_time': 0.0
        }

        if progress_callback:
            progress_callback(int(0))

        # Шаг 1: Конвертация полилиний в полигоны
        polygon_candidates = self._convert_polylines_to_polygons(
            polylines, min_area
        )

        if not polygon_candidates:
            log_warning("Fsm_1_1_2: нет подходящих полилиний для создания полигонов")
            return []

        if progress_callback:
            progress_callback(int(30))

        # Шаг 2: Сортировка по площади (убывание)
        polygon_candidates.sort(key=lambda x: x['area'], reverse=True)

        # Шаг 3: Группировка по вложенности
        grouped = self._group_by_containment(polygon_candidates)

        # Шаг 3.5: Удаление самого большого внешнего контура если требуется
        if remove_largest_outer and grouped:
            # Находим группу с самой большой площадью внешнего контура
            largest_idx = max(range(len(grouped)), key=lambda i: grouped[i]['exterior']['area'])
            largest_group = grouped[largest_idx]

            # Проверяем что этот контур действительно содержит все остальные
            largest_geom = largest_group['exterior']['geometry']
            contains_all = True

            for i, other_group in enumerate(grouped):
                if i == largest_idx:
                    continue
                other_geom = other_group['exterior']['geometry']
                if not largest_geom.contains(other_geom):
                    contains_all = False
                    break

            # Если самый большой содержит все остальные - преобразуем его holes в отдельные полигоны
            if contains_all and largest_group['holes']:
                log_info(f"Fsm_1_1_2: удаление самого большого внешнего контура (площадь {largest_group['exterior']['area']:.2f} м²)")
                # Удаляем самый большой контур из списка
                grouped.pop(largest_idx)
                # Преобразуем его holes в отдельные группы (они станут новыми внешними контурами)
                for hole in largest_group['holes']:
                    # Проверяем валидность geometry hole перед добавлением
                    hole_geom = hole.get('geometry')
                    if hole_geom and hole_geom.isGeosValid():
                        grouped.append({
                            'exterior': hole,
                            'holes': []  # У них не будет своих holes
                        })
                    else:
                        log_warning(f"Fsm_1_1_2: пропуск невалидного hole при преобразовании в внешний контур")
                log_info(f"Fsm_1_1_2: создано {len([g for g in grouped if g['exterior'] in largest_group['holes']])} новых внешних контуров из holes")

        if progress_callback:
            progress_callback(int(60))

        # Шаг 4: Создание полигонов с дырками
        result_polygons = []

        for group in grouped:
            polygon = self._create_polygon_with_rings(
                group['exterior'],
                group['holes']
            )

            if polygon:
                # Валидация если требуется
                if validate:
                    if not polygon.isGeosValid():
                        self.statistics['invalid_geometries'] += 1
                        # Пытаемся исправить
                        polygon = polygon.makeValid()
                        # Проверяем что исправление сработало
                        if not polygon or polygon.isEmpty() or not polygon.isGeosValid():
                            log_warning(f"Fsm_1_1_2: Не удалось исправить невалидный полигон, пропускаем")
                            continue

                result_polygons.append(polygon)
                self.statistics['polygons_created'] += 1
                self.statistics['holes_created'] += len(group['holes'])

        if progress_callback:
            progress_callback(int(90))

        # Финальная валидация
        if validate:
            result_polygons = self._validate_results(result_polygons)

        self.statistics['processing_time'] = float(time.time() - start_time)

        # Логируем только итог (без промежуточных сообщений для каждого блока)

        if progress_callback:
            progress_callback(int(100))

        return result_polygons
    
    def _convert_polylines_to_polygons(self,
                                      polylines: List[QgsGeometry],
                                      min_area: float) -> List[Dict[str, Any]]:
        """
        Конвертация полилиний в полигоны.
        
        Args:
            polylines: Список полилиний
            min_area: Минимальная площадь
            
        Returns:
            Список словарей с информацией о полигонах
        """
        polygon_candidates = []
        
        for i, geom in enumerate(polylines):
            if not geom:
                continue
            
            # Обработка в зависимости от типа
            if geom.type() == QgsWkbTypes.LineGeometry:
                # Это линия - конвертируем
                # МИГРАЦИЯ LINESTRING → MULTILINESTRING: упрощённый паттерн
                lines = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
                if lines and lines[0]:
                    line = lines[0]  # Берем первую часть
                else:
                    continue
                
                if not line or len(line) < 3:
                    continue

                # Проверяем замкнутость (с tolerance 0.01м)
                # FIX (2025-11-19): Используем is_ring_closed() вместо прямого сравнения ==
                # (исправляет баг с округлением координат - координаты 2474567.89 vs 2474567.90 теперь считаются замкнутыми)
                ring_points = [QgsPoint(pt) for pt in line]
                is_closed = CoordinatePrecisionManager.is_ring_closed(ring_points)
                if is_closed:
                    self.statistics['closed_polylines'] += 1
                    
                    # Создаем полигон
                    poly_geom = QgsGeometry.fromPolygonXY([line])
                    area = poly_geom.area()
                    
                    if area >= min_area:
                        polygon_candidates.append({
                            'geometry': poly_geom,
                            'area': area,
                            'vertices': line,
                            'index': i,
                            'used': False
                        })
                        
            elif geom.type() == QgsWkbTypes.PolygonGeometry:
                # Уже полигон - используем как есть
                area = geom.area()
                if area >= min_area:
                    # МИГРАЦИЯ POLYGON → MULTIPOLYGON: упрощённый паттерн
                    polygons = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]

                    for poly in polygons:
                        if poly:
                            poly_geom = QgsGeometry.fromPolygonXY([poly[0]])
                            polygon_candidates.append({
                                'geometry': poly_geom,
                                'area': poly_geom.area(),
                                'vertices': poly[0],
                                'index': i,
                                'used': False
                            })
        
        return polygon_candidates
    
    def _group_by_containment(self, polygons: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Группировка полигонов по вложенности.

        Использует spatial index для оптимизации при большом количестве полигонов
        (> SPATIAL_INDEX_THRESHOLD). Алгоритм Bajaj-Dey для определения parent-child.

        Args:
            polygons: Список полигонов (отсортирован по убыванию площади)

        Returns:
            Список групп {exterior, holes}
        """
        groups = []
        use_spatial_index = len(polygons) > SPATIAL_INDEX_THRESHOLD
        spatial_index = None

        # Создаем пространственный индекс для оптимизации (best practice)
        if use_spatial_index:
            spatial_index = QgsSpatialIndex()
            for i, poly in enumerate(polygons):
                feature = QgsFeature(i)
                feature.setGeometry(poly['geometry'])
                spatial_index.addFeature(feature)

        # Обрабатываем каждый полигон как потенциальный внешний контур
        for i, exterior in enumerate(polygons):
            if exterior['used']:
                continue

            holes = []
            exterior_geom = exterior['geometry']
            exterior_bbox = exterior_geom.boundingBox()

            # Определяем кандидатов для проверки
            if use_spatial_index and spatial_index:
                # Используем spatial index для фильтрации по bounding box
                candidate_ids = spatial_index.intersects(exterior_bbox)
            else:
                # Проверяем все полигоны
                candidate_ids = range(len(polygons))

            # Ищем все полигоны внутри текущего
            for j in candidate_ids:
                if i == j:
                    continue
                hole = polygons[j]
                if hole['used']:
                    continue

                # Проверяем вложенность (contains - точная проверка после bbox фильтрации)
                if exterior_geom.contains(hole['geometry']):
                    # Проверяем что это не вложено в другой внутренний контур
                    # (полигон внутри дырки = новый внешний контур, не hole)
                    is_nested_in_hole = False
                    for existing_hole in holes:
                        if polygons[existing_hole]['geometry'].contains(hole['geometry']):
                            is_nested_in_hole = True
                            break

                    if not is_nested_in_hole:
                        holes.append(j)
                        hole['used'] = True

            # Добавляем группу
            groups.append({
                'exterior': exterior,
                'holes': [polygons[h] for h in holes]
            })
            exterior['used'] = True

        return groups
    
    def _normalize_ring_orientation(self, ring: List[QgsPointXY], should_be_ccw: bool) -> List[QgsPointXY]:
        """
        Нормализация ориентации кольца (CCW для exterior, CW для holes).

        Best practice из Shapely: exterior CCW (sign=1.0), interior CW.
        Это стандарт OGC Simple Features и обеспечивает корректную работу
        с различными GIS инструментами.

        Args:
            ring: Список точек кольца
            should_be_ccw: True для exterior (CCW), False для holes (CW)

        Returns:
            Кольцо с правильной ориентацией
        """
        if len(ring) < 3:
            return ring

        # Вычисляем signed area (формула Shoelace)
        # Положительная = CCW, отрицательная = CW
        signed_area = 0.0
        n = len(ring)
        for i in range(n):
            j = (i + 1) % n
            signed_area += ring[i].x() * ring[j].y()
            signed_area -= ring[j].x() * ring[i].y()

        is_ccw = signed_area > 0

        # Инвертируем если ориентация неправильная
        if is_ccw != should_be_ccw:
            return list(reversed(ring))

        return ring

    def _create_polygon_with_rings(self,
                                  exterior: Dict[str, Any],
                                  holes: List[Dict[str, Any]]) -> Optional[QgsGeometry]:
        """
        Создание полигона с внутренними контурами.

        Применяет нормализацию ориентации колец:
        - Exterior: CCW (counter-clockwise)
        - Holes: CW (clockwise)

        Args:
            exterior: Внешний контур
            holes: Список внутренних контуров

        Returns:
            Полигон с дырками или None при ошибке
        """
        # Нормализуем exterior (CCW)
        exterior_ring = self._normalize_ring_orientation(
            exterior['vertices'],
            should_be_ccw=True
        )
        rings = [exterior_ring]

        # Нормализуем и добавляем holes (CW)
        for hole in holes:
            hole_ring = self._normalize_ring_orientation(
                hole['vertices'],
                should_be_ccw=False  # Holes должны быть CW
            )
            rings.append(hole_ring)

        # Создаем геометрию
        polygon = QgsGeometry.fromPolygonXY(rings)

        # Проверка корректности
        if not polygon or polygon.isEmpty():
            log_warning("Fsm_1_1_2: не удалось создать полигон с дырками")
            return None

        return polygon
    
    def _validate_results(self, polygons: List[QgsGeometry]) -> List[QgsGeometry]:
        """
        Валидация результирующих полигонов.
        
        Args:
            polygons: Список полигонов
            
        Returns:
            Список валидных полигонов
        """
        valid_polygons = []
        
        for polygon in polygons:
            if not polygon:
                continue
            
            # Проверка валидности
            if not polygon.isGeosValid():
                # Пытаемся исправить
                fixed = polygon.makeValid()
                if fixed and fixed.isGeosValid():
                    valid_polygons.append(fixed)
                    log_info("Fsm_1_1_2: геометрия исправлена")
                else:
                    self.statistics['invalid_geometries'] += 1
            else:
                valid_polygons.append(polygon)

            # Детальная проверка топологии
            errors = polygon.validateGeometry()
            if errors:
                for error in errors:
                    log_warning(f"Fsm_1_1_2: топологическая ошибка: {error.what()}")
        
        return valid_polygons
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Получение статистики последней обработки.
        
        Returns:
            Словарь со статистикой
        """
        return self.statistics.copy()
    
    def create_layer_from_polygons(self,
                                  polygons: List[QgsGeometry],
                                  layer_name: str = "Полигоны с внутренними контурами",
                                  crs: Optional[QgsCoordinateReferenceSystem] = None,
                                  as_single_multipolygon: bool = False) -> QgsVectorLayer:
        """
        Создание векторного слоя из полигонов.

        Args:
            polygons: Список полигонов
            layer_name: Имя слоя
            crs: Система координат (если None, используется из проекта)
            as_single_multipolygon: Если True - объединить все в один MultiPolygon feature
                                    (для границ работ L_1_1_1).
                                    Если False - каждый полигон = отдельный feature
                                    (для ЗПР, ОКС и других слоёв).

        Returns:
            Векторный слой с полигонами
        """
        # Определяем CRS
        if not crs:
            crs = QgsProject.instance().crs()

        # Если CRS все еще None, используем WGS84 по умолчанию
        if not crs:
            crs = QgsCoordinateReferenceSystem("EPSG:4326")

        crs_authid = crs.authid() if crs else "EPSG:4326"

        if as_single_multipolygon:
            # === РЕЖИМ: Один MultiPolygon (для границ работ) ===
            return self._create_single_multipolygon_layer(polygons, layer_name, crs_authid)
        else:
            # === РЕЖИМ: Отдельные features (для ЗПР, ОКС и т.д.) ===
            return self._create_separate_features_layer(polygons, layer_name, crs_authid)

    def _create_single_multipolygon_layer(self,
                                          polygons: List[QgsGeometry],
                                          layer_name: str,
                                          crs_authid: str) -> QgsVectorLayer:
        """
        Создание слоя с одним MultiPolygon (для границ работ).

        Все полигоны объединяются в один feature с MultiPolygon геометрией.
        Это нужно для слоёв границ работ (L_1_1_1), которые могут иметь разный формат.
        """
        layer = QgsVectorLayer(
            f"MultiPolygon?crs={crs_authid}",
            layer_name,
            "memory"
        )

        # Добавляем атрибуты
        provider = layer.dataProvider()
        fields = QgsFields()
        fields.append(QgsField("id", QMetaType.Type.Int))
        fields.append(QgsField("area", QMetaType.Type.Int))
        fields.append(QgsField("polygons_count", QMetaType.Type.Int))
        fields.append(QgsField("total_holes", QMetaType.Type.Int))
        provider.addAttributes(fields)
        layer.updateFields()

        # Собираем все части для MultiPolygon
        multi_parts = []
        total_holes = 0

        for polygon in polygons:
            if not polygon or polygon.isEmpty():
                continue

            # МИГРАЦИЯ POLYGON → MULTIPOLYGON: упрощённый паттерн
            multi_poly = polygon.asMultiPolygon() if polygon.isMultipart() else [polygon.asPolygon()]

            for part in multi_poly:
                if part:
                    multi_parts.append(part)
                    if len(part) > 1:
                        total_holes += len(part) - 1

        # Создаем MultiPolygon геометрию
        multi_polygon_geom = QgsGeometry.fromMultiPolygonXY(multi_parts)

        # Валидация и исправление геометрии
        if not multi_polygon_geom.isGeosValid():
            log_warning("Fsm_1_1_2: MultiPolygon невалиден, исправление геометрии...")
            multi_polygon_geom = multi_polygon_geom.makeValid()
            if not multi_polygon_geom.isGeosValid():
                log_error("Fsm_1_1_2: Не удалось исправить геометрию MultiPolygon")

        # Создаем ОДИН feature с MultiPolygon
        feature = QgsFeature()
        feature.setGeometry(multi_polygon_geom)
        feature.setAttributes([
            1,
            int(round(multi_polygon_geom.area())),
            len(multi_parts),
            total_holes
        ])

        layer.startEditing()
        layer.addFeature(feature)
        layer.commitChanges()
        layer.updateExtents()

        log_info(f"Fsm_1_1_2: создан MultiPolygon с {len(multi_parts)} частями и {total_holes} внутренними контурами")

        return layer

    def _create_separate_features_layer(self,
                                        polygons: List[QgsGeometry],
                                        layer_name: str,
                                        crs_authid: str) -> QgsVectorLayer:
        """
        Создание слоя с отдельными features (для ЗПР, ОКС и других слоёв).

        Каждый полигон создаётся как отдельный feature (объект).
        UNIFIED PATTERN: Слой всегда MultiPolygon для совместимости с остальным кодом.
        """
        layer = QgsVectorLayer(
            f"MultiPolygon?crs={crs_authid}",
            layer_name,
            "memory"
        )

        # Добавляем атрибуты
        provider = layer.dataProvider()
        fields = QgsFields()
        fields.append(QgsField("id", QMetaType.Type.Int))
        fields.append(QgsField("area", QMetaType.Type.Int))
        fields.append(QgsField("holes_count", QMetaType.Type.Int))
        provider.addAttributes(fields)
        layer.updateFields()

        # Создаём отдельный feature для каждого полигона
        features_to_add = []
        total_holes = 0

        for idx, polygon in enumerate(polygons, start=1):
            if not polygon or polygon.isEmpty():
                continue

            # Валидация и исправление геометрии
            if not polygon.isGeosValid():
                polygon = polygon.makeValid()
                if not polygon or polygon.isEmpty() or not polygon.isGeosValid():
                    log_warning(f"Fsm_1_1_2: Полигон #{idx} невалиден, пропускаем")
                    continue

            # Считаем количество внутренних контуров (дырок)
            holes_count = 0
            if polygon.isMultipart():
                multi_poly = polygon.asMultiPolygon()
                for part in multi_poly:
                    if part and len(part) > 1:
                        holes_count += len(part) - 1
            else:
                poly = polygon.asPolygon()
                if poly and len(poly) > 1:
                    holes_count = len(poly) - 1

            total_holes += holes_count

            # UNIFIED PATTERN: Конвертируем в MultiPolygon если нужно
            if not polygon.isMultipart():
                # Конвертируем Polygon → MultiPolygon
                poly_data = polygon.asPolygon()
                if poly_data:
                    polygon = QgsGeometry.fromMultiPolygonXY([poly_data])

            # Создаём feature
            feature = QgsFeature()
            feature.setGeometry(polygon)
            feature.setAttributes([
                idx,
                int(round(polygon.area())),
                holes_count
            ])
            features_to_add.append(feature)

        # Добавляем все features в слой
        layer.startEditing()
        layer.addFeatures(features_to_add)
        layer.commitChanges()
        layer.updateExtents()

        log_info(f"Fsm_1_1_2: создано {len(features_to_add)} полигонов с {total_holes} внутренними контурами")

        return layer
    
    @staticmethod
    def process_layer(layer: QgsVectorLayer,
                     create_new_layer: bool = True,
                     min_area: float = MIN_POLYGON_AREA) -> Optional[QgsVectorLayer]:
        """
        Обработка целого слоя с полилиниями.
        
        Args:
            layer: Исходный слой с полилиниями
            create_new_layer: Создавать ли новый слой или изменить существующий
            min_area: Минимальная площадь
            
        Returns:
            Новый слой с полигонами или None
        """
        # Собираем геометрии
        polylines = []
        for feature in layer.getFeatures():
            geom = feature.geometry()
            if geom:
                polylines.append(geom)

        if not polylines:
            log_warning("Fsm_1_1_2: нет геометрий в слое")
            return None

        # Создаем построитель и обрабатываем
        builder = PolygonBuilder()
        polygons = builder.build_polygons_with_holes(
            polylines,
            min_area=min_area,
            validate=True
        )

        if not polygons:
            return None

        # Создаем новый слой
        if create_new_layer:
            new_layer = builder.create_layer_from_polygons(
                polygons,
                f"{layer.name()}_полигоны",
                layer.crs()
            )
            return new_layer
        else:
            # Изменяем существующий (не рекомендуется)
            log_warning("Fsm_1_1_2: изменение существующего слоя не реализовано")
            return None
