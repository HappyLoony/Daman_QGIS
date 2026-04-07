# -*- coding: utf-8 -*-
"""
M_37_ProfileSetupManager - Автоматическое создание и настройка профиля Daman_QGIS.

Отвечает за:
- Создание профиля Daman_QGIS при первой установке в default
- Копирование плагина из default в Daman_QGIS
- Скачивание и применение референсного профиля (QGIS3.ini, стили)
- Синхронизацию версий при обновлении в default
- Обновление профиля при выходе новых версий настроек
- Offline fallback с отложенным скачиванием

Зависимости:
- constants.py (PLUGIN_NAME, API_BASE_URL, DAMAN_PROFILE_NAME и др.)
- utils.py (log_info, log_error, log_warning)
- QgsUserProfileManager (QGIS API)

ВАЖНО: qgisSettingsDirPath() возвращает КОРЕНЬ профиля:
    .../profiles/Daman_QGIS/
НЕ .../profiles/Daman_QGIS/QGIS/
"""

import io
import shutil
import zipfile
from pathlib import Path
from typing import Any, List, Optional, Dict, Tuple

from qgis.PyQt.QtCore import QSettings, QTimer
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import QgsApplication, QgsSettings, Qgis

from Daman_QGIS.utils import log_info, log_error, log_warning
from Daman_QGIS.constants import (
    PLUGIN_NAME,
    API_BASE_URL,
    DEFAULT_PROFILE_NAME,
    DAMAN_PROFILE_NAME,
    PROFILE_API_ENDPOINT,
    PROFILE_INFO_ENDPOINT,
    PROFILE_COPY_IGNORE,
)

__all__ = ['ProfileSetupManager']


class ProfileSetupManager:
    """Менеджер создания и настройки профиля Daman_QGIS.

    Основные сценарии:
    1. Первый запуск в default -- создать Daman_QGIS, скопировать плагин,
       скачать reference profile, переключить.
    2. Повторный вход в default -- тихая синхронизация версий.
    3. Запуск в Daman_QGIS -- deferred retry для reference profile,
       проверка обновлений профиля.
    4. Запуск в другом профиле -- предупреждение.
    """

    # URL репозитория плагина (Beta)
    REPO_URL = (
        "https://raw.githubusercontent.com/HappyLoony/"
        "Daman_QGIS/main/beta/plugins.xml"
    )
    REPO_NAME = "Daman QGIS (Beta)"

    # Timeout для profile операций (выполняются на UI thread при запуске)
    _PROFILE_TIMEOUT = 10  # seconds

    # Секции QGIS3.ini, которые НЕ заменяются при обновлении профиля.
    # CRS (Projections) -- пользователь настраивает МСК через F_0_5.
    # Daman_QGIS -- profile_hash, profile_applied_at_version и др.
    # метаданные плагина, иначе каждый запуск = повторное обновление.
    _PROTECTED_INI_GROUPS = ("Projections", "Daman_QGIS")

    def __init__(self) -> None:
        pass

    # ================================================================
    # Публичные методы
    # ================================================================

    def apply_pending_ini(self) -> None:
        """Применить staged QGIS3.ini при запуске, ДО загрузки QgsSettings.

        Вызывается ПЕРВЫМ в initGui() -- до любого обращения к QgsSettings.
        Защищённые секции (CRS и др.) сохраняются и восстанавливаются
        после замены, чтобы не затереть пользовательские настройки.
        """
        profile_root = Path(QgsApplication.qgisSettingsDirPath())

        # Workaround QGIS bug: папка processing не создаётся автоматически,
        # но QGIS валидирует путь при открытии Settings -> Options.
        # defaultOutputFolder() = QDir.homePath() + "/processing"
        # https://github.com/qgis/QGIS/issues/64029
        from qgis.PyQt.QtCore import QDir
        processing_dir = Path(QDir.homePath()) / "processing"
        if not processing_dir.exists():
            processing_dir.mkdir(parents=True, exist_ok=True)

        pending = profile_root / "QGIS" / "QGIS3.ini.pending"
        target = profile_root / "QGIS" / "QGIS3.ini"

        if pending.exists():
            try:
                # Сохранить пользовательские настройки (CRS и др.)
                preserved = self._read_protected_ini_keys(target)

                shutil.copy2(pending, target)
                pending.unlink()

                # Восстановить пользовательские настройки
                if preserved:
                    self._write_protected_ini_keys(target, preserved)
                    log_info(
                        f"M_37: Pending QGIS3.ini applied, "
                        f"preserved groups: {list(preserved.keys())}"
                    )
                else:
                    log_info("M_37: Pending QGIS3.ini applied")
            except Exception as e:
                log_error(f"M_37: Failed to apply pending INI: {e}")

    def check_and_setup_profile(self) -> str:
        """Главный роутинг -- определить профиль и выполнить нужное действие.

        Returns:
            "ok" -- мы в Daman_QGIS, нормальная инициализация
            "setup_done" -- профиль создан, переключение инициировано
            "sync_done" -- версия синхронизирована из default
            "wrong_profile" -- запуск в неизвестном профиле
        """
        try:
            current = Path(QgsApplication.qgisSettingsDirPath())

            if self._is_default_profile():
                return self._handle_default_profile()
            elif self._is_daman_profile():
                return "ok"
            else:
                self._show_wrong_profile_warning()
                return "wrong_profile"
        except Exception as e:
            log_error(f"M_37 (check_and_setup_profile): {e}")
            return "ok"  # Не блокировать плагин при ошибке

    def ensure_reference_profile_applied(self) -> None:
        """Deferred retry: скачать reference profile если не был применен.

        Вызывается в Daman_QGIS после основной инициализации.
        """
        from time import perf_counter

        if not self._is_daman_profile():
            log_warning("M_37: ensure_reference_profile_applied skipped (not Daman_QGIS profile)")
            return

        settings = QgsSettings()
        if settings.value("Daman_QGIS/profile_hash", ""):
            log_info("M_37: [TIMING] ensure_reference_profile_applied: skipped (already applied)")
            return  # Уже применен

        try:
            _t = perf_counter()
            zip_data = self._download_profile_zip()
            log_info(f"M_37: [TIMING] _download_profile_zip: {perf_counter() - _t:.3f}s")
            if not zip_data:
                return  # API недоступен, попробуем в следующий раз

            profile_root = Path(QgsApplication.qgisSettingsDirPath())

            _t = perf_counter()
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                self._validate_zip_entries(zf, profile_root)
                self._extract_with_ini_staging(zf, profile_root)
            log_info(f"M_37: [TIMING] extract_profile: {perf_counter() - _t:.3f}s")

            # Получить version info
            _t = perf_counter()
            remote_info = self._get_remote_profile_info()
            log_info(f"M_37: [TIMING] _get_remote_profile_info: {perf_counter() - _t:.3f}s")
            if remote_info:
                settings.setValue(
                    "Daman_QGIS/profile_version", remote_info.get("version", "")
                )
                settings.setValue(
                    "Daman_QGIS/profile_hash", remote_info.get("hash", "")
                )

            # Записать версию плагина при которой профиль применен
            plugin_path = Path(QgsApplication.qgisSettingsDirPath()) / \
                "python" / "plugins" / DAMAN_PROFILE_NAME
            current_version = self._read_plugin_version(plugin_path)
            settings.setValue(
                "Daman_QGIS/profile_applied_at_version", current_version
            )

            log_info("M_37: Reference profile applied (deferred)")

            log_info("M_37: Profile settings loaded, restart QGIS to apply")
        except Exception as e:
            log_warning(f"M_37: Deferred reference profile failed: {e}")

    def is_first_run(self) -> bool:
        """Первый запуск в профиле Daman_QGIS (показать welcome)."""
        settings = QgsSettings()
        return not settings.value(
            "Daman_QGIS/welcome_shown", False, type=bool
        )

    def show_first_run_welcome(self) -> None:
        """Приветственный диалог при первом запуске."""
        from qgis.utils import iface  # type: ignore[import-untyped]

        settings = QgsSettings()
        if settings.value("Daman_QGIS/welcome_shown", False, type=bool):
            return

        QMessageBox.information(
            iface.mainWindow(),
            PLUGIN_NAME,
            "Daman QGIS -- инструмент для работы с проектами\n"
            "планировки территории.\n\n"
            "Для начала работы активируйте лицензию\n"
            "в меню плагина (F 5.3)."
        )
        settings.setValue("Daman_QGIS/welcome_shown", True)

    def check_profile_update(self) -> None:
        """Автоматическое обновление профиля при смене версии плагина.

        Логика: при обновлении плагина (новая версия) проверяет hash
        профиля на сервере. Если hash отличается от локального --
        скачивает и применяет автоматически (без диалога).
        """
        from time import perf_counter

        if not self._is_daman_profile():
            return

        try:
            settings = QgsSettings()

            # Текущая версия плагина
            plugin_path = Path(QgsApplication.qgisSettingsDirPath()) / \
                "python" / "plugins" / DAMAN_PROFILE_NAME
            current_version = self._read_plugin_version(plugin_path)

            # Версия при которой профиль последний раз проверялся
            applied_version = settings.value(
                "Daman_QGIS/profile_applied_at_version", ""
            )

            # Версия не изменилась -- пропускаем
            if applied_version and \
               self._parse_version(current_version) <= \
               self._parse_version(applied_version):
                log_info("M_37: [TIMING] check_profile_update: skipped (version unchanged)")
                return

            # Нет сохраненной версии -- первый запуск (ensure_reference)
            if not applied_version:
                log_info("M_37: [TIMING] check_profile_update: skipped (first run)")
                return

            # Версия плагина изменилась -- проверить hash профиля
            _t = perf_counter()
            remote_info = self._get_remote_profile_info()
            log_info(f"M_37: [TIMING] check_profile_update/_get_remote_profile_info: {perf_counter() - _t:.3f}s")
            if not remote_info:
                # API недоступен -- до 3 попыток при следующих запусках
                retry_count = settings.value(
                    "Daman_QGIS/profile_check_retries", 0, type=int
                )
                if retry_count >= 3:
                    settings.setValue(
                        "Daman_QGIS/profile_applied_at_version",
                        current_version,
                    )
                    settings.remove("Daman_QGIS/profile_check_retries")
                    log_warning(
                        "M_37: Profile check skipped after 3 failed attempts"
                    )
                else:
                    settings.setValue(
                        "Daman_QGIS/profile_check_retries", retry_count + 1
                    )
                    log_info(
                        f"M_37: API unavailable, retry {retry_count + 1}/3"
                    )
                return

            remote_hash = remote_info.get("hash", "")
            local_hash = settings.value("Daman_QGIS/profile_hash", "")

            if remote_hash and remote_hash != local_hash:
                # Hash отличается -- применить обновление автоматически
                log_info(
                    f"M_37: Profile update detected "
                    f"(plugin {applied_version} -> {current_version}), "
                    f"applying..."
                )
                if not self._apply_profile_update(remote_info):
                    return  # Не записывать версию если обновление не применено

            # Записать текущую версию + сбросить счетчик попыток
            settings.setValue(
                "Daman_QGIS/profile_applied_at_version", current_version
            )
            settings.remove("Daman_QGIS/profile_check_retries")
        except Exception as e:
            log_warning(f"M_37 (check_profile_update): {e}")

    # ================================================================
    # Определение профиля
    # ================================================================

    def _is_default_profile(self) -> bool:
        """Текущий профиль -- default?"""
        current = Path(QgsApplication.qgisSettingsDirPath())
        return current.name.lower() == DEFAULT_PROFILE_NAME.lower()

    def _is_daman_profile(self) -> bool:
        """Текущий профиль -- Daman_QGIS?"""
        current = Path(QgsApplication.qgisSettingsDirPath())
        return current.name == DAMAN_PROFILE_NAME

    # ================================================================
    # Сценарий: default profile
    # ================================================================

    def _handle_default_profile(self) -> str:
        """Логика для запуска в default."""
        from qgis.utils import iface  # type: ignore[import-untyped]

        manager = iface.userProfileManager()
        profile_exists = manager.profileExists(DAMAN_PROFILE_NAME)

        if not profile_exists:
            return self._handle_default_first_time(manager)
        else:
            return self._handle_default_existing(manager)

    def _handle_default_first_time(self, manager: object) -> str:
        """Первый запуск -- создание профиля Daman_QGIS."""
        from qgis.utils import iface  # type: ignore[import-untyped]

        log_info("M_37: Первичная установка -- создание профиля Daman_QGIS")

        # 1. Создать профиль
        profile_path = self._create_daman_profile(manager)
        if not profile_path:
            log_error("M_37: Не удалось создать профиль Daman_QGIS")
            return "ok"  # Не блокировать

        # 2. Скачать reference profile
        self._apply_reference_profile(profile_path)

        # 3. Записать repo URL и включить плагин
        self._write_repo_url_to_profile(profile_path)
        self._enable_plugin_in_profile(profile_path)

        # 4. Скопировать плагин
        self._copy_plugin_to_profile(profile_path)

        # 5. Записать profiles.ini (defaultProfile=Daman_QGIS)
        self._write_profiles_ini(manager)

        # 6. Предложить переключиться
        result = QMessageBox.question(
            iface.mainWindow(),
            PLUGIN_NAME,
            "Профиль Daman_QGIS создан и настроен.\n"
            "Переключиться на него сейчас?\n\n"
            "При следующем запуске QGIS откроется "
            "в профиле Daman_QGIS автоматически.",
        )
        if result == QMessageBox.StandardButton.Yes:
            self._switch_to_daman_profile(manager)

        return "setup_done"

    def _handle_default_existing(self, manager: object) -> str:
        """Повторный вход в default -- синхронизация и переключение."""
        from qgis.utils import iface  # type: ignore[import-untyped]

        synced = self._sync_if_version_newer(manager)
        if synced:
            log_info("M_37: Plugin synced to Daman_QGIS profile")

        # Всегда предлагать переключиться -- плагин не должен работать в default
        result = QMessageBox.question(
            iface.mainWindow(),
            PLUGIN_NAME,
            "Плагин запущен в профиле default.\n"
            "Переключиться на профиль Daman_QGIS?\n\n"
            "Плагин предназначен для работы в профиле Daman_QGIS.",
        )
        if result == QMessageBox.StandardButton.Yes:
            self._switch_to_daman_profile(manager)

        return "sync_done"

    # ================================================================
    # Создание профиля
    # ================================================================

    def _create_daman_profile(self, manager: object) -> Optional[Path]:
        """Создать профиль Daman_QGIS через QgsUserProfileManager."""
        try:
            error = manager.createUserProfile(DAMAN_PROFILE_NAME)  # type: ignore[union-attr]
            if error:
                log_error(f"M_37: createUserProfile error: {error}")
                return None

            # Путь к новому профилю
            profiles_root = Path(
                QgsApplication.qgisSettingsDirPath()
            ).parent
            profile_path = profiles_root / DAMAN_PROFILE_NAME

            if profile_path.exists():
                log_info(f"M_37: Профиль создан: {profile_path}")
                return profile_path

            log_error(f"M_37: Профиль создан, но папка не найдена: {profile_path}")
            return None
        except Exception as e:
            log_error(f"M_37 (_create_daman_profile): {e}")
            return None

    # ================================================================
    # Reference profile (download + extract)
    # ================================================================

    def _apply_reference_profile(self, profile_path: Path) -> None:
        """Скачать и применить reference profile при первичной установке.

        При первичной установке QSettings работает в default,
        поэтому staging для QGIS3.ini НЕ нужен (он пишется в другой профиль).
        """
        try:
            zip_data = self._download_profile_zip()
            if zip_data:
                with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                    self._validate_zip_entries(zf, profile_path)
                    zf.extractall(profile_path)

                # Записать hash
                remote_info = self._get_remote_profile_info()
                if remote_info:
                    ini_path = profile_path / "QGIS" / "QGIS3.ini"
                    s = QSettings(str(ini_path), QSettings.Format.IniFormat)
                    s.setValue(
                        "Daman_QGIS/profile_version",
                        remote_info.get("version", ""),
                    )
                    s.setValue(
                        "Daman_QGIS/profile_hash",
                        remote_info.get("hash", ""),
                    )
                    # Записать версию плагина при которой профиль применен
                    default_plugin = Path(
                        QgsApplication.qgisSettingsDirPath()
                    ) / "python" / "plugins" / DAMAN_PROFILE_NAME
                    s.setValue(
                        "Daman_QGIS/profile_applied_at_version",
                        self._read_plugin_version(default_plugin),
                    )
                    s.sync()

                log_info("M_37: Reference profile applied")
            else:
                log_warning(
                    "M_37: Reference profile не получен, "
                    "будет скачан при следующем запуске"
                )
        except Exception as e:
            log_error(f"M_37 (_apply_reference_profile): {e}")

    def _apply_profile_update(self, remote_info: Dict) -> bool:
        """Применить обновление профиля с staging для QGIS3.ini.

        Returns:
            True если обновление успешно применено, False при ошибке.
        """
        zip_data = self._download_profile_zip()
        if not zip_data:
            return False

        profile_root = Path(QgsApplication.qgisSettingsDirPath())

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            self._validate_zip_entries(zf, profile_root)
            self._extract_with_ini_staging(zf, profile_root)

        # Сохранить hash и version
        settings = QgsSettings()
        settings.setValue(
            "Daman_QGIS/profile_version", remote_info.get("version", "")
        )
        settings.setValue(
            "Daman_QGIS/profile_hash", remote_info.get("hash", "")
        )

        log_info("M_37: Profile updated, changes will apply on next restart")
        return True

    def _download_profile_zip(self) -> Optional[bytes]:
        """Скачать profile.zip с API."""
        try:
            import requests
            response = requests.get(
                PROFILE_API_ENDPOINT,
                timeout=self._PROFILE_TIMEOUT,
            )
            if response.status_code == 200:
                return response.content
            else:
                log_warning(
                    f"M_37: Profile download HTTP {response.status_code}"
                )
                return None
        except Exception as e:
            log_warning(f"M_37: Profile download failed: {e}")
            return None

    def _get_remote_profile_info(self) -> Optional[Dict]:
        """Получить метаданные профиля с API (?action=profile&info=1)."""
        try:
            import requests
            response = requests.get(
                PROFILE_INFO_ENDPOINT,
                timeout=self._PROFILE_TIMEOUT,
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception:
            return None

    # ================================================================
    # INI protection helpers (CRS preservation)
    # ================================================================

    def _read_protected_ini_keys(
        self, ini_path: Path
    ) -> Dict[str, Dict[str, Any]]:
        """Прочитать защищённые секции из QGIS3.ini перед заменой.

        Returns:
            Словарь {group_name: {key: value, ...}} для непустых групп.
        """
        if not ini_path.exists():
            return {}

        result: Dict[str, Dict[str, Any]] = {}
        s = QSettings(str(ini_path), QSettings.Format.IniFormat)

        for group in self._PROTECTED_INI_GROUPS:
            s.beginGroup(group)
            keys = s.allKeys()
            if keys:
                result[group] = {key: s.value(key) for key in keys}
            s.endGroup()

        return result

    def _write_protected_ini_keys(
        self, ini_path: Path, preserved: Dict[str, Dict[str, Any]]
    ) -> None:
        """Восстановить защищённые секции в QGIS3.ini после замены."""
        s = QSettings(str(ini_path), QSettings.Format.IniFormat)

        for group, keys in preserved.items():
            s.beginGroup(group)
            for key, value in keys.items():
                s.setValue(key, value)
            s.endGroup()

        s.sync()

    # ================================================================
    # ZIP extraction helpers (adversarial review fixes)
    # ================================================================

    def _validate_zip_entries(
        self, zf: zipfile.ZipFile, target_dir: Path
    ) -> None:
        """Zip Slip protection: проверить что записи не выходят за target."""
        target_resolved = target_dir.resolve()
        for entry in zf.namelist():
            entry_target = (target_dir / entry).resolve()
            if not str(entry_target).startswith(str(target_resolved)):
                raise ValueError(f"M_37: Zip Slip detected: {entry}")

    def _extract_with_ini_staging(
        self, zf: zipfile.ZipFile, profile_root: Path
    ) -> None:
        """Извлечь ZIP с защитой пользовательских данных.

        Защита:
        - QGIS3.ini: staging как .pending (применяется при следующем
          запуске через apply_pending_ini с сохранением [Projections])
        - qgis.db: пропускается (CRS управляются через Base_CRS.json,
          sync в Msm_4_19.sync_crs_from_json)
        """
        for entry in zf.namelist():
            if entry == "QGIS/QGIS3.ini":
                pending_path = profile_root / "QGIS" / "QGIS3.ini.pending"
                pending_path.parent.mkdir(parents=True, exist_ok=True)
                with open(pending_path, 'wb') as f:
                    f.write(zf.read(entry))
                log_info("M_37: QGIS3.ini staged as .pending")
            elif entry == "qgis.db":
                log_info("M_37: qgis.db пропущен (CRS из Base_CRS.json)")
            else:
                zf.extract(entry, profile_root)

    # ================================================================
    # Profile configuration (repo URL, plugin enabled, profiles.ini)
    # ================================================================

    def _write_repo_url_to_profile(self, profile_path: Path) -> None:
        """Записать repository URL в QGIS3.ini нового профиля.

        Использует один QSettings объект с единым sync() в конце,
        чтобы избежать проблем с множественными перезаписями INI файла.
        """
        try:
            ini_path = profile_path / "QGIS" / "QGIS3.ini"
            ini_path.parent.mkdir(parents=True, exist_ok=True)

            repo_key = f"app/plugin_repositories/{self.REPO_NAME}"

            s = QSettings(str(ini_path), QSettings.Format.IniFormat)
            s.setValue(f"{repo_key}/url", self.REPO_URL)
            s.setValue(f"{repo_key}/authcfg", "")
            s.setValue(f"{repo_key}/enabled", True)
            s.sync()

            # Верификация: проверить что URL реально записался
            s2 = QSettings(str(ini_path), QSettings.Format.IniFormat)
            written_url = s2.value(f"{repo_key}/url", "")
            if written_url == self.REPO_URL:
                log_info("M_37: Repo URL written to profile (verified)")
            else:
                log_warning(
                    f"M_37: Repo URL verification failed: "
                    f"expected '{self.REPO_URL}', got '{written_url}'"
                )
        except Exception as e:
            log_error(f"M_37 (_write_repo_url_to_profile): {e}")

    def _enable_plugin_in_profile(self, profile_path: Path) -> None:
        """Включить Daman_QGIS в PythonPlugins нового профиля."""
        try:
            ini_path = profile_path / "QGIS" / "QGIS3.ini"
            ini_path.parent.mkdir(parents=True, exist_ok=True)

            s = QSettings(str(ini_path), QSettings.Format.IniFormat)
            s.setValue(f"PythonPlugins/{PLUGIN_NAME}", True)
            s.sync()

            log_info("M_37: Plugin enabled in profile")
        except Exception as e:
            log_error(f"M_37 (_enable_plugin_in_profile): {e}")

    def _copy_plugin_to_profile(self, profile_path: Path) -> None:
        """Скопировать плагин из текущего профиля в Daman_QGIS."""
        try:
            # Источник: текущий плагин
            current_plugin = Path(__file__).parent.parent.parent
            # Назначение: python/plugins/Daman_QGIS в новом профиле
            target = profile_path / "python" / "plugins" / DAMAN_PROFILE_NAME

            if target.exists():
                shutil.rmtree(target, ignore_errors=True)

            shutil.copytree(
                current_plugin,
                target,
                ignore=shutil.ignore_patterns(*PROFILE_COPY_IGNORE),
            )
            log_info(f"M_37: Plugin copied to {target}")
        except Exception as e:
            log_error(f"M_37 (_copy_plugin_to_profile): {e}")

    def _write_profiles_ini(self, manager: object) -> None:
        """Установить Daman_QGIS как профиль по умолчанию.

        Использует API QgsUserProfileManager чтобы обновить
        и in-memory состояние, и profiles.ini. Прямая запись
        в файл через QSettings не работает -- QGIS при выходе
        перезаписывает profiles.ini из in-memory состояния менеджера,
        затирая изменения.
        """
        try:
            manager.setDefaultProfileName(DAMAN_PROFILE_NAME)  # type: ignore[union-attr]
            manager.setUserProfileSelectionPolicy(  # type: ignore[union-attr]
                Qgis.UserProfileSelectionPolicy.DefaultProfile
            )
            log_info("M_37: Default profile set to Daman_QGIS via API")
        except Exception as e:
            log_error(f"M_37 (_write_profiles_ini): {e}")
            # Fallback: прямая запись (может быть затёрта при выходе)
            try:
                profiles_root = Path(
                    QgsApplication.qgisSettingsDirPath()
                ).parent
                profiles_ini = profiles_root / "profiles.ini"
                s = QSettings(str(profiles_ini), QSettings.Format.IniFormat)
                s.setValue("core/defaultProfile", DAMAN_PROFILE_NAME)
                s.setValue("core/selectionPolicy", 1)
                s.sync()
                log_warning("M_37: profiles.ini written via fallback (QSettings)")
            except Exception as e2:
                log_error(f"M_37 (_write_profiles_ini fallback): {e2}")

    def _switch_to_daman_profile(self, manager: object) -> None:
        """Переключить QGIS на профиль Daman_QGIS."""
        try:
            manager.loadUserProfile(DAMAN_PROFILE_NAME)  # type: ignore[union-attr]
            log_info("M_37: Loading Daman_QGIS profile...")

            # Закрыть текущий экземпляр через небольшую задержку
            from qgis.PyQt.QtWidgets import QApplication
            QTimer.singleShot(1500, QApplication.quit)
        except Exception as e:
            log_error(f"M_37 (_switch_to_daman_profile): {e}")

    # ================================================================
    # Plugin version sync (default -> Daman_QGIS)
    # ================================================================

    def _sync_if_version_newer(self, manager: object) -> bool:
        """Синхронизировать плагин если версия в default новее."""
        try:
            # Пути к плагинам
            current_root = Path(QgsApplication.qgisSettingsDirPath())
            profiles_root = current_root.parent

            default_plugin = (
                current_root / "python" / "plugins" / DAMAN_PROFILE_NAME
            )
            daman_plugin = (
                profiles_root
                / DAMAN_PROFILE_NAME
                / "python"
                / "plugins"
                / DAMAN_PROFILE_NAME
            )

            if not default_plugin.exists() or not daman_plugin.exists():
                return False

            default_version = self._read_plugin_version(default_plugin)
            daman_version = self._read_plugin_version(daman_plugin)

            if self._parse_version(default_version) > self._parse_version(
                daman_version
            ):
                self._atomic_sync_plugin(default_plugin, daman_plugin)
                log_info(
                    f"M_37: Synced plugin {default_version} -> Daman_QGIS"
                )
                return True

            return False
        except Exception as e:
            log_error(f"M_37 (_sync_if_version_newer): {e}")
            return False

    def _read_plugin_version(self, plugin_path: Path) -> str:
        """Прочитать version из metadata.txt плагина."""
        metadata = plugin_path / "metadata.txt"
        if not metadata.exists():
            return "0.0.0"
        try:
            with open(metadata, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('version='):
                        return line.split('=', 1)[1].strip()
        except Exception:
            pass
        return "0.0.0"

    def _parse_version(self, version_str: str) -> Tuple[int, ...]:
        """Парсинг строки версии в числовой кортеж.

        ВАЖНО: строковое сравнение "0.9.319" > "0.9.32" = False
        (лексикографическое: '1' < '2'). Кортежное (0,9,319) > (0,9,32) = True.
        """
        try:
            return tuple(int(x) for x in version_str.strip().split('.'))
        except (ValueError, AttributeError):
            return (0, 0, 0)

    def _atomic_sync_plugin(self, src: Path, dst: Path) -> None:
        """Атомарная синхронизация плагина с rollback.

        Паттерн: copy -> temp, rename old, rename new, delete old.
        При ошибке -- восстановление старой версии.
        """
        temp_path = dst.with_name(f"{DAMAN_PROFILE_NAME}_new")
        old_path = dst.with_name(f"{DAMAN_PROFILE_NAME}_old")

        try:
            # Очистка предыдущих temp (на случай неудачного прошлого sync)
            if temp_path.exists():
                shutil.rmtree(temp_path, ignore_errors=True)
            if old_path.exists():
                shutil.rmtree(old_path, ignore_errors=True)

            # 1. Copy to temp
            shutil.copytree(
                src,
                temp_path,
                ignore=shutil.ignore_patterns(*PROFILE_COPY_IGNORE),
            )
            # 2. Rename old (reversible)
            if dst.exists():
                dst.rename(old_path)
            # 3. Rename new to target
            temp_path.rename(dst)
            # 4. Clean up old
            shutil.rmtree(old_path, ignore_errors=True)
        except Exception as e:
            # Rollback: restore old if new failed
            if old_path.exists() and not dst.exists():
                old_path.rename(dst)
            if temp_path.exists():
                shutil.rmtree(temp_path, ignore_errors=True)
            log_error(f"M_37 (_atomic_sync_plugin): {e}")

    # ================================================================
    # Wrong profile warning
    # ================================================================

    def _show_wrong_profile_warning(self) -> None:
        """Предупреждение о запуске в неизвестном профиле."""
        from qgis.utils import iface  # type: ignore[import-untyped]

        current = Path(QgsApplication.qgisSettingsDirPath()).name
        iface.messageBar().pushMessage(
            PLUGIN_NAME,
            f"Плагин запущен в профиле '{current}'. "
            f"Рекомендуется использовать профиль '{DAMAN_PROFILE_NAME}'.",
            Qgis.MessageLevel.Warning,
            duration=10,
        )
