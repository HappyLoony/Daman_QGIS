# -*- coding: utf-8 -*-
"""
Msm_26_4 - Движок нарезки ЗПР

Основной движок выполнения нарезки:
- Первичная нарезка по ЗУ (Раздел и НГС)
- Автоматическая классификация ЗУ (Изменяемые/Без_Меж)
- Индивидуальная нарезка по overlay слоям (ЗК РФ ст. 11.9 п. 3)
- Маппинг названий МО/НП/Лес/Вода из overlay features
- Нумерация характерных точек контуров
- Координация работы других субмодулей
"""

import time
from typing import Dict, List, Tuple, Optional, Any

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsPointXY,
    QgsSpatialIndex,
)

from Daman_QGIS.utils import log_info, log_warning, log_error

# Lazy imports для избежания циклических зависимостей
def _get_managers():
    from Daman_QGIS.managers import (
        PointNumberingManager, WorkTypeAssignmentManager, LayerType,
        OksZuAnalysisManager, LandCategoryAssignmentManager, VRIAssignmentManager
    )
    return (PointNumberingManager, WorkTypeAssignmentManager, LayerType,
            OksZuAnalysisManager, LandCategoryAssignmentManager, VRIAssignmentManager)

# Импорт типов для аннотаций
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .Msm_26_1_geometry_processor import Msm_26_1_GeometryProcessor
    from .Msm_26_2_attribute_mapper import Msm_26_2_AttributeMapper
    from .Msm_26_3_layer_creator import Msm_26_3_LayerCreator

# Импорт матчера КК и создателя точечных слоёв
from .Msm_26_5_kk_matcher import Msm_26_5_KKMatcher
from .Msm_26_6_point_layer_creator import Msm_26_6_PointLayerCreator

# Lazy imports для избежания циклических зависимостей
# Детектор, процессоры и валидатор импортируются внутри _detect_and_process_no_change()

# Минимальная площадь НГС (м2)
# Установлено 0.0 - все микро-полигоны НГС сохраняются без фильтрации.
# Причина: наличие мелких НГС указывает на несостыковку ЗПР с ЗУ
# или реестровую ошибку, что требует внимания оператора.
MIN_NGS_AREA = 0.0


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

        # Ленивая инициализация менеджеров
        self._work_type_manager = None
        self._oks_zu_manager = None
        self._land_category_manager = None
        self._vri_manager = None

        # Статистика обработки
        self.statistics: Dict[str, Any] = {}

    @property
    def work_type_manager(self):
        """Ленивый доступ к WorkTypeAssignmentManager"""
        if self._work_type_manager is None:
            _, WorkTypeAssignmentManager, _, _, _, _ = _get_managers()
            self._work_type_manager = WorkTypeAssignmentManager()
        return self._work_type_manager

    @property
    def oks_zu_manager(self):
        """Ленивый доступ к OksZuAnalysisManager"""
        if self._oks_zu_manager is None:
            _, _, _, OksZuAnalysisManager, _, _ = _get_managers()
            self._oks_zu_manager = OksZuAnalysisManager()
        return self._oks_zu_manager

    @property
    def land_category_manager(self):
        """Ленивый доступ к LandCategoryAssignmentManager"""
        if self._land_category_manager is None:
            _, _, _, _, LandCategoryAssignmentManager, _ = _get_managers()
            self._land_category_manager = LandCategoryAssignmentManager()
        return self._land_category_manager

    @property
    def vri_manager(self):
        """Ленивый доступ к VRIAssignmentManager"""
        if self._vri_manager is None:
            _, _, _, _, _, VRIAssignmentManager = _get_managers()
            self._vri_manager = VRIAssignmentManager()
        return self._vri_manager

    def _reset_statistics(self) -> None:
        """Сброс статистики перед обработкой"""
        self.statistics = {
            'total_zpr_features': 0,
            'processed_features': 0,
            'invalid_geometries': 0,
            'razdel_created': 0,
            'ngs_created': 0,
            'izm_created': 0,
            'bez_mezh_created': 0,
            'overlay_cuts': 0,
            'processing_time': 0.0,
        }

    def process_zpr_type(
        self,
        zpr_layer: QgsVectorLayer,
        zu_layer: QgsVectorLayer,
        zpr_type: str,
        overlay_layers: Dict[str, Dict[str, Any]],
        razdel_layer_name: str,
        ngs_layer_name: str,
        crs: QgsCoordinateReferenceSystem,
        kk_layer: Optional[QgsVectorLayer] = None,
        detect_no_change: bool = False,
        izm_layer_name: Optional[str] = None,
        bez_mezh_layer_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Обработка одного типа ЗПР

        Args:
            zpr_layer: Слой ЗПР (источник)
            zu_layer: Слой Выборка_ЗУ
            zpr_type: Тип ЗПР (ОКС, ЛО, ВО)
            overlay_layers: Словарь overlay слоёв {тип: {'layer': QgsVectorLayer, 'name_field': str}}
            razdel_layer_name: Имя слоя Раздел
            ngs_layer_name: Имя слоя НГС
            crs: Система координат
            kk_layer: Слой L_2_1_3_Выборка_КК для привязки НГС к кварталам
            detect_no_change: Включить автоматическую классификацию ЗУ (Изм/Без_Меж)
            izm_layer_name: Имя слоя Изменяемые (для detect_no_change)
            bez_mezh_layer_name: Имя слоя Без_Меж (для detect_no_change)

        Returns:
            Dict: {'razdel_count': int, 'ngs_count': int, 'izm_count': int,
                   'bez_mezh_count': int, 'statistics': dict}
            или None при ошибке
        """
        start_time = time.time()
        log_info(f"Msm_26_4: Начало нарезки {zpr_type}")

        # Сброс статистики и счётчиков ID
        # ВАЖНО: reset_kn_counters() НЕ вызываем здесь - счётчики КН/ЕЗ глобальные
        # для всех типов ЗПР и сбрасываются один раз в начале операции в F_2_1
        self._reset_statistics()

        # Сброс сквозного счётчика ID для этого типа ЗПР
        # zpr_type = ОКС, ЛО, ВО (стандартные) или РЕК_АД, СЕТИ_ПО, СЕТИ_ВО, НЭ (рекреационные)
        # Нумерация: Раздел -> НГС -> Без_Меж (последовательно внутри каждого типа ЗПР)
        self.attribute_mapper.reset_zpr_id_counter(zpr_type)

        self.statistics['total_zpr_features'] = zpr_layer.featureCount()

        try:
            # 0. Автоматическая классификация ЗУ (Изм/Без_Меж) ПЕРЕД нарезкой
            izm_features: List[Dict[str, Any]] = []
            bez_mezh_features: List[Dict[str, Any]] = []
            excluded_zu_ids: set = set()  # fid ЗУ исключённых из нарезки

            if detect_no_change and izm_layer_name and bez_mezh_layer_name:
                izm_features, bez_mezh_features, excluded_zu_ids = self._detect_and_process_no_change(
                    zpr_layer=zpr_layer,
                    zu_layer=zu_layer,
                    zpr_type=zpr_type,
                    izm_layer_name=izm_layer_name,
                    bez_mezh_layer_name=bez_mezh_layer_name
                )
                log_info(f"Msm_26_4: Детекция no_change: {len(izm_features)} Изм, "
                        f"{len(bez_mezh_features)} Без_Меж, исключено {len(excluded_zu_ids)} ЗУ")

            # 1. Первичная нарезка по ЗУ (исключая уже обработанные Изм/Без_Меж)
            razdel_data, ngs_data = self._cut_by_zu(
                zpr_layer, zu_layer, zpr_type, excluded_zu_ids=excluded_zu_ids
            )

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

            # 2.6. Обратное геокодирование НГС (адрес по центроиду)
            if ngs_data:
                ngs_data = self._geocode_ngs_addresses(ngs_data, crs)

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
            _, _, LayerType, _, _, _ = _get_managers()
            if razdel_features:
                razdel_features = self.work_type_manager.assign_work_type_basic(
                    razdel_features, LayerType.RAZDEL
                )
            if ngs_features:
                ngs_features = self.work_type_manager.assign_work_type_basic(
                    ngs_features, LayerType.NGS
                )

            # 3.3 Назначение План_категория (Раздел + НГС + Изменяемые + Без_Меж)
            # M_36 определяет категорию по пространственному пересечению с НП/ООПТ/Лес
            all_features_for_category: List[Dict[str, Any]] = []
            if razdel_features:
                all_features_for_category.extend(razdel_features)
            if ngs_features:
                all_features_for_category.extend(ngs_features)

            # Сохраняем исходную категорию ЗУ перед M_36 для Изм и Без_Меж
            izm_original_categories: Dict[int, str] = {}
            if izm_features:
                for idx, feat in enumerate(izm_features):
                    izm_original_categories[idx] = feat['attributes'].get('План_категория', '-')
                all_features_for_category.extend(izm_features)

            bez_mezh_original_categories: Dict[int, str] = {}
            if bez_mezh_features:
                for idx, feat in enumerate(bez_mezh_features):
                    bez_mezh_original_categories[idx] = feat['attributes'].get('План_категория', '-')
                all_features_for_category.extend(bez_mezh_features)

            if all_features_for_category:
                self.land_category_manager.assign_land_category(all_features_for_category)

            # 3.3.1 Пост-проверка категории для initial ИЗМ (VRI mismatch)
            # Если M_36 назначила иную категорию -> добавляем флаг category
            if izm_features and izm_original_categories:
                for idx, feat in enumerate(izm_features):
                    original_cat = izm_original_categories.get(idx, '-')
                    m36_cat = feat['attributes'].get('План_категория', '-')
                    if original_cat != m36_cat and m36_cat != '-':
                        feat.setdefault('_izm_flags', {})['category'] = True
                        log_info(f"Msm_26_4: Изм (VRI): категория также изменилась "
                                f"'{original_cat}' -> '{m36_cat}'")

            # 3.3.2 Пост-проверка категории для Без_Меж
            # Если M_36 назначила категорию, отличную от исходной ЗУ -> переносим в Изм
            if bez_mezh_features and bez_mezh_original_categories:
                moved_to_izm = []
                remaining_bez_mezh = []

                for idx, feat in enumerate(bez_mezh_features):
                    original_cat = bez_mezh_original_categories.get(idx, '-')
                    m36_cat = feat['attributes'].get('План_категория', '-')

                    if original_cat != m36_cat and m36_cat != '-':
                        # Категория изменилась -> перенос в Изм
                        feat['attributes']['Точки'] = '-'
                        feat.setdefault('_izm_flags', {})['category'] = True
                        moved_to_izm.append(feat)
                        log_info(f"Msm_26_4: Без_Меж -> Изм: категория изменилась "
                                f"'{original_cat}' -> '{m36_cat}'")
                    else:
                        # Категория совпала -> остаётся Без_Меж
                        # Восстанавливаем исходную категорию из ЗУ (Без_Меж = без изменений)
                        feat['attributes']['План_категория'] = original_cat
                        remaining_bez_mezh.append(feat)

                if moved_to_izm:
                    izm_features.extend(moved_to_izm)
                    log_info(f"Msm_26_4: Перенесено {len(moved_to_izm)} объектов из Без_Меж в Изм "
                            f"(несовпадение категории)")

                bez_mezh_features = remaining_bez_mezh

            # 3.3.3 Пост-проверка площади для initial ИЗМ
            # Реестровая ошибка как модификатор к основной причине
            if izm_features:
                for feat in izm_features:
                    geom = feat.get('geometry')
                    if not geom or geom.isEmpty():
                        continue
                    actual_area = geom.area()
                    try:
                        egrn_area = float(feat['attributes'].get('Площадь_ОЗУ', 0) or 0)
                    except (ValueError, TypeError):
                        egrn_area = 0.0
                    if round(egrn_area) != round(actual_area):
                        feat.setdefault('_izm_flags', {})['area'] = True
                        feat['attributes']['Площадь_ОЗУ'] = int(round(actual_area))
                        log_info(f"Msm_26_4: Изм: реестровая ошибка площади "
                                f"ЕГРН={round(egrn_area)} м2 -> факт={round(actual_area)} м2")

            # 3.3.4 Пост-проверка площади для Без_Меж
            # Если фактическая площадь геометрии отличается от площади из выписки (ЕГРН)
            # на >= 1 м2 (округлённо) -> переносим в Изм (реестровая ошибка)
            if bez_mezh_features:
                moved_area = []
                remaining_area = []

                for feat in bez_mezh_features:
                    geom = feat.get('geometry')
                    if not geom or geom.isEmpty():
                        remaining_area.append(feat)
                        continue

                    actual_area = geom.area()
                    try:
                        egrn_area = float(feat['attributes'].get('Площадь_ОЗУ', 0) or 0)
                    except (ValueError, TypeError):
                        egrn_area = 0.0

                    if round(egrn_area) != round(actual_area):
                        # Площадь отличается -> перенос в Изм (реестровая ошибка)
                        feat['attributes']['Точки'] = '-'
                        feat['attributes']['Площадь_ОЗУ'] = int(round(actual_area))
                        feat.setdefault('_izm_flags', {})['area'] = True
                        moved_area.append(feat)
                        log_info(f"Msm_26_4: Без_Меж -> Изм: площадь изменилась "
                                f"ЕГРН={round(egrn_area)} м2 -> факт={round(actual_area)} м2")
                    else:
                        remaining_area.append(feat)

                if moved_area:
                    izm_features.extend(moved_area)
                    log_info(f"Msm_26_4: Перенесено {len(moved_area)} объектов из Без_Меж в Изм "
                            f"(несовпадение площади)")

                bez_mezh_features = remaining_area

            # 3.3.5 Компоновка Вид_Работ для всех ИЗМ из флагов причин
            # Также разделяем ИЗМ: кому нужна смена ВРИ, а кому нет
            izm_need_vri_reassign: List[Dict[str, Any]] = []
            izm_keep_vri: List[Dict[str, Any]] = []
            if izm_features:
                from Daman_QGIS.constants import compose_work_type_izm
                for feat in izm_features:
                    flags = feat.pop('_izm_flags', {})
                    feat['attributes']['Вид_Работ'] = compose_work_type_izm(
                        vri_changed=flags.get('vri', False),
                        category_changed=flags.get('category', False),
                        area_mismatch=flags.get('area', False)
                    )
                    # ВРИ менять только если мягкая валидация НЕ прошла (vri_changed)
                    if flags.get('vri', False):
                        izm_need_vri_reassign.append(feat)
                    else:
                        izm_keep_vri.append(feat)

            # Очистка _izm_flags у Без_Меж (не нужны дальше)
            if bez_mezh_features:
                for feat in bez_mezh_features:
                    feat.pop('_izm_flags', None)

            # 3.4 Присвоение План_ВРИ и Общая_земля по геометрическому пересечению с ЗПР
            if razdel_features:
                razdel_features = self.vri_manager.reassign_vri_by_geometry(
                    razdel_features, zpr_layer
                )
            if ngs_features:
                ngs_features = self.vri_manager.reassign_vri_by_geometry(
                    ngs_features, zpr_layer
                )
            # Для ИЗМ с несовпавшим ВРИ - пересчитываем ВРИ по геометрии ЗПР
            if izm_need_vri_reassign:
                izm_need_vri_reassign = self.vri_manager.reassign_vri_by_geometry(
                    izm_need_vri_reassign, zpr_layer
                )
            # Для ИЗМ с совпавшим ВРИ (только категория/площадь) - ВРИ остаётся как у ЗУ
            # Аналогично Без_Меж: мягкая валидация прошла, План_ВРИ = исходный ВРИ
            izm_features = izm_need_vri_reassign + izm_keep_vri

            # ВАЖНО: Для Без_Меж НЕ вызываем reassign_vri_by_geometry!
            # План_ВРИ и План_категория уже установлены в Fsm_2_1_9_BezMezhProcessor
            # как ТОЧНЫЕ КОПИИ исходных атрибутов ЗУ (без нормализации).
            # Это соответствует логике: Без_Меж = существующий ЗУ без изменений.

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

            # 6. Создание слоёв Изм и Без_Меж (если detect_no_change включён)
            izm_layer_result = None
            bez_mezh_layer_result = None

            if detect_no_change and izm_layer_name and bez_mezh_layer_name:
                if izm_features:
                    izm_layer_result = self.layer_creator.create_cutting_layer(
                        izm_layer_name, crs, izm_features
                    )
                    log_info(f"Msm_26_4: Создан слой {izm_layer_name} ({len(izm_features)} объектов)")

                if bez_mezh_features:
                    bez_mezh_layer_result = self.layer_creator.create_cutting_layer(
                        bez_mezh_layer_name, crs, bez_mezh_features
                    )
                    log_info(f"Msm_26_4: Создан слой {bez_mezh_layer_name} ({len(bez_mezh_features)} объектов)")

            # Финализация статистики
            self.statistics['processing_time'] = time.time() - start_time
            self.statistics['razdel_created'] = len(razdel_features) if razdel_features else 0
            self.statistics['ngs_created'] = len(ngs_features) if ngs_features else 0
            self.statistics['izm_created'] = len(izm_features) if izm_features else 0
            self.statistics['bez_mezh_created'] = len(bez_mezh_features) if bez_mezh_features else 0
            self.statistics['razdel_points'] = len(razdel_points_data)
            self.statistics['ngs_points'] = len(ngs_points_data)

            log_info(f"Msm_26_4: {zpr_type} завершено за "
                    f"{self.statistics['processing_time']:.2f} сек. "
                    f"Раздел={self.statistics['razdel_created']}, НГС={self.statistics['ngs_created']}, "
                    f"Изм={self.statistics['izm_created']}, Без_Меж={self.statistics['bez_mezh_created']}")

            return {
                'razdel_count': self.statistics['razdel_created'],
                'ngs_count': self.statistics['ngs_created'],
                'izm_count': self.statistics['izm_created'],
                'bez_mezh_count': self.statistics['bez_mezh_created'],
                'razdel_layer': razdel_layer_result,
                'ngs_layer': ngs_layer_result,
                'izm_layer': izm_layer_result,
                'bez_mezh_layer': bez_mezh_layer_result,
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
        zpr_type: str,
        excluded_zu_ids: Optional[set] = None
    ) -> Tuple[List[Dict], List[Dict]]:
        """Первичная нарезка ЗПР по границам ЗУ

        Args:
            zpr_layer: Слой ЗПР
            zu_layer: Слой Выборка_ЗУ
            zpr_type: Тип ЗПР
            excluded_zu_ids: Множество fid ЗУ исключённых из нарезки (Изм/Без_Меж)

        Returns:
            Tuple: (razdel_data, ngs_data) - списки словарей с геометрией и атрибутами
        """
        if excluded_zu_ids is None:
            excluded_zu_ids = set()
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

            # Извлекаем ВРИ из ЗПР для передачи в Раздел/НГС
            zpr_vri = None
            for vri_field in ['ВРИ', 'VRI', 'vri']:
                if vri_field in zpr_feature.fields().names():
                    zpr_vri = zpr_feature[vri_field]
                    break

            # Находим пересекающиеся ЗУ
            intersecting_zu = self._find_intersecting_features(zpr_geom, zu_layer, zu_index)

            # Нарезка по каждому пересекающемуся ЗУ
            processed_area = QgsGeometry()  # Уже обработанная область

            for zu_feature in intersecting_zu:
                # Пропускаем ЗУ которые уже обработаны как Изм/Без_Меж
                if zu_feature.id() in excluded_zu_ids:
                    continue

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
                        'zpr_vri': zpr_vri,  # ВРИ из ЗПР для План_ВРИ
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
                            'zpr_vri': zpr_vri,  # ВРИ из ЗПР для План_ВРИ
                            'overlays': {}
                        })

                    if filtered_count > 0:
                        log_info(f"Msm_26_4: НГС от ЗПР ID={zpr_id}: отфильтровано {filtered_count} "
                                f"микро-полигонов (площадь < {MIN_NGS_AREA} м2)")

        return razdel_data, ngs_data

    def _detect_and_process_no_change(
        self,
        zpr_layer: QgsVectorLayer,
        zu_layer: QgsVectorLayer,
        zpr_type: str,
        izm_layer_name: str,
        bez_mezh_layer_name: str
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], set]:
        """Детекция и обработка ЗУ без изменения геометрии (Изм/Без_Меж)

        Args:
            zpr_layer: Слой ЗПР
            zu_layer: Слой Выборка_ЗУ
            zpr_type: Тип ЗПР (ОКС, ЛО, ВО)
            izm_layer_name: Имя слоя Изменяемые
            bez_mezh_layer_name: Имя слоя Без_Меж

        Returns:
            Tuple[izm_features, bez_mezh_features, excluded_zu_ids]:
                - izm_features: features_data для слоя Изм
                - bez_mezh_features: features_data для слоя Без_Меж
                - excluded_zu_ids: set fid ЗУ которые НЕ требуют нарезки
        """
        # Lazy imports для избежания циклических зависимостей
        from Daman_QGIS.database import BaseReferenceLoader
        from Daman_QGIS.tools.F_2_cutting.submodules.Fsm_2_1_7_no_change_detector import (
            Fsm_2_1_7_NoChangeDetector,
            ZuClassification,
        )
        from Daman_QGIS.tools.F_2_cutting.submodules.Fsm_2_1_8_izmenyaemye_processor import (
            Fsm_2_1_8_IzmenyaemyeProcessor,
        )
        from Daman_QGIS.tools.F_2_cutting.submodules.Fsm_2_1_9_bez_mezh_processor import (
            Fsm_2_1_9_BezMezhProcessor,
        )
        from Daman_QGIS.managers.validation.submodules.Msm_21_1_existing_vri_validator import (
            Msm_21_1_ExistingVRIValidator,
        )

        # Инициализация валидатора ВРИ для мягкого сравнения
        vri_validator = None
        try:
            loader = BaseReferenceLoader()
            vri_data = loader._load_json('VRI.json')
            if vri_data:
                vri_validator = Msm_21_1_ExistingVRIValidator(vri_data)
                log_info("Msm_26_4: Инициализирован ExistingVRIValidator для soft validation ВРИ")
            else:
                log_warning("Msm_26_4: VRI.json не загружен, используется строгое сравнение ВРИ")
        except Exception as e:
            log_warning(f"Msm_26_4: Ошибка инициализации VRI валидатора: {e}")

        # Инициализация детектора с валидатором
        detector = Fsm_2_1_7_NoChangeDetector(
            zpr_layer=zpr_layer,
            zu_layer=zu_layer,
            vri_validator=vri_validator
        )

        # Выполняем детекцию
        results, stats = detector.detect_all()

        # Собираем пары (zu_fid, zpr_fid) для каждой классификации
        izm_pairs = []
        bez_mezh_pairs = []
        excluded_zu_ids = set()

        for result in results:
            if result.classification == ZuClassification.IZMENYAEMYE:
                if result.zpr_fid is not None:
                    izm_pairs.append((result.zu_fid, result.zpr_fid))
                    excluded_zu_ids.add(result.zu_fid)
            elif result.classification == ZuClassification.BEZ_MEZH:
                if result.zpr_fid is not None:
                    bez_mezh_pairs.append((result.zu_fid, result.zpr_fid))
                    excluded_zu_ids.add(result.zu_fid)
            # RAZDEL - не исключаем, пойдёт в _cut_by_zu

        # Процессор для Изменяемых
        izm_features = []
        if izm_pairs:
            izm_processor = Fsm_2_1_8_IzmenyaemyeProcessor(
                zu_layer=zu_layer,
                zpr_layer=zpr_layer,
                attribute_mapper=self.attribute_mapper
            )
            izm_features = izm_processor.create_features(
                izm_zu_with_zpr=izm_pairs,
                layer_name=izm_layer_name,
                zpr_type=zpr_type
            )
            # Initial ИЗМ = VRI mismatch (из Fsm_2_1_7)
            for feat in izm_features:
                feat['_izm_flags'] = {'vri': True, 'category': False, 'area': False}

        # Процессор для Без_Меж
        bez_mezh_features = []
        if bez_mezh_pairs:
            bez_mezh_processor = Fsm_2_1_9_BezMezhProcessor(
                zu_layer=zu_layer,
                zpr_layer=zpr_layer,
                attribute_mapper=self.attribute_mapper
            )
            bez_mezh_features = bez_mezh_processor.create_features(
                bez_mezh_zu_with_zpr=bez_mezh_pairs,
                layer_name=bez_mezh_layer_name,
                zpr_type=zpr_type
            )
            # Без_Меж изначально без флагов (могут перейти в ИЗМ позже)
            for feat in bez_mezh_features:
                feat['_izm_flags'] = {'vri': False, 'category': False, 'area': False}

        log_info(f"Msm_26_4: Детекция no_change для {zpr_type}: "
                f"Изм={len(izm_features)}, Без_Меж={len(bez_mezh_features)}, "
                f"исключено ЗУ={len(excluded_zu_ids)}")

        return izm_features, bez_mezh_features, excluded_zu_ids

    def _geocode_ngs_addresses(
        self,
        ngs_data: List[Dict[str, Any]],
        crs: QgsCoordinateReferenceSystem
    ) -> List[Dict[str, Any]]:
        """Шаг 2.6: Обратное геокодирование НГС -- адрес по центроиду через DaData

        Для каждого НГС-полигона определяет адрес по координатам центроида.
        Результат записывается в zu_attributes['Адрес_Местоположения'].

        Args:
            ngs_data: Данные НГС после нарезки
            crs: CRS проекта (МСК)

        Returns:
            ngs_data с заполненными адресами
        """
        from Daman_QGIS.managers import registry

        geocoder = registry.get('M_39')
        if not geocoder or not geocoder.is_configured():
            log_warning("Msm_26_4: DaData не настроен, адреса НГС не заполнены")
            return ngs_data

        # Трансформация CRS проекта -> WGS-84
        wgs84_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(crs, wgs84_crs, QgsProject.instance())

        geocoded_count = 0
        failed_count = 0

        for item in ngs_data:
            geom = item['geometry']
            if geom.isEmpty():
                continue

            # pointOnSurface гарантирует точку внутри полигона (centroid может быть вне)
            point_geom = geom.pointOnSurface()
            if point_geom.isEmpty():
                point_geom = geom.centroid()

            point = point_geom.asPoint()

            try:
                wgs84_point = transform.transform(QgsPointXY(point.x(), point.y()))
                lat = wgs84_point.y()
                lon = wgs84_point.x()

                result = geocoder.geolocate(lat=lat, lon=lon, radius_meters=500)

                if result:
                    address = geocoder.format_address_by_quality(result)
                    item['zu_attributes']['Адрес_Местоположения'] = address
                    geocoded_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                log_warning(f"Msm_26_4: Ошибка геокодирования НГС: {e}")
                failed_count += 1

        log_info(f"Msm_26_4: Геокодирование НГС: {geocoded_count} успешно, "
                f"{failed_count} не найдено (всего {len(ngs_data)})")

        return ngs_data

    def _cut_by_overlays(
        self,
        data: List[Dict],
        overlay_layers: Dict[str, Dict[str, Any]],
        layer_name: str,
        zpr_type: str
    ) -> List[Dict]:
        """Нарезка по overlay слоям (индивидуальная, по каждому feature)

        ЗК РФ ст. 11.9 п. 3: границы ЗУ не должны пересекать границы МО и НП.
        Нарезка выполняется по каждому feature overlay-слоя индивидуально,
        а не по union -- это сохраняет внутренние границы между смежными МО/НП
        и позволяет маппить названия.

        Args:
            data: Исходные данные (после нарезки по ЗУ)
            overlay_layers: {тип: {'layer': QgsVectorLayer, 'name_field': str}}
            layer_name: Имя целевого слоя
            zpr_type: Тип ЗПР

        Returns:
            List[Dict]: Обновлённые данные после нарезки
        """
        result = data

        for overlay_type, overlay_config in overlay_layers.items():
            overlay_layer = overlay_config['layer']
            name_field = overlay_config['name_field']

            if not overlay_layer or overlay_layer.featureCount() == 0:
                continue

            log_info(f"Msm_26_4: Индивидуальная нарезка по {overlay_type} "
                    f"({overlay_layer.featureCount()} features)")

            # Spatial index для быстрого поиска пересекающихся overlay features
            overlay_index = self._build_spatial_index(overlay_layer)

            new_result = []

            for item in result:
                geom = item['geometry']

                if geom.isEmpty():
                    continue

                zu_attrs = item['zu_attributes']
                overlays = item.get('overlays', {}).copy()
                zpr_vri = item.get('zpr_vri')

                # Находим overlay features, пересекающие этот контур
                intersecting = self._find_intersecting_features(
                    geom, overlay_layer, overlay_index
                )

                if not intersecting:
                    # Контур вне всех overlay features этого типа
                    new_result.append({
                        'geometry': geom,
                        'zu_attributes': zu_attrs,
                        'zpr_vri': zpr_vri,
                        'overlays': overlays
                    })
                    continue

                # Нарезка по каждому overlay feature
                remaining = QgsGeometry(geom)
                has_cuts = False

                for ov_feature in intersecting:
                    if remaining.isEmpty():
                        break

                    ov_geom = ov_feature.geometry()
                    if ov_geom.isEmpty():
                        continue

                    # Извлечение названия из overlay feature
                    ov_name = self._get_overlay_name(ov_feature, name_field)

                    # Проверяем пересечение с этим конкретным overlay feature
                    if not self.geometry_processor.need_additional_cut(remaining, ov_geom):
                        # Не нужно резать -- проверяем, полностью ли внутри
                        test_intersection = remaining.intersection(ov_geom)
                        if not test_intersection.isEmpty():
                            # Полностью внутри этого overlay feature
                            inside_overlays = overlays.copy()
                            inside_overlays[overlay_type] = ov_name
                            new_result.append({
                                'geometry': remaining,
                                'zu_attributes': zu_attrs,
                                'zpr_vri': zpr_vri,
                                'overlays': inside_overlays
                            })
                            remaining = QgsGeometry()
                            has_cuts = True
                    else:
                        # Частичное пересечение -- вырезаем intersection
                        inside = self.geometry_processor.intersection(remaining, ov_geom)
                        outside = self.geometry_processor.difference(remaining, ov_geom)

                        if not inside.isEmpty():
                            inside_overlays = overlays.copy()
                            inside_overlays[overlay_type] = ov_name

                            for poly_geom in self.geometry_processor.extract_polygons(inside):
                                if not poly_geom.isEmpty():
                                    new_result.append({
                                        'geometry': poly_geom,
                                        'zu_attributes': zu_attrs.copy(),
                                        'zpr_vri': zpr_vri,
                                        'overlays': inside_overlays.copy()
                                    })
                            has_cuts = True

                        remaining = outside if not outside.isEmpty() else QgsGeometry()

                # Остаток (вне всех overlay features этого типа)
                if not remaining.isEmpty():
                    for poly_geom in self.geometry_processor.extract_polygons(remaining):
                        if not poly_geom.isEmpty():
                            new_result.append({
                                'geometry': poly_geom,
                                'zu_attributes': zu_attrs.copy(),
                                'zpr_vri': zpr_vri,
                                'overlays': overlays.copy()
                            })

            result = new_result
            log_info(f"Msm_26_4: После нарезки по {overlay_type}: {len(result)} объектов")

        return result

    @staticmethod
    def _get_overlay_name(feature: QgsFeature, name_field: str) -> str:
        """Извлечь название из overlay feature

        Args:
            feature: Feature overlay-слоя
            name_field: Имя поля с названием

        Returns:
            str: Название или '-' если поле пустое
        """
        if name_field in feature.fields().names():
            value = feature[name_field]
            if value and str(value).strip():
                return str(value).strip()
        return "-"

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

        # Сортировка контуров от СЗ к ЮВ (ID=1 → самый СЗ контур)
        data = self._sort_data_by_northwest(data)

        for item in data:
            geom = item['geometry']
            zu_attrs = item['zu_attributes']
            overlays = item.get('overlays', {})
            zpr_vri = item.get('zpr_vri')  # ВРИ из ЗПР

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

            # План_ВРИ = ВРИ из ЗПР (строгий, "причёсанный")
            if zpr_vri:
                attributes['План_ВРИ'] = zpr_vri
            else:
                attributes['План_ВРИ'] = '-'

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

    @staticmethod
    def _sort_data_by_northwest(data: List[Dict]) -> List[Dict]:
        """Сортировка данных нарезки от СЗ к ЮВ

        Обеспечивает назначение ID контуров в порядке от северо-западного
        к юго-восточному (по расстоянию центроида до СЗ угла глобального MBR).

        Args:
            data: Данные нарезки (каждый элемент содержит 'geometry')

        Returns:
            Отсортированный список
        """
        if len(data) <= 1:
            return data

        # Глобальный MBR
        global_min_x = float('inf')
        global_max_y = float('-inf')
        centroids = []

        for item in data:
            geom = item['geometry']
            if not geom.isEmpty():
                centroid = geom.centroid().asPoint()
                centroids.append((centroid.x(), centroid.y()))
                bbox = geom.boundingBox()
                global_min_x = min(global_min_x, bbox.xMinimum())
                global_max_y = max(global_max_y, bbox.yMaximum())
            else:
                centroids.append(None)

        nw_x, nw_y = global_min_x, global_max_y

        def sort_key(idx_item):
            idx, _ = idx_item
            c = centroids[idx]
            if c is None:
                return float('inf')
            return (c[0] - nw_x) ** 2 + (c[1] - nw_y) ** 2

        indexed = list(enumerate(data))
        indexed.sort(key=sort_key)
        return [item for _, item in indexed]

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
        PointNumberingManager, _, _, _, _, _ = _get_managers()
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
