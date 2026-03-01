# Prosecutor Rebuttal: Fsm_1_2_16_deduplicator + callers

**Scope:** Rebuttal to Defender report on Fsm_1_2_16, Fsm_1_2_15, Fsm_1_2_11, Fsm_1_2_14
**Date:** 2026-03-01 17:30

---

## ISSUE-001: `_delete_features` ignores return values

**Verdict: ACCEPT defense.**

The Defender's convention argument is substantiated. I confirmed `Fsm_1_2_1_egrn_loader.py:1363-1365`, `Fsm_1_2_13_4_geometry_processor.py:177-179`, and `Fsm_1_2_13_3_selection_engine.py:936-937` all follow the identical pattern of unchecked `deleteFeatures()` + `commitChanges()` on memory layers. The `_delete_features` method does check `startEditing()` (line 229) and wraps the whole block in a try/except with `rollBack()` (lines 237-240), which is more defensive than most callers in the codebase. The returned count will be wrong only if the internal delete silently fails on a memory layer, which is not a realistic scenario.

No rebuttal. Defense accepted.

---

## ISSUE-002: Bare `except Exception: continue` without logging

**Verdict: REBUTTAL SUSTAINED -- defense concedes.**

The Defender rated their own defense WEAK (0.40) and agreed. I confirm the code at line 207-208:

```python
except Exception:
    continue
```

This sits inside the IoU computation loop (`deduplicate_near`, lines 192-208). The `intersection()` and `area()` calls on QGIS geometries can raise GEOSException for invalid/corrupt geometries. Silently swallowing these means:

1. **No visibility into data quality.** If 50% of candidate pairs throw exceptions, the operator sees only "0 near-duplicates removed" with no indication that the IoU analysis was effectively skipped for those pairs.
2. **Violates project standard.** CLAUDE.md explicitly requires `log_info`/`log_error` with MODULE_ID prefix. The `except` block produces zero log output.
3. **Trivial fix with zero risk.** Add a counter + a single `log_warning` after the loop: `log_warning(f"{self.caller_id}: {error_count} IoU computation errors skipped")`. This does not change behavior, only adds observability.

**Confidence: 0.90.** Both parties agree. This is a confirmed defect.

---

## ISSUE-003: Stale docstring in Fsm_1_2_15

**Verdict: REBUTTAL SUSTAINED -- defense concedes.**

The Defender rated WEAK (0.30) and agreed. I confirm the docstring at `Fsm_1_2_15_oopt_loader.py` lines 9-10:

```
Содержит логику дедупликации по точному совпадению геометрий (WKB),
применяемую ко всему слою Le_1_2_5_21 после объединения всех источников.
```

The class `Fsm_1_2_15_OoptLoader` contains zero deduplication logic. It is a thin loader that calls `egrn_loader.load_layer_by_endpoint()` and returns. Deduplication was extracted to `Fsm_1_2_16_Deduplicator` and is invoked by the parent orchestrator (`Fsm_1_2_9_zouit_loader`), not by this file. The docstring is factually incorrect.

**Confidence: 0.95.** Trivial but confirmed.

---

## ISSUE-004: Non-deterministic attribute preservation in exact dedup

**Verdict: ACCEPT defense with caveat.**

The Defender argues that the deduplicator is geometry-only by design, and that EGRN data loads first (lower FIDs, preserved). I verified:

- `deduplicate_exact` at line 109: `for feature in layer.getFeatures()` -- iterates in FID order.
- Lines 118-121: first-seen WKB is kept, later duplicates are appended to `duplicate_ids`.
- Callers (`Fsm_1_2_11` line 132, `Fsm_1_2_14` line 347): the base/first layer in `loaded_layers` comes from the endpoint with the most fields (Fsm_1_2_11) or the first endpoint (Fsm_1_2_14).

The behavior is deterministic for a given endpoint ordering and layer construction. The Defender's design argument is reasonable -- coupling attribute-awareness into a geometry deduplicator would violate single-responsibility.

However, the **caveat** remains: the documentation (`Fsm_1_2_16_deduplicator.md` line 32) says "first encountered feature is preserved" but does not document that this means lower FID wins, or that FID ordering depends on layer construction order. This is an implicit contract. If a future developer changes the order of `loaded_layers` construction, richer attributes could be silently lost. A one-line documentation note would eliminate this risk entirely.

**Downgraded to Medium. Confidence: 0.60.** Not a blocking issue, but a documentation gap.

---

## ISSUE-005: Same non-determinism in near-duplicate selection

**Verdict: ACCEPT defense.**

The Defender's argument about `fid_b > fid_a` being standard computational geometry practice is correct. At line 183: `if fid_b <= fid_a or fid_b in duplicate_ids: continue` -- this ensures the higher FID is always the one marked for deletion. Combined with line 167: `checked_fids = sorted(features_cache.keys())`, the behavior is fully deterministic for any given layer state.

The same caveat from ISSUE-004 applies (implicit FID-ordering contract), but since near-duplicates across different WFS sources are genuinely rare (same object with sub-5% geometric deviation from different APIs), the practical impact is negligible.

No rebuttal. Defense accepted.

---

## ISSUE-006: Test coverage gaps

**Verdict: PARTIAL REBUTTAL.**

The Defender conceded two gaps (invalid geometries in IoU, MultiPolygon). I verified the test file (`Fsm_4_2_T_1_2_16.py`). The 12 tests cover:

- Empty layer (test_02)
- No duplicates (test_03)
- Exact duplicates (test_04)
- normalize() effect (test_05)
- Near-duplicates IoU (test_06)
- Non-duplicate overlap (test_07)
- Line layer skip (test_08)
- NULL geometries (test_09)
- Full pipeline (test_10)
- Disable near-duplicates flag (test_11)
- Custom IoU threshold (test_12)

**What is missing and matters:**

1. **Invalid/corrupt geometry in IoU loop.** This directly relates to ISSUE-002. The bare `except` catches errors from `geom_a.intersection(geom_b)` on malformed geometries, but there is no test proving the code handles this gracefully rather than crashing. A test with a self-intersecting or degenerate polygon would verify the error path.

2. **MultiPolygon handling.** The code at line 163 does `features_cache[fid] = QgsGeometry(feature.geometry())` -- it caches the geometry as-is. For MultiPolygon, `area()` returns total area and `intersection()` works correctly. However, there is no test confirming this. WFS endpoints frequently return MultiPolygon for features with disjoint parts (e.g., an OOPT split by a road). This is a real-world scenario, not theoretical.

The Defender's argument that `_delete_features` failure is "untestable on memory layers" is correct -- memory providers always succeed for valid FIDs. The argument that "multi-source attributes belong in loader tests" is also correct -- the deduplicator intentionally ignores attributes.

**Rebuttal sustained for 2 of 4 originally claimed gaps. Confidence: 0.75.**

---

## Summary

| Issue | Original Severity | Rebuttal Verdict | Final Status |
|-------|------------------|-----------------|--------------|
| ISSUE-001 | High | ACCEPT defense | Dismissed |
| ISSUE-002 | High | SUSTAINED (conceded) | **FIX_REQUIRED** |
| ISSUE-003 | Medium | SUSTAINED (conceded) | **FIX_REQUIRED** |
| ISSUE-004 | High | ACCEPT with caveat | Downgraded to doc note |
| ISSUE-005 | Medium | ACCEPT defense | Dismissed |
| ISSUE-006 | Medium | PARTIAL REBUTTAL | 2 gaps remain |

**Remaining actionable items after rebuttal:**

| # | Action | Effort |
|---|--------|--------|
| 1 | Add `log_warning` with counter to `except` block in `deduplicate_near` (line 207-208) | 5 min |
| 2 | Fix stale docstring in `Fsm_1_2_15_oopt_loader.py` (lines 9-10) | 2 min |
| 3 | Add test for invalid/corrupt geometry in IoU loop | 15 min |
| 4 | Add test for MultiPolygon deduplication | 15 min |

**Final Verdict: FIX_REQUIRED** (2 confirmed defects + 2 test gaps, no blockers)
