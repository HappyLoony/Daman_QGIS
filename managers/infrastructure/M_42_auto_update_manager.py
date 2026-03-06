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
    UPDATE_DEFAULT_CHANNEL,
)

__all__ = ['AutoUpdateManager']


class AutoUpdateManager:
    """Автоматическое обновление плагина при запуске QGIS."""

    _SETTINGS_CHANNEL = "Daman_QGIS/update_channel"
    _SETTINGS_IN_PROGRESS = "Daman_QGIS/update_in_progress"
    _SETTINGS_PREV_VERSION = "Daman_QGIS/update_previous_version"
    _SETTINGS_LAST_CHECK = "Daman_QGIS/update_last_check"

    def check_and_update(self) -> bool:
        """Проверить наличие обновления и установить.

        Returns:
            True  -- обновление установлено, вызывающий должен запланировать reload.
            False -- обновление не нужно или не удалось.
        """
        if self._is_crash_recovery():
            return False

        channel = self._get_channel()
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

        # Записать время последней проверки
        from datetime import datetime
        settings = QgsSettings()
        settings.setValue(
            self._SETTINGS_LAST_CHECK,
            datetime.now().isoformat()
        )

        log_info(
            f"M_42: Обновление {remote_version} установлено успешно"
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

    def _get_channel(self) -> str:
        """Получить канал обновления из QgsSettings."""
        settings = QgsSettings()
        channel = settings.value(
            self._SETTINGS_CHANNEL,
            UPDATE_DEFAULT_CHANNEL,
            type=str
        )
        if channel not in ("stable", "beta"):
            channel = UPDATE_DEFAULT_CHANNEL
        return channel

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

    def _is_newer(self, remote: str, local: str) -> bool:
        """Сравнить версии (tuple comparison).

        '0.9.500' > '0.9.499' -> True
        '0.9.499' == '0.9.499' -> False
        """
        try:
            remote_tuple = tuple(int(x) for x in remote.split('.'))
            local_tuple = tuple(int(x) for x in local.split('.'))
            return remote_tuple > local_tuple
        except (ValueError, AttributeError):
            log_warning(
                f"M_42: Невозможно сравнить версии: "
                f"remote={remote}, local={local}"
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
        """Извлечь ZIP в директорию плагинов.

        Последовательность:
        1. Установить флаг update_in_progress
        2. Сохранить предыдущую версию
        3. Извлечь ZIP (перезаписывая файлы)
        4. Очистить __pycache__
        5. Снять флаг update_in_progress
        """
        settings = QgsSettings()
        parent_dir = os.path.dirname(PLUGIN_DIR)

        try:
            # Флаг crash recovery
            settings.setValue(self._SETTINGS_IN_PROGRESS, True)
            settings.setValue(
                self._SETTINGS_PREV_VERSION, PLUGIN_VERSION
            )

            # Извлечение (ZIP содержит Daman_QGIS/ как корневую папку)
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                zf.extractall(parent_dir)

            # Очистка __pycache__
            self._clean_pycache(PLUGIN_DIR)

            # Снять флаг
            settings.setValue(self._SETTINGS_IN_PROGRESS, False)
            return True

        except Exception as e:
            log_error(f"M_42 (_install): {e}")
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
