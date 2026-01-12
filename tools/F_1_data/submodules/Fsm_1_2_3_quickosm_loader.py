# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_1_2_3 для загрузки данных OSM (highway и railway) через QuickOSM
Используется функцией F_1_2_Загрузка Web карт
"""

import sys
import os
from typing import Optional, Dict, List, Tuple
from pathlib import Path

from qgis.core import (
    QgsVectorLayer, QgsProject, QgsFeature, QgsGeometry,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsRectangle, QgsWkbTypes, QgsFeedback
)

from Daman_QGIS.utils import log_info, log_warning, log_error, log_success
from Daman_QGIS.managers import LayerManager, get_project_structure_manager


class Fsm_1_2_3_QuickOSMLoader:
    """Загрузчик данных OSM (highway/railway) через QuickOSM"""

    # Константы для типов данных OSM
    HIGHWAY_VALUES = [
        'motorway', 'trunk', 'primary', 'secondary', 'tertiary',
        'unclassified', 'residential', 'motorway_link', 'trunk_link',
        'primary_link', 'secondary_link', 'tertiary_link',
        'living_street', 'service', 'pedestrian', 'bus_guideway',
        'escape', 'raceway', 'road', 'busway'
    ]

    RAILWAY_VALUES = [
        'abandoned', 'construction', 'proposed', 'disused',
        'funicular', 'light_rail', 'miniature', 'monorail',
        'narrow_gauge', 'rail', 'subway', 'tram'
    ]

    def __init__(self, iface, layer_manager: LayerManager = None, project_manager=None, api_manager=None):
        """
        Инициализация загрузчика OSM

        Args:
            iface: Интерфейс QGIS
            layer_manager: Менеджер слоев (опционально)
            project_manager: Менеджер проектов (опционально)
            api_manager: APIManager для получения Overpass fallback servers (опционально)
        """
        self.iface = iface
        self.layer_manager = layer_manager
        self.project_manager = project_manager
        self.api_manager = api_manager
        self.quickosm_available = None  # Lazy initialization - проверяем только при первом использовании

    def _check_quickosm_availability(self) -> bool:
        """
        Проверить доступность плагина QuickOSM

        Returns:
            bool: True если QuickOSM доступен
        """
        try:
            log_info("Fsm_1_2_3: Проверка доступности QuickOSM...")

            # Проверяем стандартный путь установки QuickOSM
            quickosm_path = Path.home() / 'AppData' / 'Roaming' / 'QGIS' / 'QGIS3' / 'profiles' / 'Daman_QGIS' / 'python' / 'plugins' / 'QuickOSM'

            if not quickosm_path.exists():
                log_warning(f"Fsm_1_2_3: QuickOSM не найден по пути: {quickosm_path}")
                log_warning("Fsm_1_2_3: Проверяем альтернативный путь...")

                # Альтернативный путь для разработки
                quickosm_dev_path = Path(__file__).parent.parent.parent.parent / 'external_modules' / 'ВРЕМЕННО' / 'QuickOSM'
                if quickosm_dev_path.exists():
                    log_info(f"Fsm_1_2_3: QuickOSM найден в режиме разработки: {quickosm_dev_path}")
                    quickosm_path = quickosm_dev_path
                else:
                    log_error("Fsm_1_2_3: QuickOSM не найден ни в стандартном, ни в альтернативном пути")
                    return False

            # Добавляем путь к QuickOSM в sys.path если его там нет
            quickosm_str = str(quickosm_path)
            if quickosm_str not in sys.path:
                sys.path.insert(0, quickosm_str)
                log_info(f"Fsm_1_2_3: QuickOSM добавлен в sys.path: {quickosm_str}")

            # Пытаемся импортировать QuickOSM модули с дополнительной защитой от краша
            try:
                log_info("Fsm_1_2_3: Импорт QuickOSM.core.process...")
                from QuickOSM.core.process import process_quick_query
                log_info("Fsm_1_2_3: Импорт QuickOSM.definitions.osm...")
                from QuickOSM.definitions.osm import OsmType, QueryType
                log_success("Fsm_1_2_3: QuickOSM успешно импортирован")
                return True
            except Exception as import_error:
                log_error(f"Fsm_1_2_3: Ошибка импорта модулей QuickOSM: {str(import_error)}")
                return False

        except ImportError as e:
            log_error(f"Fsm_1_2_3: Не удалось импортировать QuickOSM: {str(e)}")
            return False
        except Exception as e:
            log_error(f"Fsm_1_2_3: Ошибка при проверке доступности QuickOSM: {str(e)}")
            return False

    def get_boundary_extent(self) -> Optional[QgsRectangle]:
        """
        Получить bbox границ из слоя L_1_1_3_Границы_работ_500_м

        Returns:
            QgsRectangle: Прямоугольник границ или None
        """
        try:
            # Ищем слой L_1_1_3_Границы_работ_500_м в проекте
            layers = QgsProject.instance().mapLayersByName('L_1_1_3_Границы_работ_500_м')

            if not layers:
                log_error("Fsm_1_2_3: Слой L_1_1_3_Границы_работ_500_м не найден! Загрузка невозможна.")
                return None

            layer = layers[0]
            if not isinstance(layer, QgsVectorLayer):
                log_error("Fsm_1_2_3: Слой L_1_1_3_Границы_работ_500_м не является векторным!")
                return None

            # Проверяем наличие объектов
            if layer.featureCount() == 0:
                log_error("Fsm_1_2_3: Слой L_1_1_3_Границы_работ_500_м пустой! Загрузка невозможна.")
                return None

            # Получаем extent слоя (L_1_1_3 уже содержит буфер 500м)
            layer_extent = layer.extent()

            log_info(f"Fsm_1_2_3: Используется extent слоя L_1_1_3_Границы_работ_500_м для загрузки OSM")
            return layer_extent

        except Exception as e:
            log_error(f"Fsm_1_2_3: Ошибка получения extent границ: {str(e)}")
            return None

    def _transform_extent_to_wgs84(self, extent: QgsRectangle) -> QgsRectangle:
        """
        Трансформировать extent в WGS84 (EPSG:4326)

        Args:
            extent: Исходный extent

        Returns:
            QgsRectangle: Extent в WGS84
        """
        try:
            # ОТКЛЮЧЕНО: Python Stack Trace - Windows fatal exception: access violation
            # Проблема: iface.mapCanvas() вызывает краш
            # canvas = self.iface.mapCanvas()
            # crs_src = canvas.mapSettings().destinationCrs()

            # Получаем CRS напрямую из проекта вместо mapCanvas
            project = QgsProject.instance()
            crs_src = project.crs()

            crs_dest = QgsCoordinateReferenceSystem('EPSG:4326')

            if crs_src == crs_dest:
                return extent

            transform = QgsCoordinateTransform(crs_src, crs_dest, project)
            return transform.transformBoundingBox(extent)

        except Exception as e:
            log_error(f"Fsm_1_2_3: Ошибка трансформации extent в WGS84: {str(e)}")
            return extent

    def _clip_layer_by_boundaries(self, layer: QgsVectorLayer) -> QgsVectorLayer:
        """
        Обрезать слой по extent (bbox) L_1_1_3_Границы_работ_500_м

        Args:
            layer: Исходный слой для обрезки

        Returns:
            QgsVectorLayer: Обрезанный слой или исходный при ошибке
        """
        try:
            # Получаем слой границ
            boundary_layers = QgsProject.instance().mapLayersByName('L_1_1_3_Границы_работ_500_м')
            if not boundary_layers:
                log_warning("Fsm_1_2_3: Слой L_1_1_3 не найден, пропускаем обрезку OSM")
                return layer

            boundary_layer = boundary_layers[0]

            # Проверяем CRS и создаем трансформацию если нужно
            layer_crs = layer.crs()
            boundary_crs = boundary_layer.crs()
            transform = None

            if layer_crs != boundary_crs:
                log_info(f"Fsm_1_2_3: OSM CRS: {layer_crs.authid()}, Границы CRS: {boundary_crs.authid()}")
                transform = QgsCoordinateTransform(layer_crs, boundary_crs, QgsProject.instance())
            else:
                log_info(f"Fsm_1_2_3: OSM и границы в одной CRS: {layer_crs.authid()}")

            # Создаем новый memory слой для результата (в СК границ!)
            clipped_layer = QgsVectorLayer(
                f"{QgsWkbTypes.displayString(layer.wkbType())}?crs={boundary_crs.authid()}",
                layer.name(),
                "memory"
            )

            clipped_provider = clipped_layer.dataProvider()
            clipped_provider.addAttributes(layer.fields())
            clipped_layer.updateFields()

            # Получаем extent (bbox) границ L_1_1_3
            boundary_extent = boundary_layer.extent()

            # Создаем геометрию прямоугольника из extent
            boundary_rect_geom = QgsGeometry.fromRect(boundary_extent)

            log_info(f"Fsm_1_2_3: OSM обрезка по extent L_1_1_3: {boundary_extent.toString()}")

            # Обрезаем объекты по extent (bbox)
            clipped_features = []
            total_features = layer.featureCount()
            clipped_count = 0

            for feature in layer.getFeatures():
                if feature.hasGeometry():
                    geom = QgsGeometry(feature.geometry())  # Создаем копию

                    # Трансформируем геометрию OSM в СК границ
                    if transform:
                        result = geom.transform(transform)
                        if result != 0:
                            log_warning(f"Fsm_1_2_3: Ошибка трансформации геометрии объекта {feature.id()}")
                            continue

                    # Проверяем пересечение с extent (bbox)
                    if geom.intersects(boundary_rect_geom):
                        # Обрезаем геометрию по bbox
                        clipped_geom = geom.intersection(boundary_rect_geom)

                        if not clipped_geom.isEmpty():
                            new_feature = QgsFeature(feature)
                            new_feature.setGeometry(clipped_geom)
                            clipped_features.append(new_feature)
                            clipped_count += 1

            clipped_provider.addFeatures(clipped_features)

            log_info(f"Fsm_1_2_3: OSM обрезка: {total_features} -> {clipped_count} объектов (удалено {total_features - clipped_count})")

            return clipped_layer

        except Exception as e:
            log_error(f"Fsm_1_2_3: Ошибка обрезки OSM слоя: {str(e)}")
            return layer

    def load_osm_layer(
        self,
        key: str,
        values: List[str],
        layer_name: str,
        extent: QgsRectangle
    ) -> Optional[List[QgsVectorLayer]]:
        """
        Загрузить слой OSM через QuickOSM с автоматическим переключением серверов

        ВАЖНО: Может вернуть несколько слоёв, если QuickOSM вернул разные типы геометрии
        (например Lines и MultiPolygons). Каждый тип геометрии сохраняется в отдельный слой.

        Args:
            key: OSM ключ (highway, railway)
            values: Список значений ключа
            layer_name: Базовое имя результирующих слоёв
            extent: Границы загрузки

        Returns:
            List[QgsVectorLayer]: Список загруженных слоёв (по одному на каждый тип геометрии) или None
        """
        # Lazy check - проверяем доступность QuickOSM только при первом использовании
        if self.quickosm_available is None:
            self.quickosm_available = self._check_quickosm_availability()

        if not self.quickosm_available:
            log_error("Fsm_1_2_3: QuickOSM недоступен, пропускаем загрузку")
            return None

        # Получаем список Overpass серверов из api_manager (fallback_group: "overpass_group")
        priority_servers = []

        # Получаем fallback endpoints из M_14 (обязательно должны быть в Base_api_endpoints.json)
        assert self.api_manager is not None, "api_manager не инициализирован"
        fallback_endpoints = self.api_manager.get_fallback_servers("overpass_group")
        assert fallback_endpoints, "Overpass серверы не найдены в Base_api_endpoints.json (fallback_group='overpass_group')"

        priority_servers = [ep['base_url'] for ep in fallback_endpoints if 'base_url' in ep]
        log_info(f"Fsm_1_2_3: Получены Overpass серверы из api_manager: {len(priority_servers)} серверов")

        # Пробуем каждый сервер по очереди
        for server_index, server_url in enumerate(priority_servers, 1):
            result = self._try_load_from_server(key, values, layer_name, extent, server_url)

            if result is not None:
                log_success(f"Fsm_1_2_3: Успешная загрузка с сервера: {server_url}")
                return result

            # Если это не последний сервер, сообщаем что переходим к следующему
            if server_index < len(priority_servers):
                log_warning(f"Fsm_1_2_3: Сервер {server_url} недоступен, переключаемся на следующий...")

        # Все серверы недоступны
        log_error(f"Fsm_1_2_3: Не удалось загрузить '{layer_name}' ни с одного из {len(priority_servers)} серверов")
        return None

    def _try_load_from_server(
        self,
        key: str,
        values: List[str],
        layer_name: str,
        extent: QgsRectangle,
        server_url: str
    ) -> Optional[List[QgsVectorLayer]]:
        """
        Попытка загрузки OSM слоя с конкретного сервера

        Args:
            key: OSM ключ (highway, railway)
            values: Список значений ключа
            layer_name: Имя результирующего слоя
            extent: Границы загрузки
            server_url: URL Overpass API сервера

        Returns:
            QgsVectorLayer или None при ошибке
        """

        try:
            from QuickOSM.core.process import process_quick_query
            from QuickOSM.definitions.osm import OsmType, QueryType, LayerType
            from QuickOSM.definitions.format import Format
            from QuickOSM.core.utilities.tools import set_setting

            # Устанавливаем текущий сервер Overpass API
            set_setting('defaultOAPI', server_url)

            # Трансформируем extent в WGS84 для QuickOSM
            extent_wgs84 = self._transform_extent_to_wgs84(extent)

            # Формируем значение для QuickOSM (через '|' для OR запроса)
            value_query = '|'.join(values)

            # Загружаем только lines и multilinestrings (без points)
            output_geom_types = [LayerType.Lines, LayerType.Multilinestrings]

            # Также разрешаем polygon/multipolygon на случай если OSM вернет их
            output_geom_types.extend([LayerType.Multipolygons])

            # Вызываем QuickOSM для загрузки данных
            # process_quick_query требует dialog с атрибутом feedback_process
            # Создаем минимальный mock-объект для этого
            class MockIface:
                """Mock для iface с методом addCustomActionForLayer"""
                def addCustomActionForLayer(self, action, layer):
                    """Заглушка - не добавляем custom actions"""
                    pass

            class MockDialog:
                def __init__(self):
                    self.feedback_process = QgsFeedback()
                    self.iface = MockIface()  # QuickOSM требует iface для custom actions
                    self.reload_action = None  # Заглушка для reload action

                def set_progress_text(self, text):
                    """Заглушка для отображения прогресса"""
                    log_info(f"QuickOSM: {text}")

                def set_progress_percentage(self, percentage):
                    """Заглушка для отображения процента прогресса"""
                    if percentage % 10 == 0:  # Логируем каждые 10%
                        log_info(f"QuickOSM: {percentage}%")

            mock_dialog = MockDialog()

            # Загружаем ВСЕ объекты с ключом (highway/railway)
            # Фильтрацию по значениям применим после загрузки
            num_layers = process_quick_query(
                dialog=mock_dialog,  # Mock-объект с feedback_process
                query_type=QueryType.BBox,  # BBox для запроса по extent
                key=key,
                value='',  # Пустое значение = все объекты с ключом
                bbox=extent_wgs84,
                osm_objects=[OsmType.Way, OsmType.Relation],  # Way для линий, Relation для сложных объектов
                output_directory=None,  # Загружаем в память
                output_format=None,  # Memory layer
                layer_name=layer_name,
                output_geometry_types=output_geom_types
            )

            # QuickOSM создаёт слои с суффиксами типа геометрии: "name lines", "name multilinestrings"
            # Ищем все слои, которые начинаются с нашего имени
            all_layers = QgsProject.instance().mapLayers().values()
            loaded_layers = [
                layer for layer in all_layers
                if layer.name().startswith(layer_name)
            ]

            # ВАЖНО: Если QuickOSM вернул 0 слоёв, это УСПЕШНЫЙ результат (просто нет данных в этой области)
            # Это НЕ ошибка сервера! Не нужно переключаться на другой сервер.
            # Возвращаем специальное значение "пустой успех" - создаём пустой memory layer
            if not loaded_layers:
                log_info(f"Fsm_1_2_3: Слой '{layer_name}' не содержит данных в указанной области (это нормально)")
                # Создаём пустой memory layer для обозначения "успешной загрузки без данных"
                from qgis.core import QgsVectorLayer, QgsWkbTypes
                empty_layer = QgsVectorLayer("LineString?crs=EPSG:4326", layer_name, "memory")
                empty_layer.setCustomProperty("osm_no_data", True)  # Маркер "нет данных"
                return [empty_layer]

            # QuickOSM может вернуть несколько слоев (lines, multilinestrings, multipolygons)
            # ВСЕГДА объединяем их, группируя по типам геометрии (это также переименовывает слои)
            combined_layers = self._combine_osm_layers(loaded_layers, layer_name)

            # Удаляем исходные слои из проекта
            for layer in loaded_layers:
                QgsProject.instance().removeMapLayer(layer.id())

            # Возвращаем список объединённых слоёв (может быть несколько типов геометрии)
            return combined_layers

        except Exception as e:
            error_msg = str(e)

            # Проверяем, является ли это сетевой ошибкой Overpass API
            if "Gateway Timeout" in error_msg or "NetWorkErrorException" in error_msg:
                log_warning(f"Fsm_1_2_3: Временная проблема с Overpass API для '{layer_name}': {error_msg}")
                log_warning("Fsm_1_2_3: Попробуйте запустить загрузку позже")
            else:
                log_error(f"Fsm_1_2_3: Ошибка загрузки OSM слоя '{layer_name}': {error_msg}")

            return None

    def _combine_osm_layers(
        self,
        layers: List[QgsVectorLayer],
        combined_name: str
    ) -> List[QgsVectorLayer]:
        """
        Объединить несколько OSM слоев, группируя по типам геометрии

        ВАЖНО: QuickOSM может вернуть разные типы геометрии (Lines, MultiPolygons и т.д.)
        для одного запроса. Нельзя смешивать разные типы в одном слое, поэтому
        создаем отдельный слой для каждого типа геометрии.

        Args:
            layers: Список слоев для объединения
            combined_name: Базовое имя результирующих слоёв

        Returns:
            List[QgsVectorLayer]: Список объединённых слоёв (по одному на каждый тип геометрии)
        """
        try:
            # Группируем слои по типу геометрии
            from collections import defaultdict
            layers_by_geom_type = defaultdict(list)

            for layer in layers:
                if layer.featureCount() > 0:
                    geom_type = QgsWkbTypes.geometryType(layer.wkbType())
                    layers_by_geom_type[geom_type].append(layer)

            if not layers_by_geom_type:
                return [layers[0]]

            # Создаем отдельный объединенный слой для каждого типа геометрии
            result_layers = []

            for geom_type, geom_layers in layers_by_geom_type.items():
                geom_type_str = QgsWkbTypes.geometryDisplayString(geom_type)

                # Используем слой с наибольшим количеством объектов как базовый
                base_layer = max(geom_layers, key=lambda l: l.featureCount())
                crs = base_layer.crs()
                geom_type_name = QgsWkbTypes.displayString(base_layer.wkbType())

                # ВАЖНО: ВСЕГДА формируем имя с суффиксом типа геометрии
                # Используем формат Base_layers.json: Le_1_4_1_1_OSM_АД_line, Le_1_4_1_2_OSM_АД_poly
                # Маппинг типов геометрии на суффиксы в Base_layers.json
                if geom_type == QgsWkbTypes.LineGeometry:
                    geom_suffix = "line"
                elif geom_type == QgsWkbTypes.PolygonGeometry:
                    geom_suffix = "poly"
                elif geom_type == QgsWkbTypes.PointGeometry:
                    geom_suffix = "point"
                else:
                    geom_suffix = geom_type_str.lower()

                # Преобразуем L_1_4_1_OSM_АД в Le_1_4_1_X_OSM_АД_suffix
                # L_1_4_1_OSM_АД -> Le_1_4_1_1_OSM_АД_line, Le_1_4_1_2_OSM_АД_poly
                if combined_name == 'L_1_4_1_OSM_АД':
                    if geom_suffix == "line":
                        layer_name = "Le_1_4_1_1_OSM_АД_line"
                    else:  # poly
                        layer_name = "Le_1_4_1_2_OSM_АД_poly"
                elif combined_name == 'L_1_4_2_OSM_ЖД':
                    if geom_suffix == "line":
                        layer_name = "Le_1_4_2_1_OSM_ЖД_line"
                    else:  # poly
                        layer_name = "Le_1_4_2_2_OSM_ЖД_poly"
                else:
                    layer_name = f"{combined_name}_{geom_suffix}"

                # Создаём memory layer для этого типа геометрии
                combined_layer = QgsVectorLayer(
                    f"{geom_type_name}?crs={crs.authid()}",
                    layer_name,
                    "memory"
                )

                # Копируем структуру полей из базового слоя
                combined_layer.dataProvider().addAttributes(base_layer.fields())
                combined_layer.updateFields()

                # Начинаем редактирование для добавления объектов
                combined_layer.startEditing()
                combined_fields = combined_layer.fields()

                # Копируем все объекты из слоёв с таким же типом геометрии
                total_features = 0
                for layer in geom_layers:
                    layer_fields = layer.fields()
                    features = list(layer.getFeatures())

                    # Дополняем недостающие поля значениями NULL
                    fixed_features = []
                    for feat in features:
                        new_feat = QgsFeature(combined_fields)
                        new_feat.setGeometry(feat.geometry())

                        # Копируем атрибуты
                        source_attrs = feat.attributes()
                        target_attrs = [None] * combined_fields.count()

                        # Сопоставляем поля по именам
                        for src_idx, src_field in enumerate(layer_fields):
                            field_name = src_field.name()
                            tgt_idx = combined_fields.indexOf(field_name)
                            if tgt_idx >= 0 and src_idx < len(source_attrs):
                                target_attrs[tgt_idx] = source_attrs[src_idx]

                        new_feat.setAttributes(target_attrs)
                        fixed_features.append(new_feat)

                    # Добавляем объекты
                    if fixed_features:
                        success = combined_layer.addFeatures(fixed_features)
                        if success:
                            total_features += len(fixed_features)
                        else:
                            log_error(f"Fsm_1_2_3: ОШИБКА: Не удалось добавить {len(fixed_features)} объектов")

                # Фиксируем изменения
                commit_result = combined_layer.commitChanges()
                if not commit_result:
                    errors = combined_layer.commitErrors()
                    log_error(f"Fsm_1_2_3: Ошибки commitChanges: {errors}")

                combined_layer.updateExtents()

                result_layers.append(combined_layer)

            return result_layers

        except Exception as e:
            log_error(f"Fsm_1_2_3: Ошибка объединения OSM слоёв: {str(e)}")
            # Возвращаем первый слой как fallback
            return [layers[0]]

    def _filter_osm_layer(
        self,
        layer: QgsVectorLayer,
        key: str,
        allowed_values: List[str]
    ) -> QgsVectorLayer:
        """
        Фильтровать OSM слой по списку разрешённых значений атрибута

        Args:
            layer: Слой для фильтрации
            key: Имя атрибута (highway, railway)
            allowed_values: Список разрешённых значений

        Returns:
            QgsVectorLayer: Отфильтрованный слой
        """
        try:
            initial_count = layer.featureCount()
            log_info(f"Fsm_1_2_3: Фильтрация слоя по атрибуту '{key}': {initial_count} объектов")
            log_info(f"Fsm_1_2_3: Разрешённые значения ({len(allowed_values)}): {', '.join(allowed_values)}")

            # Получаем индекс поля с ключом (highway/railway)
            field_index = layer.fields().indexOf(key)

            if field_index == -1:
                log_warning(f"Fsm_1_2_3: Атрибут '{key}' не найден в слое, пропускаем фильтрацию")
                return layer

            # Включаем редактирование
            layer.startEditing()

            # Удаляем объекты, которые не соответствуют разрешённым значениям
            features_to_delete = []
            for feature in layer.getFeatures():
                value = feature.attribute(key)
                if value not in allowed_values:
                    features_to_delete.append(feature.id())

            # Удаляем объекты
            if features_to_delete:
                layer.deleteFeatures(features_to_delete)
                log_info(f"Fsm_1_2_3: Удалено {len(features_to_delete)} объектов с неразрешёнными значениями")

            # Сохраняем изменения
            layer.commitChanges()

            final_count = layer.featureCount()
            log_success(f"Fsm_1_2_3: Фильтрация завершена: осталось {final_count} объектов (удалено {initial_count - final_count})")

            return layer

        except Exception as e:
            log_error(f"Fsm_1_2_3: Ошибка фильтрации OSM слоя: {str(e)}")
            # Откатываем изменения при ошибке
            if layer.isEditable():
                layer.rollBack()
            return layer

    def save_layer_to_gpkg(
        self,
        layer: QgsVectorLayer,
        layer_name: str
    ) -> bool:
        """
        Сохранить слой в project.gpkg

        Args:
            layer: Слой для сохранения
            layer_name: Имя слоя в GPKG

        Returns:
            bool: True если успешно
        """
        try:
            if not layer or not layer.isValid():
                log_error(f"Fsm_1_2_3: Невалидный слой для сохранения: {layer_name}")
                return False

            # Проверяем специальный маркер "нет данных в области"
            if layer.customProperty("osm_no_data"):
                log_info(f"Fsm_1_2_3: Слой '{layer_name}' не содержит данных (это нормально), пропускаем сохранение")
                return True  # Это успех, просто нет данных

            if layer.featureCount() == 0:
                log_warning(f"Fsm_1_2_3: Слой '{layer_name}' пустой, пропускаем сохранение")
                return False

            # ФИЛЬТРАЦИЯ ПО 'name' ОТКЛЮЧЕНА: Сохраняем все объекты OSM независимо от наличия имени
            # Это включает дороги, тропы, дворы и другие объекты без названия
            log_info(f"Fsm_1_2_3: Сохранение OSM слоя '{layer_name}' без фильтрации: {layer.featureCount()} объектов")

            # Используем LayerManager если доступен
            if self.layer_manager:
                log_info(f"Fsm_1_2_3: Сохранение слоя '{layer_name}' через LayerManager")

                # Сохраняем в project.gpkg
                from qgis.core import QgsVectorFileWriter
                project = QgsProject.instance()

                # Получаем путь к project.gpkg
                gpkg_path = None

                # Пытаемся получить через project_manager напрямую
                if self.project_manager and hasattr(self.project_manager, 'project_db'):
                    if self.project_manager.project_db:
                        gpkg_path = self.project_manager.project_db.gpkg_path
                        log_info(f"Fsm_1_2_3: Получен путь через project_manager: {gpkg_path}")

                # Если не получилось, пытаемся получить через M_19
                if not gpkg_path:
                    project_path = project.homePath()
                    if project_path:
                        structure_manager = get_project_structure_manager()
                        structure_manager.project_root = project_path
                        gpkg_path = structure_manager.get_gpkg_path(create=False)
                        log_info(f"Fsm_1_2_3: Получен путь через M_19: {gpkg_path}")

                if not gpkg_path:
                    log_error("Fsm_1_2_3: Не удалось получить путь к project.gpkg")
                    return False

                log_info(f"Fsm_1_2_3: Путь к GeoPackage: {gpkg_path}")

                # Сохраняем memory layer в GeoPackage
                options = QgsVectorFileWriter.SaveVectorOptions()
                options.driverName = "GPKG"
                options.layerName = layer_name
                options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

                error = QgsVectorFileWriter.writeAsVectorFormatV3(
                    layer,
                    gpkg_path,
                    project.transformContext(),
                    options
                )

                if error[0] != QgsVectorFileWriter.NoError:
                    log_error(f"Fsm_1_2_3: Ошибка сохранения в GeoPackage: {error}")
                    return False

                log_info(f"Fsm_1_2_3: Слой '{layer_name}' сохранён в GeoPackage")

                # Загружаем слой из GeoPackage
                uri = f"{gpkg_path}|layername={layer_name}"
                saved_layer = QgsVectorLayer(uri, layer_name, "ogr")

                if not saved_layer.isValid():
                    log_error(f"Fsm_1_2_3: Не удалось загрузить слой из GeoPackage")
                    return False

                # Удаляем старый memory слой из проекта
                if layer.id() in project.mapLayers():
                    project.removeMapLayer(layer.id())
                    log_info(f"Fsm_1_2_3: Memory слой '{layer_name}' удалён из проекта")

                # Добавляем в правильную группу через LayerManager
                try:
                    saved_layer.setName(layer_name)
                    if self.layer_manager.add_layer(saved_layer, make_readonly=False, auto_number=False, check_precision=False):
                        log_success(f"Fsm_1_2_3: Слой '{layer_name}' добавлен в проект: {saved_layer.featureCount()} объектов")
                        return True
                    else:
                        log_error(f"Fsm_1_2_3: Не удалось добавить слой '{layer_name}' в группу")
                        return False
                except Exception as e:
                    log_error(f"Fsm_1_2_3: Ошибка сохранения слоя '{layer_name}' в GPKG: {str(e)}")
                    return False
            else:
                log_warning("Fsm_1_2_3: LayerManager недоступен, слой остаётся в памяти")
                # Добавляем слой в проект хотя бы в памяти
                QgsProject.instance().addMapLayer(layer)
                log_info(f"Fsm_1_2_3: Слой '{layer_name}' добавлен в проект (memory): {layer.featureCount()} объектов")
                return True

        except Exception as e:
            log_error(f"Fsm_1_2_3: Ошибка сохранения слоя '{layer_name}' в GPKG: {str(e)}")
            return False

    def load_all_osm_layers(self) -> Tuple[bool, int]:
        """
        Загрузить все OSM слои (highway и railway)

        Returns:
            Tuple[bool, int]: (успех, количество загруженных слоёв)
        """
        # Lazy check - проверяем доступность QuickOSM только при первом использовании
        if self.quickosm_available is None:
            self.quickosm_available = self._check_quickosm_availability()

        if not self.quickosm_available:
            log_error("Fsm_1_2_3: QuickOSM недоступен, загрузка невозможна")
            return False, 0

        # Получаем границы загрузки
        extent = self.get_boundary_extent()
        if not extent:
            log_error("Fsm_1_2_3: Не удалось получить границы для загрузки")
            return False, 0

        loaded_count = 0

        # Загружаем highway слой (L_1_4_1_OSM_АД)

        highway_layers = self.load_osm_layer(
            key='highway',
            values=self.HIGHWAY_VALUES,
            layer_name='L_1_4_1_OSM_АД',
            extent=extent
        )

        if highway_layers:
            # Обрабатываем каждый слой (может быть несколько типов геометрии)
            for idx, layer in enumerate(highway_layers):
                # Обрезаем слой по границам L_1_1_2
                clipped_layer = self._clip_layer_by_boundaries(layer)

                # ВАЖНО: Всегда используем имя с суффиксом из layer.name()
                # Имя уже сформировано в _combine_osm_layers: Le_1_4_1_1_OSM_АД_line или Le_1_4_1_2_OSM_АД_poly
                save_name = layer.name()

                if self.save_layer_to_gpkg(clipped_layer, save_name):
                    loaded_count += 1

        # Загружаем railway слой (L_1_4_2_OSM_ЖД)
        railway_layers = self.load_osm_layer(
            key='railway',
            values=self.RAILWAY_VALUES,
            layer_name='L_1_4_2_OSM_ЖД',
            extent=extent
        )

        if railway_layers:
            # Обрабатываем каждый слой (может быть несколько типов геометрии)
            for idx, layer in enumerate(railway_layers):
                # Обрезаем слой по границам L_1_1_2
                clipped_layer = self._clip_layer_by_boundaries(layer)

                # ВАЖНО: Всегда используем имя с суффиксом из layer.name()
                # Имя уже сформировано в _combine_osm_layers: Le_1_4_2_1_OSM_ЖД_line или Le_1_4_2_2_OSM_ЖД_poly
                save_name = layer.name()

                if self.save_layer_to_gpkg(clipped_layer, save_name):
                    loaded_count += 1

        if loaded_count > 0:
            log_success(f"Fsm_1_2_3: Загрузка OSM завершена успешно: {loaded_count} слоя(ёв)")
        else:
            log_warning("Fsm_1_2_3: Загрузка OSM завершена: слои не загружены")

        return loaded_count > 0, loaded_count
