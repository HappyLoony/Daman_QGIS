# -*- coding: utf-8 -*-
# pyright: reportUnsupportedDunderAll=false
"""
Infrastructure managers - техническая инфраструктура.

Менеджеры: M_14, M_16, M_17, M_29, M_30, M_32, M_37, M_38, M_40

Автоматически импортирует все M_*.py и регистрирует singleton-менеджеры.
"""
from pathlib import Path
from .._domain_loader import load_domain

__all__ = load_domain(
    domain='infrastructure',
    package=__name__,
    directory=Path(__file__).parent,
    caller_globals=globals(),
)
