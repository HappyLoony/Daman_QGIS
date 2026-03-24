# -*- coding: utf-8 -*-
"""
Fsm_2_7_2_MergeProcessor - Логика объединения контуров нарезки

Поддерживает два режима:
1. Same-layer: объединение внутри слоя Раздел (source = target)
2. Cross-layer: объединение Без_Меж -> результат в Раздел

Выполняет:
1. Объединение геометрий через QgsGeometry.unaryUnion()
2. Генерацию атрибутов объединённого контура
3. Удаление исходных контуров из слоя-источника
4. Добавление объединённого контура в целевой слой
5. Перенумерование ID
6. Пересоздание точечного слоя
7. Сохранение в GPKG

Атрибуты объединённого:
- Услов_КН = "КН:ЗУ{N}" (N = max+1 с учётом Раздел + НГС)
- Вид_Работ = "Образование ЗУ путём объединения ... с условными номерами X, Y"
- Состав_контуров = "ID (КН), ID, ID (КН)" - расширенный формат
- Площадь_ОЗУ = area() объединённой геометрии
- Многоконтурный = "Да" / "Нет"
"""

import os
from typing import List, Optional, Dict, Any, TYPE_CHECKING

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsFeature,
    QgsGeometry,
)

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.constants import COORDINATE_PRECISION

# Импорт субмодулей F_2_1 для переиспользования
from .Fsm_2_1_6_point_layer_creator import Fsm_2_1_6_PointLayerCreator
from .Fsm_2_7_3_attribute_handler import Fsm_2_7_3_AttributeHandler

if TYPE_CHECKING:
    from Daman_QGIS.managers import LayerManager


class Fsm_2_7_2_MergeProcessor:
    """Процессор объединения контуров нарезки"""

    def __init__(
        self,
        gpkg_path: str,
        plugin_dir: str,
        layer_manager: Optional['LayerManager'] = None
    ) -> None:
        """Инициализация процессора

        Args:
            gpkg_path: Путь к GeoPackage проекта
            plugin_dir: Путь к папке плагина
            layer_manager: Менеджер слоёв (опционально)
        """
        self.gpkg_path = gpkg_path
        self.plugin_dir = plugin_dir
        self.layer_manager = layer_manager

        # Инициализация субмодулей
        self._point_layer_creator = Fsm_2_1_6_PointLayerCreator(gpkg_path)
        self._attribute_handler = Fsm_2_7_3_AttributeHandler(plugin_dir)

    def execute(
        self,
        source_layer: QgsVectorLayer,
        feature_ids: List[int],
        target_razdel_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Выполнить объединение контуров

        Args:
            source_layer: Слой-источник (Раздел или Без_Меж)
            feature_ids: Список fid объектов для объединения
            target_razdel_name: Имя целевого слоя Раздел (если source = Без_Меж).
                None означает same-layer merge (source = Раздел).

        Returns:
            Словарь с результатом
        """
        is_cross_layer = target_razdel_name is not None
        mode = "cross-layer" if is_cross_layer else "same-layer"
        log_info(f"Fsm_2_7_2: Объединение {len(feature_ids)} контуров "
                 f"из {source_layer.name()} ({mode})")

        if len(feature_ids) < 2:
            return {'error': "Для объединения нужно минимум 2 контура"}

        try:
            # 1. Собрать features для объединения
            features_to_merge = []
            geometries = []

            for fid in feature_ids:
                feature = source_layer.getFeature(fid)
                if feature and feature.hasGeometry():
                    features_to_merge.append(feature)
                    geometries.append(QgsGeometry(feature.geometry()))

            if len(features_to_merge) < 2:
                return {'error': "Недостаточно валидных контуров для объединения"}

            # 2. Объединить геометрии
            merged_geom = QgsGeometry.unaryUnion(geometries)
            merged_geom = merged_geom.snappedToGrid(
                COORDINATE_PRECISION, COORDINATE_PRECISION
            )

            if merged_geom.isEmpty():
                return {'error': "Не удалось объединить геометрии"}

            # Нормализация геометрии: кольца начинаются с СЗ точки (П/0592)
            merged_geom = self._normalize_polygon_geometry(merged_geom)

            is_multipart = merged_geom.isMultipart()
            new_area = merged_geom.area()

            log_info(f"Fsm_2_7_2: Объединённая геометрия - "
                     f"{'MultiPolygon' if is_multipart else 'Polygon'}, "
                     f"площадь {new_area:.0f} м2")

            # 3. Определить целевой слой
            if is_cross_layer:
                target_layer = self._find_or_create_razdel_layer(
                    target_razdel_name, source_layer
                )
                if not target_layer:
                    return {'error': f"Не удалось создать слой {target_razdel_name}"}
            else:
                target_layer = source_layer

            # 4. Сбор существующих Услов_КН для нумерации :ЗУ{N}
            if is_cross_layer:
                existing_uslov_kns = self._collect_uslov_kns_for_razdel(
                    target_layer, target_razdel_name
                )
            else:
                existing_uslov_kns = self._collect_existing_uslov_kns(
                    source_layer, feature_ids
                )

            # 5. Генерация атрибутов
            merged_attrs = self._attribute_handler.generate_merged_attributes(
                features_to_merge,
                target_layer.fields(),
                new_area,
                is_multipart,
                existing_uslov_kns=existing_uslov_kns
            )

            if not merged_attrs:
                return {'error': "Не удалось сгенерировать атрибуты"}

            new_uslov_kn = merged_attrs.get('Услов_КН', '')

            # 6. Создать новый feature
            new_feature = QgsFeature(target_layer.fields())
            new_feature.setGeometry(merged_geom)

            for field_name, value in merged_attrs.items():
                idx = target_layer.fields().indexOf(field_name)
                if idx >= 0:
                    new_feature.setAttribute(idx, value)

            # 7. Удаление исходных контуров из source
            if not source_layer.isEditable():
                source_layer.startEditing()

            if not source_layer.deleteFeatures(feature_ids):
                source_layer.rollBack()
                return {'error': "Ошибка удаления исходных контуров"}

            # 8. Добавление объединённого контура в target
            if is_cross_layer:
                # Cross-layer: target отличается от source
                if not target_layer.isEditable():
                    target_layer.startEditing()

                if not target_layer.addFeature(new_feature):
                    source_layer.rollBack()
                    target_layer.rollBack()
                    return {'error': "Ошибка добавления объединённого контура в Раздел"}

                # Перенумерация target (Раздел)
                self._renumber_ids(target_layer)

                # Нумерация характерных точек в target
                self._number_all_points(target_layer)

                # Commit target
                target_layer.commitChanges()
                target_layer.updateExtents()

                # Перенумерация source (Без_Меж) и commit
                self._renumber_ids(source_layer)
                source_layer.commitChanges()
                source_layer.updateExtents()

            else:
                # Same-layer: source = target
                if not target_layer.addFeature(new_feature):
                    source_layer.rollBack()
                    return {'error': "Ошибка добавления объединённого контура"}

                self._renumber_ids(target_layer)

                # Нумерация характерных точек
                self._number_all_points(target_layer)

                source_layer.commitChanges()
                source_layer.updateExtents()

            # 9. Пересоздание точечных слоёв
            source_points_layer = self._recreate_point_layer(source_layer)
            razdel_points_layer = None
            if is_cross_layer:
                razdel_points_layer = self._recreate_point_layer(target_layer)

            # 10. Удаление пустого source слоя из проекта (cross-layer)
            source_removed = False
            if is_cross_layer and source_layer.featureCount() == 0:
                self._remove_empty_layer(source_layer)
                source_removed = True

            # 11. Перезагрузка dataProvider всех слоёв из того же GPKG
            # writeAsVectorFormatV3 инвалидирует OGR file handles
            self._reload_gpkg_layers()

            log_info(f"Fsm_2_7_2: Успешно объединено {len(feature_ids)} контуров, "
                     f"новый Услов_КН: {new_uslov_kn}")

            result: Dict[str, Any] = {
                'merged_count': len(feature_ids),
                'is_multipart': is_multipart,
                'new_area': new_area,
                'new_uslov_kn': new_uslov_kn,
                'points_layer': source_points_layer,
                'source_removed': source_removed,
            }
            if is_cross_layer:
                result['razdel_layer'] = target_layer
                result['razdel_points_layer'] = razdel_points_layer

            return result

        except Exception as e:
            log_error(f"Fsm_2_7_2: Исключение при объединении: {e}")
            if source_layer.isEditable():
                source_layer.rollBack()
            if is_cross_layer and target_razdel_name:
                # target_layer может не существовать при ранней ошибке
                project = QgsProject.instance()
                layers = project.mapLayersByName(target_razdel_name)
                if layers and layers[0].isEditable():
                    layers[0].rollBack()
            return {'error': str(e)}

    # ------------------------------------------------------------------
    # Поиск / создание целевого слоя Раздел
    # ------------------------------------------------------------------

    def _find_or_create_razdel_layer(
        self,
        razdel_name: str,
        source_layer: QgsVectorLayer
    ) -> Optional[QgsVectorLayer]:
        """Найти или создать слой Раздел в проекте

        Args:
            razdel_name: Имя слоя Раздел
            source_layer: Слой-источник (для CRS и полей)

        Returns:
            QgsVectorLayer или None
        """
        project = QgsProject.instance()
        existing = project.mapLayersByName(razdel_name)
        if existing and isinstance(existing[0], QgsVectorLayer) and existing[0].isValid():
            log_info(f"Fsm_2_7_2: Найден существующий слой {razdel_name}")
            return existing[0]

        # Создаём новый пустой слой в GPKG
        log_info(f"Fsm_2_7_2: Создание нового слоя {razdel_name} в GPKG")
        return self._create_empty_razdel_layer(razdel_name, source_layer)

    def _create_empty_razdel_layer(
        self,
        layer_name: str,
        source_layer: QgsVectorLayer
    ) -> Optional[QgsVectorLayer]:
        """Создать пустой слой Раздел в GPKG

        Использует паттерн из Msm_26_3_layer_creator.

        Args:
            layer_name: Имя слоя
            source_layer: Слой-источник (для CRS и структуры полей)

        Returns:
            Загруженный QgsVectorLayer или None
        """
        try:
            crs = source_layer.crs()
            fields = source_layer.fields()

            # Создаём memory layer с полями
            mem_layer = QgsVectorLayer(
                f"MultiPolygon?crs={crs.authid()}",
                layer_name,
                "memory"
            )

            if not mem_layer.isValid():
                log_error(f"Fsm_2_7_2: Не удалось создать memory layer для {layer_name}")
                return None

            mem_layer.dataProvider().addAttributes(fields.toList())
            mem_layer.updateFields()

            # Сохраняем в GPKG (пустой слой)
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = layer_name

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
                log_error(f"Fsm_2_7_2: Ошибка записи слоя {layer_name} в GPKG: {error[1]}")
                return None

            # Загружаем из GPKG
            uri = f"{self.gpkg_path}|layername={layer_name}"
            layer = QgsVectorLayer(uri, layer_name, "ogr")

            if not layer.isValid():
                log_error(f"Fsm_2_7_2: Не удалось загрузить слой из {uri}")
                return None

            # Добавляем в проект через LayerManager (стили + подписи + visibility)
            if self.layer_manager:
                self.layer_manager.add_layer(layer, check_precision=False)
            else:
                QgsProject.instance().addMapLayer(layer)

            log_info(f"Fsm_2_7_2: Создан пустой слой {layer_name} в GPKG")
            return layer

        except Exception as e:
            log_error(f"Fsm_2_7_2: Ошибка создания слоя {layer_name}: {e}")
            return None

    # ------------------------------------------------------------------
    # Сбор Услов_КН
    # ------------------------------------------------------------------

    def _collect_existing_uslov_kns(
        self,
        source_layer: QgsVectorLayer,
        exclude_fids: List[int]
    ) -> List[str]:
        """Собрать существующие Услов_КН из слоя и соответствующего НГС

        Используется при same-layer merge (source = Раздел).

        Args:
            source_layer: Слой Раздел
            exclude_fids: fid объектов, которые будут удалены (объединяемые)

        Returns:
            Список всех существующих Услов_КН
        """
        existing = []
        exclude_set = set(exclude_fids)

        # 1. Собрать из текущего слоя (кроме объединяемых)
        for feature in source_layer.getFeatures():
            if feature.id() not in exclude_set:
                uslov_kn = feature['Услов_КН'] if 'Услов_КН' in feature.fields().names() else None
                if uslov_kn:
                    existing.append(str(uslov_kn))

        # 2. Найти соответствующий НГС слой и собрать оттуда
        ngs_layer = self._find_ngs_layer(source_layer.name())
        if ngs_layer:
            for feature in ngs_layer.getFeatures():
                uslov_kn = feature['Услов_КН'] if 'Услов_КН' in feature.fields().names() else None
                if uslov_kn:
                    existing.append(str(uslov_kn))

        log_info(f"Fsm_2_7_2: Найдено {len(existing)} существующих Услов_КН "
                 f"для нумерации :ЗУ")
        return existing

    def _collect_uslov_kns_for_razdel(
        self,
        razdel_layer: QgsVectorLayer,
        razdel_name: str
    ) -> List[str]:
        """Собрать существующие Услов_КН для целевого слоя Раздел

        Используется при cross-layer merge (source = Без_Меж).
        Собирает из Раздел (все features) + НГС.

        Args:
            razdel_layer: Целевой слой Раздел
            razdel_name: Имя слоя Раздел

        Returns:
            Список всех существующих Услов_КН
        """
        existing = []

        # 1. Собрать из Раздел (все features, ничего не исключаем)
        for feature in razdel_layer.getFeatures():
            uslov_kn = feature['Услов_КН'] if 'Услов_КН' in feature.fields().names() else None
            if uslov_kn:
                existing.append(str(uslov_kn))

        # 2. Найти НГС слой (по имени Раздел, не Без_Меж)
        ngs_layer = self._find_ngs_layer(razdel_name)
        if ngs_layer:
            for feature in ngs_layer.getFeatures():
                uslov_kn = feature['Услов_КН'] if 'Услов_КН' in feature.fields().names() else None
                if uslov_kn:
                    existing.append(str(uslov_kn))

        log_info(f"Fsm_2_7_2: Найдено {len(existing)} существующих Услов_КН "
                 f"в Раздел+НГС для нумерации :ЗУ")
        return existing

    # ------------------------------------------------------------------
    # Поиск НГС слоя
    # ------------------------------------------------------------------

    @staticmethod
    def _find_ngs_layer(razdel_name: str) -> Optional[QgsVectorLayer]:
        """Найти НГС слой по имени слоя Раздел

        Паттерн: Le_2_1_X_1_Раздел_* -> Le_2_1_X_2_НГС_*

        Args:
            razdel_name: Имя слоя Раздел

        Returns:
            QgsVectorLayer НГС или None
        """
        # Заменяем _1_Раздел_ на _2_НГС_
        ngs_name = razdel_name.replace('_1_Раздел_', '_2_НГС_')
        if ngs_name == razdel_name:
            return None

        project = QgsProject.instance()
        layers = project.mapLayersByName(ngs_name)
        if layers and isinstance(layers[0], QgsVectorLayer) and layers[0].isValid():
            log_info(f"Fsm_2_7_2: Найден НГС слой {ngs_name}")
            return layers[0]

        return None

    # ------------------------------------------------------------------
    # Перенумерация и точки
    # ------------------------------------------------------------------

    def _renumber_ids(self, layer: QgsVectorLayer) -> None:
        """Перенумеровать ID в слое (1, 2, 3...) в порядке СЗ -> ЮВ

        Сортирует контуры по расстоянию от центроида до северо-западного
        угла общего MBR (как в нарезке M_26/M_20).

        Args:
            layer: Слой для перенумерации
        """
        if not layer.isEditable():
            layer.startEditing()

        id_idx = layer.fields().indexOf('ID')
        if id_idx < 0:
            log_warning(f"Fsm_2_7_2: Поле ID не найдено в слое {layer.name()}")
            return

        features = list(layer.getFeatures())
        if not features:
            return

        # Сортировка по расстоянию от центроида до СЗ угла MBR
        global_min_x = float('inf')
        global_max_y = float('-inf')

        centroids = []
        for f in features:
            geom = f.geometry()
            if geom and not geom.isEmpty():
                centroid = geom.centroid().asPoint()
                centroids.append((centroid.x(), centroid.y()))
                bbox = geom.boundingBox()
                global_min_x = min(global_min_x, bbox.xMinimum())
                global_max_y = max(global_max_y, bbox.yMaximum())
            else:
                centroids.append(None)

        nw_x, nw_y = global_min_x, global_max_y

        def nw_sort_key(idx_feature):
            idx, _ = idx_feature
            c = centroids[idx]
            if c is None:
                return float('inf')
            return (c[0] - nw_x) ** 2 + (c[1] - nw_y) ** 2

        indexed = list(enumerate(features))
        indexed.sort(key=nw_sort_key)

        # Перенумерация в порядке СЗ -> ЮВ
        for new_id, (_, feature) in enumerate(indexed, start=1):
            layer.changeAttributeValue(feature.id(), id_idx, new_id)

        log_info(f"Fsm_2_7_2: Перенумерованы ID в {layer.name()} "
                 f"({len(features)} объектов, СЗ -> ЮВ)")

    def _number_all_points(self, layer: QgsVectorLayer) -> None:
        """Пронумеровать характерные точки всех контуров в слое

        Использует number_layer_points() для обработки всего слоя.
        Обновляет поле Точки для каждого feature.

        Args:
            layer: Слой с контурами (должен быть в режиме редактирования)
        """
        try:
            from Daman_QGIS.managers.geometry.M_20_point_numbering_manager import (
                number_layer_points,
            )

            points_dict, _ = number_layer_points(layer)

            if not points_dict:
                log_warning(f"Fsm_2_7_2: Нет данных нумерации точек для {layer.name()}")
                return

            if not layer.isEditable():
                layer.startEditing()

            points_idx = layer.fields().indexOf('Точки')
            if points_idx < 0:
                return

            for fid, points_str in points_dict.items():
                layer.changeAttributeValue(fid, points_idx, points_str)

            log_info(f"Fsm_2_7_2: Пронумерованы точки для {len(points_dict)} "
                     f"контуров в {layer.name()}")

        except Exception as e:
            log_warning(f"Fsm_2_7_2: Ошибка нумерации точек: {e}")

    # ------------------------------------------------------------------
    # Пересоздание точечного слоя
    # ------------------------------------------------------------------

    @staticmethod
    def _remove_empty_layer(layer: QgsVectorLayer) -> None:
        """Удалить пустой слой из проекта

        Вызывается при cross-layer merge, когда все features
        из source (Без_Меж) перенесены в target (Раздел).

        Args:
            layer: Пустой слой для удаления
        """
        layer_name = layer.name()
        project = QgsProject.instance()
        project.removeMapLayer(layer.id())
        log_info(f"Fsm_2_7_2: Пустой слой {layer_name} удалён из проекта")

    def _reload_gpkg_layers(self) -> None:
        """Перезагрузить dataProvider всех слоёв из того же GPKG

        После writeAsVectorFormatV3 OGR file handles других слоёв
        из того же GPKG становятся невалидными. Вызов reloadData()
        восстанавливает соединение.
        """
        gpkg_norm = os.path.normpath(self.gpkg_path).lower()
        project = QgsProject.instance()
        reloaded = 0

        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            source = layer.source().split('|')[0]
            if os.path.normpath(source).lower() == gpkg_norm:
                layer.dataProvider().reloadData()
                layer.triggerRepaint()
                reloaded += 1

        if reloaded:
            log_info(f"Fsm_2_7_2: Перезагружено {reloaded} GPKG-слоёв")

    def _recreate_point_layer(
        self,
        source_layer: QgsVectorLayer
    ) -> Optional[QgsVectorLayer]:
        """Пересоздать точечный слой для полигонального

        Args:
            source_layer: Полигональный слой

        Returns:
            QgsVectorLayer: Новый точечный слой или None
        """
        source_name = source_layer.name()
        point_layer_name = self._point_layer_creator.get_point_layer_name(source_name)

        if not point_layer_name:
            log_warning(f"Fsm_2_7_2: Не найдено имя точечного слоя для {source_name}")
            return None

        # Если в слое нет features, удаляем точечный слой и выходим
        if source_layer.featureCount() == 0:
            project = QgsProject.instance()
            existing = project.mapLayersByName(point_layer_name)
            for layer in existing:
                project.removeMapLayer(layer.id())
            log_info(f"Fsm_2_7_2: Слой {source_name} пуст, "
                     f"точечный слой {point_layer_name} удалён")
            return None

        try:
            # Генерируем данные точек для всех контуров слоя
            points_data = []
            global_point_id = 1

            for feature in source_layer.getFeatures():
                geom = feature.geometry()
                if not geom or geom.isEmpty():
                    continue

                contour_id = feature['ID'] or 0
                uslov_kn = feature['Услов_КН'] or ''
                kn = feature['КН'] or ''

                feature_points = self._extract_points_from_geometry(
                    geom,
                    contour_id,
                    uslov_kn,
                    kn,
                    global_point_id,
                    source_layer.crs()
                )

                points_data.extend(feature_points)
                global_point_id += len(feature_points)

            if not points_data:
                log_warning(f"Fsm_2_7_2: Нет точек для слоя {point_layer_name}")
                return None

            # Удаляем старый слой из проекта (если есть)
            project = QgsProject.instance()
            existing = project.mapLayersByName(point_layer_name)
            for layer in existing:
                project.removeMapLayer(layer.id())

            # Создаём новый точечный слой
            point_layer = self._point_layer_creator.create_point_layer(
                point_layer_name,
                source_layer.crs(),
                points_data
            )

            if point_layer and point_layer.isValid():
                # Добавляем через LayerManager (стили + подписи + visibility)
                if self.layer_manager:
                    self.layer_manager.add_layer(point_layer, check_precision=False)
                else:
                    project.addMapLayer(point_layer)

                log_info(f"Fsm_2_7_2: Пересоздан точечный слой {point_layer_name}")
                return point_layer

            return None

        except Exception as e:
            log_error(f"Fsm_2_7_2: Ошибка пересоздания точечного слоя: {e}")
            return None

    def _extract_points_from_geometry(
        self,
        geom: QgsGeometry,
        contour_id: int,
        uslov_kn: str,
        kn: str,
        start_id: int,
        crs
    ) -> List[Dict[str, Any]]:
        """Извлечь точки из геометрии полигона

        Args:
            geom: Геометрия полигона
            contour_id: ID контура
            uslov_kn: Условный КН
            kn: Кадастровый номер
            start_id: Начальный ID для нумерации
            crs: Система координат

        Returns:
            Список словарей с данными точек
        """
        from qgis.core import QgsPointXY

        points_data = []
        point_id = start_id

        # Нормализуем к списку полигонов
        if geom.isMultipart():
            polygons = geom.asMultiPolygon()
        else:
            polygons = [geom.asPolygon()]

        for polygon in polygons:
            for ring_idx, ring in enumerate(polygon):
                is_outer = (ring_idx == 0)
                contour_type = 'Внешний' if is_outer else 'Внутренний'
                contour_number = ring_idx + 1

                # Убираем замыкающую точку и нормализуем от СЗ угла
                ring_points = list(ring[:-1])
                ring_points = self._rotate_ring_to_nw(ring_points)

                for pt_idx, point in enumerate(ring_points):
                    x_math = point.x()
                    y_math = point.y()

                    # Геодезические координаты (X=Y_math, Y=X_math)
                    x_geodetic = round(y_math, 2)
                    y_geodetic = round(x_math, 2)

                    points_data.append({
                        'id': point_id,
                        'contour_point_index': pt_idx + 1,
                        'contour_id': contour_id,
                        'uslov_kn': uslov_kn,
                        'kn': kn,
                        'contour_type': contour_type,
                        'contour_number': contour_number,
                        'x_geodetic': x_geodetic,
                        'y_geodetic': y_geodetic,
                        'point': QgsPointXY(x_math, y_math)
                    })

                    point_id += 1

        return points_data

    @staticmethod
    def _normalize_polygon_geometry(geom: QgsGeometry) -> QgsGeometry:
        """Нормализовать геометрию полигона: кольца начинаются с СЗ точки

        После unaryUnion() первая вершина оказывается на стыке
        объединённых полигонов. Эта функция ротирует каждое кольцо
        чтобы обход начинался с СЗ точки (стандарт П/0592).

        Args:
            geom: Исходная геометрия (Polygon или MultiPolygon)

        Returns:
            Новая геометрия с нормализованными кольцами
        """
        from qgis.core import QgsPointXY

        if geom.isEmpty():
            return geom

        if geom.isMultipart():
            polygons = geom.asMultiPolygon()
        else:
            polygons = [geom.asPolygon()]

        new_polygons = []
        for polygon in polygons:
            new_rings = []
            for ring in polygon:
                # Убираем замыкающую точку
                pts = list(ring[:-1])
                if len(pts) < 3:
                    new_rings.append(ring)
                    continue

                # Находим СЗ точку
                min_x = min(p.x() for p in pts)
                max_y = max(p.y() for p in pts)
                best_idx = 0
                best_dist = float('inf')
                for i, p in enumerate(pts):
                    d = (p.x() - min_x) ** 2 + (p.y() - max_y) ** 2
                    if d < best_dist:
                        best_dist = d
                        best_idx = i

                # Ротация
                if best_idx > 0:
                    pts = pts[best_idx:] + pts[:best_idx]

                # Замыкаем кольцо
                pts.append(QgsPointXY(pts[0]))
                new_rings.append(pts)
            new_polygons.append(new_rings)

        if geom.isMultipart():
            return QgsGeometry.fromMultiPolygonXY(new_polygons)
        else:
            return QgsGeometry.fromPolygonXY(new_polygons[0])

    @staticmethod
    def _rotate_ring_to_nw(points: list) -> list:
        """Ротация кольца чтобы нумерация начиналась с СЗ точки

        Находит точку ближайшую к СЗ углу MBR кольца
        и ротирует список, чтобы она стала первой.
        Аналог PointNumberingManager.find_nw_point_index + normalize_ring.

        Args:
            points: Список QgsPointXY (без замыкающей точки)

        Returns:
            Ротированный список
        """
        if len(points) <= 1:
            return points

        min_x = min(p.x() for p in points)
        max_y = max(p.y() for p in points)

        best_idx = 0
        best_dist_sq = float('inf')
        for idx, pt in enumerate(points):
            dist_sq = (pt.x() - min_x) ** 2 + (pt.y() - max_y) ** 2
            if dist_sq < best_dist_sq:
                best_dist_sq = dist_sq
                best_idx = idx

        if best_idx > 0:
            points = points[best_idx:] + points[:best_idx]

        return points
