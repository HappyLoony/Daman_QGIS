# -*- coding: utf-8 -*-
# pyright: reportUnsupportedDunderAll=false
"""
Core managers - жизненный цикл проекта.

Менеджеры: M_1, M_2, M_3, M_8, M_10, M_19

Автоматически импортирует все M_*.py и регистрирует singleton-менеджеры.
"""
from pathlib import Path
from .._domain_loader import load_domain

__all__ = load_domain(
    domain='core',
    package=__name__,
    directory=Path(__file__).parent,
    caller_globals=globals(),
)
