# -*- coding: utf-8 -*-
"""
conftest.py - Shared fixtures and configuration for test system

Provides:
- Test fixtures for layers, geometries, projects
- Edge case data for parametrized tests
- Common test utilities
"""

from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsField,
    QgsProject, QgsCoordinateReferenceSystem, QgsPointXY,
    QgsFields
)
from qgis.PyQt.QtCore import QMetaType


# =============================================================================
# DATA CLASSES FOR TEST CASES
# =============================================================================

@dataclass
class GeometryTestCase:
    """Test case for geometry validation"""
    name: str
    wkt: Optional[str]
    expected_valid: bool
    expected_type: str = ""
    description: str = ""


@dataclass
class FieldTestCase:
    """Test case for field value validation"""
    name: str
    value: Any
    field_type: int  # QMetaType.Type
    expected_valid: bool
    description: str = ""


@dataclass
class LayerTestCase:
    """Test case for layer operations"""
    name: str
    geometry_type: str  # Point, LineString, Polygon
    crs: str  # EPSG code
    fields: List[Tuple[str, int]]  # (name, QMetaType.Type)
    features_wkt: List[str]
    description: str = ""


# =============================================================================
# GEOMETRY EDGE CASES
# =============================================================================

GEOMETRY_EDGE_CASES: List[GeometryTestCase] = [
    # Valid geometries
    GeometryTestCase(
        name="simple_polygon",
        wkt="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        expected_valid=True,
        expected_type="Polygon",
        description="Simple valid polygon"
    ),
    GeometryTestCase(
        name="polygon_with_hole",
        wkt="POLYGON((0 0, 10 0, 10 10, 0 10, 0 0), (2 2, 8 2, 8 8, 2 8, 2 2))",
        expected_valid=True,
        expected_type="Polygon",
        description="Polygon with inner ring (hole)"
    ),
    GeometryTestCase(
        name="multipolygon",
        wkt="MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)), ((2 2, 3 2, 3 3, 2 3, 2 2)))",
        expected_valid=True,
        expected_type="MultiPolygon",
        description="Valid multipolygon"
    ),
    GeometryTestCase(
        name="triangle",
        wkt="POLYGON((0 0, 1 0, 0.5 1, 0 0))",
        expected_valid=True,
        expected_type="Polygon",
        description="Triangle (minimum valid polygon)"
    ),

    # Invalid geometries
    GeometryTestCase(
        name="self_intersection",
        wkt="POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))",
        expected_valid=False,
        expected_type="Polygon",
        description="Self-intersecting polygon (bowtie)"
    ),
    GeometryTestCase(
        name="degenerate_polygon",
        wkt="POLYGON((0 0, 0 0, 0 0, 0 0))",
        expected_valid=False,
        expected_type="Polygon",
        description="Degenerate polygon (all same points)"
    ),
    GeometryTestCase(
        name="unclosed_ring",
        wkt="POLYGON((0 0, 1 0, 1 1, 0 1))",
        expected_valid=False,
        expected_type="Polygon",
        description="Unclosed ring (missing closing point)"
    ),
    GeometryTestCase(
        name="null_geometry",
        wkt=None,
        expected_valid=False,
        expected_type="",
        description="NULL geometry"
    ),

    # Boundary cases
    GeometryTestCase(
        name="micro_polygon",
        wkt="POLYGON((0 0, 0.001 0, 0.001 0.001, 0 0.001, 0 0))",
        expected_valid=True,
        expected_type="Polygon",
        description="Very small polygon (centimeter precision)"
    ),
    GeometryTestCase(
        name="large_polygon",
        wkt="POLYGON((0 0, 1000000 0, 1000000 1000000, 0 1000000, 0 0))",
        expected_valid=True,
        expected_type="Polygon",
        description="Large polygon (1000km x 1000km)"
    ),
    GeometryTestCase(
        name="complex_polygon",
        wkt="POLYGON((0 0, 10 0, 10 5, 8 5, 8 3, 6 3, 6 5, 4 5, 4 3, 2 3, 2 5, 0 5, 0 0))",
        expected_valid=True,
        expected_type="Polygon",
        description="Complex polygon with comb-like shape"
    ),

    # Line geometries
    GeometryTestCase(
        name="simple_line",
        wkt="LINESTRING(0 0, 1 1, 2 0)",
        expected_valid=True,
        expected_type="LineString",
        description="Simple linestring"
    ),
    GeometryTestCase(
        name="closed_line",
        wkt="LINESTRING(0 0, 1 0, 1 1, 0 1, 0 0)",
        expected_valid=True,
        expected_type="LineString",
        description="Closed linestring (ring)"
    ),
    GeometryTestCase(
        name="self_crossing_line",
        wkt="LINESTRING(0 0, 1 1, 1 0, 0 1)",
        expected_valid=True,  # Lines can self-cross
        expected_type="LineString",
        description="Self-crossing linestring"
    ),

    # Point geometries
    GeometryTestCase(
        name="simple_point",
        wkt="POINT(0 0)",
        expected_valid=True,
        expected_type="Point",
        description="Simple point"
    ),
    GeometryTestCase(
        name="multipoint",
        wkt="MULTIPOINT((0 0), (1 1), (2 2))",
        expected_valid=True,
        expected_type="MultiPoint",
        description="Multipoint geometry"
    ),

    # =========================================================================
    # DEGENERATE GEOMETRIES (PostGIS/ArcGIS best practices)
    # =========================================================================
    GeometryTestCase(
        name="duplicate_vertices",
        wkt="POLYGON((0 0, 1 0, 1 0, 1 1, 0 1, 0 0))",
        expected_valid=True,  # Usually valid but may cause issues
        expected_type="Polygon",
        description="Polygon with duplicate consecutive vertices"
    ),
    GeometryTestCase(
        name="zero_area_spike",
        wkt="POLYGON((0 0, 1 0, 0.5 0.5, 1 0, 1 1, 0 1, 0 0))",
        expected_valid=False,
        expected_type="Polygon",
        description="Polygon with zero-area spike"
    ),
    GeometryTestCase(
        name="collinear_points",
        wkt="POLYGON((0 0, 0.5 0, 1 0, 1 1, 0 1, 0 0))",
        expected_valid=True,
        expected_type="Polygon",
        description="Polygon with collinear points on edge"
    ),
    GeometryTestCase(
        name="line_polygon_degenerate",
        wkt="POLYGON((0 0, 1 0, 2 0, 1 0, 0 0))",
        expected_valid=False,
        expected_type="Polygon",
        description="Degenerate polygon collapsed to line"
    ),
    GeometryTestCase(
        name="empty_polygon",
        wkt="POLYGON EMPTY",
        expected_valid=True,
        expected_type="Polygon",
        description="Empty polygon geometry"
    ),

    # =========================================================================
    # BANANA POLYGONS AND TOUCHING RINGS
    # =========================================================================
    GeometryTestCase(
        name="banana_polygon",
        wkt="POLYGON((0 0, 5 0, 5 1, 3 1, 3 0.5, 2 0.5, 2 1, 0 1, 0 0))",
        expected_valid=True,
        expected_type="Polygon",
        description="Banana-shaped polygon (concave)"
    ),
    GeometryTestCase(
        name="ring_touching_single_point",
        wkt="POLYGON((0 0, 2 0, 2 2, 0 2, 0 0), (1 0, 1.5 0.5, 1 1, 0.5 0.5, 1 0))",
        expected_valid=False,  # Hole touches outer ring at single point
        expected_type="Polygon",
        description="Hole touching outer ring at single point"
    ),
    GeometryTestCase(
        name="inverted_shell",
        wkt="POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))",
        expected_valid=False,  # Counter-clockwise outer ring (inverted)
        expected_type="Polygon",
        description="Inverted polygon (CCW outer ring)"
    ),
    GeometryTestCase(
        name="figure_eight",
        wkt="POLYGON((0 0, 1 1, 2 0, 2 2, 1 1, 0 2, 0 0))",
        expected_valid=False,
        expected_type="Polygon",
        description="Figure-eight polygon (self-touching at point)"
    ),
    GeometryTestCase(
        name="exverted_hole",
        wkt="POLYGON((0 0, 10 0, 10 10, 0 10, 0 0), (2 2, 2 8, 8 8, 8 2, 2 2))",
        expected_valid=False,  # CW hole (exverted)
        expected_type="Polygon",
        description="Exverted hole (CW instead of CCW)"
    ),

    # =========================================================================
    # MICRO-PRECISION EDGE CASES
    # =========================================================================
    GeometryTestCase(
        name="near_coincident_vertices",
        wkt="POLYGON((0 0, 1 0, 1.00000001 0.00000001, 1 1, 0 1, 0 0))",
        expected_valid=True,
        expected_type="Polygon",
        description="Vertices differing by < 0.01mm"
    ),
    GeometryTestCase(
        name="micro_self_intersection",
        wkt="POLYGON((0 0, 1 0, 0.5 0.0001, 0.50001 0, 1 1, 0 1, 0 0))",
        expected_valid=False,
        expected_type="Polygon",
        description="Tiny self-intersection (< 1mm)"
    ),
    GeometryTestCase(
        name="sliver_polygon",
        wkt="POLYGON((0 0, 100 0, 100 0.001, 0 0.001, 0 0))",
        expected_valid=True,
        expected_type="Polygon",
        description="Sliver polygon (aspect ratio > 100000:1)"
    ),
    GeometryTestCase(
        name="hairline_gap",
        wkt="POLYGON((0 0, 1 0, 1 1, 0.5 1, 0.5 0.9999, 0.5001 0.9999, 0.5001 1, 0 1, 0 0))",
        expected_valid=True,
        expected_type="Polygon",
        description="Polygon with hairline notch"
    ),
    GeometryTestCase(
        name="coordinate_precision_limit",
        wkt="POLYGON((0.123456789012 0.123456789012, 1.123456789012 0.123456789012, 1.123456789012 1.123456789012, 0.123456789012 1.123456789012, 0.123456789012 0.123456789012))",
        expected_valid=True,
        expected_type="Polygon",
        description="Coordinates at double precision limit"
    ),

    # =========================================================================
    # BOUNDARY CASE GEOMETRIES
    # =========================================================================
    GeometryTestCase(
        name="multipolygon_touching",
        wkt="MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)), ((1 0, 2 0, 2 1, 1 1, 1 0)))",
        expected_valid=True,
        expected_type="MultiPolygon",
        description="Multipolygon parts touching at edge"
    ),
    GeometryTestCase(
        name="multipolygon_overlapping",
        wkt="MULTIPOLYGON(((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 1, 3 1, 3 3, 1 3, 1 1)))",
        expected_valid=False,
        expected_type="MultiPolygon",
        description="Multipolygon with overlapping parts"
    ),
    GeometryTestCase(
        name="line_zero_length",
        wkt="LINESTRING(0 0, 0 0)",
        expected_valid=False,
        expected_type="LineString",
        description="Zero-length line (same start/end)"
    ),
    GeometryTestCase(
        name="line_near_zero_length",
        wkt="LINESTRING(0 0, 0.0001 0.0001)",
        expected_valid=True,
        expected_type="LineString",
        description="Near-zero length line"
    ),

    # =========================================================================
    # GEOS/PostGIS VALIDATION ERROR CASES (ST_IsValidReason)
    # =========================================================================
    GeometryTestCase(
        name="hole_outside_shell",
        wkt="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0), (2 2, 3 2, 3 3, 2 3, 2 2))",
        expected_valid=False,
        expected_type="Polygon",
        description="Hole lies outside shell"
    ),
    GeometryTestCase(
        name="nested_holes",
        wkt="POLYGON((0 0, 10 0, 10 10, 0 10, 0 0), (1 1, 9 1, 9 9, 1 9, 1 1), (2 2, 8 2, 8 8, 2 8, 2 2))",
        expected_valid=False,
        expected_type="Polygon",
        description="Holes are nested (overlap each other)"
    ),
    GeometryTestCase(
        name="disconnected_interior",
        wkt="POLYGON((0 0, 10 0, 10 10, 0 10, 0 0), (0 5, 10 5, 10 5.01, 0 5.01, 0 5))",
        expected_valid=False,
        expected_type="Polygon",
        description="Interior is disconnected by hole"
    ),
    GeometryTestCase(
        name="duplicate_rings",
        wkt="POLYGON((0 0, 10 0, 10 10, 0 10, 0 0), (2 2, 5 2, 5 5, 2 5, 2 2), (2 2, 5 2, 5 5, 2 5, 2 2))",
        expected_valid=False,
        expected_type="Polygon",
        description="Geometry contains duplicate rings"
    ),
    GeometryTestCase(
        name="too_few_points",
        wkt="POLYGON((0 0, 1 0, 0 0))",
        expected_valid=False,
        expected_type="Polygon",
        description="Too few points (LinearRing needs >= 4)"
    ),
    GeometryTestCase(
        name="ring_self_intersection",
        wkt="POLYGON((0 0, 2 2, 2 0, 0 2, 0 0))",
        expected_valid=False,
        expected_type="Polygon",
        description="Ring self-intersection (crosses itself)"
    ),

    # =========================================================================
    # QGIS GEOMETRY CHECKER SPECIFIC CASES
    # =========================================================================
    GeometryTestCase(
        name="self_contact",
        wkt="POLYGON((0 0, 2 0, 2 1, 1 1, 1 0.5, 1 1, 0 1, 0 0))",
        expected_valid=False,
        expected_type="Polygon",
        description="Self-contact (vertex touches same ring twice)"
    ),
    GeometryTestCase(
        name="polygon_spike_antenna",
        wkt="POLYGON((0 0, 1 0, 1 1, 0.5 0.5, 0.5 2, 0.5 0.5, 0 1, 0 0))",
        expected_valid=False,
        expected_type="Polygon",
        description="Spike/antenna geometry"
    ),

    # =========================================================================
    # SPECIAL COORDINATE EDGE CASES
    # =========================================================================
    GeometryTestCase(
        name="negative_coordinates",
        wkt="POLYGON((-10 -10, -5 -10, -5 -5, -10 -5, -10 -10))",
        expected_valid=True,
        expected_type="Polygon",
        description="Polygon with negative coordinates"
    ),
    GeometryTestCase(
        name="mixed_sign_coordinates",
        wkt="POLYGON((-1 -1, 1 -1, 1 1, -1 1, -1 -1))",
        expected_valid=True,
        expected_type="Polygon",
        description="Polygon crossing coordinate axes"
    ),
    GeometryTestCase(
        name="very_large_coordinates",
        wkt="POLYGON((1e7 1e7, 1e7+1 1e7, 1e7+1 1e7+1, 1e7 1e7+1, 1e7 1e7))",
        expected_valid=True,
        expected_type="Polygon",
        description="Polygon with very large coordinates"
    ),

    # =========================================================================
    # 3D GEOMETRY (Z COORDINATE) EDGE CASES
    # =========================================================================
    GeometryTestCase(
        name="polygon_z",
        wkt="POLYGON Z((0 0 0, 1 0 0, 1 1 0, 0 1 0, 0 0 0))",
        expected_valid=True,
        expected_type="Polygon",
        description="3D polygon with Z coordinates (flat)"
    ),
    GeometryTestCase(
        name="polygon_z_tilted",
        wkt="POLYGON Z((0 0 0, 1 0 1, 1 1 2, 0 1 1, 0 0 0))",
        expected_valid=True,
        expected_type="Polygon",
        description="3D polygon tilted in Z"
    ),
    GeometryTestCase(
        name="linestring_z",
        wkt="LINESTRING Z(0 0 0, 1 1 5, 2 0 10)",
        expected_valid=True,
        expected_type="LineString",
        description="3D linestring with varying Z"
    ),
    GeometryTestCase(
        name="point_z",
        wkt="POINT Z(1 2 3)",
        expected_valid=True,
        expected_type="Point",
        description="3D point with Z coordinate"
    ),
    GeometryTestCase(
        name="linestring_z_vertical",
        wkt="LINESTRING Z(0 0 0, 0 0 10)",
        expected_valid=True,  # Valid in 3D, but projects to point in 2D
        expected_type="LineString",
        description="Vertical line (same XY, different Z)"
    ),
    GeometryTestCase(
        name="polygon_z_mismatched",
        wkt="POLYGON Z((0 0 0, 1 0 0, 1 1 5, 0 1 0, 0 0 0))",
        expected_valid=True,  # Z mismatch at closing point may be issue
        expected_type="Polygon",
        description="3D polygon with Z mismatch at closure"
    ),

    # =========================================================================
    # M COORDINATE (MEASURE) EDGE CASES
    # =========================================================================
    GeometryTestCase(
        name="linestring_m",
        wkt="LINESTRING M(0 0 0, 1 1 10, 2 0 20)",
        expected_valid=True,
        expected_type="LineString",
        description="Line with M (measure) values"
    ),
    GeometryTestCase(
        name="point_zm",
        wkt="POINT ZM(1 2 3 100)",
        expected_valid=True,
        expected_type="Point",
        description="Point with both Z and M"
    ),
    GeometryTestCase(
        name="polygon_zm",
        wkt="POLYGON ZM((0 0 0 0, 1 0 0 10, 1 1 0 20, 0 1 0 30, 0 0 0 40))",
        expected_valid=True,
        expected_type="Polygon",
        description="Polygon with Z and M coordinates"
    ),

    # =========================================================================
    # GEOMETRY COLLECTION EDGE CASES
    # =========================================================================
    GeometryTestCase(
        name="geometry_collection_mixed",
        wkt="GEOMETRYCOLLECTION(POINT(0 0), LINESTRING(0 0, 1 1), POLYGON((0 0, 1 0, 1 1, 0 1, 0 0)))",
        expected_valid=True,
        expected_type="GeometryCollection",
        description="Collection with mixed geometry types"
    ),
    GeometryTestCase(
        name="geometry_collection_empty",
        wkt="GEOMETRYCOLLECTION EMPTY",
        expected_valid=True,
        expected_type="GeometryCollection",
        description="Empty geometry collection"
    ),
    GeometryTestCase(
        name="geometry_collection_nested",
        wkt="GEOMETRYCOLLECTION(GEOMETRYCOLLECTION(POINT(0 0)))",
        expected_valid=True,
        expected_type="GeometryCollection",
        description="Nested geometry collection"
    ),
]


# =============================================================================
# FIELD VALUE EDGE CASES
# =============================================================================

FIELD_VALUE_EDGE_CASES: List[FieldTestCase] = [
    # String fields
    FieldTestCase(
        name="normal_string",
        value="Обычный текст",
        field_type=QMetaType.Type.QString,
        expected_valid=True,
        description="Normal Cyrillic text"
    ),
    FieldTestCase(
        name="empty_string",
        value="",
        field_type=QMetaType.Type.QString,
        expected_valid=True,
        description="Empty string"
    ),
    FieldTestCase(
        name="null_string",
        value=None,
        field_type=QMetaType.Type.QString,
        expected_valid=True,
        description="NULL string value"
    ),
    FieldTestCase(
        name="unicode_string",
        value="Тест: αβγδ ©®™ 日本語",
        field_type=QMetaType.Type.QString,
        expected_valid=True,
        description="Unicode with special characters"
    ),
    FieldTestCase(
        name="long_string",
        value="A" * 10000,
        field_type=QMetaType.Type.QString,
        expected_valid=True,
        description="Very long string (10K chars)"
    ),
    FieldTestCase(
        name="special_chars",
        value="Line1\nLine2\tTab\"Quote'Apos",
        field_type=QMetaType.Type.QString,
        expected_valid=True,
        description="Special characters (newline, tab, quotes)"
    ),
    FieldTestCase(
        name="sql_injection",
        value="'; DROP TABLE users; --",
        field_type=QMetaType.Type.QString,
        expected_valid=True,
        description="SQL injection attempt (should be escaped)"
    ),

    # Integer fields
    FieldTestCase(
        name="normal_int",
        value=123,
        field_type=QMetaType.Type.Int,
        expected_valid=True,
        description="Normal integer"
    ),
    FieldTestCase(
        name="zero_int",
        value=0,
        field_type=QMetaType.Type.Int,
        expected_valid=True,
        description="Zero"
    ),
    FieldTestCase(
        name="negative_int",
        value=-999,
        field_type=QMetaType.Type.Int,
        expected_valid=True,
        description="Negative integer"
    ),
    FieldTestCase(
        name="max_int",
        value=2147483647,
        field_type=QMetaType.Type.Int,
        expected_valid=True,
        description="Max 32-bit integer"
    ),
    FieldTestCase(
        name="null_int",
        value=None,
        field_type=QMetaType.Type.Int,
        expected_valid=True,
        description="NULL integer"
    ),

    # Double fields
    FieldTestCase(
        name="normal_double",
        value=123.456,
        field_type=QMetaType.Type.Double,
        expected_valid=True,
        description="Normal double"
    ),
    FieldTestCase(
        name="precision_double",
        value=0.0000001,
        field_type=QMetaType.Type.Double,
        expected_valid=True,
        description="High precision double"
    ),
    FieldTestCase(
        name="scientific_double",
        value=1.23e10,
        field_type=QMetaType.Type.Double,
        expected_valid=True,
        description="Scientific notation"
    ),
]


# =============================================================================
# CRS TEST CASES
# =============================================================================

CRS_TEST_CASES: List[Tuple[str, str, bool]] = [
    # (EPSG code, description, expected_valid)
    ("EPSG:4326", "WGS84 Geographic", True),
    ("EPSG:3857", "Web Mercator", True),
    ("EPSG:32637", "UTM Zone 37N", True),
    ("EPSG:4284", "Pulkovo 1942", True),
    ("EPSG:28404", "Pulkovo 1942 / Gauss-Kruger zone 4", True),
    ("EPSG:0", "Invalid EPSG", False),
    ("EPSG:999999", "Non-existent EPSG", False),
]


# =============================================================================
# TOPOLOGY TEST CASES
# =============================================================================

TOPOLOGY_EDGE_CASES: Dict[str, List[str]] = {
    "overlapping_polygons": [
        "POLYGON((0 0, 2 0, 2 2, 0 2, 0 0))",
        "POLYGON((1 1, 3 1, 3 3, 1 3, 1 1))",  # Overlaps first
    ],
    "adjacent_polygons": [
        "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        "POLYGON((1 0, 2 0, 2 1, 1 1, 1 0))",  # Shares edge
    ],
    "duplicate_polygons": [
        "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",  # Exact duplicate
    ],
    "gap_polygons": [
        "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        "POLYGON((1.01 0, 2 0, 2 1, 1.01 1, 1.01 0))",  # Gap between
    ],
    "nested_polygons": [
        "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))",
        "POLYGON((2 2, 8 2, 8 8, 2 8, 2 2))",  # Inside first
    ],
}


# =============================================================================
# ERROR HANDLING TEST CASES
# =============================================================================

@dataclass
class ErrorTestCase:
    """Test case for error handling validation"""
    name: str
    input_value: Any
    expected_error_type: str  # Exception class name as string
    description: str = ""


ERROR_HANDLING_CASES: List[ErrorTestCase] = [
    # Layer loading errors
    ErrorTestCase(
        name="none_path",
        input_value=None,
        expected_error_type="TypeError",
        description="None as layer path"
    ),
    ErrorTestCase(
        name="empty_path",
        input_value="",
        expected_error_type="ValueError",
        description="Empty string as layer path"
    ),
    ErrorTestCase(
        name="nonexistent_file",
        input_value="/nonexistent/path/file.gpkg",
        expected_error_type="FileNotFoundError",
        description="Non-existent file path"
    ),
    ErrorTestCase(
        name="invalid_uri",
        input_value="invalid://not_a_real_uri",
        expected_error_type="ValueError",
        description="Invalid URI scheme"
    ),

    # Geometry errors
    ErrorTestCase(
        name="invalid_wkt",
        input_value="NOT_A_VALID_WKT",
        expected_error_type="ValueError",
        description="Invalid WKT string"
    ),
    ErrorTestCase(
        name="empty_wkt",
        input_value="",
        expected_error_type="ValueError",
        description="Empty WKT string"
    ),
    ErrorTestCase(
        name="incomplete_polygon",
        input_value="POLYGON((0 0, 1 0, 1 1))",
        expected_error_type="ValueError",
        description="Unclosed polygon ring"
    ),

    # CRS errors
    ErrorTestCase(
        name="invalid_epsg",
        input_value="EPSG:0",
        expected_error_type="ValueError",
        description="Invalid EPSG code (0)"
    ),
    ErrorTestCase(
        name="malformed_crs",
        input_value="NOT_A_CRS",
        expected_error_type="ValueError",
        description="Malformed CRS string"
    ),

    # Field value errors
    ErrorTestCase(
        name="string_to_int",
        input_value="not_a_number",
        expected_error_type="TypeError",
        description="String value for integer field"
    ),
    ErrorTestCase(
        name="overflow_int",
        input_value=2**63,
        expected_error_type="OverflowError",
        description="Integer overflow (64-bit)"
    ),
]


# Input validation scenarios (for parametrized testing)
INPUT_VALIDATION_CASES: List[Tuple[str, Any, bool]] = [
    # (input_type, value, should_raise)
    ("layer_path", None, True),
    ("layer_path", "", True),
    ("layer_path", "/valid/path.gpkg", False),
    ("wkt", None, True),
    ("wkt", "", True),
    ("wkt", "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))", False),
    ("crs", None, True),
    ("crs", "", True),
    ("crs", "EPSG:4326", False),
    ("field_name", None, True),
    ("field_name", "", True),
    ("field_name", "valid_field", False),
]


# File operation error scenarios
FILE_ERROR_CASES: Dict[str, Dict[str, Any]] = {
    "read_nonexistent": {
        "operation": "read",
        "path": "/nonexistent/file.gpkg",
        "expected_error": "FileNotFoundError",
    },
    "write_readonly": {
        "operation": "write",
        "path": "C:\\Windows\\System32\\test.gpkg",  # Usually not writable
        "expected_error": "PermissionError",
    },
    "write_invalid_dir": {
        "operation": "write",
        "path": "/nonexistent_dir/file.gpkg",
        "expected_error": "FileNotFoundError",
    },
    "load_corrupted": {
        "operation": "load",
        "path": "corrupted.gpkg",  # Would need actual corrupted file
        "expected_error": "RuntimeError",
    },
}


# =============================================================================
# ERROR HANDLING HELPER CLASS
# =============================================================================

class ErrorTestRunner:
    """Helper for running error handling tests"""

    def __init__(self, logger):
        self.logger = logger
        self.passed = 0
        self.failed = 0

    def test_raises(
        self,
        func,
        args: tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
        expected_error: str = "Exception",
        test_name: str = ""
    ) -> bool:
        """
        Test that a function raises the expected error

        Args:
            func: Function to test
            args: Positional arguments
            kwargs: Keyword arguments
            expected_error: Expected exception class name
            test_name: Name for logging

        Returns:
            True if expected error was raised
        """
        actual_kwargs = kwargs if kwargs is not None else {}

        try:
            func(*args, **actual_kwargs)
            # No exception raised - test failed
            self.logger.fail(f"{test_name}: No exception raised (expected {expected_error})")
            self.failed += 1
            return False
        except Exception as e:
            actual_error = type(e).__name__
            if actual_error == expected_error or expected_error in str(type(e).__mro__):
                self.logger.success(f"{test_name}: Raised {actual_error}")
                self.passed += 1
                return True
            else:
                self.logger.fail(f"{test_name}: Raised {actual_error} (expected {expected_error})")
                self.failed += 1
                return False

    def test_no_raise(
        self,
        func,
        args: tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
        test_name: str = ""
    ) -> bool:
        """
        Test that a function does NOT raise an error

        Returns:
            True if no exception was raised
        """
        actual_kwargs = kwargs if kwargs is not None else {}

        try:
            func(*args, **actual_kwargs)
            self.logger.success(f"{test_name}: No exception")
            self.passed += 1
            return True
        except Exception as e:
            self.logger.fail(f"{test_name}: Unexpected {type(e).__name__}: {e}")
            self.failed += 1
            return False

    def run_error_cases(self, test_cases: List[ErrorTestCase], test_func):
        """
        Run all error test cases

        Args:
            test_cases: List of ErrorTestCase
            test_func: Function(input_value) that should raise expected error
        """
        self.logger.section(f"Error Handling Tests ({len(test_cases)} cases)")

        for case in test_cases:
            self.test_raises(
                test_func,
                args=(case.input_value,),
                expected_error=case.expected_error_type,
                test_name=case.name
            )

    def get_results(self) -> Tuple[int, int]:
        """Return (passed, failed) counts"""
        return self.passed, self.failed


# =============================================================================
# FIXTURE FACTORY FUNCTIONS
# =============================================================================

class TestFixtures:
    """Factory for creating test fixtures"""

    @staticmethod
    def create_memory_layer(
        name: str,
        geometry_type: str = "Polygon",
        crs: str = "EPSG:4326",
        fields: Optional[List[Tuple[str, int]]] = None
    ) -> QgsVectorLayer:
        """
        Create a memory layer for testing

        Args:
            name: Layer name
            geometry_type: Point, LineString, Polygon, etc.
            crs: CRS as EPSG string
            fields: List of (field_name, QMetaType.Type)

        Returns:
            QgsVectorLayer in memory
        """
        # Build URI
        uri_parts = [f"{geometry_type}?crs={crs.lower()}"]

        if fields:
            for field_name, field_type in fields:
                type_name = TestFixtures._qmetatype_to_string(field_type)
                uri_parts.append(f"field={field_name}:{type_name}")

        uri = "&".join(uri_parts)
        layer = QgsVectorLayer(uri, name, "memory")

        return layer

    @staticmethod
    def _qmetatype_to_string(qmeta_type: int) -> str:
        """Convert QMetaType.Type to string for URI"""
        type_map = {
            QMetaType.Type.Int: "integer",
            QMetaType.Type.Double: "double",
            QMetaType.Type.QString: "string",
            QMetaType.Type.QDate: "date",
            QMetaType.Type.QDateTime: "datetime",
            QMetaType.Type.Bool: "boolean",
        }
        return type_map.get(qmeta_type, "string")

    @staticmethod
    def add_feature_from_wkt(
        layer: QgsVectorLayer,
        wkt: str,
        attributes: Optional[List[Any]] = None
    ) -> Optional[QgsFeature]:
        """
        Add a feature to layer from WKT

        Args:
            layer: Target layer
            wkt: WKT geometry string
            attributes: Optional attribute values

        Returns:
            Created feature or None on error
        """
        if not layer.isValid():
            return None

        geom = QgsGeometry.fromWkt(wkt)
        if geom.isNull():
            return None

        feature = QgsFeature(layer.fields())
        feature.setGeometry(geom)

        if attributes:
            feature.setAttributes(attributes)

        layer.dataProvider().addFeature(feature)
        return feature

    @staticmethod
    def create_test_layer_with_cases(
        test_cases: List[GeometryTestCase],
        layer_name: str = "test_geometries"
    ) -> QgsVectorLayer:
        """
        Create a layer with geometries from test cases

        Args:
            test_cases: List of GeometryTestCase
            layer_name: Name for the layer

        Returns:
            QgsVectorLayer with test geometries
        """
        # Determine geometry type from first valid case
        geom_type = "Polygon"
        for case in test_cases:
            if case.wkt and case.expected_type:
                if "Point" in case.expected_type:
                    geom_type = "Point"
                elif "Line" in case.expected_type:
                    geom_type = "LineString"
                break

        layer = TestFixtures.create_memory_layer(
            layer_name,
            geom_type,
            fields=[
                ("case_name", QMetaType.Type.QString),
                ("expected_valid", QMetaType.Type.Bool),
                ("description", QMetaType.Type.QString),
            ]
        )

        for case in test_cases:
            if case.wkt:
                TestFixtures.add_feature_from_wkt(
                    layer,
                    case.wkt,
                    [case.name, case.expected_valid, case.description]
                )

        return layer


# =============================================================================
# PARAMETRIZED TEST HELPER
# =============================================================================

class ParametrizedTestRunner:
    """Helper for running parametrized tests with the existing TestLogger"""

    def __init__(self, logger):
        self.logger = logger
        self.passed = 0
        self.failed = 0

    def run_parametrized(
        self,
        test_name: str,
        test_cases: List[Any],
        test_func,
        case_name_func=None
    ):
        """
        Run a test function with multiple test cases

        Args:
            test_name: Name of the test group
            test_cases: List of test case objects
            test_func: Function(case) -> bool
            case_name_func: Optional function to get case name
        """
        self.logger.section(f"{test_name} ({len(test_cases)} cases)")

        for case in test_cases:
            case_name = case_name_func(case) if case_name_func else str(case)
            try:
                result = test_func(case)
                if result:
                    self.logger.success(f"{case_name}")
                    self.passed += 1
                else:
                    self.logger.fail(f"{case_name}")
                    self.failed += 1
            except Exception as e:
                self.logger.fail(f"{case_name}: {e}")
                self.failed += 1

    def get_results(self) -> Tuple[int, int]:
        """Return (passed, failed) counts"""
        return self.passed, self.failed
