# -*- coding: utf-8 -*-
"""
M_3: VersionManager - Менеджер версий проектов

Управление версионированием проектов через M_19_ProjectStructureManager.
Рабочая версия: "Рабочая версия/"
Архивные версии: "Выпуски/Выпуск_YYYY_MM_DD/"
"""

import os
import shutil
from datetime import datetime
from typing import List, Optional, Dict, Any

from qgis.core import Qgis

from Daman_QGIS.constants import MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION
from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.database.schemas import VersionInfo
from Daman_QGIS.managers.M_19_project_structure_manager import (
    get_project_structure_manager, FolderType, PROJECT_FOLDERS, RELEASE_PATTERN
)


class VersionManager:
    """Менеджер версий проектов"""

    def __init__(self, iface: Any, project_path: Optional[str] = None) -> None:
        """
        Инициализация менеджера версий

        Args:
            iface: Интерфейс QGIS
            project_path: Путь к проекту
        """
        self.iface = iface
        self._structure_manager = get_project_structure_manager()
        if project_path:
            self._structure_manager.project_root = project_path

    @property
    def project_path(self) -> Optional[str]:
        """Путь к проекту"""
        return self._structure_manager.project_root

    @project_path.setter
    def project_path(self, value: Optional[str]):
        """Установка пути к проекту"""
        self._structure_manager.project_root = value

    def set_project_path(self, project_path: str) -> None:
        """Установка пути к проекту"""
        self._structure_manager.project_root = project_path

    def _get_working_folder_name(self) -> str:
        """Получить имя рабочей папки из M_19"""
        return PROJECT_FOLDERS[FolderType.WORKING]["name"]

    def _get_working_path(self) -> Optional[str]:
        """Получить путь к рабочей папке"""
        return self._structure_manager.get_folder(FolderType.WORKING, create=False)

    def _get_releases_path(self) -> Optional[str]:
        """Получить путь к папке выпусков"""
        return self._structure_manager.get_folder(FolderType.RELEASES, create=True)

    def create_version(self, description: str = "", author: str = "") -> Optional[str]:
        """
        Создание новой версии (архивирование текущей рабочей версии)

        Args:
            description: Описание версии
            author: Автор версии

        Returns:
            Имя созданной версии или None
        """
        if not self._structure_manager.is_active():
            raise ValueError("Путь к проекту не установлен")

        # Путь к рабочей версии
        working_path = self._get_working_path()
        if not working_path or not os.path.exists(working_path):
            raise ValueError(f"Рабочая папка не найдена: {working_path}")

        # Создаём папку для выпуска через M_19
        date_str = datetime.now().strftime("%Y_%m_%d")
        release_path = self._structure_manager.create_release_folder(date_str)

        if not release_path:
            raise RuntimeError("Не удалось создать папку выпуска")

        version_name = os.path.basename(release_path)
        log_info(f"M_3: Создание версии: {version_name}")

        try:
            # Копируем содержимое рабочей версии в папку выпуска
            for item in os.listdir(working_path):
                src = os.path.join(working_path, item)
                dst = os.path.join(release_path, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)

        except OSError as e:
            log_error(f"M_3: Ошибка копирования версии: {e}")
            # Удаляем созданную папку при ошибке
            if os.path.exists(release_path):
                shutil.rmtree(release_path, ignore_errors=True)
            raise RuntimeError(f"Не удалось создать версию: {e}") from e

        # Создаем информацию о версии
        version_info = VersionInfo(
            version_name=version_name,
            created=datetime.now(),
            description=description,
            author=author,
            is_current=False,
            parent_version=self._get_previous_version(),
            files_count=self._count_files(release_path),
            size_mb=self._get_folder_size(release_path)
        )

        # Сохраняем метаданные версии
        self._save_version_info(release_path, version_info)

        log_info(f"M_3: Версия '{version_name}' успешно создана")

        self.iface.messageBar().pushMessage(
            "Успех",
            f"Создана версия: {version_name}",
            level=Qgis.Success,
            duration=MESSAGE_INFO_DURATION
        )

        return version_name

    def list_versions(self) -> List[VersionInfo]:
        """
        Получение списка всех версий проекта

        Returns:
            Список версий
        """
        versions = []

        if not self._structure_manager.is_active():
            return versions

        # Добавляем текущую рабочую версию
        working_path = self._get_working_path()
        if working_path and os.path.exists(working_path):
            version_info = VersionInfo(
                version_name=self._get_working_folder_name(),
                created=datetime.fromtimestamp(os.path.getctime(working_path)),
                description="Текущая рабочая версия",
                author="",
                is_current=True,
                files_count=self._count_files(working_path),
                size_mb=self._get_folder_size(working_path)
            )
            versions.append(version_info)

        # Ищем архивные версии в папке Выпуски/
        releases_path = self._get_releases_path()
        if releases_path and os.path.exists(releases_path):
            for item in os.listdir(releases_path):
                item_path = os.path.join(releases_path, item)

                if os.path.isdir(item_path) and item.startswith("Выпуск_"):
                    # Пытаемся загрузить метаданные
                    version_info = self._load_version_info(item_path)
                    if version_info:
                        versions.append(version_info)
                    else:
                        # Создаем информацию по умолчанию
                        version_info = VersionInfo(
                            version_name=item,
                            created=datetime.fromtimestamp(os.path.getctime(item_path)),
                            description="",
                            author="",
                            is_current=False,
                            files_count=self._count_files(item_path),
                            size_mb=self._get_folder_size(item_path)
                        )
                        versions.append(version_info)

        # Сортируем по дате создания (новые первые)
        versions.sort(key=lambda v: v.created, reverse=True)

        return versions

    def restore_version(self, version_name: str) -> bool:
        """
        Восстановление версии (замена текущей рабочей версии)

        Args:
            version_name: Имя версии для восстановления

        Returns:
            True если восстановление успешно
        """
        if not self._structure_manager.is_active():
            raise ValueError("Путь к проекту не установлен")

        releases_path = self._get_releases_path()
        if not releases_path:
            raise ValueError("Папка выпусков не найдена")

        version_path = os.path.join(releases_path, version_name)
        if not os.path.exists(version_path):
            raise ValueError(f"Версия не найдена: {version_name}")

        working_path = self._get_working_path()
        if not working_path:
            raise ValueError("Рабочая папка не определена")

        # Создаем резервную копию текущей версии
        backup_name = f"Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_path = os.path.join(releases_path, backup_name)

        if os.path.exists(working_path):
            try:
                shutil.copytree(working_path, backup_path)
                log_info(f"M_3: Создана резервная копия: {backup_name}")
            except OSError as e:
                log_error(f"M_3: Ошибка создания резервной копии: {e}")
                raise RuntimeError(f"Не удалось создать резервную копию: {e}") from e

        # Очищаем рабочую папку и копируем выбранную версию
        try:
            # Очищаем содержимое рабочей папки
            for item in os.listdir(working_path):
                item_path = os.path.join(working_path, item)
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)

            # Копируем содержимое версии
            for item in os.listdir(version_path):
                if item == 'version_info.json':
                    continue  # Пропускаем метаданные
                src = os.path.join(version_path, item)
                dst = os.path.join(working_path, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)

        except OSError as e:
            log_error(f"M_3: Ошибка восстановления версии: {e}")
            raise RuntimeError(f"Не удалось восстановить версию: {e}") from e

        log_info(f"M_3: Версия '{version_name}' восстановлена")

        self.iface.messageBar().pushMessage(
            "Успех",
            f"Версия '{version_name}' успешно восстановлена",
            level=Qgis.Success,
            duration=MESSAGE_INFO_DURATION
        )

        return True

    def delete_version(self, version_name: str) -> bool:
        """
        Удаление версии

        Args:
            version_name: Имя версии для удаления

        Returns:
            True если удаление успешно
        """
        if not self._structure_manager.is_active():
            raise ValueError("Путь к проекту не установлен")

        # Нельзя удалить текущую рабочую версию
        if version_name == self._get_working_folder_name():
            raise ValueError("Нельзя удалить текущую рабочую версию")

        releases_path = self._get_releases_path()
        if not releases_path:
            raise ValueError("Папка выпусков не найдена")

        version_path = os.path.join(releases_path, version_name)
        if not os.path.exists(version_path):
            raise ValueError(f"Версия не найдена: {version_name}")

        try:
            shutil.rmtree(version_path)
        except OSError as e:
            log_error(f"M_3: Ошибка удаления версии: {e}")
            raise RuntimeError(f"Не удалось удалить версию: {e}") from e

        log_info(f"M_3: Версия '{version_name}' удалена")

        self.iface.messageBar().pushMessage(
            "Успех",
            f"Версия '{version_name}' удалена",
            level=Qgis.Success,
            duration=MESSAGE_SUCCESS_DURATION
        )

        return True

    def compare_versions(self, version1: str, version2: str) -> Dict[str, Any]:
        """
        Сравнение двух версий

        Args:
            version1: Имя первой версии
            version2: Имя второй версии

        Returns:
            Словарь с результатами сравнения
        """
        comparison = {
            'version1': version1,
            'version2': version2,
            'differences': []
        }

        if not self._structure_manager.is_active():
            raise ValueError("Путь к проекту не установлен")

        releases_path = self._get_releases_path()
        working_name = self._get_working_folder_name()

        # Определяем пути к версиям
        if version1 == working_name:
            path1 = self._get_working_path()
        else:
            path1 = os.path.join(releases_path, version1) if releases_path else None

        if version2 == working_name:
            path2 = self._get_working_path()
        else:
            path2 = os.path.join(releases_path, version2) if releases_path else None

        if not path1 or not path2 or not os.path.exists(path1) or not os.path.exists(path2):
            raise ValueError("Одна из версий не найдена")

        # Сравниваем файлы
        files1 = set(self._get_all_files(path1))
        files2 = set(self._get_all_files(path2))

        only_in_1 = files1 - files2
        only_in_2 = files2 - files1
        common = files1 & files2

        comparison['only_in_version1'] = list(only_in_1)
        comparison['only_in_version2'] = list(only_in_2)
        comparison['common_files'] = len(common)

        # Сравниваем размеры
        size1 = self._get_folder_size(path1)
        size2 = self._get_folder_size(path2)
        comparison['size_version1_mb'] = size1
        comparison['size_version2_mb'] = size2
        comparison['size_difference_mb'] = size2 - size1

        return comparison

    def _get_previous_version(self) -> Optional[str]:
        """Получение имени предыдущей версии"""
        versions = self.list_versions()
        for v in versions:
            if not v.is_current:
                return v.version_name
        return None

    def _count_files(self, path: str) -> int:
        """Подсчет количества файлов в папке"""
        count = 0
        try:
            for root, dirs, files in os.walk(path):
                count += len(files)
        except OSError as e:
            log_warning(f"M_3: Ошибка при подсчёте файлов в {path}: {e}")
        return count

    def _get_folder_size(self, path: str) -> float:
        """Получение размера папки в МБ"""
        total_size = 0
        try:
            for root, dirs, files in os.walk(path):
                for file in files:
                    file_path = os.path.join(root, file)
                    if os.path.exists(file_path):
                        total_size += os.path.getsize(file_path)
        except OSError as e:
            log_warning(f"M_3: Ошибка при расчёте размера папки {path}: {e}")
        return round(total_size / (1024 * 1024), 2)

    def _get_all_files(self, path: str) -> List[str]:
        """Получение списка всех файлов в папке"""
        all_files = []
        try:
            for root, dirs, files in os.walk(path):
                for file in files:
                    rel_path = os.path.relpath(os.path.join(root, file), path)
                    all_files.append(rel_path)
        except OSError as e:
            log_warning(f"M_3: Ошибка при получении списка файлов из {path}: {e}")
        return all_files

    def _save_version_info(self, version_path: str, version_info: VersionInfo) -> None:
        """Сохранение информации о версии"""
        try:
            import json
            info_file = os.path.join(version_path, 'version_info.json')

            data = {
                'version_name': version_info.version_name,
                'created': version_info.created.isoformat(),
                'description': version_info.description,
                'author': version_info.author,
                'parent_version': version_info.parent_version,
                'files_count': version_info.files_count,
                'size_mb': version_info.size_mb
            }

            with open(info_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except (OSError, IOError) as e:
            log_warning(f"M_3: Не удалось сохранить информацию о версии: {e}")

    def _load_version_info(self, version_path: str) -> Optional[VersionInfo]:
        """Загрузка информации о версии"""
        try:
            import json
            info_file = os.path.join(version_path, 'version_info.json')

            if not os.path.exists(info_file):
                return None

            with open(info_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            return VersionInfo(
                version_name=data['version_name'],
                created=datetime.fromisoformat(data['created']),
                description=data.get('description', ''),
                author=data.get('author', ''),
                is_current=False,
                parent_version=data.get('parent_version'),
                files_count=data.get('files_count', 0),
                size_mb=data.get('size_mb', 0.0)
            )
        except (OSError, IOError, json.JSONDecodeError, KeyError) as e:
            log_warning(f"M_3: Не удалось загрузить информацию о версии: {e}")
            return None
