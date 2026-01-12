"""
Субмодули инструментов раздела F_0 - Проект
Native QGIS версия (без GRASS)
"""

# Новые native QGIS модули проверки топологии
from .Fsm_0_4_1_geometry_validity import Fsm_0_4_1_GeometryValidityChecker
from .Fsm_0_4_2_duplicates import Fsm_0_4_2_DuplicatesChecker
from .Fsm_0_4_3_topology_errors import Fsm_0_4_3_TopologyErrorsChecker
from .Fsm_0_4_4_precision import Fsm_0_4_4_PrecisionChecker
from .Fsm_0_4_5_coordinator import Fsm_0_4_5_TopologyCoordinator
from .Fsm_0_4_6_fixer import Fsm_0_4_6_TopologyFixer

# Модули расчёта параметров проекции (Fsm_0_5_4_X)
from .Fsm_0_5_4_base_method import BaseCalculationMethod, CalculationResult
from .Fsm_0_5_4_1_simple_offset import Fsm_0_5_4_1_SimpleOffset
from .Fsm_0_5_4_2_offset_meridian import Fsm_0_5_4_2_OffsetMeridian
from .Fsm_0_5_4_3_affine import Fsm_0_5_4_3_Affine
from .Fsm_0_5_4_4_helmert_7p import Fsm_0_5_4_4_Helmert7P
from .Fsm_0_5_4_5_scikit_affine import Fsm_0_5_4_5_ScikitAffine
from .Fsm_0_5_4_6_gdal_gcp import Fsm_0_5_4_6_GdalGcp
from .Fsm_0_5_4_7_projestions_api import Fsm_0_5_4_7_ProjectionsApi

# Остальные субмодули F_0
from .Fsm_0_5_refine_dialog import RefineProjectionDialog

__all__ = [
    # Native QGIS topology modules
    'Fsm_0_4_1_GeometryValidityChecker',
    'Fsm_0_4_2_DuplicatesChecker',
    'Fsm_0_4_3_TopologyErrorsChecker',
    'Fsm_0_4_4_PrecisionChecker',
    'Fsm_0_4_5_TopologyCoordinator',
    'Fsm_0_4_6_TopologyFixer',

    # Projection calculation methods (Fsm_0_5_4_X)
    'BaseCalculationMethod',
    'CalculationResult',
    'Fsm_0_5_4_1_SimpleOffset',
    'Fsm_0_5_4_2_OffsetMeridian',
    'Fsm_0_5_4_3_Affine',
    'Fsm_0_5_4_4_Helmert7P',
    'Fsm_0_5_4_5_ScikitAffine',
    'Fsm_0_5_4_6_GdalGcp',
    'Fsm_0_5_4_7_ProjectionsApi',

    # Other F_0 submodules
    'RefineProjectionDialog'
]