# -*- coding: utf-8 -*-
"""
Fsm_4_1_15_EnvironmentTabWidget - Вкладка "Среда" для DiagnosticsDialog

Отображает результаты диагностики среды QGIS (Fsm_4_1_14).
Паттерн: аналогичен Fsm_4_1_12_NetworkTabWidget.

Зависимости:
- Fsm_4_1_14_environment_doctor: EnvironmentDoctor, DiagResult
"""

from typing import Dict, Optional, Any

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit
)
from qgis.PyQt.QtCore import pyqtSignal

from Daman_QGIS.utils import log_info

from .Fsm_4_1_14_environment_doctor import EnvironmentDoctor


class EnvironmentTabWidget(QWidget):
    """Вкладка диагностики среды QGIS"""

    request_recheck = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.env_results: Optional[Dict[str, Any]] = None
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

        # Кнопки
        btn_layout = QHBoxLayout()

        self.recheck_button = QPushButton("Перепроверить")
        self.recheck_button.setToolTip("Повторная диагностика среды")
        self.recheck_button.clicked.connect(self.request_recheck.emit)
        btn_layout.addWidget(self.recheck_button)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def on_environment_results(self, env_results: Dict) -> None:
        """Обработка результатов диагностики среды от контейнера."""
        self.env_results = env_results

        if not env_results:
            self.results_text.setHtml(
                "<p style='color: gray'>Результаты диагностики среды отсутствуют</p>"
            )
            return

        report: list = []
        self._build_report(report)
        self.results_text.setHtml("".join(report))

    def _build_report(self, report: list) -> None:
        """Формирование HTML отчёта диагностики среды."""
        if not self.env_results:
            return

        report.append("<h3>Среда QGIS</h3>")

        status_map = {
            "ok": ("green", "OK"),
            "issue": ("orange", "!"),
            "error": ("gray", "?"),
            "skip": ("gray", "-"),
        }

        for check_id, diag in self.env_results.items():
            color, prefix = status_map.get(diag.status, ("gray", "?"))
            msg_html = diag.message.replace("\n", "<br>")
            report.append(
                f"<p style='color: {color}'>{prefix} {diag.name}: {msg_html}</p>"
            )

            # Инструкция для проблем
            instruction = diag.details.get("instruction")
            if instruction and diag.status == "issue":
                report.append(
                    f"<p style='margin-left: 20px; color: #666; font-style: italic'>"
                    f"Рекомендация: {instruction}</p>"
                )

        # Итог
        issue_count = EnvironmentDoctor.get_issue_count(self.env_results)
        if issue_count == 0:
            report.append(
                "<p style='color: green'><b>Среда QGIS настроена корректно</b></p>"
            )
        else:
            report.append(
                f"<p style='color: orange'><b>Обнаружено {issue_count} "
                f"замечаний к среде</b></p>"
            )
