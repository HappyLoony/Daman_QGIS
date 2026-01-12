# -*- coding: utf-8 -*-
"""
Модуль исправления топологических ошибок - native QGIS версия
Исправляет ошибки найденные координатором
"""

from typing import Dict, Any, List, Optional
from qgis.core import (
    QgsVectorLayer, QgsGeometry,
    QgsFeature, QgsVectorFileWriter, QgsProject, QgsPointXY
)
import processing
from Daman_QGIS.constants import COORDINATE_PRECISION, PRECISION_DECIMALS
from Daman_QGIS.utils import log_info
from Daman_QGIS.managers import CoordinatePrecisionManager as CPM


class Fsm_0_4_6_TopologyFixer:
    """
    Исправление топологических ошибок через native QGIS алгоритмы
    """

    def __init__(self):
        """Инициализация fixer'а"""
        self.statistics = {}

    def fix_errors(self, layer: QgsVectorLayer,
                  errors_by_type: Dict[str, List[Dict]],
                  fix_types: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Исправление ошибок

        Args:
            layer: Исходный слой
            errors_by_type: Ошибки по типам из координатора
            fix_types: Типы для исправления. None = все.
                ['validity', 'duplicate_vertices', 'precision']

        Returns:
            Результаты исправления:
            {
                'fixed_layer': QgsVectorLayer,
                'fixes_applied': int,
                'fixes_by_type': dict
            }
        """
        if fix_types is None:
            fix_types = list(errors_by_type.keys())

        log_info(f"Fsm_0_4_6: Начало исправления ошибок. Типы: {fix_types}")

        # Копируем слой для исправлений
        fixed_layer = layer
        total_fixes = 0
        fixes_by_type = {}

        # 1. Исправление валидности
        if 'validity' in fix_types and 'validity' in errors_by_type:
            fixed_layer, count = self._fix_validity(fixed_layer, errors_by_type['validity'])
            fixes_by_type['validity'] = count
            total_fixes += count

        # 2. Исправление дублей вершин
        if 'duplicate_vertex' in fix_types and 'duplicate_vertex' in errors_by_type:
            fixed_layer, count = self._fix_duplicate_vertices(fixed_layer)
            fixes_by_type['duplicate_vertices'] = count
            total_fixes += count

        # 3. Исправление точности
        if 'precision' in fix_types and 'precision' in errors_by_type:
            fixed_layer, count = self._fix_precision(fixed_layer, errors_by_type['precision'])
            fixes_by_type['precision'] = count
            total_fixes += count

        # 4. Исправление самопересечений
        if 'self_intersection' in fix_types and 'self_intersection' in errors_by_type:
            fixed_layer, count = self._fix_self_intersections(fixed_layer, errors_by_type['self_intersection'])
            fixes_by_type['self_intersections'] = count
            total_fixes += count

        # 5. Исправление близких точек через native:removeduplicatevertices
        if 'close_points' in fix_types and 'close_points' in errors_by_type:
            fixed_layer, count = self._fix_close_points(fixed_layer)
            fixes_by_type['close_points'] = count
            total_fixes += count

        # 6. Исправление близких точек между объектами через snap
        if 'cross_feature_close_points' in fix_types and 'cross_feature_close_points' in errors_by_type:
            fixed_layer, count = self._fix_cross_feature_close_points(fixed_layer)
            fixes_by_type['cross_feature_close_points'] = count
            total_fixes += count

        log_info(f"Fsm_0_4_6: Исправление завершено. Применено {total_fixes} исправлений")

        return {
            'fixed_layer': fixed_layer,
            'fixes_applied': total_fixes,
            'fixes_by_type': fixes_by_type
        }
    def _fix_validity(self, layer: QgsVectorLayer,
                     errors: List[Dict]) -> tuple:
        """
        Исправление невалидных геометрий через native:fixgeometries

        Returns:
            (исправленный_слой, количество_исправлений)
        """
        result = processing.run("native:fixgeometries", {
            'INPUT': layer,
            'METHOD': 1,  # Structure method
            'OUTPUT': 'memory:'
        })

        fixed_layer = result['OUTPUT']
        count = len(errors)

        log_info(f"Fsm_0_4_6: Исправлено {count} ошибок валидности")

        return fixed_layer, count
    def _fix_duplicate_vertices(self, layer: QgsVectorLayer) -> tuple:
        """
        Удаление дублей вершин через native:removeduplicatevertices

        Returns:
            (исправленный_слой, количество_исправлений)
        """
        # Считаем вершины до
        vertices_before = processing.run("native:extractvertices", {
            'INPUT': layer,
            'OUTPUT': 'memory:'
        })
        count_before = vertices_before['OUTPUT'].featureCount()

        # Удаляем дубли
        result = processing.run("native:removeduplicatevertices", {
            'INPUT': layer,
            'TOLERANCE': COORDINATE_PRECISION,
            'USE_Z_VALUE': False,
            'OUTPUT': 'memory:'
        })

        fixed_layer = result['OUTPUT']

        # Считаем вершины после
        vertices_after = processing.run("native:extractvertices", {
            'INPUT': fixed_layer,
            'OUTPUT': 'memory:'
        })
        count_after = vertices_after['OUTPUT'].featureCount()

        count = count_before - count_after

        log_info(f"Fsm_0_4_6: Удалено {count} дублей вершин")

        return fixed_layer, count
    def _fix_precision(self, layer: QgsVectorLayer,
                      errors: List[Dict]) -> tuple:
        """
        Округление координат до 0.01м

        Returns:
            (исправленный_слой, количество_исправлений)
        """
        # Создаем копию слоя
        # МИГРАЦИЯ POLYGON → MULTIPOLYGON: временный слой
        fixed_layer = QgsVectorLayer(
            f"MultiPolygon?crs={layer.crs().authid()}",
            f"{layer.name()}_fixed",
            "memory"
        )

        provider = fixed_layer.dataProvider()
        provider.addAttributes(layer.fields())
        fixed_layer.updateFields()

        count = 0

        # Обрабатываем каждый объект
        for feature in layer.getFeatures():
            geom = feature.geometry()
            if not geom:
                continue

            # Округляем координаты
            rounded_geom = self._round_geometry(geom)

            if rounded_geom:
                new_feat = QgsFeature()
                new_feat.setGeometry(rounded_geom)
                new_feat.setAttributes(feature.attributes())
                provider.addFeature(new_feat)
                count += 1

        fixed_layer.updateExtents()

        log_info(f"Fsm_0_4_6: Округлено координат в {count} объектах")

        return fixed_layer, len(errors)

    def _fix_self_intersections(self, layer: QgsVectorLayer,
                               errors: List[Dict]) -> tuple:
        """
        Исправление самопересечений через native:fixgeometries

        Returns:
            (исправленный_слой, количество_исправлений)
        """
        # Аналогично _fix_validity
        return self._fix_validity(layer, errors)

    def _fix_close_points(self, layer: QgsVectorLayer) -> tuple:
        """
        Исправление близких точек через native:removeduplicatevertices.

        Использует TOLERANCE=0.01м (1 см) для объединения близких вершин.
        Это аналог PostGIS ST_RemoveRepeatedPoints.

        ВАЖНО: Этот метод объединяет ВСЕ вершины на расстоянии <= 1 см,
        включая не последовательные. Это может изменить форму геометрии,
        но гарантирует отсутствие близких точек.

        Returns:
            (исправленный_слой, количество_исправлений)
        """
        # Считаем вершины до
        vertices_before = processing.run("native:extractvertices", {
            'INPUT': layer,
            'OUTPUT': 'memory:'
        })
        count_before = vertices_before['OUTPUT'].featureCount()

        # Удаляем близкие точки с TOLERANCE = 0.01м (1 см)
        # native:removeduplicatevertices объединяет вершины на расстоянии <= TOLERANCE
        result = processing.run("native:removeduplicatevertices", {
            'INPUT': layer,
            'TOLERANCE': COORDINATE_PRECISION,  # 0.01м
            'USE_Z_VALUE': False,
            'OUTPUT': 'memory:'
        })

        fixed_layer = result['OUTPUT']

        # Считаем вершины после
        vertices_after = processing.run("native:extractvertices", {
            'INPUT': fixed_layer,
            'OUTPUT': 'memory:'
        })
        count_after = vertices_after['OUTPUT'].featureCount()

        count = count_before - count_after

        log_info(f"Fsm_0_4_6: Исправлено {count} близких точек (tolerance={COORDINATE_PRECISION}м)")

        return fixed_layer, count

    def _fix_cross_feature_close_points(self, layer: QgsVectorLayer) -> tuple:
        """
        Исправление близких точек между разными объектами через native:snapgeometries.

        Snap привязывает вершины одного объекта к ближайшим вершинам других объектов
        в пределах TOLERANCE. Это устраняет микро-расхождения на общих границах.

        Returns:
            (исправленный_слой, количество_исправлений)
        """
        # native:snapgeometries привязывает геометрии к ссылочному слою
        # Используем сам слой как reference - snap к соседним объектам
        result = processing.run("native:snapgeometries", {
            'INPUT': layer,
            'REFERENCE_LAYER': layer,  # Snap к самому себе (к соседним features)
            'TOLERANCE': COORDINATE_PRECISION,  # 0.01м
            'BEHAVIOR': 0,  # Prefer aligning nodes, insert extra vertices where required
            'OUTPUT': 'memory:'
        })

        fixed_layer = result['OUTPUT']

        # Подсчитываем изменения через сравнение WKB
        changes_count = 0
        original_features = {f.id(): f.geometry().asWkb() for f in layer.getFeatures() if f.hasGeometry()}
        for feature in fixed_layer.getFeatures():
            if not feature.hasGeometry():
                continue
            fid = feature.id()
            if fid in original_features:
                if feature.geometry().asWkb() != original_features[fid]:
                    changes_count += 1

        log_info(
            f"Fsm_0_4_6: Исправлено {changes_count} объектов с близкими точками между features "
            f"(snap tolerance={COORDINATE_PRECISION}м)"
        )

        return fixed_layer, changes_count

    def _round_geometry(self, geometry: QgsGeometry) -> Optional[QgsGeometry]:
        """
        Округление координат геометрии до 0.01м с использованием snappedToGrid.

        Использует QGIS snappedToGrid() для классического математического
        округления (совместимо с нарезкой F_3_1).

        Args:
            geometry: Исходная геометрия

        Returns:
            Геометрия с округленными координатами
        """
        # Используем централизованный метод из M_6
        return CPM._round_geometry(geometry)

    def get_statistics(self) -> Dict[str, Any]:
        """Получение статистики исправлений"""
        return self.statistics
