# Judge Verdict

**Date:** 2026-03-01 20:30
**Prosecutor:** prosecutor_report.md
**Defender:** defender_report.md

## Verdict Matrix

| Issue | P.Conf | D.Conf | Verdict | Reason |
|-------|--------|--------|---------|--------|
| ISSUE-001 | 0.90 | 0.75 | DEFENDER | Codebase convention confirmed (5/43 checked); memory-layer context valid; try/except already present |
| ISSUE-002 | 0.85 | 0.40 | PROSECUTOR | Both sides agree; bare except violates project standards; logging forgotten |
| ISSUE-003 | 0.95 | 0.30 | PROSECUTOR | Both sides agree; docstring factually incorrect |
| ISSUE-004 | 0.80 | 0.70 | DEFENDER | Geometry-only scope is valid SRP; behavior is deterministic per endpoint config; add doc note |
| ISSUE-005 | 0.75 | 0.65 | DEFENDER | Standard pairwise comparison; deterministic via sorted FIDs; practical impact negligible |
| ISSUE-006 | 0.90 | 0.45 | PARTIAL | 2 of 4 gaps confirmed (invalid geometry, MultiPolygon); 2 rebutted (memory-layer delete, multi-source attrs) |

## Detailed Analysis

### ISSUE-001: `_delete_features` unchecked return values

**Prosecutor (Conf: 0.90):** `deleteFeatures()` and `commitChanges()` return booleans that are ignored; reported count may be wrong if they fail silently.
**Defender (Conf: 0.75):** Dominant codebase convention (79% unchecked); memory layers with freshly-iterated FIDs cannot realistically fail; try/except + rollBack already handles exception-class failures.

**Independent Verification:**
- Checked: Ran a count of `commitChanges()` calls vs `if.*commitChanges()` calls across `tools/`.
- Found: 43 total `commitChanges()` calls in 23 files. Only 5 calls (in 3 files) check the return value. The unchecked pattern represents ~88% of usage. The files that DO check are `Fsm_0_6_3_transform_applicator.py`, `Fsm_1_1_3_coordinate_input.py`, and `Fsm_2_2_2_transfer.py` -- all operating on GeoPackage-backed layers where I/O failure is realistic.
- Found: The `_delete_features` method at lines 228-240 does check `startEditing()` (line 229) and wraps the entire block in try/except with `log_error` + `rollBack()`. This is more defensive than many callers in the codebase.
- Found: The deduplicator operates exclusively on in-memory layers (confirmed by checking callers in Fsm_1_2_9 line 150, Fsm_1_2_11, Fsm_1_2_14). Memory provider `deleteFeatures()` with valid FIDs obtained from `getFeatures()` in the same method will not fail in practice.

**Verdict: DEFENDER**
The codebase convention is real and the operational context (memory layers, valid FIDs) makes failure unrealistic. The existing try/except block provides adequate safety. While checking return values would be technically more correct, this is not a defect requiring a fix -- it is consistent with the project's established patterns and appropriate for the risk profile.

---

### ISSUE-002: Bare `except Exception: continue` without logging

**Prosecutor (Conf: 0.85):** Silent exception swallowing makes Level 2 failures invisible; violates project logging standards.
**Defender (Conf: 0.40):** Intent was crash prevention for GEOS topology errors; logging was simply forgotten.

**Independent Verification:**
- Checked: Lines 207-208 of `Fsm_1_2_16_deduplicator.py`.
- Found: `except Exception: continue` with zero diagnostic output. The module imports `log_warning` (line 21) but does not use it here.
- Checked: CLAUDE.md mandates `log_info`/`log_error` with MODULE_ID prefix and prohibits silent exception handling.
- Found: The code handles the IoU computation block (lines 192-208) which calls `intersection()`, `area()` -- both of which can raise GEOS topology exceptions on invalid WFS geometries. If all candidate pairs fail, the method silently returns 0 near-duplicates with no indication that errors occurred.

**Verdict: PROSECUTOR**
Both parties agree this is a defect. The try/except intent is correct (crash prevention), but the missing logging violates project standards and eliminates diagnostic visibility. A counter + summary log_warning is the minimal correct fix.

---

### ISSUE-003: Stale docstring in Fsm_1_2_15

**Prosecutor (Conf: 0.95):** Docstring claims deduplication logic is in this file; the file contains zero deduplication code.
**Defender (Conf: 0.30):** No defense; confirmed stale.

**Independent Verification:**
- Checked: Lines 9-10 of `Fsm_1_2_15_oopt_loader.py`.
- Found: "Содержит логику дедупликации по точному совпадению геометрий (WKB), применяемую ко всему слою Le_1_2_5_21 после объединения всех источников."
- Checked: The class `Fsm_1_2_15_OoptLoader` has exactly two methods: `load_oopt_minprirody()` and `_find_endpoint()`. Neither contains deduplication logic.
- Checked: The Markdown documentation (`Fsm_1_2_15_oopt_loader.md` line 46) correctly states: "Дедупликация: выполняется через Fsm_1_2_16_deduplicator в Fsm_1_2_9."
- Checked: The actual deduplication call is in `Fsm_1_2_9_zouit_loader.py` at lines 148-153.

**Verdict: PROSECUTOR**
The Python docstring is factually incorrect. The Markdown documentation is accurate. This is a leftover from the extraction of deduplication logic into Fsm_1_2_16. Trivial fix.

---

### ISSUE-004: Non-deterministic attribute preservation (exact dedup)

**Prosecutor (Conf: 0.80):** First-encountered feature is kept; the "winner" depends on insertion order which is implicitly tied to endpoint loading order.
**Defender (Conf: 0.70):** Geometry-only by design; attribute selection is caller responsibility; adding attribute-awareness would violate SRP.

**Independent Verification:**
- Checked: `deduplicate_exact` lines 109-121. The first feature with a given WKB hash is preserved; subsequent features with the same hash are marked for deletion.
- Checked: `Fsm_1_2_16_deduplicator.md` line 32: "Первый встреченный feature сохраняется."
- Found: The deduplicator has zero imports from attribute-related modules, zero field references, zero `_source` awareness. Its API is purely geometric.
- Checked: The Defender's SRP argument is sound. Three different callers use this module (Fsm_1_2_11, Fsm_1_2_14, Fsm_1_2_9), each with different field strategies (MAX fields, UNION fields, homogeneous fields). A generic "richness" heuristic would be fragile and caller-specific.
- Found: The behavior IS deterministic for a given endpoint configuration -- it depends on insertion order, which depends on endpoint declaration order in `Base_api_endpoints.json`. The Prosecutor's characterization of "non-deterministic" is imprecise; it is better described as "implicit."

**Verdict: DEFENDER**
The geometry-only scope is a legitimate design decision consistent with SRP. The behavior is deterministic (not random) for a given configuration. The Rebuttal's suggestion of a one-line documentation note about "first-encountered feature wins, determined by insertion order" is reasonable but optional, not a required fix.

---

### ISSUE-005: Near-duplicate FID-based selection

**Prosecutor (Conf: 0.75):** Higher-FID feature is always discarded regardless of attribute quality.
**Defender (Conf: 0.65):** Standard computational geometry pairwise comparison; `sorted(features_cache.keys())` + `fid_b > fid_a` ensures deterministic behavior.

**Independent Verification:**
- Checked: Lines 167-206. `checked_fids = sorted(features_cache.keys())` followed by the constraint `if fid_b <= fid_a or fid_b in duplicate_ids: continue` at line 183.
- Found: This is the standard approach for avoiding redundant pairwise checks in computational geometry (process each unordered pair exactly once). The lower-FID feature is retained, which is consistent with Level 1 behavior.
- Found: Near-duplicates from DIFFERENT WFS endpoints (same object with sub-5% geometric difference) are genuinely rare compared to same-endpoint duplicates.

**Verdict: DEFENDER**
Standard algorithm. Consistent with Level 1 behavior. Practical impact is negligible for the near-duplicate case.

---

### ISSUE-006: Test coverage gaps

**Prosecutor (Conf: 0.90):** Four gaps: (1) _delete_features failure, (2) multi-source attributes, (3) invalid geometry in IoU, (4) MultiPolygon dedup.
**Defender (Conf: 0.45):** Two legitimate (#3, #4), two not applicable (#1 untestable on memory layers, #2 belongs to loader tests).

**Independent Verification:**
- Checked: All 12 tests in `Fsm_4_2_T_1_2_16.py`. Test geometries are all simple valid polygons (squares) constructed from WKT. No test uses `MULTIPOLYGON` or self-intersecting geometry.
- Found: Gap #1 (_delete_features failure) -- Defender is correct that provoking a failure on memory layers with valid FIDs requires mocking, and the value is low since the failure path already has try/except + rollBack.
- Found: Gap #2 (multi-source attributes) -- Defender is correct that this is the caller's concern. The deduplicator's contract is geometry deduplication.
- Found: Gap #3 (invalid geometry in IoU) -- Legitimate gap. The bare except at line 207 is the error path for GEOS exceptions. Testing with a self-intersecting polygon (e.g., bowtie) would verify the code does not crash and returns the correct count minus the skipped pair.
- Found: Gap #4 (MultiPolygon) -- Legitimate gap. WFS data commonly returns MultiPolygon features. While `area()` and `intersection()` work on MultiPolygon in QGIS, there is no test confirming this for the deduplicator.

**Verdict: PARTIAL**
Two of four gaps are confirmed and should be addressed (invalid geometry, MultiPolygon). The other two are correctly dismissed.

---

## Score

| Side | Wins | Partial |
|------|------|---------|
| Prosecutor | 2 | 1 |
| Defender | 3 | 0 |

## Final Verdict: FIX_REQUIRED

The deduplicator module (`Fsm_1_2_16_Deduplicator`) is well-structured with clean separation of concerns and correct algorithmic design. The core architecture is sound and the Defender successfully defended the main design decisions (geometry-only scope, memory-layer assumptions, first-seen-wins strategy).

However, two confirmed defects require fixes before the module meets the project's own coding standards:

1. **ISSUE-002:** The bare `except Exception: continue` at line 207-208 must include diagnostic logging. This is a violation of CLAUDE.md logging requirements and eliminates diagnostic visibility for Level 2 failures on real WFS data.

2. **ISSUE-003:** The stale docstring in `Fsm_1_2_15_oopt_loader.py` lines 9-10 must be corrected. It claims deduplication logic resides in a file that contains none.

Additionally, two test gaps (ISSUE-006) should be addressed to ensure edge-case coverage:

3. A test for invalid/self-intersecting geometry in the IoU loop.
4. A test for MultiPolygon deduplication.

All four items are low-risk, low-effort changes (estimated total: ~30 minutes). No architectural changes are needed.
