# -*- coding: utf-8 -*-
"""
Msm_23_1 - GeometryAnalyzer: Геометрический анализ пересечения ОКС и ЗУ

Назначение:
    Выполняет геометрический анализ пересечений объектов ОКС с земельными
    участками (ЗУ) используя пространственный индекс QgsSpatialIndex.

Логика:
    1. Создание пространственного индекса для ЗУ
    2. Для каждого ОКС:
       - Получение bbox -> поиск кандидатов в индексе
       - Детальная проверка intersects() для кандидатов
       - Расчёт площади пересечения intersection().area()
       - Фильтрация по минимальной площади (>= 1 м2)
    3. Результат: {КН_ОКС: [список_КН_ЗУ]}

Best practices:
    - QgsSpatialIndex для быстрого поиска кандидатов по bbox
    - prepareGeometry() для оптимизации множественных проверок
    - contains() проверка перед intersection() для экономии вычислений
    - Кэширование геометрий для избежания повторных getFeatures()
"""

from typing import Dict, List, Optional
from qgis.core import (
    QgsVectorLayer, QgsGeometry,
    QgsSpatialIndex, QgsCoordinateTransform, QgsProject
)

from Daman_QGIS.utils import log_info, log_warning


class GeometryAnalyzer:
    """Геометрический анализатор пересечения ОКС и ЗУ"""

    def __init__(self, min_intersection_area: float = 1.0):
        """
        Инициализация

        Args:
            min_intersection_area: Минимальная площадь пересечения (м2)
        """
        self.min_intersection_area = min_intersection_area

    def analyze(
        self,
        oks_layer: QgsVectorLayer,
        zu_layer: QgsVectorLayer,
        min_intersection_area: Optional[float] = None
    ) -> Dict[str, List[str]]:
        """
        Выполнить геометрический анализ пересечений

        Args:
            oks_layer: Слой ОКС
            zu_layer: Слой ЗУ
            min_intersection_area: Минимальная площадь (переопределяет default)

        Returns:
            dict: {КН_ОКС: [список_КН_ЗУ_по_геометрии]}
        """
        if min_intersection_area is not None:
            self.min_intersection_area = min_intersection_area

        result: Dict[str, List[str]] = {}

        # Получаем индексы полей КН
        oks_kn_idx = oks_layer.fields().indexOf('КН')
        zu_kn_idx = zu_layer.fields().indexOf('КН')

        if oks_kn_idx == -1:
            log_warning("Msm_23_1: Поле 'КН' не найдено в слое ОКС")
            return result

        if zu_kn_idx == -1:
            log_warning("Msm_23_1: Поле 'КН' не найдено в слое ЗУ")
            return result

        # Проверяем CRS слоёв
        transform = self._get_coordinate_transform(oks_layer, zu_layer)

        # Создаём пространственный индекс для ЗУ
        # Best practice: кэшируем features и геометрии для избежания повторных вызовов
        log_info("Msm_23_1: Создание пространственного индекса для ЗУ...")
        zu_index = QgsSpatialIndex()
        zu_cache: Dict[int, tuple] = {}  # {fid: (kn, geometry)} - кэш КН и геометрий

        for feature in zu_layer.getFeatures():
            if not feature.hasGeometry():
                continue
            geom = feature.geometry()
            if geom.isNull() or geom.isEmpty():
                continue

            zu_kn = feature[zu_kn_idx]
            if not zu_kn:
                continue

            zu_index.addFeature(feature)
            # Кэшируем КН и геометрию сразу
            zu_cache[feature.id()] = (str(zu_kn).strip(), QgsGeometry(geom))

        log_info(f"Msm_23_1: Индексировано {len(zu_cache)} ЗУ")

        # Анализируем каждый ОКС
        processed = 0
        for oks_feature in oks_layer.getFeatures():
            oks_kn = oks_feature[oks_kn_idx]
            if not oks_kn:
                continue

            oks_kn = str(oks_kn).strip()

            # Получаем геометрию ОКС
            if not oks_feature.hasGeometry():
                result[oks_kn] = []
                continue

            oks_geom = oks_feature.geometry()
            if oks_geom.isNull() or oks_geom.isEmpty():
                result[oks_kn] = []
                continue

            # Трансформируем геометрию если нужно
            if transform:
                oks_geom_transformed = QgsGeometry(oks_geom)
                oks_geom_transformed.transform(transform)
            else:
                oks_geom_transformed = oks_geom

            # Ищем пересекающиеся ЗУ
            intersecting_zu = self._find_intersecting_zu(
                oks_geom_transformed,
                zu_index,
                zu_cache
            )

            result[oks_kn] = intersecting_zu
            processed += 1

            # Логируем прогресс каждые 100 объектов
            if processed % 100 == 0:
                log_info(f"Msm_23_1: Обработано {processed} ОКС...")

        log_info(f"Msm_23_1: Анализ завершён. Обработано {processed} ОКС")
        return result

    def _get_coordinate_transform(
        self,
        oks_layer: QgsVectorLayer,
        zu_layer: QgsVectorLayer
    ) -> Optional[QgsCoordinateTransform]:
        """
        Получить трансформацию координат если CRS слоёв различаются

        Args:
            oks_layer: Слой ОКС
            zu_layer: Слой ЗУ

        Returns:
            QgsCoordinateTransform или None если трансформация не нужна
        """
        oks_crs = oks_layer.crs()
        zu_crs = zu_layer.crs()

        if oks_crs != zu_crs:
            log_info(
                f"Msm_23_1: CRS различаются. "
                f"ОКС: {oks_crs.authid()}, ЗУ: {zu_crs.authid()}. "
                f"Будет выполнена трансформация."
            )
            return QgsCoordinateTransform(
                oks_crs,
                zu_crs,
                QgsProject.instance()
            )

        return None

    def _find_intersecting_zu(
        self,
        oks_geom: QgsGeometry,
        zu_index: QgsSpatialIndex,
        zu_cache: Dict[int, tuple]
    ) -> List[str]:
        """
        Найти все ЗУ, пересекающиеся с ОКС

        Best practices:
        1. Spatial index для быстрого поиска кандидатов по bbox
        2. prepareGeometry() для оптимизации множественных проверок
        3. contains() проверка перед intersection() для экономии вычислений
        4. Кэширование геометрий для избежания повторных getFeatures()

        Args:
            oks_geom: Геометрия ОКС
            zu_index: Пространственный индекс ЗУ
            zu_cache: Словарь {fid: (kn, geometry)} - кэш КН и геометрий

        Returns:
            list: Список КН ЗУ, пересекающихся с ОКС
        """
        result: List[str] = []

        # Получаем bbox ОКС
        bbox = oks_geom.boundingBox()

        # Поиск кандидатов по bbox (шаг 1 - быстрая фильтрация)
        candidate_ids = zu_index.intersects(bbox)

        if not candidate_ids:
            return result

        # Создаём geometry engine для оптимизации множественных проверок
        engine = QgsGeometry.createGeometryEngine(oks_geom.constGet())
        engine.prepareGeometry()

        # Детальная проверка каждого кандидата (шаг 2 - точная проверка)
        for zu_fid in candidate_ids:
            cached = zu_cache.get(zu_fid)
            if not cached:
                continue

            zu_kn, zu_geom = cached

            # Быстрая проверка через prepared geometry
            if not engine.intersects(zu_geom.constGet()):
                continue

            # Проверяем contains - если ОКС полностью внутри ЗУ,
            # не нужен расчёт intersection
            if zu_geom.contains(oks_geom):
                result.append(zu_kn)
                continue

            # Вычисляем площадь пересечения
            try:
                intersection = oks_geom.intersection(zu_geom)

                if intersection.isNull() or intersection.isEmpty():
                    continue

                # Проверяем площадь пересечения >= 1 м2
                intersection_area = intersection.area()
                if intersection_area < self.min_intersection_area:
                    continue

                result.append(zu_kn)

            except Exception as e:
                log_warning(f"Msm_23_1: Ошибка расчёта пересечения: {e}")
                continue

        return result

    def analyze_single_geometry(
        self,
        geometry: QgsGeometry,
        oks_layer: QgsVectorLayer
    ) -> List[str]:
        """
        Анализ пересечений одной геометрии ЗУ со всеми ОКС.

        Используется для нарезки/коррекции - анализирует новую геометрию
        нарезанного контура и находит все ОКС, которые с ней пересекаются.

        Args:
            geometry: Геометрия нарезанного контура ЗУ
            oks_layer: Слой ОКС для анализа (обычно L_2_1_2_Выборка_ОКС)

        Returns:
            Список КН ОКС, пересекающихся с геометрией
        """
        result: List[str] = []

        if geometry is None or geometry.isEmpty():
            return result

        if oks_layer is None or oks_layer.featureCount() == 0:
            return result

        # Получаем индекс поля КН в слое ОКС
        kn_idx = oks_layer.fields().indexOf('КН')
        if kn_idx == -1:
            log_warning("Msm_23_1: Поле 'КН' не найдено в слое ОКС")
            return result

        # Создаём spatial index для ОКС (для оптимизации)
        oks_index = QgsSpatialIndex()
        oks_cache: Dict[int, tuple] = {}  # {fid: (kn, geometry)}

        for feature in oks_layer.getFeatures():
            if not feature.hasGeometry():
                continue
            geom = feature.geometry()
            if geom.isNull() or geom.isEmpty():
                continue

            oks_kn = feature[kn_idx]
            if not oks_kn:
                continue

            oks_index.addFeature(feature)
            oks_cache[feature.id()] = (str(oks_kn).strip(), QgsGeometry(geom))

        if not oks_cache:
            return result

        # Получаем bbox геометрии ЗУ
        bbox = geometry.boundingBox()

        # Поиск кандидатов по bbox
        candidate_ids = oks_index.intersects(bbox)

        if not candidate_ids:
            return result

        # Создаём geometry engine для оптимизации множественных проверок
        engine = QgsGeometry.createGeometryEngine(geometry.constGet())
        engine.prepareGeometry()

        # Детальная проверка каждого кандидата
        for oks_fid in candidate_ids:
            cached = oks_cache.get(oks_fid)
            if not cached:
                continue

            oks_kn, oks_geom = cached

            # Быстрая проверка через prepared geometry
            if not engine.intersects(oks_geom.constGet()):
                continue

            # Проверяем contains - если ЗУ полностью содержит ОКС
            if geometry.contains(oks_geom):
                result.append(oks_kn)
                continue

            # Вычисляем площадь пересечения
            try:
                intersection = geometry.intersection(oks_geom)

                if intersection.isNull() or intersection.isEmpty():
                    continue

                # Проверяем площадь пересечения >= min_intersection_area
                intersection_area = intersection.area()
                if intersection_area < self.min_intersection_area:
                    continue

                result.append(oks_kn)

            except Exception as e:
                log_warning(f"Msm_23_1: Ошибка расчёта пересечения для ОКС {oks_kn}: {e}")
                continue

        return result
