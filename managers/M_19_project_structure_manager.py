# -*- coding: utf-8 -*-
"""
M_19: ProjectStructureManager - Координатор структуры папок проекта

Централизованное управление файловой структурой проекта:
- Служебные папки (.project/) - скрыты от пользователя
- Рабочие папки (Рабочая версия/) - для текущей работы
- Экспортные папки (Документы/, Подложки/, Графика/) - результаты для пользователя
- Архивные папки (Выпуски/) - история версий

Все функции плагина должны использовать этот менеджер для получения путей,
а не создавать папки напрямую.
"""

import os
import shutil
from typing import Optional, Dict, Any
from enum import Enum

from Daman_QGIS.utils import log_info, log_warning, log_error


class FolderType(Enum):
    """Типы папок проекта"""
    # Служебные (скрытые от пользователя)
    SERVICE = "service"           # .project/
    DATABASE = "database"         # .project/database/ (gpkg)
    TEMP = "temp"                 # .project/temp/
    CACHE = "cache"               # .project/cache/

    # Рабочая версия
    WORKING = "working"           # Рабочая версия/
    IMPORT = "import"             # Рабочая версия/Импорт/
    EXPORT = "export"             # Рабочая версия/Экспорт/
    RASTERS = "rasters"           # Рабочая версия/Растры/
    APPENDICES = "appendices"     # Рабочая версия/Приложения/
    REGISTERS = "registers"       # Рабочая версия/Ведомости/
    TABLES = "tables"             # Рабочая версия/Таблицы/

    # Экспортные (для пользователя)
    DOCUMENTS = "documents"       # Документы/
    BACKGROUNDS = "backgrounds"   # Подложки/
    GRAPHICS = "graphics"         # Графика/

    # Архивные
    RELEASES = "releases"         # Выпуски/


# Структура папок проекта (новая консистентная схема)
# ВАЖНО: Все папки создаются ТОЛЬКО через этот менеджер!
# Поле "created_by" указывает функцию, ответственную за использование папки
PROJECT_FOLDERS = {
    # Служебные папки
    FolderType.SERVICE: {
        "name": ".project",
        "parent": None,
        "user_visible": False,
        "description": "Служебная папка проекта",
        "created_by": "M_1_ProjectManager.create_project"
    },
    FolderType.DATABASE: {
        "name": "database",
        "parent": FolderType.SERVICE,
        "user_visible": False,
        "description": "База данных проекта (project.gpkg)",
        "created_by": "M_1_ProjectManager.create_project"
    },
    FolderType.TEMP: {
        "name": "temp",
        "parent": FolderType.SERVICE,
        "user_visible": False,
        "description": "Временные файлы операций",
        "created_by": "M_19_ProjectStructureManager (по требованию)"
    },
    FolderType.CACHE: {
        "name": "cache",
        "parent": FolderType.SERVICE,
        "user_visible": False,
        "description": "Кэш данных API и WFS",
        "created_by": "F_1_2_LoadWMS, M_14_APIManager"
    },

    # Рабочая версия
    FolderType.WORKING: {
        "name": "Рабочая версия",
        "parent": None,
        "user_visible": True,
        "description": "Текущая рабочая версия проекта",
        "created_by": "M_1_ProjectManager.create_project"
    },
    FolderType.IMPORT: {
        "name": "Импорт",
        "parent": FolderType.WORKING,
        "user_visible": True,
        "description": "Импортированные файлы (MIF, DXF, SHP)",
        "created_by": "F_1_1_Import"
    },
    FolderType.EXPORT: {
        "name": "Экспорт",
        "parent": FolderType.WORKING,
        "user_visible": True,
        "description": "Экспортированные файлы",
        "created_by": "F_1_5_UniversalExport"
    },
    FolderType.RASTERS: {
        "name": "Растры",
        "parent": FolderType.WORKING,
        "user_visible": True,
        "description": "Растровые подложки (TIF, JPG)",
        "created_by": "F_1_1_Import (растры)"
    },
    FolderType.APPENDICES: {
        "name": "Приложения",
        "parent": FolderType.WORKING,
        "user_visible": True,
        "description": "Координатные ведомости (Excel)",
        "created_by": "F_6_3_DocumentExport"
    },
    FolderType.REGISTERS: {
        "name": "Ведомости",
        "parent": FolderType.WORKING,
        "user_visible": True,
        "description": "Атрибутные списки (Excel)",
        "created_by": "F_6_3_DocumentExport"
    },
    FolderType.TABLES: {
        "name": "Таблицы",
        "parent": FolderType.WORKING,
        "user_visible": True,
        "description": "Таблицы данных и результаты бюджета",
        "created_by": "F_1_3_BudgetSelection"
    },

    # Экспортные папки (в корне проекта)
    FolderType.DOCUMENTS: {
        "name": "Документы",
        "parent": None,
        "user_visible": True,
        "description": "Экспорт документов Word (чертежи, ведомости)",
        "created_by": "F_6_3_DocumentExport"
    },
    FolderType.BACKGROUNDS: {
        "name": "Подложки",
        "parent": None,
        "user_visible": True,
        "description": "Экспорт подложек DXF для AutoCAD",
        "created_by": "F_6_2_BackgroundExport"
    },
    FolderType.GRAPHICS: {
        "name": "Графика",
        "parent": None,
        "user_visible": True,
        "description": "Графика к запросам (PDF, DXF, TAB, Excel)",
        "created_by": "F_1_4_GraphicsRequest"
    },

    # Архив версий
    FolderType.RELEASES: {
        "name": "Выпуски",
        "parent": None,
        "user_visible": True,
        "description": "Архив версий проекта",
        "created_by": "M_3_VersionManager"
    }
}

# Файлы проекта
PROJECT_FILES = {
    "gpkg": {
        "name": "project.gpkg",
        "folder": FolderType.DATABASE,
        "description": "База данных GeoPackage"
    },
    "qgs": {
        "name": "{project_name}.qgs",
        "folder": None,  # В корне проекта
        "description": "Файл проекта QGIS"
    }
}

# Паттерн для архивных версий
RELEASE_PATTERN = "Выпуск_{date}"  # Выпуск_2025_12_01


class ProjectStructureManager:
    """
    Менеджер структуры папок проекта.

    Централизует все операции с файловой системой проекта:
    - Создание структуры при новом проекте
    - Получение путей к папкам
    - Создание папок по требованию
    - Очистка временных папок
    - Миграция старых проектов

    Использование:
        from Daman_QGIS.managers import ProjectStructureManager

        structure_manager = ProjectStructureManager(project_root)

        # Получить путь к папке (создаст если не существует)
        docs_path = structure_manager.get_folder(FolderType.DOCUMENTS)

        # Получить путь к gpkg
        gpkg_path = structure_manager.get_gpkg_path()
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        Args:
            project_root: Корневая папка проекта. Если None, менеджер неактивен.
        """
        self._project_root = project_root
        self._folders_cache: Dict[FolderType, str] = {}

    @property
    def project_root(self) -> Optional[str]:
        """Корневая папка проекта"""
        return self._project_root

    @project_root.setter
    def project_root(self, value: Optional[str]):
        """Установка корневой папки (сбрасывает кэш)"""
        self._project_root = value
        self._folders_cache.clear()

    def is_active(self) -> bool:
        """Проверка активности менеджера (есть ли проект)"""
        return self._project_root is not None and os.path.exists(self._project_root)

    # =========================================================================
    # ПОЛУЧЕНИЕ ПУТЕЙ
    # =========================================================================

    def get_folder(self, folder_type: FolderType, create: bool = True) -> Optional[str]:
        """
        Получить путь к папке указанного типа.

        Args:
            folder_type: Тип папки из FolderType
            create: Создать папку если не существует

        Returns:
            Абсолютный путь к папке или None если проект не открыт
        """
        if not self.is_active():
            log_warning(f"M_19: Проект не открыт, невозможно получить путь к {folder_type.value}")
            return None

        # Type narrowing: is_active() guarantees _project_root is not None
        assert self._project_root is not None

        # Проверяем кэш
        if folder_type in self._folders_cache:
            path = self._folders_cache[folder_type]
            if create and not os.path.exists(path):
                os.makedirs(path, exist_ok=True)
            return path

        # Строим путь
        folder_config = PROJECT_FOLDERS.get(folder_type)
        if not folder_config:
            log_error(f"M_19: Неизвестный тип папки: {folder_type}")
            return None

        # Рекурсивно строим путь с учётом родительской папки
        if folder_config["parent"]:
            parent_path = self.get_folder(folder_config["parent"], create=create)
            if not parent_path:
                return None
            path = os.path.join(parent_path, folder_config["name"])
        else:
            path = os.path.join(self._project_root, folder_config["name"])

        # Создаём если нужно
        if create and not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            log_info(f"M_19: Создана папка {folder_config['name']}")

        # Кэшируем
        self._folders_cache[folder_type] = path

        return path

    def get_gpkg_path(self, create: bool = False) -> Optional[str]:
        """
        Получить путь к файлу GeoPackage.

        Args:
            create: Создать папку database если не существует (по умолчанию False)

        Returns:
            Абсолютный путь к project.gpkg
        """
        db_folder = self.get_folder(FolderType.DATABASE, create=create)
        if not db_folder:
            return None
        return os.path.join(db_folder, PROJECT_FILES["gpkg"]["name"])

    def get_qgs_path(self, project_name: str) -> Optional[str]:
        """
        Получить путь к файлу проекта QGIS.

        Args:
            project_name: Имя проекта

        Returns:
            Абсолютный путь к {project_name}.qgs
        """
        if not self.is_active():
            return None
        # Type narrowing: is_active() guarantees _project_root is not None
        assert self._project_root is not None
        return os.path.join(self._project_root, f"{project_name}.qgs")

    # =========================================================================
    # СОЗДАНИЕ СТРУКТУРЫ
    # =========================================================================

    def create_project_structure(self) -> bool:
        """
        Создать полную структуру папок нового проекта.

        Returns:
            True если успешно
        """
        if not self._project_root:
            log_error("M_19: Не указана корневая папка проекта")
            return False

        try:
            # Создаём корневую папку
            os.makedirs(self._project_root, exist_ok=True)

            # Создаём все папки из структуры
            created_count = 0
            for folder_type in FolderType:
                path = self.get_folder(folder_type, create=True)
                if path:
                    created_count += 1

            log_info(f"M_19: Структура проекта создана ({created_count} папок)")
            return True

        except Exception as e:
            log_error(f"M_19: Ошибка создания структуры: {e}")
            return False

    def create_release_folder(self, date_str: str) -> Optional[str]:
        """
        Создать папку для нового выпуска (архивной версии).

        Args:
            date_str: Дата в формате YYYY_MM_DD

        Returns:
            Путь к созданной папке или None
        """
        releases_path = self.get_folder(FolderType.RELEASES, create=True)
        if not releases_path:
            return None

        release_name = RELEASE_PATTERN.format(date=date_str)
        release_path = os.path.join(releases_path, release_name)

        # Если папка существует, добавляем счётчик
        counter = 1
        original_path = release_path
        while os.path.exists(release_path):
            counter += 1
            release_path = f"{original_path}_{counter}"

        os.makedirs(release_path, exist_ok=True)
        log_info(f"M_19: Создана папка выпуска: {release_name}")

        return release_path

    # =========================================================================
    # ОЧИСТКА
    # =========================================================================

    def clear_folder(self, folder_type: FolderType, recreate: bool = True) -> bool:
        """
        Очистить папку (удалить содержимое).

        Args:
            folder_type: Тип папки
            recreate: Создать папку заново после удаления

        Returns:
            True если успешно
        """
        path = self.get_folder(folder_type, create=False)
        if not path or not os.path.exists(path):
            if recreate:
                self.get_folder(folder_type, create=True)
            return True

        try:
            shutil.rmtree(path)
            log_info(f"M_19: Очищена папка {PROJECT_FOLDERS[folder_type]['name']}")

            if recreate:
                os.makedirs(path, exist_ok=True)

            return True

        except Exception as e:
            log_error(f"M_19: Ошибка очистки папки: {e}")
            return False

    def clear_temp(self) -> bool:
        """Очистить временную папку"""
        return self.clear_folder(FolderType.TEMP, recreate=True)

    def clear_cache(self) -> bool:
        """Очистить кэш"""
        return self.clear_folder(FolderType.CACHE, recreate=True)

    # =========================================================================
    # ИНФОРМАЦИЯ
    # =========================================================================

    def get_structure_info(self) -> Dict[str, Any]:
        """
        Получить информацию о структуре проекта.

        Returns:
            Словарь с информацией о папках
        """
        info = {
            "project_root": self._project_root,
            "is_active": self.is_active(),
            "folders": {}
        }

        if self.is_active():
            for folder_type in FolderType:
                config = PROJECT_FOLDERS[folder_type]
                path = self.get_folder(folder_type, create=False)
                info["folders"][folder_type.value] = {
                    "name": config["name"],
                    "path": path,
                    "exists": os.path.exists(path) if path else False,
                    "user_visible": config["user_visible"],
                    "description": config["description"],
                    "created_by": config.get("created_by", "unknown")
                }

        return info

    def get_folder_info(self, folder_type: FolderType) -> Optional[Dict[str, Any]]:
        """
        Получить информацию о конкретной папке.

        Args:
            folder_type: Тип папки

        Returns:
            Словарь с информацией о папке или None
        """
        if folder_type not in PROJECT_FOLDERS:
            return None

        config = PROJECT_FOLDERS[folder_type]
        path = self.get_folder(folder_type, create=False) if self.is_active() else None

        return {
            "type": folder_type.value,
            "name": config["name"],
            "path": path,
            "exists": os.path.exists(path) if path else False,
            "parent": config["parent"].value if config["parent"] else None,
            "user_visible": config["user_visible"],
            "description": config["description"],
            "created_by": config.get("created_by", "unknown")
        }

    @staticmethod
    def get_all_folder_types() -> Dict[str, Dict[str, Any]]:
        """
        Получить информацию о всех типах папок (статический метод).

        Returns:
            Словарь с информацией о всех папках проекта
        """
        result = {}
        for folder_type in FolderType:
            config = PROJECT_FOLDERS[folder_type]
            result[folder_type.value] = {
                "name": config["name"],
                "parent": config["parent"].value if config["parent"] else None,
                "user_visible": config["user_visible"],
                "description": config["description"],
                "created_by": config.get("created_by", "unknown")
            }
        return result


# Глобальный экземпляр (singleton pattern)
_instance: Optional[ProjectStructureManager] = None


def get_project_structure_manager() -> ProjectStructureManager:
    """Получить глобальный экземпляр менеджера структуры"""
    global _instance
    if _instance is None:
        _instance = ProjectStructureManager()
    return _instance


def reset_project_structure_manager():
    """Сбросить глобальный экземпляр (при закрытии проекта)"""
    global _instance
    if _instance:
        _instance.project_root = None
    _instance = None
