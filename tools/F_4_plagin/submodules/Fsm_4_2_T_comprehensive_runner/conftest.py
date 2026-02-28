# -*- coding: utf-8 -*-
"""
conftest.py - Shared fixtures and configuration for test system

Provides:
- Test data classes for parametrized tests (reserved for future use)
"""

from typing import List, Any, Optional, Tuple
from dataclasses import dataclass


# =============================================================================
# DATA CLASSES FOR TEST CASES (reserved for future use)
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
