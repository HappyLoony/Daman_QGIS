# -*- coding: utf-8 -*-
"""
Fsm_4_1_13_TestTabWidget - Вкладка тестирования для DiagnosticsDialog

Извлечение из F_4_2_test.py.
Автономная вкладка - не получает результатов от проверки зависимостей,
но требует iface для ComprehensiveTestRunner.

Использует QTimer stepping через генератор run_all_tests_stepped()
для неблокирующего выполнения тестов (окно остаётся отзывчивым).
"""

from typing import Optional

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLabel, QProgressBar, QApplication
)
from qgis.PyQt.QtCore import QTimer

from Daman_QGIS.utils import log_info, log_error
from Daman_QGIS.managers import track_exception


class TestTabWidget(QWidget):
    """Вкладка комплексного тестирования плагина"""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._test_gen = None  # Генератор тестов
        self._runner = None  # ComprehensiveTestRunner
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

        # Прогресс (скрыт по умолчанию)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m")
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.progress_label = QLabel()
        self.progress_label.setStyleSheet("color: #666; font-style: italic;")
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

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

    def _on_test_progress(self, current: int, total: int, test_name: str) -> None:
        """Callback прогресса от ComprehensiveTestRunner"""
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)

        if test_name:
            display_name = test_name.replace('Fsm_4_2_T_', '').replace('.py', '')
            self.progress_label.setText(f"Тест {current + 1}/{total}: {display_name}")
        else:
            self.progress_label.setText("Завершено")

    def _run_tests(self):
        """Запуск комплексного теста через QTimer stepping"""
        self.output.clear()

        self.btn_run.setEnabled(False)
        self.btn_run.setText("Тестирование...")

        # Показываем прогресс
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        self.progress_label.setText("Обнаружение тестов...")
        self.progress_label.setVisible(True)
        QApplication.processEvents()

        try:
            from Daman_QGIS.tools.F_4_plagin.submodules.Fsm_4_2_T_comprehensive_runner import (
                ComprehensiveTestRunner, TestLogger
            )

            self._runner = ComprehensiveTestRunner(
                self.iface,
                log_level=TestLogger.LOG_LEVEL_ERROR,
                skip_network_tests=False,
                progress_callback=self._on_test_progress
            )

            # Запускаем генератор — каждый шаг = один тест
            self._test_gen = self._runner.run_all_tests_stepped()
            QTimer.singleShot(0, self._step_test)

        except Exception as e:
            self.output.append(f"КРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
            log_error(f"Fsm_4_1_13: Критическая ошибка: {str(e)}")
            import traceback
            self.output.append(traceback.format_exc())
            track_exception("Fsm_4_1_13", e)
            self._finish_tests()

    def _step_test(self) -> None:
        """Выполнение одного шага генератора, затем возврат в event loop"""
        try:
            next(self._test_gen)
            # Планируем следующий шаг — event loop полностью обрабатывает
            # события между вызовами (окно остаётся отзывчивым)
            QTimer.singleShot(0, self._step_test)
        except StopIteration:
            # Все тесты завершены
            self._on_tests_finished()
        except Exception as e:
            self.output.append(f"КРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
            log_error(f"Fsm_4_1_13: Критическая ошибка: {str(e)}")
            import traceback
            self.output.append(traceback.format_exc())
            track_exception("Fsm_4_1_13", e)
            self._finish_tests()

    def _on_tests_finished(self) -> None:
        """Обработка завершения всех тестов"""
        if self._runner:
            for line in self._runner.logger.get_log():
                self.output.append(line)
        self._finish_tests()

    def _finish_tests(self) -> None:
        """Сброс UI после завершения/ошибки"""
        self._test_gen = None
        self._runner = None
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self.btn_run.setEnabled(True)
        self.btn_run.setText("Запустить тестирование")
