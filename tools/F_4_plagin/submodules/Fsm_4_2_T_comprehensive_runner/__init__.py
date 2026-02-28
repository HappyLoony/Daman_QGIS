# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_comprehensive_runner - Comprehensive Test System

Structure:
    /Fsm_4_2_T_comprehensive_runner/
    ├── __init__.py              # This file
    ├── conftest.py              # Data classes for test cases
    ├── Fsm_4_2_1_test_logger.py # Test logging infrastructure
    ├── Fsm_4_2_T_comprehensive_runner.py  # Main orchestrator
    ├── Fsm_4_2_T_*.py          # Individual test modules
    └── fixtures/                # Test fixtures
        ├── layer_fixtures.py
        └── project_fixtures.py

Usage:
    from Fsm_4_2_T_comprehensive_runner import ComprehensiveTestRunner, TestLogger
"""

from .Fsm_4_2_1_test_logger import TestLogger
from .Fsm_4_2_T_comprehensive_runner import ComprehensiveTestRunner

# Re-export conftest dataclasses (reserved for future parametrized tests)
from .conftest import (
    GeometryTestCase,
    FieldTestCase,
    LayerTestCase,
)

__all__ = [
    # Core test infrastructure
    "TestLogger",
    "ComprehensiveTestRunner",

    # Test case data classes (reserved for future use)
    "GeometryTestCase",
    "FieldTestCase",
    "LayerTestCase",
]
