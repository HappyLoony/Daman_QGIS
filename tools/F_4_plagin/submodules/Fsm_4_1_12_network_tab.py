# -*- coding: utf-8 -*-
"""
Fsm_4_1_12_NetworkTabWidget - Вкладка сетевой диагностики для DiagnosticsDialog

Извлечение сетевого функционала из Fsm_4_1_7_dependency_dialog.py:
- Отчёт о сетевых проблемах
- 3-этапная починка сети через DependencyInstallerThread
"""

from typing import Dict, Optional, Any

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTextEdit, QGroupBox, QMessageBox, QProgressBar
)
from qgis.PyQt.QtCore import pyqtSignal

from Daman_QGIS.utils import log_info, log_error

from .Fsm_4_1_10_network_doctor import NetworkDoctor
from .Fsm_4_1_8_installer_thread import DependencyInstallerThread


class NetworkTabWidget(QWidget):
    """Вкладка сетевой диагностики и починки"""

    request_recheck = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.network_results: Optional[Dict[str, Any]] = None
        self.install_paths: Optional[Dict[str, Any]] = None
        self.installer_thread: Optional[DependencyInstallerThread] = None
        self._setup_ui()

    def _setup_ui(self):
        """Создание интерфейса вкладки"""
        layout = QVBoxLayout(self)

        # Результаты диагностики
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setHtml(
            "<p style='color: gray'>Ожидание результатов диагностики...</p>"
        )
        layout.addWidget(self.results_text)

        # Прогресс починки
        self.install_group = QGroupBox("Процесс починки")
        install_layout = QVBoxLayout()

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m")
        install_layout.addWidget(self.progress_bar)

        self.install_log = QTextEdit()
        self.install_log.setReadOnly(True)
        self.install_log.setMinimumHeight(150)
        install_layout.addWidget(self.install_log)

        self.install_group.setLayout(install_layout)
        self.install_group.setVisible(False)
        layout.addWidget(self.install_group)

        # Кнопки
        btn_layout = QHBoxLayout()

        self.fix_button = QPushButton("Починка сети")
        self.fix_button.setToolTip(
            "Диагностика и исправление сетевых проблем "
            "(прокси, DNS, сертификаты VPN/антивирусов)"
        )
        self.fix_button.clicked.connect(self._on_fix_network_clicked)
        self.fix_button.setEnabled(False)
        self.fix_button.setVisible(False)
        self.fix_button.setStyleSheet(
            "QPushButton:enabled { background-color: #FF9800; color: white; font-weight: bold; }"
        )
        btn_layout.addWidget(self.fix_button)

        self.recheck_button = QPushButton("Перепроверить")
        self.recheck_button.setToolTip("Повторная диагностика сети")
        self.recheck_button.clicked.connect(self.request_recheck.emit)
        btn_layout.addWidget(self.recheck_button)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def on_network_results(self, network_results: Dict, install_paths: Dict) -> None:
        """Обработка результатов сетевой диагностики от контейнера"""
        self.network_results = network_results
        self.install_paths = install_paths

        if not network_results:
            self.results_text.setHtml(
                "<p style='color: gray'>Результаты сетевой диагностики отсутствуют</p>"
            )
            self.fix_button.setVisible(False)
            self.fix_button.setEnabled(False)
            return

        # Формируем HTML отчёт
        report = []
        self._build_report(report)
        self.results_text.setHtml("".join(report))

        # Управление кнопкой починки
        fixable = NetworkDoctor.get_fixable_issues(network_results)
        self.fix_button.setVisible(bool(fixable))
        self.fix_button.setEnabled(bool(fixable))

    def _build_report(self, report: list) -> None:
        """Формирование HTML отчёта сетевой диагностики"""
        if not self.network_results:
            return

        report.append("<h3>Сетевое соединение</h3>")

        status_map = {
            "ok": ("green", "OK"),
            "issue": ("red", "!"),
            "error": ("gray", "?"),
            "skip": ("gray", "-"),
        }

        for check_id, diag in self.network_results.items():
            color, prefix = status_map.get(diag.status, ("gray", "?"))
            msg_html = diag.message.replace("\n", "<br>")
            report.append(
                f"<p style='color: {color}'>{prefix} {diag.name}: {msg_html}</p>"
            )

        # Подсказка про VPN split-tunnel при изолированной недоступности NSPD
        self._append_nspd_vpn_hint(report)

        # Итог
        issue_count = NetworkDoctor.get_issue_count(self.network_results)
        fixable = NetworkDoctor.get_fixable_issues(self.network_results)

        if issue_count == 0:
            report.append("<p style='color: green'><b>Сетевых проблем не обнаружено</b></p>")
        else:
            report.append(
                f"<p style='color: orange'><b>Найдено {issue_count} проблем"
                f"{f' ({len(fixable)} исправимых)' if fixable else ''}"
                f"</b></p>"
            )
            if fixable:
                needs_admin = NetworkDoctor.needs_any_admin(self.network_results)
                if needs_admin:
                    report.append(
                        "<p>Нажмите <b>'Починка сети'</b> для исправления. "
                        "Потребуется подтверждение UAC (права администратора).</p>"
                    )
                else:
                    report.append(
                        "<p>Нажмите <b>'Починка сети'</b> для автоматического исправления.</p>"
                    )

    def _append_nspd_vpn_hint(self, report: list) -> None:
        """Красная плашка про NSPD и VPN split-tunnel.

        Показывается, если соединение определено как 'issue', NSPD отсутствует
        среди доступных, но остальные тестовые сайты (Google/GitHub/NextGIS)
        доступны — типичная картина при включённом VPN без split-tunnel для
        домена nspd.gov.ru.
        """
        if not self.network_results:
            return

        conn_diag = self.network_results.get("connectivity")
        if conn_diag is None or conn_diag.status != "issue":
            return

        details = getattr(conn_diag, "details", None)
        if not isinstance(details, dict):
            return

        nspd_entry = None
        other_entries = []
        for label, entry in details.items():
            if not isinstance(entry, dict):
                continue
            label_lower = str(label).lower()
            # Ловим любую метку с упоминанием NSPD/Rosreestr
            if "nspd" in label_lower or "росреестр" in label_lower or "rosreestr" in label_lower:
                nspd_entry = entry
            else:
                other_entries.append(entry)

        if nspd_entry is None:
            return

        nspd_ok = bool(nspd_entry.get("ok"))
        if nspd_ok:
            return  # NSPD доступен — подсказка не нужна

        # Серверная SSL-ошибка NSPD — это проблема сервера, не VPN
        if nspd_entry.get("server_issue"):
            return

        others_ok = [bool(e.get("ok")) for e in other_entries]
        if not others_ok or not all(others_ok):
            return  # Проблема шире, чем только NSPD

        report.append(
            "<p style='color: white; background: #D32F2F; "
            "padding: 8px; border-radius: 4px; font-weight: bold;'>"
            "NSPD недоступен. Возможно включён VPN без split-tunnel. "
            "Добавьте nspd.gov.ru в split-tunnel или отключите VPN "
            "для работы с Росреестром."
            "</p>"
        )

    def _on_fix_network_clicked(self) -> None:
        """Обработка нажатия кнопки 'Починка сети'"""
        if not self.network_results:
            return

        fixable = NetworkDoctor.get_fixable_issues(self.network_results)
        if not fixable:
            QMessageBox.information(self, "Починка сети", "Нет проблем для исправления.")
            return

        # Формируем описание проблем
        lines = ["Будут исправлены следующие проблемы:\n"]
        needs_admin = False
        for diag in fixable.values():
            admin_mark = " [требует админ]" if diag.needs_admin else ""
            lines.append(f"  - {diag.name}: {diag.message}{admin_mark}")
            if diag.needs_admin:
                needs_admin = True

        lines.append("")
        if needs_admin:
            lines.append("Для некоторых операций потребуется подтверждение UAC.")
            lines.append("")

        lines.append("Этап 1: Быстрое исправление (без перезагрузки)")
        lines.append("Этап 2: Полное исправление (с правами администратора)")
        lines.append("Этап 3: Глубокая починка (может потребовать перезагрузку)")

        # Диалог с выбором этапа
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Починка сети")
        msg_box.setText("Обнаружены сетевые проблемы")
        msg_box.setInformativeText("\n".join(lines))
        msg_box.setIcon(QMessageBox.Icon.Question)

        btn_quick = msg_box.addButton("Быстро (этап 1)", QMessageBox.ButtonRole.AcceptRole)
        btn_full = msg_box.addButton("Полностью (этапы 1-3)", QMessageBox.ButtonRole.AcceptRole)
        msg_box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)

        msg_box.exec()
        clicked = msg_box.clickedButton()

        if clicked == btn_quick:
            stage = 1
        elif clicked == btn_full:
            stage = 3
        else:
            return

        self._run_network_fix(fixable, stage)

    def _run_network_fix(self, issues: Dict, stage: int) -> None:
        """Запуск починки сетевых проблем"""
        self.install_group.setVisible(True)
        self.install_log.clear()
        self.fix_button.setEnabled(False)
        self.recheck_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)

        self._update_log(f"<b>--- Починка сети (этап {stage}) ---</b>")

        self.installer_thread = DependencyInstallerThread(
            packages={},
            install_paths=self.install_paths,
            fix_network=True,
            network_issues=issues,
            network_fix_stage=stage
        )
        self.installer_thread.progress.connect(self._update_log)
        self.installer_thread.progress_percent.connect(self._update_progress)
        self.installer_thread.finished.connect(self._on_network_fix_finished)
        self.installer_thread.start()

    def _on_network_fix_finished(self, success: bool, message: str) -> None:
        """Завершение починки сети"""
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1 if success else 0)

        if success:
            self._update_log(f"\n<b style='color: green'>{message}</b>")
        else:
            self._update_log(f"\n<b style='color: orange'>{message}</b>")

        if "перезагруз" in message.lower() or "reboot" in message.lower():
            self._update_log(
                "\n<b style='color: #2196F3'>Для завершения починки "
                "требуется перезагрузка компьютера.</b>"
            )

        self.recheck_button.setEnabled(True)
        self._update_log("\nПерепроверка...")
        from qgis.PyQt.QtCore import QTimer
        QTimer.singleShot(2000, self.request_recheck.emit)

    def _update_log(self, message: str) -> None:
        """Обновление лога"""
        self.install_log.append(message)
        cursor = self.install_log.textCursor()
        cursor.movePosition(cursor.End)
        self.install_log.setTextCursor(cursor)

    def _update_progress(self, current: int, total: int) -> None:
        """Обновление прогресс-бара"""
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
