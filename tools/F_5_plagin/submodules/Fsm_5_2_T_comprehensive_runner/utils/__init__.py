# -*- coding: utf-8 -*-
"""
utils/ - Test utilities for QGIS plugin testing

Provides:
- Custom assertions for geometry/layer validation
- Test data generators
- Common test helpers
"""

from .assertions import (
    GeometryAssertions,
    LayerAssertions,
    FeatureAssertions,
    assert_geometry_valid,
    assert_geometry_equals_wkt,
    assert_layer_has_features,
    assert_field_exists,
)

from .test_data_generator import (
    TestDataGenerator,
    generate_random_polygon,
    generate_random_points,
    generate_grid_polygons,
)

__all__ = [
    # Assertions
    "GeometryAssertions",
    "LayerAssertions",
    "FeatureAssertions",
    "assert_geometry_valid",
    "assert_geometry_equals_wkt",
    "assert_layer_has_features",
    "assert_field_exists",

    # Generators
    "TestDataGenerator",
    "generate_random_polygon",
    "generate_random_points",
    "generate_grid_polygons",
]
