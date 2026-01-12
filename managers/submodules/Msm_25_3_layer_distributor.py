# -*- coding: utf-8 -*-
"""
Msm_25_3 - Распределитель объектов по целевым слоям

Основная логика распределения объектов из исходного слоя
в целевые слои на основе классификации.

Использует:
- Msm_25_0 для создания слоёв и сохранения в GPKG
- Msm_25_1 для классификации по категориям
- Msm_25_2 для классификации по правам

Перенесено из Fsm_2_3_1 и Fsm_2_3_2
"""

import os
from typing import Dict, List, Optional, Tuple, Any, Callable

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature,
    QgsVectorFileWriter
)

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers import get_project_structure_manager

from .Msm_25_0_fills_utils import (
    create_memory_layer, save_layer_to_gpkg,
    add_layer_to_project, get_gpkg_path
)
from .Msm_25_1_category_classifier import Msm_25_1_CategoryClassifier
from .Msm_25_2_rights_classifier import Msm_25_2_RightsClassifier


class Msm_25_3_LayerDistributor:
    """Распределитель объектов по целевым слоям"""

    def __init__(self, layer_manager=None):
        """
        Инициализация распределителя

        Args:
            layer_manager: LayerManager для добавления слоёв в проект
        """
        self.layer_manager = layer_manager
        self.category_classifier = Msm_25_1_CategoryClassifier()
        self.rights_classifier = Msm_25_2_RightsClassifier()

    def distribute_by_categories(
        self,
        source_layer: QgsVectorLayer
    ) -> Dict[str, Any]:
        """
        Распределение объектов по категориям земель

        Args:
            source_layer: Исходный слой с объектами

        Returns:
            Dict с результатами:
                - success: bool
                - layers_created: List[str] - имена созданных слоёв
                - feature_counts: Dict[str, int] - количество объектов по слоям
                - errors: List[str] - ошибки
        """
        result = {
            "success": False,
            "layers_created": [],
            "feature_counts": {},
            "errors": []
        }

        try:
            # Проверяем наличие поля категории
            field_name = self.category_classifier.get_field_name()
            if source_layer.fields().indexFromName(field_name) == -1:
                result["errors"].append(f"В слое отсутствует поле '{field_name}'")
                return result

            # Словари для слоёв и счётчиков
            target_layers: Dict[str, QgsVectorLayer] = {}
            feature_counts: Dict[str, int] = {}

            total_features = source_layer.featureCount()
            processed = 0

            log_info(f"Msm_25_3: Начало распределения по категориям ({total_features} объектов)")

            # Обрабатываем каждый объект
            for feature in source_layer.getFeatures():
                if not feature.hasGeometry():
                    continue

                category_value = feature.attribute(field_name)
                target_layer_name = self.category_classifier.classify_feature(category_value)

                # Добавляем объект в целевой слой
                self._add_feature_to_layer(
                    source_layer=source_layer,
                    feature=feature,
                    target_layer_name=target_layer_name,
                    target_layers=target_layers,
                    feature_counts=feature_counts
                )

                processed += 1

            # Финализируем слои
            created_layers = self._finalize_layers(target_layers, feature_counts)

            result["success"] = len(created_layers) > 0
            result["layers_created"] = created_layers
            result["feature_counts"] = feature_counts

            log_info(f"Msm_25_3: Распределение по категориям завершено. "
                    f"Создано {len(created_layers)} слоёв, обработано {processed} объектов")

        except Exception as e:
            error_msg = f"Ошибка распределения по категориям: {e}"
            log_error(f"Msm_25_3: {error_msg}")
            result["errors"].append(error_msg)

        return result

    def distribute_by_rights(
        self,
        source_layer: QgsVectorLayer,
        unknown_handler: Optional[Callable[[QgsFeature, int, int], Optional[str]]] = None
    ) -> Dict[str, Any]:
        """
        Распределение объектов по правам на землю

        Args:
            source_layer: Исходный слой с объектами
            unknown_handler: Callback для обработки неопознанных объектов
                            Сигнатура: (feature, index, total) -> Optional[layer_name]
                            Возвращает None для пропуска (в слой "Свед_нет")

        Returns:
            Dict с результатами:
                - success: bool
                - layers_created: List[str] - имена созданных слоёв
                - feature_counts: Dict[str, int] - количество объектов по слоям
                - unknown_count: int - количество неопознанных объектов
                - errors: List[str] - ошибки
        """
        result = {
            "success": False,
            "layers_created": [],
            "feature_counts": {},
            "unknown_count": 0,
            "errors": []
        }

        try:
            # Проверяем наличие необходимых полей
            rights_field, owners_field, encumbrances_field = self.rights_classifier.get_field_names()
            required_fields = [rights_field, owners_field]

            for field_name in required_fields:
                if source_layer.fields().indexFromName(field_name) == -1:
                    result["errors"].append(f"В слое отсутствует поле '{field_name}'")
                    return result

            # Словари для слоёв и счётчиков
            target_layers: Dict[str, QgsVectorLayer] = {}
            feature_counts: Dict[str, int] = {}
            unknown_features: List[QgsFeature] = []

            total_features = source_layer.featureCount()
            processed = 0

            log_info(f"Msm_25_3: Начало распределения по правам ({total_features} объектов)")

            # Первый проход - автоматическая классификация
            for feature in source_layer.getFeatures():
                if not feature.hasGeometry():
                    continue

                rights_value = feature.attribute(rights_field)
                owners_value = feature.attribute(owners_field)
                encumbrances_value = feature.attribute(encumbrances_field) if source_layer.fields().indexFromName(encumbrances_field) != -1 else None

                # Классифицируем объект
                primary_layer, additional_layers = self.rights_classifier.classify_feature(
                    rights_value, owners_value, encumbrances_value
                )

                if primary_layer is None:
                    # Не удалось классифицировать - в список неопознанных
                    unknown_features.append(feature)
                else:
                    # Добавляем в основной слой
                    self._add_feature_to_layer(
                        source_layer=source_layer,
                        feature=feature,
                        target_layer_name=primary_layer,
                        target_layers=target_layers,
                        feature_counts=feature_counts
                    )

                    # Дублируем в дополнительные слои (обременения)
                    for additional_layer_name in additional_layers:
                        self._add_feature_to_layer(
                            source_layer=source_layer,
                            feature=feature,
                            target_layer_name=additional_layer_name,
                            target_layers=target_layers,
                            feature_counts=feature_counts
                        )

                processed += 1

            # Обработка неопознанных объектов
            result["unknown_count"] = len(unknown_features)

            if unknown_features:
                log_info(f"Msm_25_3: Обнаружено {len(unknown_features)} неопознанных объектов")

                skip_all = False
                for idx, feature in enumerate(unknown_features, start=1):
                    target_layer_name = None

                    if not skip_all and unknown_handler:
                        # Вызываем handler для определения слоя
                        handler_result = unknown_handler(feature, idx, len(unknown_features))

                        if handler_result == "__SKIP_ALL__":
                            skip_all = True
                            target_layer_name = self.rights_classifier.UNKNOWN_LAYER
                        elif handler_result:
                            target_layer_name = handler_result
                        else:
                            target_layer_name = self.rights_classifier.UNKNOWN_LAYER
                    else:
                        target_layer_name = self.rights_classifier.UNKNOWN_LAYER

                    self._add_feature_to_layer(
                        source_layer=source_layer,
                        feature=feature,
                        target_layer_name=target_layer_name,
                        target_layers=target_layers,
                        feature_counts=feature_counts
                    )

            # Финализируем слои
            created_layers = self._finalize_layers(target_layers, feature_counts)

            result["success"] = len(created_layers) > 0
            result["layers_created"] = created_layers
            result["feature_counts"] = feature_counts

            log_info(f"Msm_25_3: Распределение по правам завершено. "
                    f"Создано {len(created_layers)} слоёв, обработано {processed} объектов")

        except Exception as e:
            error_msg = f"Ошибка распределения по правам: {e}"
            log_error(f"Msm_25_3: {error_msg}")
            result["errors"].append(error_msg)

        return result

    def _add_feature_to_layer(
        self,
        source_layer: QgsVectorLayer,
        feature: QgsFeature,
        target_layer_name: str,
        target_layers: Dict[str, QgsVectorLayer],
        feature_counts: Dict[str, int]
    ) -> None:
        """
        Добавление объекта в целевой слой

        Args:
            source_layer: Исходный слой (для копирования структуры)
            feature: Объект для добавления
            target_layer_name: Имя целевого слоя
            target_layers: Словарь целевых слоёв
            feature_counts: Словарь счётчиков
        """
        # Создаём слой если не существует
        if target_layer_name not in target_layers:
            new_layer = create_memory_layer(source_layer, target_layer_name)
            if new_layer:
                target_layers[target_layer_name] = new_layer
                feature_counts[target_layer_name] = 0
            else:
                log_error(f"Msm_25_3: Не удалось создать слой {target_layer_name}")
                return

        # Добавляем объект
        target_layer = target_layers[target_layer_name]
        if target_layer:
            new_feature = QgsFeature(target_layer.fields())
            new_feature.setGeometry(feature.geometry())
            new_feature.setAttributes(feature.attributes())
            target_layer.addFeature(new_feature)
            feature_counts[target_layer_name] += 1

    def _finalize_layers(
        self,
        target_layers: Dict[str, QgsVectorLayer],
        feature_counts: Dict[str, int]
    ) -> List[str]:
        """
        Финализация слоёв: commit, сохранение в GPKG, добавление в проект

        Args:
            target_layers: Словарь целевых слоёв
            feature_counts: Словарь счётчиков

        Returns:
            List[str]: Список имён созданных слоёв
        """
        created_layers = []
        gpkg_path = get_gpkg_path()

        for layer_name, layer in target_layers.items():
            if not layer:
                continue

            # Завершаем редактирование
            layer.commitChanges()
            count = layer.featureCount()

            if count == 0:
                log_info(f"Msm_25_3: Слой {layer_name} пуст, не добавлен")
                continue

            # Сохраняем в GPKG
            saved = save_layer_to_gpkg(layer)

            # Добавляем в проект
            added_layer = add_layer_to_project(
                layer=layer,
                layer_manager=self.layer_manager,
                gpkg_path=gpkg_path if saved else None
            )

            if added_layer:
                created_layers.append(layer_name)
                log_info(f"Msm_25_3: Создан слой {layer_name} - {count} объектов")

        # Сортируем слои если есть layer_manager
        if created_layers and self.layer_manager:
            log_info("Msm_25_3: Сортировка слоёв по order_layers")
            self.layer_manager.sort_all_layers()

        return created_layers

    def get_source_layer(self, layer_name: str) -> Optional[QgsVectorLayer]:
        """
        Получить слой по имени из проекта

        Args:
            layer_name: Имя слоя

        Returns:
            QgsVectorLayer или None
        """
        project = QgsProject.instance()
        for layer in project.mapLayers().values():
            if layer.name() == layer_name:
                return layer
        return None

    def check_source_layer(
        self,
        source_layer: QgsVectorLayer,
        required_fields: List[str]
    ) -> Tuple[bool, List[str]]:
        """
        Проверка исходного слоя на наличие необходимых полей

        Args:
            source_layer: Исходный слой
            required_fields: Список обязательных полей

        Returns:
            Tuple[bool, List[str]]: (валиден, список отсутствующих полей)
        """
        if not source_layer or not source_layer.isValid():
            return False, ["Слой не валиден"]

        missing_fields = []
        for field_name in required_fields:
            if source_layer.fields().indexFromName(field_name) == -1:
                missing_fields.append(field_name)

        return len(missing_fields) == 0, missing_fields
