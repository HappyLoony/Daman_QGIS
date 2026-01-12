# -*- coding: utf-8 -*-
"""
Фабрика для инициализации менеджеров справочных данных плагина Daman_QGIS.

Создает и настраивает все специализированные менеджеры с правильными зависимостями.

ПРИМЕЧАНИЕ: VRI теперь обрабатывается через M_21_VRIAssignmentManager,
который предоставляет расширенный API для работы с ВРИ.
"""

import os
import threading
from typing import NamedTuple

from Daman_QGIS.constants import DATA_REFERENCE_PATH

# Импортируем все менеджеры
from Daman_QGIS.managers.submodules.Msm_4_2_work_type_reference_manager import WorkTypeReferenceManager
from Daman_QGIS.managers.submodules.Msm_4_3_project_metadata_manager import ProjectMetadataManager
from Daman_QGIS.managers.submodules.Msm_4_4_zouit_reference_manager import ZOUITReferenceManager
from Daman_QGIS.managers.submodules.Msm_4_5_function_reference_manager import FunctionReferenceManager
from Daman_QGIS.managers.submodules.Msm_4_6_layer_reference_manager import LayerReferenceManager
from Daman_QGIS.managers.submodules.Msm_4_7_employee_reference_manager import EmployeeReferenceManager
from Daman_QGIS.managers.submodules.Msm_4_8_urban_planning_reference_manager import UrbanPlanningReferenceManager
from Daman_QGIS.managers.submodules.Msm_4_9_layer_style_manager import LayerStyleManager
from Daman_QGIS.managers.submodules.Msm_4_10_excel_export_style_manager import ExcelExportStyleManager
from Daman_QGIS.managers.submodules.Msm_4_12_layer_field_structure_manager import LayerFieldStructureManager
from Daman_QGIS.managers.submodules.Msm_4_13_drawings_reference_manager import DrawingsReferenceManager
from Daman_QGIS.managers.submodules.Msm_4_14_data_validation_manager import DataValidationManager
from Daman_QGIS.managers.submodules.Msm_4_15_label_reference_manager import LabelReferenceManager
from Daman_QGIS.managers.submodules.Msm_4_16_background_reference_manager import BackgroundReferenceManager
from Daman_QGIS.managers.submodules.Msm_4_11_excel_list_style_manager import ExcelListStyleManager
from Daman_QGIS.managers.submodules.Msm_4_17_field_mapping_manager import FieldMappingManager
from Daman_QGIS.managers.submodules.Msm_4_18_zouit_classification_manager import ZOUITClassificationManager
from Daman_QGIS.managers.submodules.Msm_4_19_crs_reference_manager import CRSReferenceManager
from Daman_QGIS.managers.submodules.Msm_4_20_legal_abbreviations_manager import LegalAbbreviationsManager


class ReferenceManagers(NamedTuple):
    """Контейнер для всех менеджеров справочных данных

    ПРИМЕЧАНИЕ: VRI удалён - используйте M_21_VRIAssignmentManager напрямую:
        from Daman_QGIS.managers import VRIAssignmentManager
        vri_manager = VRIAssignmentManager()
        vri_list = vri_manager.get_all_vri()
    """
    work_type: WorkTypeReferenceManager
    project_metadata: ProjectMetadataManager
    zouit: ZOUITReferenceManager
    function: FunctionReferenceManager
    layer: LayerReferenceManager
    employee: EmployeeReferenceManager
    urban_planning: UrbanPlanningReferenceManager
    layer_style: LayerStyleManager
    excel_export_style: ExcelExportStyleManager
    excel_list_style: ExcelListStyleManager
    layer_field_structure: LayerFieldStructureManager
    drawings: DrawingsReferenceManager
    data_validation: DataValidationManager
    label: LabelReferenceManager
    background: BackgroundReferenceManager
    field_mapping: FieldMappingManager
    zouit_classification: ZOUITClassificationManager
    crs: CRSReferenceManager
    legal_abbreviations: LegalAbbreviationsManager


def create_reference_managers() -> ReferenceManagers:
    """
    Создать и инициализировать все менеджеры справочных данных

    Returns:
        ReferenceManagers: NamedTuple со всеми менеджерами

    Example:
        >>> managers = create_reference_managers()
        >>> layer_style = managers.layer_style.get_layer_style("3_1_1_ЗУ")
        >>> # Для VRI используйте M_21_VRIAssignmentManager
    """
    # Путь к справочным данным из constants.py
    # ВАЖНО: Данные хранятся в отдельном репозитории Daman_QGIS_data_reference
    reference_dir = DATA_REFERENCE_PATH

    # Создаем менеджеры без зависимостей
    work_type_manager = WorkTypeReferenceManager(reference_dir)
    project_metadata_manager = ProjectMetadataManager(reference_dir)
    zouit_manager = ZOUITReferenceManager(reference_dir)
    function_manager = FunctionReferenceManager(reference_dir)
    layer_manager = LayerReferenceManager(reference_dir)
    employee_manager = EmployeeReferenceManager(reference_dir)
    urban_planning_manager = UrbanPlanningReferenceManager(reference_dir)
    excel_export_style_manager = ExcelExportStyleManager(reference_dir)
    excel_list_style_manager = ExcelListStyleManager(reference_dir)
    layer_field_structure_manager = LayerFieldStructureManager(reference_dir)
    drawings_manager = DrawingsReferenceManager(reference_dir)
    label_manager = LabelReferenceManager(reference_dir)
    background_manager = BackgroundReferenceManager(reference_dir)
    field_mapping_manager = FieldMappingManager(reference_dir)
    zouit_classification_manager = ZOUITClassificationManager(reference_dir)
    crs_manager = CRSReferenceManager(reference_dir)
    legal_abbreviations_manager = LegalAbbreviationsManager(reference_dir)

    # Создаем менеджеры с зависимостями (композиция)
    layer_style_manager = LayerStyleManager(reference_dir, layer_manager)
    data_validation_manager = DataValidationManager(
        reference_dir=reference_dir,
        function_manager=function_manager,
        layer_manager=layer_manager,
        employee_manager=employee_manager,
        excel_export_manager=excel_export_style_manager
    )

    return ReferenceManagers(
        work_type=work_type_manager,
        project_metadata=project_metadata_manager,
        zouit=zouit_manager,
        function=function_manager,
        layer=layer_manager,
        employee=employee_manager,
        urban_planning=urban_planning_manager,
        layer_style=layer_style_manager,
        excel_export_style=excel_export_style_manager,
        excel_list_style=excel_list_style_manager,
        layer_field_structure=layer_field_structure_manager,
        drawings=drawings_manager,
        data_validation=data_validation_manager,
        label=label_manager,
        background=background_manager,
        field_mapping=field_mapping_manager,
        zouit_classification=zouit_classification_manager,
        crs=crs_manager,
        legal_abbreviations=legal_abbreviations_manager
    )


# Глобальный синглтон (для удобства использования)
_reference_managers = None
_lock = threading.Lock()


def get_reference_managers() -> ReferenceManagers:
    """
    Получить глобальный экземпляр всех менеджеров (потокобезопасно)

    Returns:
        ReferenceManagers: NamedTuple со всеми менеджерами

    Example:
        >>> managers = get_reference_managers()
        >>> layers = managers.layer.get_base_layers()
        >>> # Для VRI используйте M_21_VRIAssignmentManager
    """
    global _reference_managers

    if _reference_managers is None:
        with _lock:
            if _reference_managers is None:
                _reference_managers = create_reference_managers()

    return _reference_managers


def reload_reference_managers() -> ReferenceManagers:
    """
    Перезагрузить все менеджеры справочных данных (сбросить кэш)

    Используется когда файлы Base_*.json были изменены и нужно
    загрузить новые данные без перезапуска QGIS.

    Returns:
        ReferenceManagers: Новый экземпляр всех менеджеров с обновленными данными

    Example:
        >>> # После редактирования Base_layers.json
        >>> managers = reload_reference_managers()
        >>> # Теперь managers содержит актуальные данные
    """
    global _reference_managers

    with _lock:
        from Daman_QGIS.utils import log_info
        log_info("M_4_ReferenceManager: Сброс кэша и перезагрузка всех справочников")
        _reference_managers = create_reference_managers()
        log_info("M_4_ReferenceManager: Справочники успешно перезагружены")

    return _reference_managers
