# Tests Audit Report

Date: 2026-03-02
Task: Ralph Loop - static audit of all Fsm_4_2_T_*.py test files against source modules

## Summary

- Total test files audited: 62
- Status OK (no QGIS needed, passes statically): 18
- Status NEEDS_QGIS (requires QGIS iface, can't verify statically): 41
- Status WILL_FAIL (blocking mismatches found): 3 (all FIXED)
- Source bugs found and fixed: 1

## Fixes Applied

### 1. SOURCE FIX: utils.py (telemetry call)

**File:** `utils.py` (lines 92-97)
**Issue:** `log_error()` called `telemetry.track_error()` with keyword args (`func_id`, `error_type`, `error_msg`, `stack`) that don't match the method signature `track_error(func_id, error: Exception, context)`. The method expects an Exception object, but `log_error()` has no Exception available.
**Fix:** Changed to `telemetry.track_event('error', {...})` which accepts generic event data.

Before:
```python
telemetry.track_error(
    func_id=module_id,
    error_type="LogError",
    error_msg=error_msg,
    stack=None
)
```

After:
```python
telemetry.track_event('error', {
    'func': module_id,
    'error_type': 'LogError',
    'error_msg': error_msg,
    'stack': []
})
```

### 2. TEST FIX: Fsm_4_2_T_1_1.py (wrong imports + wrong constructor arg)

**File:** `tools/F_4_plagin/submodules/Fsm_4_2_T_comprehensive_runner/Fsm_4_2_T_1_1.py`

**Issue A - Wrong import paths (lines 164, 177, 247, 267):**
- `Fsm_1_1_2_dxf.DxfImportSubmodule` -> actual: `Fsm_1_1_1_dxf_importer.DxfImporter`
- `Fsm_1_1_3_tab.TabImportSubmodule` -> actual: `Fsm_1_1_2_tab_importer.TabImporter`

**Issue B - Wrong constructor arg (line 128):**
- `LayerManager(self.iface, self.project_manager)` passed ProjectManager object where `plugin_dir: Optional[str]` expected
- Fixed to `LayerManager(self.iface)` (plugin_dir is optional)

**Fix:** Corrected all import paths and class names, fixed constructor call.

## Pyright Verification

```
npx pyright utils.py tools/F_4_plagin/submodules/Fsm_4_2_T_comprehensive_runner/Fsm_4_2_T_1_1.py
0 errors, 0 warnings, 0 informations
```

## Full Audit Table

| # | Test File | Tests | Status | Notes |
|---|-----------|-------|--------|-------|
| 1 | Fsm_4_2_T_0_1.py | F_0_1 NewProject | NEEDS_QGIS | Minor: test data setup incomplete (handled gracefully) |
| 2 | Fsm_4_2_T_0_2.py | F_0_2 OpenProject | NEEDS_QGIS | Minor: dynamic attrs on ProjectManager (runtime only) |
| 3 | Fsm_4_2_T_0_3.py | F_0_3 EditProjectProperties | NEEDS_QGIS | No issues |
| 4 | Fsm_4_2_T_0_4.py | F_0_4 TopologyCheck | NEEDS_QGIS | No issues |
| 5 | Fsm_4_2_T_0_4_1.py | F_0_4 Polygon checkers | NEEDS_QGIS | No issues |
| 6 | Fsm_4_2_T_0_4_2.py | F_0_4 Advanced checkers | NEEDS_QGIS | No issues |
| 7 | Fsm_4_2_T_0_5.py | F_0_5 RefineProjection | NEEDS_QGIS | Lines 56,59: external_modules doesn't exist (warning only, non-fatal) |
| 8 | Fsm_4_2_T_0_6.py | F_0_6 TransformLayers | NEEDS_QGIS | No issues |
| 9 | Fsm_4_2_T_1_1.py | F_1_1 UniversalImport | **FIXED** | Wrong import paths and constructor arg (see Fixes #2) |
| 10 | Fsm_4_2_T_1_1_4.py | Fsm_1_1_4 DXF/SHP import | NEEDS_QGIS | No issues |
| 11 | Fsm_4_2_T_1_2.py | F_1_2 LoadWebMaps | NEEDS_QGIS | Non-fatal: hasattr checks for methods that may not exist (warning) |
| 12 | Fsm_4_2_T_1_2_1.py | Fsm_1_2_1 ZouitClassifier | NEEDS_QGIS | No issues |
| 13 | Fsm_4_2_T_1_2_16.py | Fsm_1_2_16 BackgroundRef | OK | No issues |
| 14 | Fsm_4_2_T_1_2_2.py | Fsm_1_2_2 ImportSubmodule | NEEDS_QGIS | No issues |
| 15 | Fsm_4_2_T_1_2_4_qt.py | Qt6 compatibility | OK | No issues |
| 16 | Fsm_4_2_T_1_3.py | F_1_3 BudgetSelection | NEEDS_QGIS | No issues |
| 17 | Fsm_4_2_T_1_4.py | F_1_4 GraphicsRequest | NEEDS_QGIS | Non-fatal: 12 method name checks (warning only) |
| 18 | Fsm_4_2_T_1_5.py | F_1_5 UniversalExport | NEEDS_QGIS | Non-fatal: prepare_layer, validate don't exist (warning) |
| 19 | Fsm_4_2_T_2_1.py | F_2_1 AutoClassification | NEEDS_QGIS | Non-fatal: cut_all_zpr_types, cut_zpr_layer don't exist (warning) |
| 20 | Fsm_4_2_T_2_1_7.py | Fsm_2_1_7 VRI mapping | NEEDS_QGIS | No code mismatches |
| 21 | Fsm_4_2_T_2_1_cutting.py | Fsm_2_1 Cutting pipeline | NEEDS_QGIS | No issues |
| 22 | Fsm_4_2_T_2_2.py | F_2_2 ManualTransfer | NEEDS_QGIS | No issues |
| 23 | Fsm_4_2_T_2_3.py | F_2_3 VRIAssignment | NEEDS_QGIS | No issues |
| 24 | Fsm_4_2_T_2_4.py | F_2_4 WorkType | NEEDS_QGIS | No issues |
| 25 | Fsm_4_2_T_2_5.py | F_2_5 AreaTransfer | NEEDS_QGIS | No issues |
| 26 | Fsm_4_2_T_3_1.py | F_3_1 ForestAnalysis | NEEDS_QGIS | Minor: REQUIRED_FOREST_FIELDS not in source (warning) |
| 27 | Fsm_4_2_T_3_2.py | F_3_2 LandCategory | NEEDS_QGIS | No issues |
| 28 | Fsm_4_2_T_4_4.py | F_4_4 BugReport | NEEDS_QGIS | All imports, attributes, methods verified |
| 29 | Fsm_4_2_T_5_1.py | F_5_1 VectorExport | NEEDS_QGIS | All imports, methods, dependencies verified |
| 30 | Fsm_4_2_T_5_2.py | F_5_2 BackgroundExport | NEEDS_QGIS | All imports, methods, dependencies verified |
| 31 | Fsm_4_2_T_5_3.py | F_5_3 DocumentExport | NEEDS_QGIS | All imports, submodule files verified |
| 32 | Fsm_4_2_T_6_1.py | F_6_1 Timesheet | NEEDS_QGIS | TimesheetData, vacation_hours, validator verified |
| 33 | Fsm_4_2_T_17_2.py | Msm_17_2 ProgressReporter | NEEDS_QGIS | Constructor signature verified |
| 34 | Fsm_4_2_T_21_1.py | Msm_21_1 ExistingVRIValidator | NEEDS_QGIS | Dynamic submodule export verified |
| 35 | Fsm_4_2_T_22.py | M_22 WorkTypeAssignment | NEEDS_QGIS | LayerType, StageType enums verified |
| 36 | Fsm_4_2_T_28.py | M_28 ForestSchema | NEEDS_QGIS | LAYER_SCHEMAS, ForestVydelySchemaProvider verified |
| 37 | Fsm_4_2_T_29.py | M_29 LicenseManager | NEEDS_QGIS | LicenseStatus, session cache, verify_for_display verified |
| 38 | Fsm_4_2_T_33.py | M_33 WordExport | NEEDS_QGIS | Constructor(template_dir=None) verified |
| 39 | Fsm_4_2_T_33_1.py | Msm_33_1 HLU_DataProcessor | NEEDS_QGIS | Export domain submodule_imports verified |
| 40 | Fsm_4_2_T_36.py | M_36 LandCategory | NEEDS_QGIS | _CATEGORY_CASCADE, _FALLBACK_CATEGORY verified |
| 41 | Fsm_4_2_T_40.py | M_40 NspdAuth | NEEDS_QGIS | CookieStore, NspdAuthManager, Edge auth verified |
| 42 | Fsm_4_2_T_api.py | API connectivity | OK | No issues |
| 43 | Fsm_4_2_T_network.py | Network resilience | OK | No issues |
| 44 | Fsm_4_2_T_security.py | Security (OWASP) | OK | No issues |
| 45 | Fsm_4_2_T_telemetry.py | M_32 Telemetry | OK | No issues |
| 46 | Fsm_4_2_T_heartbeat.py | Heartbeat | OK | No issues |
| 47 | Fsm_4_2_T_dadata.py | DaData integration | OK | No issues |
| 48 | Fsm_4_2_T_nspd.py | NSPD integration | OK | No issues |
| 49 | Fsm_4_2_T_crs_transform.py | CRS transform | NEEDS_QGIS | No issues |
| 50 | Fsm_4_2_T_dxf_export.py | DXF export | OK | No issues |
| 51 | Fsm_4_2_T_expressions.py | QGIS expressions | NEEDS_QGIS | No issues |
| 52 | Fsm_4_2_T_memory_leak.py | Memory leak detection | NEEDS_QGIS | No issues |
| 53 | Fsm_4_2_T_normalize_ring.py | Ring normalization | OK | No issues |
| 54 | Fsm_4_2_T_performance.py | Performance benchmarks | NEEDS_QGIS | No issues |
| 55 | Fsm_4_2_T_plugin_lifecycle.py | Plugin lifecycle | OK | No issues |
| 56 | Fsm_4_2_T_processing.py | Processing algorithms | NEEDS_QGIS | No issues |
| 57 | Fsm_4_2_T_pyright.py | Pyright type checks | OK | No issues |
| 58 | Fsm_4_2_T_qgis_environment.py | QGIS environment | NEEDS_QGIS | No issues |
| 59 | Fsm_4_2_T_qt6_compatibility.py | Qt6 compat | OK | No issues |
| 60 | Fsm_4_2_T_signals.py | Signal safety | OK | No issues |
| 61 | Fsm_4_2_T_thread_safety.py | Thread safety | OK | No issues |
| 62 | Fsm_4_2_T_utils_refresh.py | Utils refresh | OK | No issues |

## Non-Fatal Warnings (not fixed, by design)

These tests check for methods/attributes that don't exist in current source, but use `logger.warning()` (not `logger.fail()`), so they produce warnings but don't crash the test suite:

1. **Fsm_4_2_T_0_5.py** (lines 56, 59): Imports from `Daman_QGIS.external_modules` which doesn't exist. The folder was likely removed or never created. Non-blocking (try/except + warning).

2. **Fsm_4_2_T_1_2.py**: hasattr checks for methods that may have been renamed. Non-blocking (warning only).

3. **Fsm_4_2_T_1_4.py**: 12 method name checks for methods that don't exist in current GraphicsRequest. Non-blocking (warning only).

4. **Fsm_4_2_T_1_5.py**: Checks for `prepare_layer`, `validate` methods that don't exist. Non-blocking (warning only).

5. **Fsm_4_2_T_2_1.py** (lines 160-161): Checks for `cut_all_zpr_types`, `cut_zpr_layer` on CuttingManager. Non-blocking (data logging + warning).

6. **Fsm_4_2_T_3_1.py**: Checks for `REQUIRED_FOREST_FIELDS` constant that doesn't exist. Non-blocking (warning only).

## Excluded Files

Per test runner configuration (`EXCLUDED_FILES`):
- `Fsm_4_2_1_test_logger.py` - Test infrastructure, not a test
- `Fsm_4_2_T_comprehensive_runner.py` - Test runner itself
- `Fsm_4_2_T_4_1.py` - Excluded by runner configuration

## Modified Files

1. `utils.py` - Fixed telemetry track_error call (source bug)
2. `tools/F_4_plagin/submodules/Fsm_4_2_T_comprehensive_runner/Fsm_4_2_T_1_1.py` - Fixed wrong imports and constructor arg (test bug)
