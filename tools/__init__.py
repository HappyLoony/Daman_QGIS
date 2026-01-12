"""
Инструменты плагина Daman_QGIS
"""

# Импорт инструментов для удобства
from .F_0_project import *
from .F_1_data import *
from .F_2_processing import *
from .F_3_cutting import *
from .F_4_hlu import *
from .F_5_plagin import *
from .F_6_release import *

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

    # Раздел F_2 - Обработка
    'F_2_1_LandSelection',
    'F_2_2_LandCategories',
    'F_2_4_GPMT',

    # Раздел F_3 - Нарезка
    # Будут добавлены позже

    # Раздел F_4 - ХЛУ
    # Будут добавлены позже

    # Раздел F_5 - Плагин
    'F_5_1_CheckDependencies',

    # Раздел F_6 - Выпуск
    'F_6_1_VectorExport',
    'F_6_2_BackgroundExport',
    'F_6_3_DocumentExport'
]
__all__ = _exported_classes  # type: ignore[reportUnsupportedDunderAll]
