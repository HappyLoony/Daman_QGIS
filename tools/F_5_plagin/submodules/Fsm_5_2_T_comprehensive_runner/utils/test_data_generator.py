# -*- coding: utf-8 -*-
"""
test_data_generator.py - Generate random test data

Provides:
- Random geometry generation
- Random attribute generation
- Bulk data generation for stress testing
"""

from typing import List, Tuple, Optional, Dict, Any
import random
import math
import string
from datetime import datetime, timedelta

from qgis.core import (
    QgsGeometry, QgsPointXY, QgsVectorLayer, QgsFeature,
    QgsField
)
from qgis.PyQt.QtCore import QMetaType, QDate, QDateTime


# =============================================================================
# GEOMETRY GENERATORS
# =============================================================================

def generate_random_polygon(
    center: Tuple[float, float] = (0, 0),
    size: float = 1.0,
    num_vertices: int = 4,
    regularity: float = 0.8
) -> QgsGeometry:
    """
    Generate a random polygon

    Args:
        center: Center point (x, y)
        size: Approximate size (radius)
        num_vertices: Number of vertices
        regularity: 0-1, how regular the shape is (1=perfect, 0=chaotic)

    Returns:
        QgsGeometry polygon
    """
    cx, cy = center
    points = []

    for i in range(num_vertices):
        # Base angle for this vertex
        angle = 2 * math.pi * i / num_vertices

        # Add some randomness
        angle_jitter = (1 - regularity) * (random.random() - 0.5) * (2 * math.pi / num_vertices)
        angle += angle_jitter

        # Random radius
        radius_jitter = (1 - regularity) * (random.random() - 0.5) * 0.5 + 1.0
        radius = size * radius_jitter

        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        points.append(f"{x:.6f} {y:.6f}")

    # Close the ring
    points.append(points[0])

    wkt = f"POLYGON(({', '.join(points)}))"
    return QgsGeometry.fromWkt(wkt)


def generate_random_points(
    count: int,
    bounds: Tuple[float, float, float, float] = (0, 0, 10, 10)
) -> List[QgsGeometry]:
    """
    Generate random points within bounds

    Args:
        count: Number of points
        bounds: (xmin, ymin, xmax, ymax)

    Returns:
        List of QgsGeometry points
    """
    xmin, ymin, xmax, ymax = bounds
    points = []

    for _ in range(count):
        x = random.uniform(xmin, xmax)
        y = random.uniform(ymin, ymax)
        points.append(QgsGeometry.fromPointXY(QgsPointXY(x, y)))

    return points


def generate_grid_polygons(
    rows: int,
    cols: int,
    cell_size: float = 1.0,
    origin: Tuple[float, float] = (0, 0)
) -> List[QgsGeometry]:
    """
    Generate a grid of non-overlapping polygons

    Args:
        rows: Number of rows
        cols: Number of columns
        cell_size: Size of each cell
        origin: Bottom-left corner

    Returns:
        List of QgsGeometry polygons
    """
    ox, oy = origin
    polygons = []

    for r in range(rows):
        for c in range(cols):
            x = ox + c * cell_size
            y = oy + r * cell_size
            wkt = (
                f"POLYGON(("
                f"{x} {y}, {x+cell_size} {y}, "
                f"{x+cell_size} {y+cell_size}, {x} {y+cell_size}, "
                f"{x} {y}"
                f"))"
            )
            polygons.append(QgsGeometry.fromWkt(wkt))

    return polygons


def generate_random_line(
    start: Tuple[float, float] = (0, 0),
    num_vertices: int = 5,
    segment_length: float = 1.0,
    angle_variance: float = 0.5
) -> QgsGeometry:
    """
    Generate a random linestring

    Args:
        start: Starting point
        num_vertices: Number of vertices
        segment_length: Approximate length of each segment
        angle_variance: How much direction can change (0-1)

    Returns:
        QgsGeometry linestring
    """
    points = [start]
    current_angle = random.uniform(0, 2 * math.pi)

    for _ in range(num_vertices - 1):
        # Vary the angle
        current_angle += (random.random() - 0.5) * angle_variance * math.pi

        # Vary the length
        length = segment_length * (0.5 + random.random())

        # Calculate next point
        last_x, last_y = points[-1]
        new_x = last_x + length * math.cos(current_angle)
        new_y = last_y + length * math.sin(current_angle)
        points.append((new_x, new_y))

    wkt = "LINESTRING(" + ", ".join(f"{x:.6f} {y:.6f}" for x, y in points) + ")"
    return QgsGeometry.fromWkt(wkt)


# =============================================================================
# ATTRIBUTE GENERATORS
# =============================================================================

def generate_random_string(
    length: int = 10,
    charset: str = "letters"
) -> str:
    """
    Generate a random string

    Args:
        length: String length
        charset: "letters", "digits", "alphanumeric", "cyrillic"
    """
    if charset == "letters":
        chars = string.ascii_letters
    elif charset == "digits":
        chars = string.digits
    elif charset == "alphanumeric":
        chars = string.ascii_letters + string.digits
    elif charset == "cyrillic":
        # Cyrillic alphabet range
        chars = "".join(chr(i) for i in range(0x0410, 0x0450))
    else:
        chars = string.ascii_letters

    return "".join(random.choice(chars) for _ in range(length))


def generate_random_int(min_val: int = 0, max_val: int = 1000) -> int:
    """Generate random integer"""
    return random.randint(min_val, max_val)


def generate_random_double(min_val: float = 0.0, max_val: float = 1000.0, precision: int = 2) -> float:
    """Generate random double with specified precision"""
    value = random.uniform(min_val, max_val)
    return round(value, precision)


def generate_random_date(
    start_year: int = 2000,
    end_year: int = 2025
) -> QDate:
    """Generate random date"""
    start = datetime(start_year, 1, 1)
    end = datetime(end_year, 12, 31)
    delta = end - start
    random_days = random.randint(0, delta.days)
    random_date = start + timedelta(days=random_days)
    return QDate(random_date.year, random_date.month, random_date.day)


def generate_random_datetime(
    start_year: int = 2000,
    end_year: int = 2025
) -> QDateTime:
    """Generate random datetime"""
    date = generate_random_date(start_year, end_year)
    hour = random.randint(0, 23)
    minute = random.randint(0, 59)
    second = random.randint(0, 59)
    return QDateTime(date, QDateTime.currentDateTime().time())


# =============================================================================
# TEST DATA GENERATOR CLASS
# =============================================================================

class TestDataGenerator:
    """Comprehensive test data generator"""

    def __init__(self, seed: Optional[int] = None):
        """
        Initialize generator with optional seed for reproducibility

        Args:
            seed: Random seed for reproducible tests
        """
        if seed is not None:
            random.seed(seed)

    def generate_polygon_layer_data(
        self,
        feature_count: int = 10,
        bounds: Tuple[float, float, float, float] = (0, 0, 100, 100)
    ) -> List[Dict[str, Any]]:
        """
        Generate data for a polygon layer

        Returns:
            List of {geometry: QgsGeometry, attributes: dict}
        """
        xmin, ymin, xmax, ymax = bounds
        data = []

        for i in range(feature_count):
            # Random center within bounds
            cx = random.uniform(xmin + 5, xmax - 5)
            cy = random.uniform(ymin + 5, ymax - 5)
            size = random.uniform(1, 5)

            geom = generate_random_polygon(
                center=(cx, cy),
                size=size,
                num_vertices=random.randint(4, 8),
                regularity=random.uniform(0.6, 1.0)
            )

            data.append({
                "geometry": geom,
                "attributes": {
                    "id": i + 1,
                    "name": f"polygon_{i+1}",
                    "area": geom.area(),
                    "perimeter": geom.length(),
                }
            })

        return data

    def generate_stress_test_data(
        self,
        feature_count: int = 1000,
        geometry_type: str = "polygon"
    ) -> List[QgsGeometry]:
        """
        Generate large amount of data for stress testing

        Args:
            feature_count: Number of features
            geometry_type: "polygon", "line", "point"

        Returns:
            List of geometries
        """
        geometries = []

        for i in range(feature_count):
            if geometry_type == "polygon":
                geom = generate_random_polygon(
                    center=(i % 100, i // 100),
                    size=0.4,
                    num_vertices=random.randint(4, 6)
                )
            elif geometry_type == "line":
                geom = generate_random_line(
                    start=(i % 100, i // 100),
                    num_vertices=random.randint(3, 10)
                )
            else:  # point
                geom = QgsGeometry.fromPointXY(
                    QgsPointXY(random.uniform(0, 1000), random.uniform(0, 1000))
                )

            geometries.append(geom)

        return geometries

    def generate_edge_case_attributes(self) -> List[Dict[str, Any]]:
        """
        Generate attribute values that are edge cases

        Returns:
            List of attribute dictionaries
        """
        return [
            {"type": "null", "value": None},
            {"type": "empty_string", "value": ""},
            {"type": "long_string", "value": "A" * 10000},
            {"type": "unicode", "value": "Тест: \u2603 \u2764 \u2605"},
            {"type": "special_chars", "value": "Line1\nLine2\tTab\"Quote'Apos"},
            {"type": "sql_injection", "value": "'; DROP TABLE users; --"},
            {"type": "zero", "value": 0},
            {"type": "negative", "value": -999999},
            {"type": "max_int", "value": 2147483647},
            {"type": "min_int", "value": -2147483648},
            {"type": "float_precision", "value": 0.0000001},
            {"type": "float_large", "value": 1e308},
            {"type": "bool_true", "value": True},
            {"type": "bool_false", "value": False},
        ]

    def populate_layer(
        self,
        layer: QgsVectorLayer,
        feature_count: int = 10,
        geometry_generator=None
    ) -> int:
        """
        Populate a layer with random features

        Args:
            layer: Target layer
            feature_count: Number of features to add
            geometry_generator: Optional custom geometry generator

        Returns:
            Number of features added
        """
        if geometry_generator is None:
            geometry_generator = lambda i: generate_random_polygon(
                center=(i * 2, 0),
                size=1.0
            )

        added = 0
        for i in range(feature_count):
            feature = QgsFeature(layer.fields())
            feature.setGeometry(geometry_generator(i))

            # Set attributes based on field types
            attrs = []
            for field in layer.fields():
                field_type = field.type()
                if field_type == QMetaType.Type.Int:
                    attrs.append(i + 1)
                elif field_type == QMetaType.Type.Double:
                    attrs.append(random.uniform(0, 100))
                elif field_type == QMetaType.Type.QString:
                    attrs.append(f"feature_{i+1}")
                elif field_type == QMetaType.Type.Bool:
                    attrs.append(random.choice([True, False]))
                else:
                    attrs.append(None)

            feature.setAttributes(attrs)

            if layer.dataProvider().addFeature(feature):
                added += 1

        return added
