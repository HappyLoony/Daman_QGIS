# -*- coding: utf-8 -*-
"""
Централизованный загрузчик доменов для авторегистрации менеджеров.

Заменяет 8 дублирующихся доменных __init__.py единой параметризованной функцией.
Каждый доменный __init__.py становится ~15 строк.

Стратегия регистрации (B+C гибрид):
  B (приоритет): Если M_*.py имеет __all__ — берём ТОЛЬКО из него
  C (fallback):  Если __all__ нет — dir() + isinstance(type) + keyword match (БЕЗ __module__)
"""
import importlib
import re
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ID_PATTERN = re.compile(r'^(M_\d+)_')


def load_domain(
    domain: str,
    package: str,
    directory: Path,
    caller_globals: dict,
    register_keywords: Tuple[str, ...] = ('Manager',),
    callable_prefixes: Tuple[str, ...] = ('get_', 'reset_'),
    second_pass: str = 'enum',
    submodule_imports: Optional[Dict[str, List[str]]] = None,
    wildcard_submodule: bool = False,
) -> List[str]:
    """
    Загрузка всех M_*.py из домена, экспорт символов, регистрация менеджеров.

    Args:
        domain: Имя домена ('core', 'infrastructure', ...)
        package: __name__ вызывающего __init__.py
        directory: Path(__file__).parent вызывающего __init__.py
        caller_globals: globals() вызывающего __init__.py
        register_keywords: Ключевые слова в имени класса для регистрации в registry.
                          По умолчанию ('Manager',), validation добавляет ('Manager', 'Validator')
        callable_prefixes: Префиксы для экспорта callable объектов.
                          По умолчанию ('get_', 'reset_'), geometry добавляет 'number_'
        second_pass: 'enum' = экспорт только Enum (hasattr __members__) во втором проходе.
                     'all_types' = экспорт ВСЕХ типов (для reference — NamedTuple и суб-менеджеры)
        submodule_imports: Явные импорты из субмодулей.
                          {'.submodules.Msm_33_1_hlu_processor': ['HLU_DataProcessor', ...]}
        wildcard_submodule: Если True — from .submodules import * (для validation)

    Returns:
        Список экспортированных имён (для __all__)
    """
    from ._registry import registry

    all_exports: List[str] = []

    # === Проход 1: M_*.py файлы ===
    for _file in sorted(directory.glob("M_*.py")):
        module_name = _file.stem
        try:
            module = importlib.import_module(f".{module_name}", package=package)

            match = _ID_PATTERN.match(module_name)
            manager_id = match.group(1) if match else None

            # --- Path B: модуль имеет __all__ (приоритет) ---
            if hasattr(module, '__all__'):
                for name in module.__all__:
                    obj = getattr(module, name, None)
                    if obj is None:
                        continue
                    if name not in all_exports:
                        caller_globals[name] = obj
                        all_exports.append(name)
                    # Регистрация если это класс с нужным ключевым словом
                    if (manager_id
                            and isinstance(obj, type)
                            and any(kw in name for kw in register_keywords)
                            and not registry.is_registered(manager_id)):
                        registry.register(manager_id, obj, domain=domain)
                continue  # __all__ обработан — fallback не нужен

            # --- Path C: fallback (нет __all__) — БЕЗ __module__ check ---
            for name in dir(module):
                if name.startswith('_'):
                    continue
                obj = getattr(module, name)
                if isinstance(obj, type):
                    if name not in all_exports:
                        caller_globals[name] = obj
                        all_exports.append(name)
                    if (manager_id
                            and any(kw in name for kw in register_keywords)
                            and not registry.is_registered(manager_id)):
                        registry.register(manager_id, obj, domain=domain)
                elif callable(obj) and name.startswith(callable_prefixes):
                    if name not in all_exports:
                        caller_globals[name] = obj
                        all_exports.append(name)

        except Exception as e:
            tb = traceback.format_exc()
            try:
                from Daman_QGIS.utils import log_error
                log_error(f"{domain}/__init__: Ошибка {module_name}: {e}\n{tb}")
            except ImportError:
                print(f"{domain}/__init__: Ошибка {module_name}: {e}\n{tb}")
            continue

    # === Проход 2: Enum / все типы ===
    for _file in sorted(directory.glob("M_*.py")):
        module_name = _file.stem
        try:
            module = importlib.import_module(f".{module_name}", package=package)
            for name in dir(module):
                if name.startswith('_') or name in all_exports:
                    continue
                obj = getattr(module, name)
                if second_pass == 'enum':
                    if isinstance(obj, type) and hasattr(obj, '__members__'):
                        caller_globals[name] = obj
                        all_exports.append(name)
                elif second_pass == 'all_types':
                    if isinstance(obj, type):
                        caller_globals[name] = obj
                        all_exports.append(name)
        except Exception:
            continue

    # === Субмодульные импорты ===
    if submodule_imports:
        for dotpath, names in submodule_imports.items():
            try:
                sub_module = importlib.import_module(dotpath, package=package)
                for name in names:
                    obj = getattr(sub_module, name, None)
                    if obj is not None and name not in all_exports:
                        caller_globals[name] = obj
                        all_exports.append(name)
            except Exception as e:
                try:
                    from Daman_QGIS.utils import log_error
                    log_error(f"{domain}/__init__: Ошибка импорта субмодуля {dotpath}: {e}")
                except ImportError:
                    print(f"{domain}/__init__: Ошибка импорта субмодуля {dotpath}: {e}")

    if wildcard_submodule:
        try:
            sub_pkg = importlib.import_module('.submodules', package=package)
            if hasattr(sub_pkg, '__all__'):
                for name in sub_pkg.__all__:
                    obj = getattr(sub_pkg, name, None)
                    if obj is not None and name not in all_exports:
                        caller_globals[name] = obj
                        all_exports.append(name)
        except Exception as e:
            try:
                from Daman_QGIS.utils import log_error
                log_error(f"{domain}/__init__: Ошибка импорта submodules: {e}")
            except ImportError:
                print(f"{domain}/__init__: Ошибка импорта submodules: {e}")

    return all_exports
