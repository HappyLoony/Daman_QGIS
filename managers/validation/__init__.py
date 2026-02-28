# -*- coding: utf-8 -*-
# pyright: reportUnsupportedDunderAll=false
"""
Validation managers - валидаторы.

Менеджеры: M_21, M_22, M_27, M_28, M_36

Автоматически импортирует все M_*.py и регистрирует singleton-менеджеры.
"""
from pathlib import Path
from .._domain_loader import load_domain

__all__ = load_domain(
    domain='validation',
    package=__name__,
    directory=Path(__file__).parent,
    caller_globals=globals(),
    register_keywords=('Manager', 'Validator'),
    wildcard_submodule=True,
)
