# -*- coding: utf-8 -*-
"""
Fsm_5_1_3_CertificateChecker - Проверка корневых сертификатов Минцифры РФ

Проверяет наличие установленных сертификатов Минцифры в хранилище Windows
"""

import sys
import subprocess
from typing import Dict, Any, List, Tuple

from qgis.core import Qgis
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error


class CertificateChecker:
    """Проверка корневых сертификатов Минцифры"""

    # Ключевые слова для поиска сертификатов Минцифры
    CERT_KEYWORDS = [
        'минцифры', 'минцифр', 'mincifr', 'mintsifr',
        'министерство цифрового развития',
        'russian trusted', 'российский', 'россия', 'russia',
        'головной удостоверяющий центр', 'гуц', 'gук', 'guc',
        'аккредитованный удостоверяющий центр',
        'ministry of digital', 'digital development',
        'minsvyaz', 'roskomnadzor', 'gosuslugi', 'esia',
        'ca fk', 'ca guk', 'ca guc', 'ca1 guk', 'ca2 guk',
        'root ca guk', 'sub ca guk'
    ]

    # Конкретные названия сертификатов
    SPECIFIC_CERTS = [
        'russian trusted root ca', 'russian trusted sub ca',
        'министерство цифрового развития',
        'головной удостоверяющий центр',
        'ca guk', 'ca1 guk', 'ca2 guk', 'root ca guk', 'sub ca guk',
        'russian trusted ca', 'ministry of digital development',
        'аккредитованный удостоверяющий центр "фк"',
        'ca fk nuc rf', 'ca fk',
        'gost 2001 ca', 'gost 2012 ca',
        'crypto-pro ca', 'cryptopro ca'
    ]

    @staticmethod
    def parse_certutil_output(output: str) -> Tuple[List[str], List[str]]:
        """
        Парсинг вывода certutil для поиска сертификатов Минцифры

        Args:
            output: Вывод команды certutil

        Returns:
            tuple: (найденные_ключевые_слова, найденные_конкретные_сертификаты)
        """
        output_lower = output.lower()
        found_keywords = []
        found_specific = []

        for keyword in CertificateChecker.CERT_KEYWORDS:
            if keyword in output_lower:
                found_keywords.append(keyword)

        for cert_name in CertificateChecker.SPECIFIC_CERTS:
            if cert_name in output_lower:
                found_specific.append(cert_name)

        return found_keywords, found_specific

    @staticmethod
    def check_cert_store(user_mode: bool = True) -> Tuple[bool, str, List[str]]:
        """
        Проверка хранилища сертификатов Windows

        Args:
            user_mode: True для пользовательского хранилища, False для общего

        Returns:
            tuple: (найдены_сертификаты, сообщение, список_найденных)
        """
        # Формируем команду
        if user_mode:
            command = ['certutil', '-user', '-store', 'ROOT']
            store_name = "пользователь"
        else:
            command = ['certutil', '-store', 'ROOT']
            store_name = "общее"

        # Выполняем проверку
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding='cp866',
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )

        if result.returncode == 0:
            output = result.stdout
            found_keywords, found_specific = CertificateChecker.parse_certutil_output(output)

            if found_keywords or found_specific:
                if found_specific:
                    message = f'Найдены сертификаты ({store_name}): {", ".join(found_specific[:3])}'
                    return True, message, found_specific
                else:
                    message = f'Обнаружены ключевые слова ({store_name}): {", ".join(found_keywords[:3])}'
                    return True, message, found_keywords
            else:
                return False, f'Сертификаты не найдены ({store_name})', []
        else:
            return False, f'Не удалось проверить хранилище ({store_name})', []

    @staticmethod
    def check_certificates() -> Dict[str, Any]:
        """
        Проверка наличия корневых сертификатов Минцифры

        Returns:
            dict: Информация о сертификатах
                - certificates_installed: bool
                - check_performed: bool
                - os_supported: bool
                - message: str
                - found_certificates: list
        """
        cert_info = {
            'certificates_installed': False,
            'check_performed': False,
            'os_supported': True,
            'message': '',
            'found_certificates': []
        }

        # Проверка только для Windows
        if sys.platform != 'win32':
            cert_info['os_supported'] = False
            cert_info['message'] = 'Проверка сертификатов доступна только для Windows'
            return cert_info

        # Сначала проверяем пользовательское хранилище
        found_user, message_user, certs_user = CertificateChecker.check_cert_store(user_mode=True)

        if found_user:
            cert_info['certificates_installed'] = True
            cert_info['message'] = message_user
            cert_info['found_certificates'].extend(certs_user)
        else:
            # Если не нашли в пользовательском, проверяем общее
            found_machine, message_machine, certs_machine = CertificateChecker.check_cert_store(user_mode=False)

            if found_machine:
                cert_info['certificates_installed'] = True
                cert_info['message'] = message_machine
                cert_info['found_certificates'].extend(certs_machine)
            else:
                cert_info['message'] = 'Сертификаты Минцифры не найдены'

        cert_info['check_performed'] = True

        # Логируем результат
        log_info(f"F_5_1: Проверка сертификатов - найдено: {cert_info['certificates_installed']}, "
                 f"сертификаты: {cert_info['found_certificates'][:3] if cert_info['found_certificates'] else 'нет'}")

        return cert_info
