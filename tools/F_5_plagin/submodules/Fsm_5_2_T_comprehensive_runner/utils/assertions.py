# -*- coding: utf-8 -*-
"""
assertions.py - Custom assertions for QGIS testing

Provides assertion helpers that work with TestLogger
instead of raising exceptions (for integration with existing test system)
"""

from typing import Optional, List, Tuple, Any

from qgis.core import (
    QgsGeometry, QgsVectorLayer, QgsFeature,
    QgsCoordinateReferenceSystem, QgsRectangle
)


# =============================================================================
# ASSERTION RESULT CLASS
# =============================================================================

class AssertionResult:
    """Result of an assertion check"""

    def __init__(self, passed: bool, message: str = "", details: str = ""):
        self.passed = passed
        self.message = message
        self.details = details

    def __bool__(self):
        return self.passed

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        result = f"[{status}] {self.message}"
        if self.details:
            result += f"\n    Details: {self.details}"
        return result


# =============================================================================
# GEOMETRY ASSERTIONS
# =============================================================================

class GeometryAssertions:
    """Assertions for geometry validation"""

    @staticmethod
    def is_valid(geom: QgsGeometry) -> AssertionResult:
        """Assert that geometry is valid (GEOS validation)"""
        if geom is None or geom.isNull():
            return AssertionResult(False, "Geometry is NULL")

        if geom.isEmpty():
            return AssertionResult(False, "Geometry is empty")

        if not geom.isGeosValid():
            error = geom.lastError() if hasattr(geom, 'lastError') else "Unknown error"
            return AssertionResult(
                False,
                "Geometry is not GEOS valid",
                error
            )

        return AssertionResult(True, "Geometry is valid")

    @staticmethod
    def equals_wkt(geom: QgsGeometry, expected_wkt: str, tolerance: float = 1e-6) -> AssertionResult:
        """Assert geometry equals expected WKT"""
        if geom is None or geom.isNull():
            return AssertionResult(False, "Geometry is NULL")

        expected = QgsGeometry.fromWkt(expected_wkt)
        if expected.isNull():
            return AssertionResult(False, f"Invalid expected WKT: {expected_wkt[:50]}")

        if geom.equals(expected):
            return AssertionResult(True, "Geometries are equal")

        # Check with tolerance
        if geom.isGeosEqual(expected):
            return AssertionResult(True, "Geometries are GEOS equal")

        return AssertionResult(
            False,
            "Geometries are not equal",
            f"Expected: {expected_wkt[:50]}...\nGot: {geom.asWkt()[:50]}..."
        )

    @staticmethod
    def has_type(geom: QgsGeometry, expected_type: str) -> AssertionResult:
        """Assert geometry is of expected type (Point, LineString, Polygon, etc.)"""
        if geom is None or geom.isNull():
            return AssertionResult(False, "Geometry is NULL")

        actual_type = geom.type()
        type_names = {0: "Point", 1: "LineString", 2: "Polygon"}
        actual_name = type_names.get(actual_type, f"Unknown({actual_type})")

        expected_normalized = expected_type.lower().replace("string", "")
        actual_normalized = actual_name.lower()

        if expected_normalized in actual_normalized or actual_normalized in expected_normalized:
            return AssertionResult(True, f"Geometry type is {actual_name}")

        return AssertionResult(
            False,
            f"Wrong geometry type",
            f"Expected: {expected_type}, Got: {actual_name}"
        )

    @staticmethod
    def within_bounds(geom: QgsGeometry, bounds: QgsRectangle) -> AssertionResult:
        """Assert geometry is within given bounds"""
        if geom is None or geom.isNull():
            return AssertionResult(False, "Geometry is NULL")

        geom_bounds = geom.boundingBox()
        if bounds.contains(geom_bounds):
            return AssertionResult(True, "Geometry within bounds")

        return AssertionResult(
            False,
            "Geometry outside bounds",
            f"Bounds: {bounds.toString()}, Geom bounds: {geom_bounds.toString()}"
        )

    @staticmethod
    def area_equals(geom: QgsGeometry, expected_area: float, tolerance: float = 0.01) -> AssertionResult:
        """Assert polygon area equals expected value"""
        if geom is None or geom.isNull():
            return AssertionResult(False, "Geometry is NULL")

        actual_area = geom.area()
        diff = abs(actual_area - expected_area)

        if diff <= tolerance:
            return AssertionResult(True, f"Area {actual_area:.4f} matches expected")

        return AssertionResult(
            False,
            "Area mismatch",
            f"Expected: {expected_area:.4f}, Got: {actual_area:.4f}, Diff: {diff:.4f}"
        )


# =============================================================================
# LAYER ASSERTIONS
# =============================================================================

class LayerAssertions:
    """Assertions for layer validation"""

    @staticmethod
    def is_valid(layer: QgsVectorLayer) -> AssertionResult:
        """Assert layer is valid"""
        if layer is None:
            return AssertionResult(False, "Layer is None")

        if not layer.isValid():
            return AssertionResult(
                False,
                "Layer is not valid",
                f"Provider error: {layer.dataProvider().error().message() if layer.dataProvider() else 'No provider'}"
            )

        return AssertionResult(True, f"Layer '{layer.name()}' is valid")

    @staticmethod
    def has_features(layer: QgsVectorLayer, min_count: int = 1, max_count: Optional[int] = None) -> AssertionResult:
        """Assert layer has expected number of features"""
        if layer is None or not layer.isValid():
            return AssertionResult(False, "Layer is invalid")

        count = layer.featureCount()

        if count < min_count:
            return AssertionResult(
                False,
                f"Too few features",
                f"Expected at least {min_count}, got {count}"
            )

        if max_count is not None and count > max_count:
            return AssertionResult(
                False,
                f"Too many features",
                f"Expected at most {max_count}, got {count}"
            )

        return AssertionResult(True, f"Layer has {count} features")

    @staticmethod
    def has_field(layer: QgsVectorLayer, field_name: str) -> AssertionResult:
        """Assert layer has a field with given name"""
        if layer is None or not layer.isValid():
            return AssertionResult(False, "Layer is invalid")

        field_idx = layer.fields().indexOf(field_name)
        if field_idx < 0:
            fields = [f.name() for f in layer.fields()]
            return AssertionResult(
                False,
                f"Field '{field_name}' not found",
                f"Available fields: {', '.join(fields)}"
            )

        return AssertionResult(True, f"Field '{field_name}' exists")

    @staticmethod
    def has_crs(layer: QgsVectorLayer, expected_crs: str) -> AssertionResult:
        """Assert layer has expected CRS"""
        if layer is None or not layer.isValid():
            return AssertionResult(False, "Layer is invalid")

        layer_crs = layer.crs()
        expected = QgsCoordinateReferenceSystem(expected_crs)

        if layer_crs == expected:
            return AssertionResult(True, f"Layer CRS is {expected_crs}")

        return AssertionResult(
            False,
            "CRS mismatch",
            f"Expected: {expected_crs}, Got: {layer_crs.authid()}"
        )

    @staticmethod
    def geometry_type_is(layer: QgsVectorLayer, expected_type: int) -> AssertionResult:
        """Assert layer geometry type"""
        if layer is None or not layer.isValid():
            return AssertionResult(False, "Layer is invalid")

        actual = layer.geometryType()
        type_names = {0: "Point", 1: "Line", 2: "Polygon", 3: "Unknown", 4: "Null"}

        if actual == expected_type:
            return AssertionResult(True, f"Geometry type is {type_names.get(actual, actual)}")

        return AssertionResult(
            False,
            "Geometry type mismatch",
            f"Expected: {type_names.get(expected_type, expected_type)}, Got: {type_names.get(actual, actual)}"
        )


# =============================================================================
# FEATURE ASSERTIONS
# =============================================================================

class FeatureAssertions:
    """Assertions for feature validation"""

    @staticmethod
    def has_geometry(feature: QgsFeature) -> AssertionResult:
        """Assert feature has a geometry"""
        if feature is None:
            return AssertionResult(False, "Feature is None")

        if not feature.hasGeometry():
            return AssertionResult(False, "Feature has no geometry")

        if feature.geometry().isNull():
            return AssertionResult(False, "Feature geometry is NULL")

        return AssertionResult(True, "Feature has geometry")

    @staticmethod
    def attribute_equals(feature: QgsFeature, field_name: str, expected_value: Any) -> AssertionResult:
        """Assert feature attribute equals expected value"""
        if feature is None:
            return AssertionResult(False, "Feature is None")

        try:
            actual = feature.attribute(field_name)
        except KeyError:
            return AssertionResult(False, f"Field '{field_name}' not found")

        if actual == expected_value:
            return AssertionResult(True, f"{field_name} = {expected_value}")

        return AssertionResult(
            False,
            "Attribute mismatch",
            f"Field '{field_name}': Expected {expected_value}, Got {actual}"
        )

    @staticmethod
    def attribute_not_null(feature: QgsFeature, field_name: str) -> AssertionResult:
        """Assert feature attribute is not NULL"""
        if feature is None:
            return AssertionResult(False, "Feature is None")

        try:
            value = feature.attribute(field_name)
        except KeyError:
            return AssertionResult(False, f"Field '{field_name}' not found")

        if value is None or (hasattr(value, 'isNull') and value.isNull()):
            return AssertionResult(False, f"Field '{field_name}' is NULL")

        return AssertionResult(True, f"Field '{field_name}' is not NULL")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def assert_geometry_valid(geom: QgsGeometry) -> bool:
    """Quick check if geometry is valid"""
    return bool(GeometryAssertions.is_valid(geom))


def assert_geometry_equals_wkt(geom: QgsGeometry, wkt: str) -> bool:
    """Quick check if geometry equals WKT"""
    return bool(GeometryAssertions.equals_wkt(geom, wkt))


def assert_layer_has_features(layer: QgsVectorLayer, count: int = 1) -> bool:
    """Quick check if layer has at least N features"""
    return bool(LayerAssertions.has_features(layer, min_count=count))


def assert_field_exists(layer: QgsVectorLayer, field_name: str) -> bool:
    """Quick check if field exists in layer"""
    return bool(LayerAssertions.has_field(layer, field_name))
