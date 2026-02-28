# -*- coding: utf-8 -*-
"""
Fsm_4_1_7_DependencyTabWidget - Вкладка зависимостей для DiagnosticsDialog

Рефакторинг из DependencyCheckDialog(QDialog) -> DependencyTabWidget(QWidget).
Отображает статус зависимостей и управляет установкой/обновлением.
Координация и сетевая диагностика вынесены в Fsm_4_1_11 и Fsm_4_1_12.
"""

import sys
from typing import Dict, Optional, Any

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTextEdit, QGroupBox, QMessageBox, QProgressBar
)
from qgis.PyQt.QtCore import pyqtSignal

from .Fsm_4_1_1_dependency_checker import DependencyChecker
from .Fsm_4_1_2_font_checker import FontChecker
from .Fsm_4_1_3_cert_checker import CertificateChecker
from .Fsm_4_1_4_pip_installer import PipInstaller
from .Fsm_4_1_8_installer_thread import DependencyInstallerThread
from .Fsm_4_1_9_certifi_checker import CertifiChecker


class DependencyTabWidget(QWidget):
    """Вкладка проверки и установки зависимостей"""

    request_recheck = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.results: Optional[Dict[str, Any]] = None
        self.installer_thread: Optional[DependencyInstallerThread] = None
        self.install_paths: Optional[Dict[str, Any]] = None

        self.setup_ui()

    def setup_ui(self):
        """Создание интерфейса"""
        layout = QVBoxLayout(self)

        # Результаты проверки
        self.results_group = QGroupBox("Статус зависимостей")
        results_layout = QVBoxLayout()
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setHtml(
            "<p style='color: gray'>Ожидание результатов проверки...</p>"
        )
        results_layout.addWidget(self.results_text)
        self.results_group.setLayout(results_layout)
        layout.addWidget(self.results_group)

        # Прогресс установки
        self.install_group = QGroupBox("Процесс установки")
        install_layout = QVBoxLayout()

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m")
        install_layout.addWidget(self.progress_bar)

        self.install_log = QTextEdit()
        self.install_log.setReadOnly(True)
        self.install_log.setMinimumHeight(200)
        install_layout.addWidget(self.install_log)

        self.install_group.setLayout(install_layout)
        self.install_group.setVisible(False)
        layout.addWidget(self.install_group)

        # Кнопки
        button_layout = QHBoxLayout()

        self.install_button = QPushButton("Установить стабильные")
        self.install_button.setToolTip("Установить/переустановить библиотеки согласно requirements.txt")
        self.install_button.clicked.connect(self.install_stable)
        self.install_button.setEnabled(False)
        self.install_button.setStyleSheet(
            "QPushButton:enabled { background-color: #4CAF50; color: white; font-weight: bold; }"
        )
        button_layout.addWidget(self.install_button)

        self.update_button = QPushButton("Обновить все")
        self.update_button.setToolTip("Обновить библиотеки + установить шрифты, сертификаты, SSL")
        self.update_button.clicked.connect(self.update_packages)
        self.update_button.setEnabled(False)
        self.update_button.setStyleSheet(
            "QPushButton:enabled { background-color: #2196F3; color: white; }"
        )
        button_layout.addWidget(self.update_button)

        button_layout.addStretch()
        layout.addLayout(button_layout)

    def on_check_results(self, results: Dict[str, Any], install_paths: Dict[str, Any]) -> None:
        """Обработка результатов проверки зависимостей от контейнера"""
        self.results = results
        self.install_paths = install_paths

        if not results:
            self.results_text.setHtml(
                "<p style='color: red'>Ошибка: результаты проверки не доступны</p>"
            )
            return

        # Определяем отсутствующие библиотеки и доступные обновления
        has_updates = False
        for module_name, info in self.results['external'].items():
            if not info['installed']:
                self.results['missing'].append(module_name)
            elif info.get('has_update', False):
                has_updates = True

        # Сохраняем флаг наличия обновлений
        self.results['has_updates'] = has_updates

        # Проверяем есть ли отсутствующие компоненты
        has_missing_packages = len(self.results['missing']) > 0
        has_missing_fonts = not self.results['fonts'].get('all_fonts_installed', False)
        ssl_status = self.results.get('ssl_status', {})
        has_missing_certs = (
            not self.results['certificates'].get('certificates_installed', False)
            and self.results['certificates'].get('os_supported', True)
        )
        has_ssl_issues = ssl_status.get('status') in ('needs_install', 'needs_config')

        # Кнопка "Установить стабильные" всегда активна
        self.install_button.setEnabled(True)
        # Кнопка "Обновить все" активна если есть что обновлять/устанавливать
        self.update_button.setEnabled(
            has_updates or has_missing_packages
            or has_missing_fonts or has_missing_certs or has_ssl_issues
        )

        # Формируем отчет
        report = self.build_report()
        self.results_text.setHtml("".join(report))

    def build_report(self) -> list:
        """
        Формирование HTML отчета о статусе зависимостей

        Returns:
            list: Список строк HTML
        """
        # Проверка, что results инициализирован
        if self.results is None:
            return ["<p style='color: red'>Ошибка: результаты проверки не доступны</p>"]

        report = []

        # Внешние Python библиотеки
        report.append("<h3>Python библиотеки</h3>")
        report.append("<table border='1' cellpadding='5' cellspacing='0' width='100%'>")
        report.append("<tr><th>Библиотека</th><th>Статус</th><th>Версия</th><th>Использование</th></tr>")

        for module_name, info in self.results['external'].items():
            status_color = "green" if info['installed'] else "red"
            status_text = "OK" if info['installed'] else "X Не установлена"
            version_text = info['version'] if info['version'] else "-"

            # Проверяем наличие обновления
            has_update = info.get('has_update', False)
            latest_version = info.get('latest_version')
            if has_update and latest_version:
                version_text = f"{info['version']} <span style='color: orange'>(новая: {latest_version})</span>"
                status_text = "OK (есть новее)"
                status_color = "orange"

            report.append(f"<tr>")
            report.append(f"<td><b>{module_name}</b></td>")
            report.append(f"<td style='color: {status_color}'>{status_text}</td>")
            report.append(f"<td>{version_text}</td>")
            report.append(f"<td>{info['usage']}</td>")
            report.append(f"</tr>")

        report.append("</table>")

        # 3. Шрифты
        report.append("<h3>Шрифты</h3>")
        font_info = self.results.get('fonts', {})

        if font_info.get('all_fonts_installed', False):
            installed_count = len(font_info.get('installed_fonts', []))
            if installed_count > 0:
                report.append(f"<p style='color: green'>OK Все необходимые шрифты установлены ({installed_count} шт.)</p>")
            else:
                report.append(f"<p style='color: green'>OK Все необходимые шрифты установлены</p>")
        else:
            missing_count = len(font_info.get('missing_fonts', []))
            installed_count = len(font_info.get('installed_fonts', []))
            total_count = missing_count + installed_count

            report.append(
                f"<p style='color: orange'>! Необходимо установить {missing_count} шрифтов из {total_count}</p>"
            )

            if font_info.get('missing_fonts'):
                missing_fonts = font_info['missing_fonts']
                gost_missing = sum(1 for f in missing_fonts if 'gost' in f.lower())
                opensans_missing = sum(1 for f in missing_fonts if 'opensans' in f.lower())

                if gost_missing > 0:
                    report.append(f"<p>- {gost_missing} шрифтов GOST 2.304 (для DXF/AutoCAD)</p>")
                if opensans_missing > 0:
                    report.append(f"<p>- {opensans_missing} шрифтов OpenSans (для оформления)</p>")

            report.append("<p>Нажмите <b>'Установить стабильные'</b> для автоматической установки.</p>")

        # 4. Сертификаты Минцифры
        report.append("<h3>Корневые сертификаты Минцифры РФ</h3>")
        cert_info = self.results.get('certificates', {})

        if not cert_info.get('os_supported', True):
            report.append("<p style='color: gray'>Проверка сертификатов доступна только для Windows</p>")
        elif cert_info.get('certificates_installed', False):
            report.append("<p style='color: green'>OK Сертификаты установлены</p>")
            report.append("<p>Доступ к ПКК Росреестра, НСПД и госсервисам обеспечен</p>")
        else:
            report.append("<p style='color: orange'>! Сертификаты не установлены</p>")
            report.append("<p>Необходимы для:</p>")
            report.append("<ul>")
            report.append("<li>Публичная кадастровая карта (ПКК Росреестра)</li>")
            report.append("<li>Портал НСПД (Национальная система пространственных данных)</li>")
            report.append("<li>Государственные геосервисы</li>")
            report.append("<li>Электронная подпись на госпорталах</li>")
            report.append("</ul>")
            report.append("<p>Нажмите <b>'Установить стабильные'</b> для автоматической установки.</p>")

        # 5. SSL сертификаты (certifi)
        report.append("<h3>SSL сертификаты (GitHub/PyPI)</h3>")
        ssl_info = self.results.get('ssl_status', {})

        ssl_status = ssl_info.get('status', 'unknown')
        if ssl_status == 'ok':
            report.append("<p style='color: green'>OK SSL работает корректно</p>")
            certifi_info = ssl_info.get('certifi', {})
            if certifi_info.get('version'):
                report.append(f"<p>certifi версия: {certifi_info['version']}</p>")
        elif ssl_status == 'needs_install':
            report.append("<p style='color: red'>X certifi не установлен</p>")
            report.append("<p>Библиотека certifi необходима для HTTPS соединений.</p>")
            report.append("<p>Нажмите <b>'Установить стабильные'</b> для установки.</p>")
        elif ssl_status == 'needs_config':
            report.append("<p style='color: orange'>! Требуется настройка SSL</p>")
            report.append("<p>certifi установлен, но не настроен для использования QGIS.</p>")
            report.append("<p>Это может вызывать ошибки при обновлении плагина:</p>")
            report.append("<p style='color: gray; font-style: italic'>'Не удалось получить сертификат локального издателя'</p>")
            report.append("<p>Нажмите <b>'Установить стабильные'</b> для автоматической настройки.</p>")
        elif ssl_status == 'error':
            error_msg = ssl_info.get('message', 'Неизвестная ошибка')
            report.append(f"<p style='color: red'>X Ошибка SSL: {error_msg}</p>")
        else:
            report.append("<p style='color: gray'>Статус SSL неизвестен</p>")

        # Проверка .old файлов (ожидание перезапуска)
        pending_count = PipInstaller.count_pending_restart_files()
        if pending_count > 0:
            report.append("<h3>Ожидание перезапуска QGIS</h3>")
            report.append(
                f"<p style='color: #2196F3'>"
                f"Обнаружено {pending_count} файлов, ожидающих обновления после перезапуска QGIS."
                f"</p>"
            )
            report.append(
                "<p>Некоторые библиотеки были обновлены, но их файлы заблокированы "
                "запущенным QGIS. Обновления будут автоматически применены "
                "при следующем запуске.</p>"
            )

        # Итоговый статус
        self._check_need_install(font_info, cert_info, ssl_info, report)

        return report

    def _check_need_install(self, font_info: Dict, cert_info: Dict, ssl_info: Dict, report: list) -> bool:
        """Проверка необходимости установки"""
        # Проверка, что results инициализирован
        if self.results is None:
            return False

        need_install = False

        # Подсчёт пакетов с обновлениями
        packages_with_updates = [
            name for name, info in self.results.get('external', {}).items()
            if info.get('has_update', False)
        ]

        if self.results['missing']:
            missing_count = len(self.results['missing'])
            report.append(f"<h3 style='color: orange'>! Требуется установка {missing_count} библиотек</h3>")
            report.append(f"<p>Отсутствуют: <b>{', '.join(self.results['missing'])}</b></p>")
            report.append("<p>Нажмите <b>'Установить стабильные'</b> для автоматической установки.</p>")
            need_install = True
        elif packages_with_updates:
            update_count = len(packages_with_updates)
            report.append(f"<h3 style='color: #2196F3'>Доступно обновление {update_count} библиотек</h3>")
            report.append(f"<p>Обновления: <b>{', '.join(packages_with_updates)}</b></p>")
            report.append("<p>Нажмите <b>'Обновить все'</b> для обновления.</p>")
        elif not font_info.get('all_fonts_installed', False):
            report.append("<h3 style='color: orange'>! Требуется установка шрифтов</h3>")
            report.append("<p>Шрифты необходимы для корректного экспорта в DXF/AutoCAD</p>")
            report.append("<p>Нажмите <b>'Установить стабильные'</b> для автоматической установки шрифтов.</p>")
            need_install = True
        elif not cert_info.get('certificates_installed', False) and cert_info.get('os_supported', True):
            report.append("<h3 style='color: orange'>! Требуется установка сертификатов Минцифры</h3>")
            report.append("<p>Сертификаты необходимы для работы с госсервисами</p>")
            report.append("<p>Нажмите <b>'Установить стабильные'</b> для автоматической установки.</p>")
            need_install = True
        elif ssl_info.get('status') in ('needs_install', 'needs_config'):
            report.append("<h3 style='color: orange'>! Требуется настройка SSL</h3>")
            report.append("<p>Настройка SSL необходима для обновления плагина через QGIS</p>")
            report.append("<p>Нажмите <b>'Установить стабильные'</b> для автоматической настройки.</p>")
            need_install = True
        else:
            report.append("<h3 style='color: green'>OK Все зависимости установлены!</h3>")

        return need_install

    def install_stable(self):
        """Установка/переустановка библиотек согласно requirements.txt + шрифты + сертификаты"""
        if not self.results:
            return

        # Показываем прогресс
        self.install_group.setVisible(True)
        self.install_log.clear()
        self.install_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)  # Неопределенный прогресс

        # Собираем ВСЕ пакеты для установки стабильных версий
        packages_to_install = {}
        external_deps = DependencyChecker.get_external_dependencies()

        for module_name, dep_info in external_deps.items():
            min_version = dep_info.get('min_version', '')
            if min_version:
                # Устанавливаем точную минимальную версию
                version_num = min_version.lstrip('>=<~!')
                packages_to_install[module_name] = {
                    'install_cmd': f'python -m pip install {module_name}=={version_num}',
                    'description': dep_info.get('description', ''),
                    'usage': dep_info.get('usage', '')
                }
            else:
                # Без версии - просто устанавливаем
                packages_to_install[module_name] = dep_info

        self.update_install_log("<b>Установка стабильных версий библиотек:</b>")
        for name in packages_to_install:
            self.update_install_log(f"  {name}")
        self.update_install_log("")

        # Собираем задачи на шрифты, сертификаты, SSL
        (fonts_to_install, fonts_dir, install_certificates,
         cert_install_mode, configure_ssl) = self._collect_non_python_tasks()

        # Запускаем установку в отдельном потоке
        self.installer_thread = DependencyInstallerThread(
            packages_to_install,
            self.install_paths,
            fonts_to_install,
            fonts_dir,
            install_certificates,
            cert_install_mode,
            configure_ssl
        )
        self.installer_thread.progress.connect(self.update_install_log)
        self.installer_thread.progress_percent.connect(self.update_install_progress)
        self.installer_thread.finished.connect(self._on_installation_finished)
        self.installer_thread.start()

    def update_install_log(self, message):
        """Обновление лога установки"""
        self.install_log.append(message)
        # Прокручиваем вниз
        cursor = self.install_log.textCursor()
        cursor.movePosition(cursor.End)
        self.install_log.setTextCursor(cursor)

    def update_install_progress(self, current: int, total: int):
        """Обновление прогресс-бара установки"""
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)

    def _on_installation_finished(self, success, message):
        """Завершение установки с автоматической перепроверкой"""
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1 if success else 0)

        # Проверяем наличие .old файлов (ожидание перезапуска)
        pending_restart = PipInstaller.has_pending_restart()

        if success:
            if pending_restart:
                # Успех, но нужен перезапуск
                self.update_install_log(f"\n<b style='color: #2196F3'>{message}</b>")
            else:
                self.update_install_log(f"\n<b style='color: green'>{message}</b>")
            self.update_install_log("\nПерепроверка зависимостей...")
            # Автоматическая перепроверка через контейнер
            from qgis.PyQt.QtCore import QTimer
            QTimer.singleShot(1000, self.request_recheck.emit)
        else:
            if pending_restart:
                # Ошибки есть, но часть обновлений ожидает перезапуска
                self.update_install_log(f"\n<b style='color: #ff9900'>{message}</b>")
                self.update_install_log(
                    "\n<b>Перезапустите QGIS</b> для применения обновлений "
                    "заблокированных библиотек.\n"
                    "После перезапуска запустите проверку зависимостей повторно."
                )
            else:
                self.update_install_log(f"\n<b style='color: red'>{message}</b>")
                self.update_install_log(
                    "\n<b>Для полной установки шрифтов:</b>\n"
                    "1. Запустите QGIS от имени администратора\n"
                    "2. Или установите шрифты вручную из папки: resources/styles/fonts\n\n"
                    "<b>Библиотеки Python через OSGeo4W Shell:</b>\n"
                    "python -m pip install --user ezdxf>=1.4.2 xlsxwriter>=3.0.0 requests cryptography"
                )
            self.install_button.setEnabled(True)
            self.update_button.setEnabled(True)

    def _collect_non_python_tasks(self):
        """Собрать задачи на установку шрифтов, сертификатов и SSL.

        Returns:
            Кортеж (fonts_to_install, fonts_dir, install_certificates,
                    cert_install_mode, configure_ssl)
        """
        # Шрифты
        fonts_to_install = []
        fonts_dir = None
        font_info = self.results.get('fonts', {})
        if not font_info.get('all_fonts_installed', False):
            fonts_to_install = font_info.get('missing_fonts', [])
            fonts_dir = FontChecker.get_plugin_fonts_dir()

        # Сертификаты Минцифры
        cert_info = self.results.get('certificates', {})
        install_certificates = False
        cert_install_mode = 'user'

        if cert_info.get('os_supported', True) and not cert_info.get('certificates_installed', False):
            install_certificates = True
            if sys.platform == 'win32':
                reply = QMessageBox.question(
                    self,
                    "Установка сертификатов Минцифры",
                    "Будут установлены официальные корневые сертификаты Минцифры РФ\n"
                    "для доступа к госсервисам (ПКК, НСПД и др.)\n\n"
                    "Установить для текущего пользователя?\n"
                    "(Да - для текущего пользователя, Нет - для всех пользователей)",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Yes
                )
                if reply == QMessageBox.StandardButton.Yes:
                    cert_install_mode = 'user'
                elif reply == QMessageBox.StandardButton.No:
                    cert_install_mode = 'admin'
                    QMessageBox.information(
                        self,
                        "Требуются права администратора",
                        "Для установки сертификатов для всех пользователей\n"
                        "может потребоваться подтверждение UAC."
                    )
                else:
                    install_certificates = False

        # SSL через certifi
        ssl_info = self.results.get('ssl_status', {})
        configure_ssl = ssl_info.get('status') in ('needs_config', 'needs_install')

        return fonts_to_install, fonts_dir, install_certificates, cert_install_mode, configure_ssl

    def update_packages(self):
        """Обновление библиотек до последних версий + установка всех отсутствующих компонентов"""
        if not self.results:
            return

        # Собираем пакеты: обновления + отсутствующие
        packages_to_process = {}
        update_info = []
        install_info = []

        for module_name, info in self.results['external'].items():
            if not info['installed']:
                # Отсутствующий пакет - установить последнюю версию
                latest = info.get('latest_version')
                if latest:
                    packages_to_process[module_name] = {
                        'install_cmd': f'python -m pip install {module_name}=={latest}',
                        'description': info.get('description', ''),
                        'usage': info.get('usage', '')
                    }
                    install_info.append(f"  {module_name}: (новый) -> {latest}")
                else:
                    # Без версии - просто установить
                    packages_to_process[module_name] = {
                        'install_cmd': f'python -m pip install {module_name}',
                        'description': info.get('description', ''),
                        'usage': info.get('usage', '')
                    }
                    install_info.append(f"  {module_name}: (новый)")
            elif info.get('has_update', False) and info.get('latest_version'):
                # Есть обновление
                packages_to_process[module_name] = {
                    'install_cmd': f'python -m pip install {module_name}=={info["latest_version"]}',
                    'description': info.get('description', ''),
                    'usage': info.get('usage', '')
                }
                update_info.append(f"  {module_name}: {info['version']} -> {info['latest_version']}")

        # Собираем задачи на шрифты, сертификаты, SSL
        (fonts_to_install, fonts_dir, install_certificates,
         cert_install_mode, configure_ssl) = self._collect_non_python_tasks()

        # Проверяем есть ли что делать
        has_work = (
            packages_to_process or fonts_to_install
            or install_certificates or configure_ssl
        )
        if not has_work:
            QMessageBox.information(
                self, "Обновление",
                "Нет доступных обновлений или отсутствующих компонентов."
            )
            return

        # Показываем прогресс
        self.install_group.setVisible(True)
        self.install_log.clear()

        if install_info:
            self.update_install_log("<b>Установка отсутствующих библиотек:</b>")
            for info_line in install_info:
                self.update_install_log(info_line)
            self.update_install_log("")

        if update_info:
            self.update_install_log("<b>Обновление библиотек:</b>")
            for info_line in update_info:
                self.update_install_log(info_line)
            self.update_install_log("")

        if fonts_to_install:
            self.update_install_log(f"<b>Шрифты:</b> {len(fonts_to_install)} для установки")
        if install_certificates:
            self.update_install_log("<b>Сертификаты Минцифры:</b> будут установлены")
        if configure_ssl:
            self.update_install_log("<b>SSL:</b> будет настроен")
        if fonts_to_install or install_certificates or configure_ssl:
            self.update_install_log("")

        self.install_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)

        # Запускаем установку со всеми компонентами
        self.installer_thread = DependencyInstallerThread(
            packages_to_process,
            self.install_paths,
            fonts_to_install,
            fonts_dir,
            install_certificates,
            cert_install_mode,
            configure_ssl
        )
        self.installer_thread.progress.connect(self.update_install_log)
        self.installer_thread.progress_percent.connect(self.update_install_progress)
        self.installer_thread.finished.connect(self._on_installation_finished)
        self.installer_thread.start()
