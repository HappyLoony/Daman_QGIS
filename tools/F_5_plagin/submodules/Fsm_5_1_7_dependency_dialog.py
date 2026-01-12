# -*- coding: utf-8 -*-
"""
Fsm_5_1_7_DependencyCheckDialog - GUI диалог проверки зависимостей

Интерфейс для проверки и установки зависимостей плагина.
Использует M_17_AsyncTaskManager для фоновой проверки.
"""

import sys
import os
from typing import Dict, Optional, Any

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QGroupBox, QMessageBox, QProgressBar
)
from qgis.PyQt.QtGui import QFont

from Daman_QGIS.managers.submodules.Msm_17_1_base_task import BaseAsyncTask
from Daman_QGIS.managers import get_async_manager

from .Fsm_5_1_1_dependency_checker import DependencyChecker
from .Fsm_5_1_2_font_checker import FontChecker
from .Fsm_5_1_3_cert_checker import CertificateChecker
from .Fsm_5_1_8_installer_thread import DependencyInstallerThread


class DependencyCheckTask(BaseAsyncTask):
    """Задача проверки зависимостей через M_17"""

    def __init__(self):
        super().__init__("Проверка зависимостей", can_cancel=False)

    def execute(self) -> Dict[str, Any]:
        """Выполнение проверки в фоновом потоке"""
        self.report_progress(0, "Проверка Python библиотек...")

        # Проверяем внешние библиотеки (включая PyPI)
        external = DependencyChecker.check_all_external(check_updates=True)

        self.report_progress(40, "Проверка шрифтов...")

        # Проверяем шрифты
        fonts = FontChecker.check_fonts()

        self.report_progress(70, "Проверка сертификатов...")

        # Проверяем сертификаты
        certificates = CertificateChecker.check_certificates()

        self.report_progress(100, "Готово")

        # Собираем результаты
        return {
            'external': external,
            'fonts': fonts,
            'certificates': certificates,
            'missing': [],
            'all_ok': True
        }


class DependencyCheckDialog(QDialog):
    """Диалог проверки и установки зависимостей"""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.results: Optional[Dict[str, Any]] = None
        self.installer_thread: Optional[DependencyInstallerThread] = None
        self.check_task_id: Optional[str] = None
        self.install_paths: Optional[Dict[str, Any]] = None

        self.setWindowTitle("Daman_QGIS - Проверка зависимостей")
        self.setMinimumWidth(800)
        self.setMinimumHeight(600)

        self.setup_ui()
        self.check_dependencies()

    def setup_ui(self):
        """Создание интерфейса"""
        layout = QVBoxLayout(self)

        # Заголовок
        title_label = QLabel("Проверка и установка зависимостей плагина Daman_QGIS")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # Статус проверки (показывается во время проверки)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(self.status_label)

        # Прогресс-бар проверки
        self.check_progress = QProgressBar()
        self.check_progress.setTextVisible(False)
        self.check_progress.setMaximumHeight(10)
        self.check_progress.setRange(0, 0)  # Неопределённый прогресс
        self.check_progress.setVisible(False)
        layout.addWidget(self.check_progress)

        # Результаты проверки
        self.results_group = QGroupBox("Статус зависимостей")
        results_layout = QVBoxLayout()
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
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

        # Кнопки - первый ряд
        button_layout = QHBoxLayout()

        self.refresh_button = QPushButton("Проверить заново")
        self.refresh_button.clicked.connect(self.check_dependencies)
        button_layout.addWidget(self.refresh_button)

        self.install_button = QPushButton("Установить зависимости")
        self.install_button.clicked.connect(self.install_dependencies)
        self.install_button.setEnabled(False)
        self.install_button.setStyleSheet(
            "QPushButton:enabled { background-color: #4CAF50; color: white; font-weight: bold; }"
        )
        button_layout.addWidget(self.install_button)

        self.close_button = QPushButton("Закрыть")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

        # Кнопки - второй ряд (обновление/откат)
        update_layout = QHBoxLayout()

        self.update_button = QPushButton("Обновить библиотеки")
        self.update_button.setToolTip("Обновить все библиотеки до последних версий из PyPI")
        self.update_button.clicked.connect(self.update_packages)
        self.update_button.setEnabled(False)
        self.update_button.setStyleSheet(
            "QPushButton:enabled { background-color: #2196F3; color: white; }"
        )
        update_layout.addWidget(self.update_button)

        self.reset_button = QPushButton("Сбросить версии")
        self.reset_button.setToolTip("Переустановить библиотеки согласно requirements.txt (минимальные версии)")
        self.reset_button.clicked.connect(self.reset_packages)
        self.reset_button.setEnabled(False)
        self.reset_button.setStyleSheet(
            "QPushButton:enabled { background-color: #FF9800; color: white; }"
        )
        update_layout.addWidget(self.reset_button)

        layout.addLayout(update_layout)

    def check_dependencies(self):
        """Выполнение проверки зависимостей через M_17"""
        # Очищаем логи
        self.results_text.clear()
        self.install_log.clear()
        self.install_group.setVisible(False)

        # Показываем прогресс
        self.status_label.setText("Загрузка...")
        self.check_progress.setVisible(True)
        self.check_progress.setRange(0, 100)
        self.check_progress.setValue(0)
        self.results_text.setHtml("<p style='color: gray'>Проверка зависимостей...</p>")

        # Отключаем кнопки на время проверки
        self.refresh_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.reset_button.setEnabled(False)

        # Получаем пути установки
        self.install_paths = DependencyChecker.get_install_paths()

        # Запускаем проверку через M_17 (show_progress=False - используем свой UI)
        task = DependencyCheckTask()
        task.signals.progress_updated.connect(self._on_check_progress)

        manager = get_async_manager(self.iface)
        self.check_task_id = manager.run(
            task,
            show_progress=False,  # Не показываем в MessageBar
            on_completed=self._on_check_finished,
            on_failed=self._on_check_failed
        )

    def _on_check_progress(self, percent: int, message: str):
        """Обновление статуса проверки"""
        self.status_label.setText(message)
        self.check_progress.setValue(percent)

    def _on_check_failed(self, error: str):
        """Ошибка при проверке"""
        self.check_progress.setVisible(False)
        self.status_label.setText("")
        self.refresh_button.setEnabled(True)
        self.results_text.setHtml(f"<p style='color: red'>Ошибка проверки: {error}</p>")

    def _on_check_finished(self, results: dict):
        """Завершение проверки зависимостей"""
        # Скрываем прогресс
        self.check_progress.setVisible(False)
        self.status_label.setText("")
        self.refresh_button.setEnabled(True)

        # Сохраняем результаты
        self.results = results

        # Определяем отсутствующие библиотеки и доступные обновления
        has_updates = False
        for module_name, info in self.results['external'].items():
            if not info['installed']:
                self.results['missing'].append(module_name)
                self.results['all_ok'] = False
            elif info.get('has_update', False):
                has_updates = True

        # Проверяем шрифты и сертификаты
        if not self.results['fonts'].get('all_fonts_installed', False):
            self.results['all_ok'] = False

        if not self.results['certificates'].get('certificates_installed', False):
            self.results['all_ok'] = False

        # Сохраняем флаг наличия обновлений
        self.results['has_updates'] = has_updates

        # Активируем кнопки обновления/сброса если есть установленные библиотеки
        has_installed = any(info['installed'] for info in self.results['external'].values())
        self.update_button.setEnabled(has_updates)
        self.reset_button.setEnabled(has_installed)

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
                report.append(f"<p style='color: green'>✓ Все необходимые шрифты установлены ({installed_count} шт.)</p>")
            else:
                report.append(f"<p style='color: green'>✓ Все необходимые шрифты установлены</p>")
        else:
            missing_count = len(font_info.get('missing_fonts', []))
            installed_count = len(font_info.get('installed_fonts', []))
            total_count = missing_count + installed_count

            report.append(
                f"<p style='color: orange'>⚠ Необходимо установить {missing_count} шрифтов из {total_count}</p>"
            )

            if font_info.get('missing_fonts'):
                missing_fonts = font_info['missing_fonts']
                gost_missing = sum(1 for f in missing_fonts if 'gost' in f.lower())
                opensans_missing = sum(1 for f in missing_fonts if 'opensans' in f.lower())

                if gost_missing > 0:
                    report.append(f"<p>• {gost_missing} шрифтов GOST 2.304 (для DXF/AutoCAD)</p>")
                if opensans_missing > 0:
                    report.append(f"<p>• {opensans_missing} шрифтов OpenSans (для оформления)</p>")

            report.append("<p>Нажмите <b>'Установить зависимости'</b> для автоматической установки.</p>")

        # 4. Сертификаты Минцифры
        report.append("<h3>Корневые сертификаты Минцифры РФ</h3>")
        cert_info = self.results.get('certificates', {})

        if not cert_info.get('os_supported', True):
            report.append("<p style='color: gray'>Проверка сертификатов доступна только для Windows</p>")
        elif cert_info.get('certificates_installed', False):
            report.append("<p style='color: green'>✓ Сертификаты установлены</p>")
            report.append("<p>Доступ к ПКК Росреестра, НСПД и госсервисам обеспечен</p>")
        else:
            report.append("<p style='color: orange'>⚠ Сертификаты не установлены</p>")
            report.append("<p>Необходимы для:</p>")
            report.append("<ul>")
            report.append("<li>Публичная кадастровая карта (ПКК Росреестра)</li>")
            report.append("<li>Портал НСПД (Национальная система пространственных данных)</li>")
            report.append("<li>Государственные геосервисы</li>")
            report.append("<li>Электронная подпись на госпорталах</li>")
            report.append("</ul>")
            report.append("<p>Нажмите <b>'Установить зависимости'</b> для автоматической установки.</p>")

        # Итоговый статус
        need_install = self._check_need_install(font_info, cert_info, report)
        self.install_button.setEnabled(need_install)

        return report

    def _check_need_install(self, font_info: Dict, cert_info: Dict, report: list) -> bool:
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
            report.append(f"<h3 style='color: orange'>⚠ Требуется установка {missing_count} библиотек</h3>")
            report.append(f"<p>Отсутствуют: <b>{', '.join(self.results['missing'])}</b></p>")
            report.append("<p>Нажмите <b>'Установить зависимости'</b> для автоматической установки.</p>")
            need_install = True
        elif packages_with_updates:
            update_count = len(packages_with_updates)
            report.append(f"<h3 style='color: #2196F3'>Доступно обновление {update_count} библиотек</h3>")
            report.append(f"<p>Обновления: <b>{', '.join(packages_with_updates)}</b></p>")
            report.append("<p>Нажмите <b>'Обновить библиотеки'</b> для обновления.</p>")
            # need_install остаётся False - обновления через отдельную кнопку
        elif not font_info.get('all_fonts_installed', False):
            report.append("<h3 style='color: orange'>⚠ Требуется установка шрифтов</h3>")
            report.append("<p>Шрифты необходимы для корректного экспорта в DXF/AutoCAD</p>")
            report.append("<p>Нажмите <b>'Установить зависимости'</b> для автоматической установки шрифтов.</p>")
            need_install = True
        elif not cert_info.get('certificates_installed', False) and cert_info.get('os_supported', True):
            report.append("<h3 style='color: orange'>⚠ Требуется установка сертификатов</h3>")
            report.append("<p>Сертификаты необходимы для работы с госсервисами</p>")
            report.append("<p>Нажмите <b>'Установить зависимости'</b> для автоматической установки.</p>")
            need_install = True
        else:
            report.append("<h3 style='color: green'>✓ Все зависимости установлены!</h3>")

        return need_install

    def install_dependencies(self):
        """Запуск установки зависимостей, шрифтов и сертификатов"""
        if not self.results:
            return

        # Показываем прогресс
        self.install_group.setVisible(True)
        self.install_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)  # Неопределенный прогресс

        # Собираем пакеты для установки (только отсутствующие)
        # Обновления обрабатываются через отдельную кнопку "Обновить библиотеки"
        packages_to_install = {}
        external_deps = DependencyChecker.get_external_dependencies()

        # Отсутствующие пакеты
        for module_name in self.results.get('missing', []):
            if module_name in external_deps:
                packages_to_install[module_name] = external_deps[module_name]

        # Собираем шрифты для установки
        fonts_to_install = []
        fonts_dir = None
        font_info = self.results.get('fonts', {})
        if not font_info.get('all_fonts_installed', False):
            fonts_to_install = font_info.get('missing_fonts', [])
            fonts_dir = FontChecker.get_plugin_fonts_dir()

        # Проверяем нужна ли установка сертификатов
        cert_info = self.results.get('certificates', {})
        install_certificates = False
        cert_install_mode = 'user'

        if cert_info.get('os_supported', True) and not cert_info.get('certificates_installed', False):
            install_certificates = True
            # Для Windows можем предложить выбор режима установки
            if sys.platform == 'win32':
                reply = QMessageBox.question(
                    self,
                    "Установка сертификатов Минцифры",
                    "Будут установлены официальные корневые сертификаты Минцифры РФ\n"
                    "для доступа к госсервисам (ПКК, НСПД и др.)\n\n"
                    "Установить для текущего пользователя?\n"
                    "(Да - для текущего пользователя, Нет - для всех пользователей)",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                    QMessageBox.Yes
                )
                if reply == QMessageBox.Yes:
                    cert_install_mode = 'user'
                elif reply == QMessageBox.No:
                    cert_install_mode = 'admin'
                    QMessageBox.information(
                        self,
                        "Требуются права администратора",
                        "Для установки сертификатов для всех пользователей\n"
                        "может потребоваться подтверждение UAC."
                    )
                else:
                    install_certificates = False

        # Запускаем установку в отдельном потоке
        self.installer_thread = DependencyInstallerThread(
            packages_to_install,
            self.install_paths,
            fonts_to_install,
            fonts_dir,
            install_certificates,
            cert_install_mode
        )
        self.installer_thread.progress.connect(self.update_install_log)
        self.installer_thread.progress_percent.connect(self.update_install_progress)
        self.installer_thread.finished.connect(self.installation_finished)
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

    def installation_finished(self, success, message):
        """Завершение установки"""
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1 if success else 0)
        self.refresh_button.setEnabled(True)
        self.install_button.setEnabled(True)

        if success:
            self.update_install_log(f"\n<b style='color: green'>{message}</b>")
            self.update_install_log("\nНажмите 'Проверить заново' для подтверждения результатов.")
        else:
            self.update_install_log(f"\n<b style='color: red'>{message}</b>")
            self.update_install_log(
                "\n<b>Для полной установки шрифтов:</b>\n"
                "1. Запустите QGIS от имени администратора\n"
                "2. Или установите шрифты вручную из папки: resources/styles/fonts\n\n"
                "<b>Библиотеки Python через OSGeo4W Shell:</b>\n"
                "python -m pip install --user ezdxf>=1.4.2 xlsxwriter>=3.0.0 requests"
            )

    def update_packages(self):
        """Обновление всех библиотек до последних версий из PyPI"""
        if not self.results:
            return

        # Собираем пакеты с доступными обновлениями
        packages_to_update = {}
        update_info = []
        for module_name, info in self.results['external'].items():
            if info.get('has_update', False) and info.get('latest_version'):
                # Устанавливаем последнюю версию (без ограничения >=)
                packages_to_update[module_name] = {
                    'install_cmd': f'python -m pip install {module_name}=={info["latest_version"]}',
                    'description': info.get('description', ''),
                    'usage': info.get('usage', '')
                }
                update_info.append(f"  {module_name}: {info['version']} -> {info['latest_version']}")

        if not packages_to_update:
            QMessageBox.information(self, "Обновление", "Нет доступных обновлений.")
            return

        # Показываем прогресс и логируем что будет обновлено
        self.install_group.setVisible(True)
        self.install_log.clear()
        self.update_install_log("<b>Обновление библиотек:</b>")
        for info_line in update_info:
            self.update_install_log(info_line)
        self.update_install_log("")

        self.update_button.setEnabled(False)
        self.reset_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)

        # Запускаем установку (без шрифтов и сертификатов)
        self.installer_thread = DependencyInstallerThread(
            packages_to_update,
            self.install_paths,
            [],  # Без шрифтов
            None,
            False,  # Без сертификатов
            'user'
        )
        self.installer_thread.progress.connect(self.update_install_log)
        self.installer_thread.progress_percent.connect(self.update_install_progress)
        self.installer_thread.finished.connect(self.installation_finished)
        self.installer_thread.start()

    def reset_packages(self):
        """Сброс библиотек до версий из requirements.txt"""
        if not self.results:
            return

        # Собираем все установленные внешние пакеты
        packages_to_reset = {}
        reset_info = []
        external_deps = DependencyChecker.get_external_dependencies(include_optional=True)

        for module_name, info in self.results['external'].items():
            if info.get('installed', False) and module_name in external_deps:
                dep_info = external_deps[module_name]
                min_version = dep_info.get('min_version', '')
                current_version = info.get('version', '')

                # Формируем спецификацию для установки минимальной версии
                if min_version:
                    # Извлекаем версию без оператора
                    version_num = min_version.lstrip('>=<~!')
                    packages_to_reset[module_name] = {
                        'install_cmd': f'python -m pip install {module_name}=={version_num}',
                        'description': dep_info.get('description', ''),
                        'usage': dep_info.get('usage', '')
                    }
                    reset_info.append(f"  {module_name}: {current_version} -> {version_num}")

        if not packages_to_reset:
            QMessageBox.information(self, "Сброс версий", "Нет библиотек для сброса.")
            return

        # Подтверждение
        reply = QMessageBox.question(
            self,
            "Сброс версий библиотек",
            f"Библиотеки будут переустановлены до минимальных версий из requirements.txt:\n\n" +
            "\n".join(reset_info) +
            "\n\nЭто полезно если новая версия вызывает проблемы.\nПродолжить?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Показываем прогресс
        self.install_group.setVisible(True)
        self.update_button.setEnabled(False)
        self.reset_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)

        # Запускаем установку (без шрифтов и сертификатов)
        self.installer_thread = DependencyInstallerThread(
            packages_to_reset,
            self.install_paths,
            [],  # Без шрифтов
            None,
            False,  # Без сертификатов
            'user'
        )
        self.installer_thread.progress.connect(self.update_install_log)
        self.installer_thread.progress_percent.connect(self.update_install_progress)
        self.installer_thread.finished.connect(self.installation_finished)
        self.installer_thread.start()
