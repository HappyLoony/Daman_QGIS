# -*- coding: utf-8 -*-
"""
Модуль проверки топологии между разными слоями (cross-layer)
Проверяет наложения полигонов из разных слоев

Основан на алгоритмах из плагина KAT Overlap (GPLv3)
Адаптирован для Daman_QGIS
"""

from typing import List, Dict, Any, Tuple
from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsWkbTypes, QgsSpatialIndex
)
from Daman_QGIS.utils import log_info, log_warning
from Daman_QGIS.constants import COORDINATE_PRECISION


class Fsm_0_4_11_CrossLayerChecker:
    """
    Проверка топологии между разными слоями

    Типы проверок:
    - cross_layer_overlap: наложение полигонов из разных слоев
    """

    # Минимальная площадь наложения для регистрации ошибки (м2)
    MIN_OVERLAP_AREA = COORDINATE_PRECISION  # 0.01 м2

    def __init__(self):
        self.overlaps_found = 0

    def check_overlaps(self, layers: List[QgsVectorLayer]) -> List[Dict[str, Any]]:
        """
        Проверка наложений между всеми парами слоев

        Args:
            layers: Список полигональных слоев для проверки

        Returns:
            Список наложений между слоями
        """
        if len(layers) < 2:
            log_info("Fsm_0_4_11: Нужно минимум 2 слоя для cross-layer проверки")
            return []

        # Фильтруем только полигональные слои
        polygon_layers = [
            layer for layer in layers
            if layer.geometryType() == QgsWkbTypes.PolygonGeometry
        ]

        if len(polygon_layers) < 2:
            log_info("Fsm_0_4_11: Нужно минимум 2 полигональных слоя")
            return []

        log_info(f"Fsm_0_4_11: Запуск cross-layer проверки для {len(polygon_layers)} слоев")

        all_errors = []

        # Проверяем каждую пару слоев
        for i in range(len(polygon_layers)):
            for j in range(i + 1, len(polygon_layers)):
                layer_a = polygon_layers[i]
                layer_b = polygon_layers[j]

                log_info(f"Fsm_0_4_11: Проверка '{layer_a.name()}' vs '{layer_b.name()}'")

                errors = self._check_layer_pair(layer_a, layer_b)
                all_errors.extend(errors)

        self.overlaps_found = len(all_errors)

        if all_errors:
            log_info(f"Fsm_0_4_11: Найдено {len(all_errors)} cross-layer наложений")
        else:
            log_info("Fsm_0_4_11: Cross-layer наложений не обнаружено")

        return all_errors

    def _check_layer_pair(self, layer_a: QgsVectorLayer,
                         layer_b: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Проверка наложений между двумя слоями

        Args:
            layer_a: Первый слой
            layer_b: Второй слой

        Returns:
            Список наложений между слоями
        """
        errors = []

        # Строим spatial index для второго слоя
        index_b = QgsSpatialIndex()
        features_b = {}

        for feat in layer_b.getFeatures():
            if feat.hasGeometry() and not feat.geometry().isEmpty():
                index_b.addFeature(feat)
                features_b[feat.id()] = feat

        # Проверяем каждый объект первого слоя против второго
        for feat_a in layer_a.getFeatures():
            geom_a = feat_a.geometry()
            if not geom_a or geom_a.isEmpty():
                continue

            bbox = geom_a.boundingBox()
            candidate_ids = index_b.intersects(bbox)

            for cid in candidate_ids:
                feat_b = features_b.get(cid)
                if not feat_b:
                    continue

                geom_b = feat_b.geometry()

                try:
                    # Используем overlaps() для OGC-совместимости
                    if geom_a.overlaps(geom_b):
                        intersection = geom_a.intersection(geom_b)

                        if intersection and not intersection.isEmpty():
                            # Проверяем что пересечение полигональное
                            if intersection.type() != QgsWkbTypes.PolygonGeometry:
                                continue

                            area = intersection.area()
                            if area < self.MIN_OVERLAP_AREA:
                                continue

                            # Вычисляем процент наложения относительно меньшего полигона
                            area_a = geom_a.area()
                            area_b = geom_b.area()
                            min_area = min(area_a, area_b)
                            ratio = (area / min_area * 100) if min_area > 0 else 0

                            # Геометрия для отображения - центроид пересечения
                            error_geom = intersection.centroid()
                            if not error_geom or error_geom.isEmpty():
                                error_geom = intersection

                            errors.append({
                                'type': 'cross_layer_overlap',
                                'geometry': error_geom,
                                'feature_id': feat_a.id(),
                                'feature_id2': feat_b.id(),
                                'layer_a': layer_a.name(),
                                'layer_b': layer_b.name(),
                                'layer_a_id': layer_a.id(),
                                'layer_b_id': layer_b.id(),
                                'description': f'Наложение между слоями: '
                                              f'{layer_a.name()}[{feat_a.id()}] и '
                                              f'{layer_b.name()}[{feat_b.id()}] '
                                              f'(площадь {area:.4f} м2, {ratio:.1f}%)',
                                'area': area,
                                'ratio': ratio,
                                'intersection_geometry': intersection
                            })

                except Exception as e:
                    log_warning(f"Fsm_0_4_11: Ошибка проверки {feat_a.id()}/{feat_b.id()}: {e}")
                    continue

        return errors

    def get_errors_count(self) -> int:
        """Возвращает количество найденных ошибок"""
        return self.overlaps_found


class CrossLayerAnalysis:
    """
    Утилита для анализа cross-layer отношений

    Дополнительные проверки помимо overlaps:
    - contains: один полигон полностью содержит другой
    - within: один полигон полностью внутри другого
    - touches: полигоны касаются границами
    """

    @staticmethod
    def check_contains(layer_a: QgsVectorLayer,
                      layer_b: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Проверка contains: объекты layer_a содержат объекты layer_b

        Полезно для проверки что все ЗУ находятся внутри границ работ
        """
        results = []

        # Строим spatial index для layer_b
        index_b = QgsSpatialIndex()
        features_b = {}

        for feat in layer_b.getFeatures():
            if feat.hasGeometry() and not feat.geometry().isEmpty():
                index_b.addFeature(feat)
                features_b[feat.id()] = feat

        for feat_a in layer_a.getFeatures():
            geom_a = feat_a.geometry()
            if not geom_a or geom_a.isEmpty():
                continue

            bbox = geom_a.boundingBox()
            candidate_ids = index_b.intersects(bbox)

            for cid in candidate_ids:
                feat_b = features_b.get(cid)
                if not feat_b:
                    continue

                geom_b = feat_b.geometry()

                try:
                    if geom_a.contains(geom_b):
                        results.append({
                            'type': 'contains',
                            'container_layer': layer_a.name(),
                            'container_id': feat_a.id(),
                            'contained_layer': layer_b.name(),
                            'contained_id': feat_b.id(),
                            'geometry': geom_b.centroid()
                        })

                except Exception:
                    continue

        return results

    @staticmethod
    def check_outside(layer_a: QgsVectorLayer,
                     layer_b: QgsVectorLayer) -> List[Dict[str, Any]]:
        """
        Проверка: какие объекты layer_b находятся ВНЕ всех объектов layer_a

        Полезно для проверки что все ЗУ находятся в пределах границ работ
        """
        results = []

        # Объединяем все геометрии layer_a в одну
        combined_geom = None

        for feat in layer_a.getFeatures():
            geom = feat.geometry()
            if not geom or geom.isEmpty():
                continue

            if combined_geom is None:
                combined_geom = QgsGeometry(geom)
            else:
                combined_geom = combined_geom.combine(geom)

        if not combined_geom or combined_geom.isEmpty():
            return results

        # Проверяем каждый объект layer_b
        for feat_b in layer_b.getFeatures():
            geom_b = feat_b.geometry()
            if not geom_b or geom_b.isEmpty():
                continue

            try:
                # Объект вне границ если не пересекается с combined
                if not geom_b.intersects(combined_geom):
                    results.append({
                        'type': 'outside',
                        'boundary_layer': layer_a.name(),
                        'outside_layer': layer_b.name(),
                        'feature_id': feat_b.id(),
                        'geometry': geom_b.centroid(),
                        'description': f'Объект {feat_b.id()} из {layer_b.name()} '
                                      f'находится вне границ {layer_a.name()}'
                    })

                # Объект частично вне границ
                elif not combined_geom.contains(geom_b):
                    # Вычисляем часть, которая вне границ
                    outside_part = geom_b.difference(combined_geom)

                    if outside_part and not outside_part.isEmpty():
                        outside_area = outside_part.area()
                        total_area = geom_b.area()
                        ratio = (outside_area / total_area * 100) if total_area > 0 else 0

                        results.append({
                            'type': 'partially_outside',
                            'boundary_layer': layer_a.name(),
                            'outside_layer': layer_b.name(),
                            'feature_id': feat_b.id(),
                            'geometry': outside_part.centroid(),
                            'outside_area': outside_area,
                            'ratio': ratio,
                            'description': f'Объект {feat_b.id()} из {layer_b.name()} '
                                          f'частично ({ratio:.1f}%) вне границ {layer_a.name()}'
                        })

            except Exception as e:
                log_warning(f"Fsm_0_4_11: Ошибка проверки outside для {feat_b.id()}: {e}")
                continue

        return results
