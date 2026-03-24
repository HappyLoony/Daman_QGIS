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

# Импорт менеджеров
from Daman_QGIS.managers import registry

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
                points_field = self._number_points(target_layer, merged_geom, new_uslov_kn)
                if points_field:
                    self._update_points_field(target_layer, new_uslov_kn, points_field)

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

                points_field = self._number_points(target_layer, merged_geom, new_uslov_kn)
                if points_field:
                    self._update_points_field(target_layer, new_uslov_kn, points_field)

                source_layer.commitChanges()
                source_layer.updateExtents()

            # 9. Пересоздание точечных слоёв
            source_points_layer = self._recreate_point_layer(source_layer)
            razdel_points_layer = None
            if is_cross_layer:
                razdel_points_layer = self._recreate_point_layer(target_layer)

            log_info(f"Fsm_2_7_2: Успешно объединено {len(feature_ids)} контуров, "
                     f"новый Услов_КН: {new_uslov_kn}")

            result: Dict[str, Any] = {
                'merged_count': len(feature_ids),
                'is_multipart': is_multipart,
                'new_area': new_area,
                'new_uslov_kn': new_uslov_kn,
                'points_layer': source_points_layer,
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

            # Добавляем в проект
            project = QgsProject.instance()
            project.addMapLayer(layer)

            # Применяем стили
            if self.layer_manager:
                try:
                    self.layer_manager.apply_style_to_layer(layer)
                    self.layer_manager.apply_labels_to_layer(layer)
                except Exception as e:
                    log_warning(f"Fsm_2_7_2: Не удалось применить стили к {layer_name}: {e}")

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
        """Перенумеровать ID в слое (1, 2, 3...)

        Args:
            layer: Слой для перенумерации
        """
        if not layer.isEditable():
            layer.startEditing()

        id_idx = layer.fields().indexOf('ID')
        if id_idx < 0:
            log_warning(f"Fsm_2_7_2: Поле ID не найдено в слое {layer.name()}")
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

        log_info(f"Fsm_2_7_2: Перенумерованы ID в {layer.name()} ({len(features)} объектов)")

    def _number_points(
        self,
        layer: QgsVectorLayer,
        merged_geom: QgsGeometry,
        uslov_kn: str
    ) -> Optional[str]:
        """Пронумеровать характерные точки объединённого контура

        Args:
            layer: Слой с объединённым контуром
            merged_geom: Геометрия объединённого контура
            uslov_kn: Условный КН для поиска контура

        Returns:
            Строка с номерами точек (например, "н1-н8") или None
        """
        try:
            point_manager = registry.get('M_20')
            if not point_manager:
                log_warning("Fsm_2_7_2: Не удалось получить PointNumberingManager")
                return None

            for feature in layer.getFeatures():
                if feature['Услов_КН'] == uslov_kn:
                    points_str = point_manager.number_points_for_feature(
                        feature,
                        layer.crs()
                    )
                    return points_str

            return None

        except Exception as e:
            log_warning(f"Fsm_2_7_2: Ошибка нумерации точек: {e}")
            return None

    def _update_points_field(
        self,
        layer: QgsVectorLayer,
        uslov_kn: str,
        points_value: str
    ) -> None:
        """Обновить поле Точки для контура

        Args:
            layer: Слой
            uslov_kn: Условный КН контура
            points_value: Значение для поля Точки
        """
        if not layer.isEditable():
            layer.startEditing()

        points_idx = layer.fields().indexOf('Точки')
        if points_idx < 0:
            return

        for feature in layer.getFeatures():
            if feature['Услов_КН'] == uslov_kn:
                layer.changeAttributeValue(feature.id(), points_idx, points_value)
                break

    # ------------------------------------------------------------------
    # Пересоздание точечного слоя
    # ------------------------------------------------------------------

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
            point_manager = registry.get('M_20')
            if not point_manager:
                log_warning("Fsm_2_7_2: Не удалось получить PointNumberingManager")
                return None

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
                project.addMapLayer(point_layer)

                if self.layer_manager:
                    try:
                        self.layer_manager.apply_style_to_layer(point_layer)
                        self.layer_manager.apply_labels_to_layer(point_layer)
                    except Exception as e:
                        log_warning(f"Fsm_2_7_2: Не удалось применить стили: {e}")

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

                # Пропускаем последнюю точку (дублирует первую)
                for pt_idx, point in enumerate(ring[:-1]):
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
