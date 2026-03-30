# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_6 - Тестирование M_6 CoordinatePrecision

Тестирует:
- _math_round() граничные значения
- round_coordinate(), round_coordinates(), round_point()
- round_point_tuple()
- is_ring_closed()
- check_layer_precision()
- validate_and_round_layer()
"""

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY, QgsField, QgsFields
)
from qgis.PyQt.QtCore import QMetaType


class TestCoordinatePrecision:
    """Тесты M_6 CoordinatePrecision"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger

    def run_all_tests(self):
        self.logger.section("ТЕСТ M_6: CoordinatePrecision")
        try:
            # _math_round
            self.test_01_math_round_half_up_positive()
            self.test_02_math_round_half_up_negative()
            self.test_03_math_round_zero()
            self.test_04_math_round_large_value()
            self.test_05_math_round_boundary_015()
            self.test_06_math_round_floating_point_edge()

            # round_coordinate
            self.test_07_round_coordinate_default_precision()
            self.test_08_round_coordinate_custom_precision()

            # round_coordinates
            self.test_09_round_coordinates_pair()

            # round_point
            self.test_10_round_point_qgspointxy()

            # round_point_tuple
            self.test_11_round_point_tuple()

            # is_ring_closed
            self.test_12_is_ring_closed_exact()
            self.test_13_is_ring_open()
            self.test_14_is_ring_closed_within_tolerance()
            self.test_15_is_ring_closed_empty()
            self.test_16_is_ring_closed_optimized()

            # check_layer_precision
            self.test_17_check_layer_precision_clean()
            self.test_18_check_layer_precision_imprecise()
            self.test_19_check_layer_precision_none()

            # validate_and_round_layer
            self.test_20_validate_and_round_auto()
            self.test_21_validate_already_precise()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов M_6: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
        self.logger.summary()

    # ========================================================================
    # _math_round
    # ========================================================================

    def test_01_math_round_half_up_positive(self):
        """ТЕСТ 1: _math_round(0.005, 2) -> 0.01 (round half away from zero)"""
        self.logger.section("1. _math_round: 0.005 -> 0.01")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import _math_round

            result = _math_round(0.005, 2)
            self.logger.check(
                result == 0.01,
                "_math_round(0.005, 2) = 0.01",
                f"_math_round(0.005, 2) = {result} (ожидалось 0.01)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_02_math_round_half_up_negative(self):
        """ТЕСТ 2: _math_round(-123.455, 2) -> -123.46"""
        self.logger.section("2. _math_round: отрицательное значение")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import _math_round

            result = _math_round(-123.455, 2)
            self.logger.check(
                result == -123.46,
                "_math_round(-123.455, 2) = -123.46",
                f"_math_round(-123.455, 2) = {result} (ожидалось -123.46)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_03_math_round_zero(self):
        """ТЕСТ 3: _math_round(0.0, 2) -> 0.0"""
        self.logger.section("3. _math_round: ноль")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import _math_round

            result = _math_round(0.0, 2)
            self.logger.check(
                result == 0.0,
                "_math_round(0.0, 2) = 0.0",
                f"_math_round(0.0, 2) = {result} (ожидалось 0.0)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_04_math_round_large_value(self):
        """ТЕСТ 4: _math_round(99999.999, 2) -> 100000.0"""
        self.logger.section("4. _math_round: большое значение")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import _math_round

            result = _math_round(99999.999, 2)
            self.logger.check(
                result == 100000.0,
                "_math_round(99999.999, 2) = 100000.0",
                f"_math_round(99999.999, 2) = {result} (ожидалось 100000.0)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_05_math_round_boundary_015(self):
        """ТЕСТ 5: _math_round(0.015, 2) -> 0.02"""
        self.logger.section("5. _math_round: 0.015 -> 0.02")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import _math_round

            result = _math_round(0.015, 2)
            self.logger.check(
                result == 0.02,
                "_math_round(0.015, 2) = 0.02",
                f"_math_round(0.015, 2) = {result} (ожидалось 0.02)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_06_math_round_floating_point_edge(self):
        """ТЕСТ 6: Floating-point edge cases"""
        self.logger.section("6. _math_round: floating-point edge cases")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import _math_round

            # 2.675 в float = 2.6749999... — проверяем что math_round корректно обрабатывает
            result_2675 = _math_round(2.675, 2)
            # Python round(2.675, 2) = 2.67 (банковское), но _math_round должен дать 2.68
            # Однако из-за IEEE 754 фактическое значение 2.675 = 2.6749999...
            # Поэтому _math_round даст 2.67 — это корректное поведение
            self.logger.info(f"_math_round(2.675, 2) = {result_2675}")
            self.logger.check(
                result_2675 == 2.67 or result_2675 == 2.68,
                f"_math_round(2.675, 2) = {result_2675} (IEEE 754 граничный случай)",
                f"_math_round(2.675, 2) = {result_2675} (неожиданное значение)"
            )

            # Целое число — без изменений
            result_int = _math_round(5.0, 2)
            self.logger.check(
                result_int == 5.0,
                "_math_round(5.0, 2) = 5.0",
                f"_math_round(5.0, 2) = {result_int} (ожидалось 5.0)"
            )

            # Отрицательный ноль
            result_neg_zero = _math_round(-0.0, 2)
            self.logger.check(
                result_neg_zero == 0.0,
                "_math_round(-0.0, 2) = 0.0",
                f"_math_round(-0.0, 2) = {result_neg_zero} (ожидалось 0.0)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # ========================================================================
    # round_coordinate
    # ========================================================================

    def test_07_round_coordinate_default_precision(self):
        """ТЕСТ 7: round_coordinate делегирует в _math_round с PRECISION_DECIMALS=2"""
        self.logger.section("7. round_coordinate: default precision")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import (
                CoordinatePrecisionManager as CPM
            )

            result = CPM.round_coordinate(123.456789)
            self.logger.check(
                result == 123.46,
                "round_coordinate(123.456789) = 123.46",
                f"round_coordinate(123.456789) = {result} (ожидалось 123.46)"
            )

            # Граничный случай .005
            result_boundary = CPM.round_coordinate(123.005)
            self.logger.check(
                result_boundary == 123.01,
                "round_coordinate(123.005) = 123.01 (math round, не банковское)",
                f"round_coordinate(123.005) = {result_boundary} (ожидалось 123.01)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_08_round_coordinate_custom_precision(self):
        """ТЕСТ 8: round_coordinate с кастомной точностью"""
        self.logger.section("8. round_coordinate: custom precision")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import (
                CoordinatePrecisionManager as CPM
            )

            result = CPM.round_coordinate(123.456789, precision=4)
            self.logger.check(
                result == 123.4568,
                "round_coordinate(123.456789, precision=4) = 123.4568",
                f"round_coordinate(123.456789, precision=4) = {result} (ожидалось 123.4568)"
            )

            result_0 = CPM.round_coordinate(123.5, precision=0)
            self.logger.check(
                result_0 == 124.0,
                "round_coordinate(123.5, precision=0) = 124.0",
                f"round_coordinate(123.5, precision=0) = {result_0} (ожидалось 124.0)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # ========================================================================
    # round_coordinates
    # ========================================================================

    def test_09_round_coordinates_pair(self):
        """ТЕСТ 9: round_coordinates округляет оба значения"""
        self.logger.section("9. round_coordinates: пара координат")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import (
                CoordinatePrecisionManager as CPM
            )

            x, y = CPM.round_coordinates(123.456, 456.789)
            self.logger.check(
                x == 123.46 and y == 456.79,
                f"round_coordinates(123.456, 456.789) = ({x}, {y})",
                f"round_coordinates(123.456, 456.789) = ({x}, {y}) (ожидалось 123.46, 456.79)"
            )

            # С кастомной точностью
            x2, y2 = CPM.round_coordinates(1.1111, 2.2222, precision=3)
            self.logger.check(
                x2 == 1.111 and y2 == 2.222,
                f"round_coordinates(1.1111, 2.2222, precision=3) = ({x2}, {y2})",
                f"round_coordinates(..., precision=3) = ({x2}, {y2}) (ожидалось 1.111, 2.222)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # ========================================================================
    # round_point
    # ========================================================================

    def test_10_round_point_qgspointxy(self):
        """ТЕСТ 10: round_point возвращает QgsPointXY с округленными координатами"""
        self.logger.section("10. round_point: QgsPointXY")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import (
                CoordinatePrecisionManager as CPM
            )

            p = QgsPointXY(123.456789, 456.789123)
            rounded = CPM.round_point(p)

            self.logger.check(
                isinstance(rounded, QgsPointXY),
                "round_point возвращает QgsPointXY",
                f"round_point вернул {type(rounded)}"
            )

            self.logger.check(
                rounded.x() == 123.46 and rounded.y() == 456.79,
                f"round_point: ({rounded.x()}, {rounded.y()}) = (123.46, 456.79)",
                f"round_point: ({rounded.x()}, {rounded.y()}) (ожидалось 123.46, 456.79)"
            )

            # Исходная точка не изменена
            self.logger.check(
                p.x() == 123.456789,
                "Исходная точка не изменена (иммутабельность)",
                f"Исходная точка изменилась: {p.x()}"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # ========================================================================
    # round_point_tuple
    # ========================================================================

    def test_11_round_point_tuple(self):
        """ТЕСТ 11: round_point_tuple возвращает tuple для использования как dict key"""
        self.logger.section("11. round_point_tuple")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import (
                CoordinatePrecisionManager as CPM
            )

            p = QgsPointXY(123.456789, 456.789123)
            result = CPM.round_point_tuple(p)

            self.logger.check(
                isinstance(result, tuple) and len(result) == 2,
                f"round_point_tuple возвращает tuple длины 2",
                f"round_point_tuple вернул {type(result)}"
            )

            self.logger.check(
                result == (123.46, 456.79),
                f"round_point_tuple = {result}",
                f"round_point_tuple = {result} (ожидалось (123.46, 456.79))"
            )

            # Можно использовать как ключ dict
            d = {result: True}
            self.logger.check(
                d.get((123.46, 456.79)) is True,
                "tuple корректно работает как dict key",
                "tuple не работает как dict key"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # ========================================================================
    # is_ring_closed
    # ========================================================================

    def test_12_is_ring_closed_exact(self):
        """ТЕСТ 12: is_ring_closed — замкнутый контур (совпадение первой и последней точки)"""
        self.logger.section("12. is_ring_closed: замкнутый контур")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import (
                CoordinatePrecisionManager as CPM
            )

            ring = [
                QgsPointXY(0.0, 0.0),
                QgsPointXY(10.0, 0.0),
                QgsPointXY(10.0, 10.0),
                QgsPointXY(0.0, 0.0)
            ]
            result = CPM.is_ring_closed(ring)
            self.logger.check(
                result is True,
                "Замкнутый контур -> True",
                f"Замкнутый контур -> {result} (ожидалось True)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_13_is_ring_open(self):
        """ТЕСТ 13: is_ring_closed — открытый контур"""
        self.logger.section("13. is_ring_closed: открытый контур")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import (
                CoordinatePrecisionManager as CPM
            )

            ring = [
                QgsPointXY(0.0, 0.0),
                QgsPointXY(10.0, 0.0),
                QgsPointXY(10.0, 10.0),
                QgsPointXY(5.0, 5.0)
            ]
            result = CPM.is_ring_closed(ring)
            self.logger.check(
                result is False,
                "Открытый контур -> False",
                f"Открытый контур -> {result} (ожидалось False)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_14_is_ring_closed_within_tolerance(self):
        """ТЕСТ 14: is_ring_closed — замкнут в пределах tolerance"""
        self.logger.section("14. is_ring_closed: в пределах tolerance")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import (
                CoordinatePrecisionManager as CPM
            )
            from Daman_QGIS.constants import CLOSURE_TOLERANCE

            # Разница 0.005 м — меньше CLOSURE_TOLERANCE (0.01 м)
            ring_within = [
                QgsPointXY(0.0, 0.0),
                QgsPointXY(10.0, 0.0),
                QgsPointXY(10.0, 10.0),
                QgsPointXY(0.005, 0.0)
            ]
            result_within = CPM.is_ring_closed(ring_within)
            self.logger.check(
                result_within is True,
                f"Разница 0.005 м < tolerance {CLOSURE_TOLERANCE} -> True",
                f"Разница 0.005 м -> {result_within} (ожидалось True)"
            )

            # Разница 0.02 м — больше CLOSURE_TOLERANCE
            ring_outside = [
                QgsPointXY(0.0, 0.0),
                QgsPointXY(10.0, 0.0),
                QgsPointXY(10.0, 10.0),
                QgsPointXY(0.02, 0.0)
            ]
            result_outside = CPM.is_ring_closed(ring_outside)
            self.logger.check(
                result_outside is False,
                f"Разница 0.02 м > tolerance {CLOSURE_TOLERANCE} -> False",
                f"Разница 0.02 м -> {result_outside} (ожидалось False)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_15_is_ring_closed_empty(self):
        """ТЕСТ 15: is_ring_closed — пустой и короткий список"""
        self.logger.section("15. is_ring_closed: пустой/короткий список")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import (
                CoordinatePrecisionManager as CPM
            )

            result_empty = CPM.is_ring_closed([])
            self.logger.check(
                result_empty is False,
                "Пустой список -> False",
                f"Пустой список -> {result_empty}"
            )

            result_one = CPM.is_ring_closed([QgsPointXY(0.0, 0.0)])
            self.logger.check(
                result_one is False,
                "Один элемент -> False",
                f"Один элемент -> {result_one}"
            )

            result_none = CPM.is_ring_closed(None)
            self.logger.check(
                result_none is False,
                "None -> False",
                f"None -> {result_none}"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_16_is_ring_closed_optimized(self):
        """ТЕСТ 16: is_ring_closed с use_optimization=True"""
        self.logger.section("16. is_ring_closed: optimized mode")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import (
                CoordinatePrecisionManager as CPM
            )

            ring_closed = [
                QgsPointXY(0.0, 0.0),
                QgsPointXY(10.0, 0.0),
                QgsPointXY(10.0, 10.0),
                QgsPointXY(0.0, 0.0)
            ]
            result = CPM.is_ring_closed(ring_closed, use_optimization=True)
            self.logger.check(
                result is True,
                "Optimized: замкнутый контур -> True",
                f"Optimized: замкнутый контур -> {result}"
            )

            ring_open = [
                QgsPointXY(0.0, 0.0),
                QgsPointXY(10.0, 0.0),
                QgsPointXY(10.0, 10.0),
                QgsPointXY(5.0, 5.0)
            ]
            result_open = CPM.is_ring_closed(ring_open, use_optimization=True)
            self.logger.check(
                result_open is False,
                "Optimized: открытый контур -> False",
                f"Optimized: открытый контур -> {result_open}"
            )

            # Результат optimized и standard должны совпадать
            ring_tolerance = [
                QgsPointXY(0.0, 0.0),
                QgsPointXY(10.0, 0.0),
                QgsPointXY(10.0, 10.0),
                QgsPointXY(0.005, 0.0)
            ]
            result_std = CPM.is_ring_closed(ring_tolerance, use_optimization=False)
            result_opt = CPM.is_ring_closed(ring_tolerance, use_optimization=True)
            self.logger.check(
                result_std == result_opt,
                f"Standard ({result_std}) == Optimized ({result_opt}) для tolerance case",
                f"Standard ({result_std}) != Optimized ({result_opt})"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # ========================================================================
    # check_layer_precision
    # ========================================================================

    def _create_test_layer(self, coords_list):
        """
        Создать memory layer с точками для тестирования.

        Args:
            coords_list: список tuple (x, y) для создания точечных объектов
        Returns:
            QgsVectorLayer
        """
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "test_precision", "memory")
        pr = layer.dataProvider()

        features = []
        for x, y in coords_list:
            f = QgsFeature()
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
            features.append(f)

        pr.addFeatures(features)
        layer.updateExtents()
        return layer

    def _create_polygon_layer(self, rings_list):
        """
        Создать memory layer с полигонами для тестирования.

        Args:
            rings_list: список списков QgsPointXY (каждый — кольцо полигона)
        Returns:
            QgsVectorLayer
        """
        layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "test_polygon", "memory")
        pr = layer.dataProvider()

        features = []
        for ring in rings_list:
            f = QgsFeature()
            f.setGeometry(QgsGeometry.fromPolygonXY([ring]))
            features.append(f)

        pr.addFeatures(features)
        layer.updateExtents()
        return layer

    def test_17_check_layer_precision_clean(self):
        """ТЕСТ 17: check_layer_precision — слой с точными координатами"""
        self.logger.section("17. check_layer_precision: точные координаты")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import (
                CoordinatePrecisionManager as CPM
            )

            # Координаты уже округлены до 0.01
            layer = self._create_test_layer([
                (100.01, 200.02),
                (300.10, 400.20),
            ])

            needs_rounding, total, imprecise = CPM.check_layer_precision(layer)
            self.logger.check(
                needs_rounding is False,
                f"Точные координаты: needs_rounding=False, total={total}, imprecise={imprecise}",
                f"Точные координаты: needs_rounding={needs_rounding}, imprecise={imprecise}"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_18_check_layer_precision_imprecise(self):
        """ТЕСТ 18: check_layer_precision — слой с избыточной точностью"""
        self.logger.section("18. check_layer_precision: избыточная точность")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import (
                CoordinatePrecisionManager as CPM
            )

            # Координаты с избыточной точностью (>2 знаков)
            layer = self._create_test_layer([
                (100.123456, 200.654321),
                (300.10, 400.20),
            ])

            needs_rounding, total, imprecise = CPM.check_layer_precision(layer)
            self.logger.check(
                needs_rounding is True,
                f"Избыточная точность: needs_rounding=True",
                f"Избыточная точность: needs_rounding={needs_rounding}"
            )
            self.logger.check(
                total == 2,
                f"Всего вершин: {total} = 2",
                f"Всего вершин: {total} (ожидалось 2)"
            )
            self.logger.check(
                imprecise >= 1,
                f"Вершин с избыточной точностью: {imprecise} >= 1",
                f"Вершин с избыточной точностью: {imprecise} (ожидалось >= 1)"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_19_check_layer_precision_none(self):
        """ТЕСТ 19: check_layer_precision — None и невалидный слой"""
        self.logger.section("19. check_layer_precision: None/невалидный")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import (
                CoordinatePrecisionManager as CPM
            )

            needs, total, imprecise = CPM.check_layer_precision(None)
            self.logger.check(
                needs is False and total == 0 and imprecise == 0,
                "None layer -> (False, 0, 0)",
                f"None layer -> ({needs}, {total}, {imprecise})"
            )

            # Не QgsVectorLayer
            needs2, total2, imprecise2 = CPM.check_layer_precision("not_a_layer")
            self.logger.check(
                needs2 is False and total2 == 0 and imprecise2 == 0,
                "Строка вместо слоя -> (False, 0, 0)",
                f"Строка вместо слоя -> ({needs2}, {total2}, {imprecise2})"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    # ========================================================================
    # validate_and_round_layer
    # ========================================================================

    def test_20_validate_and_round_auto(self):
        """ТЕСТ 20: validate_and_round_layer с auto_round=True (end-to-end)"""
        self.logger.section("20. validate_and_round_layer: auto_round")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import (
                CoordinatePrecisionManager as CPM
            )

            # Создаем полигон с избыточной точностью
            ring = [
                QgsPointXY(100.123456, 200.654321),
                QgsPointXY(100.123456, 210.654321),
                QgsPointXY(110.123456, 210.654321),
                QgsPointXY(110.123456, 200.654321),
                QgsPointXY(100.123456, 200.654321),
            ]
            layer = self._create_polygon_layer([ring])

            # Проверяем что требуется округление
            needs_before, _, _ = CPM.check_layer_precision(layer)
            self.logger.check(
                needs_before is True,
                "До округления: needs_rounding=True",
                f"До округления: needs_rounding={needs_before}"
            )

            # Выполняем validate_and_round с auto_round
            result = CPM.validate_and_round_layer(layer, auto_round=True)
            self.logger.check(
                result is True,
                "validate_and_round_layer(auto_round=True) = True",
                f"validate_and_round_layer(auto_round=True) = {result}"
            )

            # Проверяем что после округления точность в норме
            needs_after, total_after, imprecise_after = CPM.check_layer_precision(layer)
            self.logger.check(
                needs_after is False,
                f"После округления: needs_rounding=False (imprecise={imprecise_after})",
                f"После округления: needs_rounding={needs_after}, imprecise={imprecise_after}"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")

    def test_21_validate_already_precise(self):
        """ТЕСТ 21: validate_and_round_layer — координаты уже точные"""
        self.logger.section("21. validate_and_round_layer: уже точный слой")
        try:
            from Daman_QGIS.managers.geometry.M_6_coordinate_precision import (
                CoordinatePrecisionManager as CPM
            )

            # Координаты уже округлены
            layer = self._create_test_layer([
                (100.01, 200.02),
                (300.10, 400.20),
            ])

            result = CPM.validate_and_round_layer(layer, auto_round=True)
            self.logger.check(
                result is True,
                "Уже точный слой -> True (без изменений)",
                f"Уже точный слой -> {result}"
            )

            # None
            result_none = CPM.validate_and_round_layer(None)
            self.logger.check(
                result_none is False,
                "None layer -> False",
                f"None layer -> {result_none}"
            )
        except Exception as e:
            self.logger.error(f"Ошибка: {e}")


def run_tests(iface, logger):
    """Точка входа для запуска тестов"""
    test = TestCoordinatePrecision(iface, logger)
    test.run_all_tests()
    return test
