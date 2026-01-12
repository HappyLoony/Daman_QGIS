# -*- coding: utf-8 -*-
"""
project_fixtures.py - Test project setup and teardown

Provides:
- Clean project state for tests
- Pre-configured project with layers
- Project cleanup utilities
"""

from typing import List, Optional, Dict, Any
import os
import tempfile
import shutil

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsCoordinateReferenceSystem,
    QgsLayerTreeGroup
)

from .layer_fixtures import (
    create_polygon_layer,
    create_line_layer,
    create_point_layer,
    LayerFixtures
)


# =============================================================================
# PROJECT CLEANUP
# =============================================================================

def cleanup_test_project():
    """
    Remove all layers and reset project to clean state

    Should be called before and after each test
    """
    project = QgsProject.instance()

    # Remove all layers
    project.removeAllMapLayers()

    # Clear layer tree
    root = project.layerTreeRoot()
    root.removeAllChildren()

    # Reset project CRS to default
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

    # Clear project filename
    project.setFileName("")


def create_test_project(
    crs: str = "EPSG:4326",
    add_layers: bool = False
) -> QgsProject:
    """
    Create/reset project for testing

    Args:
        crs: Project CRS
        add_layers: Add default test layers

    Returns:
        QgsProject instance
    """
    # Clean first
    cleanup_test_project()

    project = QgsProject.instance()
    project.setCrs(QgsCoordinateReferenceSystem(crs))

    if add_layers:
        # Add some default test layers
        polygon_layer = LayerFixtures.polygon_layer_with_squares(3)
        project.addMapLayer(polygon_layer)

    return project


# =============================================================================
# PROJECT FIXTURES CLASS
# =============================================================================

class ProjectFixtures:
    """Factory for creating test project configurations"""

    @staticmethod
    def empty_project(crs: str = "EPSG:4326") -> QgsProject:
        """Create an empty project with specified CRS"""
        return create_test_project(crs, add_layers=False)

    @staticmethod
    def project_with_polygon_layer() -> QgsProject:
        """Create project with a single polygon layer"""
        project = create_test_project()
        layer = LayerFixtures.polygon_layer_with_squares(5)
        project.addMapLayer(layer)
        return project

    @staticmethod
    def project_with_all_geometry_types() -> QgsProject:
        """Create project with point, line, and polygon layers"""
        project = create_test_project()

        # Polygon layer
        polygon_layer = create_polygon_layer("polygons")
        LayerFixtures.add_feature(
            polygon_layer,
            "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
            [1, "poly", 1.0]
        )
        project.addMapLayer(polygon_layer)

        # Line layer
        line_layer = create_line_layer("lines")
        from qgis.core import QgsGeometry, QgsFeature
        line_geom = QgsGeometry.fromWkt("LINESTRING(0 0, 1 1, 2 0)")
        line_feat = QgsFeature(line_layer.fields())
        line_feat.setGeometry(line_geom)
        line_feat.setAttributes([1, "line", 2.0])
        line_layer.dataProvider().addFeature(line_feat)
        project.addMapLayer(line_layer)

        # Point layer
        point_layer = create_point_layer("points")
        point_geom = QgsGeometry.fromWkt("POINT(0.5 0.5)")
        point_feat = QgsFeature(point_layer.fields())
        point_feat.setGeometry(point_geom)
        point_feat.setAttributes([1, "point", 100.0])
        point_layer.dataProvider().addFeature(point_feat)
        project.addMapLayer(point_layer)

        return project

    @staticmethod
    def project_with_layer_groups() -> QgsProject:
        """Create project with organized layer groups"""
        project = create_test_project()
        root = project.layerTreeRoot()

        # Create groups
        base_group = root.addGroup("Base Data")
        analysis_group = root.addGroup("Analysis")

        # Add layers to groups
        base_layer = LayerFixtures.polygon_layer_with_squares(3, size=1.0)
        project.addMapLayer(base_layer, False)  # Don't add to root
        base_group.addLayer(base_layer)

        analysis_layer = LayerFixtures.polygon_layer_with_squares(2, size=0.5, spacing=3.0)
        analysis_layer.setName("analysis_result")
        project.addMapLayer(analysis_layer, False)
        analysis_group.addLayer(analysis_layer)

        return project

    @staticmethod
    def project_with_invalid_data() -> QgsProject:
        """Create project with layers containing invalid/edge case data"""
        project = create_test_project()

        # Layer with invalid geometries
        invalid_layer = LayerFixtures.polygon_layer_with_invalid_geometries()
        project.addMapLayer(invalid_layer)

        # Layer with NULL geometries
        null_layer = LayerFixtures.layer_with_null_geometries()
        project.addMapLayer(null_layer)

        # Layer with special attributes
        special_layer = LayerFixtures.layer_with_special_attributes()
        project.addMapLayer(special_layer)

        return project

    @staticmethod
    def project_with_topology_issues() -> QgsProject:
        """Create project with layers having topology problems"""
        project = create_test_project()

        topology_layer = LayerFixtures.polygon_layer_with_topology_issues()
        project.addMapLayer(topology_layer)

        return project


# =============================================================================
# TEMPORARY PROJECT FILES
# =============================================================================

class TempProjectFixtures:
    """Create temporary project files for testing save/load"""

    _temp_dirs: List[str] = []

    @classmethod
    def create_temp_project_dir(cls) -> str:
        """
        Create a temporary directory for a test project

        Returns:
            Path to temp directory
        """
        temp_dir = tempfile.mkdtemp(prefix="qgis_test_")
        cls._temp_dirs.append(temp_dir)
        return temp_dir

    @classmethod
    def create_project_structure(
        cls,
        project_name: str = "test_project"
    ) -> Dict[str, str]:
        """
        Create a typical project folder structure

        Returns:
            Dict with paths: {project_dir, gpkg_path, qgs_path}
        """
        project_dir = cls.create_temp_project_dir()

        paths = {
            "project_dir": project_dir,
            "gpkg_path": os.path.join(project_dir, "project.gpkg"),
            "qgs_path": os.path.join(project_dir, f"{project_name}.qgs"),
            "metadata_path": os.path.join(project_dir, "metadata.json"),
        }

        return paths

    @classmethod
    def cleanup_temp_dirs(cls):
        """Remove all temporary directories created during tests"""
        for temp_dir in cls._temp_dirs:
            if os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except OSError:
                    pass
        cls._temp_dirs = []

    @classmethod
    def save_current_project(cls, path: str) -> bool:
        """Save current project to file"""
        return QgsProject.instance().write(path)

    @classmethod
    def load_project(cls, path: str) -> bool:
        """Load project from file"""
        return QgsProject.instance().read(path)
