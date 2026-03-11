# -*- coding: utf-8 -*-
# pyright: reportUnsupportedDunderAll=false
"""
Export managers - экспорт данных.

Менеджеры: M_33, M_35, M_44

Автоматически импортирует все M_*.py и регистрирует singleton-менеджеры.
"""
from pathlib import Path
from .._domain_loader import load_domain

__all__ = load_domain(
    domain='export',
    package=__name__,
    directory=Path(__file__).parent,
    caller_globals=globals(),
    submodule_imports={
        '.submodules.Msm_33_1_hlu_processor': [
            'HLU_DataProcessor',
            'ZPR_LAYERS',
            'ZPR_FULL_NAMES',
            'MO_LAYER_NAME',
        ],
    },
)
