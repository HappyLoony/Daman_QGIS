# Fix Summary

**Date:** 2026-03-01 20:30
**Status:** FIX_REQUIRED

## Critical Fixes

### FIX-1: Add diagnostic logging to bare except in IoU loop

**Location:** `tools/F_1_data/submodules/Fsm_1_2_16_deduplicator.py:192-208`

**Current:**
```python
            # IoU
            try:
                intersection = geom_a.intersection(geom_b)
                if intersection.isEmpty():
                    continue
                intersection_area = intersection.area()
                if intersection_area <= 0:
                    continue

                union_area = area_a + area_b - intersection_area
                if union_area <= 0:
                    continue

                iou = intersection_area / union_area
                if iou >= iou_threshold:
                    duplicate_ids.add(fid_b)
            except Exception:
                continue
```

**Required:**
```python
            # IoU
            try:
                intersection = geom_a.intersection(geom_b)
                if intersection.isEmpty():
                    continue
                intersection_area = intersection.area()
                if intersection_area <= 0:
                    continue

                union_area = area_a + area_b - intersection_area
                if union_area <= 0:
                    continue

                iou = intersection_area / union_area
                if iou >= iou_threshold:
                    duplicate_ids.add(fid_b)
            except Exception:
                iou_error_count += 1
                continue
```

Additionally, declare the counter before the loop (after line 167) and log a summary after the loop (before line 210):

**Before the `for fid_a in checked_fids:` loop (after line 167):**
```python
        iou_error_count = 0
```

**After the loop ends, before `if not duplicate_ids:` (before line 210):**
```python
        if iou_error_count > 0:
            log_warning(
                f"{self.caller_id}: {iou_error_count} IoU computation errors skipped "
                f"(invalid geometries)"
            )
```

**Why:** The bare except violates the project's logging standards (CLAUDE.md requires MODULE_ID-prefixed logging for all except handlers). Without this, Level 2 silently becomes a no-op on layers with invalid geometries, with zero diagnostic output.

---

### FIX-2: Update stale docstring in Fsm_1_2_15_oopt_loader.py

**Location:** `tools/F_1_data/submodules/Fsm_1_2_15_oopt_loader.py:2-11`

**Current:**
```python
"""
Субмодуль F_1_2: Загрузка ООПТ Минприроды (category_id=36507)

Отдельный загрузчик для endpoint 31 (ООПТ Минприроды).
Данные объединяются в Le_1_2_5_21_WFS_ЗОУИТ_ОЗ_ООПТ вместе с другими
источниками (36940 classified + 36948 OOPT).

Содержит логику дедупликации по точному совпадению геометрий (WKB),
применяемую ко всему слою Le_1_2_5_21 после объединения всех источников.
"""
```

**Required:**
```python
"""
Субмодуль F_1_2: Загрузка ООПТ Минприроды (category_id=36507)

Отдельный загрузчик для endpoint 31 (ООПТ Минприроды).
Данные объединяются в Le_1_2_5_21_WFS_ЗОУИТ_ОЗ_ООПТ вместе с другими
источниками (36940 classified + 36948 OOPT).

Дедупликация выполняется через Fsm_1_2_16_Deduplicator в Fsm_1_2_9_zouit_loader.
"""
```

**Why:** The docstring claims deduplication logic resides in this file, but the class contains zero deduplication code. The logic was extracted to Fsm_1_2_16. The Markdown documentation (Fsm_1_2_15_oopt_loader.md) is already correct; only the Python docstring needs updating.

---

## Optional Improvements

### OPT-1: Add test for invalid/self-intersecting geometry in IoU loop

**Location:** `tools/F_4_plagin/submodules/Fsm_4_2_T_comprehensive_runner/Fsm_4_2_T_1_2_16.py` (new test_13)

**Suggested test:**
```python
def test_13_invalid_geometry_iou(self):
    """ТЕСТ 13: Invalid/self-intersecting geometry in IoU loop"""
    self.logger.section("13. Invalid geometry (Level 2 resilience)")

    if not self.dedup_class:
        self.logger.fail("Модуль не инициализирован")
        return

    try:
        layer = create_polygon_layer("invalid_geom_test")

        # Valid polygon
        LayerFixtures.add_feature(
            layer, "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))", [1, "valid", 100.0]
        )
        # Self-intersecting (bowtie) polygon overlapping with the first
        LayerFixtures.add_feature(
            layer, "POLYGON((1 1, 9 9, 9 1, 1 9, 1 1))", [2, "bowtie", 0.0]
        )
        # Another valid polygon (near-duplicate of first, shifted by 0.1)
        LayerFixtures.add_feature(
            layer,
            "POLYGON((0.1 0.1, 10.1 0.1, 10.1 10.1, 0.1 10.1, 0.1 0.1))",
            [3, "near_dup", 100.0],
        )

        initial = layer.featureCount()
        self.logger.data("Features до", str(initial))

        dedup = self.dedup_class(caller_id="TEST")
        # Should not crash; should handle the bowtie gracefully
        removed = dedup.deduplicate_near(layer, iou_threshold=0.95)

        self.logger.check(
            layer.featureCount() <= initial,
            f"Не упал при invalid geometry (removed={removed})",
            "Crash при обработке invalid geometry!",
        )
        self.logger.check(
            removed >= 1,
            f"Near-duplicate найден несмотря на invalid geometry (removed={removed})",
            f"Near-duplicate пропущен (removed={removed})",
        )

    except Exception as e:
        self.logger.error(f"Ошибка: {str(e)}")
        import traceback
        self.logger.data("Traceback", traceback.format_exc())
```

**Why:** Verifies that the try/except in the IoU loop (FIX-1) correctly handles GEOS topology exceptions from invalid geometries without crashing or aborting the entire Level 2 pass.

---

### OPT-2: Add test for MultiPolygon deduplication

**Location:** `tools/F_4_plagin/submodules/Fsm_4_2_T_comprehensive_runner/Fsm_4_2_T_1_2_16.py` (new test_14)

**Suggested test:**
```python
def test_14_multipolygon_dedup(self):
    """ТЕСТ 14: MultiPolygon exact and near deduplication"""
    self.logger.section("14. MultiPolygon deduplication")

    if not self.dedup_class:
        self.logger.fail("Модуль не инициализирован")
        return

    try:
        layer = create_polygon_layer("multipolygon_test")

        # MultiPolygon with two disjoint parts
        mp_wkt = "MULTIPOLYGON(((0 0, 5 0, 5 5, 0 5, 0 0)),((10 10, 15 10, 15 15, 10 15, 10 10)))"
        LayerFixtures.add_feature(layer, mp_wkt, [1, "mp_A", 50.0])
        # Exact duplicate
        LayerFixtures.add_feature(layer, mp_wkt, [2, "mp_A_dup", 50.0])

        self.logger.data("Features до", str(layer.featureCount()))

        dedup = self.dedup_class(caller_id="TEST")

        # Level 1: exact duplicate
        exact_removed = dedup.deduplicate_exact(layer)
        self.logger.check(
            exact_removed == 1,
            "MultiPolygon exact duplicate найден",
            f"exact_removed = {exact_removed}, ожидалось 1",
        )

        # Add near-duplicate MultiPolygon (shifted by 0.1)
        mp_shifted = "MULTIPOLYGON(((0.1 0.1, 5.1 0.1, 5.1 5.1, 0.1 5.1, 0.1 0.1)),((10.1 10.1, 15.1 10.1, 15.1 15.1, 10.1 15.1, 10.1 10.1)))"
        LayerFixtures.add_feature(layer, mp_shifted, [3, "mp_near", 50.0])

        before_near = layer.featureCount()
        near_removed = dedup.deduplicate_near(layer, iou_threshold=0.95)
        self.logger.check(
            near_removed == 1,
            "MultiPolygon near-duplicate найден",
            f"near_removed = {near_removed}, ожидалось 1",
        )

    except Exception as e:
        self.logger.error(f"Ошибка: {str(e)}")
        import traceback
        self.logger.data("Traceback", traceback.format_exc())
```

**Why:** WFS endpoints frequently return MultiPolygon features (e.g., OOPT split by a road). While QGIS `area()` and `intersection()` handle MultiPolygon correctly, this is not verified by the existing test suite.

---

## Do Not Change

| Decision | Location | Reason |
|----------|----------|--------|
| Unchecked `deleteFeatures()`/`commitChanges()` return values | `Fsm_1_2_16_deduplicator.py:233-234` | Consistent with 88% of codebase; memory-layer context makes failure unrealistic; try/except already handles exceptions |
| First-seen-wins attribute preservation | `Fsm_1_2_16_deduplicator.py:109-121` | Geometry-only scope by design (SRP); three callers with different field strategies; behavior is deterministic per endpoint config |
| FID-based near-duplicate selection (lower FID wins) | `Fsm_1_2_16_deduplicator.py:183, 206` | Standard computational geometry pairwise comparison; consistent with Level 1 behavior |

## Execution Order

1. FIX-1: Add IoU error counter and log_warning (independent)
2. FIX-2: Update Fsm_1_2_15 docstring (independent)
3. OPT-1: Add test_13 for invalid geometry (after FIX-1, to test the new logging path)
4. OPT-2: Add test_14 for MultiPolygon (independent)

FIX-1 and FIX-2 are independent and can be applied in any order. OPT-1 should be written after FIX-1 to verify the error counter behavior. OPT-2 is independent of all other changes.
