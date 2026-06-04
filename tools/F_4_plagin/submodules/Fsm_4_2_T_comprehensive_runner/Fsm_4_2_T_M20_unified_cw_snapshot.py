# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_M20_unified_cw_snapshot — regression guard для unified_cw (FIX-9).

Фиксирует поведение нормализации колец ПОСЛЕ flip П/0592 → unified_cw (2026-05-31):
- ВСЕ кольца (exterior + hole) приводятся к CW в мат.СК (signed_area < 0).
- Shared-boundary topology (hole = соседний exterior, общие точки): после нормализации
  общие точки идентичны в обоих кольцах → нумерация M_20 (_unique_points first-encounter)
  стабильна, нет рассогласования exterior_numbers vs holes_numbers.

Назначение: поймать регресс, если кто-то частично откатит unified_cw или вернёт П/0592
hole-CCW. Прецедент: rev1 Issue 2 (shared-boundary dedup-order break при смене ориентации).
"""


class TestM20UnifiedCwSnapshot:
    """Regression guard: unified_cw + shared-boundary стабильность нумерации."""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.pnm = None

    def run_all_tests(self):
        self.logger.section("ТЕСТ M_20: unified_cw snapshot (shared-boundary, FIX-9)")

        try:
            self._init_manager()
            self.test_01_hole_normalized_to_cw()
            self.test_02_exterior_and_hole_both_cw()
            self.test_03_shared_boundary_points_consistent()
        except Exception as e:
            self.logger.error(f"Критическая ошибка: {e}")

        self.logger.summary()

    def _init_manager(self):
        from Daman_QGIS.managers import registry
        self.pnm = registry.get('M_20')
        self.logger.success("PointNumberingManager инициализирован")

    def _signed_area_2(self, points):
        """Shoelace: signed_area*2. < 0 = CW в мат.СК."""
        n = len(points)
        area = 0.0
        for i in range(n):
            j = (i + 1) % n
            area += points[i][0] * points[j][1]
            area -= points[j][0] * points[i][1]
        return area

    def test_01_hole_normalized_to_cw(self):
        """unified_cw: hole (is_exterior=False) приводится к CW, НЕ к CCW (был П/0592)."""
        self.logger.section("1. Hole → CW (unified_cw, не CCW)")

        # CCW-квадрат (signed_area > 0) как «внутренний контур»
        ccw_hole = [(30, 30), (70, 30), (70, 70), (30, 70)]
        result = self.pnm.normalize_ring(ccw_hole, is_exterior=False)
        sa = self._signed_area_2(result)
        if sa < 0:
            self.logger.success(f"Hole нормализован в CW (unified_cw): signed_area_2 = {sa}")
        else:
            self.logger.error(f"Регресс П/0592: hole остался CCW (signed_area_2 = {sa}), ожидалось CW < 0")

    def test_02_exterior_and_hole_both_cw(self):
        """unified_cw: exterior И hole оба CW (единый обход)."""
        self.logger.section("2. Exterior + hole оба CW")

        exterior = [(0, 0), (100, 0), (100, 100), (0, 100)]   # CCW вход
        hole = [(30, 30), (70, 30), (70, 70), (30, 70)]       # CCW вход
        ext_n = self.pnm.normalize_ring(exterior, is_exterior=True)
        hole_n = self.pnm.normalize_ring(hole, is_exterior=False)
        ext_cw = self._signed_area_2(ext_n) < 0
        hole_cw = self._signed_area_2(hole_n) < 0
        if ext_cw and hole_cw:
            self.logger.success("Оба кольца CW (exterior + hole) — unified_cw соблюдён")
        else:
            self.logger.error(f"Не оба CW: exterior_cw={ext_cw}, hole_cw={hole_cw}")

    def test_03_shared_boundary_points_consistent(self):
        """Shared-boundary: два смежных кольца с общей гранью → общие точки
        после нормализации присутствуют в обоих (стабильность _unique_points)."""
        self.logger.section("3. Shared-boundary: общие точки консистентны")

        # Два квадрата с общей гранью x=50 (точки (50,0) и (50,100) — общие)
        left = [(0, 0), (50, 0), (50, 100), (0, 100)]
        right = [(50, 0), (100, 0), (100, 100), (50, 100)]
        left_n = set(self.pnm.normalize_ring(left, is_exterior=True))
        right_n = set(self.pnm.normalize_ring(right, is_exterior=True))
        shared = left_n & right_n
        # Общая грань: ожидаем минимум 2 общие точки (50,0) и (50,100)
        expected_shared = {(50, 0), (50, 100)}
        if expected_shared.issubset(shared):
            self.logger.success(
                f"Общие точки сохранены в обоих кольцах после нормализации: {sorted(shared)}"
            )
        else:
            self.logger.error(
                f"Shared-boundary регресс: ожидались {expected_shared}, найдены {sorted(shared)}"
            )
