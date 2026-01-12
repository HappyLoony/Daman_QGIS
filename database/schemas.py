# -*- coding: utf-8 -*-
"""
Схемы данных для Daman_QGIS.
Определяет структуры для проектов и слоев.
Справочные данные теперь в отдельных JSON базах в data/reference/
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

# Система метаданных проекта
# Префиксы: 1_ - обязательные поля, 2_ - необязательные поля
METADATA_FIELDS = {
    # Обязательные поля (префикс 1_)
    '1_0_working_name': {
        'ui_name': 'Рабочее название (для папок)',
        'db_key': '1_0_working_name',
        'required': True,
        'placeholder': 'Обязательно',
        'description': 'Используется для названия папок и файлов'
    },
    '1_1_full_name': {
        'ui_name': 'Полное наименование объекта',
        'db_key': '1_1_full_name',
        'required': True,
        'placeholder': 'Обязательно',
        'description': 'Используется в документах и макетах'
    },
    '1_2_object_type': {
        'ui_name': 'Тип объекта',
        'db_key': '1_2_object_type',
        'required': True,
        'placeholder': None,  # ComboBox
        'description': 'Площадной или линейный объект'
    },
    '1_3_project_folder': {
        'ui_name': 'Папка проекта',
        'db_key': '1_3_project_folder',
        'required': True,
        'placeholder': 'Обязательно',
        'description': 'Путь к папке проекта'
    },
    '1_4_crs': {
        'ui_name': 'Система координат',
        'db_key': '1_4_crs',  # Включает crs_epsg, crs_wkt, crs_description
        'required': True,
        'placeholder': None,  # CRS Widget
        'description': 'Система координат проекта'
    },
    '1_5_doc_type': {
        'ui_name': 'Тип документации',
        'db_key': '1_5_doc_type',
        'required': True,
        'placeholder': None,  # ComboBox
        'description': 'Разработка ДПТ или Мастер-План'
    },
    # Дополнительные поля (префикс 2_)
    '2_1_code': {
        'ui_name': 'Шифр',
        'db_key': '2_1_code',
        'required': False,
        'placeholder': 'Дополнительно',
        'description': 'Внутренняя кодировка объекта'
    }
}

# Функция для получения UI названия по ключу
def get_metadata_ui_name(db_key: str) -> str:
    """Получить человекочитаемое название поля по ключу БД"""
    for field_data in METADATA_FIELDS.values():
        if field_data['db_key'] == db_key:
            return field_data['ui_name']
    return db_key  # Если не найдено, возвращаем сам ключ


# Типы объектов проектирования - теперь в data/reference/project_metadata.json
# Категории земель - теперь в data/reference/land_categories.json
# Виды работ - теперь в data/reference/work_types.json
# ВРИ - теперь в data/reference/vri.json

@dataclass
class ProjectSettings:
    """Настройки проекта Daman_QGIS"""
    name: str
    created: datetime
    modified: datetime
    version: str = ""  # Версия берется из metadata.txt через main_plugin
    crs_epsg: int = 0  # EPSG код системы координат
    gpkg_path: str = ""  # Путь к основному GeoPackage
    work_dir: str = ""   # Рабочая папка проекта
    
    # Метаданные объекта
    object_name: str = ""  # Наименование объекта
    object_type: str = ""  # Тип объекта (Линейный/Площадной)
    crs_description: str = ""  # Описание СК (например "МСК 14 зона 2")
    
    # Настройки слоев
    auto_numbering: bool = True  # Автоматическая нумерация слоев
    readonly_imports: bool = True  # Импортированные слои только для чтения
    
    # Настройки версионирования
    versioning_enabled: bool = True
    current_version: str = "Рабочая версия"  # Папка текущей версии (M_19: FolderType.WORKING)
    
    # Дополнительные параметры (расширяемые)
    custom_settings: Dict[str, Any] = field(default_factory=dict)

@dataclass 
class LayerInfo:
    """Информация о слое в проекте"""
    id: str  # Уникальный ID слоя
    name: str  # Имя слоя
    type: str  # Тип слоя (vector, raster)
    geometry_type: str  # Тип геометрии для векторных
    source_path: str  # Путь к источнику данных
    prefix: str  # Префикс нумерации
    created: datetime
    modified: datetime
    readonly: bool = False
    visible: bool = True
    style_path: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ImportSettings:
    """Настройки импорта данных"""
    source_format: str  # Формат источника (MIF, TAB, DXF, etc.)
    target_layer_name: str
    crs_transform: bool = True  # Преобразовывать СК
    target_crs: Optional[Any] = None  # Целевая СК (QgsCoordinateReferenceSystem)
    encoding: str = "utf-8"  # Кодировка атрибутов
    simplify_geometry: bool = False
    fix_geometry: bool = True
    attributes_mapping: Dict[str, str] = field(default_factory=dict)

@dataclass
class ExportSettings:
    """Настройки экспорта данных"""
    target_format: str  # Формат экспорта (DXF, DOCX, XLSX, etc.)
    output_path: str
    layers: List[str]  # Список слоев для экспорта
    include_attributes: bool = True
    include_styles: bool = True
    format_specific: Dict[str, Any] = field(default_factory=dict)

@dataclass
class VersionInfo:
    """Информация о версии проекта"""
    version_name: str  # Например "Выпуск_от_2025_08_24"
    created: datetime
    description: str = ""
    author: str = ""
    is_current: bool = False
    parent_version: Optional[str] = None
    files_count: int = 0
    size_mb: float = 0.0

# Структура меню инструментов
# ВАЖНО: Используется динамическая структура для гибкости
# Номера и названия могут меняться без изменения кода
@dataclass
class ToolMenuItem:
    """Элемент меню инструмента"""
    id: str  # Уникальный ID инструмента (не зависит от номера)
    display_name: str  # Отображаемое имя с номером
    tool_class_name: str  # Имя класса инструмента
    parent_id: Optional[str] = None  # ID родительского меню
    icon: Optional[str] = None
    enabled: bool = True
    order: int = 0  # Порядок в меню

# ВАЖНО: Структура папок проекта определена в M_19_ProjectStructureManager
# Все операции с папками должны использовать ProjectStructureManager
# НЕ используйте хардкод путей - импортируйте из M_19:
# from Daman_QGIS.managers.M_19_project_structure_manager import (
#     get_project_structure_manager, FolderType, PROJECT_FOLDERS, RELEASE_PATTERN
# )
