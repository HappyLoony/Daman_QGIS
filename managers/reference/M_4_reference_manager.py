# -*- coding: utf-8 -*-
"""
Фабрика для инициализации менеджеров справочных данных плагина Daman_QGIS.

Создает и настраивает все специализированные менеджеры с правильными зависимостями.

ПРИМЕЧАНИЕ: VRI теперь обрабатывается через M_21_VRIAssignmentManager,
который предоставляет расширенный API для работы с ВРИ.
"""

from typing import NamedTuple

# Импортируем все менеджеры (относительные импорты внутри домена)
from .submodules.Msm_4_2_simple_reference_manager import SimpleReferenceManager
from .submodules.Msm_4_3_project_metadata_manager import ProjectMetadataManager
from .submodules.Msm_4_4_zouit_reference_manager import ZOUITReferenceManager
from .submodules.Msm_4_5_function_reference_manager import FunctionReferenceManager
from .submodules.Msm_4_6_layer_reference_manager import LayerReferenceManager
from .submodules.Msm_4_7_employee_reference_manager import EmployeeReferenceManager
from .submodules.Msm_4_8_urban_planning_reference_manager import UrbanPlanningReferenceManager
from .submodules.Msm_4_9_layer_style_manager import LayerStyleManager
from .submodules.Msm_4_12_layer_field_structure_manager import LayerFieldStructureManager
from .submodules.Msm_4_14_data_validation_manager import DataValidationManager
from .submodules.Msm_4_15_label_reference_manager import LabelReferenceManager
from .submodules.Msm_4_16_background_reference_manager import BackgroundReferenceManager
from .submodules.Msm_4_17_field_mapping_manager import FieldMappingManager
from .submodules.Msm_4_18_zouit_classification_manager import ZOUITClassificationManager
from .submodules.Msm_4_19_crs_reference_manager import CRSReferenceManager
from .submodules.Msm_4_20_legal_abbreviations_manager import LegalAbbreviationsManager
from .submodules.Msm_4_23_negativ_classification_manager import NegativClassificationManager

__all__ = [
    'ReferenceManagers', 'create_reference_managers',
    'SimpleReferenceManager', 'ProjectMetadataManager', 'ZOUITReferenceManager',
    'FunctionReferenceManager', 'LayerReferenceManager', 'EmployeeReferenceManager',
    'UrbanPlanningReferenceManager', 'LayerStyleManager', 'LayerFieldStructureManager',
    'DataValidationManager', 'LabelReferenceManager', 'BackgroundReferenceManager',
    'FieldMappingManager', 'ZOUITClassificationManager', 'CRSReferenceManager',
    'LegalAbbreviationsManager', 'NegativClassificationManager',
]


class ReferenceManagers(NamedTuple):
    """Контейнер для всех менеджеров справочных данных

    ПРИМЕЧАНИЕ: VRI удалён - используйте M_21_VRIAssignmentManager напрямую:
        from Daman_QGIS.managers import VRIAssignmentManager
        vri_manager = VRIAssignmentManager()
        vri_list = vri_manager.get_all_vri()

    ПРИМЕЧАНИЕ: work_type и drawings указывают на один SimpleReferenceManager
    """
    work_type: SimpleReferenceManager
    project_metadata: ProjectMetadataManager
    zouit: ZOUITReferenceManager
    function: FunctionReferenceManager
    layer: LayerReferenceManager
    employee: EmployeeReferenceManager
    urban_planning: UrbanPlanningReferenceManager
    layer_style: LayerStyleManager
    layer_field_structure: LayerFieldStructureManager
    drawings: SimpleReferenceManager
    data_validation: DataValidationManager
    label: LabelReferenceManager
    background: BackgroundReferenceManager
    field_mapping: FieldMappingManager
    zouit_classification: ZOUITClassificationManager
    crs: CRSReferenceManager
    legal_abbreviations: LegalAbbreviationsManager
    negativ_classification: NegativClassificationManager


def create_reference_managers() -> ReferenceManagers:
    """
    Создать и инициализировать все менеджеры справочных данных

    Данные загружаются через Daman API (BaseReferenceLoader).

    Returns:
        ReferenceManagers: NamedTuple со всеми менеджерами

    Example:
        >>> managers = create_reference_managers()
        >>> layer_style = managers.layer_style.get_layer_style("3_1_1_ЗУ")
        >>> # Для VRI используйте M_21_VRIAssignmentManager
    """
    # Создаем менеджеры без зависимостей
    # SimpleReferenceManager объединяет work_type и drawings
    simple_manager = SimpleReferenceManager()
    project_metadata_manager = ProjectMetadataManager()
    zouit_manager = ZOUITReferenceManager()
    function_manager = FunctionReferenceManager()
    layer_manager = LayerReferenceManager()
    employee_manager = EmployeeReferenceManager()
    urban_planning_manager = UrbanPlanningReferenceManager()
    layer_field_structure_manager = LayerFieldStructureManager()
    label_manager = LabelReferenceManager()
    background_manager = BackgroundReferenceManager()
    field_mapping_manager = FieldMappingManager()
    zouit_classification_manager = ZOUITClassificationManager()
    crs_manager = CRSReferenceManager()
    legal_abbreviations_manager = LegalAbbreviationsManager()
    negativ_classification_manager = NegativClassificationManager()

    # Создаем менеджеры с зависимостями (композиция)
    layer_style_manager = LayerStyleManager(layer_manager)
    data_validation_manager = DataValidationManager(
        function_manager=function_manager,
        layer_manager=layer_manager,
        employee_manager=employee_manager
    )

    return ReferenceManagers(
        work_type=simple_manager,
        project_metadata=project_metadata_manager,
        zouit=zouit_manager,
        function=function_manager,
        layer=layer_manager,
        employee=employee_manager,
        urban_planning=urban_planning_manager,
        layer_style=layer_style_manager,
        layer_field_structure=layer_field_structure_manager,
        drawings=simple_manager,  # Тот же экземпляр что и work_type
        data_validation=data_validation_manager,
        label=label_manager,
        background=background_manager,
        field_mapping=field_mapping_manager,
        zouit_classification=zouit_classification_manager,
        crs=crs_manager,
        legal_abbreviations=legal_abbreviations_manager,
        negativ_classification=negativ_classification_manager
    )
