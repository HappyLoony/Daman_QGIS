# -*- coding: utf-8 -*-
"""
M_36_LandCategoryAssignmentManager - Менеджер назначения План_категория

Каскадное определение планируемой категории земель для нарезанных ЗУ
на основе пространственного попадания центроида в зональные слои.

Приоритет (каскад):
1. "Земли населённых пунктов" - центроид внутри L_2_1_4_Выборка_НП
2. "Земли особо охраняемых территорий и объектов" - центроид внутри Le_1_2_5_21_WFS_ЗОУИТ_ОЗ_ООПТ
3. "Земли лесного фонда" - центроид внутри L_2_1_5_1_ЕГРН_Лесничество
4. "Земли промышленности..." - fallback (для всех остальных)

Проверка по центроиду - быстро и корректно для правильно нарезанных ЗУ.
При частичном попадании (центроид внутри, но геометрия не полностью) - warning в лог.

Зависимости:
- QgsProject - для поиска слоёв в проекте
- QgsSpatialIndex - для быстрого пространственного поиска

Используется в:
- Msm_26_4 (CuttingEngine) - после assign_work_type, перед нумерацией точек
"""

from typing import Dict, List, Optional, Any

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsGeometry,
    QgsSpatialIndex,
    QgsFeatureRequest,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
)

from Daman_QGIS.utils import log_info, log_warning

__all__ = ['LandCategoryAssignmentManager']

# Имена слоёв для поиска в проекте
_LAYER_NP = "L_2_1_4_Выборка_НП"
_LAYER_OOPT = "Le_1_2_5_21_WFS_ЗОУИТ_ОЗ_ООПТ"
_LAYER_LES = "L_2_1_5_1_ЕГРН_Лесничество"

# Категории в порядке приоритета каскада
_CATEGORY_CASCADE = [
    {"layer_name": _LAYER_NP, "category": "Земли населённых пунктов"},
    {"layer_name": _LAYER_OOPT, "category": "Земли особо охраняемых территорий и объектов"},
    {"layer_name": _LAYER_LES, "category": "Земли лесного фонда"},
]

_FALLBACK_CATEGORY = (
    "Земли промышленности, энергетики, транспорта, связи, радиовещания, "
    "телевидения, информатики, земли для обеспечения космической деятельности, "
    "земли обороны, безопасности и земли иного специального назначения"
)


class LandCategoryAssignmentManager:
    """Менеджер назначения планируемой категории земель (План_категория)

    Каскадная проверка: НП -> ООПТ -> Лес -> Промышленность (fallback).
    Поддерживает слои в разных CRS (WFS в EPSG:3857, данные в локальной МСК).
    """

    def __init__(self) -> None:
        self._zone_layers: Optional[List[Dict[str, Any]]] = None
        self._source_crs: Optional[QgsCoordinateReferenceSystem] = None

    def _find_layer_by_name(self, layer_name: str) -> Optional[QgsVectorLayer]:
        """Найти слой в проекте по имени

        Args:
            layer_name: Имя слоя для поиска

        Returns:
            QgsVectorLayer или None если не найден
        """
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if layer.name() == layer_name:
                return layer
        return None

    def _load_zone_layers(
        self, source_crs: QgsCoordinateReferenceSystem
    ) -> List[Dict[str, Any]]:
        """Загрузить зональные слои из проекта и построить пространственные индексы.

        Args:
            source_crs: CRS исходных данных (нарезки) для создания трансформов

        Returns:
            Список словарей в порядке приоритета:
            [{"layer": QgsVectorLayer, "category": str, "index": QgsSpatialIndex,
              "transform": QgsCoordinateTransform или None}, ...]
            Отсутствующие/пустые слои пропускаются.
        """
        zone_layers: List[Dict[str, Any]] = []

        for cascade_item in _CATEGORY_CASCADE:
            layer_name = cascade_item["layer_name"]
            category = cascade_item["category"]

            layer = self._find_layer_by_name(layer_name)
            if layer is None or not layer.isValid():
                log_info(f"M_36: Слой '{layer_name}' не найден - пропущен")
                continue

            feature_count = layer.featureCount()
            if feature_count == 0:
                log_info(f"M_36: Слой '{layer_name}' пуст - пропущен")
                continue

            # Строим пространственный индекс
            spatial_index = QgsSpatialIndex(layer.getFeatures())

            # Создаём трансформ если CRS различаются
            layer_crs = layer.crs()
            transform: Optional[QgsCoordinateTransform] = None
            if layer_crs != source_crs and layer_crs.isValid() and source_crs.isValid():
                transform = QgsCoordinateTransform(
                    source_crs, layer_crs, QgsProject.instance()
                )
                log_info(
                    f"M_36: Слой '{layer_name}' в другой CRS "
                    f"({layer_crs.authid()}), трансформация включена"
                )

            zone_layers.append({
                "layer": layer,
                "category": category,
                "index": spatial_index,
                "layer_name": layer_name,
                "transform": transform,
            })

            log_info(f"M_36: Слой '{layer_name}' найден ({feature_count} features)")

        return zone_layers

    def _determine_category(
        self,
        geometry: QgsGeometry,
        zone_layers: List[Dict[str, Any]],
        feature_id: Any = None,
    ) -> str:
        """Определить категорию земель для одной геометрии.

        Args:
            geometry: Геометрия ЗУ (в исходной CRS)
            zone_layers: Загруженные зональные слои с индексами и трансформами
            feature_id: ID объекта для логирования

        Returns:
            Строковое значение категории
        """
        centroid = geometry.centroid()
        if centroid.isEmpty():
            log_warning(f"M_36: Не удалось вычислить центроид для ID={feature_id}")
            return _FALLBACK_CATEGORY

        for zone in zone_layers:
            spatial_index: QgsSpatialIndex = zone["index"]
            layer: QgsVectorLayer = zone["layer"]
            category: str = zone["category"]
            layer_name: str = zone["layer_name"]
            transform: Optional[QgsCoordinateTransform] = zone.get("transform")

            # Трансформируем центроид в CRS зонального слоя если нужно
            test_centroid = QgsGeometry(centroid)
            test_geometry = QgsGeometry(geometry)
            if transform is not None:
                test_centroid.transform(transform)
                test_geometry.transform(transform)

            centroid_bbox = test_centroid.boundingBox()

            # Быстрый поиск кандидатов через пространственный индекс
            candidate_ids = spatial_index.intersects(centroid_bbox)
            if not candidate_ids:
                continue

            # Точная проверка: центроид внутри геометрии зоны
            for fid in candidate_ids:
                request = QgsFeatureRequest().setFilterFid(fid)
                request.setSubsetOfAttributes([])  # Атрибуты не нужны
                for zone_feature in layer.getFeatures(request):
                    zone_geom = zone_feature.geometry()
                    if zone_geom.isEmpty():
                        continue

                    if test_centroid.within(zone_geom):
                        # Центроид внутри - проверяем полное вмещение
                        if not test_geometry.within(zone_geom):
                            log_warning(
                                f"M_36: Частичное попадание ID={feature_id} "
                                f"в слой '{layer_name}' - возможная ошибка нарезки"
                            )
                        return category

        return _FALLBACK_CATEGORY

    def assign_land_category(
        self,
        features_data: List[Dict[str, Any]],
        source_crs: Optional[QgsCoordinateReferenceSystem] = None,
    ) -> List[Dict[str, Any]]:
        """Назначить План_категория для списка features_data.

        Для каждого feature:
        1. Берёт геометрию из item['geometry']
        2. Вычисляет центроид
        3. Проверяет каскад: НП -> ООПТ -> Лес -> fallback
        4. Устанавливает attrs['План_категория']

        Args:
            features_data: Список словарей с ключами 'geometry' (QgsGeometry)
                          и 'attributes' (dict)
            source_crs: CRS исходных данных. Если None, берётся CRS проекта.

        Returns:
            Тот же список с обновлённым полем План_категория (in-place)
        """
        if not features_data:
            return features_data

        log_info(f"M_36: Начало назначения План_категория: {len(features_data)} объектов")

        # Определяем CRS исходных данных
        if source_crs is None:
            source_crs = QgsProject.instance().crs()
        self._source_crs = source_crs

        # Загрузка зональных слоёв (один раз для всей партии)
        zone_layers = self._load_zone_layers(source_crs)

        if not zone_layers:
            log_info("M_36: Зональные слои не найдены - все объекты получат fallback категорию")

        # Счётчики для итогового лога
        counts: Dict[str, int] = {}

        for item in features_data:
            geometry = item.get('geometry')
            attrs = item.get('attributes', {})
            feature_id = attrs.get('ID', '?')

            if geometry is None or geometry.isEmpty():
                category = _FALLBACK_CATEGORY
            else:
                category = self._determine_category(geometry, zone_layers, feature_id)

            attrs['План_категория'] = category

            # Считаем статистику
            # Короткое название для лога
            short_name = category.split(',')[0] if ',' in category else category
            short_name = short_name.replace('Земли ', '')
            counts[short_name] = counts.get(short_name, 0) + 1

        # Итоговый лог
        stats_parts = [f"{name}={count}" for name, count in counts.items()]
        log_info(f"M_36: Результат План_категория: {', '.join(stats_parts)}")

        return features_data
