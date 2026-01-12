# -*- coding: utf-8 -*-
"""
Fsm_5_1_8_InstallerThread - Координатор установки всех компонентов

Поток для установки Python библиотек, шрифтов и сертификатов
"""

from qgis.PyQt.QtCore import QThread, pyqtSignal

from .Fsm_5_1_4_pip_installer import PipInstaller
from .Fsm_5_1_5_font_installer import FontInstaller
from .Fsm_5_1_6_cert_installer import CertificateInstaller


class DependencyInstallerThread(QThread):
    """Поток для установки всех зависимостей"""

    progress = pyqtSignal(str)  # Текстовое сообщение
    progress_percent = pyqtSignal(int, int)  # (текущий, всего) для прогресс-бара
    finished = pyqtSignal(bool, str)

    def __init__(self, packages, install_paths, fonts_to_install=None, fonts_dir=None,
                 install_certificates=False, cert_install_mode='user'):
        """
        Инициализация потока установки

        Args:
            packages: Словарь пакетов Python для установки
            install_paths: Пути установки (включая user_site)
            fonts_to_install: Список шрифтов для установки
            fonts_dir: Путь к папке со шрифтами
            install_certificates: Устанавливать ли сертификаты
            cert_install_mode: Режим установки сертификатов ('user' или 'admin')
        """
        super().__init__()
        self.packages = packages
        self.install_paths = install_paths
        self.fonts_to_install = fonts_to_install or []
        self.fonts_dir = fonts_dir
        self.install_certificates = install_certificates
        self.cert_install_mode = cert_install_mode
    def run(self):
        """Установка пакетов через pip, шрифтов и сертификатов"""
        errors = []

        # Подсчитываем общее количество шагов
        total_steps = len(self.packages)
        if self.install_certificates:
            total_steps += 1
        if self.fonts_to_install:
            total_steps += len(self.fonts_to_install)

        current_step = 0

        # 1. Устанавливаем Python пакеты если есть
        if self.packages:
            self.progress.emit("--- Установка Python библиотек ---")

            # Устанавливаем пакеты по одному для отслеживания прогресса
            # PipInstaller использует изолированную папку dependencies автоматически
            pip_installer = PipInstaller(
                self.packages,
                progress_callback=self.progress.emit
            )

            for package_name, package_info in self.packages.items():
                current_step += 1
                self.progress_percent.emit(current_step, total_steps)

                # Формируем спецификацию пакета
                install_cmd = package_info.get('install_cmd', f'python -m pip install {package_name}')
                package_spec = install_cmd.split()[-1]

                if not pip_installer.install_package(package_name, package_spec):
                    errors.append(f"Ошибка при установке {package_name}")

            # Добавляем путь в sys.path
            pip_installer.ensure_dependencies_in_path()

        # 2. Устанавливаем сертификаты если нужно
        if self.install_certificates:
            current_step += 1
            self.progress_percent.emit(current_step, total_steps)
            self.progress.emit("--- Установка сертификатов Минцифры ---")

            cert_installer = CertificateInstaller(
                install_mode=self.cert_install_mode,
                progress_callback=self.progress.emit
            )

            success, message = cert_installer.install_all()
            if not success:
                errors.append(f"Сертификаты: {message}")

        # 3. Устанавливаем шрифты если есть
        if self.fonts_to_install and self.fonts_dir:
            self.progress.emit("--- Установка шрифтов ---")

            font_installer = FontInstaller(
                self.fonts_dir,
                self.fonts_to_install,
                progress_callback=self.progress.emit
            )

            # Устанавливаем шрифты по одному для отслеживания прогресса
            for font_name in self.fonts_to_install:
                current_step += 1
                self.progress_percent.emit(current_step, total_steps)

            fonts_installed, font_errors = font_installer.install_all()
            errors.extend(font_errors)

        # Финальный прогресс
        self.progress_percent.emit(total_steps, total_steps)

        # Проверяем результат
        if errors:
            self.finished.emit(False, "\n".join(errors))
        else:
            self.finished.emit(True, "Все компоненты успешно установлены!")
