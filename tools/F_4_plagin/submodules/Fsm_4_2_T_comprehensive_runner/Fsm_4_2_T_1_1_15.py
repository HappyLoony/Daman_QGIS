# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_1_1_15 — Тест Fsm_1_1_15_GeometryValidator (F_1_1).

Проверяет валидацию и авто-исправление невалидной геометрии на импорте:
- hole-outside-shell → валидный MultiPolygon (2 части);
- позиционный merge (>=2 невалидных различимых фичи);
- C-1b unfixable-ветка (fixgeometries → MultiPolygon EMPTY);
- атрибутная идентичность, исходный порядок, feature_count сохранён;
- OPT-002 (ОБЯЗАТЕЛЕН): ветка re-validation _round_geometry:431 (snap-induced
  невалидность) — свойство-планка (test_01) + сквозной прогон через validator
  (test_04, E2E-фикстура) + прямой unit _round_geometry (test_10);
- Z/M defensive skip (test_11, FIX-3).

SCOPE (FIX-6c): все тесты — unit на memory-слоях. Интеграция «MultiPolygon-выход
→ save_to_gpkg → commitChanges()/commitErrors()» (§4) вне unit-scope —
верифицируется GUI-приёмкой владельца (§8 DoD: реимпорт тест-TAB в QGIS,
отрисовка исправленного контура на всех масштабах).

ВЫПОЛНЕНИЕ: тесты плагина исполняются в QGIS вручную (агент их не запускает).
"""

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsField,
    QgsFields,
    Qgis,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QMetaType


# Raw hourglass с талией 0.004 (эмпирически выверен QGIS 3.40.15):
# snappedToGrid(0.01) сваривает талию 0.502/0.498→0.50 → non-empty И
# isGeosValid=False. ВАЖНО (FIX-2): сам hourglass ВАЛИДЕН до fix (isGeosValid=
# True) → validator D1 его НЕ флагует. Поэтому эта фикстура пригодна ТОЛЬКО для
# машинной планки СВОЙСТВА snappedToGrid (test_01), НЕ для сквозного прогона
# через validator. Сквозной вход в :431 — FIXTURE_E2E_431_WKT ниже.
FIXTURE_HOURGLASS_WKT = "POLYGON((0 0,1 0,0.502 0.5,1 1,0 1,0.498 0.5,0 0))"

# Сквозная OPT-002-фикстура (эмпирически выверена QGIS 3.40.15, FIX-2): hourglass-
# shell (талия 0.004) + hole-outside-shell → вход isGeosValid=FALSE → validator D1
# флагует → fixgeometries METHOD=1 → валидный MultiPolygon (талия сохранена) →
# внутри M_6._round_geometry: snappedToGrid(0.01) сваривает талию → empty=False,
# valid=False = РЕАЛЬНЫЙ вход в ветку :431 через пайплайн validator (не только
# в property-тесте). test_04 прогоняет её сквозь validate_and_fix_layer.
FIXTURE_E2E_431_WKT = (
    "POLYGON((0 0,1 0,0.502 0.5,1 1,0 1,0.498 0.5,0 0),"
    "(20 20,20.5 20,20.5 20.5,20 20.5,20 20))"
)

# Контроль «коллапс-слайвер» — snap → EMPTY → :424 (НЕ входит в :431).
# Демонстрирует, почему неверная фикстура прошла бы зелёной (OPT-R15-001).
FIXTURE_COLLAPSE_SLIVER_WKT = "POLYGON((0 0,1 0,1 0.004,0 0.004,0 0))"

# hole-outside-shell (диагноз §1): второе кольцо полностью снаружи shell.
FIXTURE_HOLE_OUTSIDE_SHELL_WKT = (
    "POLYGON((0 0,10 0,10 10,0 10,0 0),(20 20,22 20,22 22,20 22,20 20))"
)


class TestGeometryValidator:
    """Тесты Fsm_1_1_15_GeometryValidator."""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger

    def run_all_tests(self):
        self.logger.section("ТЕСТ Fsm_1_1_15: Валидация/исправление геометрии на импорте")
        try:
            self.test_01_fixture_assert_bar()
            self.test_02_collapse_sliver_control()
            self.test_03_hole_outside_shell_fix()
            self.test_04_re_validation_branch_431()
            self.test_05_valid_layer_early_return()
            self.test_06_positional_merge()
            self.test_07_unfixable_c1b_guard()
            self.test_08_non_polygon_passthrough()
            self.test_09_attribute_identity_and_count()
            self.test_10_round_geometry_direct_unit()
            self.test_11_zm_defensive_skip()
        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов Fsm_1_1_15: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
        self.logger.summary()

    # ------------------------------------------------------------------
    # Хелперы
    # ------------------------------------------------------------------

    def _make_polygon_layer(self, name="test_geom", crs="EPSG:32637"):
        """Полигональный memory-слой с полями id(Int), name(String)."""
        layer = QgsVectorLayer(f"Polygon?crs={crs}", name, "memory")
        provider = layer.dataProvider()
        fields = QgsFields()
        fields.append(QgsField("id", QMetaType.Type.Int))
        fields.append(QgsField("name", QMetaType.Type.QString))
        provider.addAttributes(fields)
        layer.updateFields()
        return layer

    def _add_feature(self, layer, wkt, attrs):
        feat = QgsFeature(layer.fields())
        feat.setGeometry(QgsGeometry.fromWkt(wkt))
        feat.setAttributes(attrs)
        layer.dataProvider().addFeature(feat)
        layer.updateExtents()
        return feat

    # ------------------------------------------------------------------
    # OPT-002 — машинная ассерт-планка (ОБЯЗАТЕЛЬНА)
    # ------------------------------------------------------------------

    def test_01_fixture_assert_bar(self):
        """ТЕСТ 1: Канонич. фикстура hourglass входит в ветку :431.

        Машинная планка (план §8): fixture.snappedToGrid(0.01,0.01) обязан быть
        `not isEmpty() AND not isGeosValid()` — доказательство входа в целевую
        re-validation-ветку. Иначе фикстура мимо цели (лазейка в геометрии).
        """
        self.logger.section("1. OPT-002 ассерт-планка: hourglass → :431")
        try:
            fixture = QgsGeometry.fromWkt(FIXTURE_HOURGLASS_WKT)
            self.logger.check(
                not fixture.isEmpty(),
                "Исходная фикстура не пуста",
                "Фикстура пуста — некорректный WKT!",
            )

            snapped = fixture.snappedToGrid(0.01, 0.01)

            # КЛЮЧЕВАЯ ПЛАНКА: доказательство входа в _round_geometry:431.
            self.logger.check(
                not snapped.isEmpty(),
                "snappedToGrid(0.01) НЕ пуст (мимо empty-fallback :424)",
                "snappedToGrid дал EMPTY — фикстура коллапсирует, мимо ветки :431!",
            )
            self.logger.check(
                not snapped.isGeosValid(),
                "snappedToGrid(0.01) GEOS-НЕВАЛИДЕН (вход в :431 подтверждён)",
                "snappedToGrid валиден — фикстура НЕ триггерит re-validation!",
            )
        except Exception as e:
            self.logger.error(f"Ошибка теста ассерт-планки: {str(e)}")

    def test_02_collapse_sliver_control(self):
        """ТЕСТ 2: Контроль — коллапс-слайвер snap→EMPTY (мимо :431).

        Демонстрирует OPT-R15-001: неверная фикстура даёт EMPTY на :424, тест
        прошёл бы зелёным БЕЗ исполнения guard :431.
        """
        self.logger.section("2. Контроль: коллапс-слайвер → EMPTY (мимо :431)")
        try:
            sliver = QgsGeometry.fromWkt(FIXTURE_COLLAPSE_SLIVER_WKT)
            snapped = sliver.snappedToGrid(0.01, 0.01)
            self.logger.check(
                snapped.isEmpty(),
                "Коллапс-слайвер snappedToGrid → EMPTY (подтверждает: НЕ годна для :431)",
                "Коллапс-слайвер дал непустой результат — контроль не работает!",
            )
        except Exception as e:
            self.logger.error(f"Ошибка контрольного теста: {str(e)}")

    # ------------------------------------------------------------------
    # Основная функциональность
    # ------------------------------------------------------------------

    def test_03_hole_outside_shell_fix(self):
        """ТЕСТ 3: hole-outside-shell → валидный MultiPolygon (2 части)."""
        self.logger.section("3. hole-outside-shell → валидный MultiPolygon")
        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_1_15_geometry_validator import (
                Fsm_1_1_15_GeometryValidator,
            )

            layer = self._make_polygon_layer()
            src = QgsGeometry.fromWkt(FIXTURE_HOLE_OUTSIDE_SHELL_WKT)
            self.logger.check(
                not src.isGeosValid(),
                "Исходная hole-outside-shell геометрия невалидна (как ожидалось)",
                "Исходная геометрия валидна — фикстура некорректна!",
            )
            self._add_feature(layer, FIXTURE_HOLE_OUTSIDE_SHELL_WKT, [127, "fid127"])

            result, stats = Fsm_1_1_15_GeometryValidator.validate_and_fix_layer(layer)

            self.logger.data("stats", str(stats))
            self.logger.check(
                stats.get("invalid") == 1 and stats.get("fixed") == 1,
                "Исправлена 1 из 1 невалидной",
                f"Счётчик неверен: {stats}",
            )

            out_feats = list(result.getFeatures())
            self.logger.check(
                len(out_feats) == 1,
                "feature_count сохранён (1=1)",
                f"feature_count изменился: {len(out_feats)}",
            )
            fixed_geom = out_feats[0].geometry()
            self.logger.check(
                fixed_geom.isGeosValid(),
                "Выходная геометрия валидна",
                "Выходная геометрия невалидна!",
            )
            self.logger.check(
                fixed_geom.isMultipart()
                and len(fixed_geom.asMultiPolygon()) == 2,
                "Выход — MultiPolygon из 2 частей",
                f"Не 2-частный MultiPolygon: multipart={fixed_geom.isMultipart()}",
            )
        except Exception as e:
            self.logger.error(f"Ошибка теста hole-outside-shell: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_04_re_validation_branch_431(self):
        """ТЕСТ 4: OPT-002 сквозной — E2E-фикстура через валидатор (:431 исполнен).

        FIX-2: raw hourglass ВАЛИДЕН до fix → D1 его не флагует → мимо :431.
        E2E-фикстура (hourglass-shell + hole-outside-shell) НЕВАЛИДНА на входе →
        D1 флагует → fixgeometries → валидный MP с сохранённой талией 0.004 →
        M_6._round_geometry.snappedToGrid сваривает талию → реальный вход в :431
        ВНУТРИ валидатора. Ассерты: выход валиден+непустой, fixed==1, unfixable==0.
        """
        self.logger.section("4. OPT-002 сквозной: E2E-фикстура через валидатор (:431)")
        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_1_15_geometry_validator import (
                Fsm_1_1_15_GeometryValidator,
            )

            # Самодоказательство: E2E-фикстура НЕВАЛИДНА на входе (доходит до fix).
            e2e_src = QgsGeometry.fromWkt(FIXTURE_E2E_431_WKT)
            self.logger.check(
                not e2e_src.isEmpty() and not e2e_src.isGeosValid(),
                "E2E-фикстура на входе: непуста И невалидна (доходит до fix → D1 флагует)",
                f"E2E-фикстура не годна: empty={e2e_src.isEmpty()}, valid={e2e_src.isGeosValid()}",
            )

            layer = self._make_polygon_layer()
            self._add_feature(layer, FIXTURE_E2E_431_WKT, [1, "e2e_431"])

            result, stats = Fsm_1_1_15_GeometryValidator.validate_and_fix_layer(layer)

            out_feats = list(result.getFeatures())
            self.logger.check(
                len(out_feats) == 1,
                "feature_count сохранён (1=1) для E2E-фикстуры",
                f"feature_count изменился: {len(out_feats)}",
            )
            geom = out_feats[0].geometry()
            self.logger.check(
                geom.isGeosValid() and not geom.isEmpty(),
                "E2E-фикстура исправлена → валидная непустая геометрия (:431 отработал)",
                f"E2E не исправлена: valid={geom.isGeosValid()}, empty={geom.isEmpty()}",
            )
            self.logger.check(
                stats.get("fixed") == 1 and stats.get("unfixable") == 0,
                "E2E учтена как fixed (не unfixable)",
                f"Счётчик E2E неверен: {stats}",
            )
        except Exception as e:
            self.logger.error(f"Ошибка сквозного теста ветки :431: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_05_valid_layer_early_return(self):
        """ТЕСТ 5: Валидный слой → early-return as-is (тип НЕ промотируется)."""
        self.logger.section("5. Валидный слой → early-return")
        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_1_15_geometry_validator import (
                Fsm_1_1_15_GeometryValidator,
            )

            layer = self._make_polygon_layer()
            self._add_feature(layer, "POLYGON((0 0,5 0,5 5,0 5,0 0))", [1, "ok"])

            result, stats = Fsm_1_1_15_GeometryValidator.validate_and_fix_layer(layer)

            self.logger.check(
                result is layer,
                "Возвращён тот же слой (early-return, не пересобран)",
                "Валидный слой пересобран — early-return не сработал!",
            )
            self.logger.check(
                stats.get("invalid") == 0 and stats.get("fixed") == 0,
                "Счётчик: 0 невалидных, 0 исправлено",
                f"Счётчик валидного слоя неверен: {stats}",
            )
        except Exception as e:
            self.logger.error(f"Ошибка теста early-return: {str(e)}")

    def test_06_positional_merge(self):
        """ТЕСТ 6: >=2 невалидных различимых фичи — позиционный merge (C-1)."""
        self.logger.section("6. Позиционный merge (>=2 невалидных различимых)")
        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_1_15_geometry_validator import (
                Fsm_1_1_15_GeometryValidator,
            )

            layer = self._make_polygon_layer()
            # Две различимые hole-outside-shell фичи в разных местах.
            self._add_feature(
                layer,
                "POLYGON((0 0,10 0,10 10,0 10,0 0),(20 20,22 20,22 22,20 22,20 20))",
                [1, "A"],
            )
            self._add_feature(
                layer,
                "POLYGON((100 100,110 100,110 110,100 110,100 100),"
                "(200 200,202 200,202 202,200 202,200 200))",
                [2, "B"],
            )
            # Плюс валидная между ними по порядку (проверка исходного порядка).
            self._add_feature(layer, "POLYGON((50 50,55 50,55 55,50 55,50 50))", [3, "V"])

            result, stats = Fsm_1_1_15_GeometryValidator.validate_and_fix_layer(layer)

            out = list(result.getFeatures())
            self.logger.check(
                len(out) == 3,
                "feature_count сохранён (3=3)",
                f"feature_count изменился: {len(out)}",
            )
            # Исходный порядок id сохранён: 1,2,3.
            ids = [f.attribute("id") for f in out]
            self.logger.check(
                ids == [1, 2, 3],
                "Исходный порядок фич сохранён (id=[1,2,3])",
                f"Порядок нарушен: {ids}",
            )
            # Каждая невалидная (A под id=1, B под id=2) на своём месте и валидна.
            geom_a = out[0].geometry()
            geom_b = out[1].geometry()
            # A привязана к области (0..22), B — (100..202): проверяем bbox-центры.
            bbox_a = geom_a.boundingBox()
            bbox_b = geom_b.boundingBox()
            self.logger.check(
                bbox_a.xMinimum() < 50 and bbox_b.xMinimum() > 50,
                "Позиционный merge верен: A(id=1)~малые координаты, B(id=2)~большие",
                f"Merge сдвинут: A.xmin={bbox_a.xMinimum()}, B.xmin={bbox_b.xMinimum()}",
            )
            self.logger.check(
                geom_a.isGeosValid() and geom_b.isGeosValid(),
                "Обе невалидные фичи исправлены",
                "Не все невалидные исправлены после merge!",
            )
        except Exception as e:
            self.logger.error(f"Ошибка теста позиционного merge: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_07_unfixable_c1b_guard(self):
        """ТЕСТ 7: C-1b — unfixable (collapse) → EMPTY-детект, фича сохранена."""
        self.logger.section("7. C-1b unfixable guard (collapse → EMPTY)")
        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_1_15_geometry_validator import (
                Fsm_1_1_15_GeometryValidator,
            )

            # Вырожденный «спайк»: линия-в-полигоне (нулевая площадь) →
            # fixgeometries METHOD=1 даёт MultiPolygon EMPTY (isNull=False).
            spike_wkt = "POLYGON((0 0,1 0,0 0,0 0))"

            # FIX-4: input-планка (зеркально test_01) — фикстура доходит до fix.
            # Эмпирически spike: empty=False, valid=False → проходит D1.
            spike_src = QgsGeometry.fromWkt(spike_wkt)
            self.logger.check(
                not spike_src.isEmpty() and not spike_src.isGeosValid(),
                "Spike-фикстура на входе: непуста И невалидна (доходит до fix → D1 флагует)",
                f"Spike-фикстура не годна: empty={spike_src.isEmpty()}, valid={spike_src.isGeosValid()}",
            )

            layer = self._make_polygon_layer()
            self._add_feature(layer, spike_wkt, [1, "spike"])

            result, stats = Fsm_1_1_15_GeometryValidator.validate_and_fix_layer(layer)

            out = list(result.getFeatures())
            self.logger.check(
                len(out) == 1,
                "Unfixable фича СОХРАНЕНА (count не упал: 1=1)",
                f"Unfixable фича потеряна! count={len(out)}",
            )
            geom = out[0].geometry()
            self.logger.check(
                not geom.isEmpty(),
                "Выходная геометрия НЕ пустая (EMPTY не записался — нет silent-loss)",
                "Записана пустая геометрия — C-1b guard пропустил EMPTY (silent-loss)!",
            )
            self.logger.check(
                geom.isMultipart(),
                "Unfixable перенесена как MultiPolygon (промотирована)",
                "Unfixable не промотирована в Multi — не сохранилась бы в MP-слое!",
            )
            self.logger.check(
                stats.get("unfixable") == 1,
                "Счётчик unfixable=1",
                f"Счётчик unfixable неверен: {stats}",
            )
        except Exception as e:
            self.logger.error(f"Ошибка теста C-1b: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_08_non_polygon_passthrough(self):
        """ТЕСТ 8: Не полигональный слой → as-is (тип не промотируется)."""
        self.logger.section("8. Не-полигональный слой → passthrough")
        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_1_15_geometry_validator import (
                Fsm_1_1_15_GeometryValidator,
            )

            layer = QgsVectorLayer("Point?crs=EPSG:32637", "pts", "memory")
            provider = layer.dataProvider()
            fields = QgsFields()
            fields.append(QgsField("id", QMetaType.Type.Int))
            provider.addAttributes(fields)
            layer.updateFields()
            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry.fromWkt("POINT(1 1)"))
            feat.setAttributes([1])
            provider.addFeature(feat)

            result, stats = Fsm_1_1_15_GeometryValidator.validate_and_fix_layer(layer)

            self.logger.check(
                result is layer,
                "Точечный слой возвращён as-is",
                "Точечный слой изменён — фильтр не сработал!",
            )
            self.logger.check(
                stats.get("invalid") == 0,
                "Невалидных не искали в не-полигональном слое",
                f"Счётчик неверен для точек: {stats}",
            )
        except Exception as e:
            self.logger.error(f"Ошибка теста passthrough: {str(e)}")

    def test_09_attribute_identity_and_count(self):
        """ТЕСТ 9: Атрибутная идентичность + feature_count при смешанном слое."""
        self.logger.section("9. Атрибутная идентичность + count (смешанный слой)")
        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_1_15_geometry_validator import (
                Fsm_1_1_15_GeometryValidator,
            )

            layer = self._make_polygon_layer()
            # 1 валидная + 1 невалидная, с кириллическими атрибутами.
            self._add_feature(layer, "POLYGON((0 0,5 0,5 5,0 5,0 0))", [10, "Участок_А"])
            self._add_feature(
                layer,
                "POLYGON((0 0,10 0,10 10,0 10,0 0),(20 20,22 20,22 22,20 22,20 20))",
                [11, "Контур_Б"],
            )

            result, stats = Fsm_1_1_15_GeometryValidator.validate_and_fix_layer(layer)

            out = list(result.getFeatures())
            self.logger.check(
                len(out) == 2,
                "feature_count сохранён (2=2)",
                f"feature_count изменился: {len(out)}",
            )
            # Атрибуты + кириллица сохранены позиционно.
            names = [f.attribute("name") for f in out]
            ids = [f.attribute("id") for f in out]
            self.logger.check(
                ids == [10, 11] and names == ["Участок_А", "Контур_Б"],
                "Атрибуты (вкл. кириллицу) и порядок сохранены",
                f"Атрибуты искажены: ids={ids}, names={names}",
            )
            # Все фичи на выходе — MultiPolygon.
            all_multi = all(
                f.geometry().isMultipart() for f in out if not f.geometry().isNull()
            )
            self.logger.check(
                all_multi,
                "Все выходные фичи — MultiPolygon (валидная промотирована)",
                "Не все фичи MultiPolygon — валидная не промотирована!",
            )
        except Exception as e:
            self.logger.error(f"Ошибка теста атрибутной идентичности: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_10_round_geometry_direct_unit(self):
        """ТЕСТ 10: Прямой unit M_6._round_geometry на snap-невалидной геометрии.

        FIX-2: прямое доказательство исполнения ветки :431-435 (не через пайплайн).
        Подаём геометрию, гарантированно НЕВАЛИДНУЮ ПОСЛЕ snap (снапнутый hourglass
        со сваренной талией) → _round_geometry обязан вернуть валидную непустую
        (второй makeValid+CollectionExtract чинит snap-induced невалидность).
        """
        self.logger.section("10. Прямой unit: M_6._round_geometry(:431-435)")
        try:
            from Daman_QGIS.managers import CoordinatePrecisionManager as CPM

            # Снапнутый hourglass (талия сварена 0.502/0.498→0.50) — невалиден.
            snapped_invalid = QgsGeometry.fromWkt(FIXTURE_HOURGLASS_WKT).snappedToGrid(0.01, 0.01)
            # Самодоказательство: подаваемая геометрия непуста И невалидна
            # (иначе _round_geometry ушёл бы на empty-fallback :424, мимо :431).
            self.logger.check(
                not snapped_invalid.isEmpty() and not snapped_invalid.isGeosValid(),
                "Вход _round_geometry: непуст И невалиден (вход в :431 гарантирован)",
                f"Вход не годен: empty={snapped_invalid.isEmpty()}, valid={snapped_invalid.isGeosValid()}",
            )

            fixed = CPM._round_geometry(snapped_invalid)

            self.logger.check(
                fixed is not None and not fixed.isNull() and not fixed.isEmpty(),
                "_round_geometry вернул непустую геометрию (не свалился в fallback)",
                "_round_geometry вернул пустую/None — ветка :431-435 не исправила!",
            )
            self.logger.check(
                fixed is not None and fixed.isGeosValid(),
                "_round_geometry вернул ВАЛИДНУЮ геометрию (:432 makeValid отработал)",
                "_round_geometry вернул невалидную — re-validation :431 не сработал!",
            )
        except Exception as e:
            self.logger.error(f"Ошибка прямого unit _round_geometry: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    def test_11_zm_defensive_skip(self):
        """ТЕСТ 11: FIX-3 — невалидная Z-фича → defensive skip fix, перенос как есть.

        Z/M-невалидная фича НЕ гонится через fixgeometries/snap (план §2/§6), но
        сохраняется (count не падает), промотирована в Multi, учтена в zm_skipped.
        """
        self.logger.section("11. Z/M defensive skip (FIX-3)")
        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_1_15_geometry_validator import (
                Fsm_1_1_15_GeometryValidator,
            )

            # Полигональный слой с Z. Невалидная hole-outside-shell в 3D.
            layer = QgsVectorLayer("PolygonZ?crs=EPSG:32637", "geomz", "memory")
            provider = layer.dataProvider()
            fields = QgsFields()
            fields.append(QgsField("id", QMetaType.Type.Int))
            provider.addAttributes(fields)
            layer.updateFields()
            feat = QgsFeature(layer.fields())
            zwkt = (
                "POLYGON Z((0 0 5,10 0 5,10 10 5,0 10 5,0 0 5),"
                "(20 20 5,22 20 5,22 22 5,20 22 5,20 20 5))"
            )
            zgeom = QgsGeometry.fromWkt(zwkt)
            feat.setGeometry(zgeom)
            feat.setAttributes([1])
            provider.addFeature(feat)
            layer.updateExtents()

            # Планка входа: Z-фича невалидна и имеет Z.
            self.logger.check(
                not zgeom.isGeosValid() and QgsWkbTypes.hasZ(zgeom.wkbType()),
                "Z-фикстура: невалидна И hasZ (годна для Z/M-skip ветки)",
                f"Z-фикстура не годна: valid={zgeom.isGeosValid()}, hasZ={QgsWkbTypes.hasZ(zgeom.wkbType())}",
            )

            result, stats = Fsm_1_1_15_GeometryValidator.validate_and_fix_layer(layer)

            self.logger.check(
                stats.get("zm_skipped") == 1 and stats.get("invalid") == 0,
                "Z-фича учтена как zm_skipped=1, invalid=0 (не гналась через fix)",
                f"Счётчик Z/M неверен: {stats}",
            )
            out = list(result.getFeatures())
            self.logger.check(
                len(out) == 1,
                "Z-фича СОХРАНЕНА (count 1=1)",
                f"Z-фича потеряна! count={len(out)}",
            )
            self.logger.check(
                out[0].geometry() is not None and not out[0].geometry().isEmpty(),
                "Z-фича перенесена как есть (непустая)",
                "Z-фича пустая на выходе!",
            )
        except Exception as e:
            self.logger.error(f"Ошибка теста Z/M defensive skip: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
