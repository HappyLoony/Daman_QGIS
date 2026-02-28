# -*- coding: utf-8 -*-
# pyright: reportUnsupportedDunderAll=false
"""
Processing managers - обработка данных.

Менеджеры: M_13, M_15, M_23, M_24, M_25

Автоматически импортирует все M_*.py и регистрирует singleton-менеджеры.
"""
from pathlib import Path
from .._domain_loader import load_domain

__all__ = load_domain(
    domain='processing',
    package=__name__,
    directory=Path(__file__).parent,
    caller_globals=globals(),
)
