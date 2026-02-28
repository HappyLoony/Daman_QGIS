# -*- coding: utf-8 -*-
"""
Fsm_4_1_9_CertifiChecker - Проверка SSL сертификатов через certifi

Проверяет наличие и конфигурацию certifi для HTTPS соединений с GitHub и PyPI.
Необходимо для корректной работы обновлений плагина через QGIS Plugin Manager.
"""

import os
import sys
import ssl
from typing import Dict, Any, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

from Daman_QGIS.utils import log_info, log_warning, log_error


class CertifiChecker:
    """Проверка SSL сертификатов через certifi"""

    # URL для тестирования HTTPS
    TEST_URLS = [
        'https://github.com',
        'https://raw.githubusercontent.com',
        'https://pypi.org',
    ]

    @staticmethod
    def check_certifi_installed() -> Dict[str, Any]:
        """
        Проверка наличия библиотеки certifi

        Returns:
            dict: Информация о certifi
                - installed: bool
                - version: str или None
                - ca_bundle_path: str или None
        """
        result = {
            'installed': False,
            'version': None,
            'ca_bundle_path': None
        }

        try:
            import certifi
            result['installed'] = True
            result['version'] = getattr(certifi, '__version__', 'unknown')
            result['ca_bundle_path'] = certifi.where()
        except ImportError:
            pass

        return result

    @staticmethod
    def check_ssl_env_configured() -> Dict[str, Any]:
        """
        Проверка конфигурации переменных окружения SSL

        Returns:
            dict: Информация о конфигурации
                - ssl_cert_file: str или None
                - requests_ca_bundle: str или None
                - configured: bool
        """
        ssl_cert_file = os.environ.get('SSL_CERT_FILE')
        requests_ca_bundle = os.environ.get('REQUESTS_CA_BUNDLE')

        return {
            'ssl_cert_file': ssl_cert_file,
            'requests_ca_bundle': requests_ca_bundle,
            'configured': bool(ssl_cert_file or requests_ca_bundle)
        }

    @staticmethod
    def test_https_connection(url: str, timeout: int = 10) -> Dict[str, Any]:
        """
        Тестирование HTTPS соединения.

        Проверяет два транспорта:
        1. urllib + certifi SSL context (строгая проверка)
        2. requests (fallback -- реальный транспорт плагина)

        Антивирусы (Kaspersky, ESET) внедряют свой CA для MITM-перехвата HTTPS.
        Этот CA есть в системном хранилище, но отсутствует в certifi bundle.
        Поэтому urllib + certifi может падать, а requests через системные CA работает.

        Args:
            url: URL для тестирования
            timeout: Таймаут в секундах

        Returns:
            dict: Результат теста
                - success: bool -- True если хотя бы один транспорт работает
                - error: str или None
                - ssl_version: str или None
                - urllib_ok: bool -- urllib + certifi работает
                - requests_ok: bool -- requests работает
        """
        result: Dict[str, Any] = {
            'success': False,
            'error': None,
            'ssl_version': None,
            'urllib_ok': False,
            'requests_ok': False,
        }

        # --- 1. Тест urllib + certifi (строгий) ---
        urllib_error = None
        try:
            try:
                import certifi
                ssl_context = ssl.create_default_context(cafile=certifi.where())
            except ImportError:
                ssl_context = ssl.create_default_context()

            request = Request(url, headers={'User-Agent': 'QGIS-Plugin/1.0'})
            with urlopen(request, timeout=timeout, context=ssl_context) as response:
                if response.status == 200:
                    result['urllib_ok'] = True
                    result['ssl_version'] = ssl.OPENSSL_VERSION

        except ssl.SSLCertVerificationError as e:
            urllib_error = f"SSL Certificate Error: {e}"
        except URLError as e:
            urllib_error = f"Connection Error: {e.reason}"
        except Exception as e:
            urllib_error = str(e)

        # --- 2. Тест requests (реальный транспорт плагина) ---
        try:
            import requests as req_lib
            resp = req_lib.head(url, timeout=timeout,
                               headers={'User-Agent': 'QGIS-Plugin/1.0'})
            if resp.status_code < 400:
                result['requests_ok'] = True
                if not result['ssl_version']:
                    result['ssl_version'] = ssl.OPENSSL_VERSION
        except Exception:
            pass

        # --- Итоговый вердикт ---
        if result['urllib_ok']:
            result['success'] = True
        elif result['requests_ok']:
            # urllib падает (антивирус MITM), но requests работает -- плагин в норме
            result['success'] = True
            result['error'] = (
                f"urllib SSL blocked (antivirus MITM?): {urllib_error}; "
                "requests OK -- plugin API работает"
            )
        else:
            result['error'] = urllib_error

        return result

    @staticmethod
    def configure_certifi_ssl() -> bool:
        """
        Настройка SSL через certifi

        Устанавливает переменные окружения SSL_CERT_FILE и REQUESTS_CA_BUNDLE
        для использования сертификатов из certifi.

        Returns:
            bool: True если настройка успешна
        """
        try:
            import certifi
            ca_bundle = certifi.where()

            if not os.path.exists(ca_bundle):
                log_error(f"Fsm_4_1_9: CA bundle не найден: {ca_bundle}")
                return False

            # Устанавливаем переменные окружения
            os.environ['SSL_CERT_FILE'] = ca_bundle
            os.environ['REQUESTS_CA_BUNDLE'] = ca_bundle

            log_info(f"Fsm_4_1_9: SSL настроен через certifi: {ca_bundle}")
            return True

        except ImportError:
            log_error("Fsm_4_1_9: certifi не установлен")
            return False
        except Exception as e:
            log_error(f"Fsm_4_1_9: Ошибка настройки SSL: {e}")
            return False

    @staticmethod
    def check_ssl_status() -> Dict[str, Any]:
        """
        Полная проверка статуса SSL

        Returns:
            dict: Полная информация о SSL
                - certifi: dict (installed, version, ca_bundle_path)
                - env_config: dict (ssl_cert_file, requests_ca_bundle, configured)
                - github_test: dict (success, error, urllib_ok, requests_ok)
                - status: str ('ok', 'warning', 'error', 'needs_config', 'needs_install')
                - message: str
        """
        result: Dict[str, Any] = {
            'certifi': CertifiChecker.check_certifi_installed(),
            'env_config': CertifiChecker.check_ssl_env_configured(),
            'github_test': {'success': False, 'error': None},
            'status': 'needs_install',
            'message': ''
        }

        # Если certifi не установлен
        if not result['certifi']['installed']:
            result['status'] = 'needs_install'
            result['message'] = 'certifi не установлен'
            log_warning("Fsm_4_1_9: certifi не установлен")
            return result

        # Тестируем соединение с GitHub
        result['github_test'] = CertifiChecker.test_https_connection('https://github.com')
        test = result['github_test']

        if test['success'] and test.get('urllib_ok'):
            # Оба транспорта работают
            result['status'] = 'ok'
            result['message'] = 'SSL работает корректно'
            log_info("Fsm_4_1_9: SSL работает корректно")
        elif test['success'] and test.get('requests_ok') and not test.get('urllib_ok'):
            # requests работает, urllib нет -- антивирус MITM (Kaspersky и др.)
            result['status'] = 'warning'
            result['message'] = (
                'SSL: антивирус блокирует urllib (MITM), '
                'но requests работает -- API плагина в норме'
            )
            log_info(f"Fsm_4_1_9: {result['message']}")
        elif not test['success']:
            # Оба транспорта не работают
            if result['env_config']['configured']:
                result['status'] = 'error'
                result['message'] = (
                    f"SSL настроен, но соединение не работает: "
                    f"{test.get('error', 'unknown')}"
                )
                log_warning(f"Fsm_4_1_9: {result['message']}")
            else:
                result['status'] = 'needs_config'
                result['message'] = 'Требуется настройка SSL через certifi'
                log_info("Fsm_4_1_9: Требуется настройка SSL")

        return result
