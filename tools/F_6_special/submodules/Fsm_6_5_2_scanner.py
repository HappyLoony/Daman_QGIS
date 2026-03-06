"""
Fsm_6_5_2: FileLockScanner

Сканирование папки на наличие заблокированных файлов.
Два уровня: парсинг lock-файлов программ + exclusive open test.
"""

import os
import struct
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from Daman_QGIS.utils import log_error, log_info, log_warning

# ---------------------------------------------------------------------------
# Расширения рабочих файлов для exclusive open test
# ---------------------------------------------------------------------------
CHECKED_EXTENSIONS: Set[str] = {
    ".dwg", ".dxf", ".dgn", ".rvt",
    ".pdf",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".mdb", ".accdb",
    ".vsd", ".vsdx",
    ".gpkg", ".shp", ".qgs", ".qgz", ".tab", ".mxd", ".aprx",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class LockedFile:
    """Информация о заблокированном файле."""

    file_path: str
    file_name: str
    relative_path: str
    locked_by_user: str
    locked_by_host: str
    lock_source: str
    lock_program: str
    file_size: int


@dataclass
class ScanResult:
    """Результат сканирования папки."""

    locked_files: List[LockedFile] = field(default_factory=list)
    total_files_scanned: int = 0
    total_dirs_scanned: int = 0
    scan_duration_ms: int = 0
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Lock-файл маппинг: расширение lock -> расширение оригинала
# ---------------------------------------------------------------------------
_DWL_TARGET_EXTENSIONS = (".dwg", ".dxf", ".dgn")


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------
class FileLockScanner:
    """Сканер заблокированных файлов в папке."""

    def __init__(self, root_folder: str) -> None:
        self._root = os.path.normpath(root_folder)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def scan(
        self,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> ScanResult:
        """Полное рекурсивное сканирование.

        Args:
            progress_callback: функция(current, total) для обновления прогресса.

        Returns:
            ScanResult с найденными блокировками.
        """
        t0 = time.monotonic()
        result = ScanResult()

        # Фаза 1: собрать все файлы рекурсивно
        all_entries = self._collect_entries(result)
        total = len(all_entries)

        if total == 0:
            result.scan_duration_ms = int((time.monotonic() - t0) * 1000)
            return result

        # Индекс файлов по имени (lowercase) для быстрого поиска оригиналов
        name_index: Dict[str, str] = {}
        for entry_path, entry_name in all_entries:
            name_index[entry_name.lower()] = entry_path

        # Фаза 2: анализ каждого файла
        lock_targets: Set[str] = set()  # файлы найденные через lock-маркеры

        for i, (entry_path, entry_name) in enumerate(all_entries):
            if progress_callback and i % 50 == 0:
                progress_callback(i, total)

            result.total_files_scanned += 1
            locked = self._check_lock_file(entry_path, entry_name, name_index)
            if locked:
                result.locked_files.append(locked)
                lock_targets.add(os.path.normpath(locked.file_path).lower())

        # Фаза 3: exclusive open test для файлов без lock-маркеров
        for i, (entry_path, entry_name) in enumerate(all_entries):
            ext = os.path.splitext(entry_name)[1].lower()
            if ext not in CHECKED_EXTENSIONS:
                continue
            norm = os.path.normpath(entry_path).lower()
            if norm in lock_targets:
                continue  # уже найден через lock-файл
            if self._test_exclusive_open(entry_path):
                try:
                    size = os.path.getsize(entry_path)
                except OSError:
                    size = 0
                rel = os.path.relpath(os.path.dirname(entry_path), self._root)
                result.locked_files.append(
                    LockedFile(
                        file_path=entry_path,
                        file_name=entry_name,
                        relative_path=rel if rel != "." else "",
                        locked_by_user="Неизвестно",
                        locked_by_host="",
                        lock_source="Файл занят",
                        lock_program="",
                        file_size=size,
                    )
                )

        if progress_callback:
            progress_callback(total, total)

        result.scan_duration_ms = int((time.monotonic() - t0) * 1000)
        log_info(
            f"Fsm_6_5_2: Сканирование завершено: {len(result.locked_files)} "
            f"блокировок из {result.total_files_scanned} файлов "
            f"за {result.scan_duration_ms} мс"
        )
        return result

    # ------------------------------------------------------------------
    # Сбор файлов
    # ------------------------------------------------------------------
    def _collect_entries(
        self, result: ScanResult
    ) -> List[Tuple[str, str]]:
        """Рекурсивный сбор всех файлов через os.scandir."""
        entries: List[Tuple[str, str]] = []
        dirs_to_scan = [self._root]

        while dirs_to_scan:
            current_dir = dirs_to_scan.pop()
            result.total_dirs_scanned += 1
            try:
                with os.scandir(current_dir) as it:
                    for entry in it:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                dirs_to_scan.append(entry.path)
                            elif entry.is_file(follow_symlinks=False):
                                entries.append((entry.path, entry.name))
                        except OSError:
                            pass
            except PermissionError:
                msg = f"Нет доступа к папке: {current_dir}"
                result.errors.append(msg)
                log_warning(f"Fsm_6_5_2: {msg}")
            except OSError as exc:
                msg = f"Ошибка чтения папки {current_dir}: {exc}"
                result.errors.append(msg)
                log_warning(f"Fsm_6_5_2: {msg}")

        return entries

    # ------------------------------------------------------------------
    # Определение lock-файлов
    # ------------------------------------------------------------------
    def _check_lock_file(
        self,
        file_path: str,
        file_name: str,
        name_index: Dict[str, str],
    ) -> Optional[LockedFile]:
        """Проверяет, является ли файл lock-маркером. Возвращает LockedFile для оригинала."""
        name_lower = file_name.lower()

        # AutoCAD: .dwl / .dwl2
        if name_lower.endswith(".dwl") or name_lower.endswith(".dwl2"):
            return self._parse_dwl_file(file_path, file_name, name_index)

        # MS Office: ~$filename.ext
        if name_lower.startswith("~$"):
            return self._parse_office_lock(file_path, file_name, name_index)

        # LibreOffice: .~lock.filename.ext#
        if name_lower.startswith(".~lock.") and name_lower.endswith("#"):
            return self._parse_libreoffice_lock(file_path, file_name, name_index)

        # MS Access: .laccdb
        if name_lower.endswith(".laccdb"):
            return self._parse_access_lock(file_path, file_name, name_index)

        return None

    # ------------------------------------------------------------------
    # Парсеры
    # ------------------------------------------------------------------
    def _parse_dwl_file(
        self,
        dwl_path: str,
        dwl_name: str,
        name_index: Dict[str, str],
    ) -> Optional[LockedFile]:
        """Парсинг AutoCAD .dwl / .dwl2 файла.

        Формат .dwl:
            Строка 1: Имя пользователя
            Строка 2: Имя компьютера
            (остальные строки -- дата, версия и т.д.)
        """
        try:
            with open(dwl_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            return None

        if not lines:
            return None

        user = lines[0].strip() if len(lines) > 0 else "Неизвестно"
        host = lines[1].strip() if len(lines) > 1 else ""

        if not user:
            user = "Неизвестно"

        # Найти оригинальный файл
        target_path, target_name = self._find_dwl_target(dwl_path, dwl_name, name_index)
        if not target_path:
            return None

        try:
            size = os.path.getsize(target_path)
        except OSError:
            size = 0

        rel = os.path.relpath(os.path.dirname(target_path), self._root)
        return LockedFile(
            file_path=target_path,
            file_name=target_name,
            relative_path=rel if rel != "." else "",
            locked_by_user=user,
            locked_by_host=host,
            lock_source="AutoCAD (.dwl)",
            lock_program="AutoCAD",
            file_size=size,
        )

    def _find_dwl_target(
        self,
        dwl_path: str,
        dwl_name: str,
        name_index: Dict[str, str],
    ) -> Tuple[Optional[str], str]:
        """Находит оригинальный файл для .dwl / .dwl2."""
        # Убрать .dwl2 или .dwl
        base = dwl_name
        if base.lower().endswith(".dwl2"):
            base = base[:-5]
        elif base.lower().endswith(".dwl"):
            base = base[:-4]

        # Проверить расширения в той же папке
        folder = os.path.dirname(dwl_path)
        for ext in _DWL_TARGET_EXTENSIONS:
            candidate = base + ext
            candidate_path = os.path.join(folder, candidate)
            if os.path.isfile(candidate_path):
                return candidate_path, candidate

        # Fallback: поиск в индексе
        for ext in _DWL_TARGET_EXTENSIONS:
            key = (base + ext).lower()
            if key in name_index:
                path = name_index[key]
                return path, os.path.basename(path)

        return None, base

    def _parse_office_lock(
        self,
        lock_path: str,
        lock_name: str,
        name_index: Dict[str, str],
    ) -> Optional[LockedFile]:
        """Парсинг MS Office ~$ lock-файла.

        Имя пользователя хранится в первых байтах (бинарный формат).
        Первый байт -- длина имени, затем имя в ASCII или UTF-16LE.
        """
        user = self._extract_office_username(lock_path)

        # Оригинал: убрать ~$ из начала имени
        original_name = lock_name[2:]  # ~$report.xlsx -> report.xlsx
        folder = os.path.dirname(lock_path)
        original_path = os.path.join(folder, original_name)

        if not os.path.isfile(original_path):
            # Попробовать через индекс
            key = original_name.lower()
            if key in name_index:
                original_path = name_index[key]
            else:
                return None

        # Определить программу по расширению
        ext = os.path.splitext(original_name)[1].lower()
        program = _OFFICE_EXT_TO_PROGRAM.get(ext, "MS Office")

        try:
            size = os.path.getsize(original_path)
        except OSError:
            size = 0

        rel = os.path.relpath(os.path.dirname(original_path), self._root)
        return LockedFile(
            file_path=original_path,
            file_name=original_name,
            relative_path=rel if rel != "." else "",
            locked_by_user=user,
            locked_by_host="",
            lock_source="Office (~$)",
            lock_program=program,
            file_size=size,
        )

    def _extract_office_username(self, lock_path: str) -> str:
        """Извлечь имя пользователя из бинарного ~$ файла Office."""
        try:
            with open(lock_path, "rb") as f:
                data = f.read(512)
        except OSError:
            return "Неизвестно"

        if len(data) < 2:
            return "Неизвестно"

        # Word (.docx): первый байт = длина имени, далее имя в UTF-16LE
        # Excel (.xlsx): может быть plain ASCII с padding нулями
        try:
            name_len = data[0]
            if 1 <= name_len <= 100:
                # Попытка 1: UTF-16LE (Word)
                raw = data[1 : 1 + name_len * 2]
                try:
                    name = raw.decode("utf-16-le").rstrip("\x00").strip()
                    if name and all(c.isprintable() for c in name):
                        return name
                except (UnicodeDecodeError, ValueError):
                    pass

                # Попытка 2: ASCII/CP1251 (Excel)
                raw = data[1 : 1 + name_len]
                try:
                    name = raw.decode("cp1251").rstrip("\x00").strip()
                    if name and all(c.isprintable() for c in name):
                        return name
                except (UnicodeDecodeError, ValueError):
                    pass

            # Попытка 3: поиск читаемой строки в начале файла
            for encoding in ("utf-16-le", "utf-8", "cp1251"):
                try:
                    text = data.decode(encoding, errors="ignore")
                    # Извлечь первую читаемую последовательность
                    clean = []
                    for ch in text:
                        if ch.isprintable() and ch not in ("\t", "\r", "\n"):
                            clean.append(ch)
                        elif clean:
                            break
                    candidate = "".join(clean).strip()
                    if 2 <= len(candidate) <= 50:
                        return candidate
                except (UnicodeDecodeError, ValueError):
                    continue

        except (IndexError, struct.error):
            pass

        return "Неизвестно"

    def _parse_libreoffice_lock(
        self,
        lock_path: str,
        lock_name: str,
        name_index: Dict[str, str],
    ) -> Optional[LockedFile]:
        """Парсинг LibreOffice .~lock.filename# файла.

        Формат: user,host,PID,date,path,env (CSV через запятую).
        """
        try:
            with open(lock_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(1024).strip()
        except OSError:
            return None

        parts = content.split(",")
        user = parts[0].strip() if len(parts) > 0 else "Неизвестно"
        host = parts[1].strip() if len(parts) > 1 else ""

        if not user:
            user = "Неизвестно"

        # Оригинал: .~lock.filename.ext# -> filename.ext
        original_name = lock_name
        if original_name.startswith(".~lock."):
            original_name = original_name[7:]  # убрать .~lock.
        if original_name.endswith("#"):
            original_name = original_name[:-1]  # убрать #

        folder = os.path.dirname(lock_path)
        original_path = os.path.join(folder, original_name)

        if not os.path.isfile(original_path):
            key = original_name.lower()
            if key in name_index:
                original_path = name_index[key]
            else:
                return None

        ext = os.path.splitext(original_name)[1].lower()
        program = "LibreOffice"

        try:
            size = os.path.getsize(original_path)
        except OSError:
            size = 0

        rel = os.path.relpath(os.path.dirname(original_path), self._root)
        return LockedFile(
            file_path=original_path,
            file_name=original_name,
            relative_path=rel if rel != "." else "",
            locked_by_user=user,
            locked_by_host=host,
            lock_source="LibreOffice (.~lock)",
            lock_program=program,
            file_size=size,
        )

    def _parse_access_lock(
        self,
        lock_path: str,
        lock_name: str,
        name_index: Dict[str, str],
    ) -> Optional[LockedFile]:
        """Парсинг MS Access .laccdb файла.

        Содержит записи по 64 байта: имя компьютера + имя пользователя.
        """
        try:
            with open(lock_path, "rb") as f:
                data = f.read(256)
        except OSError:
            return None

        # Извлечь первую запись (текущий пользователь)
        user = "Неизвестно"
        host = ""
        try:
            # Первые 32 байта -- имя компьютера, следующие 32 -- имя пользователя
            if len(data) >= 64:
                host = data[:32].decode("utf-16-le", errors="ignore").rstrip("\x00").strip()
                user = data[32:64].decode("utf-16-le", errors="ignore").rstrip("\x00").strip()
                if not user:
                    user = "Неизвестно"
        except (UnicodeDecodeError, ValueError):
            pass

        # Оригинал: filename.laccdb -> filename.accdb (или .mdb)
        base = os.path.splitext(lock_name)[0]
        folder = os.path.dirname(lock_path)

        original_path = None
        original_name = ""
        for ext in (".accdb", ".mdb"):
            candidate = base + ext
            candidate_path = os.path.join(folder, candidate)
            if os.path.isfile(candidate_path):
                original_path = candidate_path
                original_name = candidate
                break

        if not original_path:
            return None

        try:
            size = os.path.getsize(original_path)
        except OSError:
            size = 0

        rel = os.path.relpath(os.path.dirname(original_path), self._root)
        return LockedFile(
            file_path=original_path,
            file_name=original_name,
            relative_path=rel if rel != "." else "",
            locked_by_user=user,
            locked_by_host=host,
            lock_source="Access (.laccdb)",
            lock_program="MS Access",
            file_size=size,
        )

    # ------------------------------------------------------------------
    # Exclusive open test (fallback)
    # ------------------------------------------------------------------
    def _test_exclusive_open(self, file_path: str) -> bool:
        """Попытка эксклюзивного открытия файла. True = заблокирован."""
        try:
            with open(file_path, "r+b"):
                pass
            return False
        except PermissionError:
            return True
        except OSError:
            # Другие ошибки (файл не найден и т.д.) -- не считаем блокировкой
            return False


# ---------------------------------------------------------------------------
# Маппинг расширений Office -> программа
# ---------------------------------------------------------------------------
_OFFICE_EXT_TO_PROGRAM: Dict[str, str] = {
    ".doc": "Word",
    ".docx": "Word",
    ".xls": "Excel",
    ".xlsx": "Excel",
    ".ppt": "PowerPoint",
    ".pptx": "PowerPoint",
    ".vsd": "Visio",
    ".vsdx": "Visio",
}
