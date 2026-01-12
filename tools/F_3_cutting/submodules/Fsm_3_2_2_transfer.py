# -*- coding: utf-8 -*-
"""
Fsm_3_2_2_Transfer - Логика переноса ЗУ из Раздел в Без_Меж

Выполняет:
1. Создание слоя Без_Меж (если не существует)
2. Копирование features из Раздел в Без_Меж
3. Перезапись атрибутов (План_* = исходные значения)
4. Удаление features из Раздел
5. Перенумерование ID в обоих слоях
6. Сохранение в GPKG

Атрибуты для Без_Меж:
- Услов_КН = КН (не генерируется)
- Услов_ЕЗ = ЕЗ
- План_категория = Категория
- План_ВРИ = ВРИ
- Площадь_ОЗУ = Площадь
- Вид_Работ = "Существующий (сохраняемый) земельный участок"
- Точки = "" (пустое)
"""

import os
from typing import List, Optional, Dict, Any, TYPE_CHECKING

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


class Fsm_3_2_2_Transfer:
    """Модуль переноса features из Раздел в Без_Меж"""

    def __init__(
        self,
        gpkg_path: str,
        razdel_to_bez_mezh: Dict[str, str],
        work_type: str,
        layer_manager: Optional['LayerManager'] = None
    ) -> None:
        """Инициализация модуля переноса

        Args:
            gpkg_path: Путь к GeoPackage проекта
            razdel_to_bez_mezh: Маппинг имён слоёв Раздел -> Без_Меж
            work_type: Значение поля Вид_Работ для Без_Меж
            layer_manager: Менеджер слоёв (опционально)
        """
        self.gpkg_path = gpkg_path
        self.razdel_to_bez_mezh = razdel_to_bez_mezh
        self.work_type = work_type
        self.layer_manager = layer_manager

    def execute(
        self,
        source_layer: QgsVectorLayer,
        feature_ids: List[int]
    ) -> Dict[str, Any]:
        """Выполнить перенос features

        Args:
            source_layer: Слой-источник (Раздел)
            feature_ids: Список fid объектов для переноса

        Returns:
            Словарь с результатом:
            {
                'transferred': int,      # Количество перенесённых
                'source_remaining': int, # Осталось в источнике
                'target_total': int,     # Всего в целевом
                'target_layer': str,     # Имя целевого слоя
                'target_layer_obj': QgsVectorLayer,  # Объект слоя
                'error': str             # Ошибка (если есть)
            }
        """
        log_info(f"Fsm_3_2_2: Перенос {len(feature_ids)} объектов из {source_layer.name()}")

        # Определить целевой слой
        source_name = source_layer.name()
        target_name = self.razdel_to_bez_mezh.get(source_name)

        if not target_name:
            # Попробуем по имени без констант
            for razdel, bez_mezh in self.razdel_to_bez_mezh.items():
                if razdel in source_name or source_name in razdel:
                    target_name = bez_mezh
                    break

        if not target_name:
            return {'error': f"Не найден целевой слой для {source_name}"}

        try:
            # 1. Получить или создать целевой слой
            target_layer = self._get_or_create_target_layer(
                source_layer, target_name
            )

            if not target_layer:
                return {'error': f"Не удалось создать слой {target_name}"}

            # 2. Собрать features для переноса
            features_to_transfer = []
            for fid in feature_ids:
                feature = source_layer.getFeature(fid)
                if feature and feature.hasGeometry():
                    features_to_transfer.append(feature)

            if not features_to_transfer:
                return {'error': "Нет объектов для переноса"}

            # 3. Подготовить атрибуты для Без_Меж
            prepared_features = self._prepare_bez_mezh_features(
                features_to_transfer, source_layer.fields()
            )

            # 4. Добавить в целевой слой
            if not self._add_features_to_layer(target_layer, prepared_features):
                return {'error': "Ошибка добавления объектов в целевой слой"}

            # 5. Удалить из источника
            if not self._delete_features_from_layer(source_layer, feature_ids):
                return {'error': "Ошибка удаления объектов из источника"}

            # 6. Перенумеровать ID в обоих слоях
            self._renumber_ids(source_layer)
            self._renumber_ids(target_layer)

            # 7. Сохранить изменения
            source_layer.commitChanges()
            target_layer.commitChanges()

            # 8. Добавить целевой слой в проект (если новый)
            self._add_layer_to_project(target_layer, target_name)

            log_info(f"Fsm_3_2_2: Успешно перенесено {len(feature_ids)} объектов в {target_name}")

            return {
                'transferred': len(feature_ids),
                'source_remaining': source_layer.featureCount(),
                'target_total': target_layer.featureCount(),
                'target_layer': target_name,
                'target_layer_obj': target_layer
            }

        except Exception as e:
            log_error(f"Fsm_3_2_2: Исключение при переносе: {e}")
            return {'error': str(e)}

    def _get_or_create_target_layer(
        self,
        source_layer: QgsVectorLayer,
        target_name: str
    ) -> Optional[QgsVectorLayer]:
        """Получить существующий или создать новый целевой слой

        Args:
            source_layer: Слой-источник (для копирования структуры)
            target_name: Имя целевого слоя

        Returns:
            QgsVectorLayer или None
        """
        project = QgsProject.instance()

        # Проверить существующий слой в проекте
        existing_layers = project.mapLayersByName(target_name)
        if existing_layers:
            layer = existing_layers[0]
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                log_info(f"Fsm_3_2_2: Используем существующий слой {target_name}")
                layer.startEditing()
                return layer

        # Проверить слой в GPKG
        uri = f"{self.gpkg_path}|layername={target_name}"
        gpkg_layer = QgsVectorLayer(uri, target_name, "ogr")
        if gpkg_layer.isValid():
            log_info(f"Fsm_3_2_2: Загружен слой {target_name} из GPKG")
            gpkg_layer.startEditing()
            return gpkg_layer

        # Создать новый слой
        log_info(f"Fsm_3_2_2: Создание нового слоя {target_name}")
        return self._create_new_layer(source_layer, target_name)

    def _create_new_layer(
        self,
        source_layer: QgsVectorLayer,
        target_name: str
    ) -> Optional[QgsVectorLayer]:
        """Создать новый слой в GPKG с такой же структурой

        Args:
            source_layer: Слой-образец
            target_name: Имя нового слоя

        Returns:
            QgsVectorLayer или None
        """
        try:
            crs = source_layer.crs()
            fields = source_layer.fields()

            # Создаём memory layer
            mem_layer = QgsVectorLayer(
                f"MultiPolygon?crs={crs.authid()}",
                target_name,
                "memory"
            )

            if not mem_layer.isValid():
                log_error(f"Fsm_3_2_2: Не удалось создать memory layer")
                return None

            # Добавляем поля
            mem_layer.dataProvider().addAttributes(fields.toList())
            mem_layer.updateFields()

            # Сохраняем в GPKG
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = target_name

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
                log_error(f"Fsm_3_2_2: Ошибка создания слоя в GPKG: {error[1]}")
                return None

            # Загружаем созданный слой
            uri = f"{self.gpkg_path}|layername={target_name}"
            new_layer = QgsVectorLayer(uri, target_name, "ogr")

            if new_layer.isValid():
                new_layer.startEditing()
                return new_layer
            else:
                log_error(f"Fsm_3_2_2: Не удалось загрузить созданный слой")
                return None

        except Exception as e:
            log_error(f"Fsm_3_2_2: Ошибка создания слоя: {e}")
            return None

    def _prepare_bez_mezh_features(
        self,
        features: List[QgsFeature],
        fields: QgsFields
    ) -> List[QgsFeature]:
        """Подготовить features с атрибутами для Без_Меж

        Перезаписывает:
        - Услов_КН = КН
        - Услов_ЕЗ = ЕЗ
        - План_категория = Категория
        - План_ВРИ = ВРИ
        - Площадь_ОЗУ = Площадь
        - Вид_Работ = "Существующий (сохраняемый) земельный участок"
        - Точки = ""

        Args:
            features: Исходные features
            fields: Структура полей

        Returns:
            Список подготовленных features
        """
        prepared = []

        for source_feat in features:
            new_feat = QgsFeature(fields)

            # Глубокая копия геометрии через WKB
            geom = source_feat.geometry()
            if geom and not geom.isEmpty():
                wkb = geom.asWkb()
                new_geom = QgsGeometry()
                new_geom.fromWkb(wkb)
                new_feat.setGeometry(new_geom)

            # Копируем все атрибуты
            for i in range(fields.count()):
                field_name = fields.at(i).name()
                try:
                    value = source_feat[field_name]
                    new_feat.setAttribute(i, value)
                except (KeyError, IndexError):
                    pass

            # Перезаписываем специфичные для Без_Меж
            self._set_attribute(new_feat, fields, 'Услов_КН',
                               self._get_value(source_feat, 'КН', '-'))
            self._set_attribute(new_feat, fields, 'Услов_ЕЗ',
                               self._get_value(source_feat, 'ЕЗ', '-'))
            self._set_attribute(new_feat, fields, 'План_категория',
                               self._get_value(source_feat, 'Категория', '-'))
            self._set_attribute(new_feat, fields, 'План_ВРИ',
                               self._get_value(source_feat, 'ВРИ', '-'))
            self._set_attribute(new_feat, fields, 'Площадь_ОЗУ',
                               self._get_value(source_feat, 'Площадь', 0))
            self._set_attribute(new_feat, fields, 'Вид_Работ', self.work_type)
            self._set_attribute(new_feat, fields, 'Точки', '')

            prepared.append(new_feat)

        log_info(f"Fsm_3_2_2: Подготовлено {len(prepared)} features для Без_Меж")
        return prepared

    def _get_value(self, feature: QgsFeature, field_name: str, default: Any) -> Any:
        """Безопасное получение значения атрибута

        Args:
            feature: Feature
            field_name: Имя поля
            default: Значение по умолчанию

        Returns:
            Значение или default
        """
        try:
            value = feature[field_name]
            if value is None or value == '':
                return default
            return value
        except (KeyError, IndexError):
            return default

    def _set_attribute(
        self,
        feature: QgsFeature,
        fields: QgsFields,
        field_name: str,
        value: Any
    ) -> None:
        """Установить атрибут по имени поля

        Args:
            feature: Feature
            fields: Структура полей
            field_name: Имя поля
            value: Значение
        """
        idx = fields.indexOf(field_name)
        if idx >= 0:
            feature.setAttribute(idx, value)

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
                log_error("Fsm_3_2_2: Ошибка добавления features")
                return False
        except Exception as e:
            log_error(f"Fsm_3_2_2: Исключение при добавлении: {e}")
            return False

    def _delete_features_from_layer(
        self,
        layer: QgsVectorLayer,
        feature_ids: List[int]
    ) -> bool:
        """Удалить features из слоя

        Args:
            layer: Слой-источник
            feature_ids: Список fid для удаления

        Returns:
            bool: True если успешно
        """
        if not layer.isEditable():
            layer.startEditing()

        try:
            success = layer.deleteFeatures(feature_ids)
            if success:
                layer.updateExtents()
                return True
            else:
                log_error("Fsm_3_2_2: Ошибка удаления features")
                return False
        except Exception as e:
            log_error(f"Fsm_3_2_2: Исключение при удалении: {e}")
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
            log_warning(f"Fsm_3_2_2: Поле ID не найдено в слое {layer.name()}")
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

        log_info(f"Fsm_3_2_2: Перенумерованы ID в {layer.name()} ({len(features)} объектов)")

    def _add_layer_to_project(
        self,
        layer: QgsVectorLayer,
        layer_name: str
    ) -> None:
        """Добавить слой в проект QGIS (если ещё не добавлен)

        Args:
            layer: Слой
            layer_name: Имя слоя
        """
        project = QgsProject.instance()

        # Проверить, есть ли уже такой слой
        existing = project.mapLayersByName(layer_name)
        if existing:
            return

        # Добавить слой
        project.addMapLayer(layer)
        log_info(f"Fsm_3_2_2: Слой {layer_name} добавлен в проект")

        # Применить стили через LayerManager если доступен
        if self.layer_manager:
            try:
                self.layer_manager.apply_style_to_layer(layer)
                self.layer_manager.apply_labels_to_layer(layer)
            except Exception as e:
                log_warning(f"Fsm_3_2_2: Не удалось применить стили: {e}")
