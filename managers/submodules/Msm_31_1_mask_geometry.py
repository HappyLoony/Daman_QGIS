# -*- coding: utf-8 -*-
"""
Msm_31_1_MaskGeometry - Создание и управление геометрией маски.

Отвечает за:
- Получение геометрий из слоя-источника
- Объединение полигонов (QgsGeometry.combine)
- Применение буфера
- Создание memory layer
- Применение QML стиля
"""

import os
from typing import Optional

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsLayerTreeLayer,
    QgsCoordinateReferenceSystem,
    QgsMapToPixelSimplifier,
    QgsRectangle,
)

from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.constants import BUFFER_SEGMENTS


class MaskGeometryBuilder:
    """Построитель геометрии маски."""

    # Относительный путь к QML стилю (от корня плагина)
    QML_STYLE_RELATIVE = "data/styles/mask_inverted_polygon.qml"

    # Tolerance для упрощения в пикселях (как в AEAG Mask)
    DEFAULT_SIMPLIFY_TOLERANCE = 1.0

    def __init__(self, plugin_dir: Optional[str] = None):
        """
        Инициализация построителя геометрии.

        Args:
            plugin_dir: Путь к директории плагина (для поиска QML стиля)
        """
        self._plugin_dir = plugin_dir
        # Кэш упрощённых геометрий: {tolerance: (simplified_geom, bbox)}
        self._simplified_cache: dict[float, tuple[QgsGeometry, QgsRectangle]] = {}
        # Оригинальная геометрия маски (без упрощения)
        self._original_geometry: Optional[QgsGeometry] = None
        # Включено ли упрощение
        self._do_simplify: bool = True
        # Tolerance в пикселях
        self._simplify_tolerance: float = self.DEFAULT_SIMPLIFY_TOLERANCE

    def set_plugin_dir(self, plugin_dir: str) -> None:
        """Установить путь к директории плагина."""
        self._plugin_dir = plugin_dir

    def create_mask_layer(
        self,
        source_layer: QgsVectorLayer,
        buffer_m: float = 0.0,
        layer_name: str = "L_0_0_0_Mask"
    ) -> Optional[QgsVectorLayer]:
        """
        Создать слой маски из слоя-источника.

        Args:
            source_layer: Слой с границами (L_1_1_X)
            buffer_m: Буфер в метрах (0 = без буфера)
            layer_name: Имя создаваемого слоя

        Returns:
            QgsVectorLayer (memory) или None при ошибке
        """
        if source_layer is None or not source_layer.isValid():
            log_error("Msm_31_1: Слой-источник недействителен")
            return None

        # 1. Объединить все геометрии
        combined_geom = self._combine_geometries(source_layer)
        if combined_geom is None or combined_geom.isEmpty():
            log_error("Msm_31_1: Не удалось объединить геометрии")
            return None

        # 2. Применить буфер если нужно
        if buffer_m != 0:
            combined_geom = self._apply_buffer(combined_geom, buffer_m)
            if combined_geom is None or combined_geom.isEmpty():
                log_error("Msm_31_1: Ошибка применения буфера")
                return None

        # 3. Создать memory layer
        crs = source_layer.crs()
        mask_layer = self._create_memory_layer(combined_geom, crs, layer_name)
        if mask_layer is None:
            log_error("Msm_31_1: Не удалось создать memory layer")
            return None

        # 4. Применить QML стиль
        if not self._apply_style(mask_layer):
            log_warning("Msm_31_1: Не удалось применить QML стиль")

        # 5. Сохранить оригинальную геометрию для упрощения
        self.set_original_geometry(combined_geom)

        log_info(f"Msm_31_1: Слой маски создан: {layer_name}")
        return mask_layer

    def _combine_geometries(
        self,
        layer: QgsVectorLayer
    ) -> Optional[QgsGeometry]:
        """
        Объединить все геометрии слоя в одну.

        Args:
            layer: Векторный слой с полигонами

        Returns:
            Объединённая геометрия или None
        """
        combined: Optional[QgsGeometry] = None

        for feature in layer.getFeatures():
            geom = feature.geometry()
            if geom is None or geom.isEmpty():
                continue

            if combined is None:
                combined = QgsGeometry(geom)
            else:
                combined = combined.combine(geom)

        return combined

    def _apply_buffer(
        self,
        geom: QgsGeometry,
        buffer_m: float
    ) -> QgsGeometry:
        """
        Применить буфер к геометрии.

        Args:
            geom: Исходная геометрия
            buffer_m: Размер буфера в метрах (может быть отрицательным)

        Returns:
            Геометрия с буфером
        """
        return geom.buffer(buffer_m, BUFFER_SEGMENTS)

    def _create_memory_layer(
        self,
        geom: QgsGeometry,
        crs: QgsCoordinateReferenceSystem,
        layer_name: str
    ) -> Optional[QgsVectorLayer]:
        """
        Создать memory layer с геометрией.

        Args:
            geom: Геометрия для слоя
            crs: Система координат
            layer_name: Имя слоя

        Returns:
            QgsVectorLayer или None
        """
        try:
            layer = QgsVectorLayer(
                f"MultiPolygon?crs={crs.authid()}",
                layer_name,
                "memory"
            )

            if not layer.isValid():
                log_error("Msm_31_1: Созданный memory layer недействителен")
                return None

            pr = layer.dataProvider()
            feat = QgsFeature()
            feat.setGeometry(geom)
            pr.addFeatures([feat])
            layer.updateExtents()

            return layer

        except Exception as e:
            log_error(f"Msm_31_1: Ошибка создания memory layer: {e}")
            return None

    def _apply_style(self, layer: QgsVectorLayer) -> bool:
        """
        Применить QML стиль инвертированного полигона.

        Args:
            layer: Слой маски

        Returns:
            True если стиль применён
        """
        if self._plugin_dir is None:
            log_warning("Msm_31_1: Путь к плагину не установлен, пропуск стиля")
            return False

        qml_path = os.path.join(self._plugin_dir, self.QML_STYLE_RELATIVE)

        if not os.path.exists(qml_path):
            log_warning(f"Msm_31_1: QML стиль не найден: {qml_path}")
            return False

        try:
            result = layer.loadNamedStyle(qml_path)
            if result[1]:  # result[1] содержит сообщение об ошибке если есть
                log_warning(f"Msm_31_1: Ошибка загрузки стиля: {result[1]}")
                return False

            layer.triggerRepaint()
            return True

        except Exception as e:
            log_error(f"Msm_31_1: Исключение при загрузке стиля: {e}")
            return False

    def add_to_project_top(self, layer: QgsVectorLayer) -> None:
        """
        Добавить слой в проект на верхний уровень дерева слоёв.

        Args:
            layer: Слой для добавления
        """
        # Добавить слой без автодобавления в дерево
        QgsProject.instance().addMapLayer(layer, False)

        # Вставить на верх дерева слоёв
        root = QgsProject.instance().layerTreeRoot()
        root.insertChildNode(0, QgsLayerTreeLayer(layer))

        log_info(f"Msm_31_1: Слой {layer.name()} добавлен в проект на верхний уровень")

    def update_geometry(
        self,
        mask_layer: QgsVectorLayer,
        new_geom: QgsGeometry
    ) -> bool:
        """
        Обновить геометрию существующего слоя маски.

        Args:
            mask_layer: Слой маски
            new_geom: Новая геометрия

        Returns:
            True если обновлено
        """
        if mask_layer is None or not mask_layer.isValid():
            log_error("Msm_31_1: Слой маски недействителен")
            return False

        try:
            pr = mask_layer.dataProvider()

            # Получить ID первого feature
            fid = None
            for f in pr.getFeatures():
                fid = f.id()
                break

            # Очистить и добавить новую геометрию
            pr.truncate()

            feat = QgsFeature()
            if fid is not None:
                feat.setId(fid)
            feat.setGeometry(new_geom)
            pr.addFeatures([feat])

            mask_layer.updateExtents()
            mask_layer.triggerRepaint()

            # Сохранить новую оригинальную геометрию и очистить кэш
            self.set_original_geometry(new_geom)

            log_info("Msm_31_1: Геометрия маски обновлена")
            return True

        except Exception as e:
            log_error(f"Msm_31_1: Ошибка обновления геометрии: {e}")
            return False

    def get_combined_geometry(
        self,
        source_layer: QgsVectorLayer,
        buffer_m: float = 0.0
    ) -> Optional[QgsGeometry]:
        """
        Получить объединённую геометрию из слоя с буфером.

        Args:
            source_layer: Слой-источник
            buffer_m: Буфер в метрах

        Returns:
            Объединённая геометрия или None
        """
        if source_layer is None or not source_layer.isValid():
            return None

        combined = self._combine_geometries(source_layer)
        if combined is None:
            return None

        if buffer_m != 0:
            combined = self._apply_buffer(combined, buffer_m)

        return combined

    def clear_cache(self) -> None:
        """Очистить кэш упрощённых геометрий."""
        self._simplified_cache.clear()

    # ========================================================================
    # Упрощение геометрии (QgsMapToPixelSimplifier)
    # ========================================================================

    def set_simplify_enabled(self, enabled: bool) -> None:
        """
        Включить/выключить упрощение геометрии.

        Args:
            enabled: True для включения упрощения
        """
        self._do_simplify = enabled
        if not enabled:
            self.clear_cache()

    def set_simplify_tolerance(self, tolerance_pixels: float) -> None:
        """
        Установить tolerance для упрощения.

        Args:
            tolerance_pixels: Tolerance в пикселях (по умолчанию 1.0)
        """
        if tolerance_pixels != self._simplify_tolerance:
            self._simplify_tolerance = tolerance_pixels
            self.clear_cache()

    def get_simplified_geometry(
        self,
        map_units_per_pixel: float
    ) -> Optional[QgsGeometry]:
        """
        Получить упрощённую геометрию маски для текущего масштаба.

        Использует QgsMapToPixelSimplifier для оптимизации производительности
        при разных масштабах. Результат кэшируется по tolerance.

        Алгоритм (как в AEAG Mask plugin):
        1. Вычисляем tolerance в единицах карты: tolerance_pixels * map_units_per_pixel
        2. Проверяем кэш по этому tolerance
        3. Если нет в кэше - упрощаем и сохраняем

        Args:
            map_units_per_pixel: Единиц карты на пиксель (из MapSettings)

        Returns:
            Упрощённая геометрия или оригинальная если упрощение отключено
        """
        if self._original_geometry is None:
            return None

        # Упрощение отключено - возвращаем оригинал
        if not self._do_simplify:
            return QgsGeometry(self._original_geometry)

        # Вычисляем tolerance в единицах карты
        tolerance = self._simplify_tolerance * map_units_per_pixel

        # Проверяем кэш
        if tolerance in self._simplified_cache:
            cached_geom, _ = self._simplified_cache[tolerance]
            return QgsGeometry(cached_geom)

        # Упрощаем геометрию
        simplified = self._simplify_geometry(self._original_geometry, tolerance)

        # Кэшируем результат
        self._simplified_cache[tolerance] = (simplified, simplified.boundingBox())

        log_info(f"Msm_31_1: Геометрия упрощена (tolerance={tolerance:.2f}, cache_size={len(self._simplified_cache)})")

        return QgsGeometry(simplified)

    def _simplify_geometry(
        self,
        geom: QgsGeometry,
        tolerance: float
    ) -> QgsGeometry:
        """
        Упростить геометрию с помощью QgsMapToPixelSimplifier.

        Args:
            geom: Исходная геометрия
            tolerance: Tolerance в единицах карты

        Returns:
            Упрощённая геометрия
        """
        simplifier = QgsMapToPixelSimplifier(
            QgsMapToPixelSimplifier.SimplifyFlag.SimplifyGeometry,
            tolerance
        )

        simplified = simplifier.simplify(geom)

        # Проверяем валидность упрощённой геометрии
        if not simplified.isGeosValid():
            # Исправляем невалидную геометрию через buffer(0)
            simplified = simplified.buffer(0.0, 1)

        return simplified

    def set_original_geometry(self, geom: QgsGeometry) -> None:
        """
        Установить оригинальную геометрию маски.

        Вызывается при создании/обновлении маски.
        Очищает кэш упрощённых геометрий.

        Args:
            geom: Оригинальная геометрия маски
        """
        self._original_geometry = QgsGeometry(geom) if geom else None
        self.clear_cache()

    def get_original_geometry(self) -> Optional[QgsGeometry]:
        """
        Получить оригинальную (неупрощённую) геометрию маски.

        Returns:
            QgsGeometry или None
        """
        if self._original_geometry is None:
            return None
        return QgsGeometry(self._original_geometry)
