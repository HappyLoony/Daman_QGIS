# -*- coding: utf-8 -*-
"""
Manager Submodules - Субменеджеры справочных данных и компонентов

Группа M_4 (Справочные менеджеры):
- Msm_4_1: [УДАЛЁН] VRI теперь в M_21_VRIAssignmentManager
- Msm_4_2: WorkTypeReferenceManager - Типы работ
- Msm_4_3: ProjectMetadataManager - Метаданные проекта
- Msm_4_4: ZOUITReferenceManager - ЗОУИТ
- Msm_4_5: FunctionReferenceManager - Функции плагина
- Msm_4_6: LayerReferenceManager - Слои
- Msm_4_7: EmployeeReferenceManager - Сотрудники
- Msm_4_8: UrbanPlanningReferenceManager - Градостроительство
- Msm_4_9: LayerStyleManager - Стили слоёв
- Msm_4_10: ExcelExportStyleManager - Стили экспорта Excel
- Msm_4_11: ExcelListStyleManager - Стили списков Excel
- Msm_4_12: LayerFieldStructureManager - Структура полей
- Msm_4_13: DrawingsReferenceManager - Чертежи
- Msm_4_14: DataValidationManager - Валидация данных
- Msm_4_15: LabelReferenceManager - Подписи
- Msm_4_16: BackgroundReferenceManager - Подложки

Группа M_5 (Стили):
- Msm_5_1: AutoCADToQGISConverter - Конвертер AutoCAD стилей в QGIS
- Msm_5_2: color_utils - Утилиты для работы с цветом

Группа M_12 (Подписи):
- Msm_12_1: CollisionManager - Коллизии подписей
- Msm_12_2: LabelSettingsBuilder - Построитель настроек подписей

Группа M_13 (Очистка данных):
- Msm_13_1: StringSanitizer - Очистка строк
- Msm_13_2: AttributeProcessor - Обработка атрибутов
- Msm_13_3: FieldCleanup - Очистка полей
- Msm_13_4: DataValidator - Валидация данных
- Msm_13_5: AttributeMapper - Маппинг атрибутов

Группа M_17 (Асинхронные задачи):
- Msm_17_1: BaseAsyncTask - Базовый класс для async задач
- Msm_17_2: ProgressReporter - Отображение прогресса в MessageBar
"""

# Группа M_4: Справочные менеджеры
# Msm_4_1 (VRI) удалён - используйте M_21_VRIAssignmentManager
from .Msm_4_2_work_type_reference_manager import WorkTypeReferenceManager
from .Msm_4_3_project_metadata_manager import ProjectMetadataManager
from .Msm_4_4_zouit_reference_manager import ZOUITReferenceManager
from .Msm_4_5_function_reference_manager import FunctionReferenceManager
from .Msm_4_6_layer_reference_manager import LayerReferenceManager
from .Msm_4_7_employee_reference_manager import EmployeeReferenceManager
from .Msm_4_8_urban_planning_reference_manager import UrbanPlanningReferenceManager
from .Msm_4_9_layer_style_manager import LayerStyleManager
from .Msm_4_10_excel_export_style_manager import ExcelExportStyleManager
from .Msm_4_11_excel_list_style_manager import ExcelListStyleManager
from .Msm_4_12_layer_field_structure_manager import LayerFieldStructureManager
from .Msm_4_13_drawings_reference_manager import DrawingsReferenceManager
from .Msm_4_14_data_validation_manager import DataValidationManager
from .Msm_4_15_label_reference_manager import LabelReferenceManager
from .Msm_4_16_background_reference_manager import BackgroundReferenceManager

# Группа M_5: Стили
from .Msm_5_1_autocad_to_qgis_converter import AutoCADToQGISConverter
from . import Msm_5_2_color_utils

# Группа M_12: Подписи
from .Msm_12_1_collision_manager import CollisionManager
from .Msm_12_2_label_settings_builder import LabelSettingsBuilder

# Группа M_13: Очистка данных
from .Msm_13_1_string_sanitizer import StringSanitizer
from .Msm_13_2_attribute_processor import AttributeProcessor
from .Msm_13_3_field_cleanup import FieldCleanup
from .Msm_13_4_data_validator import DataValidator
from .Msm_13_5_attribute_mapper import AttributeMapper

# Группа M_17: Асинхронные задачи
from .Msm_17_1_base_task import AsyncTaskSignals, BaseAsyncTask
from .Msm_17_2_progress_reporter import MessageBarReporter, SilentReporter

__all__ = [
    # Msm_4: Справочные менеджеры
    # VRIReferenceManager (Msm_4_1) удалён - используйте M_21_VRIAssignmentManager
    'WorkTypeReferenceManager',         # Msm_4_2
    'ProjectMetadataManager',           # Msm_4_3
    'ZOUITReferenceManager',            # Msm_4_4
    'FunctionReferenceManager',         # Msm_4_5
    'LayerReferenceManager',            # Msm_4_6
    'EmployeeReferenceManager',         # Msm_4_7
    'UrbanPlanningReferenceManager',    # Msm_4_8
    'LayerStyleManager',                # Msm_4_9
    'ExcelExportStyleManager',          # Msm_4_10
    'ExcelListStyleManager',            # Msm_4_11
    'LayerFieldStructureManager',       # Msm_4_12
    'DrawingsReferenceManager',         # Msm_4_13
    'DataValidationManager',            # Msm_4_14
    'LabelReferenceManager',            # Msm_4_15
    'BackgroundReferenceManager',       # Msm_4_16

    # Msm_5: Стили
    'AutoCADToQGISConverter',           # Msm_5_1
    'Msm_5_2_color_utils',              # Msm_5_2

    # Msm_12: Подписи
    'CollisionManager',                 # Msm_12_1
    'LabelSettingsBuilder',             # Msm_12_2

    # Msm_13: Очистка данных
    'StringSanitizer',                  # Msm_13_1
    'AttributeProcessor',               # Msm_13_2
    'FieldCleanup',                     # Msm_13_3
    'DataValidator',                    # Msm_13_4
    'AttributeMapper',                  # Msm_13_5

    # Msm_17: Асинхронные задачи
    'AsyncTaskSignals',                 # Msm_17_1
    'BaseAsyncTask',                    # Msm_17_1
    'MessageBarReporter',               # Msm_17_2
    'SilentReporter',                   # Msm_17_2
]
