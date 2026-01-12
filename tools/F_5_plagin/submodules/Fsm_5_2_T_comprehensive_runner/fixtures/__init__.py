# -*- coding: utf-8 -*-
"""
fixtures/ - Test fixtures for QGIS plugin testing

Provides ready-to-use test data:
- Layers (memory, file-based)
- Geometries (valid, invalid, edge cases)
- Projects (clean, with layers)
- Field values (all types)
"""

from .geometry_fixtures import (
    GeometryFixtures,
    VALID_POLYGONS,
    INVALID_POLYGONS,
    BOUNDARY_POLYGONS,
    VALID_LINES,
    VALID_POINTS,
    # Edge case collections (PostGIS/ArcGIS/GEOS best practices)
    DEGENERATE_POLYGONS,
    BANANA_POLYGONS,
    PRECISION_EDGE_CASES,
    MULTIPART_EDGE_CASES,
    LINE_EDGE_CASES,
    GEOS_VALIDATION_ERRORS,
    COORDINATE_EDGE_CASES,
    # 3D/Z/M coordinate cases
    Z_COORDINATE_CASES,
    M_COORDINATE_CASES,
    GEOMETRY_COLLECTION_CASES,
)

from .layer_fixtures import (
    LayerFixtures,
    TempLayerFixtures,
    DataProviderFixtures,
    create_polygon_layer,
    create_line_layer,
    create_point_layer,
    create_layer_with_all_field_types,
    PROVIDER_TEST_CASES,
    CRS_PROVIDER_COMBINATIONS,
)

from .project_fixtures import (
    ProjectFixtures,
    create_test_project,
    cleanup_test_project,
)

__all__ = [
    # Geometry fixtures
    "GeometryFixtures",
    "VALID_POLYGONS",
    "INVALID_POLYGONS",
    "BOUNDARY_POLYGONS",
    "VALID_LINES",
    "VALID_POINTS",
    # Edge case collections (PostGIS/ArcGIS/GEOS)
    "DEGENERATE_POLYGONS",
    "BANANA_POLYGONS",
    "PRECISION_EDGE_CASES",
    "MULTIPART_EDGE_CASES",
    "LINE_EDGE_CASES",
    "GEOS_VALIDATION_ERRORS",
    "COORDINATE_EDGE_CASES",
    # 3D/Z/M coordinate cases
    "Z_COORDINATE_CASES",
    "M_COORDINATE_CASES",
    "GEOMETRY_COLLECTION_CASES",

    # Layer fixtures
    "LayerFixtures",
    "TempLayerFixtures",
    "DataProviderFixtures",
    "create_polygon_layer",
    "create_line_layer",
    "create_point_layer",
    "create_layer_with_all_field_types",
    "PROVIDER_TEST_CASES",
    "CRS_PROVIDER_COMBINATIONS",

    # Project fixtures
    "ProjectFixtures",
    "create_test_project",
    "cleanup_test_project",
]
