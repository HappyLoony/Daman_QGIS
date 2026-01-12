# -*- coding: utf-8 -*-
"""
Fsm_5_2_T_comprehensive_runner - Comprehensive Test System

Structure:
    /Fsm_5_2_T_comprehensive_runner/
    ├── __init__.py              # This file
    ├── conftest.py              # Shared fixtures and edge cases
    ├── Fsm_5_2_1_test_logger.py # Test logging infrastructure
    ├── Fsm_5_2_T_comprehensive_runner.py  # Main orchestrator
    ├── Fsm_5_2_T_*.py          # Individual test modules
    ├── fixtures/                # Test fixtures
    │   ├── geometry_fixtures.py
    │   ├── layer_fixtures.py
    │   └── project_fixtures.py
    └── utils/                   # Test utilities
        ├── assertions.py
        └── test_data_generator.py

Usage:
    from Fsm_5_2_T_comprehensive_runner import ComprehensiveTestRunner
    from Fsm_5_2_T_comprehensive_runner.fixtures import LayerFixtures
    from Fsm_5_2_T_comprehensive_runner.utils import GeometryAssertions
"""

from .Fsm_5_2_1_test_logger import TestLogger
from .Fsm_5_2_T_comprehensive_runner import ComprehensiveTestRunner

# Re-export conftest items
from .conftest import (
    GeometryTestCase,
    FieldTestCase,
    LayerTestCase,
    GEOMETRY_EDGE_CASES,
    FIELD_VALUE_EDGE_CASES,
    CRS_TEST_CASES,
    TOPOLOGY_EDGE_CASES,
    TestFixtures,
    ParametrizedTestRunner,
    # Error handling
    ErrorTestCase,
    ERROR_HANDLING_CASES,
    INPUT_VALIDATION_CASES,
    FILE_ERROR_CASES,
    ErrorTestRunner,
)

__all__ = [
    # Core test infrastructure
    "TestLogger",
    "ComprehensiveTestRunner",

    # Test case data classes
    "GeometryTestCase",
    "FieldTestCase",
    "LayerTestCase",
    "ErrorTestCase",

    # Edge case collections
    "GEOMETRY_EDGE_CASES",
    "FIELD_VALUE_EDGE_CASES",
    "CRS_TEST_CASES",
    "TOPOLOGY_EDGE_CASES",

    # Error handling test cases
    "ERROR_HANDLING_CASES",
    "INPUT_VALIDATION_CASES",
    "FILE_ERROR_CASES",

    # Fixture factories and test runners
    "TestFixtures",
    "ParametrizedTestRunner",
    "ErrorTestRunner",
]
