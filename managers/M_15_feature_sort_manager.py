# -*- coding: utf-8 -*-
"""
M_15: FeatureSortManager - Сортировка объектов слоя по КН
Пересоздаёт слой с новой последовательностью FID на основе поля "КН"
"""

from typing import Optional
from qgis.core import (
    QgsVectorLayer, QgsFeatureRequest, QgsFeature,
    QgsFields, QgsWkbTypes
)
from Daman_QGIS.utils import log_info, log_error


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
        log_info(f"M_15: Начало сортировки слоя '{layer_name}' по полю 'КН'")

        # 2. Чтение объектов с сортировкой по "КН"
        try:
            request = QgsFeatureRequest()
            request.addOrderBy("КН", ascending=True)

            sorted_features = []
            for feature in layer.getFeatures(request):
                sorted_features.append(QgsFeature(feature))

            feature_count = len(sorted_features)
            log_info(f"M_15: Прочитано {feature_count} объектов из слоя '{layer_name}'")

        except Exception as e:
            log_error(f"M_15: Ошибка чтения объектов из слоя '{layer_name}': {e}")
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
        try:
            # Важно: не передаём FID - он будет назначен автоматически
            success, added_features = provider.addFeatures(sorted_features)

            if not success:
                log_error(f"M_15: Ошибка добавления объектов в новый слой '{layer_name}'")
                return layer

            new_layer.updateExtents()
            log_info(f"M_15: Создан отсортированный слой '{layer_name}' ({feature_count} объектов)")

        except Exception as e:
            log_error(f"M_15: Ошибка при добавлении объектов: {e}")
            return layer

        # 6. Возврат нового слоя (БЕЗ стилей и БЕЗ добавления в проект)
        log_info(f"M_15: Сортировка завершена для слоя '{layer_name}'")
        return new_layer

    def _get_geometry_type_string(self, wkb_type: QgsWkbTypes.Type) -> str:  # type: ignore[name-defined]
        """
        Преобразование WKB типа в строковое представление для memory layer

        Args:
            wkb_type: WKB тип геометрии

        Returns:
            str: Строковое представление ("Point", "LineString", "Polygon", etc.)
        """
        geom_type = QgsWkbTypes.geometryType(wkb_type)

        if geom_type == QgsWkbTypes.PointGeometry:
            if QgsWkbTypes.isMultiType(wkb_type):
                return "MultiPoint"
            return "Point"

        elif geom_type == QgsWkbTypes.LineGeometry:
            if QgsWkbTypes.isMultiType(wkb_type):
                return "MultiLineString"
            return "LineString"

        elif geom_type == QgsWkbTypes.PolygonGeometry:
            if QgsWkbTypes.isMultiType(wkb_type):
                return "MultiPolygon"
            return "Polygon"

        else:
            # Fallback для неизвестных типов
            return "Polygon"
