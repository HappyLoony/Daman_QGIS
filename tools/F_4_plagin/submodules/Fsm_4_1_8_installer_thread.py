# -*- coding: utf-8 -*-
"""
Fsm_4_1_8_InstallerThread - Координатор установки всех компонентов

Поток для установки Python библиотек, шрифтов, сертификатов и починки сети
"""

from typing import Dict, Optional

from qgis.PyQt.QtCore import QThread, pyqtSignal

from .Fsm_4_1_4_pip_installer import PipInstaller
from .Fsm_4_1_5_font_installer import FontInstaller
from .Fsm_4_1_6_cert_installer import CertificateInstaller
from .Fsm_4_1_9_certifi_checker import CertifiChecker


class DependencyInstallerThread(QThread):
    """Поток для установки всех зависимостей"""

    progress = pyqtSignal(str)  # Текстовое сообщение
    progress_percent = pyqtSignal(int, int)  # (текущий, всего) для прогресс-бара
    finished = pyqtSignal(bool, str)

    def __init__(self, packages, install_paths, fonts_to_install=None, fonts_dir=None,
                 install_certificates=False, cert_install_mode='user', configure_ssl=False,
                 fix_network: bool = False, network_issues: Optional[Dict] = None,
                 network_fix_stage: int = 1):
        """
        Инициализация потока установки

        Args:
            packages: Словарь пакетов Python для установки
            install_paths: Пути установки (включая user_site)
            fonts_to_install: Список шрифтов для установки
            fonts_dir: Путь к папке со шрифтами
            install_certificates: Устанавливать ли сертификаты Минцифры
            cert_install_mode: Режим установки сертификатов ('user' или 'admin')
            configure_ssl: Настроить ли SSL через certifi
            fix_network: Выполнять ли починку сети
            network_issues: Найденные сетевые проблемы (Dict[str, DiagResult])
            network_fix_stage: Этап починки (1/2/3)
        """
        super().__init__()
        self.packages = packages
        self.install_paths = install_paths
        self.fonts_to_install = fonts_to_install or []
        self.fonts_dir = fonts_dir
        self.install_certificates = install_certificates
        self.cert_install_mode = cert_install_mode
        self.configure_ssl = configure_ssl
        self.fix_network = fix_network
        self.network_issues = network_issues
        self.network_fix_stage = network_fix_stage
    def run(self):
        """Установка пакетов через pip, шрифтов, сертификатов и настройка SSL"""
        errors = []

        # Подсчитываем общее количество шагов
        total_steps = len(self.packages)
        if self.install_certificates:
            total_steps += 1
        if self.fonts_to_install:
            total_steps += len(self.fonts_to_install)
        if self.configure_ssl:
            total_steps += 1
        if self.fix_network:
            total_steps += 1

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

            # Проверяем доступность pip (с автоматическим bootstrap через ensurepip)
            if not pip_installer.ensure_pip_available():
                msg = (
                    f"pip не доступен в Python: {pip_installer.python_exe}. "
                    f"Для OSGeo4W: откройте OSGeo4W Shell и выполните "
                    f"'python -m ensurepip --default-pip'"
                )
                self.progress.emit(f"X {msg}")
                errors.append(msg)
                # Пропускаем установку пакетов, переходим к шрифтам/сертификатам
                current_step += len(self.packages)
                self.progress_percent.emit(current_step, total_steps)
            else:
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

        # 4. Настраиваем SSL через certifi если нужно
        if self.configure_ssl:
            current_step += 1
            self.progress_percent.emit(current_step, total_steps)
            self.progress.emit("--- Настройка SSL (certifi) ---")

            if CertifiChecker.configure_certifi_ssl():
                self.progress.emit("OK SSL настроен через certifi")
            else:
                errors.append("Не удалось настроить SSL через certifi")
                self.progress.emit("X Ошибка настройки SSL")

        # 5. Починка сети если нужно
        network_needs_reboot = False
        if self.fix_network and self.network_issues:
            current_step += 1
            self.progress_percent.emit(current_step, total_steps)
            self.progress.emit("--- Починка сетевых проблем ---")

            from .Fsm_4_1_10_network_doctor import NetworkDoctor
            doctor = NetworkDoctor(progress_callback=self.progress.emit)
            fix_results = doctor.fix_issues(
                self.network_issues, stage=self.network_fix_stage
            )

            for fix_result in fix_results:
                if fix_result.success:
                    self.progress.emit(f"OK {fix_result.name}: {fix_result.message}")
                else:
                    self.progress.emit(f"X {fix_result.name}: {fix_result.message}")
                    errors.append(f"Сеть ({fix_result.name}): {fix_result.message}")
                if fix_result.needs_reboot:
                    network_needs_reboot = True

        # Финальный прогресс
        self.progress_percent.emit(total_steps, total_steps)

        # Проверяем наличие .old файлов (ожидание перезапуска)
        pending_restart = PipInstaller.has_pending_restart()
        pending_count = PipInstaller.count_pending_restart_files() if pending_restart else 0

        if pending_restart:
            self.progress.emit(
                f"Обнаружено {pending_count} файлов, ожидающих перезапуска QGIS (.old)"
            )

        # Проверяем результат
        if errors:
            if pending_restart:
                restart_note = (
                    f"Некоторые обновления ({pending_count} файлов) будут применены "
                    f"после перезапуска QGIS."
                )
                self.finished.emit(False, restart_note + "\n" + "\n".join(errors))
            else:
                self.finished.emit(False, "\n".join(errors))
        else:
            if network_needs_reboot:
                self.finished.emit(
                    True,
                    "Починка выполнена. Требуется перезагрузка компьютера "
                    "для завершения сброса сетевого стека."
                )
            elif pending_restart:
                self.finished.emit(
                    True,
                    f"Компоненты установлены. "
                    f"Перезапустите QGIS для завершения обновления "
                    f"({pending_count} файлов ожидают перезапуска)."
                )
            else:
                self.finished.emit(True, "Все компоненты успешно установлены!")
