# -*- coding: utf-8 -*-
# pyright: reportUnsupportedDunderAll=false
"""
Managers - Централизованная система менеджеров Daman_QGIS.

Домены обнаруживаются автоматически по наличию папок с __init__.py.
Список менеджеров: registry.list_registered()
Группировка: registry.list_by_domain()

Структура доменов:
- core: Жизненный цикл проекта (M_1, M_2, M_3, M_8, M_10, M_19)
- reference: Справочники (M_4 + Msm_4_*)
- geometry: Геометрия и координаты (M_6, M_18, M_20, M_26)
- styling: Визуализация (M_5, M_7, M_12, M_31, M_34)
- processing: Обработка данных (M_13, M_15, M_23, M_24, M_25)
- validation: Валидаторы (M_21, M_22, M_27, M_28)
- export: Экспорт (M_33, M_35, M_44)
- infrastructure: Техническая инфраструктура (M_14, M_16, M_17, M_29, M_30, M_32, M_40)
"""
import importlib
from pathlib import Path

# Registry (импортируется первым)
from ._registry import registry, ManagerRegistry

# M_4 ReferenceManagers — фабрика (не синглтон, вне registry)
from ._registry import get_reference_managers, reset_reference_managers

# Direct export of track_function (decorator for telemetry) and track_exception
from .infrastructure.M_32_telemetry_manager import track_function, track_exception

_current_dir = Path(__file__).parent
_all_exports = [
    'registry', 'ManagerRegistry',
    # M_4 ReferenceManagers (фабрика, не синглтон)
    'get_reference_managers', 'reset_reference_managers',
    # Telemetry decorator and exception tracker
    'track_function',
    'track_exception',
]

# Автообнаружение доменов: все папки с __init__.py (кроме __pycache__ и submodules)
_domains = [
    d.name for d in _current_dir.iterdir()
    if d.is_dir()
    and not d.name.startswith('_')
    and d.name != 'submodules'  # Исключаем старую папку на время миграции
    and (d / '__init__.py').exists()
]

# Динамический импорт из всех доменов
for _domain in sorted(_domains):
    try:
        _module = importlib.import_module(f".{_domain}", package=__name__)

        # Реэкспорт всего из домена
        if hasattr(_module, '__all__'):
            for _name in _module.__all__:
                if _name not in _all_exports:  # Защита от дублей
                    globals()[_name] = getattr(_module, _name)
                    _all_exports.append(_name)
    except Exception as _e:
        # Логируем ошибку импорта домена (критично для диагностики!)
        import traceback
        _tb = traceback.format_exc()
        try:
            from Daman_QGIS.utils import log_error
            log_error(f"managers/__init__: Ошибка импорта домена '{_domain}': {_e}\n{_tb}")
        except ImportError:
            print(f"managers/__init__: Ошибка импорта домена '{_domain}': {_e}\n{_tb}")

__all__ = sorted(set(_all_exports))
