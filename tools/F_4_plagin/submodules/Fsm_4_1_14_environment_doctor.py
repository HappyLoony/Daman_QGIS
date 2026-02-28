# -*- coding: utf-8 -*-
"""
Fsm_4_1_14_EnvironmentDoctor - Диагностика среды QGIS

Проверяет системное окружение: версии QGIS/Qt/Python/GDAL/PROJ,
доступность QtWebEngine и Edge, тип установки QGIS, свободное
дисковое пространство.

Паттерн: аналогичен Fsm_4_1_10_NetworkDoctor (DiagResult, run_diagnostics).

Зависимости:
- Fsm_4_1_10_network_doctor: DiagResult (dataclass)
- Msm_40_3_edge_auth: find_edge_executable (детекция Edge)
"""

import os
import platform
import shutil
import sys
from typing import Any, Dict

from qgis.core import Qgis, QgsApplication
from qgis.PyQt.QtCore import qVersion

from Daman_QGIS.utils import log_info, log_warning

from .Fsm_4_1_10_network_doctor import DiagResult


class EnvironmentDoctor:
    """Диагностика системной среды QGIS"""

    MODULE_ID = "Fsm_4_1_14"

    # Минимальная рекомендуемая версия QGIS
    MIN_QGIS_VERSION = (3, 40)

    # Минимальное свободное место (МБ) для данных плагина
    MIN_DISK_SPACE_MB = 100

    # ------------------------------------------------------------------
    # Public static API
    # ------------------------------------------------------------------

    @staticmethod
    def run_diagnostics() -> Dict[str, DiagResult]:
        """Запуск полной диагностики среды.

        Returns:
            dict: ключ = id проверки, значение = DiagResult
        """
        doctor = EnvironmentDoctor()
        checks = [
            ("qgis_version", doctor._check_qgis_version),
            ("qt_version", doctor._check_qt_version),
            ("python_version", doctor._check_python_version),
            ("os_info", doctor._check_os_info),
            ("gdal_version", doctor._check_gdal_version),
            ("proj_version", doctor._check_proj_version),
            ("qtwebengine", doctor._check_qtwebengine),
            ("edge", doctor._check_edge),
            ("disk_space", doctor._check_disk_space),
            ("install_type", doctor._check_install_type),
        ]

        results: Dict[str, DiagResult] = {}
        for check_id, check_fn in checks:
            try:
                results[check_id] = check_fn()
            except Exception as e:
                results[check_id] = DiagResult(
                    name=check_id,
                    status="error",
                    message=f"Ошибка проверки: {e}",
                    details={"error": str(e)},
                )
        return results

    @staticmethod
    def quick_summary() -> str:
        """Краткая сводка среды для лога при запуске (одна строка).

        Пример: 'QGIS 3.40.2, Qt 5.15.3, Python 3.12.3, GDAL 3.9.3, Edge: OK, QtWebEngine: нет'
        """
        parts = []

        # QGIS
        parts.append(f"QGIS {Qgis.QGIS_VERSION}")

        # Qt
        parts.append(f"Qt {qVersion()}")

        # Python
        parts.append(f"Python {platform.python_version()}")

        # GDAL
        try:
            from osgeo import gdal
            parts.append(f"GDAL {gdal.VersionInfo('RELEASE_NAME')}")
        except Exception:
            parts.append("GDAL: ?")

        # Edge
        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_40_3_edge_auth import (
                find_edge_executable,
            )
            edge_path = find_edge_executable()
            parts.append("Edge: OK" if edge_path else "Edge: нет")
        except Exception:
            parts.append("Edge: ?")

        # QtWebEngine
        webengine = False
        try:
            from qgis.PyQt.QtWebEngineWidgets import QWebEngineView  # noqa: F401
            webengine = True
        except ImportError:
            try:
                from qgis.PyQt.QtWebEngineCore import QWebEngineProfile  # noqa: F401
                webengine = True
            except ImportError:
                pass
        parts.append("QtWebEngine: OK" if webengine else "QtWebEngine: нет")

        return ", ".join(parts)

    @staticmethod
    def has_issues(results: Dict[str, DiagResult]) -> bool:
        """Есть ли проблемы в результатах диагностики."""
        return any(d.status == "issue" for d in results.values())

    @staticmethod
    def get_issue_count(results: Dict[str, DiagResult]) -> int:
        """Количество найденных проблем."""
        return sum(1 for d in results.values() if d.status == "issue")

    @staticmethod
    def format_plain_text(results: Dict[str, DiagResult]) -> str:
        """Форматирование результатов как plain text для копирования.

        Returns:
            str: Многострочный текст с результатами
        """
        lines = []
        for check_id, diag in results.items():
            instruction = diag.details.get("instruction", "")
            extra = f" -> {instruction}" if instruction and diag.status == "issue" else ""
            lines.append(f"  [{diag.status}] {diag.name}: {diag.message}{extra}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private check methods
    # ------------------------------------------------------------------

    def _check_qgis_version(self) -> DiagResult:
        """Проверка версии QGIS."""
        version_str = Qgis.QGIS_VERSION
        version_int = Qgis.QGIS_VERSION_INT

        # Parse major.minor from version_int (e.g. 34002 -> 3.40)
        major = version_int // 10000
        minor = (version_int // 100) % 100

        if (major, minor) >= self.MIN_QGIS_VERSION:
            status = "ok"
            message = version_str
        else:
            status = "issue"
            message = (
                f"{version_str} (рекомендуется >= "
                f"{self.MIN_QGIS_VERSION[0]}.{self.MIN_QGIS_VERSION[1]})"
            )

        return DiagResult(
            name="Версия QGIS",
            status=status,
            message=message,
            details={
                "version": version_str,
                "version_int": version_int,
                "major": major,
                "minor": minor,
            },
        )

    def _check_qt_version(self) -> DiagResult:
        """Проверка версии Qt."""
        qt_ver = qVersion()
        qt_major = int(qt_ver.split(".")[0]) if qt_ver else 0

        note = ""
        if qt_major == 5:
            note = " (Qt5 -- QtWebEngine может быть ограничен)"

        return DiagResult(
            name="Qt",
            status="ok",
            message=f"{qt_ver}{note}",
            details={"version": qt_ver, "qt_major": qt_major},
        )

    def _check_python_version(self) -> DiagResult:
        """Проверка версии Python."""
        py_ver = platform.python_version()
        return DiagResult(
            name="Python",
            status="ok",
            message=py_ver,
            details={
                "version": py_ver,
                "executable": sys.executable,
                "implementation": platform.python_implementation(),
            },
        )

    def _check_os_info(self) -> DiagResult:
        """Проверка операционной системы."""
        system = platform.system()
        arch = platform.architecture()[0]
        details: Dict[str, Any] = {
            "system": system,
            "architecture": arch,
            "release": platform.release(),
            "version": platform.version(),
        }

        if system == "Windows":
            try:
                edition = platform.win32_edition()
                details["edition"] = edition
                message = f"Windows {platform.release()} {edition} ({platform.version()}) {arch}"
            except Exception:
                message = f"Windows {platform.release()} ({platform.version()}) {arch}"
        else:
            message = f"{system} {platform.release()} {arch}"

        return DiagResult(
            name="ОС",
            status="ok",
            message=message,
            details=details,
        )

    def _check_gdal_version(self) -> DiagResult:
        """Проверка версии GDAL."""
        try:
            from osgeo import gdal
            version = gdal.VersionInfo("RELEASE_NAME")
            return DiagResult(
                name="GDAL",
                status="ok",
                message=version,
                details={"version": version},
            )
        except ImportError as e:
            return DiagResult(
                name="GDAL",
                status="error",
                message=f"Не удалось импортировать: {e}",
                details={"error": str(e)},
            )

    def _check_proj_version(self) -> DiagResult:
        """Проверка версии PROJ."""
        try:
            from osgeo import osr
            major = osr.GetPROJVersionMajor()
            minor = osr.GetPROJVersionMinor()
            patch = osr.GetPROJVersionMicro()
            version = f"{major}.{minor}.{patch}"
            return DiagResult(
                name="PROJ",
                status="ok",
                message=version,
                details={"version": version, "major": major, "minor": minor, "patch": patch},
            )
        except (ImportError, AttributeError):
            # Fallback: try pyproj
            try:
                from pyproj import proj_version_str
                return DiagResult(
                    name="PROJ",
                    status="ok",
                    message=proj_version_str,
                    details={"version": proj_version_str},
                )
            except ImportError:
                return DiagResult(
                    name="PROJ",
                    status="error",
                    message="Не удалось определить версию PROJ",
                    details={},
                )

    def _check_qtwebengine(self) -> DiagResult:
        """Проверка доступности QtWebEngine."""
        # Определяем тип установки для инструкции
        install_type = self._detect_install_type()

        # Пробуем Qt6 путь
        try:
            from qgis.PyQt.QtWebEngineWidgets import QWebEngineView  # noqa: F401
            from qgis.PyQt.QtWebEngineCore import QWebEngineProfile  # noqa: F401
            return DiagResult(
                name="QtWebEngine",
                status="ok",
                message="Доступен (Qt6)",
                details={"available": True, "qt_path": "Qt6"},
            )
        except ImportError:
            pass

        # Пробуем Qt5 путь
        try:
            from qgis.PyQt.QtWebEngineWidgets import (  # noqa: F401
                QWebEngineView as _View,
                QWebEngineProfile as _Profile,
            )
            return DiagResult(
                name="QtWebEngine",
                status="ok",
                message="Доступен (Qt5)",
                details={"available": True, "qt_path": "Qt5"},
            )
        except ImportError:
            pass

        # Недоступен - формируем инструкцию
        instruction = self._get_webengine_instruction(install_type)

        return DiagResult(
            name="QtWebEngine",
            status="issue",
            message="Недоступен (авторизация НСПД через встроенный браузер отключена)",
            details={
                "available": False,
                "qt_path": None,
                "install_type": install_type,
                "instruction": instruction,
            },
        )

    def _check_edge(self) -> DiagResult:
        """Проверка доступности Microsoft Edge."""
        if sys.platform != "win32":
            return DiagResult(
                name="Microsoft Edge",
                status="skip",
                message="Проверка только для Windows",
                details={"available": False},
            )

        try:
            from Daman_QGIS.managers.infrastructure.submodules.Msm_40_3_edge_auth import (
                find_edge_executable,
            )
            edge_path = find_edge_executable()
        except ImportError:
            edge_path = None

        if edge_path:
            return DiagResult(
                name="Microsoft Edge",
                status="ok",
                message=f"OK ({edge_path})",
                details={"available": True, "path": edge_path},
            )
        else:
            return DiagResult(
                name="Microsoft Edge",
                status="issue",
                message="Не найден (авторизация НСПД через Edge CDP недоступна)",
                details={
                    "available": False,
                    "instruction": "Установите Microsoft Edge для авторизации НСПД",
                },
            )

    def _check_disk_space(self) -> DiagResult:
        """Проверка свободного дискового пространства."""
        try:
            settings_path = QgsApplication.qgisSettingsDirPath()
            usage = shutil.disk_usage(settings_path)
            free_mb = usage.free / (1024 * 1024)
            total_mb = usage.total / (1024 * 1024)

            if free_mb < self.MIN_DISK_SPACE_MB:
                status = "issue"
                message = f"{free_mb:.0f} МБ свободно (рекомендуется >= {self.MIN_DISK_SPACE_MB} МБ)"
            else:
                # Показываем в ГБ если > 1 ГБ
                if free_mb >= 1024:
                    message = f"{free_mb / 1024:.1f} ГБ свободно"
                else:
                    message = f"{free_mb:.0f} МБ свободно"
                status = "ok"

            return DiagResult(
                name="Диск",
                status=status,
                message=message,
                details={
                    "free_mb": round(free_mb, 1),
                    "total_mb": round(total_mb, 1),
                    "path": settings_path,
                },
            )
        except Exception as e:
            return DiagResult(
                name="Диск",
                status="error",
                message=f"Не удалось проверить: {e}",
                details={"error": str(e)},
            )

    def _check_install_type(self) -> DiagResult:
        """Проверка типа установки QGIS."""
        install_type = self._detect_install_type()
        prefix_path = QgsApplication.prefixPath()

        return DiagResult(
            name="Тип установки",
            status="ok",
            message=install_type,
            details={"install_type": install_type, "prefix_path": prefix_path},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_install_type() -> str:
        """Определение типа установки QGIS."""
        exe = sys.executable.lower().replace("\\", "/")
        prefix = QgsApplication.prefixPath().lower().replace("\\", "/")

        # OSGeo4W
        if os.environ.get("OSGEO4W_ROOT") or "osgeo4w" in exe or "osgeo4w" in prefix:
            return "OSGeo4W"

        # Flatpak
        if "flatpak" in exe or "flatpak" in prefix:
            return "Flatpak"

        # Snap
        if "snap" in exe or "snap" in prefix:
            return "Snap"

        # Linux system package
        if sys.platform != "win32" and (
            exe.startswith("/usr/bin") or prefix.startswith("/usr")
        ):
            return "System package"

        # Windows standalone
        if sys.platform == "win32":
            return "Standalone installer"

        return "Unknown"

    @staticmethod
    def _get_webengine_instruction(install_type: str) -> str:
        """Инструкция по установке QtWebEngine в зависимости от типа установки."""
        instructions = {
            "OSGeo4W": (
                "Запустите OSGeo4W Setup и установите пакет python3-pyqt5-qtwebengine "
                "(или qt6-webengine). Затем перезапустите QGIS."
            ),
            "Standalone installer": (
                "Переустановите QGIS с полным набором компонентов "
                "(QtWebEngine входит в стандартную поставку QGIS 3.40 LTR). "
                "Скачайте последний установщик с qgis.org."
            ),
            "System package": (
                "Установите системный пакет: sudo apt install python3-pyqt5.qtwebengine "
                "(или аналог для вашего дистрибутива). Затем перезапустите QGIS."
            ),
            "Flatpak": (
                "QtWebEngine может быть недоступен в Flatpak-сборке QGIS. "
                "Рассмотрите установку QGIS из системных пакетов."
            ),
            "Snap": (
                "QtWebEngine может быть недоступен в Snap-сборке QGIS. "
                "Рассмотрите установку QGIS из системных пакетов."
            ),
        }
        return instructions.get(install_type, "Обратитесь к документации QGIS по установке QtWebEngine.")
