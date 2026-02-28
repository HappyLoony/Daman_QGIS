# -*- coding: utf-8 -*-
"""
Инструменты раздела F_4 - ХЛУ (Хозяйственно-лесное устройство)

Автоматический импорт всех F_X_Y модулей из папки.
"""

import os
import importlib
import re

# Автоматическое обнаружение и импорт всех F_X_Y модулей
_current_dir = os.path.dirname(__file__)
_module_pattern = re.compile(r'^(F_\d+_\d+_.+)\.py$')

__all__ = []

for _filename in os.listdir(_current_dir):
    _match = _module_pattern.match(_filename)
    if _match:
        _module_name = _match.group(1)
        try:
            _module = importlib.import_module(f'.{_module_name}', package=__name__)
            # Ищем класс F_X_Y_ClassName в модуле
            for _attr_name in dir(_module):
                if _attr_name.startswith('F_') and not _attr_name.startswith('__'):
                    _attr = getattr(_module, _attr_name)
                    if isinstance(_attr, type):  # Это класс
                        globals()[_attr_name] = _attr
                        __all__.append(_attr_name)  # type: ignore[reportUnsupportedDunderAll]
        except ImportError as e:
            pass  # Модуль не загрузился - пропускаем

# Очистка временных переменных (только если они существуют)
for _var in ['_current_dir', '_module_pattern', '_filename', '_match', '_module_name', '_module', '_attr_name', '_attr']:
    if _var in dir():
        del globals()[_var]
