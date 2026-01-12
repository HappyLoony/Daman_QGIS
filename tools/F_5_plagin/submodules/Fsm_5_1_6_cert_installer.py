# -*- coding: utf-8 -*-
"""
Fsm_5_1_6_CertificateInstaller - Установка корневых сертификатов Минцифры РФ

Скачивает и устанавливает официальные сертификаты с сайта Минцифры
"""

import os
import shutil
import subprocess
import platform
import zipfile
from typing import List, Tuple, Callable, Optional

import requests

from Daman_QGIS.constants import REQUEST_TIMEOUT_TUPLE


class CertificateInstaller:
    """Установка сертификатов Минцифры"""

    # URL для скачивания сертификатов с официального сайта Минцифры
    CERT_URLS = {
        "Windows": "https://gu-st.ru/content/lending/windows_russian_trusted_root_ca.zip",
        "Darwin": "https://gu-st.ru/content/lending/russiantrustedca.zip",
        "Linux": "https://gu-st.ru/content/lending/linux_russian_trusted_root_ca_pem.zip"
    }

    def __init__(self, install_mode: str = 'user', progress_callback: Optional[Callable] = None):
        """
        Инициализация установщика сертификатов

        Args:
            install_mode: 'user' или 'admin' (для текущего пользователя или всех)
            progress_callback: Функция обратного вызова для отчета о прогрессе
        """
        self.install_mode = install_mode
        self.progress_callback = progress_callback
        self.download_dir = os.path.join(os.path.expanduser("~"), "cert_install_temp")
        self.os_type = platform.system()

    def emit_progress(self, message: str):
        """Отправить сообщение о прогрессе"""
        if self.progress_callback:
            self.progress_callback(message)
    def download_certificates(self) -> Tuple[bool, str]:
        """
        Скачивание архива с сертификатами

        Returns:
            tuple: (успешно, путь_к_архиву_или_сообщение_об_ошибке)
        """
        if self.os_type not in self.CERT_URLS:
            error_msg = f"Неподдерживаемая ОС для установки сертификатов: {self.os_type}"
            self.emit_progress(error_msg)
            return False, error_msg

        # Очищаем временную папку
        self.emit_progress("Подготовка временной папки...")
        if os.path.exists(self.download_dir):
            shutil.rmtree(self.download_dir)
        os.makedirs(self.download_dir, exist_ok=True)

        # Скачиваем архив
        url = self.CERT_URLS[self.os_type]
        zip_path = os.path.join(self.download_dir, os.path.basename(url))

        self.emit_progress(f"Скачивание сертификатов с официального сайта Минцифры...")
        self.emit_progress(f"URL: {url}")

        # timeout=(connect, read) - защита от зависания при проблемах с сетью
        response = requests.get(url, stream=True, timeout=REQUEST_TIMEOUT_TUPLE)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0

        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        self.emit_progress(f"Загружено: {downloaded}/{total_size} байт ({percent:.1f}%)")

        return True, zip_path
    def extract_certificates(self, zip_path: str) -> Tuple[bool, List[str]]:
        """
        Распаковка архива с сертификатами

        Args:
            zip_path: Путь к архиву

        Returns:
            tuple: (успешно, список_путей_к_сертификатам)
        """
        self.emit_progress("Распаковка архива с сертификатами...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(self.download_dir)

        # Ищем файлы сертификатов
        cert_files = []
        for root, _, files in os.walk(self.download_dir):
            for file in files:
                if file.lower().endswith(('.cer', '.crt')):
                    cert_files.append(os.path.join(root, file))

        if not cert_files:
            error_msg = "Не найдены файлы сертификатов в загруженном архиве"
            self.emit_progress(error_msg)
            raise RuntimeError(error_msg)

        self.emit_progress(f"Найдено сертификатов для установки: {len(cert_files)}")
        return True, cert_files
    def install_windows_certificates(self, cert_files: List[str]) -> Tuple[int, List[str]]:
        """
        Установка сертификатов в Windows

        Args:
            cert_files: Список путей к файлам сертификатов

        Returns:
            tuple: (количество_установленных, список_неудачных)
        """
        installed_count = 0
        failed_certs = []

        for cert_path in cert_files:
            cert_name = os.path.basename(cert_path)
            self.emit_progress(f"Установка сертификата: {cert_name}")

            try:
                if self.install_mode == 'user':
                    command = ['certutil.exe', '-user', '-addstore', '-f', 'ROOT', cert_path]
                else:
                    command = ['certutil.exe', '-addstore', '-f', 'ROOT', cert_path]

                result = subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding='cp866',
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                )

                self.emit_progress(f"✓ Успешно установлен: {cert_name}")
                installed_count += 1

            except subprocess.CalledProcessError as e:
                failed_certs.append(cert_name)
                self.emit_progress(f"✗ Ошибка установки {cert_name}: {e.stderr}")

        return installed_count, failed_certs

    def cleanup(self):
        """Очистка временных файлов"""
        self.emit_progress("Очистка временных файлов...")
        if os.path.exists(self.download_dir):
            shutil.rmtree(self.download_dir, ignore_errors=True)

    def install_all(self) -> Tuple[bool, str]:
        """
        Полная установка сертификатов (скачивание + установка + очистка)

        Returns:
            tuple: (успешно, сообщение)
        """
        self.emit_progress("\n=== Установка сертификатов Минцифры ===")

        # 1. Скачивание
        success, result = self.download_certificates()
        if not success:
            return False, result

        zip_path = result

        # 2. Распаковка
        success, cert_files = self.extract_certificates(zip_path)
        if not success:
            self.cleanup()
            return False, "Не удалось извлечь сертификаты"

        # 3. Установка (только для Windows)
        if self.os_type == "Windows":
            installed_count, failed_certs = self.install_windows_certificates(cert_files)

            if failed_certs:
                message = f"Не удалось установить {len(failed_certs)} из {len(cert_files)} сертификатов"
            else:
                mode_text = "для текущего пользователя" if self.install_mode == 'user' else "для всех пользователей"
                message = f"Все {len(cert_files)} сертификатов установлены {mode_text}"
                self.emit_progress(message)

            # 4. Очистка
            self.cleanup()

            return len(failed_certs) == 0, message
        else:
            message = f"Автоматическая установка для {self.os_type} пока не реализована. " \
                     f"Сертификаты загружены в: {self.download_dir}"
            self.emit_progress(message)
            return False, message
