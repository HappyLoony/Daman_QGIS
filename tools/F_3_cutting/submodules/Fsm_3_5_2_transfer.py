# -*- coding: utf-8 -*-
"""
Fsm_3_5_2_Transfer - Логика копирования ЗУ в слой Изъятие

Выполняет:
1. Создание слоя L_3_3_1_Изъятие_ЗУ (если не существует)
2. Проверка дубликатов по КН + Услов_КН
3. Копирование features из источника в Изъятие
4. Перенумерование ID в слое Изъятия
5. Сохранение в GPKG

Особенности:
- Операция КОПИРОВАНИЯ (источник не изменяется)
- Проверка дубликатов перед добавлением
- Все 27 полей из Base_cutting.json копируются 1:1
- Только ID перенумеровывается
"""

import os
from typing import List, Optional, Dict, Any, Set, TYPE_CHECKING

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsFeature,
    QgsGeometry,
    QgsFields,
)

from Daman_QGIS.utils import log_info, log_warning, log_error

if TYPE_CHECKING:
    from Daman_QGIS.managers import LayerManager


class Fsm_3_5_2_Transfer:
    """Модуль копирования features в слой Изъятие_ЗУ"""

    def __init__(
        self,
        gpkg_path: str,
        plugin_dir: str,
        target_layer_name: str,
        layer_manager: Optional['LayerManager'] = None
    ) -> None:
        """Инициализация модуля

        Args:
            gpkg_path: Путь к GeoPackage проекта
            plugin_dir: Путь к папке плагина
            target_layer_name: Имя целевого слоя (L_3_3_1_Изъятие_ЗУ)
            layer_manager: Менеджер слоёв (опционально)
        """
        self.gpkg_path = gpkg_path
        self.plugin_dir = plugin_dir
        self.target_layer_name = target_layer_name
        self.layer_manager = layer_manager

    def execute(
        self,
        source_layer: QgsVectorLayer,
        feature_ids: List[int]
    ) -> Dict[str, Any]:
        """Выполнить копирование features

        Args:
            source_layer: Слой-источник (Раздел или НГС)
            feature_ids: Список fid объектов для копирования

        Returns:
            Словарь с результатом:
            {
                'copied': int,           # Количество скопированных
                'duplicates': int,       # Количество пропущенных дубликатов
                'target_total': int,     # Всего в целевом слое
                'target_layer': str,     # Имя целевого слоя
                'target_layer_obj': QgsVectorLayer,  # Объект слоя
                'error': str             # Ошибка (если есть)
            }
        """
        log_info(f"Fsm_3_5_2: Копирование {len(feature_ids)} объектов из {source_layer.name()}")

        try:
            # 1. Получить или создать целевой слой
            target_layer = self._get_or_create_target_layer(source_layer)

            if target_layer is None:
                return {'error': f"Не удалось создать слой {self.target_layer_name}"}

            # 2. Собрать features для копирования
            features_to_copy = []
            for fid in feature_ids:
                feature = source_layer.getFeature(fid)
                if feature and feature.hasGeometry():
                    features_to_copy.append(feature)

            if not features_to_copy:
                return {'error': "Нет объектов для копирования"}

            # 3. Проверить дубликаты и подготовить features
            existing_keys = self._get_existing_keys(target_layer)
            prepared_features, duplicates = self._prepare_features(
                features_to_copy, source_layer.fields(), existing_keys
            )

            if not prepared_features:
                if duplicates > 0:
                    return {
                        'copied': 0,
                        'duplicates': duplicates,
                        'target_total': target_layer.featureCount(),
                        'target_layer': self.target_layer_name,
                        'target_layer_obj': target_layer,
                        'error': f"Все {duplicates} объект(ов) уже есть в слое Изъятия"
                    }
                return {'error': "Нет объектов для копирования после проверки дубликатов"}

            # 4. Добавить в целевой слой
            if not self._add_features_to_layer(target_layer, prepared_features):
                return {'error': "Ошибка добавления объектов в целевой слой"}

            # 5. Перенумеровать ID в целевом слое
            self._renumber_ids(target_layer)

            # 6. Сохранить изменения
            target_layer.commitChanges()

            # 7. Добавить целевой слой в проект (если новый)
            self._add_layer_to_project(target_layer)

            log_info(f"Fsm_3_5_2: Успешно скопировано {len(prepared_features)} объектов "
                    f"(дубликатов: {duplicates})")

            return {
                'copied': len(prepared_features),
                'duplicates': duplicates,
                'target_total': target_layer.featureCount(),
                'target_layer': self.target_layer_name,
                'target_layer_obj': target_layer
            }

        except Exception as e:
            log_error(f"Fsm_3_5_2: Исключение при копировании: {e}")
            return {'error': str(e)}

    def _get_or_create_target_layer(
        self,
        source_layer: QgsVectorLayer
    ) -> Optional[QgsVectorLayer]:
        """Получить существующий или создать новый целевой слой

        Args:
            source_layer: Слой-источник (для копирования структуры)

        Returns:
            QgsVectorLayer или None
        """
        project = QgsProject.instance()

        # Проверить существующий слой в проекте
        existing_layers = project.mapLayersByName(self.target_layer_name)
        if existing_layers:
            layer = existing_layers[0]
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                log_info(f"Fsm_3_5_2: Используем существующий слой {self.target_layer_name}")
                layer.startEditing()
                return layer

        # Проверить слой в GPKG
        uri = f"{self.gpkg_path}|layername={self.target_layer_name}"
        gpkg_layer = QgsVectorLayer(uri, self.target_layer_name, "ogr")
        if gpkg_layer.isValid():
            log_info(f"Fsm_3_5_2: Загружен слой {self.target_layer_name} из GPKG")
            gpkg_layer.startEditing()
            return gpkg_layer

        # Создать новый слой
        log_info(f"Fsm_3_5_2: Создание нового слоя {self.target_layer_name}")
        return self._create_new_layer(source_layer)

    def _create_new_layer(
        self,
        source_layer: QgsVectorLayer
    ) -> Optional[QgsVectorLayer]:
        """Создать новый слой в GPKG с такой же структурой

        Args:
            source_layer: Слой-образец

        Returns:
            QgsVectorLayer или None
        """
        try:
            crs = source_layer.crs()
            fields = source_layer.fields()

            # Создаём memory layer
            mem_layer = QgsVectorLayer(
                f"MultiPolygon?crs={crs.authid()}",
                self.target_layer_name,
                "memory"
            )

            if not mem_layer.isValid():
                log_error(f"Fsm_3_5_2: Не удалось создать memory layer")
                return None

            # Добавляем поля
            mem_layer.dataProvider().addAttributes(fields.toList())
            mem_layer.updateFields()

            # Сохраняем в GPKG
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = self.target_layer_name

            if os.path.exists(self.gpkg_path):
                options.actionOnExistingFile = (
                    QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
                )
            else:
                options.actionOnExistingFile = (
                    QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
                )

            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                mem_layer,
                self.gpkg_path,
                QgsProject.instance().transformContext(),
                options
            )

            if error[0] != QgsVectorFileWriter.WriterError.NoError:
                log_error(f"Fsm_3_5_2: Ошибка создания слоя в GPKG: {error[1]}")
                return None

            # Загружаем созданный слой
            uri = f"{self.gpkg_path}|layername={self.target_layer_name}"
            new_layer = QgsVectorLayer(uri, self.target_layer_name, "ogr")

            if new_layer.isValid():
                new_layer.startEditing()
                return new_layer
            else:
                log_error(f"Fsm_3_5_2: Не удалось загрузить созданный слой")
                return None

        except Exception as e:
            log_error(f"Fsm_3_5_2: Ошибка создания слоя: {e}")
            return None

    def _get_existing_keys(self, target_layer: QgsVectorLayer) -> Set[str]:
        """Получить набор ключей существующих объектов

        Ключ = "КН|Услов_КН" для проверки дубликатов

        Args:
            target_layer: Целевой слой

        Returns:
            Set[str]: Набор ключей
        """
        keys = set()
        for feature in target_layer.getFeatures():
            kn = str(feature['КН']) if feature['КН'] else ""
            uslov_kn = str(feature['Услов_КН']) if feature['Услов_КН'] else ""
            key = f"{kn}|{uslov_kn}"
            keys.add(key)
        return keys

    def _prepare_features(
        self,
        features: List[QgsFeature],
        fields: QgsFields,
        existing_keys: Set[str]
    ) -> tuple[List[QgsFeature], int]:
        """Подготовить features для копирования с проверкой дубликатов

        Args:
            features: Исходные features
            fields: Структура полей
            existing_keys: Набор существующих ключей

        Returns:
            Tuple[List[QgsFeature], int]: (подготовленные features, количество дубликатов)
        """
        prepared = []
        duplicates = 0

        for source_feat in features:
            # Проверка дубликата
            kn = str(source_feat['КН']) if source_feat['КН'] else ""
            uslov_kn = str(source_feat['Услов_КН']) if source_feat['Услов_КН'] else ""
            key = f"{kn}|{uslov_kn}"

            if key in existing_keys:
                duplicates += 1
                log_warning(f"Fsm_3_5_2: Пропущен дубликат КН={kn}, Услов_КН={uslov_kn}")
                continue

            # Добавить ключ чтобы не добавить дубликат из текущей выборки
            existing_keys.add(key)

            # Создать новый feature
            new_feat = QgsFeature(fields)

            # Глубокая копия геометрии через WKB
            geom = source_feat.geometry()
            if geom and not geom.isEmpty():
                wkb = geom.asWkb()
                new_geom = QgsGeometry()
                new_geom.fromWkb(wkb)
                new_feat.setGeometry(new_geom)

            # Копируем все атрибуты 1:1
            for i in range(fields.count()):
                field_name = fields.at(i).name()
                try:
                    value = source_feat[field_name]
                    new_feat.setAttribute(i, value)
                except (KeyError, IndexError):
                    pass

            prepared.append(new_feat)

        log_info(f"Fsm_3_5_2: Подготовлено {len(prepared)} features, дубликатов: {duplicates}")
        return prepared, duplicates

    def _add_features_to_layer(
        self,
        layer: QgsVectorLayer,
        features: List[QgsFeature]
    ) -> bool:
        """Добавить features в слой

        Args:
            layer: Целевой слой (в режиме редактирования)
            features: Features для добавления

        Returns:
            bool: True если успешно
        """
        if not layer.isEditable():
            layer.startEditing()

        try:
            success, _ = layer.dataProvider().addFeatures(features)
            if success:
                layer.updateExtents()
                return True
            else:
                log_error("Fsm_3_5_2: Ошибка добавления features")
                return False
        except Exception as e:
            log_error(f"Fsm_3_5_2: Исключение при добавлении: {e}")
            return False

    def _renumber_ids(self, layer: QgsVectorLayer) -> None:
        """Перенумеровать ID в слое (1, 2, 3...)

        Args:
            layer: Слой для перенумерации
        """
        if not layer.isEditable():
            layer.startEditing()

        id_idx = layer.fields().indexOf('ID')
        if id_idx < 0:
            log_warning(f"Fsm_3_5_2: Поле ID не найдено в слое {layer.name()}")
            return

        # Сортировка features по текущему ID
        features = list(layer.getFeatures())

        def get_id(f: QgsFeature) -> int:
            try:
                return int(f['ID']) if f['ID'] else 0
            except (ValueError, TypeError):
                return 0

        features.sort(key=get_id)

        # Перенумерация
        for new_id, feature in enumerate(features, start=1):
            layer.changeAttributeValue(feature.id(), id_idx, new_id)

        log_info(f"Fsm_3_5_2: Перенумерованы ID в {layer.name()} ({len(features)} объектов)")

    def _add_layer_to_project(self, layer: QgsVectorLayer) -> None:
        """Добавить слой в проект QGIS (если ещё не добавлен)

        Args:
            layer: Слой
        """
        project = QgsProject.instance()

        # Проверить, есть ли уже такой слой
        existing = project.mapLayersByName(self.target_layer_name)
        if existing:
            return

        # Добавить слой
        project.addMapLayer(layer)
        log_info(f"Fsm_3_5_2: Слой {self.target_layer_name} добавлен в проект")

        # Применить стили через LayerManager если доступен
        if self.layer_manager:
            try:
                self.layer_manager.apply_style_to_layer(layer)
                self.layer_manager.apply_labels_to_layer(layer)
            except Exception as e:
                log_warning(f"Fsm_3_5_2: Не удалось применить стили: {e}")
