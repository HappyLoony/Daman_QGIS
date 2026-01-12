# -*- coding: utf-8 -*-
"""
Msm_27_1_ValidationEngine - Движок валидации минимальных площадей

Логика:
1. Получение MIN_AREA_VRI из исходного слоя ЗПР по геометрическому пересечению
2. Сравнение Площадь_ОЗУ с минимальной площадью
3. Сбор проблемных контуров для GUI
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any

from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsSpatialIndex

from Daman_QGIS.utils import log_info, log_warning, log_error


@dataclass
class ProblemFeature:
    """Информация о проблемном контуре"""
    feature_id: int
    uslov_kn: str
    plan_vri: str
    actual_area: int
    min_area: int
    deficit: int
    layer_name: str
    geometry: Optional[QgsGeometry] = None


class ValidationEngine:
    """Движок валидации площадей контуров нарезки"""

    # Поля для получения информации из контуров нарезки
    AREA_FIELD = 'Площадь_ОЗУ'
    USLOV_KN_FIELD = 'Услов_КН'
    PLAN_VRI_FIELD = 'План_ВРИ'
    ID_FIELD = 'ID'

    def __init__(
        self,
        zpr_layer: QgsVectorLayer,
        min_area_field: str = 'MIN_AREA_VRI'
    ) -> None:
        """Инициализация движка

        Args:
            zpr_layer: Исходный слой ЗПР с полем MIN_AREA_VRI
            min_area_field: Имя поля с минимальной площадью
        """
        self._zpr_layer = zpr_layer
        self._min_area_field = min_area_field

        # Кэш данных ЗПР: id -> {geometry, min_area}
        self._zpr_cache: List[Dict] = []
        self._spatial_index: Optional[QgsSpatialIndex] = None

        self._build_zpr_cache()

    def _build_zpr_cache(self) -> None:
        """Построение кэша данных ЗПР"""
        if not self._zpr_layer or not self._zpr_layer.isValid():
            log_warning("Msm_27_1: Слой ЗПР невалиден")
            return

        # Проверяем наличие поля
        field_names = [f.name() for f in self._zpr_layer.fields()]
        if self._min_area_field not in field_names:
            log_warning(f"Msm_27_1: Поле {self._min_area_field} отсутствует в слое ЗПР")
            return

        # Строим пространственный индекс
        self._spatial_index = QgsSpatialIndex()

        for feature in self._zpr_layer.getFeatures():
            geom = feature.geometry()
            if geom.isEmpty():
                continue

            feature_id = feature.id()
            min_area_value = feature[self._min_area_field]

            # Парсим значение MIN_AREA_VRI
            min_area = self._parse_min_area(min_area_value)

            self._zpr_cache.append({
                'id': feature_id,
                'geometry': geom,
                'min_area': min_area,  # None если "-" или пусто
            })

            # Добавляем в индекс
            self._spatial_index.addFeature(feature)

        log_info(f"Msm_27_1: Кэш ЗПР построен, {len(self._zpr_cache)} контуров")

    def _parse_min_area(self, value: Any) -> Optional[int]:
        """Парсинг значения MIN_AREA_VRI

        Args:
            value: Значение из поля

        Returns:
            Минимальная площадь в кв.м или None если проверка не нужна
        """
        if value is None:
            return None

        str_value = str(value).strip()

        # "-" означает проверка не требуется
        if str_value in ('-', '', 'NULL', 'None'):
            return None

        try:
            # Пробуем распарсить как число
            return int(float(str_value))
        except (ValueError, TypeError):
            log_warning(f"Msm_27_1: Невалидное значение MIN_AREA_VRI: {value}")
            return None

    def get_min_area_for_geometry(self, geometry: QgsGeometry) -> Optional[int]:
        """Получить минимальную площадь для геометрии по пересечению с ЗПР

        Находит контур ЗПР с максимальной площадью пересечения.

        Args:
            geometry: Геометрия для проверки

        Returns:
            Минимальная площадь или None
        """
        if not self._spatial_index or geometry.isEmpty():
            return None

        # Получаем кандидатов из пространственного индекса
        bbox = geometry.boundingBox()
        candidate_ids = self._spatial_index.intersects(bbox)

        if not candidate_ids:
            return None

        # Находим контур с максимальной площадью пересечения
        best_min_area = None
        best_intersection_area = 0.0

        for zpr_data in self._zpr_cache:
            if zpr_data['id'] not in candidate_ids:
                continue

            zpr_geom = zpr_data['geometry']
            intersection = geometry.intersection(zpr_geom)

            if intersection.isEmpty():
                continue

            intersection_area = intersection.area()
            if intersection_area > best_intersection_area:
                best_intersection_area = intersection_area
                best_min_area = zpr_data['min_area']

        return best_min_area

    def validate_layer(
        self,
        cutting_layer: QgsVectorLayer
    ) -> Tuple[List[Dict], int]:
        """Валидация слоя нарезки

        Args:
            cutting_layer: Слой нарезки (Раздел, НГС, Без_Меж, ПС)

        Returns:
            Tuple:
                - List[Dict]: Список проблемных контуров
                - int: Количество проверенных контуров
        """
        if not cutting_layer or not cutting_layer.isValid():
            return [], 0

        layer_name = cutting_layer.name()
        field_names = [f.name() for f in cutting_layer.fields()]

        # Проверяем наличие необходимых полей
        if self.AREA_FIELD not in field_names:
            log_warning(f"Msm_27_1: Поле {self.AREA_FIELD} отсутствует в слое {layer_name}")
            return [], 0

        problems: List[Dict] = []
        checked_count = 0

        for feature in cutting_layer.getFeatures():
            geom = feature.geometry()
            if geom.isEmpty():
                continue

            checked_count += 1

            # Получаем площадь контура
            area_value = feature[self.AREA_FIELD]
            actual_area = self._parse_area(area_value)

            if actual_area is None:
                # Площадь NULL - это проблема
                problems.append(self._create_problem_dict(
                    feature, layer_name, actual_area=0, min_area=0,
                    error_type='null_area'
                ))
                continue

            # Получаем минимальную площадь по геометрии
            min_area = self.get_min_area_for_geometry(geom)

            if min_area is None:
                # Нет ограничения или не найден ЗПР - пропускаем
                continue

            # Проверяем площадь
            if actual_area < min_area:
                problems.append(self._create_problem_dict(
                    feature, layer_name, actual_area, min_area,
                    geometry=geom
                ))

        return problems, checked_count

    def _parse_area(self, value: Any) -> Optional[int]:
        """Парсинг значения площади

        Args:
            value: Значение из поля Площадь_ОЗУ

        Returns:
            Площадь в кв.м или None
        """
        if value is None:
            return None

        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None

    def _create_problem_dict(
        self,
        feature: QgsFeature,
        layer_name: str,
        actual_area: int,
        min_area: int,
        geometry: Optional[QgsGeometry] = None,
        error_type: str = 'insufficient_area'
    ) -> Dict:
        """Создание словаря с информацией о проблемном контуре

        Args:
            feature: Объект контура
            layer_name: Имя слоя
            actual_area: Фактическая площадь
            min_area: Минимальная площадь
            geometry: Геометрия для подсветки на карте
            error_type: Тип ошибки

        Returns:
            Dict с информацией о проблеме
        """
        # Получаем ID
        feature_id = None
        if self.ID_FIELD in feature.fields().names():
            feature_id = feature[self.ID_FIELD]
        if feature_id is None:
            feature_id = feature.id()

        # Получаем Услов_КН
        uslov_kn = '-'
        if self.USLOV_KN_FIELD in feature.fields().names():
            val = feature[self.USLOV_KN_FIELD]
            if val:
                uslov_kn = str(val)

        # Получаем План_ВРИ
        plan_vri = '-'
        if self.PLAN_VRI_FIELD in feature.fields().names():
            val = feature[self.PLAN_VRI_FIELD]
            if val:
                plan_vri = str(val)
                # Сокращаем если слишком длинный
                if len(plan_vri) > 50:
                    plan_vri = plan_vri[:47] + '...'

        deficit = max(0, min_area - actual_area) if min_area and actual_area else 0

        return {
            'feature_id': feature_id,
            'uslov_kn': uslov_kn,
            'plan_vri': plan_vri,
            'actual_area': actual_area,
            'min_area': min_area,
            'deficit': deficit,
            'layer_name': layer_name,
            'geometry': geometry,
            'error_type': error_type,
        }
