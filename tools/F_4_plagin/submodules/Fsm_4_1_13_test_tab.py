# -*- coding: utf-8 -*-
"""
Fsm_4_1_13_TestTabWidget - Вкладка тестирования для DiagnosticsDialog

Извлечение из F_4_2_test.py.
Автономная вкладка - не получает результатов от проверки зависимостей,
но требует iface для ComprehensiveTestRunner.
"""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLabel
)

from Daman_QGIS.utils import log_info, log_error
from Daman_QGIS.managers import track_exception


class TestTabWidget(QWidget):
    """Вкладка комплексного тестирования плагина"""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._setup_ui()

    def _setup_ui(self):
        """Создание интерфейса вкладки"""
        layout = QVBoxLayout(self)

        # Описание
        desc = QLabel(
            "Автоматическая проверка всех модулей плагина.\n"
            "Выводятся ТОЛЬКО ошибки. Если ошибок нет - краткий итог."
        )
        desc.setStyleSheet("color: #666; margin-bottom: 10px;")
        layout.addWidget(desc)

        # Текстовое поле для вывода
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet("font-family: Consolas, monospace; font-size: 10pt;")
        layout.addWidget(self.output)

        # Кнопки
        btn_layout = QHBoxLayout()

        self.btn_run = QPushButton("Запустить тестирование")
        self.btn_run.setStyleSheet("font-weight: bold; padding: 8px 16px;")
        self.btn_run.clicked.connect(self._run_tests)
        btn_layout.addWidget(self.btn_run)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def _run_tests(self):
        """Запуск комплексного теста"""
        self.output.clear()

        self.btn_run.setEnabled(False)
        self.btn_run.setText("Тестирование...")

        try:
            from Daman_QGIS.tools.F_4_plagin.submodules.Fsm_4_2_T_comprehensive_runner import (
                ComprehensiveTestRunner, TestLogger
            )

            runner = ComprehensiveTestRunner(
                self.iface,
                log_level=TestLogger.LOG_LEVEL_ERROR,
                skip_network_tests=False
            )

            runner.run_all_tests()

            for line in runner.logger.get_log():
                self.output.append(line)

        except Exception as e:
            self.output.append(f"КРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
            log_error(f"Fsm_4_1_13: Критическая ошибка: {str(e)}")
            import traceback
            self.output.append(traceback.format_exc())
            track_exception("Fsm_4_1_13", e)

        finally:
            self.btn_run.setEnabled(True)
            self.btn_run.setText("Запустить тестирование")
