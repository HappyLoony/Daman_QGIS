# -*- coding: utf-8 -*-
"""
layer_fixtures.py - Test layer factories

Creates memory layers with various configurations for testing:
- Different geometry types
- Different CRS
- Various field configurations
- Pre-populated with test data
"""

from typing import List, Tuple, Optional, Any, Dict
import os
import tempfile

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsField,
    QgsCoordinateReferenceSystem, QgsVectorFileWriter,
    QgsProject, QgsFields
)
from qgis.PyQt.QtCore import QMetaType, QVariant


# =============================================================================
# LAYER CREATION FUNCTIONS
# =============================================================================

def create_polygon_layer(
    name: str = "test_polygons",
    crs: str = "EPSG:4326",
    with_fields: bool = True
) -> QgsVectorLayer:
    """
    Create a memory polygon layer

    Args:
        name: Layer name
        crs: Coordinate reference system
        with_fields: Add standard test fields

    Returns:
        QgsVectorLayer
    """
    uri = f"Polygon?crs={crs.lower()}"

    if with_fields:
        uri += "&field=id:integer&field=name:string&field=area:double"

    layer = QgsVectorLayer(uri, name, "memory")
    return layer


def create_line_layer(
    name: str = "test_lines",
    crs: str = "EPSG:4326",
    with_fields: bool = True
) -> QgsVectorLayer:
    """Create a memory linestring layer"""
    uri = f"LineString?crs={crs.lower()}"

    if with_fields:
        uri += "&field=id:integer&field=name:string&field=length:double"

    layer = QgsVectorLayer(uri, name, "memory")
    return layer


def create_point_layer(
    name: str = "test_points",
    crs: str = "EPSG:4326",
    with_fields: bool = True
) -> QgsVectorLayer:
    """Create a memory point layer"""
    uri = f"Point?crs={crs.lower()}"

    if with_fields:
        uri += "&field=id:integer&field=name:string&field=value:double"

    layer = QgsVectorLayer(uri, name, "memory")
    return layer


def create_layer_with_all_field_types(
    name: str = "test_all_fields",
    geometry_type: str = "Polygon",
    crs: str = "EPSG:4326"
) -> QgsVectorLayer:
    """
    Create a layer with all common field types for testing

    Fields:
        - fid: integer (primary key)
        - text_field: string
        - int_field: integer
        - double_field: double
        - date_field: date
        - datetime_field: datetime
        - bool_field: boolean
    """
    uri = (
        f"{geometry_type}?crs={crs.lower()}"
        "&field=fid:integer"
        "&field=text_field:string(255)"
        "&field=int_field:integer"
        "&field=double_field:double"
        "&field=date_field:date"
        "&field=datetime_field:datetime"
        "&field=bool_field:boolean"
    )

    layer = QgsVectorLayer(uri, name, "memory")
    return layer


# =============================================================================
# LAYER FIXTURES CLASS
# =============================================================================

class LayerFixtures:
    """Factory class for creating test layers with data"""

    @staticmethod
    def empty_polygon_layer(crs: str = "EPSG:4326") -> QgsVectorLayer:
        """Create an empty polygon layer"""
        return create_polygon_layer("empty_polygons", crs)

    @staticmethod
    def polygon_layer_with_squares(
        count: int = 5,
        size: float = 1.0,
        spacing: float = 2.0,
        crs: str = "EPSG:4326"
    ) -> QgsVectorLayer:
        """
        Create a layer with square polygons

        Args:
            count: Number of squares
            size: Size of each square
            spacing: Spacing between squares
            crs: Coordinate reference system
        """
        layer = create_polygon_layer("squares", crs)

        for i in range(count):
            x = i * spacing
            wkt = f"POLYGON(({x} 0, {x+size} 0, {x+size} {size}, {x} {size}, {x} 0))"
            LayerFixtures.add_feature(layer, wkt, [i, f"square_{i}", size * size])

        return layer

    @staticmethod
    def polygon_layer_with_invalid_geometries() -> QgsVectorLayer:
        """Create a layer with various invalid geometries for testing validators"""
        layer = create_polygon_layer("invalid_geometries")

        invalid_cases = [
            ("self_intersect", "POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))"),
            ("degenerate", "POLYGON((0 0, 0 0, 0 0, 0 0))"),
        ]

        for i, (name, wkt) in enumerate(invalid_cases):
            geom = QgsGeometry.fromWkt(wkt)
            if not geom.isNull():
                LayerFixtures.add_feature(layer, wkt, [i, name, 0.0])

        return layer

    @staticmethod
    def polygon_layer_with_topology_issues() -> QgsVectorLayer:
        """Create a layer with overlapping/duplicate polygons"""
        layer = create_polygon_layer("topology_issues")

        # Overlapping polygons
        LayerFixtures.add_feature(
            layer,
            "POLYGON((0 0, 2 0, 2 2, 0 2, 0 0))",
            [1, "poly_1", 4.0]
        )
        LayerFixtures.add_feature(
            layer,
            "POLYGON((1 1, 3 1, 3 3, 1 3, 1 1))",
            [2, "poly_2_overlap", 4.0]
        )

        # Duplicate polygon
        LayerFixtures.add_feature(
            layer,
            "POLYGON((5 0, 6 0, 6 1, 5 1, 5 0))",
            [3, "poly_3", 1.0]
        )
        LayerFixtures.add_feature(
            layer,
            "POLYGON((5 0, 6 0, 6 1, 5 1, 5 0))",
            [4, "poly_4_duplicate", 1.0]
        )

        return layer

    @staticmethod
    def multi_crs_layers() -> Dict[str, QgsVectorLayer]:
        """Create layers in different CRS for transformation testing"""
        crs_list = ["EPSG:4326", "EPSG:3857", "EPSG:32637"]
        layers = {}

        for crs in crs_list:
            layer = create_polygon_layer(f"layer_{crs.replace(':', '_')}", crs)
            # Add a simple square
            LayerFixtures.add_feature(
                layer,
                "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
                [1, f"test_{crs}", 1.0]
            )
            layers[crs] = layer

        return layers

    @staticmethod
    def layer_with_null_geometries(null_count: int = 3) -> QgsVectorLayer:
        """Create a layer with some NULL geometries"""
        layer = create_polygon_layer("null_geometries")

        # Valid geometries
        for i in range(3):
            LayerFixtures.add_feature(
                layer,
                f"POLYGON(({i} 0, {i+1} 0, {i+1} 1, {i} 1, {i} 0))",
                [i, f"valid_{i}", 1.0]
            )

        # NULL geometries
        for i in range(null_count):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([10 + i, f"null_{i}", 0.0])
            # No geometry set - will be NULL
            layer.dataProvider().addFeature(feature)

        return layer

    @staticmethod
    def layer_with_special_attributes() -> QgsVectorLayer:
        """Create a layer with special/edge case attribute values"""
        layer = create_layer_with_all_field_types("special_attributes")

        test_data = [
            # (fid, text, int, double, date, datetime, bool)
            [1, "Normal text", 100, 3.14, "2024-01-15", "2024-01-15 10:30:00", True],
            [2, "", 0, 0.0, None, None, False],  # Empty/zero/null
            [3, "A" * 255, 2147483647, 1e308, "1900-01-01", "1900-01-01 00:00:00", True],  # Max values
            [4, "Текст кириллицей", -999, -0.001, "2099-12-31", "2099-12-31 23:59:59", False],  # Unicode/negative
            [5, "Line\nBreak\tTab", None, None, None, None, None],  # Special chars / NULLs
        ]

        for data in test_data:
            feature = QgsFeature(layer.fields())
            geom = QgsGeometry.fromWkt(f"POLYGON(({data[0]} 0, {data[0]+1} 0, {data[0]+1} 1, {data[0]} 1, {data[0]} 0))")
            feature.setGeometry(geom)
            feature.setAttributes(data)
            layer.dataProvider().addFeature(feature)

        return layer

    @staticmethod
    def add_feature(
        layer: QgsVectorLayer,
        wkt: str,
        attributes: List[Any]
    ) -> bool:
        """Add a feature to layer from WKT string"""
        geom = QgsGeometry.fromWkt(wkt)
        if geom.isNull():
            return False

        feature = QgsFeature(layer.fields())
        feature.setGeometry(geom)
        feature.setAttributes(attributes)

        return layer.dataProvider().addFeature(feature)


# =============================================================================
# TEMPORARY FILE LAYERS
# =============================================================================

class TempLayerFixtures:
    """Create temporary file-based layers for testing file operations"""

    @staticmethod
    def create_temp_gpkg(
        layer_name: str = "test_layer",
        features_wkt: Optional[List[str]] = None
    ) -> Tuple[str, QgsVectorLayer]:
        """
        Create a temporary GeoPackage with a layer

        Returns:
            Tuple of (file_path, layer)
        """
        # Create temp file
        fd, path = tempfile.mkstemp(suffix=".gpkg")
        os.close(fd)

        # Create memory layer first
        layer = create_polygon_layer(layer_name)

        if features_wkt:
            for i, wkt in enumerate(features_wkt):
                LayerFixtures.add_feature(layer, wkt, [i, f"feature_{i}", 0.0])
        else:
            # Default feature
            LayerFixtures.add_feature(
                layer,
                "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
                [1, "default", 1.0]
            )

        # Write to GeoPackage
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = layer_name

        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer, path, QgsProject.instance().transformContext(), options
        )

        if error[0] != QgsVectorFileWriter.NoError:
            return "", None

        # Load the saved layer
        saved_layer = QgsVectorLayer(f"{path}|layername={layer_name}", layer_name, "ogr")

        return path, saved_layer

    @staticmethod
    def cleanup_temp_file(path: str):
        """Remove temporary file"""
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


# =============================================================================
# DATA PROVIDER FIXTURES
# =============================================================================

class DataProviderFixtures:
    """
    Fixtures for testing with different data providers (memory, gpkg, shp)

    Usage:
        for provider_type, layer in DataProviderFixtures.all_providers():
            # Test on memory, gpkg, and shapefile layers
            assert layer.isValid()
    """

    _temp_files: List[str] = []

    @classmethod
    def memory_layer(
        cls,
        geometry_type: str = "Polygon",
        crs: str = "EPSG:4326",
        name: str = "memory_test"
    ) -> QgsVectorLayer:
        """Create a memory layer"""
        uri = f"{geometry_type}?crs={crs.lower()}&field=id:integer&field=name:string"
        layer = QgsVectorLayer(uri, name, "memory")

        # Add default feature
        if layer.isValid():
            feature = QgsFeature(layer.fields())
            if geometry_type.lower() == "polygon":
                feature.setGeometry(QgsGeometry.fromWkt("POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"))
            elif geometry_type.lower() in ("linestring", "line"):
                feature.setGeometry(QgsGeometry.fromWkt("LINESTRING(0 0, 1 1)"))
            else:
                feature.setGeometry(QgsGeometry.fromWkt("POINT(0.5 0.5)"))
            feature.setAttributes([1, "test"])
            layer.dataProvider().addFeature(feature)

        return layer

    @classmethod
    def gpkg_layer(
        cls,
        geometry_type: str = "Polygon",
        crs: str = "EPSG:4326",
        name: str = "gpkg_test"
    ) -> Tuple[str, Optional[QgsVectorLayer]]:
        """
        Create a GeoPackage layer

        Returns:
            Tuple[str, QgsVectorLayer]: (file_path, layer)
        """
        # Create temp file
        fd, path = tempfile.mkstemp(suffix=".gpkg")
        os.close(fd)
        cls._temp_files.append(path)

        # Create memory layer first
        memory_layer = cls.memory_layer(geometry_type, crs, name)

        # Write to GeoPackage
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = name

        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            memory_layer, path, QgsProject.instance().transformContext(), options
        )

        if error[0] != QgsVectorFileWriter.NoError:
            return path, None

        # Load the saved layer
        layer = QgsVectorLayer(f"{path}|layername={name}", name, "ogr")
        return path, layer

    @classmethod
    def shapefile_layer(
        cls,
        geometry_type: str = "Polygon",
        crs: str = "EPSG:4326",
        name: str = "shp_test"
    ) -> Tuple[str, Optional[QgsVectorLayer]]:
        """
        Create a Shapefile layer

        Returns:
            Tuple[str, QgsVectorLayer]: (file_path, layer)
        """
        # Create temp directory for shapefile components
        temp_dir = tempfile.mkdtemp()
        path = os.path.join(temp_dir, f"{name}.shp")
        cls._temp_files.append(temp_dir)

        # Create memory layer first
        memory_layer = cls.memory_layer(geometry_type, crs, name)

        # Write to Shapefile
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "ESRI Shapefile"

        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            memory_layer, path, QgsProject.instance().transformContext(), options
        )

        if error[0] != QgsVectorFileWriter.NoError:
            return path, None

        # Load the saved layer
        layer = QgsVectorLayer(path, name, "ogr")
        return path, layer

    @classmethod
    def all_providers(
        cls,
        geometry_type: str = "Polygon",
        crs: str = "EPSG:4326"
    ) -> List[Tuple[str, QgsVectorLayer]]:
        """
        Create layers for all supported providers

        Returns:
            List of (provider_name, layer) tuples

        Usage:
            for provider, layer in DataProviderFixtures.all_providers():
                print(f"Testing {provider}: valid={layer.isValid()}")
        """
        results = []

        # Memory
        memory = cls.memory_layer(geometry_type, crs, "memory_test")
        results.append(("memory", memory))

        # GeoPackage
        gpkg_path, gpkg_layer = cls.gpkg_layer(geometry_type, crs, "gpkg_test")
        if gpkg_layer and gpkg_layer.isValid():
            results.append(("gpkg", gpkg_layer))

        # Shapefile
        shp_path, shp_layer = cls.shapefile_layer(geometry_type, crs, "shp_test")
        if shp_layer and shp_layer.isValid():
            results.append(("shapefile", shp_layer))

        return results

    @classmethod
    def cleanup_all(cls):
        """Remove all temporary files created by this class"""
        import shutil
        for path in cls._temp_files:
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                elif os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        cls._temp_files = []


# =============================================================================
# PROVIDER TEST CASES (for parametrized tests)
# =============================================================================

PROVIDER_TEST_CASES: List[Tuple[str, str]] = [
    # (provider_type, description)
    ("memory", "In-memory layer (fastest, no disk I/O)"),
    ("gpkg", "GeoPackage (SQLite-based, full feature support)"),
    ("shapefile", "ESRI Shapefile (legacy format, field name limits)"),
]

CRS_PROVIDER_COMBINATIONS: List[Tuple[str, str]] = [
    # (crs, provider) - all combinations
    ("EPSG:4326", "memory"),
    ("EPSG:4326", "gpkg"),
    ("EPSG:4326", "shapefile"),
    ("EPSG:3857", "memory"),
    ("EPSG:3857", "gpkg"),
    ("EPSG:32637", "memory"),
    ("EPSG:32637", "gpkg"),
]
