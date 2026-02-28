"""
Msm_41_1: NetworkPreparer - Подготовка линейного слоя для сетевого анализа.

Принимает произвольный линейный слой (OSM, DXF, ручной ввод).
Добавляет speed_kmh по профилю, конвертирует oneway -> direction,
удаляет ребра с speed=0, репроецирует в CRS проекта.
Строит QgsGraph через QgsVectorLayerDirector + QgsGraphBuilder.

Родительский менеджер: M_41_IsochroneTransportManager
"""

from __future__ import annotations

from typing import Optional

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.analysis import (
    QgsGraph,
    QgsGraphBuilder,
    QgsGraphAnalyzer,
    QgsNetworkDistanceStrategy,
    QgsNetworkSpeedStrategy,
    QgsVectorLayerDirector,
)
from qgis.PyQt.QtCore import QMetaType

from Daman_QGIS.utils import log_info, log_warning, log_error

from .Msm_41_4_speed_profiles import SpeedProfile

__all__ = ['Msm_41_1_NetworkPreparer']


# Маппинг OSM oneway -> числовое direction для QgsVectorLayerDirector
ONEWAY_MAP: dict[str, int] = {
    'yes': 1,        # Forward only (по оцифровке)
    '-1': 2,         # Reverse only (против оцифровки)
    'no': 0,         # Both directions
    'reversible': 0, # Both directions (упрощение)
}

# Фактор конвертации: скорость км/ч -> стоимость в секундах на метр
# cost = distance_m / (speed_kmh * 1000 / 3600) = distance_m * 3600 / (speed_kmh * 1000)
SPEED_FACTOR = 1000.0 / 3600.0  # для QgsNetworkSpeedStrategy


class Msm_41_1_NetworkPreparer:
    """Подготовка линейного слоя для сетевого анализа.

    Создает memory layer с полями speed_kmh и direction,
    строит QgsGraph для переиспользования в Dijkstra.
    """

    def __init__(self) -> None:
        self._cache: dict[str, _PreparedNetwork] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def prepare_network(
        self,
        road_layer: QgsVectorLayer,
        profile: SpeedProfile,
        project_crs: Optional[QgsCoordinateReferenceSystem] = None,
        clip_extent: Optional[QgsRectangle] = None,
    ) -> _PreparedNetwork:
        """Подготовить слой для сетевого анализа.

        Args:
            road_layer: Исходный линейный слой (OSM, DXF и т.д.)
            profile: Профиль скоростей
            project_crs: CRS проекта для репроекции (None = CRS слоя)
            clip_extent: Обрезка сети по bbox (None = без обрезки)

        Returns:
            _PreparedNetwork с memory layer и метаданными

        Raises:
            ValueError: Невалидный слой или отсутствие ребер
        """
        cache_key = f"{road_layer.id()}_{profile.name}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if cached.is_valid():
                log_info(f"Msm_41_1: Используется кэшированная сеть для '{profile.name}'")
                return cached

        log_info(
            f"Msm_41_1: Подготовка сети '{road_layer.name()}' "
            f"для профиля '{profile.name}'"
        )

        target_crs = project_crs or road_layer.crs()
        need_transform = road_layer.crs() != target_crs

        if need_transform:
            log_info(
                f"Msm_41_1: Репроекция {road_layer.crs().authid()} -> "
                f"{target_crs.authid()}"
            )

        # 1. Создать memory layer с нужными полями
        mem_layer = self._create_memory_layer(target_crs, profile)

        # 2. Заполнить данными (фильтрация speed=0, конвертация oneway)
        feature_count = self._populate_layer(
            source=road_layer,
            target=mem_layer,
            profile=profile,
            target_crs=target_crs,
            need_transform=need_transform,
            clip_extent=clip_extent,
        )

        if feature_count == 0:
            raise ValueError(
                f"Msm_41_1: После фильтрации не осталось ребер для профиля "
                f"'{profile.name}'. Проверьте слой '{road_layer.name()}'."
            )

        log_info(
            f"Msm_41_1: Подготовлено {feature_count} ребер "
            f"(из {road_layer.featureCount()} исходных)"
        )

        result = _PreparedNetwork(
            layer=mem_layer,
            profile=profile,
            crs=target_crs,
            feature_count=feature_count,
            source_layer_id=road_layer.id(),
        )
        self._cache[cache_key] = result
        return result

    def build_graph(
        self,
        prepared: _PreparedNetwork,
        additional_points: Optional[list[QgsPointXY]] = None,
        topology_tolerance: float = 0.0,
        cost_strategy: str = 'speed',
    ) -> GraphBuildResult:
        """Построить граф из подготовленного слоя.

        Args:
            prepared: Результат prepare_network()
            additional_points: Точки для привязки к графу (snap)
            topology_tolerance: Допуск топологии QgsGraphBuilder
            cost_strategy: 'speed' (cost в секундах) или 'distance' (cost в метрах)

        Returns:
            GraphBuildResult с графом и привязанными точками
        """
        points = additional_points or []
        layer = prepared.layer
        profile = prepared.profile
        is_walk = profile.name == 'walk'

        # Direction field
        if is_walk:
            direction_field_idx = -1  # Все ребра двунаправленные
        else:
            direction_field_idx = layer.fields().indexOf('direction')

        # Director
        director = QgsVectorLayerDirector(
            layer,
            direction_field_idx,
            '1', '2', '0',  # forward, backward, both значения в поле direction
            QgsVectorLayerDirector.Direction.DirectionBoth,  # default
        )

        # Strategy
        if cost_strategy == 'distance':
            strategy = QgsNetworkDistanceStrategy()
            log_info("Msm_41_1: Стратегия графа: distance (cost в метрах)")
        else:
            speed_field_idx = layer.fields().indexOf('speed_kmh')
            strategy = QgsNetworkSpeedStrategy(
                speed_field_idx,
                prepared.profile.default_speed,
                SPEED_FACTOR,
            )
        director.addStrategy(strategy)

        # Build graph
        builder = QgsGraphBuilder(prepared.crs, True, topology_tolerance)

        log_info(
            f"Msm_41_1: Построение графа ({prepared.feature_count} ребер, "
            f"{len(points)} доп. точек)"
        )
        tied_points = director.makeGraph(builder, points)
        graph = builder.graph()

        log_info(
            f"Msm_41_1: Граф построен: {graph.vertexCount()} вершин, "
            f"{graph.edgeCount()} ребер"
        )

        return GraphBuildResult(
            graph=graph,
            tied_points=tied_points,
            director=director,
            builder=builder,
        )

    def invalidate_cache(self, layer_id: Optional[str] = None) -> None:
        """Инвалидировать кэш подготовленных сетей.

        Args:
            layer_id: ID конкретного слоя (None = весь кэш)
        """
        if layer_id is None:
            self._cache.clear()
            log_info("Msm_41_1: Кэш полностью очищен")
        else:
            keys_to_remove = [k for k in self._cache if k.startswith(layer_id)]
            for key in keys_to_remove:
                del self._cache[key]
            if keys_to_remove:
                log_info(f"Msm_41_1: Кэш очищен для слоя {layer_id}")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_memory_layer(
        crs: QgsCoordinateReferenceSystem,
        profile: SpeedProfile,
    ) -> QgsVectorLayer:
        """Создать пустой memory layer с нужными полями."""
        uri = f"LineString?crs={crs.authid()}"
        mem_layer = QgsVectorLayer(uri, f"net_{profile.name}", "memory")
        provider = mem_layer.dataProvider()

        fields = QgsFields()
        fields.append(QgsField("speed_kmh", QMetaType.Type.Double))
        fields.append(QgsField("direction", QMetaType.Type.Int))
        fields.append(QgsField("highway", QMetaType.Type.QString))
        provider.addAttributes(fields)
        mem_layer.updateFields()

        return mem_layer

    def _populate_layer(
        self,
        source: QgsVectorLayer,
        target: QgsVectorLayer,
        profile: SpeedProfile,
        target_crs: QgsCoordinateReferenceSystem,
        need_transform: bool,
        clip_extent: Optional[QgsRectangle],
    ) -> int:
        """Заполнить memory layer данными с фильтрацией и конвертацией.

        Returns:
            Количество добавленных ребер
        """
        transform = None
        if need_transform:
            transform = QgsCoordinateTransform(
                source.crs(), target_crs, QgsProject.instance()
            )

        # Определяем имена полей в исходном слое
        source_fields = source.fields()
        highway_field = self._find_field(source_fields, ['highway', 'fclass', 'type'])
        oneway_field = self._find_field(source_fields, ['oneway', 'one_way'])
        maxspeed_field = self._find_field(source_fields, ['maxspeed', 'max_speed'])

        is_walk = profile.name == 'walk'

        # Подготовить request с clip
        request = QgsFeatureRequest()
        if clip_extent is not None:
            if need_transform:
                # Трансформировать extent обратно в CRS источника
                inv_transform = QgsCoordinateTransform(
                    target_crs, source.crs(), QgsProject.instance()
                )
                clip_rect = inv_transform.transformBoundingBox(clip_extent)
                request.setFilterRect(clip_rect)
            else:
                request.setFilterRect(clip_extent)

        features_to_add: list[QgsFeature] = []
        skipped_zero = 0

        from .Msm_41_4_speed_profiles import Msm_41_4_SpeedProfiles
        speed_profiles = Msm_41_4_SpeedProfiles()

        exploded_count = 0

        for feat in source.getFeatures(request):
            geom = feat.geometry()
            if geom.isNull() or geom.isEmpty():
                continue

            # Тип дороги
            highway_val = ''
            if highway_field is not None:
                raw = feat[highway_field]
                highway_val = str(raw).strip().lower() if raw else ''

            # Скорость: maxspeed -> highway -> default
            # ВАЖНО: для merged features (Le_1_4_1_1) maxspeed берётся от
            # первого/длиннейшего сегмента и может быть неточным.
            # Highway маппинг более надёжен для объединённых сегментов.
            maxspeed_val = None
            if maxspeed_field is not None:
                maxspeed_val = feat[maxspeed_field]

            speed = speed_profiles.get_speed_for_feature(
                profile, highway_val, maxspeed_val
            )

            # Фильтрация запрещенных ребер
            if speed_profiles.is_edge_forbidden(speed):
                skipped_zero += 1
                continue

            # Direction (oneway)
            # ВАЖНО: для merged features oneway может быть неточным
            # (разные сегменты могли иметь разные направления).
            direction = 0  # both
            if not is_walk and oneway_field is not None:
                oneway_raw = feat[oneway_field]
                oneway_str = str(oneway_raw).strip().lower() if oneway_raw else ''
                direction = ONEWAY_MAP.get(oneway_str, 0)

            # Explode MultiLineString -> отдельные LineString
            # OSM дороги загружаются как MultiLineString после merge
            # в Fsm_1_2_3. QgsGraphBuilder обработает Multi*, но
            # каждый sub-LineString = отдельное ребро с теми же атрибутами.
            line_geoms = self._explode_to_linestrings(geom)

            for line_geom in line_geoms:
                # Репроекция
                out_geom = QgsGeometry(line_geom)
                if transform is not None:
                    out_geom.transform(transform)

                out_feat = QgsFeature(target.fields())
                out_feat.setGeometry(out_geom)
                out_feat['speed_kmh'] = speed
                out_feat['direction'] = direction
                out_feat['highway'] = highway_val
                features_to_add.append(out_feat)

            if len(line_geoms) > 1:
                exploded_count += len(line_geoms) - 1

        # Batch add
        if features_to_add:
            target.dataProvider().addFeatures(features_to_add)
            target.updateExtents()

        if skipped_zero > 0:
            log_info(
                f"Msm_41_1: Отфильтровано {skipped_zero} ребер "
                f"с speed=0 для профиля '{profile.name}'"
            )

        if exploded_count > 0:
            log_info(
                f"Msm_41_1: Разбито MultiLineString -> "
                f"+{exploded_count} дополнительных ребер"
            )

        return len(features_to_add)

    @staticmethod
    def _explode_to_linestrings(geom: QgsGeometry) -> list[QgsGeometry]:
        """Разбить MultiLineString на отдельные LineString.

        OSM дороги после merge в Fsm_1_2_3 хранятся как MultiLineString.
        QgsGraphBuilder корректно обрабатывает Multi*, но для точности
        лучше разбить на отдельные ребра.

        Args:
            geom: Входная геометрия (LineString или MultiLineString)

        Returns:
            Список QgsGeometry (каждая - LineString)
        """
        wkb_type = QgsWkbTypes.flatType(geom.wkbType())

        # Уже одиночный LineString
        if wkb_type == QgsWkbTypes.Type.LineString:
            return [geom]

        # MultiLineString -> разбить на части
        if wkb_type == QgsWkbTypes.Type.MultiLineString:
            parts: list[QgsGeometry] = []
            for part in geom.parts():
                part_geom = QgsGeometry(part.clone())
                # Пропускаем вырожденные части (менее 2 вершин)
                if part_geom.constGet().nCoordinates() >= 2:
                    parts.append(part_geom)
            return parts if parts else [geom]

        # Другие типы (CompoundCurve и т.д.) - вернуть как есть
        log_warning(
            f"Msm_41_1: Неожиданный тип геометрии "
            f"{QgsWkbTypes.displayString(geom.wkbType())}, обработка как есть"
        )
        return [geom]

    @staticmethod
    def _find_field(fields: QgsFields, candidates: list[str]) -> Optional[str]:
        """Найти поле по списку возможных имен (case-insensitive)."""
        field_names_lower = {f.name().lower(): f.name() for f in fields}
        for candidate in candidates:
            if candidate.lower() in field_names_lower:
                return field_names_lower[candidate.lower()]
        return None


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

class _PreparedNetwork:
    """Результат подготовки сети (memory layer + метаданные)."""

    __slots__ = ('layer', 'profile', 'crs', 'feature_count', 'source_layer_id')

    def __init__(
        self,
        layer: QgsVectorLayer,
        profile: SpeedProfile,
        crs: QgsCoordinateReferenceSystem,
        feature_count: int,
        source_layer_id: str,
    ) -> None:
        self.layer = layer
        self.profile = profile
        self.crs = crs
        self.feature_count = feature_count
        self.source_layer_id = source_layer_id

    def is_valid(self) -> bool:
        """Проверка валидности кэшированной сети."""
        return (
            self.layer is not None
            and self.layer.isValid()
            and self.layer.featureCount() > 0
        )


class GraphBuildResult:
    """Результат построения графа."""

    __slots__ = ('graph', 'tied_points', 'director', 'builder')

    def __init__(
        self,
        graph: QgsGraph,
        tied_points: list[QgsPointXY],
        director: QgsVectorLayerDirector,
        builder: QgsGraphBuilder,
    ) -> None:
        self.graph = graph
        self.tied_points = tied_points
        self.director = director
        self.builder = builder
