# -*- coding: utf-8 -*-
# pyright: reportUnsupportedDunderAll=false
"""Processing submodules."""
import importlib
from pathlib import Path

_current_dir = Path(__file__).parent
_all_exports = []

for _file in sorted(_current_dir.glob("Msm_*.py")):
    _module_name = _file.stem
    _module = importlib.import_module(f".{_module_name}", package=__name__)
    for _name in dir(_module):
        if not _name.startswith('_'):
            _obj = getattr(_module, _name)
            if isinstance(_obj, type) or callable(_obj):
                globals()[_name] = _obj
                if _name not in _all_exports:
                    _all_exports.append(_name)

__all__ = _all_exports
