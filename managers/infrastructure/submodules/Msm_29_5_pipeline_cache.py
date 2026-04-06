# -*- coding: utf-8 -*-
"""
Msm_29_5_PipelineCache - RAM-only cache for pipeline CRS strings.

Pipelines arrive via /validate response (alongside JWT tokens).
Stored in memory only -- not persisted to disk (IP protection).

Singleton: one instance per QGIS session.
"""

from typing import Dict, Optional

from Daman_QGIS.utils import log_info, log_warning


class PipelineCache:
    """RAM-only cache for pipeline strings, keyed by region code."""

    _instance: Optional['PipelineCache'] = None

    def __init__(self):
        self._pipelines: Dict[str, str] = {}

    @classmethod
    def get_instance(cls) -> 'PipelineCache':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        if cls._instance:
            cls._instance._pipelines.clear()
        cls._instance = None

    def set_pipelines(self, pipelines: Dict[str, str]) -> None:
        """Store pipelines from /validate response."""
        self._pipelines = dict(pipelines)
        log_info(f"Msm_29_5: Cached {len(pipelines)} pipelines")

    def get_pipeline(self, region_code: str) -> Optional[str]:
        """Get pipeline for a specific region."""
        return self._pipelines.get(region_code)

    def has_pipelines(self) -> bool:
        return bool(self._pipelines)
