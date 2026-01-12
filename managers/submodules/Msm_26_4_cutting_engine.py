# -*- coding: utf-8 -*-
"""
Msm_26_4 - Движок нарезки ЗПР

Основной движок выполнения нарезки:
- Первичная нарезка по ЗУ (Раздел и НГС)
- Дополнительная нарезка по overlay слоям
- Нумерация характерных точек контуров
- Координация работы других субмодулей

Перенесено из Fsm_3_1_4_cutting_engine
"""

import time
from typing import Dict, List, Tuple, Optional, Any

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsCoordinateReferenceSystem,
    QgsSpatialIndex,
)

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers import PointNumberingManager, WorkTypeAssignmentManager, LayerType, OksZuAnalysisManager

# Импорт типов для аннотаций
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .Msm_26_1_geometry_processor import Msm_26_1_GeometryProcessor
    from .Msm_26_2_attribute_mapper import Msm_26_2_AttributeMapper
    from .Msm_26_3_layer_creator import Msm_26_3_LayerCreator

# Импорт матчера КК и создателя точечных слоёв
from .Msm_26_5_kk_matcher import Msm_26_5_KKMatcher
from .Msm_26_6_point_layer_creator import Msm_26_6_PointLayerCreator

# Минимальная площадь НГС (м2)
# НГС с площадью меньше этого порога считаются артефактами округления координат
# и фильтруются. Согласно Приказу Росреестра П/0393, допустимая СКП для земель
# населённых пунктов = 0.10 м. Площадь 0.10 м2 = квадрат ~31.6x31.6 см.
MIN_NGS_AREA = 0.10  # м2


class Msm_26_4_CuttingEngine:
    """Движок выполнения нарезки ЗПР"""

    def __init__(
        self,
        geometry_processor: 'Msm_26_1_GeometryProcessor',
        attribute_mapper: 'Msm_26_2_AttributeMapper',
        layer_creator: 'Msm_26_3_LayerCreator'
    ) -> None:
        """Инициализация движка

        Args:
            geometry_processor: Процессор геометрий
            attribute_mapper: Маппер атрибутов
            layer_creator: Создатель слоёв
        """
        self.geometry_processor = geometry_processor
        self.attribute_mapper = attribute_mapper
        self.layer_creator = layer_creator

        # Создатель точечных слоёв (использует тот же GPKG)
        self.point_layer_creator = Msm_26_6_PointLayerCreator(layer_creator.gpkg_path)

        # Менеджер присвоения Вид_Работ
        self.work_type_manager = WorkTypeAssignmentManager()

        # Менеджер анализа ОКС_на_ЗУ
        self.oks_zu_manager = OksZuAnalysisManager()

        # Кэш для overlay union геометрий
        self._overlay_union_cache: Dict[str, QgsGeometry] = {}

        # Статистика обработки
        self.statistics: Dict[str, Any] = {}

    def _reset_statistics(self) -> None:
        """Сброс статистики перед обработкой"""
        self.statistics = {
            'total_zpr_features': 0,
            'processed_features': 0,
            'invalid_geometries': 0,
            'razdel_created': 0,
            'ngs_created': 0,
            'overlay_cuts': 0,
            'processing_time': 0.0,
        }

    def _get_overlay_union(
        self,
        overlay_type: str,
        overlay_layer: QgsVectorLayer
    ) -> QgsGeometry:
        """Получить кэшированный union overlay слоя

        Args:
            overlay_type: Тип overlay (НП, МО, Лес, Вода)
            overlay_layer: Слой overlay

        Returns:
            QgsGeometry: Объединённая геометрия
        """
        if overlay_type not in self._overlay_union_cache:
            self._overlay_union_cache[overlay_type] = \
                self.geometry_processor.create_union(overlay_layer)
            log_info(f"Msm_26_4: Создан кэш union для {overlay_type}")

        return self._overlay_union_cache[overlay_type]

    def _clear_overlay_cache(self) -> None:
        """Очистка кэша overlay union"""
        self._overlay_union_cache.clear()

    def process_zpr_type(
        self,
        zpr_layer: QgsVectorLayer,
        zu_layer: QgsVectorLayer,
        zpr_type: str,
        overlay_layers: Dict[str, QgsVectorLayer],
        razdel_layer_name: str,
        ngs_layer_name: str,
        crs: QgsCoordinateReferenceSystem,
        kk_layer: Optional[QgsVectorLayer] = None
    ) -> Optional[Dict[str, Any]]:
        """Обработка одного типа ЗПР

        Args:
            zpr_layer: Слой ЗПР (источник)
            zu_layer: Слой Выборка_ЗУ
            zpr_type: Тип ЗПР (ОКС, ЛО, ВО)
            overlay_layers: Словарь overlay слоёв {тип: слой}
            razdel_layer_name: Имя слоя Раздел
            ngs_layer_name: Имя слоя НГС
            crs: Система координат
            kk_layer: Слой L_2_1_3_Выборка_КК для привязки НГС к кварталам

        Returns:
            Dict: {'razdel_count': int, 'ngs_count': int, 'statistics': dict}
            или None при ошибке
        """
        start_time = time.time()
        log_info(f"Msm_26_4: Начало нарезки {zpr_type}")

        # Сброс статистики и счётчиков ID
        # ВАЖНО: reset_kn_counters() НЕ вызываем здесь - счётчики КН/ЕЗ глобальные
        # для всех типов ЗПР и сбрасываются один раз в начале операции в F_3_1
        self._reset_statistics()
        self._clear_overlay_cache()

        # Сброс сквозного счётчика ID для этого типа ЗПР
        # zpr_type = ОКС, ЛО, ВО (стандартные) или РЕК_АД, СЕТИ_ПО, СЕТИ_ВО, НЭ (рекреационные)
        # Нумерация: Раздел -> НГС -> Без_Меж (последовательно внутри каждого типа ЗПР)
        self.attribute_mapper.reset_zpr_id_counter(zpr_type)

        self.statistics['total_zpr_features'] = zpr_layer.featureCount()

        try:
            # 1. Первичная нарезка по ЗУ
            razdel_data, ngs_data = self._cut_by_zu(zpr_layer, zu_layer, zpr_type)

            self.statistics['razdel_created'] = len(razdel_data)
            self.statistics['ngs_created'] = len(ngs_data)
            log_info(f"Msm_26_4: Первичная нарезка: {len(razdel_data)} Раздел, "
                    f"{len(ngs_data)} НГС")

            # 2. Дополнительная нарезка по overlay слоям
            if overlay_layers:
                razdel_before = len(razdel_data)
                ngs_before = len(ngs_data)

                razdel_data = self._cut_by_overlays(
                    razdel_data, overlay_layers, razdel_layer_name, zpr_type
                )
                ngs_data = self._cut_by_overlays(
                    ngs_data, overlay_layers, ngs_layer_name, zpr_type
                )

                # Подсчёт дополнительных разрезов
                self.statistics['overlay_cuts'] = \
                    (len(razdel_data) - razdel_before) + (len(ngs_data) - ngs_before)

                log_info(f"Msm_26_4: После overlay нарезки: {len(razdel_data)} Раздел, "
                        f"{len(ngs_data)} НГС (+{self.statistics['overlay_cuts']} разрезов)")

            # 2.5. Привязка НГС к кадастровым кварталам
            if kk_layer and ngs_data:
                kk_matcher = Msm_26_5_KKMatcher(kk_layer)
                ngs_data = kk_matcher.match_ngs_to_quarters(ngs_data)
                self.statistics['kk_stats'] = kk_matcher.get_statistics()

            # 3. Генерация атрибутов со сквозной нумерацией ID
            # Порядок: Раздел -> НГС -> Без_Меж (ID уникальны внутри типа ЗПР)
            razdel_features = self._generate_features_data(
                razdel_data, razdel_layer_name, zpr_type, use_zpr_id=True
            )
            razdel_max_id = self.attribute_mapper.get_current_zpr_id(zpr_type)

            ngs_features = self._generate_features_data(
                ngs_data, ngs_layer_name, zpr_type, use_zpr_id=True
            )
            ngs_max_id = self.attribute_mapper.get_current_zpr_id(zpr_type)

            log_info(f"Msm_26_4: ID нумерация {zpr_type}: Раздел 1-{razdel_max_id}, "
                    f"НГС {razdel_max_id + 1 if ngs_features else '-'}-{ngs_max_id}")

            # 3.1 Анализ ОКС_на_ЗУ для новых геометрий
            if razdel_features:
                razdel_features = self.oks_zu_manager.analyze_features_batch(
                    razdel_features,
                    is_ngs=False,
                    attribute_setter=self.attribute_mapper.set_oks_zu_values,
                    module_id="Msm_26_4"
                )
            if ngs_features:
                ngs_features = self.oks_zu_manager.analyze_features_batch(
                    ngs_features,
                    is_ngs=True,
                    attribute_setter=self.attribute_mapper.set_oks_zu_values,
                    module_id="Msm_26_4"
                )

            # 3.2 Присвоение Вид_Работ
            if razdel_features:
                razdel_features = self.work_type_manager.assign_work_type_basic(
                    razdel_features, LayerType.RAZDEL
                )
            if ngs_features:
                ngs_features = self.work_type_manager.assign_work_type_basic(
                    ngs_features, LayerType.NGS
                )

            # 4. Нумерация точек и создание точечных слоёв
            razdel_points_data = []
            ngs_points_data = []

            if razdel_features:
                razdel_features, razdel_points_data = self._number_points(
                    razdel_features, razdel_layer_name
                )

            if ngs_features:
                ngs_features, ngs_points_data = self._number_points(
                    ngs_features, ngs_layer_name
                )

            # 5. Создание слоёв (без добавления в проект - это делает вызывающий код через LayerManager)
            razdel_layer_result = None
            ngs_layer_result = None
            razdel_points_layer_result = None
            ngs_points_layer_result = None

            if razdel_features:
                razdel_layer_result = self.layer_creator.create_cutting_layer(
                    razdel_layer_name, crs, razdel_features
                )

            if ngs_features:
                ngs_layer_result = self.layer_creator.create_cutting_layer(
                    ngs_layer_name, crs, ngs_features
                )

            # Создание точечных слоёв
            if razdel_points_data:
                razdel_points_layer_result = self.point_layer_creator.create_point_layer_for_polygon(
                    razdel_layer_name, crs, razdel_points_data
                )

            if ngs_points_data:
                ngs_points_layer_result = self.point_layer_creator.create_point_layer_for_polygon(
                    ngs_layer_name, crs, ngs_points_data
                )

            # TODO: Без_Меж и ПС (заглушка)
            log_info(f"Msm_26_4: TODO - Без_Меж и ПС для {zpr_type}")

            # Финализация статистики
            self.statistics['processing_time'] = time.time() - start_time
            self.statistics['razdel_created'] = len(razdel_features) if razdel_features else 0
            self.statistics['ngs_created'] = len(ngs_features) if ngs_features else 0
            self.statistics['razdel_points'] = len(razdel_points_data)
            self.statistics['ngs_points'] = len(ngs_points_data)

            log_info(f"Msm_26_4: {zpr_type} завершено за "
                    f"{self.statistics['processing_time']:.2f} сек. "
                    f"Статистика: {self.statistics}")

            return {
                'razdel_count': self.statistics['razdel_created'],
                'ngs_count': self.statistics['ngs_created'],
                'razdel_layer': razdel_layer_result,
                'ngs_layer': ngs_layer_result,
                'razdel_points_layer': razdel_points_layer_result,
                'ngs_points_layer': ngs_points_layer_result,
                'statistics': self.statistics.copy(),
            }

        except Exception as e:
            self.statistics['processing_time'] = time.time() - start_time
            log_error(f"Msm_26_4: Ошибка нарезки {zpr_type}: {e}")
            return None

    def _cut_by_zu(
        self,
        zpr_layer: QgsVectorLayer,
        zu_layer: QgsVectorLayer,
        zpr_type: str
    ) -> Tuple[List[Dict], List[Dict]]:
        """Первичная нарезка ЗПР по границам ЗУ

        Args:
            zpr_layer: Слой ЗПР
            zu_layer: Слой Выборка_ЗУ
            zpr_type: Тип ЗПР

        Returns:
            Tuple: (razdel_data, ngs_data) - списки словарей с геометрией и атрибутами
        """
        razdel_data = []  # Части внутри ЗУ
        ngs_data = []  # Части вне ЗУ

        # Создаём union всех ЗУ
        zu_union = self.geometry_processor.create_union(zu_layer)

        # Индекс ЗУ для быстрого поиска пересечений
        zu_index = self._build_spatial_index(zu_layer)

        # Обрабатываем каждый полигон ЗПР
        for zpr_feature in zpr_layer.getFeatures():
            zpr_geom = zpr_feature.geometry()

            if not zpr_geom or zpr_geom.isEmpty():
                continue

            # Валидация геометрии
            zpr_geom = self.geometry_processor.validate_and_fix(zpr_geom)
            if zpr_geom.isEmpty():
                continue

            # Находим пересекающиеся ЗУ
            intersecting_zu = self._find_intersecting_features(zpr_geom, zu_layer, zu_index)

            # Нарезка по каждому пересекающемуся ЗУ
            processed_area = QgsGeometry()  # Уже обработанная область

            for zu_feature in intersecting_zu:
                zu_geom = zu_feature.geometry()

                if not zu_geom or zu_geom.isEmpty():
                    continue

                zu_geom = self.geometry_processor.validate_and_fix(zu_geom)

                # Пересечение ЗПР с этим ЗУ
                intersection = self.geometry_processor.intersection(zpr_geom, zu_geom)

                if intersection.isEmpty():
                    continue

                # Извлекаем отдельные полигоны
                for poly_geom in self.geometry_processor.extract_polygons(intersection):
                    if poly_geom.isEmpty():
                        continue

                    # Атрибуты из ЗУ
                    zu_attrs = self.attribute_mapper.map_zu_attributes(zu_feature)

                    razdel_data.append({
                        'geometry': poly_geom,
                        'zu_attributes': zu_attrs,
                        'overlays': {}  # Заполняется при overlay нарезке
                    })

                # Обновляем обработанную область
                if processed_area.isEmpty():
                    processed_area = intersection
                else:
                    processed_area = processed_area.combine(intersection)

            # НГС = ЗПР минус union всех ЗУ
            if not zu_union.isEmpty():
                ngs_geom = self.geometry_processor.difference(zpr_geom, zu_union)

                if not ngs_geom.isEmpty():
                    # Логируем общую площадь НГС перед извлечением
                    ngs_total_area = ngs_geom.area()
                    zpr_id = zpr_feature['ID'] if 'ID' in zpr_feature.fields().names() else zpr_feature.id()
                    log_info(f"Msm_26_4: НГС от ЗПР ID={zpr_id}: общая площадь={ngs_total_area:.4f} м2, "
                            f"isMultipart={ngs_geom.isMultipart()}")

                    # Извлекаем отдельные полигоны
                    extracted_polygons = self.geometry_processor.extract_polygons(ngs_geom)
                    log_info(f"Msm_26_4: НГС от ЗПР ID={zpr_id}: извлечено {len(extracted_polygons)} полигонов")

                    filtered_count = 0
                    for idx, poly_geom in enumerate(extracted_polygons):
                        if poly_geom.isEmpty():
                            log_warning(f"Msm_26_4: НГС #{idx} от ЗПР ID={zpr_id}: пустая геометрия, пропуск")
                            continue

                        poly_area = poly_geom.area()

                        # Фильтрация микро-НГС (артефакты округления координат)
                        if poly_area < MIN_NGS_AREA:
                            filtered_count += 1
                            log_info(f"Msm_26_4: НГС #{idx} от ЗПР ID={zpr_id}: "
                                    f"площадь={poly_area:.6f} м2 < {MIN_NGS_AREA} м2, пропуск (артефакт)")
                            continue

                        log_info(f"Msm_26_4: НГС #{idx} от ЗПР ID={zpr_id}: площадь={poly_area:.4f} м2")

                        # Пустые атрибуты для НГС
                        ngs_attrs = self.attribute_mapper.create_empty_attributes()

                        ngs_data.append({
                            'geometry': poly_geom,
                            'zu_attributes': ngs_attrs,
                            'overlays': {}
                        })

                    if filtered_count > 0:
                        log_info(f"Msm_26_4: НГС от ЗПР ID={zpr_id}: отфильтровано {filtered_count} "
                                f"микро-полигонов (площадь < {MIN_NGS_AREA} м2)")

        return razdel_data, ngs_data

    def _cut_by_overlays(
        self,
        data: List[Dict],
        overlay_layers: Dict[str, QgsVectorLayer],
        layer_name: str,
        zpr_type: str
    ) -> List[Dict]:
        """Дополнительная нарезка по overlay слоям

        Args:
            data: Исходные данные (после нарезки по ЗУ)
            overlay_layers: Словарь overlay слоёв
            layer_name: Имя целевого слоя
            zpr_type: Тип ЗПР

        Returns:
            List[Dict]: Обновлённые данные после нарезки
        """
        result = data

        # Последовательная нарезка по каждому overlay
        for overlay_type, overlay_layer in overlay_layers.items():
            if not overlay_layer or overlay_layer.featureCount() == 0:
                continue

            log_info(f"Msm_26_4: Дополнительная нарезка по {overlay_type}")

            # Используем кэшированный union
            overlay_union = self._get_overlay_union(overlay_type, overlay_layer)
            if overlay_union.isEmpty():
                continue

            new_result = []

            for item in result:
                geom = item['geometry']
                zu_attrs = item['zu_attributes']
                overlays = item.get('overlays', {}).copy()

                if geom.isEmpty():
                    continue

                # Проверяем необходимость нарезки
                if not self.geometry_processor.need_additional_cut(geom, overlay_union):
                    # Определяем находится ли внутри
                    intersection = geom.intersection(overlay_union)
                    if not intersection.isEmpty():
                        # Внутри overlay
                        overlays[overlay_type] = "TODO: маппинг"

                    new_result.append({
                        'geometry': geom,
                        'zu_attributes': zu_attrs,
                        'overlays': overlays
                    })
                else:
                    # Режем на две части
                    inside = self.geometry_processor.intersection(geom, overlay_union)
                    outside = self.geometry_processor.difference(geom, overlay_union)

                    if not inside.isEmpty():
                        inside_overlays = overlays.copy()
                        inside_overlays[overlay_type] = "TODO: маппинг"

                        for poly_geom in self.geometry_processor.extract_polygons(inside):
                            if not poly_geom.isEmpty():
                                new_result.append({
                                    'geometry': poly_geom,
                                    'zu_attributes': zu_attrs.copy(),
                                    'overlays': inside_overlays.copy()
                                })

                    if not outside.isEmpty():
                        for poly_geom in self.geometry_processor.extract_polygons(outside):
                            if not poly_geom.isEmpty():
                                new_result.append({
                                    'geometry': poly_geom,
                                    'zu_attributes': zu_attrs.copy(),
                                    'overlays': overlays.copy()
                                })

            result = new_result
            log_info(f"Msm_26_4: После нарезки по {overlay_type}: {len(result)} объектов")

        return result

    def _generate_features_data(
        self,
        data: List[Dict],
        layer_name: str,
        zpr_type: str,
        use_zpr_id: bool = True
    ) -> List[Dict[str, Any]]:
        """Генерация финальных данных для создания слоя

        Args:
            data: Данные после нарезки
            layer_name: Имя слоя
            zpr_type: Тип ЗПР
            use_zpr_id: Использовать сквозную нумерацию ID по типу ЗПР

        Returns:
            List[Dict]: Данные в формате для layer_creator
        """
        result = []

        for item in data:
            geom = item['geometry']
            zu_attrs = item['zu_attributes']
            overlays = item.get('overlays', {})

            if geom.isEmpty():
                continue

            # Генерация ID: сквозная для ЗПР или по слою
            explicit_id = None
            if use_zpr_id:
                explicit_id = self.attribute_mapper.generate_zpr_id(zpr_type)

            # Генерация расчётных полей
            attributes = self.attribute_mapper.fill_generated_fields(
                zu_attrs, geom, layer_name, zpr_type, explicit_id=explicit_id
            )

            # Установка значений overlay
            for overlay_type, overlay_value in overlays.items():
                attributes = self.attribute_mapper.set_overlay_value(
                    attributes, overlay_type, overlay_value
                )

            result.append({
                'geometry': geom,
                'attributes': attributes
            })

        return result

    def _build_spatial_index(
        self,
        layer: QgsVectorLayer
    ) -> Tuple[QgsSpatialIndex, Dict[int, QgsFeature]]:
        """Построение пространственного индекса для слоя

        Использует QgsSpatialIndex для быстрого поиска по bbox.

        Args:
            layer: Векторный слой

        Returns:
            Tuple: (QgsSpatialIndex, {fid: QgsFeature})
        """
        spatial_index = QgsSpatialIndex()
        features_dict: Dict[int, QgsFeature] = {}

        for feature in layer.getFeatures():
            geom = feature.geometry()
            if geom and not geom.isEmpty():
                spatial_index.addFeature(feature)
                features_dict[feature.id()] = feature

        log_info(f"Msm_26_4: Построен пространственный индекс ({len(features_dict)} объектов)")
        return spatial_index, features_dict

    def _find_intersecting_features(
        self,
        geom: QgsGeometry,
        layer: QgsVectorLayer,
        index_data: Tuple[QgsSpatialIndex, Dict[int, QgsFeature]]
    ) -> List[QgsFeature]:
        """Поиск объектов слоя, пересекающих геометрию

        Использует QgsSpatialIndex для быстрой фильтрации по bbox,
        затем выполняет точную проверку пересечения.

        Args:
            geom: Геометрия для поиска
            layer: Слой для поиска (не используется, для совместимости)
            index_data: Кортеж (QgsSpatialIndex, {fid: QgsFeature})

        Returns:
            List[QgsFeature]: Список пересекающихся объектов
        """
        spatial_index, features_dict = index_data
        result = []
        bbox = geom.boundingBox()

        # Быстрый поиск кандидатов по bbox через QgsSpatialIndex
        candidate_ids = spatial_index.intersects(bbox)

        for fid in candidate_ids:
            feature = features_dict.get(fid)
            if feature is None:
                continue

            feature_geom = feature.geometry()
            if feature_geom.isEmpty():
                continue

            # Точная проверка пересечения
            if geom.intersects(feature_geom):
                result.append(feature)

        return result

    def _number_points(
        self,
        features_data: List[Dict[str, Any]],
        layer_name: str
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Нумерация точек контуров и подготовка данных для точечного слоя

        Args:
            features_data: Данные объектов с geometry и attributes
            layer_name: Имя слоя (для определения соответствующего точечного слоя)

        Returns:
            Tuple:
            - Обновлённый features_data с заполненным полем 'Точки'
            - Список точек для точечного слоя
        """
        # Преобразуем features_data в формат для PointNumberingManager
        numbering_input = []
        for idx, item in enumerate(features_data):
            # ID контура берём из атрибутов или генерируем
            # ВАЖНО: .get() возвращает None если ключ существует но значение None
            # поэтому нужна явная проверка на None
            contour_id = item['attributes'].get('ID')
            if contour_id is None:
                contour_id = idx + 1
            numbering_input.append({
                'geometry': item['geometry'],
                'contour_id': contour_id,
                'attributes': item['attributes']
            })

        # Обрабатываем через менеджер нумерации
        manager = PointNumberingManager()
        processed_data, points_data = manager.process_polygon_layer(numbering_input)

        # Обновляем поле 'Точки' в атрибутах
        for idx, processed_item in enumerate(processed_data):
            if idx < len(features_data):
                point_numbers_str = processed_item.get('point_numbers_str', '')
                features_data[idx]['attributes']['Точки'] = point_numbers_str

        log_info(f"Msm_26_4: Нумерация точек для {layer_name}: "
                f"{manager.get_unique_points_count()} уникальных точек")

        return features_data, points_data

    def _create_bez_mezh(self) -> None:
        """Создание слоёв Без_Меж

        TODO: Реализовать позже
        """
        log_info("Msm_26_4: TODO - _create_bez_mezh не реализовано")

    def _create_ps(self) -> None:
        """Создание слоёв ПС (простой сегмент)

        TODO: Реализовать позже
        """
        log_info("Msm_26_4: TODO - _create_ps не реализовано")

