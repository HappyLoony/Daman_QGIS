# -*- coding: utf-8 -*-
"""
Fsm_2_1_5: Процессор геометрических операций для выборки
Обработка геометрий, трансформации СК, проверка пересечений
"""

from typing import Optional, Tuple
from qgis.core import (
    QgsVectorLayer, QgsGeometry, QgsCoordinateTransform,
    QgsProject, QgsFeature
)

from Daman_QGIS.utils import log_info, log_warning, log_debug
from Daman_QGIS.managers import CoordinatePrecisionManager


class Fsm_2_1_5_GeometryProcessor:
    """Процессор геометрических операций для выборки"""

    @staticmethod
    def get_boundaries_geometry(boundaries_layer: QgsVectorLayer) -> Optional[QgsGeometry]:
        """Получение объединенной геометрии границ

        Args:
            boundaries_layer: Слой границ

        Returns:
            QgsGeometry: Объединенная геометрия или None
        """
        geometries = []

        for feature in boundaries_layer.getFeatures():
            if feature.hasGeometry():
                geom = feature.geometry()
                if geom and not geom.isNull() and not geom.isEmpty():
                    geometries.append(geom)

        if not geometries:
            log_warning(f"Fsm_2_1_5: Слой '{boundaries_layer.name()}' не содержит валидных геометрий")
            return None

        log_debug(f"Fsm_2_1_5: Слой '{boundaries_layer.name()}': найдено {len(geometries)} валидных геометрий")

        # Объединяем все геометрии
        united = QgsGeometry.unaryUnion(geometries)
        if united and not united.isNull() and not united.isEmpty():
            return united
        else:
            log_warning(f"Fsm_2_1_5: unaryUnion вернул пустую или невалидную геометрию для слоя '{boundaries_layer.name()}'")
            return None

    @staticmethod
    def create_coordinate_transforms(source_layer: QgsVectorLayer,
                                     boundaries_layer: QgsVectorLayer) -> Tuple[Optional[QgsCoordinateTransform],
                                                                                 Optional[QgsCoordinateTransform]]:
        """Создание трансформаций систем координат

        ВАЖНО: Всегда используем project_crs как единственный источник истины для целевой СК.
        Не доверяем boundaries_layer.crs() - он может быть неправильно импортирован.

        Args:
            source_layer: Исходный слой (WFS в EPSG:3857)
            boundaries_layer: Слой границ (должен быть в project_crs, но может быть неверным)

        Returns:
            tuple: (transform_to_project, transform_for_intersection)
                - transform_to_project: для преобразования результата в СК проекта
                - transform_for_intersection: для проверки пересечения (ТАКЖЕ в СК проекта!)
        """
        project_crs = QgsProject.instance().crs()
        source_crs = source_layer.crs()
        boundaries_crs = boundaries_layer.crs()

        # Логируем CRS для диагностики
        log_debug(f"Fsm_2_1_5: source_crs={source_crs.authid()}, boundaries_crs={boundaries_crs.authid()}, project_crs={project_crs.authid()}")

        # Предупреждение если boundaries_crs отличается от project_crs
        if boundaries_crs.authid() != project_crs.authid():
            log_warning(f"Fsm_2_1_5: ВНИМАНИЕ! CRS слоя границ ({boundaries_crs.authid()}) отличается от CRS проекта ({project_crs.authid()}). "
                       f"Используем project_crs как источник истины.")

        # Трансформация в СК проекта (для результирующего слоя)
        transform_to_project = None
        if source_crs != project_crs:
            transform_to_project = QgsCoordinateTransform(source_crs, project_crs, QgsProject.instance())
            log_debug(f"Fsm_2_1_5: Создан трансформер для результата: {source_crs.authid()} → {project_crs.authid()}")

        # Трансформация для проверки пересечения - ТАКЖЕ в project_crs!
        # КРИТИЧНО: Используем project_crs, а НЕ boundaries_crs.
        # Геометрия границ должна быть в project_crs, поэтому проверку пересечения
        # выполняем также в project_crs для корректного сравнения.
        transform_for_intersection = None
        if source_crs != project_crs:
            transform_for_intersection = QgsCoordinateTransform(source_crs, project_crs, QgsProject.instance())
            log_debug(f"Fsm_2_1_5: Создан трансформер для проверки пересечения: {source_crs.authid()} → {project_crs.authid()}")

        return transform_to_project, transform_for_intersection

    @staticmethod
    def recheck_intersection_after_rounding(layer: QgsVectorLayer, boundaries_geom: QgsGeometry) -> int:
        """Повторная проверка пересечений после округления координат

        Удаляет объекты, которые после округления координат перестали пересекать границы.
        Использует два метода проверки с консервативной валидацией (удаляет только если оба метода согласны).

        Args:
            layer: Слой для проверки
            boundaries_geom: Объединённая геометрия границ

        Returns:
            int: Количество удалённых объектов
        """
        log_info("Fsm_2_1_5: ЭТАП 3: ПОВТОРНАЯ ПРОВЕРКА ПЕРЕСЕЧЕНИЙ (после округления)")

        total_features = layer.featureCount()
        log_info(f"Fsm_2_1_5: Всего объектов до повторной проверки: {total_features}")

        if total_features == 0:
            log_info("Fsm_2_1_5: Слой пуст - пропускаем повторную проверку")
            return 0

        # Два независимых метода проверки
        method_a_remove_ids = []  # intersects AND NOT touches
        method_b_remove_ids = []  # intersection.area > 0

        for feature in layer.getFeatures():
            feature_id = feature.id()
            geom = feature.geometry()

            if not geom or geom.isNull():
                continue

            # МЕТОД A: intersects AND NOT touches (строгое пересечение)
            # Логика: если НЕ пересекает ИЛИ только касается - удаляем
            if not geom.intersects(boundaries_geom) or geom.touches(boundaries_geom):
                method_a_remove_ids.append(feature_id)

            # МЕТОД B: intersection.area > 0 (проверка через площадь пересечения)
            # Логика: если площадь пересечения = 0 - удаляем
            try:
                intersection = geom.intersection(boundaries_geom)
                if intersection.isNull() or intersection.isEmpty() or intersection.area() <= 0:
                    method_b_remove_ids.append(feature_id)
            except Exception as e:
                # Ошибка при вычислении intersection - пропускаем
                log_warning(f"Fsm_2_1_5: Ошибка при проверке пересечения для feature {feature_id}: {str(e)}")

        # Логируем результаты обоих методов
        log_debug(f"Fsm_2_1_5: Метод A (intersects AND NOT touches): {len(method_a_remove_ids)} участков для удаления")
        log_debug(f"Fsm_2_1_5: Метод B (intersection.area > 0): {len(method_b_remove_ids)} участков для удаления")

        # Находим различия между методами
        only_in_a = set(method_a_remove_ids) - set(method_b_remove_ids)
        only_in_b = set(method_b_remove_ids) - set(method_a_remove_ids)
        in_both = set(method_a_remove_ids) & set(method_b_remove_ids)

        log_debug(f"Fsm_2_1_5: Совпадение методов: {len(in_both)} участков")
        if only_in_a:
            log_debug(f"Fsm_2_1_5: Только метод A: {len(only_in_a)} участков (IDs: {list(only_in_a)[:10]}...)")
        if only_in_b:
            log_debug(f"Fsm_2_1_5: Только метод B: {len(only_in_b)} участков (IDs: {list(only_in_b)[:10]}...)")

        # ИСПОЛЬЗУЕМ ПЕРЕСЕЧЕНИЕ ОБОИХ МЕТОДОВ (удаляем только если ОБА метода согласны)
        # Консервативная стратегия: если методы расходятся - оставляем объект (безопаснее)
        features_to_remove = list(set(method_a_remove_ids) & set(method_b_remove_ids))

        # Логируем разницу между консервативной (AND) и агрессивной (OR) стратегиями
        if only_in_a or only_in_b:
            would_remove_with_or = len(set(method_a_remove_ids) | set(method_b_remove_ids))
            actually_removing = len(features_to_remove)
            log_info(f"Fsm_2_1_5: Консервативная стратегия (AND): удаляем {actually_removing} участков (агрессивная OR удалила бы {would_remove_with_or})")

        if features_to_remove:
            log_info(f"Fsm_2_1_5: ИТОГО к удалению: {len(features_to_remove)} участков из {total_features}")

            # Удаляем участки
            layer.startEditing()
            layer.deleteFeatures(features_to_remove)
            layer.commitChanges()

            remaining = layer.featureCount()
            log_info(f"Fsm_2_1_5: После повторной проверки: осталось {remaining} участков (удалено {len(features_to_remove)})")
            return len(features_to_remove)
        else:
            log_info("Fsm_2_1_5: Все участки прошли повторную проверку - удалений не требуется")
            return 0
