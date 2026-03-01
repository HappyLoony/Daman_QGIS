# Defender Report

**Prosecutor report:** prosecutor_report.md
**Date:** 2026-03-01 19:30

## User Context

**Questions:**
1. Runtime version: -> QGIS 3.40 LTR, Python 3.9+ (confirmed current)
2. Project stage: -> Initial/MVP implementation, just created. NOT production-iterated.
3. Constraints: -> Extracted from inline `deduplicate_by_geometry()` in Fsm_1_2_15, made universal. Added normalize() and IoU as improvements over original WKB-only approach.

**Per-issue answers:**
4. ISSUE-001: Memory layers -- `commitChanges()` should not fail on valid operations. Matches dominant codebase pattern (50/63 calls unchecked). Conscious decision for memory layers.
5. ISSUE-002: Bare except was intentional crash prevention for GEOS topology errors, but logging was forgotten. Should have at least `log_warning`.
6. ISSUE-004/005: Geometry-only by design. Attribute selection is the caller's responsibility. EGRN endpoints load first (richer data), so in practice richer attributes ARE preserved -- but this is implicit, not guaranteed.

## Defense by Issue

### ISSUE-001: `_delete_features` Does Not Verify `deleteFeatures()` or `commitChanges()` Return Values
- **P.Confidence:** 0.9
- **D.Confidence:** 0.75
- **Claim:** The unchecked return values follow the dominant codebase convention and are appropriate for the operational context (memory layers with valid FIDs).
- **Evidence:**
  - Codebase analysis: 63 total `commitChanges()` calls across 37 files. Only 13 calls (in 10 files) check the return value. The remaining 50 calls (in 27 files) use the same fire-and-forget pattern as `Fsm_1_2_16`. This is the established project convention, not an oversight.
  - The same unchecked pattern appears in the directly analogous deduplication code in `Fsm_1_2_1_egrn_loader.py:1363-1365`:
    ```python
    layer.startEditing()
    layer.deleteFeatures(duplicate_ids)
    layer.commitChanges()
    return len(duplicate_ids)
    ```
  - Also appears in `Fsm_1_2_3_quickosm_loader.py:937-941` and `Fsm_1_2_9_zouit_loader.py:91-94` (the callers themselves).
  - The deduplicator operates exclusively on in-memory layers (`"memory"` provider), created moments earlier by the caller (`_create_merged_layer`). Memory provider `deleteFeatures()` fails only if the FID does not exist in the layer. Since FIDs are obtained from `layer.getFeatures()` iteration in the same method, the FIDs are guaranteed valid.
  - The `_delete_features` method DOES have a try/except block (lines 237-240) with `log_error()` and `layer.rollBack()` for exception-type failures.
  - The modules that DO check `commitChanges()` return values operate on GeoPackage-backed layers (e.g., `Fsm_0_6_3_transform_applicator`, `M_6_coordinate_precision`, `Msm_23_3_cutting_sync`), where I/O failures are possible. The distinction between memory-layer and disk-layer error handling is a valid architectural boundary.
- **Trade-off:** Gained: simpler code consistent with 79% of the codebase's `commitChanges()` calls. Lost: explicit detection of an edge case that is practically unreachable on memory layers with freshly-iterated FIDs.
- **Verdict:** DEFENDED

### ISSUE-002: Bare `except Exception` Silently Swallows Geometry Computation Errors in IoU Loop
- **P.Confidence:** 0.85
- **D.Confidence:** 0.40
- **Claim:** The try/except was a conscious decision to prevent GEOS topology crashes from halting WFS data loading, but the user confirms logging was simply forgotten.
- **Evidence:**
  - User confirmed: "The bare except was to avoid crashes from GEOS topology errors on real WFS data, but logging was forgotten. Should have at least `log_warning` for debugging."
  - The defensive intent is correct: `QgsGeometry.intersection()` can throw GEOS exceptions on self-intersecting or otherwise invalid geometries from WFS sources. Without a try/except, a single bad geometry pair would abort the entire Level 2 deduplication pass.
  - However, the project standards in CLAUDE.md mandate `log_error()`/`log_warning()` with MODULE_ID prefix for all except handlers. The imports are present (line 21: `from Daman_QGIS.utils import log_info, log_warning, log_error`) but unused in this handler.
  - The Prosecutor is correct that a counter or first-occurrence warning would solve the diagnostic gap without flooding logs.
- **Trade-off:** Gained: crash resilience for invalid WFS geometries. Lost: diagnostic visibility when Level 2 silently skips pairs.
- **Verdict:** WEAK

### ISSUE-003: Stale Docstring in `Fsm_1_2_15_oopt_loader.py` Claims It Contains Deduplication Logic
- **P.Confidence:** 0.95
- **D.Confidence:** 0.30
- **Claim:** The docstring is stale. No defense.
- **Evidence:**
  - The Python file docstring (lines 9-10) says "Contains deduplication logic by exact WKB match" but the class has zero deduplication code.
  - The official Markdown documentation (`documentation/doc_submodules/Fsm_1_2_15_oopt_loader.md`) is correct and states: "Deduplication is performed via Fsm_1_2_16_deduplicator in Fsm_1_2_9." The `.md` documentation was updated when dedup was extracted; the `.py` docstring was not.
  - This is a straightforward leftover from the extraction of dedup logic into Fsm_1_2_16. The user confirmed the module was extracted from inline code in Fsm_1_2_15.
  - Note: the `.md` documentation (the project's "source of truth" per CLAUDE.md) IS correct. The discrepancy is only in the Python file's module-level docstring.
- **Trade-off:** None. This is simply a missed update during extraction.
- **Verdict:** WEAK

### ISSUE-004: Non-Deterministic Attribute Preservation During Exact Dedup
- **P.Confidence:** 0.8
- **D.Confidence:** 0.70
- **Claim:** The deduplicator is a geometry-only tool by design. Attribute preservation strategy is the caller's responsibility. In practice, the current calling pattern preserves the richer source.
- **Evidence:**
  - User confirmed: "Geometry-only by design. The deduplicator is a geometry tool. Attribute selection is the caller's responsibility."
  - The deduplicator's documentation (`Fsm_1_2_16_deduplicator.md`) describes it purely in terms of geometry operations. It has zero dependencies on attribute schemas, field names, or source metadata. This is intentional -- it is a reusable geometry utility called by three different loaders with different field structures.
  - The Prosecutor's scenario requires: (a) two endpoints return the EXACT same geometry (post-normalization), AND (b) the endpoint with fewer fields happens to load first. In practice:
    - **Fsm_1_2_11 (Redlines):** `_create_merged_layer` iterates `loaded_layers` sequentially (line 230). The list is built by iterating endpoints from `Base_api_endpoints.json` in declaration order (line 99). The base layer is selected by `max(loaded_layers, key=lambda x: x[0].fields().count())` -- EGRN has more fields, so EGRN features populate the base structure. Features from all sources are appended in endpoint declaration order, and `getFeatures()` on a memory layer returns features in insertion order. So features from the first-declared endpoint (typically EGRN) get lower FIDs.
    - **Fsm_1_2_14 (Servitudes):** Uses UNION field strategy -- all sources contribute all their fields. There is no "-" padding. Attribute loss is limited to NULL vs actual-value for source-specific fields, and both features have identical coverage of shared fields.
    - **Fsm_1_2_9 (ZOUIT):** Sources are added sequentially (universal ZOUIT first, then OOPT, then OOPT Minprirody). The earlier source (universal) tends to have the richer classification data.
  - Adding attribute-awareness (e.g., "prefer the feature with fewer NULL/'-' values") would couple the deduplicator to field semantics it has no business knowing, violating the Single Responsibility Principle. Different callers have different field strategies (MAX fields in Fsm_1_2_11, UNION fields in Fsm_1_2_14, homogeneous fields in Fsm_1_2_9). A generic "richness" heuristic would be fragile.
  - The Prosecutor's claim of "non-deterministic" is imprecise. The behavior is deterministic for a given `Base_api_endpoints.json` configuration -- it always follows declaration order. It is not random. What it IS is implicit (dependent on configuration ordering rather than an explicit attribute-quality rule).
- **Trade-off:** Gained: a clean, reusable, schema-agnostic geometry utility. Lost: explicit guarantee that the "best" attributes survive when duplicate geometries have different metadata. In practice, the implicit ordering does preserve the richer source.
- **Verdict:** DEFENDED

### ISSUE-005: Same Non-Determinism in Near-Duplicate Selection
- **P.Confidence:** 0.75
- **D.Confidence:** 0.65
- **Claim:** Same design rationale as ISSUE-004, with a minor additional concern.
- **Evidence:**
  - All arguments from ISSUE-004 apply. The `fid_b > fid_a` constraint (line 183) is the standard approach for pairwise comparison in computational geometry: it avoids checking (A,B) and (B,A), halving the work. The lower-FID feature is kept, the higher-FID is discarded -- identical to the "first seen wins" pattern in Level 1.
  - For near-duplicates specifically, the geometric difference between the two features is small (IoU >= 0.95), so the "which geometry to keep" question is less impactful than for exact duplicates.
  - The concern is slightly weaker here than ISSUE-004 because near-duplicates with IoU >= 0.95 from different WFS endpoints are less common than exact duplicates. Near-duplicates typically arise from coordinate precision differences within the SAME source, not from cross-source overlap.
  - However, the user acknowledged this is "implicit, not guaranteed," which aligns with the Prosecutor's concern at the architectural level.
- **Trade-off:** Gained: standard pairwise comparison algorithm. Lost: same as ISSUE-004 -- no explicit attribute quality preference.
- **Verdict:** PARTIAL

### ISSUE-006: Test Suite Does Not Cover `_delete_features` Failure Path or Multi-Source Attribute Preservation
- **P.Confidence:** 0.9
- **D.Confidence:** 0.45
- **Claim:** The test gaps are real but proportional to the MVP stage of the module.
- **Evidence:**
  - User confirmed this is an initial/MVP implementation. The 12 existing tests cover: initialization, empty layer, no-duplicates, exact duplicates, normalize() effect, near-duplicates IoU, non-duplicate overlap, line layer skip, NULL geometries, full pipeline, disable flag, custom threshold. This is solid coverage of the core algorithm.
  - The Prosecutor identifies four specific gaps:
    1. **`_delete_features` failure:** As argued in ISSUE-001, memory-layer deletion with valid FIDs does not fail in practice. Testing a failure that cannot be provoked on memory layers would require mocking the provider, which adds test infrastructure complexity without testing real behavior.
    2. **Multi-source attributes:** This is the caller's concern (ISSUE-004), not the deduplicator's. The deduplicator's contract is "remove geometric duplicates." Testing attribute preservation belongs in the loader tests (Fsm_1_2_11, Fsm_1_2_14).
    3. **Invalid geometries in IoU:** This IS a valid gap -- testing that Level 2 gracefully handles invalid geometries would verify the try/except from ISSUE-002 works as intended.
    4. **MultiPolygon geometries:** This IS a valid gap. WFS data frequently returns MultiPolygon types, and the IoU path uses `.area()` and `.intersection()` which behave differently on multi-part geometries.
  - Two of the four gaps (invalid geometries, MultiPolygon) are legitimate test improvements. The other two (delete failure, multi-source attributes) are either untestable on memory layers or belong to different test modules.
- **Trade-off:** Gained: focused tests on core algorithm correctness for MVP. Lost: edge-case coverage for invalid geometries and multi-part features.
- **Verdict:** PARTIAL

## Weak Defenses (Confidence < 0.5)

| Issue | Reason | Recommendation |
|-------|--------|----------------|
| ISSUE-002 | User confirmed logging was forgotten. Bare except without any diagnostic output violates project standards. | Add `log_warning` with a counter: log on first occurrence + summary count at end of method. |
| ISSUE-003 | Stale docstring, no valid defense. The `.md` documentation is correct but the `.py` docstring is misleading. | Update lines 9-10 of `Fsm_1_2_15_oopt_loader.py` to remove deduplication claim. Trivial fix. |
| ISSUE-006 | Two of four identified test gaps (invalid geometry, MultiPolygon) are legitimate and testable. | Add test_13 for self-intersecting geometry in IoU loop. Add test_14 for MultiPolygon WKT. |

## Summary

| Defense | Count |
|---------|-------|
| Strong (>=0.7) | 2 |
| Partial (0.5-0.69) | 2 |
| Weak (<0.5) | 2 |

**Overall assessment:** The deduplicator is a well-structured, schema-agnostic geometry utility. Its core design decisions (geometry-only scope, memory-layer assumptions, first-seen-wins strategy) are defensible and consistent with codebase conventions. Two issues require immediate fixes: adding diagnostic logging to the IoU except handler (ISSUE-002) and updating the stale docstring (ISSUE-003). Test coverage for invalid and multi-part geometries (ISSUE-006) should be added as the module matures beyond MVP.
