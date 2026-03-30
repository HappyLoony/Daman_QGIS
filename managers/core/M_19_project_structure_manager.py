# -*- coding: utf-8 -*-
"""
M_19: ProjectStructureManager - Координатор структуры папок проекта

Централизованное управление файловой структурой проекта:
- Служебные папки (.project/) - скрыты от пользователя
- Рабочие папки (01_Работа/) - для текущей работы
- Экспортные папки (02_Документы/, 02_Подложки/, 02_Графика/) - результаты
- Архивные папки (03_Архив/) - история версий

Нумерация папок (01_, 02_, 03_) обеспечивает визуальную иерархию:
- 01 = активная работа
- 02 = выходные результаты
- 03 = архив

Все функции плагина должны использовать этот менеджер для получения путей,
а не создавать папки напрямую.
"""

import os
import shutil
from typing import Optional, Dict, Any
from enum import Enum

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.constants import PROJECT_GPKG_NAME

__all__ = ['FolderType', 'ProjectStructureManager']


class FolderType(Enum):
    """Типы папок проекта"""
    # Служебные (скрытые от пользователя)
    SERVICE = "service"           # .project/
    DATABASE = "database"         # .project/database/ (gpkg)
    TEMP = "temp"                 # .project/temp/
    CACHE = "cache"               # .project/cache/

    # Предварительные материалы (00_Предварительно/)
    PRELIMINARY = "preliminary"   # 00_Предварительно/
    GRAPHICS = "graphics"         # 00_Предварительно/Графика к запросам/ (F_1_4)
    BUDGET = "budget"             # 00_Предварительно/Бюджет/ (F_1_3)

    # Рабочая версия (01_Работа/)
    WORKING = "working"           # 01_Работа/
    IMPORT = "import"             # 01_Работа/Импорт/
    EXPORT = "export"             # 01_Работа/Экспорт/
    RASTERS = "rasters"           # 01_Работа/Растры/
    APPENDICES = "appendices"     # 01_Работа/Координаты/
    REGISTERS = "registers"       # 01_Работа/Списки/
    TABLES = "tables"             # 01_Работа/Таблицы/

    # Экспортные (для пользователя)
    DOCUMENTS = "documents"       # 02_Документы/
    BACKGROUNDS = "backgrounds"   # 02_Подложки/

    # Архивные
    RELEASES = "releases"         # 03_Архив/


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
        "created_by": "F_1_2_LoadWeb, M_14_APIManager"
    },

    # Предварительные материалы (00_Предварительно/)
    FolderType.PRELIMINARY: {
        "name": "00_Предварительно",
        "parent": None,
        "user_visible": True,
        "description": "Предварительные материалы (запросы, бюджет)",
        "created_by": "M_1_ProjectManager.create_project"
    },
    FolderType.GRAPHICS: {
        "name": "Графика к запросам",
        "parent": FolderType.PRELIMINARY,
        "user_visible": True,
        "description": "Схема границ для рассылки в ведомства (PDF, DXF, TAB, Excel). Перезаписывается",
        "created_by": "F_1_4_GraphicsRequest"
    },
    FolderType.BUDGET: {
        "name": "Бюджет",
        "parent": FolderType.PRELIMINARY,
        "user_visible": True,
        "description": "Расчёт бюджета выборки (Excel, TXT)",
        "created_by": "F_1_3_BudgetSelection"
    },

    # Рабочая версия
    FolderType.WORKING: {
        "name": "01_Работа",
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
        "name": "Координаты",
        "parent": FolderType.WORKING,
        "user_visible": True,
        "description": "Координатные ведомости (Excel)",
        "created_by": "F_5_3_DocumentExport"
    },
    FolderType.REGISTERS: {
        "name": "Списки",
        "parent": FolderType.WORKING,
        "user_visible": True,
        "description": "Атрибутные списки (Excel)",
        "created_by": "F_5_3_DocumentExport"
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
        "name": "02_Документы",
        "parent": None,
        "user_visible": True,
        "description": "Экспорт документов Word (чертежи, ведомости)",
        "created_by": "F_5_3_DocumentExport"
    },
    FolderType.BACKGROUNDS: {
        "name": "02_Подложки",
        "parent": None,
        "user_visible": True,
        "description": "Экспорт подложек DXF для AutoCAD",
        "created_by": "F_5_2_BackgroundExport"
    },

    # Архив версий
    FolderType.RELEASES: {
        "name": "03_Архив",
        "parent": None,
        "user_visible": True,
        "description": "Архив версий проекта",
        "created_by": "M_3_VersionManager"
    }
}

# Файлы проекта
PROJECT_FILES = {
    "gpkg": {
        "name": PROJECT_GPKG_NAME,
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
        # Защита от registry, который передаёт iface как первый аргумент
        if project_root is not None and not isinstance(project_root, str):
            project_root = None
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

            # Создаём README.txt с описанием структуры
            self._create_readme()

            log_info(f"M_19: Структура проекта создана ({created_count} папок)")
            return True

        except Exception as e:
            log_error(f"M_19: Ошибка создания структуры: {e}")
            return False

    def _create_readme(self) -> None:
        """
        Создать README.txt с описанием структуры проекта.

        Файл помогает пользователям понять назначение папок
        и содержит важное предупреждение о скрытой папке .project.
        """
        if not self._project_root:
            return

        readme_content = """СТРУКТУРА ПРОЕКТА DAMAN
======================

00_Предварительно/      - Предварительные материалы
  Графика к запросам/   - Схема границ для рассылки в ведомства (F_1_4)
  Бюджет/               - Расчёт бюджета выборки (F_1_3)

01_Работа/              - Текущая работа (импорт, экспорт, растры)
  Импорт/               - Импортированные файлы (MIF, DXF, SHP)
  Экспорт/              - Экспортированные файлы
  Растры/               - Растровые подложки (TIF, JPG)
  Координаты/           - Координатные ведомости (Excel)
  Списки/               - Атрибутные списки (Excel)
  Таблицы/              - Таблицы данных

02_Документы/           - Готовые документы Word для печати
02_Подложки/            - DXF файлы для передачи в AutoCAD
03_Архив/               - Сохраненные версии проекта

ВАЖНО!
------
Папка .project содержит базу данных проекта (project.gpkg).
При копировании или переносе проекта ОБЯЗАТЕЛЬНО включайте
эту скрытую папку, иначе все данные будут потеряны!

Путь к базе данных: .project/database/project.gpkg

Для отображения скрытых папок в Windows:
Проводник -> Вид -> Показать -> Скрытые элементы
"""
        readme_path = os.path.join(self._project_root, "README.txt")
        try:
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(readme_content)
            log_info("M_19: Создан README.txt")
        except Exception as e:
            log_warning(f"M_19: Не удалось создать README.txt: {e}")

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
