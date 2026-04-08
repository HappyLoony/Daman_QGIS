# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_1_2_3 для загрузки данных OSM через нативный Overpass API + OGR
Используется функцией F_1_2_Загрузка Web карт
"""

import os
import re
import tempfile
from typing import Optional, Dict, List, Tuple
from collections import defaultdict

from qgis.core import (
    QgsVectorLayer, QgsProject, QgsFeature, QgsGeometry,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsRectangle, QgsWkbTypes, Qgis, QgsFeatureRequest
)

from Daman_QGIS.utils import log_info, log_warning, log_error, log_success
from Daman_QGIS.managers import LayerManager, registry


class Fsm_1_2_3_QuickOSMLoader:
    """Загрузчик данных OSM через нативный Overpass API + OGR (data-driven)"""

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

    # --- Boundary и CRS ---

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
                log_warning("Fsm_1_2_3: Слой L_1_1_3_Границы_работ_500_м не найден. Загрузка невозможна.")
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

    def _transform_extent_to_wgs84(self, extent: QgsRectangle) -> Optional[QgsRectangle]:
        """
        Трансформировать extent в WGS84 (EPSG:4326)

        Args:
            extent: Исходный extent

        Returns:
            QgsRectangle в WGS84 или None при ошибке трансформации
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
            return None

    # --- Нативная реализация Overpass API + OGR ---

    @staticmethod
    def _build_overpass_query(
        bbox_wgs84: QgsRectangle,
        key: str,
        values: Optional[List[str]] = None,
        timeout: int = 60
    ) -> str:
        """
        Генерация OQL запроса для Overpass API.

        Args:
            bbox_wgs84: Bounding box в WGS84
            key: OSM ключ (highway, railway, waterway)
            values: Список значений для фильтрации. None/[] = все объекты с ключом
            timeout: Таймаут Overpass запроса (секунды, по умолчанию 60)
        """
        # Валидация ключа: alphanumeric, underscores, colons (стандарт OSM)
        if not re.match(r'^[a-zA-Z_:][a-zA-Z0-9_:]*$', key):
            log_error(f"Fsm_1_2_3: Invalid OSM key format: {key}")
            raise ValueError(f"Invalid OSM key: {key}")

        bbox_str = (
            f"({bbox_wgs84.yMinimum()},{bbox_wgs84.xMinimum()},"
            f"{bbox_wgs84.yMaximum()},{bbox_wgs84.xMaximum()})"
        )

        # Фильтрация values на стороне Overpass через regex
        if values:
            escaped_values = [re.escape(v) for v in values]
            values_regex = '|'.join(escaped_values)
            tag_filter = f'["{key}"~"^({values_regex})$"]'
        else:
            tag_filter = f'["{key}"]'

        return (
            f"[out:xml][timeout:{timeout}];\n"
            f"(\n"
            f"  way{tag_filter}{bbox_str};\n"
            f"  relation{tag_filter}{bbox_str};\n"
            f");\n"
            f"(._;>;);\n"
            f"out body;"
        )

    def _download_osm_data(self, query: str, server_url: str, timeout: int = 120) -> str:
        """
        Загрузка OSM данных через Overpass API (POST).

        Args:
            query: OQL запрос (результат _build_overpass_query)
            server_url: URL сервера, например "https://overpass-api.de/api/"
            timeout: HTTP таймаут (секунды). Должен быть >= Overpass timeout в запросе

        Returns:
            str: Путь к временному .osm файлу

        Raises:
            Exception: При ошибках Overpass (timeout, memory, rate limit)
        """
        import requests as req
        from Daman_QGIS.constants import PLUGIN_VERSION

        # POST к /interpreter с data= в теле запроса
        interpreter_url = server_url.rstrip('/') + '/interpreter'

        headers = {
            'User-Agent': f'Daman_QGIS/{PLUGIN_VERSION} (QGIS Plugin; overpass-loader)'
        }

        response = req.post(
            interpreter_url,
            data={'data': query},
            timeout=timeout,
            headers=headers
        )
        response.raise_for_status()

        # ВАЖНО: используем response.content (bytes), а не response.text
        # Overpass API возвращает Content-Type: application/osm3s+xml без charset.
        # requests может декодировать как ISO-8859-1, повредив кириллицу.
        raw_content = response.content

        # Проверка на runtime errors (Overpass возвращает 200 OK даже при ошибках!)
        content_str = raw_content.decode('utf-8', errors='replace')
        if 'runtime error' in content_str:
            if 'Query timed out' in content_str:
                raise Exception(f"Overpass timeout на {server_url}")
            if 'out of memory' in content_str:
                raise Exception(f"Overpass out of memory на {server_url}")
            if 'rate_limited' in content_str.lower():
                raise Exception(f"Overpass rate limit на {server_url}")
            error_snippet = content_str[:200].replace('\n', ' ')
            raise Exception(f"Overpass runtime error на {server_url}: {error_snippet}")

        # Проверяем что получили XML, а не HTML с ошибкой
        if not content_str.strip().startswith('<?xml'):
            raise Exception(f"Overpass вернул не-XML ответ на {server_url}")

        # Сохраняем во временный файл (бинарный режим!)
        with tempfile.NamedTemporaryFile(
            suffix='.osm', delete=False, mode='wb'
        ) as f:
            f.write(raw_content)
            return f.name

    def _load_osm_via_ogr(self, osm_file_path: str, layer_name: str) -> List[QgsVectorLayer]:
        """
        Загрузка .osm файла через OGR (встроенный в QGIS).

        Returns:
            List[QgsVectorLayer]: Список загруженных слоёв (memory copy)
        """
        result_layers = []
        target_layer_types = ['lines', 'multilinestrings', 'multipolygons']

        for layer_type in target_layer_types:
            uri = f"{osm_file_path}|layername={layer_type}"
            ogr_layer = QgsVectorLayer(uri, f"{layer_name}_{layer_type}", "ogr")

            if not ogr_layer.isValid():
                continue

            # OGR OSM driver может вернуть -1 (unknown count) вместо 0
            if ogr_layer.featureCount() == 0:
                continue

            # Копируем в memory layer (OGR слой привязан к файлу)
            mem_layer = ogr_layer.materialize(QgsFeatureRequest())
            if not mem_layer or not mem_layer.isValid():
                continue

            # После materialize featureCount() всегда точный
            if mem_layer.featureCount() == 0:
                continue

            mem_layer.setName(f"{layer_name}_{layer_type}")
            result_layers.append(mem_layer)
            log_info(
                f"Fsm_1_2_3: OGR загружен {layer_type}: "
                f"{mem_layer.featureCount()} объектов"
            )

        return result_layers

    def _cleanup_osm_file(self, osm_file_path: str):
        """Удаление временного .osm файла"""
        try:
            if osm_file_path and os.path.exists(osm_file_path):
                os.remove(osm_file_path)
        except OSError as e:
            log_warning(f"Fsm_1_2_3: Не удалось удалить временный файл {osm_file_path}: {e}")

    def _find_sublayers_in_base(self, layer_name: str) -> Dict[str, str]:
        """
        Поиск sublayer имён в Base_layers.json по parent layer_name.

        Args:
            layer_name: Имя родительского слоя, например "L_1_4_1_OSM_Дороги"

        Returns:
            Dict маппинг геометрии к full_name:
            {'line': 'Le_1_4_1_1_OSM_АД_line', 'poly': 'Le_1_4_1_2_OSM_АД_poly'}
        """
        parts = layer_name.split('_')
        if len(parts) < 4:
            log_warning(f"Fsm_1_2_3: Не удалось распарсить layer_name: {layer_name}")
            return {}

        group_num = parts[2]   # "4"
        layer_num = parts[3]   # "1"

        from Daman_QGIS.managers import get_reference_managers
        layer_ref = get_reference_managers().layer
        all_layers = layer_ref.get_base_layers()

        sublayers: Dict[str, str] = {}
        for entry in all_layers:
            if (entry.get('group_num') == group_num and
                    entry.get('layer_num') == layer_num and
                    entry.get('full_name', '').startswith('Le_')):
                geom = entry.get('geometry_type', '')
                if 'Line' in geom:
                    sublayers['line'] = entry['full_name']
                elif 'Polygon' in geom:
                    sublayers['poly'] = entry['full_name']

        return sublayers

    # --- Clip ---

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

            # Определяем идентификатор CRS для логирования
            boundary_crs_id = boundary_crs.authid() or boundary_crs.description() or "custom CRS"

            if layer_crs != boundary_crs:
                log_info(f"Fsm_1_2_3: OSM CRS: {layer_crs.authid()}, Границы CRS: {boundary_crs_id}")
                # Двухшаговая трансформация через EPSG:3857 для использования
                # зарегистрированного pipeline (addCoordinateOperation 3857→project).
                # Прямая 4326→project использует towgs84 (~119м ошибка).
                epsg_3857 = QgsCoordinateReferenceSystem("EPSG:3857")
                transform_to_3857 = QgsCoordinateTransform(layer_crs, epsg_3857, QgsProject.instance())
                transform = QgsCoordinateTransform(epsg_3857, boundary_crs, QgsProject.instance())
                log_info(f"Fsm_1_2_3: Hybrid path: {layer_crs.authid()} → EPSG:3857 → {boundary_crs_id}")
            else:
                transform_to_3857 = None
                log_info(f"Fsm_1_2_3: OSM и границы в одной CRS: {boundary_crs_id}")

            # Создаем новый memory слой для результата (в СК границ!)
            # Используем Multi тип: intersection() может вернуть Multi вариант
            multi_type = QgsWkbTypes.multiType(layer.wkbType())
            crs_param = boundary_crs.authid() if boundary_crs.authid() else ""
            clipped_layer = QgsVectorLayer(
                f"{QgsWkbTypes.displayString(multi_type)}?crs={crs_param}",
                layer.name(),
                "memory"
            )
            # Для пользовательских МСК без EPSG кода authid() пуст —
            # явно задаём CRS из слоя границ
            if not boundary_crs.authid():
                clipped_layer.setCrs(boundary_crs)

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
                    # Hybrid: 4326 → 3857 → project (для pipeline)
                    if transform_to_3857:
                        result = geom.transform(transform_to_3857)
                        if result != 0:
                            log_warning(f"Fsm_1_2_3: Ошибка трансформации 4326→3857 объекта {feature.id()}")
                            continue
                    if transform:
                        result = geom.transform(transform)
                        if result != 0:
                            log_warning(f"Fsm_1_2_3: Ошибка трансформации 3857→project объекта {feature.id()}")
                            continue

                    # Проверяем пересечение с extent (bbox)
                    if geom.intersects(boundary_rect_geom):
                        # Обрезаем геометрию по bbox
                        clipped_geom = geom.intersection(boundary_rect_geom)

                        if not clipped_geom.isEmpty():
                            # intersection() может вернуть тип, отличный от входного
                            # (например GeometryCollection при касании угла,
                            #  или LineString при polygon edge collinear с bbox)
                            target_geom_type = QgsWkbTypes.geometryType(layer.wkbType())
                            result_geom_type = QgsWkbTypes.geometryType(clipped_geom.wkbType())

                            if result_geom_type != target_geom_type:
                                # Пытаемся извлечь совместимые части из GeometryCollection
                                if clipped_geom.wkbType() == QgsWkbTypes.GeometryCollection:
                                    parts = [
                                        QgsGeometry(part)
                                        for part in clipped_geom.asGeometryCollection()
                                        if QgsWkbTypes.geometryType(part.wkbType()) == target_geom_type
                                    ]
                                    if not parts:
                                        continue
                                    clipped_geom = QgsGeometry.collectGeometry(parts)
                                else:
                                    # Тип полностью несовместим (Point вместо Polygon) -- пропускаем
                                    continue

                            if not clipped_geom.isMultipart():
                                clipped_geom.convertToMultiType()
                            new_feature = QgsFeature(feature)
                            new_feature.setGeometry(clipped_geom)
                            clipped_features.append(new_feature)
                            clipped_count += 1

            if clipped_features:
                success, added = clipped_provider.addFeatures(clipped_features)
                if not success:
                    log_warning(f"Fsm_1_2_3: addFeatures вернул ошибку при обрезке")

            actual_count = clipped_layer.featureCount()
            log_info(f"Fsm_1_2_3: OSM обрезка: {total_features} -> {actual_count} объектов (удалено {total_features - actual_count})")

            return clipped_layer

        except Exception as e:
            log_error(f"Fsm_1_2_3: Ошибка обрезки OSM слоя: {str(e)}")
            return layer

    # --- Объединение линейных сегментов ---

    @staticmethod
    def _extract_tag_value(other_tags: str, tag_name: str) -> str:
        """
        Извлечь значение тега из hstore-строки other_tags.

        Формат OGR: "surface"=>"gravel","lanes"=>"2"

        Args:
            other_tags: hstore-строка из OGR OSM driver
            tag_name: имя тега (surface, lanes, oneway...)

        Returns:
            Значение тега или пустая строка если не найден
        """
        if not other_tags or not tag_name:
            return ''
        match = re.search(rf'"{re.escape(tag_name)}"\s*=>\s*"([^"]*)"', other_tags)
        return match.group(1) if match else ''

    @staticmethod
    def _find_connected_components(
        features: List[QgsFeature]
    ) -> List[List[QgsFeature]]:
        """
        Поиск пространственно связных компонент (Union-Find).

        Группирует features, геометрии которых intersects() (включая touches).
        Транзитивно: если A intersects B и B intersects C, то [A, B, C] = одна компонента.

        Args:
            features: список features для группировки

        Returns:
            Список групп (каждая группа = list of QgsFeature)
        """
        n = len(features)
        if n <= 1:
            return [features] if features else []

        if n > 500:
            log_warning(
                f"Fsm_1_2_3: Большая группа connected components: {n} features. "
                f"O(n^2) попарное сравнение может быть медленным."
            )

        # Union-Find
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        # Кэш геометрий
        geoms = [f.geometry() for f in features]

        # Попарная проверка связности
        for i in range(n):
            for j in range(i + 1, n):
                # intersects() включает touches() по DE-9IM
                if geoms[i].intersects(geoms[j]):
                    union(i, j)

        # Сборка компонент
        components: Dict[int, List[QgsFeature]] = defaultdict(list)
        for i in range(n):
            components[find(i)].append(features[i])

        return list(components.values())

    def _merge_line_segments(
        self,
        layer: QgsVectorLayer,
        key: str
    ) -> QgsVectorLayer:
        """
        Объединить связанные OSM линейные сегменты.

        OSM way = один сегмент. Дорога из 10 ways = 10 отрезков.
        Метод объединяет их в MultiLineString через collectGeometry + mergeLines.

        Два режима:
        - Named features: группировка по (key_value, name)
        - Unnamed features (name=NULL): группировка по (key_value, surface),
          затем поиск пространственно связных компонент (Union-Find).
          Мерджатся только touches/intersects сегменты с одинаковым surface.

        Args:
            layer: Обрезанный memory layer с OSM линиями
            key: Имя поля OSM ключа (highway, railway)

        Returns:
            QgsVectorLayer: Новый слой с объединёнными features, или исходный при ошибке
        """
        try:
            # Guard: только Line geometry
            geom_type = QgsWkbTypes.geometryType(layer.wkbType())
            if geom_type != Qgis.GeometryType.Line:
                return layer

            initial_count = layer.featureCount()
            if initial_count == 0:
                return layer

            # Guard: проверяем наличие поля key
            fields = layer.fields()
            key_idx = fields.indexOf(key)
            name_idx = fields.indexOf('name')

            if key_idx == -1:
                log_warning(f"Fsm_1_2_3: Поле '{key}' не найдено в слое, пропуск merge")
                return layer

            # --- Группировка features ---
            groups: Dict[Tuple[str, str], List[QgsFeature]] = defaultdict(list)
            unnamed_features: List[QgsFeature] = []

            for feature in layer.getFeatures():
                key_value = feature.attribute(key)
                name_value = feature.attribute('name') if name_idx >= 0 else None

                # Объединяем только features С именем
                if name_value and str(name_value).strip():
                    group_key = (str(key_value or ''), str(name_value).strip())
                    groups[group_key].append(feature)
                else:
                    unnamed_features.append(feature)

            # --- Создаём output layer ---
            multi_type = QgsWkbTypes.multiType(layer.wkbType())
            crs = layer.crs()
            crs_param = crs.authid() if crs.authid() else ""
            merged_layer = QgsVectorLayer(
                f"{QgsWkbTypes.displayString(multi_type)}?crs={crs_param}",
                layer.name(),
                "memory"
            )
            if not crs.authid():
                merged_layer.setCrs(crs)

            provider = merged_layer.dataProvider()
            provider.addAttributes(fields)
            merged_layer.updateFields()

            result_features: List[QgsFeature] = []
            merged_groups_count = 0

            # --- Named groups: merge ---
            for (kv, nm), group_features in groups.items():
                if len(group_features) == 1:
                    # Одиночный feature -- просто копируем
                    feat = QgsFeature(fields)
                    geom = QgsGeometry(group_features[0].geometry())
                    if not geom.isMultipart():
                        geom.convertToMultiType()
                    feat.setGeometry(geom)
                    feat.setAttributes(group_features[0].attributes())
                    result_features.append(feat)
                else:
                    # Несколько features: collectGeometry + mergeLines
                    geoms = [QgsGeometry(f.geometry()) for f in group_features]
                    collected = QgsGeometry.collectGeometry(geoms)
                    merged_geom = collected.mergeLines()

                    if merged_geom.isEmpty():
                        # Fallback: оставляем collected
                        merged_geom = collected

                    if not merged_geom.isMultipart():
                        merged_geom.convertToMultiType()

                    # Атрибуты от первого feature в группе
                    feat = QgsFeature(fields)
                    feat.setGeometry(merged_geom)
                    feat.setAttributes(group_features[0].attributes())

                    # osm_id от одного из N way-ов вводит в заблуждение --
                    # лучше NULL чем произвольный ID одного сегмента
                    osm_id_idx = fields.indexOf('osm_id')
                    if osm_id_idx >= 0:
                        feat.setAttribute(osm_id_idx, None)

                    result_features.append(feat)
                    merged_groups_count += 1

            # --- Unnamed features: merge spatially connected with same (key, surface) ---
            other_tags_idx = fields.indexOf('other_tags')
            unnamed_groups: Dict[Tuple[str, str], List[QgsFeature]] = defaultdict(list)

            for uf in unnamed_features:
                kv = str(uf.attribute(key) or '')
                other = str(uf.attribute('other_tags') or '') if other_tags_idx >= 0 else ''
                surface = self._extract_tag_value(other, 'surface')
                unnamed_groups[(kv, surface)].append(uf)

            unnamed_merged_count = 0

            for (kv, surf), group_feats in unnamed_groups.items():
                if len(group_feats) == 1:
                    # Одиночный -- копировать as-is
                    feat = QgsFeature(fields)
                    geom = QgsGeometry(group_feats[0].geometry())
                    if not geom.isMultipart():
                        geom.convertToMultiType()
                    feat.setGeometry(geom)
                    feat.setAttributes(group_feats[0].attributes())
                    result_features.append(feat)
                    continue

                # Несколько features с одинаковым (key, surface):
                # найти пространственно связные компоненты
                components = self._find_connected_components(group_feats)

                for component in components:
                    if len(component) == 1:
                        feat = QgsFeature(fields)
                        geom = QgsGeometry(component[0].geometry())
                        if not geom.isMultipart():
                            geom.convertToMultiType()
                        feat.setGeometry(geom)
                        feat.setAttributes(component[0].attributes())
                        result_features.append(feat)
                    else:
                        # collectGeometry + mergeLines
                        geoms = [QgsGeometry(f.geometry()) for f in component]
                        collected = QgsGeometry.collectGeometry(geoms)
                        merged_geom = collected.mergeLines()

                        if merged_geom.isEmpty():
                            merged_geom = collected

                        if not merged_geom.isMultipart():
                            merged_geom.convertToMultiType()

                        # Атрибуты от самого длинного feature в компоненте
                        longest = max(component, key=lambda f: f.geometry().length())
                        feat = QgsFeature(fields)
                        feat.setGeometry(merged_geom)
                        feat.setAttributes(longest.attributes())

                        osm_id_idx = fields.indexOf('osm_id')
                        if osm_id_idx >= 0:
                            feat.setAttribute(osm_id_idx, None)

                        result_features.append(feat)
                        unnamed_merged_count += 1

            # --- Сохраняем результат ---
            if result_features:
                success, added = provider.addFeatures(result_features)
                if not success:
                    log_warning("Fsm_1_2_3: addFeatures вернул ошибку при merge")
                    return layer

            final_count = merged_layer.featureCount()
            log_info(
                f"Fsm_1_2_3: Line merge: {initial_count} -> {final_count} "
                f"({merged_groups_count} named merged, "
                f"{unnamed_merged_count} unnamed merged, "
                f"{len(unnamed_features)} unnamed total)"
            )

            return merged_layer

        except Exception as e:
            log_error(f"Fsm_1_2_3: Ошибка merge линейных сегментов: {str(e)}")
            return layer

    # --- Загрузка с серверов и объединение слоёв ---

    def _try_load_from_server(
        self,
        key: str,
        values: List[str],
        layer_name: str,
        extent: QgsRectangle,
        server_url: str
    ) -> Optional[List[QgsVectorLayer]]:
        """
        Попытка загрузки OSM слоя с конкретного сервера через Overpass API + OGR.

        Args:
            key: OSM ключ (highway, railway)
            values: Список значений ключа
            layer_name: Имя результирующего слоя
            extent: Границы загрузки
            server_url: URL Overpass API сервера

        Returns:
            List[QgsVectorLayer] или None при ошибке сервера
        """
        osm_file = None
        try:
            # 1. Трансформируем extent в WGS84
            extent_wgs84 = self._transform_extent_to_wgs84(extent)
            if extent_wgs84 is None:
                log_error("Fsm_1_2_3: Не удалось трансформировать extent в WGS84, загрузка отменена")
                return None

            # 2. Генерируем OQL запрос
            query = self._build_overpass_query(extent_wgs84, key, values)
            log_info(f"Fsm_1_2_3: Загрузка '{key}' с {server_url}")

            # 3. Скачиваем данные
            osm_file = self._download_osm_data(query, server_url)

            # 4. Загружаем через OGR
            layers = self._load_osm_via_ogr(osm_file, layer_name)

            # Если нет данных в области -- это нормально, не ошибка сервера
            if not layers:
                log_info(f"Fsm_1_2_3: Слой '{layer_name}' не содержит данных в указанной области (это нормально)")
                empty_layer = QgsVectorLayer("LineString?crs=EPSG:4326", layer_name, "memory")
                empty_layer.setCustomProperty("osm_no_data", True)
                return [empty_layer]

            return layers

        except Exception as e:
            error_msg = str(e)

            # Сетевые ошибки -- пробуем следующий сервер
            if any(kw in error_msg for kw in ("timeout", "Timeout", "ConnectionError", "Connection", "runtime error", "out of memory")):
                log_warning(f"Fsm_1_2_3: Сервер {server_url} недоступен: {error_msg}")
            else:
                log_error(f"Fsm_1_2_3: Ошибка загрузки OSM '{layer_name}' с {server_url}: {error_msg}")

            return None

        finally:
            if osm_file:
                self._cleanup_osm_file(osm_file)

    def _combine_osm_layers(
        self,
        layers: List[QgsVectorLayer],
        combined_name: str,
        sublayer_map: Optional[Dict[str, str]] = None
    ) -> List[QgsVectorLayer]:
        """
        Объединить несколько OSM слоев, группируя по типам геометрии.

        OGR возвращает lines, multilinestrings, multipolygons как отдельные слои.
        Группируем по типу геометрии (Line/Polygon) и переименовываем через sublayer_map.

        Args:
            layers: Список слоев для объединения
            combined_name: Базовое имя результирующих слоёв
            sublayer_map: Маппинг геометрии к имени sublayer
                          {'line': 'Le_1_4_1_1_OSM_АД_line', 'poly': 'Le_1_4_1_2_OSM_АД_poly'}

        Returns:
            List[QgsVectorLayer]: Список объединённых слоёв (по одному на каждый тип геометрии)
        """
        try:
            # Группируем слои по типу геометрии
            layers_by_geom_type: Dict[int, List[QgsVectorLayer]] = defaultdict(list)

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

                # Маппинг типов геометрии на суффиксы
                if geom_type == Qgis.GeometryType.Line:
                    geom_suffix = "line"
                elif geom_type == Qgis.GeometryType.Polygon:
                    geom_suffix = "poly"
                elif geom_type == Qgis.GeometryType.Point:
                    geom_suffix = "point"
                else:
                    geom_suffix = geom_type_str.lower()

                # Data-driven: имя из sublayer_map (Base_layers.json)
                if sublayer_map and geom_suffix in sublayer_map:
                    layer_name = sublayer_map[geom_suffix]
                else:
                    layer_name = f"{combined_name}_{geom_suffix}"

                # Создаём memory layer для этого типа геометрии
                crs_param = crs.authid() if crs.authid() else ""
                combined_layer = QgsVectorLayer(
                    f"{geom_type_name}?crs={crs_param}",
                    layer_name,
                    "memory"
                )
                if not crs.authid():
                    combined_layer.setCrs(crs)

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
                            log_error(f"Fsm_1_2_3: Не удалось добавить {len(fixed_features)} объектов")

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

    # --- Filter (safety net) ---

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

    # --- Сохранение в GPKG ---

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
                log_info(f"Fsm_1_2_3: Слой '{layer_name}' пустой, пропускаем сохранение")
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
                    project_path = os.path.normpath(project.homePath()) if project.homePath() else ""
                    if project_path:
                        structure_manager = registry.get('M_19')
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

    def save_layer_to_gpkg_only(
        self,
        layer: QgsVectorLayer,
        layer_name: str,
        gpkg_path: str
    ) -> bool:
        """
        Сохранить слой в GeoPackage (только запись, без добавления в проект).

        Thread-safe: не вызывает addMapLayer / LayerManager.
        Используется из background thread (Fsm_1_2_10).

        Args:
            layer: Слой для сохранения
            layer_name: Имя слоя в GPKG
            gpkg_path: Путь к GeoPackage файлу

        Returns:
            bool: True если успешно
        """
        try:
            if not layer or not layer.isValid():
                log_error(f"Fsm_1_2_3: Невалидный слой для сохранения: {layer_name}")
                return False

            # Маркер "нет данных в области" -- пропускаем, это не ошибка
            if layer.customProperty("osm_no_data"):
                log_info(f"Fsm_1_2_3: Слой '{layer_name}' не содержит данных (это нормально), пропускаем сохранение")
                return True

            if layer.featureCount() == 0:
                log_info(f"Fsm_1_2_3: Слой '{layer_name}' пустой, пропускаем сохранение")
                return False

            log_info(f"Fsm_1_2_3: Сохранение OSM слоя '{layer_name}' в GPKG: {layer.featureCount()} объектов")

            from qgis.core import QgsVectorFileWriter

            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = layer_name
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

            error = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                gpkg_path,
                QgsProject.instance().transformContext(),
                options
            )

            if error[0] != QgsVectorFileWriter.NoError:
                log_error(f"Fsm_1_2_3: Ошибка записи в GeoPackage: {error}")
                return False

            log_info(f"Fsm_1_2_3: Слой '{layer_name}' записан в GeoPackage")
            return True

        except Exception as e:
            log_error(f"Fsm_1_2_3: Ошибка записи слоя '{layer_name}' в GPKG: {str(e)}")
            return False

    # --- Публичный API ---

    def load_osm_layer(
        self,
        key: str,
        values: List[str],
        layer_name: str,
        sublayer_map: Dict[str, str],
        extent: QgsRectangle,
        server_urls: List[str]
    ) -> Optional[List[QgsVectorLayer]]:
        """
        Загрузить слой OSM с автоматическим переключением серверов.

        Args:
            key: OSM ключ (highway, railway, waterway)
            values: Список значений ключа (пустой = все объекты с ключом)
            layer_name: Базовое имя результирующих слоёв
            sublayer_map: Маппинг геометрии к имени sublayer из Base_layers.json
            extent: Границы загрузки
            server_urls: Список URL Overpass серверов (по приоритету)

        Returns:
            List[QgsVectorLayer]: Список загруженных слоёв или None
        """
        log_info(f"Fsm_1_2_3: Загрузка OSM '{key}' ({layer_name}), серверов: {len(server_urls)}")

        # Пробуем каждый сервер по очереди
        for server_index, server_url in enumerate(server_urls, 1):
            result = self._try_load_from_server(key, values, layer_name, extent, server_url)

            if result is not None:
                log_success(f"Fsm_1_2_3: Успешная загрузка с сервера: {server_url}")

                # Если osm_no_data — возвращаем как есть (нет данных в области)
                if result and result[0].customProperty("osm_no_data"):
                    return result

                # Объединяем OGR слои по типу геометрии и переименовываем
                return self._combine_osm_layers(result, layer_name, sublayer_map)

            # Если это не последний сервер, сообщаем что переходим к следующему
            if server_index < len(server_urls):
                log_warning(f"Fsm_1_2_3: Сервер {server_url} недоступен, переключаемся на следующий...")

        # Все серверы недоступны
        log_error(f"Fsm_1_2_3: Не удалось загрузить '{layer_name}' ни с одного из {len(server_urls)} серверов")
        return None

    def load_all_osm_layers(self) -> Tuple[bool, int]:
        """
        Загрузить все OSM слои (data-driven из Base_api_endpoints.json).

        Returns:
            Tuple[bool, int]: (успех, количество загруженных слоёв)
        """
        # Получаем границы загрузки
        extent = self.get_boundary_extent()
        if not extent:
            log_error("Fsm_1_2_3: Не удалось получить границы для загрузки")
            return False, 0

        # 1. Получить все primary OVERPASS endpoints из Base_api_endpoints.json
        assert self.api_manager is not None, "Fsm_1_2_3: api_manager не инициализирован"
        overpass_endpoints = self.api_manager.get_endpoints_by_group("OVERPASS")

        if not overpass_endpoints:
            log_error("Fsm_1_2_3: OVERPASS endpoints не найдены в Base_api_endpoints.json")
            return False, 0

        # 2. Пинг серверов и сортировка по латентности
        server_urls = self.api_manager.ping_and_sort_overpass_servers()
        if not server_urls:
            log_error("Fsm_1_2_3: Все Overpass серверы недоступны")
            return False, 0

        log_info(f"Fsm_1_2_3: Найдено {len(overpass_endpoints)} OSM endpoint(ов), {len(server_urls)} сервер(ов)")

        loaded_count = 0

        for ep in overpass_endpoints:
            key = ep['category_id']
            values_str = ep.get('osm_values', '')
            values = [v for v in values_str.split(';') if v] if values_str else []
            layer_name = ep['layer_name']

            # Найти sublayer имена в Base_layers.json
            sublayer_map = self._find_sublayers_in_base(layer_name)

            layers = self.load_osm_layer(
                key=key,
                values=values,
                layer_name=layer_name,
                sublayer_map=sublayer_map,
                extent=extent,
                server_urls=server_urls
            )

            if layers:
                for layer in layers:
                    # Обрезаем слой по границам L_1_1_3
                    clipped_layer = self._clip_layer_by_boundaries(layer)

                    # Объединяем связанные линейные сегменты с одинаковым именем
                    clipped_layer = self._merge_line_segments(clipped_layer, key)

                    # Имя уже сформировано в _combine_osm_layers через sublayer_map
                    save_name = layer.name()

                    if self.save_layer_to_gpkg(clipped_layer, save_name):
                        loaded_count += 1

        if loaded_count > 0:
            log_success(f"Fsm_1_2_3: Загрузка OSM завершена: {loaded_count} слоя(ёв)")
        else:
            log_warning("Fsm_1_2_3: Загрузка OSM завершена: слои не загружены")

        return loaded_count > 0, loaded_count

    def load_all_osm_layers_bg(self, gpkg_path: str) -> Tuple[int, List[str]]:
        """
        Загрузить все OSM слои в background thread (без добавления в проект).

        Аналог load_all_osm_layers(), но:
        - Сохраняет в GPKG через save_layer_to_gpkg_only() (thread-safe)
        - НЕ вызывает LayerManager.add_layer() / addMapLayer()
        - Возвращает список имён слоёв для добавления в main thread

        Args:
            gpkg_path: Путь к GeoPackage файлу

        Returns:
            Tuple[int, List[str]]: (количество загруженных, список имён слоёв)
        """
        loaded_layer_names: List[str] = []

        # Получаем границы загрузки
        extent = self.get_boundary_extent()
        if not extent:
            log_error("Fsm_1_2_3: Не удалось получить границы для загрузки")
            return 0, []

        # 1. Получить все primary OVERPASS endpoints
        assert self.api_manager is not None, "Fsm_1_2_3: api_manager не инициализирован"
        overpass_endpoints = self.api_manager.get_endpoints_by_group("OVERPASS")

        if not overpass_endpoints:
            log_error("Fsm_1_2_3: OVERPASS endpoints не найдены в Base_api_endpoints.json")
            return 0, []

        # 2. Пинг серверов и сортировка по латентности
        server_urls = self.api_manager.ping_and_sort_overpass_servers()
        if not server_urls:
            log_error("Fsm_1_2_3: Все Overpass серверы недоступны")
            return 0, []

        log_info(f"Fsm_1_2_3: [BG] Найдено {len(overpass_endpoints)} OSM endpoint(ов), {len(server_urls)} сервер(ов)")

        loaded_count = 0

        for ep in overpass_endpoints:
            key = ep['category_id']
            values_str = ep.get('osm_values', '')
            values = [v for v in values_str.split(';') if v] if values_str else []
            layer_name = ep['layer_name']

            # Найти sublayer имена в Base_layers.json
            sublayer_map = self._find_sublayers_in_base(layer_name)

            layers = self.load_osm_layer(
                key=key,
                values=values,
                layer_name=layer_name,
                sublayer_map=sublayer_map,
                extent=extent,
                server_urls=server_urls
            )

            if layers:
                for layer in layers:
                    # Обрезаем слой по границам L_1_1_3
                    clipped_layer = self._clip_layer_by_boundaries(layer)

                    # Объединяем связанные линейные сегменты с одинаковым именем
                    clipped_layer = self._merge_line_segments(clipped_layer, key)

                    # Имя уже сформировано в _combine_osm_layers через sublayer_map
                    save_name = layer.name()

                    if self.save_layer_to_gpkg_only(clipped_layer, save_name, gpkg_path):
                        loaded_layer_names.append(save_name)
                        loaded_count += 1

        if loaded_count > 0:
            log_success(f"Fsm_1_2_3: [BG] Загрузка OSM завершена: {loaded_count} слоя(ёв)")
        else:
            log_warning("Fsm_1_2_3: [BG] Загрузка OSM завершена: слои не загружены")

        return loaded_count, loaded_layer_names
