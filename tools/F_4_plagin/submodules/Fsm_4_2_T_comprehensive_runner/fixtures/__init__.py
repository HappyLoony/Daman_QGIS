# -*- coding: utf-8 -*-
"""
fixtures/ - Test fixtures for QGIS plugin testing

Provides ready-to-use test data:
- Layers (memory, file-based)
- Projects (clean, with layers)
"""

from .layer_fixtures import (
    LayerFixtures,
    TempLayerFixtures,
    create_polygon_layer,
    create_line_layer,
    create_point_layer,
    create_layer_with_all_field_types,
)

from .project_fixtures import (
    ProjectFixtures,
    create_test_project,
    cleanup_test_project,
)

__all__ = [
    # Layer fixtures
    "LayerFixtures",
    "TempLayerFixtures",
    "create_polygon_layer",
    "create_line_layer",
    "create_point_layer",
    "create_layer_with_all_field_types",

    # Project fixtures
    "ProjectFixtures",
    "create_test_project",
    "cleanup_test_project",
]
