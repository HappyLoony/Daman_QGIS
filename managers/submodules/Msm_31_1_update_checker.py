# -*- coding: utf-8 -*-
"""
Msm_31_1_UpdateChecker - Проверка обновлений плагина.

Проверяет наличие новой версии через plugins.xml на GitHub.
Поддерживает beta и stable каналы обновлений.

Зависимости:
- requests (HTTP запросы)
- xml.etree.ElementTree (парсинг plugins.xml)
"""

from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass
from xml.etree import ElementTree as ET
import re

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from ...utils import log_info, log_error, log_warning
from ...constants import (
    PLUGIN_VERSION,
    UPDATE_CHECK_TIMEOUT,
    UPDATE_BETA_URL,
    UPDATE_STABLE_URL
)


@dataclass
class UpdateInfo:
    """Информация об обновлении."""
    available: bool
    current_version: str
    latest_version: str
    download_url: str = ""
    changelog: str = ""
    is_beta: bool = False

    @property
    def version_tuple(self) -> Tuple[int, ...]:
        """Текущая версия как tuple для сравнения."""
        return self._parse_version(self.current_version)

    @property
    def latest_tuple(self) -> Tuple[int, ...]:
        """Новая версия как tuple для сравнения."""
        return self._parse_version(self.latest_version)

    @staticmethod
    def _parse_version(version: str) -> Tuple[int, ...]:
        """Парсинг версии X.Y.Z в tuple."""
        try:
            parts = re.findall(r'\d+', version)
            return tuple(int(p) for p in parts[:3])
        except (ValueError, AttributeError):
            return (0, 0, 0)


class UpdateChecker:
    """Проверка обновлений плагина через plugins.xml."""

    MODULE_ID = "Msm_31_1"

    def __init__(self, check_beta: bool = False):
        """
        Инициализация.

        Args:
            check_beta: Проверять beta канал (True) или stable (False)
        """
        self.check_beta = check_beta
        self.current_version = PLUGIN_VERSION
        self._last_check_result: Optional[UpdateInfo] = None

    def check_for_updates(self) -> UpdateInfo:
        """
        Проверка наличия обновлений.

        Returns:
            UpdateInfo с информацией об обновлении
        """
        if not REQUESTS_AVAILABLE:
            log_warning(f"{self.MODULE_ID}: requests не установлен, проверка обновлений невозможна")
            return UpdateInfo(
                available=False,
                current_version=self.current_version,
                latest_version=self.current_version
            )

        url = UPDATE_BETA_URL if self.check_beta else UPDATE_STABLE_URL

        try:
            log_info(f"{self.MODULE_ID}: Проверка обновлений: {url}")

            response = requests.get(url, timeout=UPDATE_CHECK_TIMEOUT)
            response.raise_for_status()

            # Парсим XML
            update_info = self._parse_plugins_xml(response.text)
            self._last_check_result = update_info

            if update_info.available:
                log_info(f"{self.MODULE_ID}: Доступно обновление: {update_info.latest_version}")
            else:
                log_info(f"{self.MODULE_ID}: Установлена последняя версия: {self.current_version}")

            return update_info

        except requests.Timeout:
            log_warning(f"{self.MODULE_ID}: Таймаут при проверке обновлений")
        except requests.RequestException as e:
            log_warning(f"{self.MODULE_ID}: Ошибка сети: {e}")
        except ET.ParseError as e:
            log_error(f"{self.MODULE_ID}: Ошибка парсинга XML: {e}")
        except Exception as e:
            log_error(f"{self.MODULE_ID}: Неожиданная ошибка: {e}")

        return UpdateInfo(
            available=False,
            current_version=self.current_version,
            latest_version=self.current_version
        )

    def _parse_plugins_xml(self, xml_content: str) -> UpdateInfo:
        """
        Парсинг plugins.xml и извлечение информации об обновлении.

        Args:
            xml_content: Содержимое plugins.xml

        Returns:
            UpdateInfo
        """
        root = ET.fromstring(xml_content)

        # Ищем плагин Daman QGIS
        plugin = root.find(".//pyqgis_plugin[@name='Daman QGIS']")

        if plugin is None:
            log_warning(f"{self.MODULE_ID}: Плагин не найден в plugins.xml")
            return UpdateInfo(
                available=False,
                current_version=self.current_version,
                latest_version=self.current_version
            )

        # Извлекаем данные
        latest_version = plugin.get('version', '0.0.0')
        download_url = plugin.findtext('download_url', '')
        about = plugin.findtext('about', '')
        experimental = plugin.findtext('experimental', 'False').lower() == 'true'

        # Сравниваем версии
        current_tuple = UpdateInfo._parse_version(self.current_version)
        latest_tuple = UpdateInfo._parse_version(latest_version)

        available = latest_tuple > current_tuple

        return UpdateInfo(
            available=available,
            current_version=self.current_version,
            latest_version=latest_version,
            download_url=download_url,
            changelog=about,
            is_beta=experimental
        )

    @property
    def last_result(self) -> Optional[UpdateInfo]:
        """Последний результат проверки."""
        return self._last_check_result
