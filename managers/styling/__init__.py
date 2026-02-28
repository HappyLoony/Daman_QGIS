# -*- coding: utf-8 -*-
# pyright: reportUnsupportedDunderAll=false
"""
Styling managers - визуализация.

Менеджеры: M_5, M_7, M_12, M_31, M_34

Автоматически импортирует все M_*.py и регистрирует singleton-менеджеры.
"""
from pathlib import Path
from .._domain_loader import load_domain

__all__ = load_domain(
    domain='styling',
    package=__name__,
    directory=Path(__file__).parent,
    caller_globals=globals(),
)
