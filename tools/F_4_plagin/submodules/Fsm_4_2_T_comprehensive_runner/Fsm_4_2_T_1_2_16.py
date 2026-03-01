# -*- coding: utf-8 -*-
"""
Субмодуль Fsm_4_2_T_1_2_16 - Тест Fsm_1_2_16_Deduplicator

Проверяет двухуровневую дедупликацию геометрий:
  Level 1: normalize() + WKB hash (exact duplicates)
  Level 2: IoU >= threshold (near-duplicates)
"""

from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry

from .fixtures.layer_fixtures import (
    create_polygon_layer,
    create_line_layer,
    LayerFixtures,
)


class TestF1216:
    """Тесты для Fsm_1_2_16_Deduplicator"""

    def __init__(self, iface, logger):
        self.iface = iface
        self.logger = logger
        self.dedup_class = None

    def run_all_tests(self):
        """Запуск всех тестов"""
        self.logger.section("ТЕСТ Fsm_1_2_16: Deduplicator")

        try:
            self.test_01_init()
            self.test_02_empty_layer()
            self.test_03_no_duplicates()
            self.test_04_exact_duplicates()
            self.test_05_normalize_effect()
            self.test_06_near_duplicates_iou()
            self.test_07_non_duplicate_overlap()
            self.test_08_line_layer_skip()
            self.test_09_null_geometries()
            self.test_10_full_pipeline()
            self.test_11_disable_near_duplicates()
            self.test_12_custom_iou_threshold()
            self.test_13_invalid_geometry_iou()
            self.test_14_multipolygon_dedup()
        except Exception as e:
            self.logger.error(f"Критическая ошибка: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

        self.logger.summary()

    # ------------------------------------------------------------------
    # Test 1: Инициализация
    # ------------------------------------------------------------------
    def test_01_init(self):
        """ТЕСТ 1: Импорт и инициализация модуля"""
        self.logger.section("1. Инициализация модуля Fsm_1_2_16")

        try:
            from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_2_16_deduplicator import (
                Fsm_1_2_16_Deduplicator,
            )

            self.dedup_class = Fsm_1_2_16_Deduplicator
            self.logger.success("Модуль Fsm_1_2_16_Deduplicator импортирован")

            # Проверка создания экземпляра
            dedup = Fsm_1_2_16_Deduplicator(caller_id="TEST")
            self.logger.check(
                dedup.caller_id == "TEST",
                "caller_id установлен корректно",
                f"caller_id = '{dedup.caller_id}', ожидался 'TEST'",
            )

            # Константа IOU_THRESHOLD
            self.logger.check(
                Fsm_1_2_16_Deduplicator.IOU_THRESHOLD == 0.95,
                "IOU_THRESHOLD = 0.95",
                f"IOU_THRESHOLD = {Fsm_1_2_16_Deduplicator.IOU_THRESHOLD}",
            )

            # Наличие методов
            for method in ["deduplicate", "deduplicate_exact", "deduplicate_near"]:
                self.logger.check(
                    hasattr(dedup, method),
                    f"Метод {method} существует",
                    f"Метод {method} отсутствует!",
                )

            # caller_id по умолчанию
            dedup_default = Fsm_1_2_16_Deduplicator()
            self.logger.check(
                dedup_default.caller_id == "Fsm_1_2_16",
                "caller_id по умолчанию = 'Fsm_1_2_16'",
                f"caller_id по умолчанию = '{dedup_default.caller_id}'",
            )

        except Exception as e:
            self.logger.error(f"Ошибка инициализации: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ------------------------------------------------------------------
    # Test 2: Пустой слой
    # ------------------------------------------------------------------
    def test_02_empty_layer(self):
        """ТЕСТ 2: Пустой слой (0 features)"""
        self.logger.section("2. Пустой слой")

        if not self.dedup_class:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            layer = create_polygon_layer("empty_test")
            dedup = self.dedup_class(caller_id="TEST")
            result = dedup.deduplicate(layer)

            self.logger.check(
                result["exact_removed"] == 0,
                "exact_removed = 0",
                f"exact_removed = {result['exact_removed']}",
            )
            self.logger.check(
                result["near_removed"] == 0,
                "near_removed = 0",
                f"near_removed = {result['near_removed']}",
            )
            self.logger.check(
                result["total_removed"] == 0,
                "total_removed = 0",
                f"total_removed = {result['total_removed']}",
            )
            self.logger.check(
                result["remaining"] == 0,
                "remaining = 0",
                f"remaining = {result['remaining']}",
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ------------------------------------------------------------------
    # Test 3: Без дубликатов
    # ------------------------------------------------------------------
    def test_03_no_duplicates(self):
        """ТЕСТ 3: Слой без дубликатов"""
        self.logger.section("3. Слой без дубликатов")

        if not self.dedup_class:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            layer = LayerFixtures.polygon_layer_with_squares(
                count=5, size=1.0, spacing=3.0
            )
            initial = layer.featureCount()
            self.logger.data("Features до", str(initial))

            dedup = self.dedup_class(caller_id="TEST")
            result = dedup.deduplicate(layer)

            self.logger.check(
                result["total_removed"] == 0,
                "Дубликаты не найдены (0 удалено)",
                f"Удалено {result['total_removed']} (ошибка!)",
            )
            self.logger.check(
                result["remaining"] == initial,
                f"remaining = {initial}",
                f"remaining = {result['remaining']}, ожидалось {initial}",
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ------------------------------------------------------------------
    # Test 4: Exact duplicates
    # ------------------------------------------------------------------
    def test_04_exact_duplicates(self):
        """ТЕСТ 4: Точные дубликаты WKB"""
        self.logger.section("4. Exact duplicates (Level 1)")

        if not self.dedup_class:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            layer = create_polygon_layer("exact_dupes")

            # 3 уникальных полигона
            LayerFixtures.add_feature(
                layer, "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))", [1, "A", 1.0]
            )
            LayerFixtures.add_feature(
                layer, "POLYGON((2 0, 3 0, 3 1, 2 1, 2 0))", [2, "B", 1.0]
            )
            LayerFixtures.add_feature(
                layer, "POLYGON((4 0, 5 0, 5 1, 4 1, 4 0))", [3, "C", 1.0]
            )
            # 2 дубликата (повтор полигонов A и B)
            LayerFixtures.add_feature(
                layer, "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))", [4, "A_dup", 1.0]
            )
            LayerFixtures.add_feature(
                layer, "POLYGON((2 0, 3 0, 3 1, 2 1, 2 0))", [5, "B_dup", 1.0]
            )

            self.logger.data("Features до", str(layer.featureCount()))

            dedup = self.dedup_class(caller_id="TEST")
            result = dedup.deduplicate_exact(layer)

            self.logger.check(
                result == 2,
                f"Удалено 2 exact дубликата",
                f"Удалено {result}, ожидалось 2",
            )
            self.logger.check(
                layer.featureCount() == 3,
                f"Осталось 3 features",
                f"Осталось {layer.featureCount()}, ожидалось 3",
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ------------------------------------------------------------------
    # Test 5: normalize() эффект
    # ------------------------------------------------------------------
    def test_05_normalize_effect(self):
        """ТЕСТ 5: normalize() ловит дубли с разным порядком вершин"""
        self.logger.section("5. normalize() эффект")

        if not self.dedup_class:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            layer = create_polygon_layer("normalize_test")

            # Полигон 1: начало кольца в точке (0,0)
            LayerFixtures.add_feature(
                layer, "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))", [1, "orig", 100.0]
            )
            # Полигон 2: тот же полигон, но начало кольца в (10,0)
            LayerFixtures.add_feature(
                layer, "POLYGON((10 0, 10 10, 0 10, 0 0, 10 0))", [2, "rotated", 100.0]
            )
            # Полигон 3: тот же полигон, начало в (10,10)
            LayerFixtures.add_feature(
                layer, "POLYGON((10 10, 0 10, 0 0, 10 0, 10 10))", [3, "rotated2", 100.0]
            )

            self.logger.data("Features до", str(layer.featureCount()))

            dedup = self.dedup_class(caller_id="TEST")
            removed = dedup.deduplicate_exact(layer)

            self.logger.check(
                removed == 2,
                "normalize() обнаружил 2 дубликата с разным порядком вершин",
                f"Удалено {removed}, ожидалось 2 (normalize не сработал?)",
            )
            self.logger.check(
                layer.featureCount() == 1,
                "Остался 1 уникальный feature",
                f"Осталось {layer.featureCount()}, ожидался 1",
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ------------------------------------------------------------------
    # Test 6: Near-duplicates (IoU)
    # ------------------------------------------------------------------
    def test_06_near_duplicates_iou(self):
        """ТЕСТ 6: Near-duplicates через IoU >= 0.95"""
        self.logger.section("6. Near-duplicates (Level 2, IoU)")

        if not self.dedup_class:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            layer = create_polygon_layer("near_dupes")

            # Полигон A: 10x10 квадрат
            LayerFixtures.add_feature(
                layer, "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))", [1, "A", 100.0]
            )
            # Полигон B: тот же квадрат, смещённый на 0.3 по X и Y
            # IoU = (9.7 * 9.7) / (10*10 + 10*10 - 9.7*9.7)
            #      = 94.09 / (100 + 100 - 94.09) = 94.09 / 105.91 ≈ 0.889
            # Это < 0.95, нужно меньшее смещение

            # Смещение 0.1: intersection = 9.9*9.9 = 98.01
            # union = 100 + 100 - 98.01 = 101.99
            # IoU = 98.01 / 101.99 ≈ 0.961 > 0.95
            LayerFixtures.add_feature(
                layer, "POLYGON((0.1 0.1, 10.1 0.1, 10.1 10.1, 0.1 10.1, 0.1 0.1))",
                [2, "B_near", 100.0],
            )

            self.logger.data("Features до", str(layer.featureCount()))

            dedup = self.dedup_class(caller_id="TEST")
            removed = dedup.deduplicate_near(layer, iou_threshold=0.95)

            self.logger.check(
                removed == 1,
                "Near-duplicate найден (IoU ~ 0.96)",
                f"Удалено {removed}, ожидалось 1",
            )
            self.logger.check(
                layer.featureCount() == 1,
                "Остался 1 feature",
                f"Осталось {layer.featureCount()}, ожидался 1",
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ------------------------------------------------------------------
    # Test 7: Не-дубликат с перекрытием
    # ------------------------------------------------------------------
    def test_07_non_duplicate_overlap(self):
        """ТЕСТ 7: Пересекающиеся полигоны с IoU < 0.95"""
        self.logger.section("7. Не-дубликат (IoU < 0.95)")

        if not self.dedup_class:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            layer = create_polygon_layer("non_dup_overlap")

            # Два квадрата 10x10 с перекрытием 5x10
            # intersection = 50, union = 100 + 100 - 50 = 150
            # IoU = 50/150 ≈ 0.333 << 0.95
            LayerFixtures.add_feature(
                layer, "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))", [1, "A", 100.0]
            )
            LayerFixtures.add_feature(
                layer, "POLYGON((5 0, 15 0, 15 10, 5 10, 5 0))", [2, "B", 100.0]
            )

            self.logger.data("Features до", str(layer.featureCount()))

            dedup = self.dedup_class(caller_id="TEST")
            removed = dedup.deduplicate_near(layer, iou_threshold=0.95)

            self.logger.check(
                removed == 0,
                "Пересекающиеся полигоны НЕ удалены (IoU ≈ 0.33)",
                f"Удалено {removed}, ожидалось 0!",
            )
            self.logger.check(
                layer.featureCount() == 2,
                "Оба features сохранены",
                f"Осталось {layer.featureCount()}, ожидалось 2",
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ------------------------------------------------------------------
    # Test 8: Line layer (Level 2 skip)
    # ------------------------------------------------------------------
    def test_08_line_layer_skip(self):
        """ТЕСТ 8: Level 2 пропускается для линейных слоёв"""
        self.logger.section("8. Line layer -- Level 2 skip")

        if not self.dedup_class:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            layer = create_line_layer("line_test")

            # Две одинаковые линии
            feature1 = QgsFeature(layer.fields())
            feature1.setGeometry(QgsGeometry.fromWkt("LINESTRING(0 0, 10 10)"))
            feature1.setAttributes([1, "line_A", 14.14])
            layer.dataProvider().addFeature(feature1)

            feature2 = QgsFeature(layer.fields())
            feature2.setGeometry(QgsGeometry.fromWkt("LINESTRING(0 0, 10 10)"))
            feature2.setAttributes([2, "line_B", 14.14])
            layer.dataProvider().addFeature(feature2)

            dedup = self.dedup_class(caller_id="TEST")

            # Level 2 должен вернуть 0 (не полигоны)
            near_removed = dedup.deduplicate_near(layer)
            self.logger.check(
                near_removed == 0,
                "deduplicate_near() = 0 для линейного слоя",
                f"deduplicate_near() = {near_removed} (ошибка!)",
            )

            # Но Level 1 должен найти дубликат
            exact_removed = dedup.deduplicate_exact(layer)
            self.logger.check(
                exact_removed == 1,
                "deduplicate_exact() нашёл 1 дубликат линии",
                f"deduplicate_exact() = {exact_removed}, ожидалось 1",
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ------------------------------------------------------------------
    # Test 9: NULL геометрии
    # ------------------------------------------------------------------
    def test_09_null_geometries(self):
        """ТЕСТ 9: Слой с NULL геометриями"""
        self.logger.section("9. NULL геометрии")

        if not self.dedup_class:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            layer = create_polygon_layer("null_geom_test")

            # 2 валидных полигона (одинаковых = дубликат)
            LayerFixtures.add_feature(
                layer, "POLYGON((0 0, 5 0, 5 5, 0 5, 0 0))", [1, "valid_A", 25.0]
            )
            LayerFixtures.add_feature(
                layer, "POLYGON((0 0, 5 0, 5 5, 0 5, 0 0))", [2, "valid_A_dup", 25.0]
            )

            # 1 уникальный
            LayerFixtures.add_feature(
                layer, "POLYGON((10 0, 15 0, 15 5, 10 5, 10 0))", [3, "valid_B", 25.0]
            )

            # 2 features без геометрии (NULL)
            for i in range(2):
                f = QgsFeature(layer.fields())
                f.setAttributes([10 + i, f"null_{i}", 0.0])
                layer.dataProvider().addFeature(f)

            initial = layer.featureCount()
            self.logger.data("Features до (valid + NULL)", str(initial))

            dedup = self.dedup_class(caller_id="TEST")
            result = dedup.deduplicate(layer)

            self.logger.check(
                result["exact_removed"] == 1,
                "1 exact дубликат найден (NULL пропущены)",
                f"exact_removed = {result['exact_removed']}, ожидалось 1",
            )
            self.logger.check(
                layer.featureCount() == initial - 1,
                f"Осталось {initial - 1} features (включая NULL)",
                f"Осталось {layer.featureCount()}, ожидалось {initial - 1}",
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ------------------------------------------------------------------
    # Test 10: Full pipeline
    # ------------------------------------------------------------------
    def test_10_full_pipeline(self):
        """ТЕСТ 10: Полный pipeline (Level 1 + Level 2)"""
        self.logger.section("10. Полный pipeline deduplicate()")

        if not self.dedup_class:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            layer = create_polygon_layer("full_pipeline")

            # Уникальный полигон
            LayerFixtures.add_feature(
                layer, "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))", [1, "unique", 100.0]
            )

            # Exact дубликат
            LayerFixtures.add_feature(
                layer, "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))", [2, "exact_dup", 100.0]
            )

            # Near-дубликат (смещение 0.05)
            # intersection = 9.95*9.95 = 99.0025
            # union = 100 + 100 - 99.0025 = 100.9975
            # IoU ≈ 0.980
            LayerFixtures.add_feature(
                layer,
                "POLYGON((0.05 0.05, 10.05 0.05, 10.05 10.05, 0.05 10.05, 0.05 0.05))",
                [3, "near_dup", 100.0],
            )

            # Непересекающийся полигон
            LayerFixtures.add_feature(
                layer, "POLYGON((50 50, 60 50, 60 60, 50 60, 50 50))", [4, "distant", 100.0]
            )

            initial = layer.featureCount()
            self.logger.data("Features до", str(initial))

            dedup = self.dedup_class(caller_id="TEST")
            result = dedup.deduplicate(layer)

            self.logger.data("exact_removed", str(result["exact_removed"]))
            self.logger.data("near_removed", str(result["near_removed"]))
            self.logger.data("total_removed", str(result["total_removed"]))
            self.logger.data("remaining", str(result["remaining"]))

            self.logger.check(
                result["exact_removed"] == 1,
                "1 exact дубликат удалён",
                f"exact_removed = {result['exact_removed']}, ожидалось 1",
            )
            self.logger.check(
                result["near_removed"] == 1,
                "1 near-дубликат удалён",
                f"near_removed = {result['near_removed']}, ожидалось 1",
            )
            self.logger.check(
                result["remaining"] == 2,
                "Осталось 2 уникальных features",
                f"remaining = {result['remaining']}, ожидалось 2",
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ------------------------------------------------------------------
    # Test 11: enable_near_duplicates=False
    # ------------------------------------------------------------------
    def test_11_disable_near_duplicates(self):
        """ТЕСТ 11: Флаг enable_near_duplicates=False"""
        self.logger.section("11. enable_near_duplicates=False")

        if not self.dedup_class:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            layer = create_polygon_layer("disable_near")

            # Полигон A
            LayerFixtures.add_feature(
                layer, "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))", [1, "A", 100.0]
            )
            # Near-дубликат A (смещение 0.1, IoU ≈ 0.96)
            LayerFixtures.add_feature(
                layer,
                "POLYGON((0.1 0.1, 10.1 0.1, 10.1 10.1, 0.1 10.1, 0.1 0.1))",
                [2, "A_near", 100.0],
            )

            dedup = self.dedup_class(caller_id="TEST")
            result = dedup.deduplicate(layer, enable_near_duplicates=False)

            self.logger.check(
                result["exact_removed"] == 0,
                "exact_removed = 0 (не точный дубль)",
                f"exact_removed = {result['exact_removed']}",
            )
            self.logger.check(
                result["near_removed"] == 0,
                "near_removed = 0 (Level 2 отключён)",
                f"near_removed = {result['near_removed']}!",
            )
            self.logger.check(
                result["remaining"] == 2,
                "Оба features сохранены",
                f"remaining = {result['remaining']}, ожидалось 2",
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ------------------------------------------------------------------
    # Test 12: Custom IoU threshold
    # ------------------------------------------------------------------
    def test_12_custom_iou_threshold(self):
        """ТЕСТ 12: Custom iou_threshold"""
        self.logger.section("12. Custom iou_threshold")

        if not self.dedup_class:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            # Два полигона с IoU ≈ 0.33 (50% перекрытие по X)
            # intersection = 5*10 = 50
            # union = 100 + 100 - 50 = 150
            # IoU = 50/150 ≈ 0.333

            # --- Низкий threshold: должен ловить ---
            layer_low = create_polygon_layer("threshold_low")
            LayerFixtures.add_feature(
                layer_low, "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))", [1, "A", 100.0]
            )
            LayerFixtures.add_feature(
                layer_low, "POLYGON((5 0, 15 0, 15 10, 5 10, 5 0))", [2, "B", 100.0]
            )

            dedup = self.dedup_class(caller_id="TEST")
            removed_low = dedup.deduplicate_near(layer_low, iou_threshold=0.3)

            self.logger.check(
                removed_low == 1,
                "threshold=0.3: IoU 0.33 >= 0.3, дубликат найден",
                f"Удалено {removed_low}, ожидалось 1",
            )

            # --- Высокий threshold: не должен ловить ---
            layer_high = create_polygon_layer("threshold_high")
            LayerFixtures.add_feature(
                layer_high, "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))", [1, "A", 100.0]
            )
            LayerFixtures.add_feature(
                layer_high, "POLYGON((5 0, 15 0, 15 10, 5 10, 5 0))", [2, "B", 100.0]
            )

            removed_high = dedup.deduplicate_near(layer_high, iou_threshold=0.99)

            self.logger.check(
                removed_high == 0,
                "threshold=0.99: IoU 0.33 < 0.99, дубликат НЕ найден",
                f"Удалено {removed_high}, ожидалось 0",
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ------------------------------------------------------------------
    # Test 13: Invalid geometry в IoU (adversarial review OPT-1)
    # ------------------------------------------------------------------
    def test_13_invalid_geometry_iou(self):
        """ТЕСТ 13: Invalid/self-intersecting geometry в IoU loop"""
        self.logger.section("13. Invalid geometry в IoU")

        if not self.dedup_class:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            layer = create_polygon_layer("invalid_iou")

            # Валидный полигон
            LayerFixtures.add_feature(
                layer, "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))", [1, "valid", 100.0]
            )
            # Self-intersecting (bowtie) полигон -- пересекает bbox валидного
            LayerFixtures.add_feature(
                layer, "POLYGON((5 0, 15 10, 15 0, 5 10, 5 0))", [2, "bowtie", 0.0]
            )
            # Ещё один валидный, не пересекается
            LayerFixtures.add_feature(
                layer, "POLYGON((50 50, 60 50, 60 60, 50 60, 50 50))", [3, "far", 100.0]
            )

            initial = layer.featureCount()
            self.logger.data("Features до", str(initial))

            dedup = self.dedup_class(caller_id="TEST")
            # Не должен упасть даже с невалидной геометрией
            removed = dedup.deduplicate_near(layer, iou_threshold=0.95)

            self.logger.check(
                layer.featureCount() >= 2,
                f"Слой не разрушен ({layer.featureCount()} features)",
                f"Слой разрушен! Осталось {layer.featureCount()}",
            )
            self.logger.success(
                f"IoU с invalid geometry завершился корректно (removed={removed})"
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())

    # ------------------------------------------------------------------
    # Test 14: MultiPolygon dedup (adversarial review OPT-2)
    # ------------------------------------------------------------------
    def test_14_multipolygon_dedup(self):
        """ТЕСТ 14: Дедупликация MultiPolygon геометрий"""
        self.logger.section("14. MultiPolygon dedup")

        if not self.dedup_class:
            self.logger.fail("Модуль не инициализирован")
            return

        try:
            # MultiPolygon слой (как в реальных WFS данных)
            layer = QgsVectorLayer(
                "MultiPolygon?crs=EPSG:4326"
                "&field=id:integer&field=name:string&field=area:double",
                "multi_test",
                "memory",
            )

            mp_wkt = (
                "MULTIPOLYGON(((0 0, 5 0, 5 5, 0 5, 0 0)),"
                "((10 10, 15 10, 15 15, 10 15, 10 10)))"
            )

            # Оригинал
            f1 = QgsFeature(layer.fields())
            f1.setGeometry(QgsGeometry.fromWkt(mp_wkt))
            f1.setAttributes([1, "mp_orig", 50.0])
            layer.dataProvider().addFeature(f1)

            # Точный дубликат MultiPolygon
            f2 = QgsFeature(layer.fields())
            f2.setGeometry(QgsGeometry.fromWkt(mp_wkt))
            f2.setAttributes([2, "mp_dup", 50.0])
            layer.dataProvider().addFeature(f2)

            # Уникальный MultiPolygon
            f3 = QgsFeature(layer.fields())
            f3.setGeometry(QgsGeometry.fromWkt(
                "MULTIPOLYGON(((20 20, 25 20, 25 25, 20 25, 20 20)))"
            ))
            f3.setAttributes([3, "mp_unique", 25.0])
            layer.dataProvider().addFeature(f3)

            initial = layer.featureCount()
            self.logger.data("Features до", str(initial))

            dedup = self.dedup_class(caller_id="TEST")
            result = dedup.deduplicate(layer)

            self.logger.check(
                result["exact_removed"] == 1,
                "1 MultiPolygon exact дубликат удалён",
                f"exact_removed = {result['exact_removed']}, ожидалось 1",
            )
            self.logger.check(
                result["remaining"] == 2,
                "Осталось 2 уникальных MultiPolygon",
                f"remaining = {result['remaining']}, ожидалось 2",
            )

        except Exception as e:
            self.logger.error(f"Ошибка: {str(e)}")
            import traceback
            self.logger.data("Traceback", traceback.format_exc())
