# -*- coding: utf-8 -*-
# pyright: reportUnsupportedDunderAll=false
"""
Geometry managers - геометрия и координаты.

Менеджеры: M_6, M_18, M_20, M_26, M_47

Автоматически импортирует все M_*.py и регистрирует singleton-менеджеры.
Утилита _ring_utils.py (canonical ring-helpers) импортируется явно в M_20/M_47,
не подпадает под glob M_*.py.
"""
from pathlib import Path
from .._domain_loader import load_domain

__all__ = load_domain(
    domain='geometry',
    package=__name__,
    directory=Path(__file__).parent,
    caller_globals=globals(),
    callable_prefixes=('number_',),
)
