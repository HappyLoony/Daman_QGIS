# -*- coding: utf-8 -*-
"""
Fsm_6_5_3: Принудительное закрытие заблокированных файлов.

Два режима:
- Сетевой (UNC): LogonUser + NetFileEnum + NetFileClose (Netapi32.dll)
- Локальный: RmShutdown через RestartManager (Rstrtmgr.dll)
"""

import ctypes
import ctypes.wintypes
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from Daman_QGIS.utils import log_error, log_info, log_warning


# ---------------------------------------------------------------------------
# Результат операции закрытия
# ---------------------------------------------------------------------------
@dataclass
class CloseResult:
    """Результат принудительного закрытия файлов."""

    closed_count: int = 0
    failed_files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Определение типа пути
# ---------------------------------------------------------------------------
def resolve_to_unc(path: str) -> str:
    """Резолвить маппированный диск (A:\\...) в UNC путь (\\\\server\\...).

    Если путь уже UNC или резолв не удался -- возвращает оригинал.
    """
    if sys.platform != "win32":
        return path

    normalized = path.replace("/", "\\")
    if normalized.startswith("\\\\"):
        return normalized  # Уже UNC

    # Проверить маппированный диск (A:, Z: и т.д.)
    if len(normalized) >= 2 and normalized[1] == ":":
        drive = normalized[:2]  # "A:"
        try:
            mpr = ctypes.WinDLL("mpr", use_last_error=True)
            buf = ctypes.create_unicode_buffer(512)
            buf_size = ctypes.wintypes.DWORD(512)
            ret = mpr.WNetGetConnectionW(drive, buf, ctypes.byref(buf_size))
            if ret == 0 and buf.value:
                # Заменить "A:\folder" на "\\server\share\folder"
                unc_root = buf.value  # "\\server\share"
                rest = normalized[2:]  # "\folder\..."
                resolved = unc_root + rest
                log_info(
                    f"Fsm_6_5_3: Resolved {drive} -> {unc_root}"
                )
                return resolved
        except OSError:
            pass

    return normalized


def is_unc_path(path: str) -> bool:
    """Проверка: путь UNC (сетевая шара) или маппированный диск?"""
    resolved = resolve_to_unc(path)
    return resolved.startswith("\\\\")


def parse_unc_path(path: str) -> Tuple[str, str]:
    """Разобрать UNC путь на сервер и basepath.

    \\\\server\\share\\folder -> ("server", "share\\folder")
    Маппированный диск резолвится автоматически.
    """
    normalized = resolve_to_unc(path).lstrip("\\")
    parts = normalized.split("\\")
    if len(parts) < 2:
        return parts[0], ""
    server = parts[0]
    basepath = "\\".join(parts[1:])
    return server, basepath


# ===========================================================================
# Сетевое закрытие (NetFileEnum + NetFileClose)
# ===========================================================================
def close_network_files(
    server: str,
    basepath: str,
    username: str,
    domain: str,
    password: str,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> CloseResult:
    """Принудительное закрытие файлов на сетевом сервере.

    Args:
        server: имя сервера (без \\\\)
        basepath: путь от корня шары (share\\folder)
        username: имя admin пользователя
        domain: домен
        password: пароль
        progress_callback: callback(message) для обновления статуса

    Returns:
        CloseResult с количеством закрытых файлов и ошибками.
    """
    if sys.platform != "win32":
        return CloseResult(errors=["Поддерживается только Windows"])

    result = CloseResult()

    # 1. Импер сонация через LogonUser
    token = _logon_user(username, domain, password)
    if token is None:
        err = ctypes.get_last_error()
        msg = f"Ошибка аутентификации (код {err}). Проверьте логин и пароль."
        log_error(f"Fsm_6_5_3: LogonUser failed: err={err}")
        result.errors.append(msg)
        return result

    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        if not advapi32.ImpersonateLoggedOnUser(token):
            err = ctypes.get_last_error()
            msg = f"Ошибка имперсонации (код {err})"
            log_error(f"Fsm_6_5_3: ImpersonateLoggedOnUser failed: err={err}")
            result.errors.append(msg)
            return result

        try:
            # 2. Получить список открытых файлов
            if progress_callback:
                progress_callback("Получение списка открытых файлов...")

            open_files = _net_file_enum(server, basepath)
            if not open_files:
                log_info("Fsm_6_5_3: NetFileEnum: нет открытых файлов")
                return result

            log_info(
                f"Fsm_6_5_3: NetFileEnum: найдено {len(open_files)} "
                f"открытых файлов на \\\\{server}\\{basepath}"
            )

            # 3. Закрыть каждый файл
            for file_id, file_path, file_user in open_files:
                if progress_callback:
                    fname = os.path.basename(file_path)
                    progress_callback(f"Закрытие: {fname} ({file_user})")

                success = _net_file_close(server, file_id)
                if success:
                    result.closed_count += 1
                    log_info(
                        f"Fsm_6_5_3: Closed: {file_path} "
                        f"(user={file_user}, id={file_id})"
                    )
                else:
                    result.failed_files.append(file_path)
                    log_warning(
                        f"Fsm_6_5_3: Failed to close: {file_path} "
                        f"(id={file_id})"
                    )

        finally:
            advapi32.RevertToSelf()
            log_info("Fsm_6_5_3: RevertToSelf OK")

    finally:
        ctypes.windll.kernel32.CloseHandle(token)  # type: ignore[attr-defined]

    return result


def _logon_user(
    username: str, domain: str, password: str
) -> Optional[ctypes.wintypes.HANDLE]:
    """LogonUser с типом NEW_CREDENTIALS для сетевого доступа."""
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    LOGON32_LOGON_NEW_CREDENTIALS = 9
    LOGON32_PROVIDER_DEFAULT = 0

    token = ctypes.wintypes.HANDLE()
    success = advapi32.LogonUserW(
        username,
        domain if domain else None,
        password,
        LOGON32_LOGON_NEW_CREDENTIALS,
        LOGON32_PROVIDER_DEFAULT,
        ctypes.byref(token),
    )

    if success:
        log_info(f"Fsm_6_5_3: LogonUser OK: {domain}\\{username}")
        return token
    return None


def _net_file_enum(
    server: str, basepath: str
) -> List[Tuple[int, str, str]]:
    """NetFileEnum level 3: список открытых файлов на сервере.

    Returns:
        Список кортежей (file_id, pathname, username).
    """
    try:
        netapi32 = ctypes.WinDLL("netapi32", use_last_error=True)
    except OSError:
        log_error("Fsm_6_5_3: Не удалось загрузить netapi32.dll")
        return []

    # FILE_INFO_3 structure
    class FILE_INFO_3(ctypes.Structure):
        _fields_ = [
            ("fi3_id", ctypes.wintypes.DWORD),
            ("fi3_permissions", ctypes.wintypes.DWORD),
            ("fi3_num_locks", ctypes.wintypes.DWORD),
            ("fi3_pathname", ctypes.wintypes.LPWSTR),
            ("fi3_username", ctypes.wintypes.LPWSTR),
        ]

    buf_ptr = ctypes.POINTER(FILE_INFO_3)()
    entries_read = ctypes.wintypes.DWORD(0)
    total_entries = ctypes.wintypes.DWORD(0)
    resume_handle = ctypes.wintypes.DWORD(0)

    server_str = f"\\\\{server}"

    NERR_Success = 0
    ERROR_MORE_DATA = 234

    results: List[Tuple[int, str, str]] = []

    while True:
        ret = netapi32.NetFileEnum(
            server_str,
            basepath if basepath else None,
            None,  # username filter (None = все)
            3,  # level
            ctypes.byref(buf_ptr),
            0xFFFFFFFF,  # MAX_PREFERRED_LENGTH
            ctypes.byref(entries_read),
            ctypes.byref(total_entries),
            ctypes.byref(resume_handle),
        )

        if ret not in (NERR_Success, ERROR_MORE_DATA):
            log_error(f"Fsm_6_5_3: NetFileEnum failed: ret={ret}")
            break

        if entries_read.value > 0 and buf_ptr:
            arr = ctypes.cast(
                buf_ptr,
                ctypes.POINTER(FILE_INFO_3 * entries_read.value),
            )
            for i in range(entries_read.value):
                fi = arr.contents[i]
                pathname = fi.fi3_pathname or ""
                username = fi.fi3_username or ""
                results.append((fi.fi3_id, pathname, username))

        # Освободить буфер
        if buf_ptr:
            netapi32.NetApiBufferFree(buf_ptr)
            buf_ptr = ctypes.POINTER(FILE_INFO_3)()

        if ret != ERROR_MORE_DATA:
            break

    return results


def _net_file_close(server: str, file_id: int) -> bool:
    """NetFileClose: закрыть конкретный открытый файл на сервере."""
    try:
        netapi32 = ctypes.WinDLL("netapi32", use_last_error=True)
    except OSError:
        return False

    server_str = f"\\\\{server}"
    ret = netapi32.NetFileClose(server_str, file_id)

    NERR_Success = 0
    return ret == NERR_Success


# ===========================================================================
# Локальное закрытие (RestartManager)
# ===========================================================================
def close_local_files(
    file_paths: List[str],
    progress_callback: Optional[Callable[[str], None]] = None,
) -> CloseResult:
    """Принудительное закрытие локальных файлов через RestartManager.

    Сначала graceful (WM_CLOSE), потом force если не помогло.

    Args:
        file_paths: список путей к заблокированным файлам
        progress_callback: callback(message) для обновления статуса

    Returns:
        CloseResult.
    """
    if sys.platform != "win32":
        return CloseResult(errors=["Поддерживается только Windows"])

    result = CloseResult()

    try:
        rstrtmgr = ctypes.WinDLL("rstrtmgr", use_last_error=True)
    except OSError:
        result.errors.append("Не удалось загрузить rstrtmgr.dll")
        return result

    # 1. Начать сессию
    session = ctypes.wintypes.DWORD()
    session_key = ctypes.create_unicode_buffer(
        str(uuid.uuid4()).replace("-", "")[:32]
    )
    ret = rstrtmgr.RmStartSession(
        ctypes.byref(session), 0, session_key
    )
    if ret != 0:
        result.errors.append(f"RmStartSession failed: ret={ret}")
        log_error(f"Fsm_6_5_3: RmStartSession failed: ret={ret}")
        return result

    try:
        # 2. Зарегистрировать файлы
        file_array = (ctypes.c_wchar_p * len(file_paths))(
            *file_paths
        )
        ret = rstrtmgr.RmRegisterResources(
            session.value,
            len(file_paths),
            file_array,
            0, None,  # applications
            0, None,  # services
        )
        if ret != 0:
            result.errors.append(f"RmRegisterResources failed: ret={ret}")
            log_error(
                f"Fsm_6_5_3: RmRegisterResources failed: ret={ret}"
            )
            return result

        # 3. Получить список процессов
        n_needed = ctypes.wintypes.UINT(0)
        n_info = ctypes.wintypes.UINT(0)
        reason = ctypes.wintypes.DWORD(0)

        ret = rstrtmgr.RmGetList(
            session.value,
            ctypes.byref(n_needed),
            ctypes.byref(n_info),
            None,
            ctypes.byref(reason),
        )

        if n_needed.value == 0:
            log_info("Fsm_6_5_3: RmGetList: нет процессов")
            return result

        process_count = n_needed.value
        log_info(
            f"Fsm_6_5_3: RmGetList: {process_count} процессов "
            f"используют {len(file_paths)} файлов"
        )

        # 4. Graceful shutdown (WM_CLOSE)
        if progress_callback:
            progress_callback("Отправка WM_CLOSE приложениям...")

        RmForceShutdown = 0x1
        ret = rstrtmgr.RmShutdown(session.value, 0, None)

        if ret == 0:
            result.closed_count = process_count
            log_info(
                f"Fsm_6_5_3: RmShutdown graceful OK: "
                f"{process_count} процессов"
            )
        else:
            # 5. Graceful не сработал -- force shutdown
            log_warning(
                f"Fsm_6_5_3: RmShutdown graceful failed (ret={ret}), "
                f"trying force..."
            )
            if progress_callback:
                progress_callback(
                    "Принудительное завершение приложений..."
                )

            time.sleep(2)
            ret = rstrtmgr.RmShutdown(
                session.value, RmForceShutdown, None
            )

            if ret == 0:
                result.closed_count = process_count
                log_info(
                    f"Fsm_6_5_3: RmShutdown force OK: "
                    f"{process_count} процессов"
                )
            else:
                msg = f"RmShutdown force failed: ret={ret}"
                result.errors.append(msg)
                log_error(f"Fsm_6_5_3: {msg}")

    finally:
        rstrtmgr.RmEndSession(session.value)

    return result
