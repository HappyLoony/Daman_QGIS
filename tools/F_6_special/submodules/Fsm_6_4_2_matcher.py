# -*- coding: utf-8 -*-
"""
Fsm_6_4_2: FileMatcher - поиск файлов по паттернам.

Сканирует папку, собирает файлы и расширения, выполняет
pattern matching (fnmatch) по списку имён.
Case-insensitive. Поддерживает маски * и ?.
"""

import os
import fnmatch
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from Daman_QGIS.utils import log_info, log_error


@dataclass
class MatchedFile:
    """Файл, совпавший с паттерном."""
    full_path: str
    name: str
    extension: str
    size: int
    pattern: str  # Какой паттерн сматчил


@dataclass
class MatchResult:
    """Результат поиска совпадений."""
    matched: List[MatchedFile] = field(default_factory=list)
    unmatched: List[str] = field(default_factory=list)

    @property
    def matched_count(self) -> int:
        return len(self.matched)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.matched)


@dataclass
class FileEntry:
    """Запись о файле в папке."""
    full_path: str
    name: str  # Имя без расширения
    name_with_ext: str  # Полное имя
    extension: str  # Расширение (с точкой, lowercase)
    size: int


class FileMatcher:
    """
    Сканирование папки и поиск файлов по паттернам.

    Использует fnmatch для масок * и ?.
    Case-insensitive для совместимости с Windows.
    """

    def __init__(self, folder: str, include_subdirs: bool = False):
        self._folder = folder
        self._include_subdirs = include_subdirs
        self._files: List[FileEntry] = []
        self._extensions: Dict[str, int] = {}  # ext -> count
        self._scanned = False

    @property
    def extensions(self) -> Dict[str, int]:
        """Расширения и количество файлов для каждого."""
        return dict(self._extensions)

    @property
    def file_count(self) -> int:
        """Общее количество файлов."""
        return len(self._files)

    @property
    def folder(self) -> str:
        return self._folder

    def scan_folder(self) -> None:
        """
        Сканирование папки и сбор информации о файлах.

        Использует os.scandir (быстрее pathlib на Windows).
        Результаты сохраняются для повторного использования.
        """
        self._files.clear()
        self._extensions.clear()
        self._scanned = False

        if not os.path.isdir(self._folder):
            log_error(f"Fsm_6_4_2: Папка не существует: {self._folder}")
            return

        try:
            if self._include_subdirs:
                self._scan_recursive(self._folder)
            else:
                self._scan_flat(self._folder)

            self._scanned = True
            log_info(
                f"Fsm_6_4_2: Просканировано {len(self._files)} файлов, "
                f"{len(self._extensions)} расширений в {self._folder}"
            )

        except PermissionError as e:
            log_error(f"Fsm_6_4_2: Нет доступа к папке: {e}")
        except OSError as e:
            log_error(f"Fsm_6_4_2: Ошибка сканирования: {e}")

    def _scan_flat(self, folder: str) -> None:
        """Сканирование без подпапок."""
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if entry.is_file(follow_symlinks=False):
                        self._add_file_entry(entry)
        except PermissionError:
            log_error(f"Fsm_6_4_2: Нет доступа: {folder}")

    def _scan_recursive(self, folder: str) -> None:
        """Рекурсивное сканирование с подпапками."""
        for root, _dirs, files in os.walk(folder):
            try:
                with os.scandir(root) as entries:
                    for entry in entries:
                        if entry.is_file(follow_symlinks=False):
                            self._add_file_entry(entry)
            except PermissionError:
                log_error(f"Fsm_6_4_2: Нет доступа: {root}")

    def _add_file_entry(self, entry: os.DirEntry) -> None:  # type: ignore[type-arg]
        """Добавление файла в коллекцию."""
        try:
            name_with_ext = entry.name
            name_lower = name_with_ext.lower()

            # Разделение имени и расширения
            dot_pos = name_lower.rfind('.')
            if dot_pos > 0:
                name = name_with_ext[:dot_pos]
                ext = name_lower[dot_pos:]  # .ext (lowercase)
            else:
                name = name_with_ext
                ext = ""

            stat_info = entry.stat(follow_symlinks=False)

            file_entry = FileEntry(
                full_path=entry.path,
                name=name,
                name_with_ext=name_with_ext,
                extension=ext,
                size=stat_info.st_size,
            )
            self._files.append(file_entry)

            # Подсчёт расширений
            if ext:
                self._extensions[ext] = self._extensions.get(ext, 0) + 1

        except OSError:
            pass  # Пропуск недоступных файлов

    def find_matches(
        self,
        patterns: List[str],
        extensions: Optional[Set[str]] = None,
    ) -> MatchResult:
        """
        Поиск файлов по списку паттернов.

        Args:
            patterns: Список имён/паттернов (без расширений).
                Поддерживает маски * и ? (fnmatch).
            extensions: Набор расширений для фильтрации (с точкой, lowercase).
                None = все расширения.

        Returns:
            MatchResult с найденными и ненайденными паттернами.
        """
        if not self._scanned:
            self.scan_folder()

        result = MatchResult()

        # Фильтрация файлов по расширениям
        if extensions:
            filtered_files = [
                f for f in self._files if f.extension in extensions
            ]
        else:
            filtered_files = list(self._files)

        # Индекс для exact match (быстрый путь)
        name_index: Dict[str, List[FileEntry]] = {}
        for f in filtered_files:
            key = f.name.lower()
            if key not in name_index:
                name_index[key] = []
            name_index[key].append(f)

        # Обработка каждого паттерна
        for pattern in patterns:
            pattern_clean = pattern.strip()
            if not pattern_clean:
                continue

            pattern_lower = pattern_clean.lower()
            has_wildcard = '*' in pattern_clean or '?' in pattern_clean
            found = False

            if not has_wildcard:
                # Exact match -- O(1) через индекс
                matches = name_index.get(pattern_lower, [])
                for file_entry in matches:
                    result.matched.append(MatchedFile(
                        full_path=file_entry.full_path,
                        name=file_entry.name_with_ext,
                        extension=file_entry.extension,
                        size=file_entry.size,
                        pattern=pattern_clean,
                    ))
                    found = True
            else:
                # Wildcard -- fnmatch по каждому файлу
                for file_entry in filtered_files:
                    if fnmatch.fnmatch(file_entry.name.lower(), pattern_lower):
                        result.matched.append(MatchedFile(
                            full_path=file_entry.full_path,
                            name=file_entry.name_with_ext,
                            extension=file_entry.extension,
                            size=file_entry.size,
                            pattern=pattern_clean,
                        ))
                        found = True

            if not found:
                result.unmatched.append(pattern_clean)

        return result
