# -*- coding: utf-8 -*-
"""
Msm_26_1 - Геометрические операции для нарезки ЗПР

Выполняет:
- intersection (пересечение ЗПР с ЗУ)
- difference (разность ЗПР минус ЗУ)
- union (объединение геометрий)
- определение необходимости дополнительной нарезки

Перенесено из Fsm_3_1_1_geometry_processor
"""

from typing import List, Optional, Tuple

from qgis.core import (
    QgsGeometry,
    QgsVectorLayer,
    QgsFeature,
)

from Daman_QGIS.utils import log_info, log_warning

# Точность координат (0.01м = 1 см)
COORDINATE_PRECISION = 0.01

# Минимальная площадь полигона (м2)
# Полигоны меньше этого порога считаются артефактами и удаляются при округлении.
# Синхронизировано с MIN_NGS_AREA в Msm_26_4_cutting_engine.py
MIN_VALID_AREA = 0.10  # м2 (квадрат ~31.6x31.6 см)


class Msm_26_1_GeometryProcessor:
    """Процессор геометрических операций для нарезки"""

    def __init__(self) -> None:
        """Инициализация процессора"""
        self.precision = COORDINATE_PRECISION

    def intersection(self, geom1: QgsGeometry, geom2: QgsGeometry) -> QgsGeometry:
        """Пересечение двух геометрий

        Args:
            geom1: Первая геометрия (ЗПР)
            geom2: Вторая геометрия (ЗУ)

        Returns:
            QgsGeometry: Результат пересечения (валидный)
        """
        if geom1.isEmpty() or geom2.isEmpty():
            return QgsGeometry()

        # Snap входных геометрий к сетке ДО операции
        # Это устраняет проблему несогласованных точек (разница в 1 см)
        g1 = geom1.snappedToGrid(self.precision, self.precision)
        g2 = geom2.snappedToGrid(self.precision, self.precision)

        # Валидация входных геометрий после snap
        g1 = g1.makeValid() if not g1.isGeosValid() else g1
        g2 = g2.makeValid() if not g2.isGeosValid() else g2

        if g1.isEmpty() or g2.isEmpty():
            return QgsGeometry()

        result = g1.intersection(g2)
        if result.isEmpty():
            return QgsGeometry()

        # Валидация и округление результата
        if not result.isGeosValid():
            result = result.makeValid()
            if result.isEmpty():
                return QgsGeometry()

        return self._snap_to_grid(result)

    def difference(self, geom1: QgsGeometry, geom2: QgsGeometry) -> QgsGeometry:
        """Разность двух геометрий

        Args:
            geom1: Исходная геометрия (ЗПР)
            geom2: Вычитаемая геометрия (union всех ЗУ)

        Returns:
            QgsGeometry: Результат разности (части ЗПР вне ЗУ), валидный
        """
        if geom1.isEmpty():
            return QgsGeometry()

        # Snap входных геометрий к сетке ДО операции
        # Это устраняет проблему несогласованных точек (разница в 1 см)
        g1 = geom1.snappedToGrid(self.precision, self.precision)

        # Валидация входной геометрии после snap
        g1 = g1.makeValid() if not g1.isGeosValid() else g1

        if g1.isEmpty():
            return QgsGeometry()

        if geom2.isEmpty():
            return self._snap_to_grid(g1)

        # Snap и валидация вычитаемой геометрии
        g2 = geom2.snappedToGrid(self.precision, self.precision)
        g2 = g2.makeValid() if not g2.isGeosValid() else g2

        if g2.isEmpty():
            return self._snap_to_grid(g1)

        result = g1.difference(g2)
        if result.isEmpty():
            return QgsGeometry()

        # Валидация и округление результата
        if not result.isGeosValid():
            result = result.makeValid()
            if result.isEmpty():
                return QgsGeometry()

        # Округление до сетки
        return self._snap_to_grid(result)

    def create_union(self, layer: QgsVectorLayer) -> QgsGeometry:
        """Создание union геометрии всех объектов слоя

        Args:
            layer: Векторный слой

        Returns:
            QgsGeometry: Объединённая геометрия всех объектов (валидная)
        """
        if not layer or layer.featureCount() == 0:
            return QgsGeometry()

        geometries = []
        for feature in layer.getFeatures():
            geom = feature.geometry()
            if geom and not geom.isEmpty():
                # Валидация геометрии
                if not geom.isGeosValid():
                    geom = geom.makeValid()
                    if geom.isEmpty():
                        continue
                geometries.append(geom)

        if not geometries:
            return QgsGeometry()

        # Объединение всех геометрий
        result = QgsGeometry.unaryUnion(geometries)

        # Округляем координаты до стандартной точности после объединения
        result = result.snappedToGrid(self.precision, self.precision)

        # Валидация результата union
        if not result.isEmpty() and not result.isGeosValid():
            result = result.makeValid()

        log_info(f"Msm_26_1: Создан union из {len(geometries)} геометрий")
        return result

    def need_additional_cut(self, fragment: QgsGeometry, boundary: QgsGeometry) -> bool:
        """Определение необходимости дополнительной нарезки

        Не нужно резать если:
        - Фрагмент не пересекается с границей
        - Фрагмент полностью внутри границы

        Нужно резать если:
        - Частичное пересечение (часть внутри, часть снаружи)

        Args:
            fragment: Геометрия фрагмента
            boundary: Геометрия границы (overlay)

        Returns:
            bool: True если нужно резать
        """
        if fragment.isEmpty() or boundary.isEmpty():
            return False

        intersection = fragment.intersection(boundary)

        # Не пересекается - не режем
        if intersection.isEmpty():
            return False

        # Полностью внутри - не режем, только помечаем
        # Проверка через сравнение площадей с погрешностью
        fragment_area = fragment.area()
        intersection_area = intersection.area()

        # Если площадь пересечения равна площади фрагмента (с погрешностью) - полностью внутри
        if fragment_area > 0 and abs(fragment_area - intersection_area) / fragment_area < 0.001:
            return False

        # Частичное пересечение - режем
        return True

    def cut_by_boundaries(
        self,
        features: List[Tuple[QgsGeometry, dict]],
        boundary_layer: QgsVectorLayer,
        boundary_field: str
    ) -> List[Tuple[QgsGeometry, dict, Optional[str]]]:
        """Нарезка списка геометрий по границам слоя

        Args:
            features: Список кортежей (геометрия, атрибуты)
            boundary_layer: Слой границ
            boundary_field: Имя поля для атрибута наложения

        Returns:
            List: Список кортежей (геометрия, атрибуты, значение_наложения)
        """
        if not boundary_layer or boundary_layer.featureCount() == 0:
            # Нет границ - возвращаем как есть с None для overlay
            return [(geom, attrs, None) for geom, attrs in features]

        boundary_union = self.create_union(boundary_layer)
        if boundary_union.isEmpty():
            return [(geom, attrs, None) for geom, attrs in features]

        result = []

        for geom, attrs in features:
            if geom.isEmpty():
                continue

            if not self.need_additional_cut(geom, boundary_union):
                # Не режем - определяем находится ли внутри
                intersection = geom.intersection(boundary_union)
                if not intersection.isEmpty():
                    # Внутри границы - помечаем
                    # TODO: получить название из слоя
                    result.append((geom, attrs, "TODO: маппинг"))
                else:
                    # Вне границы
                    result.append((geom, attrs, None))
            else:
                # Режем на две части
                inside = self.intersection(geom, boundary_union)
                outside = self.difference(geom, boundary_union)

                if not inside.isEmpty():
                    # TODO: получить название из слоя
                    result.append((inside, attrs.copy(), "TODO: маппинг"))

                if not outside.isEmpty():
                    result.append((outside, attrs.copy(), None))

        log_info(f"Msm_26_1: Нарезка по {boundary_field}: "
                f"было {len(features)}, стало {len(result)} объектов")
        return result

    def extract_polygons(
        self,
        geom: QgsGeometry,
        min_area: float = 0.0001
    ) -> List[QgsGeometry]:
        """Извлечение отдельных полигонов из геометрии

        Нормализация Multi* типов в список отдельных геометрий.
        Фильтрует мелкие артефакты после геометрических операций.

        Args:
            geom: Исходная геометрия (может быть Multi*)
            min_area: Минимальная площадь полигона (м2), по умолчанию 0.0001

        Returns:
            List[QgsGeometry]: Список отдельных полигонов (валидных)
        """
        if geom.isEmpty():
            return []

        result = []
        filtered_count = 0
        invalid_count = 0

        # Определяем тип геометрии
        geom_type = geom.type()
        wkb_type = geom.wkbType()

        # Проверка на GeometryCollection (может возникнуть после makeValid/snap)
        # wkbType 7 = GeometryCollection
        if wkb_type == 7:
            # Извлекаем все части из GeometryCollection
            for i in range(geom.constGet().numGeometries()):
                part = QgsGeometry(geom.constGet().geometryN(i).clone())
                if part.type() == 2:  # Polygon
                    area = part.area()
                    if area >= min_area:
                        if not part.isGeosValid():
                            part = part.makeValid()
                        if not part.isEmpty():
                            part = self._snap_to_grid(part)
                            if not part.isEmpty():
                                result.append(part)
                            else:
                                filtered_count += 1
                    else:
                        filtered_count += 1
            return result

        # Для полигонов
        if geom_type == 2:  # Polygon
            if geom.isMultipart():
                # MultiPolygon -> список полигонов
                multi = geom.asMultiPolygon()
                total_parts = len(multi)
                total_area = geom.area()

                # Fallback: если asMultiPolygon() вернул 0 частей при площади > 0
                if total_parts == 0 and total_area > 0:
                    try:
                        single_poly = geom.asPolygon()
                        if single_poly:
                            single_geom = QgsGeometry.fromPolygonXY(single_poly)
                            if not single_geom.isEmpty() and single_geom.area() >= min_area:
                                if not single_geom.isGeosValid():
                                    single_geom = single_geom.makeValid()
                                if not single_geom.isEmpty():
                                    result.append(single_geom)
                                    return result
                    except Exception:
                        pass

                for polygon in multi:
                    single_geom = QgsGeometry.fromPolygonXY(polygon)
                    if single_geom.isEmpty():
                        invalid_count += 1
                        continue
                    area = single_geom.area()
                    if area < min_area:
                        filtered_count += 1
                        continue
                    if not single_geom.isGeosValid():
                        single_geom = single_geom.makeValid()
                        if single_geom.isEmpty():
                            invalid_count += 1
                            continue
                    single_geom = self._snap_to_grid(single_geom)
                    if single_geom.isEmpty():
                        filtered_count += 1
                        continue
                    result.append(single_geom)
            else:
                # SinglePolygon
                area = geom.area()
                if area >= min_area:
                    valid_geom = geom
                    if not geom.isGeosValid():
                        valid_geom = geom.makeValid()
                    if not valid_geom.isEmpty():
                        valid_geom = self._snap_to_grid(valid_geom)
                        if not valid_geom.isEmpty():
                            result.append(valid_geom)
                        else:
                            filtered_count += 1
                else:
                    filtered_count += 1

        return result

    def _snap_to_grid(self, geom: QgsGeometry) -> QgsGeometry:
        """Округление координат геометрии до заданной точности

        Args:
            geom: Исходная геометрия

        Returns:
            QgsGeometry: Геометрия с округлёнными координатами
        """
        if geom.isEmpty():
            return geom

        area_before = geom.area()
        result = geom.snappedToGrid(self.precision, self.precision)

        # Геометрия схлопнулась в пустую
        if result.isEmpty() and area_before > 0:
            if area_before < MIN_VALID_AREA:
                return QgsGeometry()  # Артефакт - удаляем
            # Значимая геометрия - возвращаем без snap
            log_warning(f"Msm_26_1: snap схлопнул значимую геометрию ({area_before:.2f} м2)")
            return geom

        # Полигон деградировал в линию/точку
        if not result.isEmpty() and geom.type() == 2 and result.type() != 2:
            if area_before < MIN_VALID_AREA:
                return QgsGeometry()  # Артефакт - удаляем
            log_warning(f"Msm_26_1: snap деградировал полигон ({area_before:.2f} м2)")
            return geom

        # Валидация результата
        if not result.isGeosValid():
            type_before = result.type()
            result = result.makeValid()
            type_after = result.type()

            # makeValid деградировал тип
            if geom.type() == 2 and type_after != 2:
                if area_before < MIN_VALID_AREA:
                    return QgsGeometry()  # Артефакт - удаляем
                log_warning(f"Msm_26_1: makeValid деградировал полигон ({area_before:.2f} м2)")
                return geom

        return result

    def validate_and_fix(self, geom: QgsGeometry) -> QgsGeometry:
        """Валидация и исправление геометрии

        Args:
            geom: Исходная геометрия

        Returns:
            QgsGeometry: Валидная геометрия
        """
        if geom.isEmpty():
            return geom

        if not geom.isGeosValid():
            fixed = geom.makeValid()
            if fixed.isEmpty():
                log_warning("Msm_26_1: Не удалось исправить невалидную геометрию")
                return QgsGeometry()
            return fixed

        return geom
