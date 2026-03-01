# Prosecutor Report: Fsm_1_2_16_Deduplicator and Integrations

**Scope:** Geometry deduplication module (Fsm_1_2_16) and its integration in Fsm_1_2_11, Fsm_1_2_14, Fsm_1_2_9, Fsm_1_2_15; test coverage (Fsm_4_2_T_1_2_16)
**Date:** 2026-03-01 18:00
**Files analyzed:**
- `tools/F_1_data/submodules/Fsm_1_2_16_deduplicator.py` (241 lines)
- `tools/F_1_data/submodules/Fsm_1_2_11_redline_loader.py` (261 lines)
- `tools/F_1_data/submodules/Fsm_1_2_14_servitude_loader.py` (421 lines)
- `tools/F_1_data/submodules/Fsm_1_2_9_zouit_loader.py` (190 lines)
- `tools/F_1_data/submodules/Fsm_1_2_15_oopt_loader.py` (106 lines)
- `tools/F_4_plagin/submodules/Fsm_4_2_T_comprehensive_runner/Fsm_4_2_T_1_2_16.py` (658 lines)

## Issues

### ISSUE-001: `_delete_features` Does Not Verify `deleteFeatures()` or `commitChanges()` Return Values -- Silent Data Retention
- **Severity:** High
- **Confidence:** 0.9
- **Location:** `tools/F_1_data/submodules/Fsm_1_2_16_deduplicator.py:233-235`
- **Claim:** The `_delete_features` method assumes both `deleteFeatures()` and `commitChanges()` succeed without checking their boolean return values, then reports `len(fids)` as the number of deleted features regardless of actual outcome.
- **Evidence:**
  ```python
  # Line 233-235
  layer.deleteFeatures(fids)
  layer.commitChanges()
  return len(fids)
  ```
  PyQGIS API: `QgsVectorLayer.deleteFeatures()` returns `bool` (True on success). `QgsVectorLayer.commitChanges()` returns `bool`. Other code in this codebase DOES check the return value, e.g., `Fsm_1_1_3_coordinate_input.py:467: if self.edit_layer.commitChanges():`.
- **Warrant:** If `deleteFeatures()` fails (e.g., provider does not support deletion, fids are invalid after an intermediate edit), the method still returns `len(fids)` as if all features were removed. The caller (`deduplicate` at line 74) sums this into `total_removed`, and callers like `Fsm_1_2_9_zouit_loader.py:153` subtract this from `zouit_total`. The downstream count becomes wrong: the code reports N duplicates removed while the layer still contains them. This is not theoretical -- `commitChanges()` can fail if the layer is in an inconsistent editing state, and the error path only triggers on exceptions, not on boolean `False` returns.
- **Impact:** Incorrect feature counts reported to the user. The deduplication appears to succeed while duplicates remain in the GeoPackage. Downstream logic that relies on `dedup_result['remaining']` (Fsm_1_2_11:155, Fsm_1_2_14:169) will report a count that does not match actual layer content.

### ISSUE-002: Bare `except Exception` Silently Swallows Geometry Computation Errors in IoU Loop
- **Severity:** High
- **Confidence:** 0.85
- **Location:** `tools/F_1_data/submodules/Fsm_1_2_16_deduplicator.py:207-208`
- **Claim:** The bare `except Exception: continue` in the IoU computation loop silently swallows ALL exceptions -- including GEOS topology exceptions from invalid geometries -- without any logging, making it impossible to diagnose why near-duplicates are being missed.
- **Evidence:**
  ```python
  # Lines 207-208
  except Exception:
      continue
  ```
  The project coding standards in `CLAUDE.md` mandate: "try/except for file/layer operations" with proper logging via `log_error()`. The `Fsm_1_2_16_deduplicator.py` module imports `log_error` and `log_warning` (line 21) but does not use either in this handler.
- **Warrant:** GEOS `intersection()` operations on real WFS data frequently produce topology exceptions (self-intersections, ring crossings). When this happens, the pair is silently skipped. If a systematic geometry issue affects many features (e.g., a WFS source returns consistently invalid geometries), the entire Level 2 deduplication silently becomes a no-op. No log message is produced. The operator sees "0 near-duplicates" and has no way to know whether that is accurate or whether all IoU checks failed. At minimum, a `log_warning` on first occurrence or a counter of failed pairs would make diagnosis possible.
- **Impact:** Silent failure of Level 2 deduplication with no diagnostic output. Near-duplicate features from WFS sources with geometry quality issues persist undetected.

### ISSUE-003: Stale Docstring in `Fsm_1_2_15_oopt_loader.py` Claims It Contains Deduplication Logic
- **Severity:** Medium
- **Confidence:** 0.95
- **Location:** `tools/F_1_data/submodules/Fsm_1_2_15_oopt_loader.py:9-10`
- **Claim:** The module-level docstring states the file "Contains deduplication logic by exact WKB match" but the class contains no deduplication code whatsoever. Deduplication was extracted to Fsm_1_2_16.
- **Evidence:**
  ```python
  # Lines 9-10
  Содержит логику дедупликации по точному совпадению геометрий (WKB),
  применяемую ко всему слою Le_1_2_5_21 после объединения всех источников.
  ```
  The class `Fsm_1_2_15_OoptLoader` (lines 24-105) contains exactly two methods: `load_oopt_minprirody()` and `_find_endpoint()`. Neither performs deduplication. The actual deduplication call is in `Fsm_1_2_9_zouit_loader.py:148-150`.
- **Warrant:** Stale documentation actively misleads developers into thinking this module handles deduplication. When debugging dedup behavior for the OOPT layer, a developer reading the docstring would look HERE instead of in Fsm_1_2_9 or Fsm_1_2_16. The project's CLAUDE.md explicitly states: "documentation = source of truth" and "update documentation when API changes". This is a violation of that principle.
- **Impact:** Developer confusion, wasted debugging time, incorrect mental model of module responsibilities.

### ISSUE-004: `deduplicate_exact` Keeps First-Encountered Feature, Discards Later Ones -- Non-Deterministic Attribute Preservation
- **Severity:** High
- **Confidence:** 0.8
- **Location:** `tools/F_1_data/submodules/Fsm_1_2_16_deduplicator.py:109-121`
- **Claim:** When exact duplicates exist with different attribute values (common in multi-endpoint merges where the same geometry comes from EGRN vs MINSTROY with different metadata), the deduplicator keeps whichever feature is iterated first and silently discards the duplicate's attributes. The iteration order depends on the internal feature ID assignment by the memory provider, which depends on insertion order during merge.
- **Evidence:**
  ```python
  # Lines 109-121
  for feature in layer.getFeatures():
      if not feature.hasGeometry():
          continue
      geom = QgsGeometry(feature.geometry())
      geom.normalize()
      wkb = bytes(geom.asWkb())
      if wkb in seen_wkb:
          duplicate_ids.append(feature.id())  # LATER feature is discarded
      else:
          seen_wkb.add(wkb)
  ```
  In `Fsm_1_2_11_redline_loader.py:230-247`, features from multiple endpoints are appended sequentially. Features from the endpoint with MORE fields (EGRN) are added first (it is the base), then MINSTROY features with partial fields (rest = "-"). But this depends on `max()` selecting the correct base layer. If the ordering changes or if features are from the endpoint with FEWER fields that happen to be added first, the richer EGRN attributes are discarded.
- **Warrant:** The `_source` field (Fsm_1_2_11:239, Fsm_1_2_14:400) marks which endpoint each feature came from. When a geometry exists in both EGRN and MINSTROY, both features are added to the merged layer. Level 1 dedup then discards whichever was added second. Since `_create_merged_layer` iterates `loaded_layers` in the order they were appended (lines 230), and `loaded_layers` is built by sequential endpoint loading (line 99-115), the "winner" depends on endpoint response order -- which is effectively non-deterministic from the user's perspective. The feature with richer attributes (more fields filled, `_source` = EGRN) might be the one discarded.
- **Impact:** Potential loss of attribute data from the richer data source. A feature might retain MINSTROY attributes (with many fields = "-") while discarding the complete EGRN attributes for the same geometry.

### ISSUE-005: `deduplicate_near` Retains fid_a and Discards fid_b Without Attribute Quality Comparison -- Same Non-Determinism for Near-Duplicates
- **Severity:** Medium
- **Confidence:** 0.75
- **Location:** `tools/F_1_data/submodules/Fsm_1_2_16_deduplicator.py:169-206`
- **Claim:** In the near-duplicate loop, the feature with lower FID (fid_a) is always retained and the feature with higher FID (fid_b) is always marked for deletion, regardless of which has richer attributes or which source it came from.
- **Evidence:**
  ```python
  # Lines 182-183, 205-206
  if fid_b <= fid_a or fid_b in duplicate_ids:
      continue
  ...
  if iou >= iou_threshold:
      duplicate_ids.add(fid_b)  # Always discard the higher-FID feature
  ```
- **Warrant:** This is the same attribute-loss concern as ISSUE-004 but for near-duplicates. The decision of which feature to keep is based solely on FID ordering, not on attribute completeness. In a multi-endpoint merge, lower FIDs come from the endpoint processed first. There is no heuristic to prefer the feature with more non-null/non-"-" attributes.
- **Impact:** Same as ISSUE-004: potential loss of richer attribute data from the discarded feature.

### ISSUE-006: Test Suite Does Not Cover `_delete_features` Failure Path or Multi-Source Attribute Preservation
- **Severity:** Medium
- **Confidence:** 0.9
- **Location:** `tools/F_4_plagin/submodules/Fsm_4_2_T_comprehensive_runner/Fsm_4_2_T_1_2_16.py` (entire file)
- **Claim:** The test suite has notable coverage gaps: (1) no test for `_delete_features` returning 0 on failure (startEditing fails, commitChanges fails, exception during deletion), (2) no test for multi-source scenarios where duplicate geometries have different attributes, (3) no test for invalid/self-intersecting geometries that would trigger the bare except in IoU computation, (4) no test for MultiPolygon geometries (all tests use simple Polygon WKT).
- **Evidence:** All 12 tests use `create_polygon_layer` which creates simple memory layers. Test geometries are all valid simple polygons (squares). No test creates features with attributes from different "sources" to verify which attributes survive dedup. No test attempts to provoke geometry errors in the IoU path. No test uses `MULTIPOLYGON((...),(...))` WKT.
- **Warrant:** The tests verify the "happy path" of deduplication algorithms but do not exercise the failure modes that are most likely to occur with real WFS data (invalid geometries, multi-part features, failed edit operations). The test for NULL geometries (test_09) covers `hasGeometry()` checks but not invalid/corrupt geometries that pass `hasGeometry()` but fail on `intersection()`.
- **Impact:** Bugs in error handling paths (ISSUE-001, ISSUE-002) cannot be detected by the existing test suite. Regressions in these areas will go unnoticed.

## Summary
| Severity | Count |
|----------|-------|
| Critical | 0 |
| High | 3 |
| Medium | 3 |

**Verdict:** FIX_REQUIRED

Issues 001 and 002 are the most actionable: check return values from `deleteFeatures()`/`commitChanges()` and add at least a warning-level log for geometry exceptions in the IoU loop. Issue 004/005 (attribute preservation non-determinism) is an architectural concern that may require a strategy decision (e.g., prefer the feature with more non-null attributes, or prefer a specific `_source`). Issue 003 is a straightforward docstring fix. Issue 006 describes test gaps that should be closed to prevent regressions.
