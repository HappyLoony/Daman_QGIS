# -*- coding: utf-8 -*-
"""
Managers - Централизованная система менеджеров Daman_QGIS

Структура:
- M_1: ProjectManager - управление проектами
- M_2: LayerManager - управление слоями
- M_3: VersionManager - управление версиями
- M_4: ReferenceManager - фабрика справочных менеджеров
- M_5: StyleManager - управление стилями
- M_6: CoordinatePrecisionManager - точность координат
- M_7: ExpressionManager - QGIS выражения
- M_8: LayerReplacementManager - замена слоёв
- M_10: LayerCleanupManager - очистка слоёв
- M_12: LabelManager - управление подписями
- M_13: DataCleanupManager - очистка и санитизация данных (включает FieldCleanup)
- M_14: APIManager - управление API endpoints
- M_15: FeatureSortManager - сортировка объектов по КН
- M_16: CadnumSearchManager - поиск объектов по кадастровому номеру (ПКМ)
- M_17: AsyncTaskManager - асинхронные фоновые задачи (QgsTask)
- M_18: ExtentManager - управление экстентами карт в макетах
- M_19: ProjectStructureManager - координатор структуры папок проекта
- M_20: PointNumberingManager - нумерация характерных точек контуров
- M_21: VRIAssignmentManager - присвоение и валидация ВРИ
- M_22: WorkTypeAssignmentManager - присвоение Вид_Работ и План_ВРИ
- M_23: OksZuAnalysisManager - анализ связей ОКС-ЗУ (авто-заполнение)
- M_24: SyncManager - синхронизация выписок с выборкой (авто-синхронизация)
- M_25: FillsManager - распределение по категориям и правам (авто-заполнение)
- M_26: CuttingManager - нарезка ЗПР по границам ЗУ (Facade для F_3_1/F_3_2)
- M_27: MinAreaValidator - валидация минимальных площадей по ВРИ
- M_28: LayerSchemaValidator - валидация структуры слоёв (обязательные поля)
- M_29: LicenseManager - управление лицензиями и Hardware ID
- M_30: NetworkManager - HTTP клиент с JWT авторизацией
"""

# Основные менеджеры
from .M_1_project_manager import ProjectManager
from .M_2_layer_manager import LayerManager
from .M_3_version_manager import VersionManager
from .M_4_reference_manager import (
    ReferenceManagers,
    get_reference_managers,
    create_reference_managers,
    reload_reference_managers
)
from .M_5_style_manager import StyleManager
from .M_6_coordinate_precision import CoordinatePrecisionManager
from .M_7_expression_manager import ExpressionManager
from .M_8_layer_replacement_manager import LayerReplacementManager
from .M_10_layer_cleanup_manager import LayerCleanupManager
from .M_12_label_manager import LabelManager
from .M_13_data_cleanup_manager import DataCleanupManager
from .M_14_api_manager import APIManager
from .M_15_feature_sort_manager import FeatureSortManager
from .M_16_cadnum_search_manager import CadnumSearchManager
from .M_17_async_task_manager import AsyncTaskManager, get_async_manager, reset_async_manager
from .M_18_extent_manager import ExtentManager, get_extent_manager, reset_extent_manager
from .M_19_project_structure_manager import (
    ProjectStructureManager,
    FolderType,
    get_project_structure_manager,
    reset_project_structure_manager
)
from .M_20_point_numbering_manager import (
    PointNumberingManager,
    number_layer_points
)
from .M_21_vri_assignment_manager import VRIAssignmentManager
from .M_22_work_type_assignment_manager import (
    WorkTypeAssignmentManager,
    LayerType,
    StageType
)
from .M_23_oks_zu_analysis_manager import OksZuAnalysisManager
from .M_24_sync_manager import SyncManager
from .M_25_fills_manager import FillsManager, get_fills_manager, reset_fills_manager
from .M_26_cutting_manager import CuttingManager, get_cutting_manager, reset_cutting_manager
from .M_27_min_area_validator import MinAreaValidator
from .M_28_layer_schema_validator import LayerSchemaValidator
from .M_29_license_manager import (
    LicenseManager,
    LicenseStatus,
    get_license_manager,
    reset_license_manager
)
from .M_30_network_manager import (
    NetworkManager,
    NetworkStatus,
    get_network_manager,
    reset_network_manager
)

__all__ = [
    # M_1: Управление проектами
    'ProjectManager',

    # M_2: Управление слоями
    'LayerManager',

    # M_3: Управление версиями
    'VersionManager',

    # M_4: Справочные менеджеры
    'ReferenceManagers',
    'get_reference_managers',
    'create_reference_managers',
    'reload_reference_managers',

    # M_5: Стили
    'StyleManager',

    # M_6: Точность координат
    'CoordinatePrecisionManager',

    # M_7: Выражения
    'ExpressionManager',

    # M_8: Замена слоёв
    'LayerReplacementManager',

    # M_10: Очистка слоёв
    'LayerCleanupManager',

    # M_12: Подписи
    'LabelManager',

    # M_13: Очистка и санитизация данных
    'DataCleanupManager',

    # M_14: API endpoints
    'APIManager',

    # M_15: Сортировка по КН
    'FeatureSortManager',

    # M_16: Поиск по кадастровому номеру
    'CadnumSearchManager',

    # M_17: Асинхронные задачи
    'AsyncTaskManager',
    'get_async_manager',
    'reset_async_manager',

    # M_18: Управление экстентами карт
    'ExtentManager',
    'get_extent_manager',
    'reset_extent_manager',

    # M_19: Структура папок проекта
    'ProjectStructureManager',
    'FolderType',
    'get_project_structure_manager',
    'reset_project_structure_manager',

    # M_20: Нумерация точек контуров
    'PointNumberingManager',
    'number_layer_points',

    # M_21: Присвоение и валидация ВРИ
    'VRIAssignmentManager',

    # M_22: Присвоение Вид_Работ
    'WorkTypeAssignmentManager',
    'LayerType',
    'StageType',

    # M_23: Анализ связей ОКС-ЗУ
    'OksZuAnalysisManager',

    # M_24: Синхронизация выписок с выборкой
    'SyncManager',

    # M_25: Распределение по категориям и правам
    'FillsManager',
    'get_fills_manager',
    'reset_fills_manager',

    # M_26: Нарезка ЗПР по границам ЗУ
    'CuttingManager',
    'get_cutting_manager',
    'reset_cutting_manager',

    # M_27: Валидация минимальных площадей по ВРИ
    'MinAreaValidator',

    # M_28: Валидация структуры слоёв
    'LayerSchemaValidator',

    # M_29: Лицензирование
    'LicenseManager',
    'LicenseStatus',
    'get_license_manager',
    'reset_license_manager',

    # M_30: Сетевой менеджер
    'NetworkManager',
    'NetworkStatus',
    'get_network_manager',
    'reset_network_manager',
]
