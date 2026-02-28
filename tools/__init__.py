"""
Инструменты плагина Daman_QGIS
"""

# Импорт инструментов для удобства
from .F_0_project import *
from .F_1_data import *
from .F_2_cutting import *
from .F_3_hlu import *
from .F_4_plagin import *
from .F_5_release import *
from .F_6_special import *

# Список экспортируемых классов (динамический импорт из подпакетов)
_exported_classes = [
    # Раздел F_0 - Проект
    'F_0_1_NewProject',
    'F_0_2_OpenProject',
    'F_0_3_EditProjectProperties',
    'F_0_4_TopologyCheck',
    'F_0_5_RefineProjection',

    # Раздел F_1 - Данные
    'F_1_1_UniversalImport',
    'F_1_2_LoadWMS',
    'F_1_3_BudgetSelection',
    'F_1_4_GraphicsRequest',
    'F_1_5_UniversalExport',

    # Раздел F_2 - Нарезка
    # Будут добавлены позже

    # Раздел F_3 - ХЛУ
    # Будут добавлены позже

    # Раздел F_4 - Плагин
    'F_4_1_PluginDiagnostics',

    # Раздел F_5 - Выпуск
    'F_5_1_VectorExport',
    'F_5_2_BackgroundExport',
    'F_5_3_DocumentExport'
]
__all__ = _exported_classes  # type: ignore[reportUnsupportedDunderAll]
