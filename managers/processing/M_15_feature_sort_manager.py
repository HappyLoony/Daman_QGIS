# -*- coding: utf-8 -*-
"""
M_15: FeatureSortManager - Сортировка объектов слоя по КН
Пересоздаёт слой с новой последовательностью FID на основе поля "КН"
"""

from typing import Optional, Set
from qgis.core import (
    Qgis, QgsVectorLayer, QgsFeatureRequest, QgsFeature, QgsWkbTypes
)
from Daman_QGIS.utils import log_info, log_error, log_warning

__all__ = ['FeatureSortManager']


class FeatureSortManager:
    """
    Менеджер сортировки объектов слоя по полю "КН"

    Назначение:
        Пересоздание слоя с новой последовательностью FID (1, 2, 3, ...)
        на основе сортировки по полю "КН" (кадастровый номер)

    Применение:
        Только для чистовых слоёв с полем "КН":
        - L_2_1_1_ЗУ (выборка земельных участков)
        - L_2_1_2_ЗУ_+10м (выборка ЗУ с буфером 10м)
        - L_2_1_3_ОКС (выборка объектов капитального строительства)

    Особенности:
        - Silent operation: если поля "КН" нет - возвращает исходный слой без логов
        - Не добавляет слой в проект (делегирует caller'у)
        - Не применяет стили (делегирует layer_manager.add_layer())
        - Возвращает новый memory layer для дальнейшей обработки

    Архитектура:
        1. Проверка поля "КН" (silent если нет)
        2. Чтение объектов с сортировкой через QgsFeatureRequest
        3. Создание нового memory layer
        4. Добавление отсортированных объектов (FID = 1, 2, 3, ...)
        5. Возврат нового слоя (caller применяет стили и добавляет в проект)

    Пример использования:
        >>> from Daman_QGIS.managers import FeatureSortManager
        >>>
        >>> # Создание менеджера
        >>> sort_manager = FeatureSortManager()
        >>>
        >>> # Сортировка слоя (silent если нет "КН")
        >>> sorted_layer = sort_manager.sort_layer(original_layer)
        >>>
        >>> # Добавление в проект (применяет стили автоматически)
        >>> layer_manager.add_layer(sorted_layer)
        >>>
        >>> # Восстановление порядка слоёв по Base_layers.json
        >>> layer_manager.sort_all_layers()
    """

    def __init__(self) -> None:
        """Инициализация менеджера сортировки"""
        pass

    def sort_layer(self, layer: QgsVectorLayer) -> QgsVectorLayer:
        """
        Сортирует слой по полю "КН" через пересоздание

        Процесс:
            1. Проверка поля "КН" - если нет, возврат исходного слоя (silent)
            2. Чтение объектов с сортировкой: QgsFeatureRequest().addOrderBy("КН")
            3. Создание memory layer с той же структурой полей
            4. Добавление объектов в отсортированном порядке (новый FID = 1, 2, 3...)
            5. Возврат нового слоя БЕЗ добавления в проект

        ВАЖНО:
            - Возвращаемый слой НЕ имеет стилей (применяются через add_layer)
            - Возвращаемый слой НЕ добавлен в проект (добавляется через add_layer)
            - После вызова необходимо:
              1. layer_manager.add_layer(sorted_layer) - добавление + стили
              2. layer_manager.sort_all_layers() - восстановление порядка

        Args:
            layer: Исходный слой для сортировки

        Returns:
            QgsVectorLayer: Отсортированный слой (новый memory layer) или исходный если нет "КН"

        Example:
            >>> sorted_layer = sort_manager.sort_layer(zu_layer)
            >>> if sorted_layer != zu_layer:
            >>>     log_info("Слой был отсортирован по КН")
            >>> layer_manager.add_layer(sorted_layer)
        """
        # 1. Проверка наличия поля "КН" (silent если нет)
        field_names = [field.name() for field in layer.fields()]
        if "КН" not in field_names:
            return layer

        layer_name = layer.name()

        # 2. Чтение объектов с сортировкой по "КН"
        try:
            request = QgsFeatureRequest()
            request.addOrderBy("КН", ascending=True)

            sorted_features = []
            for feature in layer.getFeatures(request):
                sorted_features.append(QgsFeature(feature))

            feature_count = len(sorted_features)

        except Exception as e:
            log_error(f"M_15: Ошибка чтения объектов из слоя '{layer_name}': {e}")
            return layer

        # 2.1. Проверка на mixed geometry types (polygon + line в одном слое)
        # QGIS memory layer не поддерживает mixed geometry types
        if self._has_mixed_geometry_types(sorted_features):
            log_warning(
                f"M_15: Слой '{layer_name}' содержит смешанные типы геометрий "
                f"(polygon + line). Сортировка пропущена"
            )
            return layer

        # 3. Создание нового memory layer
        geom_type_str = self._get_geometry_type_string(layer.wkbType())
        crs = layer.crs()

        new_layer = QgsVectorLayer(
            f"{geom_type_str}?crs={crs.authid()}",
            layer_name,
            "memory"
        )

        if not new_layer.isValid():
            log_error(f"M_15: Не удалось создать memory layer для '{layer_name}'")
            return layer

        # 4. Копирование структуры полей
        provider = new_layer.dataProvider()
        provider.addAttributes(layer.fields().toList())
        new_layer.updateFields()

        # 5. Добавление отсортированных объектов (новый FID будет 1, 2, 3, ...)
        # Используем startEditing/addFeature/commitChanges - стабильный путь,
        # который корректно работает с features из любого провайдера (GeoPackage, memory)
        try:
            new_layer.startEditing()

            for feat in sorted_features:
                new_feat = QgsFeature(new_layer.fields())
                new_feat.setGeometry(feat.geometry())
                for field in new_layer.fields():
                    src_idx = feat.fields().indexFromName(field.name())
                    if src_idx >= 0:
                        new_feat.setAttribute(field.name(), feat.attribute(src_idx))
                new_layer.addFeature(new_feat)

            if not new_layer.commitChanges():
                log_error(f"M_15: Ошибка коммита для '{layer_name}': {new_layer.commitErrors()}")
                new_layer.rollBack()
                return layer

            new_layer.updateExtents()
            log_info(f"M_15: Создан отсортированный слой '{layer_name}' ({feature_count} объектов)")

        except Exception as e:
            log_error(f"M_15: Ошибка при добавлении объектов: {e}")
            if new_layer.isEditable():
                new_layer.rollBack()
            return layer

        # 6. Возврат нового слоя (БЕЗ стилей и БЕЗ добавления в проект)
        return new_layer

    def _has_mixed_geometry_types(self, features: list) -> bool:
        """
        Проверка наличия смешанных типов геометрий (например polygon + line).

        QGIS memory layer не поддерживает mixed geometry types --
        commitChanges() отклоняет features с несовместимым типом.
        Различие single/multi (Polygon vs MultiPolygon) НЕ считается mixed.

        Args:
            features: Список QgsFeature для проверки

        Returns:
            True если обнаружены несовместимые типы геометрий
        """
        geometry_types: Set[int] = set()

        for feat in features:
            geom = feat.geometry()
            if geom and not geom.isNull():
                # geometryType() возвращает базовый тип (Point/Line/Polygon)
                # без различия single/multi
                geometry_types.add(QgsWkbTypes.geometryType(geom.wkbType()))

        if len(geometry_types) > 1:
            type_names = []
            for gt in geometry_types:
                if gt == Qgis.GeometryType.Point:
                    type_names.append("Point")
                elif gt == Qgis.GeometryType.Line:
                    type_names.append("Line")
                elif gt == Qgis.GeometryType.Polygon:
                    type_names.append("Polygon")
                else:
                    type_names.append(f"Unknown({gt})")
            log_warning(f"M_15: Обнаружены типы геометрий: {', '.join(type_names)}")
            return True

        return False

    def _get_geometry_type_string(self, wkb_type: QgsWkbTypes.Type) -> str:  # type: ignore[name-defined]
        """
        Преобразование WKB типа в строковое представление для memory layer

        Args:
            wkb_type: WKB тип геометрии

        Returns:
            str: Строковое представление ("Point", "LineString", "Polygon", etc.)
        """
        geom_type = QgsWkbTypes.geometryType(wkb_type)

        if geom_type == Qgis.GeometryType.Point:
            if QgsWkbTypes.isMultiType(wkb_type):
                return "MultiPoint"
            return "Point"

        elif geom_type == Qgis.GeometryType.Line:
            if QgsWkbTypes.isMultiType(wkb_type):
                return "MultiLineString"
            return "LineString"

        elif geom_type == Qgis.GeometryType.Polygon:
            if QgsWkbTypes.isMultiType(wkb_type):
                return "MultiPolygon"
            return "Polygon"

        else:
            # Fallback для неизвестных типов
            return "Polygon"
