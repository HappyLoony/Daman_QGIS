# -*- coding: utf-8 -*-
"""
Fsm_4_1_10_NetworkDoctor - Диагностика и починка сетевых проблем

Универсальный "сетевой доктор" для обнаружения и исправления проблем,
вызванных некорректным удалением VPN/прокси/антивирусов (AdGuard, Kaspersky,
ESET, Fiddler, Charles Proxy и др.).

Staged repair:
  Stage 1 - user-level, без перезагрузки (прокси, DNS cache, user-сертификаты)
  Stage 2 - admin, без перезагрузки (WinHTTP, DNS адаптеры, machine-сертификаты)
  Stage 3 - admin + перезагрузка (драйверы, Winsock, TCP/IP reset)
"""

import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

from Daman_QGIS.utils import log_error, log_info, log_warning

# Windows-only imports
if sys.platform == 'win32':
    import winreg


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DiagResult:
    """Результат одной диагностической проверки"""
    name: str
    status: str  # "ok" | "issue" | "error" | "skip"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    fixable: bool = False
    needs_admin: bool = False


@dataclass
class FixResult:
    """Результат одной починки"""
    name: str
    success: bool
    message: str
    needs_reboot: bool = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Паттерны ВСЕГДА подозрительных сертификатов (MITM/отладочные прокси)
ALWAYS_SUSPICIOUS_CERT_PATTERNS = [
    "do_not_trust_fiddlerroot",
    "fiddler",
    "charles proxy",
    "mitmproxy",
    "proxyman",
    "burp suite",
]

# Антивирусы/VPN — подозрительны ТОЛЬКО если ПО не запущено (осиротевший сертификат)
# Формат: (паттерн_сертификата, [имена_процессов_с_.exe])
ANTIVIRUS_CERT_PATTERNS: list = [
    ("kaspersky", ["avp.exe", "avpui.exe"]),
    ("adguard", ["adguard.exe", "adguardsvc.exe"]),
    ("eset ssl filter", ["ekrn.exe", "egui.exe"]),
    ("avast", ["avastsvc.exe", "avastui.exe"]),
    ("avg", ["avgsvc.exe", "avgui.exe"]),
]

# Подозрительные файлы драйверов в system32/drivers
SUSPICIOUS_DRIVER_FILES = [
    "adgnetworkwfpdrv.sys",
    "adgnetworktdidrv.sys",
]

# Подозрительные имена сервисов
SUSPICIOUS_SERVICE_NAMES = [
    "adgnetworkwfpdrv",
    "adgnetworktdidrv",
]

# Подозрительные сетевые адаптеры
SUSPICIOUS_ADAPTER_PATTERNS = [
    "adguard",
    "wintun",
]

# URL для тестирования connectivity
CONNECTIVITY_TEST_URLS = [
    ("https://google.com", "Google"),
    ("https://github.com", "GitHub"),
    ("https://nspd.gov.ru", "Rosreestr NSPD"),
    ("https://niigais.nextgis.com", "NextGIS"),
]

# Стандартные записи hosts, которые НЕ являются подозрительными
HOSTS_STANDARD_ENTRIES: Set[str] = {
    "localhost",
    "localhost.localdomain",
    "local",
    "broadcasthost",
    "ip6-localhost",
    "ip6-loopback",
    "ip6-localnet",
    "ip6-mcastprefix",
    "ip6-allnodes",
    "ip6-allrouters",
    "ip6-allhosts",
}

# Суффиксы хостов, добавляемые известным ПО (Docker, WSL, Kubernetes)
HOSTS_KNOWN_SOFTWARE_SUFFIXES = (
    ".docker.internal",
    ".kubernetes.docker.internal",
    ".wsl.localhost",
    ".wsl.internal",
    ".mshome.net",
)

# Домены, осознанно блокируемые пользователями (лицензионные проверки ПО)
# Не являются результатом VPN/антивируса — не считаем подозрительными
HOSTS_USER_BLOCK_PATTERNS = (
    ".autodesk.com",                   # Autodesk license (genuine-software*, ase-cdn*)
    ".adobe.io",                       # Adobe license/telemetry
    "lmlicenses.wip4.adobe.com",       # Adobe License Management
    "activation.cloud.techsmith.com",  # TechSmith (Camtasia, Snagit)
)

# IP-адреса используемые для блокировки доменов (AdGuard, антивирусы, ad-blocker)
HOSTS_BLOCKING_IPS: Set[str] = {"127.0.0.1", "0.0.0.0", "::1", "::"}

# Переменные окружения прокси
PROXY_ENV_VARS = [
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "FTP_PROXY",
    "http_proxy", "https_proxy", "no_proxy", "all_proxy", "ftp_proxy",
]

# Известные сторонние WFP провайдеры (от VPN/антивирусов)
WFP_SUSPICIOUS_PROVIDERS = [
    "adguard", "kaspersky", "eset", "avast", "avg", "norton",
    "bitdefender", "dr.web", "comodo", "zonealarm", "glasswire",
    "netlimiter", "wireshark", "npcap", "winpcap",
]

# Стандартные (Microsoft) провайдеры WFP — НЕ подозрительные
WFP_STANDARD_PROVIDERS = [
    "microsoft", "windows", "tcp/ip", "ipsec", "mpssvc", "bfe",
    "wsservice", "wfp", "ikeext", "dot3svc", "eaphost",
]

# Маппинг: паттерн WFP провайдера -> имена процессов (для проверки "установлен и работает")
WFP_PROVIDER_PROCESSES: Dict[str, List[str]] = {
    "kaspersky": ["avp.exe", "avpui.exe", "kavfs.exe"],
    "eset": ["ekrn.exe", "egui.exe"],
    "avast": ["avastsvc.exe", "avastui.exe"],
    "avg": ["avgsvc.exe", "avgui.exe"],
    "norton": ["ns.exe", "nsservice.exe"],
    "bitdefender": ["bdagent.exe", "vsserv.exe", "bdservicehost.exe"],
    "dr.web": ["dwservice.exe", "dwengine.exe"],
    "comodo": ["cis.exe", "cmdagent.exe"],
    "glasswire": ["glasswire.exe", "glasswireservice.exe"],
    "netlimiter": ["netlimiter.exe", "nlsvc.exe"],
    "wireshark": ["wireshark.exe"],
    "npcap": ["npcap.exe"],
}

# subprocess creation flags
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0


def _is_private_ip(ip: str) -> bool:
    """Проверка: IP принадлежит private/link-local диапазону (RFC 1918 и др.)"""
    try:
        parts = ip.split('.')
        if len(parts) != 4:
            return ip.startswith("fe80:") or ip.startswith("fd")  # IPv6 link-local/ULA
        a, b = int(parts[0]), int(parts[1])
        # 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16
        return (a == 10 or (a == 172 and 16 <= b <= 31)
                or (a == 192 and b == 168) or (a == 169 and b == 254))
    except (ValueError, IndexError):
        return False


def _get_running_processes() -> Set[str]:
    """Получение списка имён запущенных процессов (lowercase)."""
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, timeout=10,
            creationflags=_CREATE_NO_WINDOW
        )
        output = _decode_console(result.stdout or b"")
        names: Set[str] = set()
        for line in output.splitlines():
            line = line.strip()
            if line.startswith('"'):
                # CSV: "process.exe","PID",...
                end = line.find('"', 1)
                if end > 1:
                    names.add(line[1:end].lower())
        return names
    except Exception:
        return set()


def _decode_console(raw: bytes) -> str:
    """Декодирование вывода консольных утилит (netsh и т.д.).

    На современных Windows с 'Use Unicode UTF-8' (или Win11 defaults)
    netsh выводит UTF-8. На классических русских Windows — cp866 (OEM).
    UTF-8 strict пробуется первым: если байты не валидный UTF-8 (а они
    точно не будут при cp866-кириллице), то fallback на cp866.
    """
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return raw.decode("cp866", errors="replace")

# Полный путь к PowerShell (на некоторых ПК 'powershell' не в PATH из QGIS)
_powershell_exe = ""
if sys.platform == 'win32':
    _ps_candidate = os.path.join(
        os.environ.get("SystemRoot", r"C:\Windows"),
        "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
    )
    if os.path.isfile(_ps_candidate):
        _powershell_exe = _ps_candidate
    else:
        # Fallback: надеемся что powershell в PATH
        _powershell_exe = "powershell"


# ---------------------------------------------------------------------------
# NetworkDoctor
# ---------------------------------------------------------------------------

class NetworkDoctor:
    """Диагностика и починка сетевых проблем Windows"""

    MODULE_ID = "Fsm_4_1_10"

    def __init__(self, progress_callback: Optional[Callable[[str], None]] = None):
        self._progress = progress_callback

    def _emit(self, msg: str) -> None:
        if self._progress:
            self._progress(msg)

    # ===================================================================
    # DIAGNOSTICS
    # ===================================================================

    @staticmethod
    def run_diagnostics() -> Dict[str, DiagResult]:
        """
        Запуск полной диагностики сети.

        Returns:
            dict: ключ = id проверки, значение = DiagResult
        """
        if sys.platform != 'win32':
            return {"unsupported": DiagResult(
                name="ОС", status="skip",
                message="Сетевая диагностика доступна только для Windows"
            )}

        doctor = NetworkDoctor()
        results: Dict[str, DiagResult] = {}

        checks = [
            ("proxy_wininet", doctor.check_proxy),
            ("proxy_winhttp", doctor.check_winhttp_proxy),
            ("dns", doctor.check_dns),
            ("hosts_file", doctor.check_hosts_file),
            ("env_proxy", doctor.check_env_proxy),
            ("certs", doctor.check_suspicious_certs),
            ("drivers", doctor.check_orphaned_drivers),
            ("adapters", doctor.check_orphaned_adapters),
            ("winsock", doctor.check_winsock_catalog),
            ("wfp_filters", doctor.check_wfp_filters),
            ("ssl_cache", doctor.check_ssl_cache),
            ("connectivity", doctor.test_connectivity),
        ]

        for check_id, check_fn in checks:
            try:
                results[check_id] = check_fn()
            except Exception as e:
                log_error(f"{NetworkDoctor.MODULE_ID}: Ошибка проверки {check_id}: {e}")
                results[check_id] = DiagResult(
                    name=check_id, status="error",
                    message=f"Ошибка: {e}"
                )

        # Логирование итога
        issues = [r for r in results.values() if r.status == "issue"]
        log_info(
            f"{NetworkDoctor.MODULE_ID}: Диагностика завершена. "
            f"Проверок: {len(results)}, проблем: {len(issues)}"
        )

        return results

    # --- Individual checks ------------------------------------------------

    def check_proxy(self) -> DiagResult:
        """Проверка WinINET прокси (реестр HKCU)"""
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings",
                0, winreg.KEY_READ
            ) as key:
                proxy_enable = _reg_value(key, "ProxyEnable", 0)
                proxy_server = _reg_value(key, "ProxyServer", "")
                auto_config = _reg_value(key, "AutoConfigURL", "")

            if proxy_enable:
                return DiagResult(
                    name="Прокси WinINET",
                    status="issue",
                    message=f"Системный прокси включён: {proxy_server or 'PAC: ' + auto_config}",
                    details={"proxy_enable": proxy_enable, "proxy_server": proxy_server,
                             "auto_config_url": auto_config},
                    fixable=True, needs_admin=False
                )

            return DiagResult(
                name="Прокси WinINET", status="ok",
                message="Прокси отключён"
            )

        except OSError as e:
            return DiagResult(
                name="Прокси WinINET", status="error",
                message=f"Не удалось прочитать реестр: {e}"
            )

    def check_winhttp_proxy(self) -> DiagResult:
        """Проверка WinHTTP прокси (системный уровень)"""
        try:
            result = subprocess.run(
                ["netsh", "winhttp", "show", "proxy"],
                capture_output=True, timeout=15,
                creationflags=_CREATE_NO_WINDOW
            )
            output = _decode_console(result.stdout or b"")

            log_info(f"{self.MODULE_ID}: WinHTTP raw output: {output.strip()!r}")

            if "Direct access" in output or "Прямой доступ" in output:
                return DiagResult(
                    name="Прокси WinHTTP", status="ok",
                    message="WinHTTP: прямое соединение"
                )

            # Если вывод пустой — не можем определить, не считаем проблемой
            if not output.strip():
                return DiagResult(
                    name="Прокси WinHTTP", status="ok",
                    message="WinHTTP: не удалось получить данные (вероятно прямое соединение)"
                )

            # Извлекаем адрес прокси и bypass-list из вывода netsh
            proxy_server = ""
            bypass_list = ""
            for line in output.splitlines():
                line_s = line.strip()
                if not line_s or ":" not in line_s:
                    continue
                # Разбиваем по " : " (стандартный формат netsh)
                if " : " in line_s:
                    key_part, _, val_part = line_s.partition(" : ")
                else:
                    key_part, _, val_part = line_s.partition(":")
                key_lower = key_part.strip().lower()
                val_clean = val_part.strip()
                if any(k in key_lower for k in (
                    "proxy server", "прокси-сервер", "прокси сервер", "прокси"
                )):
                    proxy_server = val_clean
                elif any(k in key_lower for k in (
                    "bypass", "обход", "исключен"
                )):
                    bypass_list = val_clean

            detail_msg = f"WinHTTP прокси: {proxy_server}" if proxy_server else "WinHTTP прокси настроен"
            if bypass_list:
                detail_msg += f" | bypass: {bypass_list}"
            # Если парсинг не нашел адрес — показываем сырой вывод
            if not proxy_server:
                raw_lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
                if raw_lines:
                    detail_msg += f" [{'; '.join(raw_lines[:3])}]"

            return DiagResult(
                name="Прокси WinHTTP",
                status="issue",
                message=detail_msg,
                details={"output": output.strip(), "proxy_server": proxy_server,
                         "bypass_list": bypass_list},
                fixable=True, needs_admin=True
            )

        except Exception as e:
            return DiagResult(
                name="Прокси WinHTTP", status="error",
                message=f"Не удалось проверить: {e}"
            )

    def check_dns(self) -> DiagResult:
        """Проверка DNS на активных адаптерах (ищем 127.0.0.1)"""
        try:
            result = _run_powershell(
                "Get-DnsClientServerAddress -AddressFamily IPv4 | "
                "Where-Object { $_.ServerAddresses -contains '127.0.0.1' } | "
                "Select-Object InterfaceAlias, @{N='DNS';E={$_.ServerAddresses -join ','}} | "
                "ConvertTo-Json -Compress"
            )

            if not result.strip() or result.strip() == "":
                return DiagResult(
                    name="DNS", status="ok",
                    message="DNS адаптеров в норме"
                )

            data = json.loads(result)
            # PowerShell возвращает объект если один результат, массив если несколько
            if isinstance(data, dict):
                data = [data]

            adapters = [f"{d.get('InterfaceAlias', '?')} ({d.get('DNS', '?')})" for d in data]
            return DiagResult(
                name="DNS",
                status="issue",
                message=f"DNS = 127.0.0.1 на адаптерах: {', '.join(adapters)}",
                details={"adapters": data},
                fixable=True, needs_admin=True
            )

        except Exception as e:
            return DiagResult(
                name="DNS", status="error",
                message=f"Не удалось проверить DNS: {e}"
            )

    def check_suspicious_certs(self) -> DiagResult:
        """Проверка подозрительных корневых сертификатов (от VPN/прокси/антивирусов).

        Различает:
        - MITM-инструменты (Fiddler, Burp и т.д.) — всегда подозрительны
        - Антивирусы (Kaspersky, ESET и т.д.) — подозрительны только если ПО не запущено
        """
        try:
            result = _run_powershell(
                "Get-ChildItem Cert:\\LocalMachine\\Root, Cert:\\CurrentUser\\Root "
                "-ErrorAction SilentlyContinue | "
                "Select-Object PSParentPath, Subject, Issuer, Thumbprint, "
                "@{N='Expired';E={$_.NotAfter -lt (Get-Date)}} | "
                "ConvertTo-Json -Compress"
            )

            if not result.strip():
                return DiagResult(
                    name="Сертификаты", status="ok",
                    message="Подозрительных корневых сертификатов не найдено"
                )

            all_certs = json.loads(result)
            if isinstance(all_certs, dict):
                all_certs = [all_certs]

            running = _get_running_processes()

            # Классифицируем сертификаты
            suspicious: List[Dict[str, Any]] = []  # Для удаления
            active_sw: List[str] = []  # Активное ПО (информационно)

            for cert in all_certs:
                subject = (cert.get("Subject") or "").lower()
                issuer = (cert.get("Issuer") or "").lower()
                combined = subject + " " + issuer
                is_machine = "LocalMachine" in (cert.get("PSParentPath") or "")

                cert_info = {
                    "subject": cert.get("Subject", ""),
                    "thumbprint": cert.get("Thumbprint", ""),
                    "expired": cert.get("Expired", False),
                    "store": "LocalMachine" if is_machine else "CurrentUser",
                }

                # 1) MITM-инструменты — всегда подозрительны
                for pattern in ALWAYS_SUSPICIOUS_CERT_PATTERNS:
                    if pattern in combined:
                        cert_info["matched_pattern"] = pattern
                        suspicious.append(cert_info)
                        break
                else:
                    # 2) Антивирусы — проверяем запущен ли процесс
                    for av_pattern, av_processes in ANTIVIRUS_CERT_PATTERNS:
                        if av_pattern in combined:
                            sw_running = any(p in running for p in av_processes)
                            if sw_running:
                                active_sw.append(av_pattern.capitalize())
                            else:
                                cert_info["matched_pattern"] = av_pattern
                                suspicious.append(cert_info)
                            break

            # Формируем результат
            if not suspicious and not active_sw:
                return DiagResult(
                    name="Сертификаты", status="ok",
                    message="Подозрительных корневых сертификатов не найдено"
                )

            if not suspicious:
                # Только активное ПО — не проблема
                sw_names = ", ".join(sorted(set(active_sw)))
                return DiagResult(
                    name="Сертификаты", status="ok",
                    message=f"Сертификаты активного ПО ({sw_names}) - норма"
                )

            # Есть осиротевшие/MITM сертификаты
            names = [s["subject"][:60] for s in suspicious[:5]]
            has_machine = any(s["store"] == "LocalMachine" for s in suspicious)
            msg = (f"Найдено {len(suspicious)} подозрительных сертификатов: "
                   f"{'; '.join(names)}")
            if active_sw:
                sw_names = ", ".join(sorted(set(active_sw)))
                msg += f" (+ {sw_names} активны, норма)"
            return DiagResult(
                name="Сертификаты",
                status="issue",
                message=msg,
                details={"certificates": suspicious},
                fixable=True,
                needs_admin=has_machine
            )

        except Exception as e:
            return DiagResult(
                name="Сертификаты", status="error",
                message=f"Не удалось проверить сертификаты: {e}"
            )

    def check_orphaned_drivers(self) -> DiagResult:
        """Проверка осиротевших драйверов (AdGuard WFP и др.)"""
        drivers_dir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                   "System32", "drivers")
        found_files: List[str] = []
        for fname in SUSPICIOUS_DRIVER_FILES:
            fpath = os.path.join(drivers_dir, fname)
            if os.path.exists(fpath):
                found_files.append(fname)

        # Проверяем сервисы
        found_services: List[str] = []
        try:
            result = _run_powershell(
                "Get-Service | Where-Object { "
                + " -or ".join(f"$_.Name -eq '{s}'" for s in SUSPICIOUS_SERVICE_NAMES)
                + " } | Select-Object Name, Status, DisplayName | ConvertTo-Json -Compress"
            )
            if result.strip():
                services = json.loads(result)
                if isinstance(services, dict):
                    services = [services]
                found_services = [s.get("Name", "?") for s in services]
        except Exception:
            pass

        if not found_files and not found_services:
            return DiagResult(
                name="Драйверы", status="ok",
                message="Осиротевших сетевых драйверов не найдено"
            )

        parts = []
        if found_files:
            parts.append(f"файлы: {', '.join(found_files)}")
        if found_services:
            parts.append(f"сервисы: {', '.join(found_services)}")

        return DiagResult(
            name="Драйверы",
            status="issue",
            message=f"Найдены осиротевшие драйверы ({'; '.join(parts)})",
            details={"files": found_files, "services": found_services},
            fixable=True, needs_admin=True
        )

    def check_orphaned_adapters(self) -> DiagResult:
        """Проверка осиротевших сетевых адаптеров (WinTun, TAP, AdGuard).

        Адаптеры в статусе Up/Connected пропускаются — это активные VPN-туннели.
        Только Disconnected/Not Present адаптеры считаются осиротевшими.
        """
        try:
            filter_parts = " -or ".join(
                f"$_.InterfaceDescription -like '*{p}*'"
                for p in SUSPICIOUS_ADAPTER_PATTERNS
            )
            result = _run_powershell(
                f"Get-NetAdapter -ErrorAction SilentlyContinue | "
                f"Where-Object {{ {filter_parts} }} | "
                f"Select-Object Name, InterfaceDescription, Status | "
                f"ConvertTo-Json -Compress"
            )

            if not result.strip():
                return DiagResult(
                    name="Сетевые адаптеры", status="ok",
                    message="Осиротевших адаптеров не найдено"
                )

            all_adapters = json.loads(result)
            if isinstance(all_adapters, dict):
                all_adapters = [all_adapters]

            # Только адаптеры НЕ в активном состоянии считаются осиротевшими.
            # Up = активный VPN-туннель, не трогаем.
            active_statuses = {"Up", "Connected"}
            orphaned = [a for a in all_adapters
                        if a.get("Status", "") not in active_statuses]
            active_vpn = [a for a in all_adapters
                          if a.get("Status", "") in active_statuses]

            if active_vpn:
                vpn_names = [a.get("Name", "?") for a in active_vpn]
                log_info(
                    f"{self.MODULE_ID}: Пропущены активные VPN-адаптеры: "
                    f"{', '.join(vpn_names)}"
                )

            if not orphaned:
                msg = "Осиротевших адаптеров не найдено"
                if active_vpn:
                    msg += f" (активных VPN: {len(active_vpn)}, пропущены)"
                return DiagResult(
                    name="Сетевые адаптеры", status="ok",
                    message=msg
                )

            names = [f"{a.get('Name', '?')} ({a.get('InterfaceDescription', '?')}, "
                     f"{a.get('Status', '?')})"
                     for a in orphaned]
            return DiagResult(
                name="Сетевые адаптеры",
                status="issue",
                message=f"Найдено {len(orphaned)} осиротевших адаптеров: {', '.join(names)}",
                details={"adapters": orphaned,
                         "skipped_active": len(active_vpn)},
                fixable=True, needs_admin=True
            )

        except Exception as e:
            return DiagResult(
                name="Сетевые адаптеры", status="error",
                message=f"Не удалось проверить адаптеры: {e}"
            )

    def check_winsock_catalog(self) -> DiagResult:
        """Проверка Winsock каталога на сторонние LSP"""
        try:
            result = subprocess.run(
                ["netsh", "winsock", "show", "catalog"],
                capture_output=True, timeout=15,
                creationflags=_CREATE_NO_WINDOW
            )
            stdout = _decode_console(result.stdout or b"")
            output = stdout.lower()

            # Стандартные провайдеры Microsoft (EN + RU описания)
            standard_prefixes = [
                # English — core
                "msafd", "rsvp", "microsoft", "hyper-v", "napagent",
                "nlansp", "nlasvc", "mswsock", "tcpip", "af_unix", "pnrp",
                "wininet", "ldap", "windows",
                # English — namespace providers
                "nla ", "nla(", "nlav", "ntds", "bluetooth",
                "mdnsnsp", "rnr20",
                # Windows resource strings (@%SystemRoot%\system32\*.dll)
                "@%systemroot%",
                # Russian (русская локаль netsh)
                "поставщик",        # "Поставщик пространства имен..."
                "пространство имен", # "Пространство имен предыдущей службы..."
            ]

            # Парсим строки с описанием провайдеров
            third_party: List[str] = []
            for line in stdout.splitlines():
                line_stripped = line.strip()
                # Строки описания обычно начинаются после "Description:"
                # или "Описание:" в русской локали
                if ":" in line_stripped:
                    key, _, val = line_stripped.partition(":")
                    key_lower = key.strip().lower()
                    if key_lower in ("description", "описание"):
                        val_lower = val.strip().lower()
                        if val_lower and not any(p in val_lower for p in standard_prefixes):
                            third_party.append(val.strip())

            if not third_party:
                return DiagResult(
                    name="Winsock каталог", status="ok",
                    message="Сторонних LSP провайдеров не найдено"
                )

            unique = list(set(third_party))
            return DiagResult(
                name="Winsock каталог",
                status="issue",
                message=f"Найдено {len(unique)} сторонних провайдеров: {', '.join(unique[:5])}",
                details={"providers": unique},
                fixable=True, needs_admin=True
            )

        except Exception as e:
            return DiagResult(
                name="Winsock каталог", status="error",
                message=f"Не удалось проверить Winsock: {e}"
            )

    # Таймаут на один URL в test_connectivity.
    # Раньше был 10с последовательно (до минуты suma при 4 URL и одном timeout).
    # Теперь 5с параллельно => ограничение ~5с на всю диагностику.
    _CONNECTIVITY_URL_TIMEOUT = 5

    def test_connectivity(self) -> DiagResult:
        """Тестирование HTTPS-соединения к нескольким сайтам параллельно.

        Параллельный запуск через ThreadPoolExecutor ограничивает общее время
        диагностики одним таймаутом на URL (~5 сек), вне зависимости от того,
        сколько сайтов недоступны. Вызывается из worker-потока (не из UI).
        """
        import concurrent.futures

        results: Dict[str, Any] = {}
        success_count = 0
        # Ошибки SSL сертификатов на стороне СЕРВЕРА — не проблема ПК
        server_ssl_errors: List[str] = []

        def _probe(url: str, label: str) -> Tuple[str, Dict[str, Any]]:
            """Одиночная проверка URL. Возвращает (label, result_dict)."""
            try:
                req = Request(url, headers={"User-Agent": "QGIS-Plugin/1.0"})
                with urlopen(req, timeout=self._CONNECTIVITY_URL_TIMEOUT) as resp:
                    return label, {"status": resp.status, "ok": True, "url": url}
            except URLError as e:
                error_str = str(e.reason)
                is_server_ssl = any(p in error_str.lower() for p in (
                    "certificate has expired",
                    "certificate is not yet valid",
                    "hostname mismatch",
                ))
                if is_server_ssl:
                    return label, {
                        "error": error_str, "ok": False, "url": url,
                        "server_issue": True,
                    }
                return label, {"error": error_str, "ok": False, "url": url}
            except Exception as e:
                return label, {"error": str(e), "ok": False, "url": url}

        # max_workers=len(CONNECTIVITY_TEST_URLS) — все проверки параллельно.
        # Лимит таймаута на future — _CONNECTIVITY_URL_TIMEOUT + 2с запас на сокеты.
        overall_timeout = self._CONNECTIVITY_URL_TIMEOUT + 2
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, len(CONNECTIVITY_TEST_URLS))
        ) as executor:
            future_map = {
                executor.submit(_probe, url, label): (url, label)
                for url, label in CONNECTIVITY_TEST_URLS
            }
            for future in concurrent.futures.as_completed(
                future_map, timeout=overall_timeout * 2
            ):
                url, label = future_map[future]
                try:
                    _, result = future.result(timeout=overall_timeout)
                except concurrent.futures.TimeoutError:
                    result = {
                        "error": f"timeout > {overall_timeout}s",
                        "ok": False, "url": url,
                    }
                except Exception as e:
                    result = {"error": str(e), "ok": False, "url": url}
                results[label] = result
                if result.get("ok"):
                    success_count += 1
                elif result.get("server_issue"):
                    server_ssl_errors.append(label)

        total = len(CONNECTIVITY_TEST_URLS)
        # Сайты с серверными SSL ошибками не считаем проблемой ПК
        effective_failures = sum(
            1 for r in results.values()
            if not r.get("ok") and not r.get("server_issue")
        )

        if success_count == total:
            return DiagResult(
                name="Соединение", status="ok",
                message=f"Все {total} тестовых сайтов доступны",
                details=results
            )

        # Формируем детальное сообщение
        failed_parts: List[str] = []
        for label, r in results.items():
            if not r.get("ok"):
                err = r.get("error", "?")
                if len(err) > 150:
                    err = err[:147] + "..."
                suffix = " [проблема сервера]" if r.get("server_issue") else ""
                failed_parts.append(f"{label}: {err}{suffix}")

        if effective_failures == 0 and server_ssl_errors:
            # Все недоступные — серверные SSL ошибки, ПК в норме
            return DiagResult(
                name="Соединение", status="ok",
                message=(f"Доступно {success_count} из {total} сайтов. "
                         f"SSL ошибки сервера: {', '.join(server_ssl_errors)} "
                         f"(не проблема ПК)"),
                details=results
            )
        elif success_count > 0 or server_ssl_errors:
            return DiagResult(
                name="Соединение",
                status="issue",
                message=(f"Недоступно {effective_failures} из {total} сайтов:\n"
                         + "\n".join(f"  - {p}" for p in failed_parts)),
                details=results,
                fixable=False
            )
        else:
            return DiagResult(
                name="Соединение",
                status="issue",
                message=("Нет доступа к интернету:\n"
                         + "\n".join(f"  - {p}" for p in failed_parts)),
                details=results,
                fixable=False
            )

    # --- New checks: hosts, env_proxy, ssl_cache, wfp_filters ----------

    def check_hosts_file(self) -> DiagResult:
        """Проверка файла hosts на подозрительные записи (VPN/антивирус/malware)"""
        try:
            hosts_path = os.path.join(
                os.environ.get("SystemRoot", r"C:\Windows"),
                "System32", "drivers", "etc", "hosts"
            )

            if not os.path.exists(hosts_path):
                return DiagResult(
                    name="Файл hosts", status="ok",
                    message="Файл hosts не найден"
                )

            # Чтение с cascade encoding
            content = ""
            encoding_used = ""
            for enc in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
                try:
                    with open(hosts_path, 'r', encoding=enc) as f:
                        content = f.read()
                    encoding_used = enc
                    break
                except (UnicodeDecodeError, ValueError):
                    continue

            if not content.strip():
                return DiagResult(
                    name="Файл hosts", status="ok",
                    message="Файл hosts пуст"
                )

            suspicious: List[Dict[str, Any]] = []
            total_custom = 0

            for line_no, line in enumerate(content.splitlines(), 1):
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    continue

                parts = stripped.split()
                if len(parts) < 2:
                    continue

                ip = parts[0]
                # Пропускаем inline-комментарии
                hostnames = [p for p in parts[1:] if not p.startswith('#')]

                for hostname in hostnames:
                    hostname_lower = hostname.lower()

                    # Стандартные записи — всегда ОК
                    if hostname_lower in HOSTS_STANDARD_ENTRIES:
                        continue

                    # Известное ПО (Docker, WSL, Kubernetes) — не подозрительно
                    if any(hostname_lower.endswith(s)
                           for s in HOSTS_KNOWN_SOFTWARE_SUFFIXES):
                        continue

                    # Осознанные блокировки (лицензионные проверки ПО)
                    if (ip in HOSTS_BLOCKING_IPS
                            and any(p in hostname_lower
                                    for p in HOSTS_USER_BLOCK_PATTERNS)):
                        continue

                    total_custom += 1

                    # Redirect на внешний IP (не blocking, не private)
                    if ip not in HOSTS_BLOCKING_IPS:
                        # Private/link-local IP — не перехват трафика
                        if _is_private_ip(ip):
                            continue
                        suspicious.append({
                            "line": line_no,
                            "ip": ip,
                            "hostname": hostname_lower,
                            "type": "redirect",
                            "content": stripped[:100],
                        })
                        continue

                    # Блокировка реальных доменов через 127.0.0.1/0.0.0.0
                    # Считаем подозрительным только если это НЕ массовый ad-block
                    # (>50 записей = ad-blocker, нормально)
                    suspicious.append({
                        "line": line_no,
                        "ip": ip,
                        "hostname": hostname_lower,
                        "type": "block",
                        "content": stripped[:100],
                    })

            if not suspicious:
                msg = "Подозрительных записей не найдено"
                if total_custom > 0:
                    msg += f" ({total_custom} пользовательских записей)"
                return DiagResult(
                    name="Файл hosts", status="ok", message=msg
                )

            # Если >50 блокирующих записей — вероятно ad-blocker, не считаем проблемой
            block_entries = [s for s in suspicious if s["type"] == "block"]
            redirect_entries = [s for s in suspicious if s["type"] == "redirect"]

            if len(block_entries) > 50 and not redirect_entries:
                return DiagResult(
                    name="Файл hosts", status="ok",
                    message=f"Ad-blocker ({len(block_entries)} записей), не проблема"
                )

            # Есть redirect или умеренное кол-во блокировок
            report = suspicious[:10]  # Показываем первые 10
            names = [f"{s['ip']} {s['hostname']}" for s in report[:5]]
            return DiagResult(
                name="Файл hosts",
                status="issue",
                message=(f"Найдено {len(suspicious)} подозрительных записей: "
                         f"{'; '.join(names)}"),
                details={
                    "entries": suspicious,
                    "file_path": hosts_path,
                    "encoding_used": encoding_used,
                    "redirect_count": len(redirect_entries),
                    "block_count": len(block_entries),
                },
                fixable=True, needs_admin=True
            )

        except PermissionError:
            return DiagResult(
                name="Файл hosts", status="error",
                message="Нет доступа к файлу hosts"
            )
        except Exception as e:
            return DiagResult(
                name="Файл hosts", status="error",
                message=f"Не удалось проверить hosts: {e}"
            )

    def check_env_proxy(self) -> DiagResult:
        """Проверка переменных окружения HTTP_PROXY/HTTPS_PROXY (процесс + реестр)"""
        try:
            process_vars: Dict[str, str] = {}
            user_registry_vars: Dict[str, str] = {}
            system_registry_vars: Dict[str, str] = {}

            # 1. Текущий процесс
            for var_name in PROXY_ENV_VARS:
                val = os.environ.get(var_name, "")
                if val:
                    process_vars[var_name] = val

            # 2. Реестр HKCU\Environment (persistent user vars)
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, "Environment",
                    0, winreg.KEY_READ
                ) as key:
                    for var_name in PROXY_ENV_VARS:
                        val = _reg_value(key, var_name, "")
                        if val:
                            user_registry_vars[var_name] = val
            except OSError:
                pass

            # 3. Реестр HKLM (persistent system vars)
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
                    0, winreg.KEY_READ
                ) as key:
                    for var_name in PROXY_ENV_VARS:
                        val = _reg_value(key, var_name, "")
                        if val:
                            system_registry_vars[var_name] = val
            except OSError:
                pass

            all_found = {**process_vars, **user_registry_vars, **system_registry_vars}
            if not all_found:
                return DiagResult(
                    name="Переменные прокси", status="ok",
                    message="Переменные окружения прокси не установлены"
                )

            parts = []
            if process_vars:
                parts.append(f"процесс: {', '.join(process_vars.keys())}")
            if user_registry_vars:
                parts.append(f"HKCU: {', '.join(user_registry_vars.keys())}")
            if system_registry_vars:
                parts.append(f"HKLM: {', '.join(system_registry_vars.keys())}")

            has_system = bool(system_registry_vars)
            return DiagResult(
                name="Переменные прокси",
                status="issue",
                message=f"Обнаружены прокси-переменные ({'; '.join(parts)})",
                details={
                    "process": process_vars,
                    "user_registry": user_registry_vars,
                    "system_registry": system_registry_vars,
                },
                fixable=True,
                needs_admin=has_system
            )

        except Exception as e:
            return DiagResult(
                name="Переменные прокси", status="error",
                message=f"Не удалось проверить переменные: {e}"
            )

    def check_ssl_cache(self) -> DiagResult:
        """Проверка SSL кэша Windows (handshake test)"""
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection(("google.com", 443), timeout=5) as sock:
                with ctx.wrap_socket(sock, server_hostname="google.com"):
                    pass  # handshake OK
            return DiagResult(
                name="SSL кэш", status="ok",
                message="SSL handshake успешен, кэш в норме"
            )
        except ssl.SSLError as e:
            return DiagResult(
                name="SSL кэш",
                status="issue",
                message=f"SSL ошибка: {e}. Очистка кэша может помочь",
                details={"ssl_error": str(e)},
                fixable=True, needs_admin=False
            )
        except (socket.timeout, socket.gaierror, OSError):
            # Сеть недоступна — не проблема SSL кэша
            return DiagResult(
                name="SSL кэш", status="ok",
                message="Сеть недоступна (не проблема SSL кэша)"
            )
        except Exception as e:
            return DiagResult(
                name="SSL кэш", status="error",
                message=f"Не удалось проверить SSL: {e}"
            )

    def check_wfp_filters(self) -> DiagResult:
        """Проверка WFP фильтров на сторонних провайдеров (kernel-level)"""
        temp_dir = None
        try:
            temp_dir = tempfile.mkdtemp(prefix="daman_wfp_")
            xml_path = os.path.join(temp_dir, "wfp_filters.xml")

            # netsh wfp show filters не требует admin для чтения
            result = subprocess.run(
                ["netsh", "wfp", "show", "filters", f"file={xml_path}"],
                capture_output=True, timeout=30,
                creationflags=_CREATE_NO_WINDOW
            )

            if not os.path.exists(xml_path):
                # netsh не создал файл — вероятно нет прав
                output = _decode_console(
                    result.stderr or result.stdout or b""
                ).strip()[:200]
                if "access" in output.lower() or "доступ" in output.lower():
                    return DiagResult(
                        name="WFP фильтры", status="error",
                        message="Требуются права администратора для проверки WFP"
                    )
                return DiagResult(
                    name="WFP фильтры", status="error",
                    message=f"netsh wfp не создал файл: {output}"
                )

            # Парсим XML через iterparse (файл может быть большим)
            third_party_providers: Dict[str, int] = {}
            suspicious_providers: List[str] = []

            try:
                for event, elem in ET.iterparse(xml_path, events=('end',)):
                    if elem.tag == 'displayData':
                        name_elem = elem.find('name')
                        if name_elem is not None and name_elem.text:
                            provider_name = name_elem.text.strip()
                            provider_lower = provider_name.lower()

                            # Пропускаем стандартных Microsoft провайдеров
                            if any(std in provider_lower
                                   for std in WFP_STANDARD_PROVIDERS):
                                elem.clear()
                                continue

                            # Считаем third-party
                            if provider_name not in third_party_providers:
                                third_party_providers[provider_name] = 0
                            third_party_providers[provider_name] += 1

                            # Проверяем подозрительных
                            for pattern in WFP_SUSPICIOUS_PROVIDERS:
                                if pattern in provider_lower:
                                    if provider_name not in suspicious_providers:
                                        suspicious_providers.append(provider_name)
                                    break

                        elem.clear()
            except ET.ParseError as e:
                log_warning(f"{self.MODULE_ID}: Ошибка парсинга WFP XML: {e}")

            if not suspicious_providers:
                msg = "Осиротевших WFP фильтров не найдено"
                if third_party_providers:
                    tp_names = list(third_party_providers.keys())[:3]
                    msg += f" (сторонние: {', '.join(tp_names)})"
                return DiagResult(
                    name="WFP фильтры", status="ok", message=msg,
                    details={"third_party": third_party_providers}
                )

            # Разделяем: установленный работающий софт vs осиротевшие фильтры
            running = _get_running_processes()
            orphaned: List[str] = []
            active: List[str] = []

            for provider_name in suspicious_providers:
                provider_lower = provider_name.lower()
                is_running = False
                for pattern, processes in WFP_PROVIDER_PROCESSES.items():
                    if pattern in provider_lower:
                        if any(p in running for p in processes):
                            is_running = True
                        break
                if is_running:
                    active.append(provider_name)
                else:
                    orphaned.append(provider_name)

            if not orphaned:
                # Все найденные провайдеры — от работающего ПО
                names = ', '.join(active[:3])
                return DiagResult(
                    name="WFP фильтры", status="ok",
                    message=f"WFP фильтры от активного ПО: {names}",
                    details={
                        "active_software": active,
                        "third_party": third_party_providers,
                    }
                )

            return DiagResult(
                name="WFP фильтры",
                status="issue",
                message=(f"Найдено {len(orphaned)} осиротевших WFP "
                         f"провайдеров: {', '.join(orphaned[:5])}"),
                details={
                    "orphaned": orphaned,
                    "active_software": active,
                    "third_party": third_party_providers,
                },
                fixable=False,  # Слишком опасно удалять WFP фильтры
                needs_admin=True
            )

        except subprocess.TimeoutExpired:
            return DiagResult(
                name="WFP фильтры", status="error",
                message="Таймаут при проверке WFP фильтров (30 сек)"
            )
        except Exception as e:
            return DiagResult(
                name="WFP фильтры", status="error",
                message=f"Не удалось проверить WFP: {e}"
            )
        finally:
            if temp_dir:
                try:
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass

    # ===================================================================
    # FIXES
    # ===================================================================

    def fix_issues(self, issues: Dict[str, DiagResult],
                   stage: int = 1) -> List[FixResult]:
        """
        Починка найденных проблем.

        Args:
            issues: Результаты диагностики (только записи со status='issue')
            stage: 1 = user-level, 2 = + admin, 3 = + admin + reboot-операции

        Returns:
            Список результатов починки
        """
        fix_results: List[FixResult] = []

        # --- Stage 1: user-level, без перезагрузки ---
        if "proxy_wininet" in issues:
            fix_results.append(self._fix_proxy_wininet())

        fix_results.append(self._fix_dns_cache())
        fix_results.append(self._fix_ssl_cache())

        if "env_proxy" in issues:
            fix_results.append(self._fix_env_proxy_user(issues["env_proxy"]))

        if "certs" in issues:
            user_certs = self._get_user_store_certs(issues["certs"])
            if user_certs:
                fix_results.append(self._fix_certs_user(user_certs))

        if stage < 2:
            return fix_results

        # --- Stage 2: admin, без перезагрузки ---
        admin_commands: List[str] = []

        if "proxy_winhttp" in issues:
            admin_commands.append("netsh winhttp reset proxy")

        if "dns" in issues:
            dns_data = issues["dns"].details.get("adapters", [])
            for adapter in dns_data:
                alias = adapter.get("InterfaceAlias", "")
                if alias:
                    admin_commands.append(
                        f"Set-DnsClientServerAddress -InterfaceAlias '{alias}' "
                        f"-ResetServerAddresses"
                    )

        if "certs" in issues:
            machine_certs = self._get_machine_store_certs(issues["certs"])
            for cert in machine_certs:
                thumb = cert.get("thumbprint", "")
                if thumb:
                    admin_commands.append(
                        f"Get-ChildItem Cert:\\LocalMachine\\Root\\{thumb} "
                        f"-ErrorAction SilentlyContinue | Remove-Item -Force"
                    )

        if "hosts_file" in issues:
            admin_commands.extend(
                self._build_hosts_fix_commands(issues["hosts_file"])
            )

        if "env_proxy" in issues:
            sys_vars = issues["env_proxy"].details.get("system_registry", {})
            for var_name in sys_vars:
                admin_commands.append(
                    f"[Environment]::SetEnvironmentVariable("
                    f"'{_ps_escape(var_name)}', $null, 'Machine')"
                )
            if sys_vars:
                # Broadcast WM_SETTINGCHANGE
                admin_commands.append(
                    "Add-Type -Namespace Win32 -Name NativeMethods -MemberDefinition '"
                    "[DllImport(\"user32.dll\", SetLastError = true, CharSet = CharSet.Auto)]"
                    "public static extern IntPtr SendMessageTimeout("
                    "IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam, "
                    "uint fuFlags, uint uTimeout, out UIntPtr lpdwResult);'; "
                    "$result = [UIntPtr]::Zero; "
                    "[Win32.NativeMethods]::SendMessageTimeout("
                    "[IntPtr]0xFFFF, 0x001A, [UIntPtr]::Zero, 'Environment', "
                    "0x0002, 5000, [ref]$result) | Out-Null"
                )

        if admin_commands:
            ok, msg = self._run_elevated_powershell(admin_commands)
            fix_results.append(FixResult(
                name="Администраторские исправления (Stage 2)",
                success=ok, message=msg
            ))

        if stage < 3:
            return fix_results

        # --- Stage 3: admin + reboot ---
        heavy_commands: List[str] = []

        if "drivers" in issues:
            driver_details = issues["drivers"].details
            for svc in driver_details.get("services", []):
                heavy_commands.append(f"sc.exe stop {svc} 2>$null")
                heavy_commands.append(f"sc.exe delete {svc}")
            drivers_dir = os.path.join(
                os.environ.get("SystemRoot", r"C:\Windows"),
                "System32", "drivers"
            )
            for fname in driver_details.get("files", []):
                fpath = os.path.join(drivers_dir, fname).replace("\\", "\\\\")
                heavy_commands.append(
                    f"Remove-Item '{fpath}' -Force -ErrorAction SilentlyContinue"
                )

        if "adapters" in issues:
            # Удаляем только адаптеры которые были найдены диагностикой
            # (уже отфильтрованы — только Disconnected/Not Present, без активных VPN)
            orphaned_adapters = issues["adapters"].details.get("adapters", [])
            for adapter in orphaned_adapters:
                adapter_name = adapter.get("Name", "")
                if adapter_name:
                    heavy_commands.append(
                        f"Get-NetAdapter -Name '{_ps_escape(adapter_name)}' "
                        f"-ErrorAction SilentlyContinue | "
                        f"Where-Object {{ $_.Status -ne 'Up' }} | "
                        f"ForEach-Object {{ "
                        f"Get-PnpDevice -InstanceId $_.PnPDeviceID "
                        f"-ErrorAction SilentlyContinue | "
                        f"ForEach-Object {{ & pnputil /remove-device $_.InstanceId 2>$null }} "
                        f"}}"
                    )

        if "winsock" in issues:
            heavy_commands.append("netsh winsock reset")
            heavy_commands.append("netsh int ipv4 reset")
            heavy_commands.append("netsh int ipv6 reset")

        if heavy_commands:
            ok, msg = self._run_elevated_powershell(heavy_commands)
            needs_reboot = "winsock" in issues or "drivers" in issues
            fix_results.append(FixResult(
                name="Глубокая починка (Stage 3)",
                success=ok, message=msg,
                needs_reboot=needs_reboot
            ))

        return fix_results

    # --- Individual fix helpers -------------------------------------------

    def _fix_proxy_wininet(self) -> FixResult:
        """Сброс WinINET прокси (HKCU, без админа)"""
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings",
                0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
                try:
                    winreg.DeleteValue(key, "ProxyServer")
                except FileNotFoundError:
                    pass
                try:
                    winreg.DeleteValue(key, "AutoConfigURL")
                except FileNotFoundError:
                    pass

            self._emit("OK Прокси WinINET отключён")
            log_info(f"{self.MODULE_ID}: Прокси WinINET сброшен")
            return FixResult(name="Прокси WinINET", success=True,
                             message="Прокси отключён")

        except OSError as e:
            msg = f"Не удалось сбросить прокси: {e}"
            log_error(f"{self.MODULE_ID}: {msg}")
            return FixResult(name="Прокси WinINET", success=False, message=msg)

    def _fix_dns_cache(self) -> FixResult:
        """Очистка DNS кэша"""
        try:
            _run_powershell("Clear-DnsClientCache")
            self._emit("OK DNS кэш очищен")
            log_info(f"{self.MODULE_ID}: DNS кэш очищен")
            return FixResult(name="DNS кэш", success=True,
                             message="DNS кэш очищен")
        except Exception as e:
            msg = f"Не удалось очистить DNS кэш: {e}"
            log_error(f"{self.MODULE_ID}: {msg}")
            return FixResult(name="DNS кэш", success=False, message=msg)

    def _fix_certs_user(self, certs: List[Dict[str, Any]]) -> FixResult:
        """Удаление подозрительных сертификатов из CurrentUser store"""
        removed = 0
        errors_list: List[str] = []

        for cert in certs:
            thumb = cert.get("thumbprint", "")
            subject = cert.get("subject", "?")
            if not thumb:
                continue
            try:
                _run_powershell(
                    f"Get-ChildItem Cert:\\CurrentUser\\Root\\{thumb} "
                    f"-ErrorAction SilentlyContinue | Remove-Item -Force"
                )
                removed += 1
                self._emit(f"OK Удалён сертификат (user): {subject[:50]}")
            except Exception as e:
                errors_list.append(f"{subject[:30]}: {e}")

        if errors_list:
            return FixResult(
                name="Сертификаты (user)",
                success=removed > 0,
                message=f"Удалено: {removed}, ошибок: {len(errors_list)}"
            )

        return FixResult(
            name="Сертификаты (user)", success=True,
            message=f"Удалено {removed} сертификатов"
        )

    def _fix_ssl_cache(self) -> FixResult:
        """Очистка SSL кэша Windows (certutil)"""
        try:
            certutil_exe = os.path.join(
                os.environ.get("SystemRoot", r"C:\Windows"),
                "System32", "certutil.exe"
            )
            if not os.path.isfile(certutil_exe):
                certutil_exe = "certutil"

            subprocess.run(
                [certutil_exe, "-urlcache", "*", "delete"],
                capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=15,
                creationflags=_CREATE_NO_WINDOW
            )
            self._emit("OK SSL кэш очищен (certutil)")
            log_info(f"{self.MODULE_ID}: SSL URL cache очищен")
            return FixResult(name="SSL кэш", success=True,
                             message="SSL кэш очищен")
        except Exception as e:
            msg = f"Не удалось очистить SSL кэш: {e}"
            log_warning(f"{self.MODULE_ID}: {msg}")
            return FixResult(name="SSL кэш", success=False, message=msg)

    def _fix_env_proxy_user(self, diag: DiagResult) -> FixResult:
        """Удаление прокси-переменных из текущего процесса и реестра HKCU"""
        removed: List[str] = []
        errors_list: List[str] = []

        # 1. Process-level
        for var_name in diag.details.get("process", {}):
            try:
                os.environ.pop(var_name, None)
                removed.append(f"env:{var_name}")
            except Exception as e:
                errors_list.append(f"env:{var_name}: {e}")

        # 2. User registry (HKCU\Environment)
        for var_name in diag.details.get("user_registry", {}):
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, "Environment",
                    0, winreg.KEY_SET_VALUE
                ) as key:
                    winreg.DeleteValue(key, var_name)
                removed.append(f"HKCU:{var_name}")
            except FileNotFoundError:
                pass  # Уже удалено
            except OSError as e:
                errors_list.append(f"HKCU:{var_name}: {e}")

        if errors_list:
            msg = f"Удалено: {len(removed)}, ошибок: {len(errors_list)}"
            log_warning(f"{self.MODULE_ID}: env_proxy fix: {msg}")
            return FixResult(name="Прокси переменные",
                             success=len(removed) > 0, message=msg)

        self._emit(f"OK Удалено {len(removed)} прокси-переменных")
        log_info(
            f"{self.MODULE_ID}: Удалено {len(removed)} "
            f"прокси-переменных: {', '.join(removed)}"
        )
        return FixResult(name="Прокси переменные", success=True,
                         message=f"Удалено {len(removed)} переменных")

    def _build_hosts_fix_commands(self, diag: DiagResult) -> List[str]:
        """Генерация PowerShell команд для очистки hosts файла"""
        hosts_path = diag.details.get("file_path", "")
        if not hosts_path:
            return []

        entries = diag.details.get("entries", [])
        if not entries:
            return []

        # Собираем номера строк для удаления
        lines_to_remove = {e["line"] for e in entries}
        lines_csv = ",".join(str(n) for n in sorted(lines_to_remove))
        ps_path = _ps_escape(hosts_path)

        commands = [
            # Backup
            f"Copy-Item -Path '{ps_path}' "
            f"-Destination '{ps_path}.bak.daman' -Force",
            # Фильтрация: читаем все строки, удаляем по номерам
            f"$removeLines = @({lines_csv}); "
            f"$lines = Get-Content -Path '{ps_path}' -Encoding UTF8; "
            f"$clean = @(); "
            f"for ($i = 0; $i -lt $lines.Count; $i++) {{ "
            f"if ($removeLines -notcontains ($i + 1)) {{ "
            f"$clean += $lines[$i] }} }}; "
            f"$clean | Set-Content -Path '{ps_path}' -Encoding UTF8 -Force",
        ]
        return commands

    # --- UAC elevation ----------------------------------------------------

    def _run_elevated_powershell(self, commands: List[str]) -> Tuple[bool, str]:
        """
        Запуск PowerShell команд с повышенными привилегиями (UAC).

        Создаёт временный .ps1 скрипт, запускает через Start-Process -Verb RunAs,
        ожидает завершения, читает результат из temp-файла.

        Returns:
            (success, message)
        """
        temp_dir = tempfile.mkdtemp(prefix="daman_netfix_")
        script_path = os.path.join(temp_dir, "fix.ps1")
        output_path = os.path.join(temp_dir, "output.json")
        lock_path = os.path.join(temp_dir, "done.lock")

        try:
            # Генерируем PS1 скрипт
            ps_lines = [
                "# Daman QGIS Network Doctor - Elevated Fix Script",
                "$ErrorActionPreference = 'Continue'",
                "$results = @()",
                "",
            ]

            for i, cmd in enumerate(commands):
                ps_lines.extend([
                    f"# Command {i + 1}",
                    "try {",
                    f"    {cmd}",
                    f"    $results += @{{ cmd='{_ps_escape(cmd[:80])}'; ok=$true; msg='OK' }}",
                    "} catch {",
                    f"    $results += @{{ cmd='{_ps_escape(cmd[:80])}'; ok=$false; msg=$_.Exception.Message }}",
                    "}",
                    "",
                ])

            ps_lines.extend([
                f"$results | ConvertTo-Json -Compress | "
                f"Out-File -FilePath '{output_path}' -Encoding utf8",
                f"'done' | Out-File -FilePath '{lock_path}' -Encoding utf8",
            ])

            with open(script_path, 'w', encoding='utf-8-sig') as f:
                f.write("\n".join(ps_lines))

            self._emit("Запрос повышения привилегий (UAC)...")
            log_info(f"{self.MODULE_ID}: Запуск elevated PS скрипта ({len(commands)} команд)")

            # Запускаем с elevation
            launcher_cmd = (
                f"Start-Process '{_powershell_exe}' -Verb RunAs -Wait "
                f"-ArgumentList '-NoProfile -ExecutionPolicy Bypass "
                f"-File \"{script_path}\"'"
            )

            subprocess.run(
                [_powershell_exe, "-NoProfile", "-Command", launcher_cmd],
                capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=120,
                creationflags=_CREATE_NO_WINDOW
            )

            # Ждём lock-файл (макс 30 сек)
            for _ in range(60):
                if os.path.exists(lock_path):
                    break
                time.sleep(0.5)

            if not os.path.exists(lock_path):
                # Пользователь отменил UAC или скрипт завис
                msg = "UAC отменён пользователем или скрипт не завершился"
                log_warning(f"{self.MODULE_ID}: {msg}")
                return False, msg

            # Читаем результат
            if os.path.exists(output_path):
                with open(output_path, 'r', encoding='utf-8-sig') as f:
                    output_data = json.loads(f.read())

                if isinstance(output_data, dict):
                    output_data = [output_data]

                success_count = sum(1 for r in output_data if r.get("ok"))
                total = len(output_data)
                errors = [r for r in output_data if not r.get("ok")]

                if errors:
                    err_msgs = [f"{r.get('cmd', '?')}: {r.get('msg', '?')}" for r in errors[:3]]
                    msg = (f"Выполнено {success_count}/{total} команд. "
                           f"Ошибки: {'; '.join(err_msgs)}")
                else:
                    msg = f"Все {total} команд выполнены успешно"

                log_info(f"{self.MODULE_ID}: Elevated fix: {msg}")
                return success_count == total, msg

            return False, "Файл результатов не найден"

        except subprocess.TimeoutExpired:
            msg = "Превышено время ожидания (120 сек)"
            log_error(f"{self.MODULE_ID}: {msg}")
            return False, msg
        except Exception as e:
            msg = f"Ошибка: {e}"
            log_error(f"{self.MODULE_ID}: Elevated fix: {msg}")
            return False, msg
        finally:
            # Очистка temp файлов
            try:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    # --- Helpers ----------------------------------------------------------

    @staticmethod
    def _get_user_store_certs(diag: DiagResult) -> List[Dict[str, Any]]:
        """Извлечь сертификаты из CurrentUser store"""
        certs = diag.details.get("certificates", [])
        return [c for c in certs if c.get("store") == "CurrentUser"]

    @staticmethod
    def _get_machine_store_certs(diag: DiagResult) -> List[Dict[str, Any]]:
        """Извлечь сертификаты из LocalMachine store"""
        certs = diag.details.get("certificates", [])
        return [c for c in certs if c.get("store") == "LocalMachine"]

    @staticmethod
    def has_issues(results: Dict[str, DiagResult]) -> bool:
        """Есть ли проблемы в результатах диагностики"""
        return any(r.status == "issue" for r in results.values())

    @staticmethod
    def get_issue_count(results: Dict[str, DiagResult]) -> int:
        """Количество найденных проблем"""
        return sum(1 for r in results.values() if r.status == "issue")

    @staticmethod
    def get_fixable_issues(results: Dict[str, DiagResult]) -> Dict[str, DiagResult]:
        """Получить только исправимые проблемы"""
        return {k: v for k, v in results.items()
                if v.status == "issue" and v.fixable}

    @staticmethod
    def needs_any_admin(results: Dict[str, DiagResult]) -> bool:
        """Требуется ли хотя бы одна admin-операция"""
        return any(r.needs_admin for r in results.values()
                   if r.status == "issue" and r.fixable)

    @staticmethod
    def needs_reboot(fix_results: List[FixResult]) -> bool:
        """Требуется ли перезагрузка после починки"""
        return any(r.needs_reboot for r in fix_results)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _reg_value(key: Any, name: str, default: Any = None) -> Any:
    """Безопасное чтение значения реестра"""
    try:
        value, _ = winreg.QueryValueEx(key, name)
        return value
    except (FileNotFoundError, OSError):
        return default


def _run_powershell(command: str, timeout: int = 30) -> str:
    """
    Запуск PowerShell команды и возврат stdout.

    Использует полный путь к powershell.exe, utf-8 encoding и CREATE_NO_WINDOW.
    """
    result = subprocess.run(
        [_powershell_exe, "-NoProfile", "-Command", command],
        capture_output=True, text=True, timeout=timeout,
        encoding='utf-8', errors='replace',
        creationflags=_CREATE_NO_WINDOW
    )
    if result.returncode != 0 and result.stderr.strip():
        log_warning(f"Fsm_4_1_10: PS stderr: {result.stderr.strip()[:200]}")
    return result.stdout or ""


def _ps_escape(text: str) -> str:
    """Экранирование строки для вставки в PS одинарные кавычки"""
    return text.replace("'", "''")
