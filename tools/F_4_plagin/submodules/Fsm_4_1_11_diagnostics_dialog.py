# -*- coding: utf-8 -*-
"""
Fsm_4_1_11_DiagnosticsDialog - Контейнер диагностики плагина

QDialog с QTabWidget (4 вкладки: Зависимости | Тестирование | Сеть | Среда).
Запускает DependencyCheckTask через M_17, распределяет результаты по вкладкам.
Кнопка "Копировать диагностику" собирает все секции в plain text для буфера обмена.
"""

from typing import Dict, Optional, Any

from qgis.core import Qgis
from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel,
    QTabWidget, QProgressBar, QPushButton, QApplication
)
from qgis.PyQt.QtGui import QFont

from Daman_QGIS.core.base_responsive_dialog import BaseResponsiveDialog

# Прямой импорт для избежания циклических зависимостей при загрузке плагина
from Daman_QGIS.managers.infrastructure.submodules.Msm_17_1_base_task import BaseAsyncTask
from Daman_QGIS.managers._registry import registry
from Daman_QGIS.constants import PLUGIN_VERSION
from Daman_QGIS.utils import log_info, log_error

from .Fsm_4_1_1_dependency_checker import DependencyChecker
from .Fsm_4_1_2_font_checker import FontChecker
from .Fsm_4_1_3_cert_checker import CertificateChecker
from .Fsm_4_1_9_certifi_checker import CertifiChecker
from .Fsm_4_1_10_network_doctor import NetworkDoctor
from .Fsm_4_1_14_environment_doctor import EnvironmentDoctor

from .Fsm_4_1_7_dependency_dialog import DependencyTabWidget
from .Fsm_4_1_12_network_tab import NetworkTabWidget
from .Fsm_4_1_13_test_tab import TestTabWidget
from .Fsm_4_1_15_environment_tab import EnvironmentTabWidget


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

        self.report_progress(55, "Проверка сертификатов Минцифры...")

        # Проверяем сертификаты Минцифры
        certificates = CertificateChecker.check_certificates()

        self.report_progress(65, "Проверка SSL (certifi)...")

        # Проверяем SSL через certifi
        ssl_status = CertifiChecker.check_ssl_status()

        self.report_progress(75, "Диагностика сети...")

        # Диагностика сетевых проблем (прокси, DNS, сертификаты VPN и др.)
        network = NetworkDoctor.run_diagnostics()

        self.report_progress(90, "Диагностика среды QGIS...")

        # Диагностика системной среды
        environment = EnvironmentDoctor.run_diagnostics()

        self.report_progress(100, "Готово")

        # Собираем результаты
        return {
            'external': external,
            'fonts': fonts,
            'certificates': certificates,
            'ssl_status': ssl_status,
            'network': network,
            'environment': environment,
            'missing': [],
        }


class DiagnosticsDialog(BaseResponsiveDialog):
    """Диалог диагностики плагина с четырьмя вкладками"""

    # Адаптивные размеры диалога
    WIDTH_RATIO = 0.62
    HEIGHT_RATIO = 0.80
    MIN_WIDTH = 700
    MAX_WIDTH = 1050
    MIN_HEIGHT = 550
    MAX_HEIGHT = 850

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.check_task_id: Optional[str] = None
        self.install_paths: Optional[Dict[str, Any]] = None
        self._last_results: Optional[Dict[str, Any]] = None

        self.setWindowTitle("Daman_QGIS - Диагностика плагина")

        self._setup_ui()
        self.check_dependencies()

    def _setup_ui(self):
        """Создание интерфейса"""
        layout = QVBoxLayout(self)

        # Заголовок
        title_label = QLabel("Диагностика плагина Daman_QGIS")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # Статус проверки
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(self.status_label)

        # Прогресс-бар проверки
        self.check_progress = QProgressBar()
        self.check_progress.setTextVisible(False)
        self.check_progress.setMaximumHeight(10)
        self.check_progress.setRange(0, 0)
        self.check_progress.setVisible(False)
        layout.addWidget(self.check_progress)

        # Вкладки
        self.tab_widget = QTabWidget()

        self.dependency_tab = DependencyTabWidget()
        self.tab_widget.addTab(self.dependency_tab, "Зависимости")

        self.test_tab = TestTabWidget(self.iface)
        self.tab_widget.addTab(self.test_tab, "Тестирование")

        self.network_tab = NetworkTabWidget()
        self.tab_widget.addTab(self.network_tab, "Сеть")

        self.env_tab = EnvironmentTabWidget()
        self.tab_widget.addTab(self.env_tab, "Среда")

        layout.addWidget(self.tab_widget)

        # Кнопка "Копировать диагностику"
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.copy_button = QPushButton("Копировать диагностику")
        self.copy_button.setToolTip(
            "Скопировать результаты всех проверок в буфер обмена "
            "(для отправки разработчику)"
        )
        self.copy_button.clicked.connect(self._on_copy_diagnostics)
        self.copy_button.setEnabled(False)
        btn_layout.addWidget(self.copy_button)

        layout.addLayout(btn_layout)

        # Подключаем сигналы перепроверки от вкладок
        self.dependency_tab.request_recheck.connect(self.check_dependencies)
        self.network_tab.request_recheck.connect(self.check_dependencies)
        self.env_tab.request_recheck.connect(self.check_dependencies)

    def check_dependencies(self):
        """Запуск проверки зависимостей через M_17"""
        log_info("Fsm_4_1_11: Запуск проверки зависимостей")

        # Показываем прогресс
        self.status_label.setText("Загрузка...")
        self.check_progress.setVisible(True)
        self.check_progress.setRange(0, 100)
        self.check_progress.setValue(0)
        self.copy_button.setEnabled(False)

        # Получаем пути установки
        self.install_paths = DependencyChecker.get_install_paths()

        # Запускаем проверку через M_17
        task = DependencyCheckTask()
        task.signals.progress_updated.connect(self._on_check_progress)

        manager = registry.get('M_17')
        self.check_task_id = manager.run(
            task,
            show_progress=False,
            on_completed=self._on_check_finished,
            on_failed=self._on_check_failed
        )

    def _on_check_progress(self, percent: int, message: str):
        """Обновление статуса проверки"""
        self.status_label.setText(message)
        self.check_progress.setValue(percent)

    def _on_check_failed(self, error: str):
        """Ошибка при проверке"""
        log_error(f"Fsm_4_1_11: Ошибка проверки: {error}")
        self.check_progress.setVisible(False)
        self.status_label.setText("")

    def _on_check_finished(self, results: dict):
        """Распределение результатов по вкладкам"""
        log_info("Fsm_4_1_11: Проверка завершена, распределяю результаты")

        # Сохраняем результаты для кнопки копирования
        self._last_results = results

        # Скрываем прогресс
        self.check_progress.setVisible(False)
        self.status_label.setText("")

        # Передаём результаты вкладке зависимостей
        self.dependency_tab.on_check_results(results, self.install_paths)

        # Передаём сетевые результаты вкладке сети
        network_results = results.get('network', {})
        self.network_tab.on_network_results(network_results, self.install_paths)

        # Передаём результаты среды вкладке среды
        env_results = results.get('environment', {})
        self.env_tab.on_environment_results(env_results)

        # Активируем кнопку копирования
        self.copy_button.setEnabled(True)

    def _on_copy_diagnostics(self) -> None:
        """Копирование полной диагностики в буфер обмена."""
        if not self._last_results:
            return

        lines = []
        lines.append(f"=== Daman_QGIS v{PLUGIN_VERSION} - Диагностика ===")
        lines.append("")

        # 1. Среда
        env_results = self._last_results.get('environment', {})
        if env_results:
            lines.append("--- Среда QGIS ---")
            lines.append(EnvironmentDoctor.format_plain_text(env_results))
            lines.append("")

        # 2. Python библиотеки
        lines.append("--- Python библиотеки ---")
        for module_name, info in self._last_results.get('external', {}).items():
            status = "OK" if info['installed'] else "X"
            version = info.get('version') or '-'
            update = ""
            if info.get('has_update') and info.get('latest_version'):
                update = f" (новая: {info['latest_version']})"
            lines.append(f"  {status} {module_name}: {version}{update}")
        lines.append("")

        # 3. Шрифты
        font_info = self._last_results.get('fonts', {})
        lines.append("--- Шрифты ---")
        if font_info.get('all_fonts_installed'):
            installed_count = len(font_info.get('installed_fonts', []))
            lines.append(f"  OK Все шрифты установлены ({installed_count} шт.)")
        else:
            missing = font_info.get('missing_fonts', [])
            lines.append(f"  ! Отсутствуют: {len(missing)} шрифтов")
        lines.append("")

        # 4. Сертификаты
        cert_info = self._last_results.get('certificates', {})
        lines.append("--- Сертификаты Минцифры ---")
        if cert_info.get('certificates_installed'):
            lines.append("  OK Установлены")
        elif not cert_info.get('os_supported', True):
            lines.append("  - Проверка недоступна на данной ОС")
        else:
            lines.append("  ! Не установлены")
        lines.append("")

        # 5. SSL
        ssl_info = self._last_results.get('ssl_status', {})
        lines.append("--- SSL ---")
        ssl_status_val = ssl_info.get('status', 'unknown')
        lines.append(f"  Статус: {ssl_status_val}")
        certifi_ver = ssl_info.get('certifi', {}).get('version')
        if certifi_ver:
            lines.append(f"  certifi: {certifi_ver}")
        ssl_message = ssl_info.get('message')
        if ssl_message and ssl_status_val not in ('ok',):
            lines.append(f"  {ssl_message}")
        lines.append("")

        # 6. Сеть
        network_results = self._last_results.get('network', {})
        if network_results:
            lines.append("--- Сетевое соединение ---")
            for check_id, diag in network_results.items():
                lines.append(f"  [{diag.status}] {diag.name}: {diag.message}")
            lines.append("")

        text = "\n".join(lines)
        QApplication.clipboard().setText(text)

        if self.iface:
            self.iface.messageBar().pushMessage(
                "Daman_QGIS",
                "Диагностика скопирована в буфер обмена",
                level=Qgis.Info, duration=3
            )
