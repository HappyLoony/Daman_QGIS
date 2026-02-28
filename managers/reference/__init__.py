# -*- coding: utf-8 -*-
# pyright: reportUnsupportedDunderAll=false
"""
Reference managers - справочники.

Менеджеры: M_4

Автоматически импортирует все M_*.py и регистрирует singleton-менеджеры.
"""
from pathlib import Path
from .._domain_loader import load_domain

__all__ = load_domain(
    domain='reference',
    package=__name__,
    directory=Path(__file__).parent,
    caller_globals=globals(),
    callable_prefixes=('get_', 'reset_', 'create_', 'reload_'),
    second_pass='all_types',
)
