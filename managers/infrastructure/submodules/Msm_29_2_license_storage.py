# -*- coding: utf-8 -*-
"""
Msm_29_2_LicenseStorage - Хранение API ключа лицензии.

Хранит только api_key через QSettings.
JWT токены хранятся в RAM (Msm_30_1_TokenManager).
Вся валидация выполняется на сервере (fail-closed).
"""

import os
from pathlib import Path
from typing import Optional

from qgis.core import QgsApplication, QgsSettings

from Daman_QGIS.utils import log_info, log_error


class LicenseStorage:
    """
    Хранение API ключа лицензии через QSettings.

    Единственная локально хранимая информация - api_key,
    чтобы пользователь не вводил его при каждом запуске QGIS.
    """

    SETTINGS_PREFIX = "Daman_QGIS/license/"

    def __init__(self):
        self._settings: Optional[QgsSettings] = None

    def initialize(self) -> bool:
        """Инициализация хранилища."""
        try:
            self._settings = QgsSettings()

            # Очистка старых файлов (миграция с AES формата)
            self._cleanup_legacy_files()

            return True

        except Exception as e:
            log_error(f"Msm_29_2: Failed to initialize storage: {e}")
            return False

    def _cleanup_legacy_files(self):
        """Удаление файлов от старого формата хранения (AES-256-GCM)."""
        try:
            profile_path = Path(QgsApplication.qgisSettingsDirPath())
            legacy_dir = profile_path / "Daman_QGIS" / "license"

            if not legacy_dir.exists():
                return

            for filename in ["license.dat", "public_key.pem", ".hwid"]:
                filepath = legacy_dir / filename
                if filepath.exists():
                    os.remove(filepath)
                    log_info(f"Msm_29_2: Removed legacy file: {filename}")

            # Удаляем пустую директорию
            if legacy_dir.exists() and not any(legacy_dir.iterdir()):
                legacy_dir.rmdir()

        except Exception as e:
            log_error(f"Msm_29_2: Failed to cleanup legacy files: {e}")

    # === API Key ===

    def has_api_key(self) -> bool:
        """Проверка наличия API ключа."""
        return bool(self.get_api_key())

    def get_api_key(self) -> Optional[str]:
        """Получение API ключа."""
        if not self._settings:
            return None
        value = self._settings.value(f"{self.SETTINGS_PREFIX}api_key", None)
        return str(value) if value else None

    def save_api_key(self, api_key: str):
        """Сохранение API ключа."""
        if self._settings:
            self._settings.setValue(f"{self.SETTINGS_PREFIX}api_key", api_key)

    # === Clear ===

    def clear(self):
        """Очистка всех данных лицензии."""
        if self._settings:
            self._settings.remove(self.SETTINGS_PREFIX)

        # Очистка старых файлов (на случай если остались)
        self._cleanup_legacy_files()
