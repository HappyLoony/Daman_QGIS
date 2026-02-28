"""
Msm_41_5: ResultLayerWriter - Запись результатов M_41 в GeoPackage / memory layers.

Форматирование маршрутов (LineString) и изохрон (Polygon) с атрибутами,
подписями, стилями и опциональным упрощением для QField.

Родительский менеджер: M_41_IsochroneTransportManager
"""

from __future__ import annotations

from typing import Optional

import processing

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGraduatedSymbolRenderer,
    QgsGeometry,
    QgsProject,
    QgsRendererRange,
    QgsSimpleFillSymbolLayer,
    QgsSimpleLineSymbolLayer,
    QgsSymbol,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QMetaType
from qgis.PyQt.QtGui import QColor

from Daman_QGIS.utils import log_info, log_warning, log_error

from .Msm_41_4_speed_profiles import RouteResult, IsochroneResult

__all__ = ['Msm_41_5_ResultLayerWriter']


# Палитра "магма инвертированная" (от ближнего к дальнему)
_MAGMA_COLORS = [
    QColor(252, 253, 191),  # Ближайший (светло-желтый)
    QColor(254, 206, 111),
    QColor(253, 159, 72),
    QColor(236, 112, 72),
    QColor(205, 72, 86),
    QColor(163, 43, 107),
    QColor(115, 22, 121),
    QColor(68, 11, 106),
    QColor(31, 12, 72),
    QColor(0, 0, 4),        # Самый дальний (почти черный)
]


class Msm_41_5_ResultLayerWriter:
    """Запись результатов маршрутов и изохрон в GeoPackage / memory layers."""

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public API: маршруты
    # ------------------------------------------------------------------

    def save_routes_to_layer(
        self,
        routes: list[RouteResult],
        layer_name: str,
        crs: QgsCoordinateReferenceSystem,
        gpkg_path: Optional[str] = None,
        add_to_project: bool = True,
    ) -> Optional[QgsVectorLayer]:
        """Сохранить маршруты как слой.

        Args:
            routes: Список RouteResult
            layer_name: Имя слоя
            crs: CRS результата
            gpkg_path: Путь к GPKG (None = memory layer)
            add_to_project: Добавить слой в текущий проект

        Returns:
            QgsVectorLayer или None при ошибке
        """
        if not routes:
            log_warning("Msm_41_5: Нет маршрутов для сохранения")
            return None

        successful = [r for r in routes if r.success and r.geometry]
        if not successful:
            log_warning("Msm_41_5: Нет успешных маршрутов для сохранения")
            return None

        log_info(
            f"Msm_41_5: Сохранение {len(successful)} маршрутов "
            f"в '{layer_name}'"
        )

        # Создать memory layer
        mem_layer = self._create_route_layer(layer_name, crs)
        features = self._routes_to_features(successful, mem_layer.fields())

        mem_layer.dataProvider().addFeatures(features)
        mem_layer.updateExtents()

        # Стиль
        self._apply_route_style(mem_layer)

        # Запись в GPKG или оставить memory
        result_layer = self._persist_layer(
            mem_layer, layer_name, gpkg_path
        )

        if result_layer and add_to_project:
            self._add_to_project(result_layer)

        log_info(
            f"Msm_41_5: Маршруты сохранены: {len(successful)} объектов"
        )
        return result_layer

    # ------------------------------------------------------------------
    # Public API: изохроны
    # ------------------------------------------------------------------

    def save_isochrones_to_layer(
        self,
        isochrones: list[IsochroneResult],
        layer_name: str,
        crs: QgsCoordinateReferenceSystem,
        gpkg_path: Optional[str] = None,
        add_to_project: bool = True,
        simplify_for_qfield: bool = False,
    ) -> Optional[QgsVectorLayer]:
        """Сохранить изохроны как слой.

        Args:
            isochrones: Список IsochroneResult
            layer_name: Имя слоя
            crs: CRS результата
            gpkg_path: Путь к GPKG (None = memory layer)
            add_to_project: Добавить слой в текущий проект
            simplify_for_qfield: Упростить геометрии для QField (Douglas-Peucker 10м)

        Returns:
            QgsVectorLayer или None при ошибке
        """
        if not isochrones:
            log_warning("Msm_41_5: Нет изохрон для сохранения")
            return None

        valid = [
            iso for iso in isochrones
            if iso.geometry and not iso.geometry.isEmpty()
        ]
        if not valid:
            log_warning("Msm_41_5: Нет валидных изохрон для сохранения")
            return None

        log_info(
            f"Msm_41_5: Сохранение {len(valid)} изохрон "
            f"в '{layer_name}'"
        )

        # Создать memory layer
        mem_layer = self._create_isochrone_layer(layer_name, crs)
        features = self._isochrones_to_features(valid, mem_layer.fields())

        mem_layer.dataProvider().addFeatures(features)
        mem_layer.updateExtents()

        # Упрощение для QField
        if simplify_for_qfield:
            mem_layer = self._simplify_layer(mem_layer)

        # Стиль
        self._apply_isochrone_style(mem_layer, valid)

        # Запись в GPKG или оставить memory
        result_layer = self._persist_layer(
            mem_layer, layer_name, gpkg_path
        )

        if result_layer and add_to_project:
            self._add_to_project(result_layer)

        log_info(
            f"Msm_41_5: Изохроны сохранены: {len(valid)} объектов"
        )
        return result_layer

    # ------------------------------------------------------------------
    # Layer creation
    # ------------------------------------------------------------------

    @staticmethod
    def _create_route_layer(
        name: str,
        crs: QgsCoordinateReferenceSystem,
    ) -> QgsVectorLayer:
        """Создать memory layer для маршрутов."""
        uri = f"LineString?crs={crs.authid()}"
        layer = QgsVectorLayer(uri, name, "memory")
        provider = layer.dataProvider()

        fields = QgsFields()
        fields.append(QgsField("id", QMetaType.Type.Int))
        fields.append(QgsField("profile", QMetaType.Type.QString))
        fields.append(QgsField("distance_m", QMetaType.Type.Double))
        fields.append(QgsField("duration_s", QMetaType.Type.Double))
        fields.append(QgsField("duration_min", QMetaType.Type.Double))
        fields.append(QgsField("origin_name", QMetaType.Type.QString))
        fields.append(QgsField("dest_name", QMetaType.Type.QString))
        provider.addAttributes(fields)
        layer.updateFields()

        return layer

    @staticmethod
    def _create_isochrone_layer(
        name: str,
        crs: QgsCoordinateReferenceSystem,
    ) -> QgsVectorLayer:
        """Создать memory layer для изохрон."""
        uri = f"Polygon?crs={crs.authid()}"
        layer = QgsVectorLayer(uri, name, "memory")
        provider = layer.dataProvider()

        fields = QgsFields()
        fields.append(QgsField("id", QMetaType.Type.Int))
        fields.append(QgsField("profile", QMetaType.Type.QString))
        fields.append(QgsField("interval", QMetaType.Type.Int))
        fields.append(QgsField("unit", QMetaType.Type.QString))
        fields.append(QgsField("interval_label", QMetaType.Type.QString))
        fields.append(QgsField("area_ha", QMetaType.Type.Double))
        fields.append(QgsField("center_name", QMetaType.Type.QString))
        provider.addAttributes(fields)
        layer.updateFields()

        return layer

    # ------------------------------------------------------------------
    # Feature conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _routes_to_features(
        routes: list[RouteResult],
        fields: QgsFields,
    ) -> list[QgsFeature]:
        """Конвертировать RouteResult -> QgsFeature."""
        features: list[QgsFeature] = []
        for i, route in enumerate(routes):
            feat = QgsFeature(fields)
            feat.setGeometry(route.geometry)
            feat['id'] = i + 1
            feat['profile'] = route.profile
            feat['distance_m'] = round(route.distance_m, 1)
            feat['duration_s'] = round(route.duration_s, 1)
            feat['duration_min'] = round(route.duration_s / 60.0, 1)
            feat['origin_name'] = ''
            feat['dest_name'] = ''
            features.append(feat)
        return features

    @staticmethod
    def _isochrones_to_features(
        isochrones: list[IsochroneResult],
        fields: QgsFields,
    ) -> list[QgsFeature]:
        """Конвертировать IsochroneResult -> QgsFeature."""
        features: list[QgsFeature] = []
        for i, iso in enumerate(isochrones):
            feat = QgsFeature(fields)
            feat.setGeometry(iso.geometry)
            feat['id'] = i + 1
            feat['profile'] = iso.profile
            feat['interval'] = iso.interval
            feat['unit'] = iso.unit
            feat['interval_label'] = _format_interval_label(
                iso.interval, iso.unit
            )
            feat['area_ha'] = round(iso.area_sq_m / 10000.0, 2)
            feat['center_name'] = ''
            features.append(feat)
        return features

    # ------------------------------------------------------------------
    # Styles
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_route_style(layer: QgsVectorLayer) -> None:
        """Простой стиль для маршрутов: синяя линия 2px."""
        symbol = QgsLineSymbol()
        line_layer = QgsSimpleLineSymbolLayer()
        line_layer.setColor(QColor(30, 100, 220))
        line_layer.setWidth(0.8)
        symbol.changeSymbolLayer(0, line_layer)

        from qgis.core import QgsSingleSymbolRenderer
        renderer = QgsSingleSymbolRenderer(symbol)
        layer.setRenderer(renderer)

    @staticmethod
    def _apply_isochrone_style(
        layer: QgsVectorLayer,
        isochrones: list[IsochroneResult],
    ) -> None:
        """Градиентный стиль для изохрон: магма инвертированная, 60% прозрачность."""
        intervals = sorted(set(iso.interval for iso in isochrones))

        if not intervals:
            return

        # Построить ranges для QgsGraduatedSymbolRenderer
        ranges: list[QgsRendererRange] = []
        n = len(intervals)

        for idx, interval in enumerate(intervals):
            # Цвет из палитры
            color_idx = min(idx, len(_MAGMA_COLORS) - 1)
            if n > 1:
                color_idx = int(idx * (len(_MAGMA_COLORS) - 1) / (n - 1))
            color = QColor(_MAGMA_COLORS[color_idx])
            color.setAlpha(153)  # ~60% прозрачность

            # Символ
            symbol = QgsFillSymbol()
            fill_layer = QgsSimpleFillSymbolLayer()
            fill_layer.setColor(color)
            fill_layer.setStrokeColor(QColor(80, 80, 80, 180))
            fill_layer.setStrokeWidth(0.3)
            symbol.changeSymbolLayer(0, fill_layer)

            # Range
            lower = intervals[idx - 1] if idx > 0 else 0.0
            upper = float(interval)
            label = _format_interval_label(interval, isochrones[0].unit)

            rng = QgsRendererRange(lower, upper, symbol, label)
            ranges.append(rng)

        renderer = QgsGraduatedSymbolRenderer('interval', ranges)
        renderer.setMode(QgsGraduatedSymbolRenderer.Mode.Custom)
        layer.setRenderer(renderer)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _persist_layer(
        mem_layer: QgsVectorLayer,
        layer_name: str,
        gpkg_path: Optional[str],
    ) -> Optional[QgsVectorLayer]:
        """Записать memory layer в GPKG или вернуть как есть.

        Args:
            mem_layer: Исходный memory layer
            layer_name: Имя слоя в GPKG
            gpkg_path: Путь к GPKG (None = вернуть memory layer)

        Returns:
            QgsVectorLayer (из GPKG или memory)
        """
        if gpkg_path is None:
            return mem_layer

        try:
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = layer_name
            options.actionOnExistingFile = (
                QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
            )

            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                mem_layer,
                gpkg_path,
                QgsProject.instance().transformContext(),
                options,
            )

            if error[0] != QgsVectorFileWriter.WriterError.NoError:
                log_error(
                    f"Msm_41_5: Ошибка записи в GPKG: {error[1]}"
                )
                return mem_layer  # Fallback: вернуть memory layer

            # Загрузить из GPKG
            uri = f"{gpkg_path}|layername={layer_name}"
            gpkg_layer = QgsVectorLayer(uri, layer_name, "ogr")

            if gpkg_layer.isValid():
                # Перенести стиль с memory layer
                doc = mem_layer.exportNamedStyle()[0]
                if doc:
                    gpkg_layer.importNamedStyle(doc)
                log_info(f"Msm_41_5: Слой записан в GPKG: {layer_name}")
                return gpkg_layer

            log_warning(
                f"Msm_41_5: GPKG слой невалиден, возвращаем memory layer"
            )
            return mem_layer

        except Exception as exc:
            log_error(f"Msm_41_5 (_persist_layer): {exc}")
            return mem_layer

    @staticmethod
    def _add_to_project(layer: QgsVectorLayer) -> None:
        """Добавить слой в текущий проект QGIS."""
        project = QgsProject.instance()

        # Удалить существующий слой с тем же именем
        for existing in project.mapLayersByName(layer.name()):
            project.removeMapLayer(existing.id())

        project.addMapLayer(layer)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _simplify_layer(layer: QgsVectorLayer) -> QgsVectorLayer:
        """Упростить геометрии для QField (Douglas-Peucker 10м).

        Returns:
            Упрощенный memory layer (или исходный при ошибке)
        """
        try:
            result = processing.run("native:simplifygeometries", {
                'INPUT': layer,
                'METHOD': 0,       # Distance (Douglas-Peucker)
                'TOLERANCE': 10,   # 10 метров
                'OUTPUT': 'memory:',
            })
            simplified: QgsVectorLayer = result['OUTPUT']
            if simplified.isValid() and simplified.featureCount() > 0:
                simplified.setName(layer.name())
                log_info(
                    f"Msm_41_5: Геометрии упрощены для QField "
                    f"(tolerance=10м)"
                )
                return simplified
        except Exception as exc:
            log_warning(f"Msm_41_5: Упрощение не удалось: {exc}")

        return layer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_interval_label(interval: int, unit: str) -> str:
    """Форматировать подпись интервала для карты.

    Examples:
        (300, 'time')     -> '5 мин'
        (3600, 'time')    -> '60 мин'
        (500, 'distance') -> '500 м'
        (1500, 'distance') -> '1.5 км'
    """
    if unit == 'distance':
        if interval >= 1000:
            km = interval / 1000.0
            if km == int(km):
                return f"{int(km)} км"
            return f"{km:.1f} км"
        return f"{interval} м"

    # unit == 'time' (секунды)
    minutes = interval / 60.0
    if minutes == int(minutes):
        return f"{int(minutes)} мин"
    return f"{minutes:.1f} мин"
