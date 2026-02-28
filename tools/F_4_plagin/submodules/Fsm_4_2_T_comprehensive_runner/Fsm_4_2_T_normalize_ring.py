# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_normalize_ring - Тесты normalize_ring() из M_20

Проверяет:
- Корректность CW/CCW ориентации (внешние/внутренние контуры)
- Ротацию к СЗ точке
- Отсутствие замыкающей точки в результате
- Граничные случаи (< 3 точек, пустой список)
"""


class TestNormalizeRing:
    """Тесты для PointNumberingManager.normalize_ring()"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.pnm = None

    def run_all_tests(self):
        self.logger.section("ТЕСТ M_20: normalize_ring()")

        try:
            self._init_manager()
            self.test_01_exterior_cw_input()
            self.test_02_exterior_ccw_input()
            self.test_03_interior_ccw_input()
            self.test_04_interior_cw_input()
            self.test_05_nw_rotation()
            self.test_06_closing_point_not_added()
            self.test_07_edge_cases()
            self.test_08_is_clockwise_public()
            self.test_09_find_nw_point_index_public()
        except Exception as e:
            self.logger.error(f"Критическая ошибка: {e}")

        self.logger.summary()

    def _init_manager(self):
        """Инициализация PointNumberingManager"""
        from Daman_QGIS.managers import registry
        self.pnm = registry.get('M_20')
        self.logger.success("PointNumberingManager инициализирован")

    def _compute_signed_area_2(self, points):
        """Вычисление удвоенной знаковой площади (Shoelace formula)"""
        n = len(points)
        area = 0.0
        for i in range(n):
            j = (i + 1) % n
            area += points[i][0] * points[j][1]
            area -= points[j][0] * points[i][1]
        return area

    def test_01_exterior_cw_input(self):
        """Внешний контур: CW на входе -> остается CW"""
        self.logger.section("1. Внешний контур: CW вход -> CW выход")

        # Квадрат CW в мат. СК (signed_area < 0)
        cw_square = [(0, 0), (0, 10), (10, 10), (10, 0)]
        sa = self._compute_signed_area_2(cw_square)
        self.logger.info(f"Входной signed_area_2 = {sa} (CW = отрицательное)")

        result = self.pnm.normalize_ring(cw_square, is_exterior=True)
        sa_result = self._compute_signed_area_2(result)

        if sa_result < 0:
            self.logger.success(f"Результат CW: signed_area_2 = {sa_result}")
        else:
            self.logger.error(f"Ожидалось CW (< 0), получено signed_area_2 = {sa_result}")

    def test_02_exterior_ccw_input(self):
        """Внешний контур: CCW на входе -> инвертируется в CW"""
        self.logger.section("2. Внешний контур: CCW вход -> CW выход")

        # Квадрат CCW в мат. СК (signed_area > 0)
        ccw_square = [(0, 0), (10, 0), (10, 10), (0, 10)]
        sa = self._compute_signed_area_2(ccw_square)
        self.logger.info(f"Входной signed_area_2 = {sa} (CCW = положительное)")

        result = self.pnm.normalize_ring(ccw_square, is_exterior=True)
        sa_result = self._compute_signed_area_2(result)

        if sa_result < 0:
            self.logger.success(f"Результат CW: signed_area_2 = {sa_result}")
        else:
            self.logger.error(f"Ожидалось CW (< 0), получено signed_area_2 = {sa_result}")

    def test_03_interior_ccw_input(self):
        """Внутренний контур: CCW на входе -> остается CCW"""
        self.logger.section("3. Внутренний контур: CCW вход -> CCW выход")

        # Квадрат CCW (signed_area > 0)
        ccw_square = [(0, 0), (10, 0), (10, 10), (0, 10)]
        sa = self._compute_signed_area_2(ccw_square)
        self.logger.info(f"Входной signed_area_2 = {sa} (CCW = положительное)")

        result = self.pnm.normalize_ring(ccw_square, is_exterior=False)
        sa_result = self._compute_signed_area_2(result)

        if sa_result > 0:
            self.logger.success(f"Результат CCW: signed_area_2 = {sa_result}")
        else:
            self.logger.error(f"Ожидалось CCW (> 0), получено signed_area_2 = {sa_result}")

    def test_04_interior_cw_input(self):
        """Внутренний контур: CW на входе -> инвертируется в CCW"""
        self.logger.section("4. Внутренний контур: CW вход -> CCW выход")

        # Квадрат CW (signed_area < 0)
        cw_square = [(0, 0), (0, 10), (10, 10), (10, 0)]
        sa = self._compute_signed_area_2(cw_square)
        self.logger.info(f"Входной signed_area_2 = {sa} (CW = отрицательное)")

        result = self.pnm.normalize_ring(cw_square, is_exterior=False)
        sa_result = self._compute_signed_area_2(result)

        if sa_result > 0:
            self.logger.success(f"Результат CCW: signed_area_2 = {sa_result}")
        else:
            self.logger.error(f"Ожидалось CCW (> 0), получено signed_area_2 = {sa_result}")

    def test_05_nw_rotation(self):
        """Начальная точка = ближайшая к СЗ углу MBR"""
        self.logger.section("5. Ротация к СЗ точке")

        # Треугольник: СЗ точка = (0, 20) (min_x=0, max_y=20)
        # CW порядок чтобы не инвертировался для exterior
        triangle = [(10, 0), (0, 20), (20, 10)]
        sa = self._compute_signed_area_2(triangle)
        self.logger.info(f"Входной signed_area_2 = {sa}")

        result = self.pnm.normalize_ring(triangle, is_exterior=True)

        # Первая точка должна быть (0, 20) - СЗ угол MBR: min_x=0, max_y=20
        expected_first = (0, 20)
        if result[0] == expected_first:
            self.logger.success(f"Первая точка = {result[0]} (СЗ точка)")
        else:
            self.logger.error(f"Ожидалось {expected_first}, получено {result[0]}")

    def test_06_closing_point_not_added(self):
        """normalize_ring() НЕ добавляет замыкающую точку"""
        self.logger.section("6. Замыкающая точка НЕ добавляется")

        points = [(0, 0), (10, 0), (10, 10), (0, 10)]
        result = self.pnm.normalize_ring(points, is_exterior=True)

        if result[0] != result[-1]:
            self.logger.success(f"Первая ({result[0]}) != Последняя ({result[-1]}): замыкания нет")
        else:
            self.logger.error(f"Первая == Последняя ({result[0]}): обнаружена замыкающая точка!")

        if len(result) == len(points):
            self.logger.success(f"Длина сохранена: {len(result)} == {len(points)}")
        else:
            self.logger.error(f"Длина изменилась: {len(result)} != {len(points)}")

    def test_07_edge_cases(self):
        """Граничные случаи: пустой список, < 3 точек"""
        self.logger.section("7. Граничные случаи")

        # Пустой список
        result = self.pnm.normalize_ring([], is_exterior=True)
        if result == []:
            self.logger.success("Пустой список -> пустой список")
        else:
            self.logger.error(f"Пустой список -> {result}")

        # 1 точка
        result = self.pnm.normalize_ring([(5, 5)], is_exterior=True)
        if result == [(5, 5)]:
            self.logger.success("1 точка -> без изменений")
        else:
            self.logger.error(f"1 точка -> {result}")

        # 2 точки
        result = self.pnm.normalize_ring([(0, 0), (10, 10)], is_exterior=True)
        if result == [(0, 0), (10, 10)]:
            self.logger.success("2 точки -> без изменений")
        else:
            self.logger.error(f"2 точки -> {result}")

    def test_08_is_clockwise_public(self):
        """is_clockwise() доступен как публичный метод"""
        self.logger.section("8. is_clockwise() - публичный API")

        from Daman_QGIS.managers.geometry import PointNumberingManager

        # CW квадрат (signed_area < 0)
        cw = [(0, 0), (0, 10), (10, 10), (10, 0)]
        result = PointNumberingManager.is_clockwise(cw)
        if result is True:
            self.logger.success("CW квадрат: is_clockwise() = True")
        else:
            self.logger.error(f"CW квадрат: ожидалось True, получено {result}")

        # CCW квадрат (signed_area > 0)
        ccw = [(0, 0), (10, 0), (10, 10), (0, 10)]
        result = PointNumberingManager.is_clockwise(ccw)
        if result is False:
            self.logger.success("CCW квадрат: is_clockwise() = False")
        else:
            self.logger.error(f"CCW квадрат: ожидалось False, получено {result}")

    def test_09_find_nw_point_index_public(self):
        """find_nw_point_index() доступен как публичный метод"""
        self.logger.section("9. find_nw_point_index() - публичный API")

        from Daman_QGIS.managers.geometry import PointNumberingManager

        points = [(10, 0), (20, 10), (0, 20), (5, 5)]
        # СЗ угол MBR: min_x=0, max_y=20 -> ближайшая точка (0, 20) = индекс 2
        idx = PointNumberingManager.find_nw_point_index(points)
        if idx == 2:
            self.logger.success(f"СЗ точка: индекс {idx} = {points[idx]}")
        else:
            self.logger.error(f"Ожидался индекс 2, получен {idx} = {points[idx]}")
