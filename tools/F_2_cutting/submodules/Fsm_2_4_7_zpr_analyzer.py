# -*- coding: utf-8 -*-
"""
Fsm_2_4_7_ZprAnalyzer - Анализ соответствия контуров контурам ЗПР

НАЗНАЧЕНИЕ:
    Определяет, к какому контуру ЗПР относится каждый контур нарезки (по
    максимальной доле пересечения от площади контура), и вычисляет максимальный
    ID контуров ЗПР для нумерации промежуточных контуров.

ОСОБЕННОСТИ:
    - Порог совпадения — доля от площади КОНТУРА, не от площади ЗПР.
    - Контуры с пустой геометрией пропускаются.
    - Значение поля ID слоя ЗПР не гарантировано целым: применяется фоллбэк.

ИСПОЛЬЗОВАНИЕ:
    Вызывается F_2_4_Staging перед формированием этапов.
"""

from typing import Dict, List, Tuple
from collections import defaultdict

from qgis.core import QgsVectorLayer

from Daman_QGIS.utils import log_info, log_warning


class Fsm_2_4_7_ZprAnalyzer:
    """Анализ соответствия контуров нарезки контурам ЗПР"""

    def __init__(self, match_threshold: float) -> None:
        """Инициализация

        Args:
            match_threshold: Порог доли пересечения с ЗПР (из F_2_4_Staging)
        """
        self.ZPR_MATCH_THRESHOLD = match_threshold

    @staticmethod
    def zpr_id(feature) -> int:
        """Единственный способ прочитать ID контура ЗПР

        Схема требует целочисленный ID (M_28, схема ZPR, `field_types`), и
        проверка типов в валидаторе блокирующая. Фоллбэков на fid здесь нет
        намеренно: два разных способа чтения одного поля давали РАЗНЫЕ значения
        для одного объекта, из-за чего диапазон промежуточных ID накладывался
        на реальные ID контуров ЗПР.

        Args:
            feature: QgsFeature контура ЗПР

        Returns:
            int: значение поля ID

        Raises:
            ValueError: поле отсутствует либо значение не целое
        """
        if feature.fields().indexFromName('ID') < 0:
            raise ValueError(f"В слое ЗПР нет поля ID (fid={feature.id()})")

        raw = feature['ID']
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw

        raise ValueError(
            f"Поле ID слоя ЗПР должно быть целым; получено {raw!r} "
            f"(тип {type(raw).__name__}), fid={feature.id()}"
        )

    def get_max_zpr_id(self, zpr_layer: QgsVectorLayer) -> int:
        """Получение максимального ID контуров ЗПР

        От максимума отсчитывается диапазон промежуточных контуров, поэтому
        значение обязано читаться тем же способом, что и при привязке контуров
        (`zpr_id`).

        Raises:
            ValueError: ID хотя бы одного контура не целый — прогон прекращается
        """
        max_id = 0
        for feature in zpr_layer.getFeatures():
            max_id = max(max_id, self.zpr_id(feature))
        return max_id

    def analyze_zpr_matching(
        self,
        source_layer: QgsVectorLayer,
        zpr_layer: QgsVectorLayer
    ) -> Tuple[Dict[int, int], Dict[int, List[int]]]:
        """Анализ соответствия участков контурам ЗПР

        Определяет к какому контуру ЗПР относится каждый участок
        по максимальной площади пересечения (>= 95%).

        ID контура читается через `zpr_id` — тем же способом, что и в
        `get_max_zpr_id`.

        Raises:
            ValueError: ID хотя бы одного контура ЗПР не целый

        Returns:
            Tuple:
                - feature_zpr_mapping: {feature_id: zpr_id}
                - features_by_zpr: {zpr_id: [feature_ids]}
        """
        feature_zpr_mapping: Dict[int, int] = {}
        features_by_zpr: Dict[int, List[int]] = defaultdict(list)

        # Кэшируем геометрии и ID контуров ЗПР
        zpr_data = []
        for zpr_feature in zpr_layer.getFeatures():
            zpr_geom = zpr_feature.geometry()
            if zpr_geom.isEmpty():
                continue

            zpr_data.append({
                'id': self.zpr_id(zpr_feature),
                'geometry': zpr_geom,
                'area': zpr_geom.area()
            })

        # Анализируем каждый участок
        for feature in source_layer.getFeatures():
            feature_id = feature.id()
            feature_geom = feature.geometry()

            if feature_geom.isEmpty():
                continue

            feature_area = feature_geom.area()

            # Находим ЗПР с максимальным пересечением
            best_zpr_id = None
            best_intersection_ratio = 0.0

            for zpr in zpr_data:
                intersection = feature_geom.intersection(zpr['geometry'])
                if intersection.isEmpty():
                    continue

                intersection_area = intersection.area()
                # Отношение площади пересечения к площади участка
                ratio = intersection_area / feature_area if feature_area > 0 else 0

                if ratio > best_intersection_ratio:
                    best_intersection_ratio = ratio
                    best_zpr_id = zpr['id']

            # Если пересечение >= 80% - привязываем к ЗПР
            if best_zpr_id is not None and best_intersection_ratio >= self.ZPR_MATCH_THRESHOLD:
                feature_zpr_mapping[feature_id] = best_zpr_id
                features_by_zpr[best_zpr_id].append(feature_id)
            else:
                # Участок не соответствует ни одному ЗПР достаточно
                log_warning(f"Fsm_2_4_7: Участок {feature_id} не соответствует ни одному ЗПР "
                           f"(лучшее пересечение {best_intersection_ratio:.1%})")

        return feature_zpr_mapping, dict(features_by_zpr)
