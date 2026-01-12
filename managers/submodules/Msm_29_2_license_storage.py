# -*- coding: utf-8 -*-
"""
Msm_29_2_LicenseStorage - Хранение лицензионных данных.

Хранит:
- API ключ
- JWT токены (access, refresh)
- RS256 public key для offline валидации
- Hardware ID (fallback файл)
- Компоненты оборудования

Данные хранятся в профиле QGIS в обфусцированном виде.
"""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from qgis.core import QgsApplication

from ...utils import log_info, log_error


class LicenseStorage:
    """
    Хранение лицензионных данных.

    Данные хранятся в профиле QGIS в обфусцированном виде.
    """

    def __init__(self):
        self._storage_path: Optional[Path] = None
        self._data: Dict[str, Any] = {}

    def initialize(self) -> bool:
        """Инициализация хранилища."""
        try:
            profile_path = Path(QgsApplication.qgisSettingsDirPath())
            storage_dir = profile_path / "Daman_QGIS" / "license"
            storage_dir.mkdir(parents=True, exist_ok=True)

            self._storage_path = storage_dir / "license.dat"
            self._load()

            log_info("Msm_29_2: Storage initialized")
            return True

        except Exception as e:
            log_error(f"Msm_29_2: Failed to initialize storage: {e}")
            return False

    def _load(self):
        """Загрузка данных из файла."""
        if self._storage_path and self._storage_path.exists():
            try:
                # Данные хранятся в обфусцированном виде
                with open(self._storage_path, "rb") as f:
                    encrypted = f.read()

                decrypted = self._deobfuscate(encrypted)
                self._data = json.loads(decrypted)

            except Exception as e:
                log_error(f"Msm_29_2: Failed to load license data: {e}")
                self._data = {}

    def _save(self):
        """Сохранение данных в файл."""
        if self._storage_path:
            try:
                json_data = json.dumps(self._data, ensure_ascii=False)
                encrypted = self._obfuscate(json_data)

                with open(self._storage_path, "wb") as f:
                    f.write(encrypted)

            except Exception as e:
                log_error(f"Msm_29_2: Failed to save license data: {e}")

    def _obfuscate(self, data: str) -> bytes:
        """
        Обфускация данных.

        Простое XOR шифрование - не криптографически стойкое,
        но достаточное для защиты от случайного просмотра.
        """
        key = b"DamanQGIS2025Key"
        data_bytes = data.encode('utf-8')
        result = bytearray()

        for i, byte in enumerate(data_bytes):
            result.append(byte ^ key[i % len(key)])

        return bytes(result)

    def _deobfuscate(self, data: bytes) -> str:
        """Деобфускация данных."""
        key = b"DamanQGIS2025Key"
        result = bytearray()

        for i, byte in enumerate(data):
            result.append(byte ^ key[i % len(key)])

        return result.decode('utf-8')

    # === API Key ===

    def has_api_key(self) -> bool:
        """Проверка наличия API ключа."""
        return bool(self._data.get("api_key"))

    def get_api_key(self) -> Optional[str]:
        """Получение API ключа."""
        return self._data.get("api_key")

    def save_api_key(self, api_key: str):
        """Сохранение API ключа."""
        self._data["api_key"] = api_key
        self._data["activated_at"] = datetime.utcnow().isoformat()
        self._save()

    # === JWT Tokens ===

    def get_access_token(self) -> Optional[str]:
        """Получение Access Token."""
        return self._data.get("access_token")

    def get_refresh_token(self) -> Optional[str]:
        """Получение Refresh Token."""
        return self._data.get("refresh_token")

    def get_access_expires_at(self) -> Optional[float]:
        """Время истечения Access Token."""
        return self._data.get("access_expires_at")

    def save_tokens(self, access_token: str, refresh_token: str, access_expires_at: Optional[float] = None):
        """Сохранение JWT токенов."""
        self._data["access_token"] = access_token
        self._data["refresh_token"] = refresh_token
        if access_expires_at:
            self._data["access_expires_at"] = access_expires_at
        self._save()

    def update_access_token(self, access_token: str, access_expires_at: Optional[float] = None):
        """Обновление только Access Token."""
        self._data["access_token"] = access_token
        if access_expires_at:
            self._data["access_expires_at"] = access_expires_at
        self._save()

    def clear_tokens(self):
        """Очистка токенов (при logout/deactivate)."""
        self._data.pop("access_token", None)
        self._data.pop("refresh_token", None)
        self._data.pop("access_expires_at", None)
        self._save()

    # === RS256 Public Key (для offline валидации JWT) ===

    def get_public_key(self) -> Optional[str]:
        """Получение RS256 public key для offline валидации."""
        if not self._storage_path:
            return None
        key_file = self._storage_path.parent / "public_key.pem"
        if key_file.exists():
            return key_file.read_text(encoding='utf-8')
        return None

    def save_public_key(self, public_key: str):
        """Сохранение RS256 public key."""
        if not self._storage_path:
            return
        key_file = self._storage_path.parent / "public_key.pem"
        key_file.write_text(public_key, encoding='utf-8')

    # === Hardware ID Fallback ===

    def get_fallback_hardware_id(self) -> Optional[str]:
        """Получение Hardware ID из fallback файла."""
        if not self._storage_path:
            return None
        hwid_file = self._storage_path.parent / ".hwid"
        if hwid_file.exists():
            return hwid_file.read_text(encoding='utf-8').strip()
        return None

    def save_fallback_hardware_id(self, hardware_id: str):
        """Сохранение Hardware ID в fallback файл."""
        if not self._storage_path:
            return
        hwid_file = self._storage_path.parent / ".hwid"
        hwid_file.write_text(hardware_id, encoding='utf-8')

    # === Hardware Components ===

    def get_hardware_components(self) -> Optional[Dict[str, str]]:
        """Получение сохранённых компонентов оборудования."""
        return self._data.get("hardware_components")

    def save_hardware_components(self, components: Dict[str, str]):
        """Сохранение компонентов оборудования."""
        self._data["hardware_components"] = components
        self._save()

    # === Verification Cache ===

    def get_last_verification(self) -> Optional[str]:
        """Время последней успешной проверки."""
        return self._data.get("last_verification")

    def save_last_verification(self):
        """Сохранение времени проверки."""
        self._data["last_verification"] = datetime.utcnow().isoformat()
        self._save()

    def has_valid_cache(self) -> bool:
        """
        Проверка валидности кэша.

        Если последняя успешная проверка была менее 24 часов назад,
        разрешаем работу даже при недоступности сервера.
        """
        last_check = self._data.get("last_verification")
        if not last_check:
            return False

        try:
            last_check_time = datetime.fromisoformat(last_check)
            cache_age = datetime.utcnow() - last_check_time
            return cache_age < timedelta(hours=24)
        except Exception:
            return False

    # === Clear All ===

    def clear(self):
        """Очистка всех данных."""
        self._data = {}
        if self._storage_path and self._storage_path.exists():
            os.remove(self._storage_path)
        # Удаляем также public key и hwid файлы
        if self._storage_path:
            for filename in ["public_key.pem", ".hwid"]:
                filepath = self._storage_path.parent / filename
                if filepath.exists():
                    os.remove(filepath)
