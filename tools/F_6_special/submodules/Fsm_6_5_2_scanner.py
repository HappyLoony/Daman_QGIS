"""
Fsm_6_5_2: FileLockScanner

Сканирование папки на наличие заблокированных файлов.
Два уровня: парсинг lock-файлов программ + exclusive open test.
"""

import ctypes
import ctypes.wintypes
import os
import struct
import sys
import time
import uuid
import xml.etree.ElementTree as ET
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
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp",
    ".md", ".txt", ".csv",
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
    skipped_entries: int = 0


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
        self._root_name = os.path.basename(self._root) or self._root

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

        # Фаза 2: анализ каждого файла
        lock_targets: Set[str] = set()  # файлы найденные через lock-маркеры

        for i, (entry_path, entry_name) in enumerate(all_entries):
            if progress_callback and i % 50 == 0:
                progress_callback(i, total * 2)

            result.total_files_scanned += 1
            locked = self._check_lock_file(entry_path, entry_name)
            if locked:
                # Fallback: если lock-парсер не определил пользователя
                if locked.locked_by_user == "Неизвестно":
                    locker = _query_file_locker(locked.file_path)
                    if locker:
                        if locker.owner:
                            locked.locked_by_user = locker.owner
                        if not locked.locked_by_host:
                            locked.locked_by_host = os.environ.get(
                                "COMPUTERNAME", ""
                            )

                norm_target = os.path.normpath(locked.file_path).lower()
                if norm_target not in lock_targets:
                    result.locked_files.append(locked)
                    lock_targets.add(norm_target)

        # Фаза 3: exclusive open test для файлов без lock-маркеров
        for i, (entry_path, entry_name) in enumerate(all_entries):
            if progress_callback and i % 50 == 0:
                progress_callback(total + i, total * 2)

            ext = os.path.splitext(entry_name)[1].lower()
            if ext not in CHECKED_EXTENSIONS:
                continue
            # Пропустить сами lock-маркеры
            name_lower = entry_name.lower()
            if (
                name_lower.startswith("~$")
                or name_lower.startswith(".~lock.")
                or name_lower.endswith(".dwl")
                or name_lower.endswith(".dwl2")
                or name_lower.endswith(".laccdb")
            ):
                continue
            norm = os.path.normpath(entry_path).lower()
            if norm in lock_targets:
                continue  # уже найден через lock-файл

            is_locked = self._test_exclusive_open(entry_path)

            if is_locked:
                try:
                    size = os.path.getsize(entry_path)
                except OSError:
                    size = 0

                # RestartManager: определить кто именно держит файл
                user = "Неизвестно"
                host = ""
                program = ""
                locker = _query_file_locker(entry_path)
                if locker:
                    if locker.owner:
                        user = locker.owner
                        # RestartManager видит только локальные процессы
                        host = os.environ.get("COMPUTERNAME", "")
                    if locker.app_name:
                        program = locker.app_name

                rel = os.path.relpath(os.path.dirname(entry_path), self._root)
                result.locked_files.append(
                    LockedFile(
                        file_path=entry_path,
                        file_name=entry_name,
                        relative_path=rel if rel != "." else self._root_name,
                        locked_by_user=user,
                        locked_by_host=host,
                        lock_source="Файл занят",
                        lock_program=program,
                        file_size=size,
                    )
                )

        # Фаза 4: поиск файлов открытых в программах (по заголовкам окон)
        # Ловит файлы загруженные в память без OS-блокировки (Notepad, Photos)
        already_found = {
            os.path.normpath(lf.file_path).lower()
            for lf in result.locked_files
        }
        phase4_found = self._scan_window_titles(all_entries, already_found)
        if phase4_found:
            result.locked_files.extend(phase4_found)
            log_info(
                f"Fsm_6_5_2: Phase4 (окна): найдено {len(phase4_found)} "
                f"файлов открытых в программах"
            )

        if progress_callback:
            progress_callback(total * 2, total * 2)

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
                            result.skipped_entries += 1
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
    ) -> Optional[LockedFile]:
        """Проверяет, является ли файл lock-маркером. Возвращает LockedFile для оригинала."""
        name_lower = file_name.lower()

        # AutoCAD: .dwl / .dwl2
        if name_lower.endswith(".dwl") or name_lower.endswith(".dwl2"):
            return self._parse_dwl_file(file_path, file_name)

        # MS Office: ~$filename.ext
        if name_lower.startswith("~$"):
            return self._parse_office_lock(file_path, file_name)

        # LibreOffice: .~lock.filename.ext#
        if name_lower.startswith(".~lock.") and name_lower.endswith("#"):
            return self._parse_libreoffice_lock(file_path, file_name)

        # MS Access: .laccdb
        if name_lower.endswith(".laccdb"):
            return self._parse_access_lock(file_path, file_name)

        return None

    # ------------------------------------------------------------------
    # Парсеры
    # ------------------------------------------------------------------
    def _parse_dwl_file(
        self,
        dwl_path: str,
        dwl_name: str,
    ) -> Optional[LockedFile]:
        """Парсинг AutoCAD .dwl / .dwl2 файла.

        Формат .dwl (plain text):
            Строка 1: Имя пользователя
            Строка 2: Имя компьютера

        Формат .dwl2 (XML, AutoCAD 2008+):
            <username>User</username>
            <machinename>PC-01</machinename>
        """
        is_dwl2 = dwl_name.lower().endswith(".dwl2")

        if is_dwl2:
            user, host = self._parse_dwl2_xml(dwl_path)
        else:
            user, host = self._parse_dwl_text(dwl_path)

        if not user:
            user = "Неизвестно"

        # Найти оригинальный файл (только в той же папке)
        target_path, target_name = self._find_dwl_target(dwl_path, dwl_name)
        if not target_path:
            return None

        try:
            size = os.path.getsize(target_path)
        except OSError:
            size = 0

        lock_source = "AutoCAD (.dwl2)" if is_dwl2 else "AutoCAD (.dwl)"
        rel = os.path.relpath(os.path.dirname(target_path), self._root)
        return LockedFile(
            file_path=target_path,
            file_name=target_name,
            relative_path=rel if rel != "." else self._root_name,
            locked_by_user=user,
            locked_by_host=host,
            lock_source=lock_source,
            lock_program="AutoCAD",
            file_size=size,
        )

    def _parse_dwl_text(self, dwl_path: str) -> Tuple[str, str]:
        """Парсинг .dwl (plain text): строка 1 = user, строка 2 = host."""
        try:
            with open(dwl_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            return "Неизвестно", ""

        if not lines:
            return "Неизвестно", ""

        user = lines[0].strip() if len(lines) > 0 else "Неизвестно"
        host = lines[1].strip() if len(lines) > 1 else ""
        return user, host

    def _parse_dwl2_xml(self, dwl2_path: str) -> Tuple[str, str]:
        """Парсинг .dwl2 (XML): теги <username>, <machinename>.

        AutoCAD пишет невалидный XML-заголовок: <?xml ... encoding="UTF-8">
        без закрывающего '?' перед '>'. Удаляем заголовок перед парсингом.
        """
        try:
            with open(dwl2_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(4096)
        except OSError:
            return "Неизвестно", ""

        # Убрать невалидную XML-декларацию AutoCAD (<?xml ...> без ?)
        cleaned = content
        if cleaned.startswith("<?xml"):
            newline_pos = cleaned.find("\n")
            if newline_pos != -1:
                cleaned = cleaned[newline_pos + 1:]

        # Попытка XML-парсинга
        try:
            root = ET.fromstring(cleaned)
            user_el = root.find("username")
            host_el = root.find("machinename")
            user = user_el.text.strip() if user_el is not None and user_el.text else ""
            host = host_el.text.strip() if host_el is not None and host_el.text else ""
            if user:
                return user, host
        except ET.ParseError:
            pass

        # Fallback на plain text (старые версии AutoCAD могут писать DWL2 как текст)
        return self._parse_dwl_text(dwl2_path)

    def _find_dwl_target(
        self,
        dwl_path: str,
        dwl_name: str,
    ) -> Tuple[Optional[str], str]:
        """Находит оригинальный файл для .dwl / .dwl2 (только в той же папке)."""
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

        return None, base

    def _parse_office_lock(
        self,
        lock_path: str,
        lock_name: str,
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
            relative_path=rel if rel != "." else self._root_name,
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
            relative_path=rel if rel != "." else self._root_name,
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
            relative_path=rel if rel != "." else self._root_name,
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
        """Проверка: файл открыт другим процессом? True = заблокирован.

        На Windows использует CreateFileW с нулевым sharing mode --
        если любой процесс держит файл открытым (даже shared read),
        CreateFileW вернёт ERROR_SHARING_VIOLATION (32).

        Python open('r+b') не ловит shared access (просмотрщики
        изображений, текстовые редакторы и т.д.).
        """
        if sys.platform == "win32":
            return self._test_exclusive_open_win32(file_path)

        # Fallback для не-Windows
        try:
            with open(file_path, "r+b"):
                pass
            return False
        except PermissionError:
            return True
        except OSError:
            return False

    @staticmethod
    def _test_exclusive_open_win32(file_path: str) -> bool:
        """Windows: CreateFileW с dwShareMode=0 (эксклюзивный доступ).

        Без restype CreateFileW возвращает c_int (32-bit signed).
        INVALID_HANDLE_VALUE = -1 как c_int. Сравниваем напрямую с -1.
        """
        try:
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        except OSError:
            return False

        ERROR_SHARING_VIOLATION = 32

        h = kernel32.CreateFileW(
            file_path,
            ctypes.wintypes.DWORD(0x80000000),  # GENERIC_READ
            ctypes.wintypes.DWORD(0),            # dwShareMode = 0
            None,                                 # lpSecurityAttributes
            ctypes.wintypes.DWORD(3),            # OPEN_EXISTING
            ctypes.wintypes.DWORD(0x80),         # FILE_ATTRIBUTE_NORMAL
            None,                                 # hTemplateFile
        )

        # c_int default restype: INVALID_HANDLE_VALUE = -1
        if h == -1:
            error_code = kernel32.GetLastError()
            return error_code == ERROR_SHARING_VIOLATION

        kernel32.CloseHandle(h)
        return False

    # ------------------------------------------------------------------
    # Phase 4: Window title scan
    # ------------------------------------------------------------------
    def _scan_window_titles(
        self,
        all_entries: List[Tuple[str, str]],
        already_found: Set[str],
    ) -> List[LockedFile]:
        """Поиск файлов открытых в программах по заголовкам окон.

        Программы вроде Notepad, Photos, VS Code загружают файл в память
        и отпускают handle. CreateFileW их не видит, но заголовок окна
        содержит имя файла.
        """
        if sys.platform != "win32":
            return []

        # Собрать имена файлов -> полный путь (для матчинга)
        name_to_entries: Dict[str, List[Tuple[str, str]]] = {}
        for entry_path, entry_name in all_entries:
            key = entry_name.lower()
            if key not in name_to_entries:
                name_to_entries[key] = []
            name_to_entries[key].append((entry_path, entry_name))

        # Получить файлы из заголовков окон
        window_files = _get_open_filenames_from_windows()
        results: List[LockedFile] = []

        for wf_name, proc_name, wf_pid in window_files:
            wf_lower = wf_name.lower()
            if wf_lower not in name_to_entries:
                continue

            for entry_path, entry_name in name_to_entries[wf_lower]:
                norm = os.path.normpath(entry_path).lower()
                if norm in already_found:
                    continue
                already_found.add(norm)

                try:
                    size = os.path.getsize(entry_path)
                except OSError:
                    size = 0

                # Определить пользователя-владельца процесса
                user = _get_process_owner(wf_pid) or ""
                friendly = _FRIENDLY_PROCESS_NAMES.get(
                    proc_name.lower(), proc_name
                )

                rel = os.path.relpath(
                    os.path.dirname(entry_path), self._root
                )
                results.append(
                    LockedFile(
                        file_path=entry_path,
                        file_name=entry_name,
                        relative_path=(
                            rel if rel != "." else self._root_name
                        ),
                        locked_by_user=user,
                        locked_by_host=os.environ.get("COMPUTERNAME", ""),
                        lock_source="Открыт в программе",
                        lock_program=friendly,
                        file_size=size,
                    )
                )

        return results


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

# ---------------------------------------------------------------------------
# Friendly names для процессов (Phase 4 -- window title scan)
# ---------------------------------------------------------------------------
_FRIENDLY_PROCESS_NAMES: Dict[str, str] = {
    # Просмотрщики изображений
    "dllhost.exe": "Просмотр фото",
    "microsoft.photos.exe": "Фотографии",
    "photoviewer.dll": "Просмотр фото",
    "irfanview.exe": "IrfanView",
    "i_view64.exe": "IrfanView",
    "xnview.exe": "XnView",
    "xnviewmp.exe": "XnView MP",
    "mspaint.exe": "Paint",
    "paintdotnet.exe": "Paint.NET",
    # Текстовые редакторы
    "notepad.exe": "Блокнот",
    "notepad++.exe": "Notepad++",
    "code.exe": "VS Code",
    "sublime_text.exe": "Sublime Text",
    "wordpad.exe": "WordPad",
    # Office
    "winword.exe": "Word",
    "excel.exe": "Excel",
    "powerpnt.exe": "PowerPoint",
    "visio.exe": "Visio",
    "onenote.exe": "OneNote",
    "outlook.exe": "Outlook",
    # PDF
    "acrobat.exe": "Acrobat",
    "acrord32.exe": "Acrobat Reader",
    "foxitreader.exe": "Foxit Reader",
    "foxitpdfeditor.exe": "Foxit Editor",
    "sumatrapdf.exe": "SumatraPDF",
    "msedge.exe": "Edge",
    # CAD / GIS
    "acad.exe": "AutoCAD",
    "revit.exe": "Revit",
    "qgis.exe": "QGIS",
    "qgis-bin.exe": "QGIS",
    "explorer.exe": "Проводник",
    # LibreOffice
    "soffice.bin": "LibreOffice",
    "soffice.exe": "LibreOffice",
}


# ---------------------------------------------------------------------------
# EnumWindows: извлечение имён файлов из заголовков окон
# ---------------------------------------------------------------------------
# Разделители заголовков: " - " (большинство), " \u2014 " (em-dash, Notepad RU),
# " | " (некоторые приложения)
_TITLE_SEPARATORS = (" - ", " \u2014 ", " | ")

# Процессы, чьи окна игнорируются (не содержат пользовательских файлов)
_IGNORED_PROCESSES = {
    "explorer.exe", "searchui.exe", "searchhost.exe",
    "shellexperiencehost.exe", "startmenuexperiencehost.exe",
    "textinputhost.exe", "applicationframehost.exe",
    "systemsettings.exe", "taskmgr.exe",
}


def _get_open_filenames_from_windows() -> List[Tuple[str, str, int]]:
    """Извлечь имена файлов из заголовков видимых окон.

    Returns:
        Список кортежей (filename, process_name, pid).
        filename -- только имя файла с расширением (без пути).
    """
    if sys.platform != "win32":
        return []

    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except OSError:
        return []

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    EnumWindowsProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )

    results: List[Tuple[str, str, int]] = []

    def _callback(hwnd: int, _lparam: int) -> bool:
        # Только видимые окна
        if not user32.IsWindowVisible(hwnd):
            return True

        # Читаем заголовок окна
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True

        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value

        # Извлечь имя файла из заголовка
        filename = _extract_filename_from_title(title)
        if not filename:
            return True

        # Определить процесс
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc_name = _get_process_name(kernel32, pid.value)

        # Фильтрация системных процессов
        if proc_name.lower() in _IGNORED_PROCESSES:
            return True

        results.append((filename, proc_name, pid.value))
        return True

    try:
        user32.EnumWindows(EnumWindowsProc(_callback), 0)
    except OSError:
        log_warning("Fsm_6_5_2: EnumWindows failed")

    return results


def _extract_filename_from_title(title: str) -> str:
    """Извлечь имя файла из заголовка окна.

    Паттерн: 'filename.ext - Program Name' или 'filename.ext | App'.
    Возвращает пустую строку если имя файла не найдено.
    """
    for sep in _TITLE_SEPARATORS:
        if sep in title:
            before = title.split(sep)[0].strip()
            # Убрать индикаторы несохранённых изменений
            clean = before.lstrip("*\u25cf ").strip()
            # Должно содержать точку (расширение) и быть похоже на имя файла
            if "." in clean and len(clean) < 260 and "/" not in clean:
                # Убедиться что после последней точки есть расширение (1-10 символов)
                ext_part = clean.rsplit(".", 1)[-1]
                if 1 <= len(ext_part) <= 10 and ext_part.isalnum():
                    return clean
            break
    return ""


def _get_process_name(kernel32: ctypes.WinDLL, pid: int) -> str:  # type: ignore[name-defined]
    """Получить имя процесса по PID через QueryFullProcessImageNameW."""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        name_buf = ctypes.create_unicode_buffer(260)
        size = ctypes.wintypes.DWORD(260)
        if kernel32.QueryFullProcessImageNameW(h, 0, name_buf, ctypes.byref(size)):
            return os.path.basename(name_buf.value)
    finally:
        kernel32.CloseHandle(h)
    return ""


# ---------------------------------------------------------------------------
# Windows RestartManager API -- определение процесса, держащего файл
# ---------------------------------------------------------------------------
@dataclass
class _ProcessLockInfo:
    """Информация о процессе, блокирующем файл."""

    app_name: str
    pid: int
    owner: str


def _query_file_locker(file_path: str) -> Optional[_ProcessLockInfo]:
    """Определить процесс, блокирующий файл через Windows RestartManager API.

    Использует RmStartSession / RmRegisterResources / RmGetList из rstrtmgr.dll.
    Возвращает None если не удалось определить или не Windows.
    """
    if sys.platform != "win32":
        return None

    try:
        rstrtmgr = ctypes.windll.LoadLibrary("rstrtmgr.dll")  # type: ignore[attr-defined]
    except OSError:
        return None

    # Константы
    CCH_RM_MAX_APP_NAME = 255
    CCH_RM_MAX_SVC_NAME = 63
    ERROR_SUCCESS = 0
    ERROR_MORE_DATA = 234

    # Структуры
    class RM_UNIQUE_PROCESS(ctypes.Structure):
        _fields_ = [
            ("dwProcessId", ctypes.wintypes.DWORD),
            ("ProcessStartTime", ctypes.wintypes.FILETIME),
        ]

    class RM_PROCESS_INFO(ctypes.Structure):
        _fields_ = [
            ("Process", RM_UNIQUE_PROCESS),
            ("strAppName", ctypes.c_wchar * (CCH_RM_MAX_APP_NAME + 1)),
            ("strServiceShortName", ctypes.c_wchar * (CCH_RM_MAX_SVC_NAME + 1)),
            ("ApplicationType", ctypes.wintypes.DWORD),
            ("AppStatus", ctypes.wintypes.DWORD),
            ("TSSessionId", ctypes.wintypes.DWORD),
            ("bRestartable", ctypes.wintypes.BOOL),
        ]

    session_handle = ctypes.wintypes.DWORD()
    session_key = ctypes.create_unicode_buffer(64)

    # Генерируем уникальный ключ сессии
    key_str = str(uuid.uuid4())[:32]
    ctypes.memmove(session_key, key_str, len(key_str) * 2)

    # RmStartSession
    ret = rstrtmgr.RmStartSession(
        ctypes.byref(session_handle), 0, session_key
    )
    if ret != ERROR_SUCCESS:
        return None

    try:
        # RmRegisterResources -- зарегистрировать файл
        path_array = (ctypes.c_wchar_p * 1)(file_path)
        ret = rstrtmgr.RmRegisterResources(
            session_handle,
            ctypes.wintypes.UINT(1),
            path_array,
            ctypes.wintypes.UINT(0),
            None,
            ctypes.wintypes.UINT(0),
            None,
        )
        if ret != ERROR_SUCCESS:
            return None

        # RmGetList -- получить список процессов
        proc_info_needed = ctypes.wintypes.UINT(0)
        proc_info_count = ctypes.wintypes.UINT(10)
        proc_info_array = (RM_PROCESS_INFO * 10)()
        reboot_reasons = ctypes.wintypes.DWORD(0)

        ret = rstrtmgr.RmGetList(
            session_handle,
            ctypes.byref(proc_info_needed),
            ctypes.byref(proc_info_count),
            proc_info_array,
            ctypes.byref(reboot_reasons),
        )

        if ret == ERROR_MORE_DATA:
            # Нужно больше места -- повторный вызов
            count = proc_info_needed.value
            proc_info_count = ctypes.wintypes.UINT(count)
            proc_info_array = (RM_PROCESS_INFO * count)()
            ret = rstrtmgr.RmGetList(
                session_handle,
                ctypes.byref(proc_info_needed),
                ctypes.byref(proc_info_count),
                proc_info_array,
                ctypes.byref(reboot_reasons),
            )

        if ret != ERROR_SUCCESS or proc_info_count.value == 0:
            return None

        # Берём первый процесс
        info = proc_info_array[0]
        pid = info.Process.dwProcessId
        app_name = info.strAppName.strip()

        # Определить владельца процесса через OpenProcess + GetTokenInformation
        owner = _get_process_owner(pid)

        return _ProcessLockInfo(
            app_name=app_name,
            pid=pid,
            owner=owner,
        )

    finally:
        rstrtmgr.RmEndSession(session_handle)


def _get_process_owner(pid: int) -> str:
    """Получить имя пользователя-владельца процесса по PID.

    Использует OpenProcess + OpenProcessToken + GetTokenInformation.
    """
    if sys.platform != "win32":
        return ""

    try:
        advapi32 = ctypes.windll.advapi32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except OSError:
        return ""

    PROCESS_QUERY_INFORMATION = 0x0400
    TOKEN_QUERY = 0x0008
    TokenUser = 1

    h_process = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
    if not h_process:
        return ""

    try:
        h_token = ctypes.wintypes.HANDLE()
        if not advapi32.OpenProcessToken(
            h_process, TOKEN_QUERY, ctypes.byref(h_token)
        ):
            return ""

        try:
            # Определить размер буфера
            buf_size = ctypes.wintypes.DWORD(0)
            advapi32.GetTokenInformation(
                h_token, TokenUser, None, 0, ctypes.byref(buf_size)
            )
            if buf_size.value == 0:
                return ""

            buf = ctypes.create_string_buffer(buf_size.value)
            if not advapi32.GetTokenInformation(
                h_token, TokenUser, buf, buf_size, ctypes.byref(buf_size)
            ):
                return ""

            # TOKEN_USER: первые sizeof(LPVOID) байт = указатель на SID
            sid_ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p)).contents

            # LookupAccountSidW
            name_buf = ctypes.create_unicode_buffer(256)
            name_size = ctypes.wintypes.DWORD(256)
            domain_buf = ctypes.create_unicode_buffer(256)
            domain_size = ctypes.wintypes.DWORD(256)
            sid_type = ctypes.wintypes.DWORD(0)

            if advapi32.LookupAccountSidW(
                None,
                sid_ptr,
                name_buf,
                ctypes.byref(name_size),
                domain_buf,
                ctypes.byref(domain_size),
                ctypes.byref(sid_type),
            ):
                return name_buf.value
        finally:
            kernel32.CloseHandle(h_token)
    finally:
        kernel32.CloseHandle(h_process)

    return ""
