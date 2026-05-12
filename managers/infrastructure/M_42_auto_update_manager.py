# -*- coding: utf-8 -*-
"""
M_42: AutoUpdateManager

Автоматическое обновление плагина при запуске QGIS.
Проверяет plugins.xml на GitHub, скачивает ZIP из GitHub Releases,
устанавливает поверх текущей версии.

Вызывается из main_plugin.initGui() после Profile Setup (M_37).
"""

import io
import os
import re
import shutil
import zipfile
from typing import Optional, Tuple
from xml.etree import ElementTree

import requests

from qgis.core import QgsSettings

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.constants import (
    PLUGIN_NAME,
    PLUGIN_DIR,
    PLUGIN_VERSION,
    UPDATE_PLUGINS_XML_URL,
    UPDATE_VERSION_CHECK_TIMEOUT,
    UPDATE_DOWNLOAD_TIMEOUT,
)

__all__ = ['AutoUpdateManager']


class AutoUpdateManager:
    """Автоматическое обновление плагина при запуске QGIS."""

    _SETTINGS_IN_PROGRESS = "Daman_QGIS/update_in_progress"
    _SETTINGS_PREV_VERSION = "Daman_QGIS/update_previous_version"
    _SETTINGS_LAST_CHECK = "Daman_QGIS/update_last_check"
    _SETTINGS_UPDATE_LOG = "Daman_QGIS/update_log"

    def check_and_update(self) -> bool:
        """Проверить наличие обновления и установить.

        Returns:
            True  -- обновление установлено, вызывающий должен запланировать reload.
            False -- обновление не нужно или не удалось.
        """
        if self._is_crash_recovery():
            return False

        channel = self._get_channel()
        if channel is None:
            return False

        result = self._fetch_remote_version(channel)
        if result is None:
            return False

        remote_version, download_url = result

        if not self._is_newer(remote_version, PLUGIN_VERSION):
            log_info(f"M_42: Версия актуальна ({PLUGIN_VERSION})")
            return False

        log_info(
            f"M_42: Доступно обновление {PLUGIN_VERSION} -> {remote_version}"
        )

        zip_data = self._download_zip(download_url)
        if zip_data is None:
            return False

        if not self._validate_zip(zip_data):
            return False

        if not self._install(zip_data):
            return False

        # Записать метаданные обновления для следующего экземпляра
        from datetime import datetime
        settings = QgsSettings()
        settings.setValue(
            self._SETTINGS_LAST_CHECK,
            datetime.now().isoformat()
        )
        settings.setValue(
            self._SETTINGS_UPDATE_LOG,
            f"{PLUGIN_VERSION} -> {remote_version} ({channel})"
        )

        log_info(
            f"M_42: Обновление {remote_version} установлено успешно"
        )
        return True

    def force_update_to(self, download_url: str, target_version: str) -> bool:
        """Принудительное обновление до конкретной версии по URL от сервера.

        Используется когда сервер вернул `update_required` (integrity mismatch
        на validate). Пропускает разрешение plugins.xml — скачивает напрямую
        по URL, выданному сервером.

        Args:
            download_url: полный URL ZIP-архива (например,
                https://daman.tools/releases/beta/Daman_QGIS-0.9.961-beta.1.zip)
            target_version: человекочитаемая версия для логов

        Returns:
            True если установлено (caller должен запланировать рестарт QGIS),
            False иначе.
        """
        log_info(
            f"M_42: Force update triggered -> {target_version} ({download_url})"
        )

        if not download_url:
            log_error("M_42: Force update: пустой download_url")
            return False

        zip_data = self._download_zip(download_url)
        if zip_data is None:
            log_error(f"M_42: Force update download failed for {target_version}")
            return False
        if not self._validate_zip(zip_data):
            log_error(
                f"M_42: Force update ZIP validation failed for {target_version}"
            )
            return False
        if not self._install(zip_data):
            log_error(f"M_42: Force update install failed for {target_version}")
            return False

        log_info(
            f"M_42: Force update to {target_version} installed; restart required"
        )
        return True

    def force_reinstall(self) -> bool:
        """Принудительная переустановка текущей версии с сервера.

        Используется при провале integrity check -- файлы повреждены
        или модифицированы, но версия актуальна. Скачивает и устанавливает
        текущую версию без проверки номера версии.

        Returns:
            True  -- переустановка выполнена, нужен перезапуск QGIS.
            False -- переустановка не удалась.
        """
        channel = self._get_channel()
        if channel is None:
            log_warning("M_42: Не удалось определить канал для переустановки")
            return False

        result = self._fetch_remote_version(channel)
        if result is None:
            log_warning("M_42: Не удалось получить версию для переустановки")
            return False

        remote_version, download_url = result

        log_info(
            f"M_42: Принудительная переустановка {remote_version} "
            f"(integrity fix)"
        )

        zip_data = self._download_zip(download_url)
        if zip_data is None:
            return False

        if not self._validate_zip(zip_data):
            return False

        if not self._install(zip_data):
            return False

        log_info(f"M_42: Переустановка {remote_version} завершена успешно")
        return True

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _is_crash_recovery(self) -> bool:
        """Проверить флаг незавершённого обновления (crash recovery).

        Если флаг установлен -- предыдущее обновление не завершилось.
        Очищаем флаг и пропускаем обновление этот раз.
        """
        settings = QgsSettings()
        if settings.value(self._SETTINGS_IN_PROGRESS, False, type=bool):
            log_warning(
                "M_42: Обнаружен флаг незавершённого обновления, "
                "пропускаем обновление"
            )
            settings.setValue(self._SETTINGS_IN_PROGRESS, False)
            return True
        return False

    def _get_channel(self) -> Optional[str]:
        """Получить канал обновления из URL репозитория QGIS.

        Returns:
            "beta" или "stable", None если репозиторий не найден.
        """
        detected = self._detect_channel_from_repo_url()
        if detected:
            return detected

        log_warning(
            f"M_42: Репозиторий {PLUGIN_NAME} не найден в настройках QGIS"
        )
        return None

    def _detect_channel_from_repo_url(self) -> Optional[str]:
        """Определить канал из URL репозитория в настройках QGIS.

        M_37 записывает URL репозитория при настройке профиля.
        URL содержит канал: .../beta/plugins.xml или .../stable/plugins.xml
        """
        settings = QgsSettings()
        settings.beginGroup("app/plugin_repositories")

        try:
            for repo_name in settings.childGroups():
                settings.beginGroup(repo_name)
                url = settings.value("url", "", type=str)
                enabled = settings.value("enabled", True, type=bool)
                settings.endGroup()

                if not enabled or PLUGIN_NAME not in url:
                    continue

                if "/beta/" in url:
                    return "beta"
                if "/stable/" in url:
                    return "stable"
        finally:
            settings.endGroup()

        return None

    def _fetch_remote_version(
        self, channel: str
    ) -> Optional[Tuple[str, str]]:
        """Получить версию и URL из plugins.xml на GitHub.

        Returns:
            (version, download_url) или None при ошибке.
        """
        url = UPDATE_PLUGINS_XML_URL.format(channel=channel)
        try:
            response = requests.get(
                url, timeout=UPDATE_VERSION_CHECK_TIMEOUT
            )
            if response.status_code != 200:
                log_warning(
                    f"M_42: plugins.xml HTTP {response.status_code}"
                )
                return None

            root = ElementTree.fromstring(response.text)
            plugin_el = root.find(".//pyqgis_plugin")
            if plugin_el is None:
                log_warning(
                    "M_42: Не найден элемент pyqgis_plugin в plugins.xml"
                )
                return None

            version_el = plugin_el.find("version")
            url_el = plugin_el.find("download_url")

            if version_el is None or url_el is None:
                log_warning(
                    "M_42: Отсутствует version или download_url "
                    "в plugins.xml"
                )
                return None

            version = (version_el.text or "").strip()
            download_url = (url_el.text or "").strip()

            if not version or not download_url:
                return None

            return (version, download_url)

        except requests.RequestException as e:
            log_info(f"M_42: Проверка версии не удалась: {e}")
            return None
        except ElementTree.ParseError as e:
            log_warning(f"M_42: Невалидный plugins.xml: {e}")
            return None

    # SemVer X.Y.Z[-{dev|beta}[.N]] — наша конвенция channel-detection
    # (см. Daman_QGIS_dev/scripts/deploy.py:increment_dev_version).
    # Channel precedence: dev (0) < beta (1) < bare stable (2). Это
    # отклонение от строгой SemVer 2.0.0 §11.4.2 alphabetical ordering
    # (`beta` < `dev` ASCII), но соответствует промежуточной природе dev.
    _SEMVER_RE = re.compile(
        r"^(\d+)\.(\d+)\.(\d+)(?:-(dev|beta)(?:\.(\d+))?)?$"
    )
    _CHANNEL_PRECEDENCE = {None: 2, "beta": 1, "dev": 0}

    def _parse_semver(self, version: str) -> Tuple[int, int, int, int, int]:
        """Распарсить SemVer X.Y.Z[-{dev|beta}[.N]] в comparable tuple.

        Returns:
            (major, minor, patch, channel_precedence, counter)
            Где channel_precedence: dev=0, beta=1, bare=2 (выше = новее).
            counter = 0 если pre-release tag без цифры (`-dev` без `.N`).

        Raises:
            ValueError: если входное значение не строка ИЛИ строка не
            соответствует поддерживаемому SemVer-формату
            (rc/alpha/build-metadata отвергаются).
        """
        if not isinstance(version, str):
            raise ValueError(f"Version must be str, got {type(version).__name__}")
        match = self._SEMVER_RE.match(version.strip())
        if not match:
            raise ValueError(f"Unsupported SemVer format: {version!r}")
        major, minor, patch = (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        )
        tag = match.group(4)
        counter = int(match.group(5)) if match.group(5) else 0
        return (major, minor, patch, self._CHANNEL_PRECEDENCE[tag], counter)

    def _is_newer(self, remote: str, local: str) -> bool:
        """Remote версия строго новее local (channel-aware SemVer).

        Канальная иерархия: dev < beta < bare stable (нашего deploy
        pipeline). Внутри канала: counter сравнивается численно.

        Примеры:
            0.9.961-dev      < 0.9.961-dev.1 < 0.9.961-beta.1 < 0.9.961
            0.9.961          > 0.9.960
            0.9.961-beta.1   > 0.9.961-dev.99

        Returns:
            True если remote строго новее local. False если равны/older
            или хотя бы одна версия не парсится (skip update — safe default).
        """
        try:
            return self._parse_semver(remote) > self._parse_semver(local)
        except ValueError as e:
            log_error(
                f"M_42: Невозможно сравнить версии: remote={remote}, "
                f"local={local} ({e}). Update будет пропущен."
            )
            return False

    def _download_zip(self, url: str) -> Optional[bytes]:
        """Скачать ZIP архив плагина.

        Returns:
            Байты ZIP или None при ошибке.
        """
        try:
            log_info(f"M_42: Скачивание обновления...")
            response = requests.get(
                url, timeout=UPDATE_DOWNLOAD_TIMEOUT
            )
            if response.status_code != 200:
                log_warning(
                    f"M_42: Скачивание ZIP HTTP {response.status_code}"
                )
                return None

            zip_data = response.content
            log_info(
                f"M_42: Скачано {len(zip_data) / 1024 / 1024:.1f} MB"
            )
            return zip_data

        except requests.RequestException as e:
            log_warning(f"M_42: Скачивание не удалось: {e}")
            return None

    def _validate_zip(self, zip_data: bytes) -> bool:
        """Валидация ZIP архива.

        Проверки:
        1. Валидный ZIP файл
        2. Содержит Daman_QGIS/metadata.txt
        3. Нет path traversal (.. в путях)
        """
        try:
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                names = zf.namelist()

                # Проверка path traversal
                for name in names:
                    if '..' in name or name.startswith('/'):
                        log_error(
                            f"M_42: Path traversal в ZIP: {name}"
                        )
                        return False

                # Проверка наличия metadata.txt
                expected = f"{PLUGIN_NAME}/metadata.txt"
                if expected not in names:
                    log_warning(
                        f"M_42: ZIP не содержит {expected}"
                    )
                    return False

            return True

        except zipfile.BadZipFile:
            log_warning("M_42: Повреждённый ZIP файл")
            return False
        except Exception as e:
            log_warning(f"M_42: Ошибка валидации ZIP: {e}")
            return False

    def _install(self, zip_data: bytes) -> bool:
        """Атомарная установка: extract в staging -> validate -> swap.

        FIX-1 (review 2026-05-09): старая последовательность
        rmtree-then-extractall на одной try ветке могла оставить
        PLUGIN_DIR в half-extracted state при disk-full / AV-block /
        OS reboot mid-extract. После такого crash'а плагин не загружался,
        не мог даже выполнить _is_crash_recovery — пользователь оставался
        без плагина с UX-hostile silent disappearance.

        Гарантия атомарности:
        - extract в staging dir (никогда не пишем напрямую в PLUGIN_DIR)
        - validate metadata.txt в staging перед swap
        - os.replace(PLUGIN_DIR -> backup), os.replace(staging -> PLUGIN_DIR)
        - на любой OSError swap — откат backup -> PLUGIN_DIR
        - на любой Exception — best-effort cleanup + restore backup if PLUGIN_DIR пуст

        Результат: либо PLUGIN_DIR содержит корректное полное обновление,
        либо PLUGIN_DIR не тронут (старая версия рабочая). Half-extracted
        состояние невозможно.
        """
        settings = QgsSettings()
        parent_dir = os.path.dirname(PLUGIN_DIR)
        plugin_name = os.path.basename(PLUGIN_DIR)
        # Staging + backup рядом с parent_dir (тот же volume — обязательно
        # для атомарного os.replace на Windows и POSIX)
        staging_parent = os.path.join(parent_dir, f".{plugin_name}.staging")
        staging_plugin = os.path.join(staging_parent, plugin_name)
        backup_dir = os.path.join(parent_dir, f".{plugin_name}.backup")

        try:
            settings.setValue(self._SETTINGS_IN_PROGRESS, True)
            settings.setValue(self._SETTINGS_PREV_VERSION, PLUGIN_VERSION)

            # 1. Подготовить чистый staging dir (на случай orphan от prior crash)
            if os.path.isdir(staging_parent):
                shutil.rmtree(staging_parent, ignore_errors=True)
            os.makedirs(staging_parent, exist_ok=True)

            # 2. Извлечь ZIP в staging — никогда напрямую в PLUGIN_DIR
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                zf.extractall(staging_parent)

            # 3. Validate: staging должен содержать metadata.txt (sanity-check
            # что ZIP правильной структуры — _validate_zip уже проверял, это
            # double-check после реального extract)
            if not os.path.isfile(os.path.join(staging_plugin, "metadata.txt")):
                log_error(
                    "M_42 (_install): staging не содержит metadata.txt — "
                    "abort, PLUGIN_DIR не тронут"
                )
                shutil.rmtree(staging_parent, ignore_errors=True)
                settings.setValue(self._SETTINGS_IN_PROGRESS, False)
                return False

            # 4. Atomic swap: backup -> replace -> remove backup
            # Если PLUGIN_DIR существует, переименовываем в backup_dir.
            # Если не существует (первая установка) — пропускаем backup.
            if os.path.isdir(PLUGIN_DIR):
                if os.path.isdir(backup_dir):
                    shutil.rmtree(backup_dir, ignore_errors=True)
                os.replace(PLUGIN_DIR, backup_dir)
            try:
                os.replace(staging_plugin, PLUGIN_DIR)
            except OSError as swap_err:
                # Откат: вернуть backup -> PLUGIN_DIR
                log_error(
                    f"M_42 (_install): atomic swap failed ({swap_err}), "
                    f"откат backup -> PLUGIN_DIR"
                )
                if os.path.isdir(backup_dir):
                    try:
                        os.replace(backup_dir, PLUGIN_DIR)
                    except OSError as restore_err:
                        log_error(
                            f"M_42 (_install): RESTORE FAILED ({restore_err}). "
                            f"Backup в {backup_dir} — восстановите вручную."
                        )
                shutil.rmtree(staging_parent, ignore_errors=True)
                settings.setValue(self._SETTINGS_IN_PROGRESS, False)
                return False

            # 5. Cleanup: backup и staging больше не нужны
            if os.path.isdir(backup_dir):
                shutil.rmtree(backup_dir, ignore_errors=True)
            if os.path.isdir(staging_parent):
                shutil.rmtree(staging_parent, ignore_errors=True)

            # 6. __pycache__ cleanup на новом дереве
            self._clean_pycache(PLUGIN_DIR)

            # 7. FIX-5: invalidate cached plugin_hash. Обычно за этим следует
            # QGIS restart (новый process = свежий import → cache пуст), но
            # safety-net на случай in-session reload через Plugin Manager.
            try:
                from Daman_QGIS.integrity_hash import invalidate_cache
                invalidate_cache()
            except ImportError:
                pass

            settings.setValue(self._SETTINGS_IN_PROGRESS, False)
            return True

        except Exception as e:
            log_error(f"M_42 (_install): {e}")
            # Best-effort cleanup. Backup восстановлен в OSError-ветке выше
            # или ещё не создавался (если crash в Шагах 1-3).
            if os.path.isdir(staging_parent):
                shutil.rmtree(staging_parent, ignore_errors=True)
            # Если PLUGIN_DIR пропал и backup есть — попытаться восстановить
            if os.path.isdir(backup_dir) and not os.path.isdir(PLUGIN_DIR):
                try:
                    os.replace(backup_dir, PLUGIN_DIR)
                    log_warning(
                        "M_42 (_install): восстановлен backup -> PLUGIN_DIR "
                        "после exception"
                    )
                except OSError:
                    log_error(
                        f"M_42 (_install): не удалось восстановить backup. "
                        f"Backup в {backup_dir} — восстановите вручную."
                    )
            settings.setValue(self._SETTINGS_IN_PROGRESS, False)
            return False

    def _clean_pycache(self, root_dir: str) -> None:
        """Рекурсивно удалить __pycache__ (best-effort)."""
        for dirpath, dirnames, _ in os.walk(root_dir):
            for dirname in dirnames:
                if dirname == '__pycache__':
                    cache_path = os.path.join(dirpath, dirname)
                    try:
                        shutil.rmtree(cache_path)
                    except OSError:
                        pass  # Файлы могут быть заблокированы
