# -*- coding: utf-8 -*-
"""
Fsm_3_1_5_KKMatcher - Привязка НГС к кадастровым кварталам

Определяет кадастровый квартал для частей ЗПР, находящихся вне границ ЗУ (НГС).
Использует слой L_2_1_3_Выборка_КК для поиска квартала с наибольшей площадью
пересечения.

Бизнес-логика:
- НГС всегда должны иметь привязку к кадастровому кварталу
- Валидный квартал: XX:XX:XXXXXXX где последние 7 цифр НЕ все нули
- При попадании в несколько кварталов - выбор по наибольшей площади
- Результат записывается в поле КН_ЗУ (условный КН квартала + :ЗУ1)
"""

import re
from typing import Dict, List, Optional, Tuple, Any

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsSpatialIndex,
)

from Daman_QGIS.utils import log_info, log_warning, log_error


class Fsm_3_1_5_KKMatcher:
    """Привязка НГС к кадастровым кварталам"""

    # Паттерн валидного кадастрового квартала
    # XX:XX:XXXXXX или XX:XX:XXXXXXX (6-7 цифр) где последняя часть НЕ все нули
    QUARTER_PATTERN = re.compile(r'^(\d{2}):(\d{2}):(\d{6,7})$')

    def __init__(self, kk_layer: Optional[QgsVectorLayer] = None) -> None:
        """Инициализация матчера

        Args:
            kk_layer: Слой L_2_1_3_Выборка_КК (может быть None - тогда привязка не выполняется)
        """
        self.kk_layer = kk_layer
        self._spatial_index: Optional[QgsSpatialIndex] = None
        self._features_dict: Dict[int, QgsFeature] = {}
        self._valid_quarters: Dict[int, str] = {}  # {fid: cad_num}

        if kk_layer and kk_layer.isValid():
            self._build_index()

    def _build_index(self) -> None:
        """Построение пространственного индекса и фильтрация валидных кварталов"""
        if not self.kk_layer:
            return

        self._spatial_index = QgsSpatialIndex()
        valid_count = 0
        total_count = 0

        for feature in self.kk_layer.getFeatures():
            total_count += 1
            geom = feature.geometry()

            if not geom or geom.isEmpty():
                continue

            # Получаем КН из поля cad_num
            cad_num = feature.attribute('cad_num')
            if not cad_num:
                continue

            cad_num = str(cad_num).strip()

            # Проверяем что это валидный квартал (не нулёвка)
            if not self.is_valid_quarter(cad_num):
                log_warning(f"Fsm_3_1_5: КК '{cad_num}' отклонён (нулёвка или неверный формат)")
                continue

            log_info(f"Fsm_3_1_5: КК '{cad_num}' - валидный квартал")

            # Добавляем в индекс
            if self._spatial_index is not None:
                self._spatial_index.addFeature(feature)
            self._features_dict[feature.id()] = feature
            self._valid_quarters[feature.id()] = cad_num
            valid_count += 1

        log_info(f"Fsm_3_1_5: Построен индекс КК: {valid_count} валидных кварталов из {total_count}")

    def is_valid_quarter(self, cad_num: str) -> bool:
        """Проверка что КН - квартал, а не нулёвка (округ/район)

        Валидный квартал: XX:XX:XXXXXXX где последние 7 цифр НЕ все нули

        Args:
            cad_num: Кадастровый номер (например "91:01:004003")

        Returns:
            True если это валидный квартал

        Examples:
            91:01:004003 -> True  (квартал)
            91:01:012001 -> True  (квартал)
            91:00:000000 -> False (округ - нулёвка)
            91:01:000000 -> False (район - нулёвка)
        """
        if not cad_num:
            return False

        match = self.QUARTER_PATTERN.match(cad_num)
        if not match:
            return False

        # Проверяем что последняя часть (6-7 цифр) не все нули
        quarter_part = match.group(3)
        if quarter_part in ('000000', '0000000'):
            return False

        # Также проверяем что район не нулевой (вторая часть)
        district_part = match.group(2)
        if district_part == '00':
            return False

        return True

    def find_quarter_for_geometry(self, geom: QgsGeometry) -> Optional[str]:
        """Найти кадастровый квартал с наибольшей площадью пересечения

        Args:
            geom: Геометрия НГС полигона

        Returns:
            Кадастровый номер квартала или None
        """
        if not self._spatial_index or not geom or geom.isEmpty():
            return None

        bbox = geom.boundingBox()
        candidate_ids = self._spatial_index.intersects(bbox)

        if not candidate_ids:
            return None

        best_quarter: Optional[str] = None
        best_area: float = 0.0

        for fid in candidate_ids:
            feature = self._features_dict.get(fid)
            if not feature:
                continue

            kk_geom = feature.geometry()
            if not kk_geom or kk_geom.isEmpty():
                continue

            # Проверяем реальное пересечение
            if not geom.intersects(kk_geom):
                continue

            # Вычисляем площадь пересечения
            intersection = geom.intersection(kk_geom)
            if intersection.isEmpty():
                continue

            area = intersection.area()

            if area > best_area:
                best_area = area
                best_quarter = self._valid_quarters.get(fid)

        return best_quarter

    def match_ngs_to_quarters(
        self,
        ngs_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Массовая привязка НГС к кадастровым кварталам

        Для каждого НГС находит квартал и прописывает условный КН в атрибуты.

        Args:
            ngs_data: Список словарей НГС с ключами:
                     - 'geometry': QgsGeometry
                     - 'zu_attributes': dict (будет дополнен)
                     - 'overlays': dict

        Returns:
            Обновлённый список с заполненными КН_ЗУ
        """
        if not self._spatial_index:
            log_warning("Fsm_3_1_5: Слой КК не инициализирован, привязка пропущена")
            return ngs_data

        matched_count = 0
        unmatched_count = 0

        for item in ngs_data:
            geom = item.get('geometry')
            if not geom or geom.isEmpty():
                continue

            # Ищем квартал
            quarter = self.find_quarter_for_geometry(geom)

            if quarter:
                # Записываем номер квартала в поле КН (для последующей генерации Услов_КН)
                item['zu_attributes']['КН'] = quarter
                matched_count += 1
            else:
                # Квартал не найден - оставляем пустым (будет "-")
                unmatched_count += 1

        log_info(f"Fsm_3_1_5: Привязка НГС к КК завершена: "
                f"{matched_count} привязано, {unmatched_count} без квартала")

        return ngs_data

    def get_statistics(self) -> Dict[str, Any]:
        """Получить статистику по индексу

        Returns:
            dict: {'total_kk': int, 'valid_quarters': int}
        """
        return {
            'total_kk': self.kk_layer.featureCount() if self.kk_layer else 0,
            'valid_quarters': len(self._valid_quarters),
        }
