# -*- coding: utf-8 -*-
"""
geometry_fixtures.py - Test geometries for various scenarios

Categories:
- Valid geometries (should pass validation)
- Invalid geometries (should fail validation)
- Boundary cases (edge cases for precision/size)
- Topology test geometries (overlaps, gaps, duplicates)
"""

from typing import List, Dict, Optional
from dataclasses import dataclass

from qgis.core import QgsGeometry, QgsPointXY


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _generate_circle_polygon(num_points: int, radius: float = 1.0) -> str:
    """Generate a circular polygon with many vertices"""
    import math
    points = []
    for i in range(num_points):
        angle = 2 * math.pi * i / num_points
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        points.append(f"{x:.6f} {y:.6f}")
    points.append(points[0])  # Close the ring
    return f"POLYGON(({', '.join(points)}))"


# =============================================================================
# POLYGON WKT COLLECTIONS
# =============================================================================

VALID_POLYGONS: List[str] = [
    # Simple shapes
    "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",  # Square
    "POLYGON((0 0, 2 0, 1 2, 0 0))",  # Triangle
    "POLYGON((0 0, 4 0, 4 3, 2 3, 2 2, 0 2, 0 0))",  # L-shape

    # With holes
    "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0), (2 2, 8 2, 8 8, 2 8, 2 2))",

    # Complex valid
    "POLYGON((0 0, 10 0, 10 5, 8 5, 8 3, 6 3, 6 5, 4 5, 4 3, 2 3, 2 5, 0 5, 0 0))",
]

INVALID_POLYGONS: List[str] = [
    # Self-intersection (bowtie)
    "POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))",

    # Spike/antenna
    "POLYGON((0 0, 1 0, 1 1, 0.5 0.5, 0.5 2, 0.5 0.5, 0 1, 0 0))",

    # Duplicate consecutive points creating spike
    "POLYGON((0 0, 1 0, 1 0, 1 1, 0 1, 0 0))",
]

BOUNDARY_POLYGONS: Dict[str, str] = {
    # Precision edge cases
    "micro_01cm": "POLYGON((0 0, 0.01 0, 0.01 0.01, 0 0.01, 0 0))",
    "micro_1mm": "POLYGON((0 0, 0.001 0, 0.001 0.001, 0 0.001, 0 0))",

    # Large areas
    "large_1000km": "POLYGON((0 0, 1000000 0, 1000000 1000000, 0 1000000, 0 0))",

    # Near-degenerate (very thin)
    "thin_strip": "POLYGON((0 0, 1000 0, 1000 0.01, 0 0.01, 0 0))",

    # Many vertices
    "many_vertices": _generate_circle_polygon(100),
}

VALID_LINES: List[str] = [
    "LINESTRING(0 0, 1 1)",  # Minimum line
    "LINESTRING(0 0, 1 0, 1 1, 0 1)",  # Polyline
    "LINESTRING(0 0, 1 0, 1 1, 0 1, 0 0)",  # Closed ring
]

VALID_POINTS: List[str] = [
    "POINT(0 0)",
    "POINT(100.123456 50.654321)",
    "MULTIPOINT((0 0), (1 1), (2 2))",
]


# =============================================================================
# DEGENERATE GEOMETRY CASES (PostGIS/ArcGIS best practices)
# =============================================================================

DEGENERATE_POLYGONS: Dict[str, str] = {
    # Duplicate vertices
    "duplicate_vertices": "POLYGON((0 0, 1 0, 1 0, 1 1, 0 1, 0 0))",

    # Zero-area shapes
    "zero_area_spike": "POLYGON((0 0, 1 0, 0.5 0.5, 1 0, 1 1, 0 1, 0 0))",
    "collapsed_to_line": "POLYGON((0 0, 1 0, 2 0, 1 0, 0 0))",

    # Collinear points
    "collinear_points": "POLYGON((0 0, 0.5 0, 1 0, 1 1, 0 1, 0 0))",

    # Empty geometry
    "empty_polygon": "POLYGON EMPTY",
}


# =============================================================================
# BANANA POLYGONS AND TOUCHING RINGS
# =============================================================================

BANANA_POLYGONS: Dict[str, str] = {
    # Concave banana shape
    "banana_shape": "POLYGON((0 0, 5 0, 5 1, 3 1, 3 0.5, 2 0.5, 2 1, 0 1, 0 0))",

    # Ring touching at single point
    "hole_touching_outer": "POLYGON((0 0, 2 0, 2 2, 0 2, 0 0), (1 0, 1.5 0.5, 1 1, 0.5 0.5, 1 0))",

    # Inverted shell (CCW outer ring)
    "inverted_shell": "POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))",

    # Figure-eight (self-touching)
    "figure_eight": "POLYGON((0 0, 1 1, 2 0, 2 2, 1 1, 0 2, 0 0))",

    # Exverted hole (CW instead of CCW)
    "exverted_hole": "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0), (2 2, 2 8, 8 8, 8 2, 2 2))",
}


# =============================================================================
# MICRO-PRECISION EDGE CASES
# =============================================================================

PRECISION_EDGE_CASES: Dict[str, str] = {
    # Near-coincident vertices
    "near_coincident": "POLYGON((0 0, 1 0, 1.00000001 0.00000001, 1 1, 0 1, 0 0))",

    # Tiny self-intersection (< 1mm)
    "micro_self_intersection": "POLYGON((0 0, 1 0, 0.5 0.0001, 0.50001 0, 1 1, 0 1, 0 0))",

    # Sliver polygon (extreme aspect ratio)
    "sliver_polygon": "POLYGON((0 0, 100 0, 100 0.001, 0 0.001, 0 0))",

    # Hairline notch
    "hairline_notch": "POLYGON((0 0, 1 0, 1 1, 0.5 1, 0.5 0.9999, 0.5001 0.9999, 0.5001 1, 0 1, 0 0))",

    # Double precision limit
    "precision_limit": "POLYGON((0.123456789012 0.123456789012, 1.123456789012 0.123456789012, 1.123456789012 1.123456789012, 0.123456789012 1.123456789012, 0.123456789012 0.123456789012))",
}


# =============================================================================
# MULTIPART EDGE CASES
# =============================================================================

MULTIPART_EDGE_CASES: Dict[str, str] = {
    # Parts touching at edge
    "touching_parts": "MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)), ((1 0, 2 0, 2 1, 1 1, 1 0)))",

    # Overlapping parts (invalid)
    "overlapping_parts": "MULTIPOLYGON(((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 1, 3 1, 3 3, 1 3, 1 1)))",

    # Nested parts (one inside another)
    "nested_parts": "MULTIPOLYGON(((0 0, 10 0, 10 10, 0 10, 0 0)), ((2 2, 8 2, 8 8, 2 8, 2 2)))",
}


# =============================================================================
# LINE EDGE CASES
# =============================================================================

LINE_EDGE_CASES: Dict[str, str] = {
    # Zero-length line
    "zero_length": "LINESTRING(0 0, 0 0)",

    # Near-zero length
    "near_zero_length": "LINESTRING(0 0, 0.0001 0.0001)",

    # Self-crossing
    "self_crossing": "LINESTRING(0 0, 1 1, 1 0, 0 1)",

    # Duplicate vertices
    "duplicate_vertices": "LINESTRING(0 0, 0.5 0.5, 0.5 0.5, 1 1)",
}


# =============================================================================
# GEOS/PostGIS VALIDATION ERROR CASES (ST_IsValidReason errors)
# =============================================================================

GEOS_VALIDATION_ERRORS: Dict[str, str] = {
    # Hole lies outside shell
    "hole_outside_shell": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0), (2 2, 3 2, 3 3, 2 3, 2 2))",

    # Holes are nested (overlap each other)
    "nested_holes": "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0), (1 1, 9 1, 9 9, 1 9, 1 1), (2 2, 8 2, 8 8, 2 8, 2 2))",

    # Interior is disconnected
    "disconnected_interior": "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0), (0 5, 10 5, 10 5.01, 0 5.01, 0 5))",

    # Duplicate rings
    "duplicate_rings": "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0), (2 2, 5 2, 5 5, 2 5, 2 2), (2 2, 5 2, 5 5, 2 5, 2 2))",

    # Too few points (LinearRing needs >= 4)
    "too_few_points": "POLYGON((0 0, 1 0, 0 0))",

    # Ring self-intersection
    "ring_self_intersection": "POLYGON((0 0, 2 2, 2 0, 0 2, 0 0))",

    # Self-contact (vertex touches same ring twice)
    "self_contact": "POLYGON((0 0, 2 0, 2 1, 1 1, 1 0.5, 1 1, 0 1, 0 0))",

    # Spike/antenna
    "spike_antenna": "POLYGON((0 0, 1 0, 1 1, 0.5 0.5, 0.5 2, 0.5 0.5, 0 1, 0 0))",
}


# =============================================================================
# COORDINATE EDGE CASES
# =============================================================================

COORDINATE_EDGE_CASES: Dict[str, str] = {
    # Negative coordinates
    "negative_coords": "POLYGON((-10 -10, -5 -10, -5 -5, -10 -5, -10 -10))",

    # Crossing coordinate axes
    "crossing_axes": "POLYGON((-1 -1, 1 -1, 1 1, -1 1, -1 -1))",

    # Very large coordinates
    "very_large": "POLYGON((1e7 1e7, 1e7+1 1e7, 1e7+1 1e7+1, 1e7 1e7+1, 1e7 1e7))",

    # Near-zero coordinates
    "near_zero": "POLYGON((0.0001 0.0001, 0.0002 0.0001, 0.0002 0.0002, 0.0001 0.0002, 0.0001 0.0001))",
}


# =============================================================================
# 3D GEOMETRY (Z COORDINATE) EDGE CASES
# =============================================================================

Z_COORDINATE_CASES: Dict[str, str] = {
    # Flat 3D polygon
    "polygon_z_flat": "POLYGON Z((0 0 0, 1 0 0, 1 1 0, 0 1 0, 0 0 0))",

    # Tilted 3D polygon
    "polygon_z_tilted": "POLYGON Z((0 0 0, 1 0 1, 1 1 2, 0 1 1, 0 0 0))",

    # 3D linestring
    "linestring_z": "LINESTRING Z(0 0 0, 1 1 5, 2 0 10)",

    # Vertical line (same XY, different Z)
    "linestring_z_vertical": "LINESTRING Z(0 0 0, 0 0 10)",

    # 3D point
    "point_z": "POINT Z(1 2 3)",

    # Z mismatch at closure
    "polygon_z_mismatch": "POLYGON Z((0 0 0, 1 0 0, 1 1 5, 0 1 0, 0 0 0))",
}


# =============================================================================
# M COORDINATE (MEASURE) EDGE CASES
# =============================================================================

M_COORDINATE_CASES: Dict[str, str] = {
    # Line with measures
    "linestring_m": "LINESTRING M(0 0 0, 1 1 10, 2 0 20)",

    # Point with Z and M
    "point_zm": "POINT ZM(1 2 3 100)",

    # Polygon with Z and M
    "polygon_zm": "POLYGON ZM((0 0 0 0, 1 0 0 10, 1 1 0 20, 0 1 0 30, 0 0 0 40))",

    # Multipoint with M
    "multipoint_m": "MULTIPOINT M((0 0 0), (1 1 10), (2 2 20))",
}


# =============================================================================
# GEOMETRY COLLECTION CASES
# =============================================================================

GEOMETRY_COLLECTION_CASES: Dict[str, str] = {
    # Mixed types
    "mixed_collection": "GEOMETRYCOLLECTION(POINT(0 0), LINESTRING(0 0, 1 1), POLYGON((0 0, 1 0, 1 1, 0 1, 0 0)))",

    # Empty collection
    "empty_collection": "GEOMETRYCOLLECTION EMPTY",

    # Nested collection
    "nested_collection": "GEOMETRYCOLLECTION(GEOMETRYCOLLECTION(POINT(0 0)))",

    # Collection with only points
    "points_collection": "GEOMETRYCOLLECTION(POINT(0 0), POINT(1 1), POINT(2 2))",
}


# =============================================================================
# GEOMETRY FIXTURES CLASS
# =============================================================================

class GeometryFixtures:
    """Factory for creating test geometries"""

    @staticmethod
    def valid_square(size: float = 1.0, origin: tuple = (0, 0)) -> QgsGeometry:
        """Create a valid square polygon"""
        x, y = origin
        wkt = f"POLYGON(({x} {y}, {x+size} {y}, {x+size} {y+size}, {x} {y+size}, {x} {y}))"
        return QgsGeometry.fromWkt(wkt)

    @staticmethod
    def valid_triangle(base: float = 1.0, height: float = 1.0) -> QgsGeometry:
        """Create a valid triangle"""
        wkt = f"POLYGON((0 0, {base} 0, {base/2} {height}, 0 0))"
        return QgsGeometry.fromWkt(wkt)

    @staticmethod
    def polygon_with_hole(
        outer_size: float = 10.0,
        inner_size: float = 5.0
    ) -> QgsGeometry:
        """Create a polygon with a hole"""
        offset = (outer_size - inner_size) / 2
        wkt = (
            f"POLYGON(("
            f"0 0, {outer_size} 0, {outer_size} {outer_size}, 0 {outer_size}, 0 0"
            f"), ("
            f"{offset} {offset}, {offset+inner_size} {offset}, "
            f"{offset+inner_size} {offset+inner_size}, {offset} {offset+inner_size}, "
            f"{offset} {offset}"
            f"))"
        )
        return QgsGeometry.fromWkt(wkt)

    @staticmethod
    def self_intersecting_bowtie() -> QgsGeometry:
        """Create an invalid self-intersecting polygon"""
        wkt = "POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))"
        return QgsGeometry.fromWkt(wkt)

    @staticmethod
    def multipolygon(count: int = 3, spacing: float = 2.0) -> QgsGeometry:
        """Create a multipolygon with several parts"""
        parts = []
        for i in range(count):
            x = i * spacing
            parts.append(f"(({x} 0, {x+1} 0, {x+1} 1, {x} 1, {x} 0))")
        wkt = f"MULTIPOLYGON({', '.join(parts)})"
        return QgsGeometry.fromWkt(wkt)

    @staticmethod
    def simple_line(length: float = 1.0) -> QgsGeometry:
        """Create a simple line"""
        wkt = f"LINESTRING(0 0, {length} {length})"
        return QgsGeometry.fromWkt(wkt)

    @staticmethod
    def closed_ring_line(size: float = 1.0) -> QgsGeometry:
        """Create a closed ring as linestring"""
        wkt = f"LINESTRING(0 0, {size} 0, {size} {size}, 0 {size}, 0 0)"
        return QgsGeometry.fromWkt(wkt)

    @staticmethod
    def point_at(x: float, y: float) -> QgsGeometry:
        """Create a point geometry"""
        return QgsGeometry.fromPointXY(QgsPointXY(x, y))

    @staticmethod
    def null_geometry() -> QgsGeometry:
        """Create a null/empty geometry"""
        return QgsGeometry()

    @staticmethod
    def from_wkt(wkt: str) -> Optional[QgsGeometry]:
        """Create geometry from WKT, returns None if invalid WKT"""
        geom = QgsGeometry.fromWkt(wkt)
        return geom if not geom.isNull() else None


# =============================================================================
# TOPOLOGY TEST DATA
# =============================================================================

class TopologyTestData:
    """Pre-built geometry sets for topology testing"""

    @staticmethod
    def overlapping_pair() -> List[QgsGeometry]:
        """Two overlapping polygons"""
        return [
            QgsGeometry.fromWkt("POLYGON((0 0, 2 0, 2 2, 0 2, 0 0))"),
            QgsGeometry.fromWkt("POLYGON((1 1, 3 1, 3 3, 1 3, 1 1))"),
        ]

    @staticmethod
    def adjacent_pair() -> List[QgsGeometry]:
        """Two adjacent polygons sharing an edge"""
        return [
            QgsGeometry.fromWkt("POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"),
            QgsGeometry.fromWkt("POLYGON((1 0, 2 0, 2 1, 1 1, 1 0))"),
        ]

    @staticmethod
    def duplicate_pair() -> List[QgsGeometry]:
        """Two identical polygons"""
        wkt = "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"
        return [
            QgsGeometry.fromWkt(wkt),
            QgsGeometry.fromWkt(wkt),
        ]

    @staticmethod
    def gap_pair(gap_size: float = 0.01) -> List[QgsGeometry]:
        """Two polygons with a gap between them"""
        return [
            QgsGeometry.fromWkt("POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"),
            QgsGeometry.fromWkt(
                f"POLYGON(({1+gap_size} 0, 2 0, 2 1, {1+gap_size} 1, {1+gap_size} 0))"
            ),
        ]

    @staticmethod
    def nested_pair() -> List[QgsGeometry]:
        """One polygon inside another"""
        return [
            QgsGeometry.fromWkt("POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))"),
            QgsGeometry.fromWkt("POLYGON((2 2, 8 2, 8 8, 2 8, 2 2))"),
        ]

    @staticmethod
    def valid_tessellation(rows: int = 2, cols: int = 2) -> List[QgsGeometry]:
        """Grid of non-overlapping adjacent polygons"""
        geometries = []
        for r in range(rows):
            for c in range(cols):
                wkt = f"POLYGON(({c} {r}, {c+1} {r}, {c+1} {r+1}, {c} {r+1}, {c} {r}))"
                geometries.append(QgsGeometry.fromWkt(wkt))
        return geometries
