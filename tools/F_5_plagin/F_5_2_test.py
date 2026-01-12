# -*- coding: utf-8 -*-
"""
Инструмент F_5_2_Тест
Комплексное тестирование всех функций плагина

ФИЛОСОФИЯ:
  - Один клик - полная проверка всего плагина
  - Вывод ТОЛЬКО ошибок (если всё ОК - краткое сообщение)
  - Расширение: добавлять тесты в Fsm_5_2_T_*.py модули
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLabel, QCheckBox
)
from qgis.PyQt.QtCore import Qt

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.utils import log_info, log_error


class F_5_2_Test(BaseTool):
    """Инструмент комплексного тестирования плагина"""

    def __init__(self, iface):
        """Инициализация инструмента"""
        super().__init__(iface)

    def get_name(self):
        """Получить имя инструмента"""
        return "F_5_2_Тест"

    def run(self):
        """Основной метод запуска инструмента"""
        log_info("F_5_2: Запуск комплексного тестирования")

        # Создаем диалог
        dialog = QDialog()
        dialog.setWindowTitle("F_5_2 Комплексный тест")
        dialog.resize(700, 500)

        layout = QVBoxLayout()

        # Заголовок
        title = QLabel("Комплексное тестирование плагина")
        title.setStyleSheet("font-size: 14pt; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)

        # Описание
        desc = QLabel(
            "Автоматическая проверка всех модулей плагина.\n"
            "Выводятся ТОЛЬКО ошибки. Если ошибок нет - краткий итог."
        )
        desc.setStyleSheet("color: #666; margin-bottom: 10px;")
        layout.addWidget(desc)

        # Опция пропуска сетевых тестов
        skip_network_cb = QCheckBox("Пропустить сетевые тесты (QuickOSM, API)")
        skip_network_cb.setChecked(True)  # По умолчанию пропускаем
        skip_network_cb.setToolTip("Сетевые тесты могут занимать много времени из-за timeout'ов")
        layout.addWidget(skip_network_cb)

        # Текстовое поле для вывода
        output = QTextEdit()
        output.setReadOnly(True)
        output.setStyleSheet("font-family: Consolas, monospace; font-size: 10pt;")
        layout.addWidget(output)

        # Кнопки
        btn_layout = QHBoxLayout()

        btn_run = QPushButton("Запустить тестирование")
        btn_run.setStyleSheet("font-weight: bold; padding: 8px 16px;")
        btn_run.setDefault(True)

        btn_close = QPushButton("Закрыть")

        btn_layout.addWidget(btn_run)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

        dialog.setLayout(layout)

        def run_comprehensive_test():
            """Запуск комплексного теста"""
            output.clear()
            output.append("Запуск комплексного тестирования...")
            output.append("")

            # Блокируем кнопку во время теста
            btn_run.setEnabled(False)
            btn_run.setText("Тестирование...")

            try:
                from Daman_QGIS.tools.F_5_plagin.submodules.Fsm_5_2_T_comprehensive_runner import ComprehensiveTestRunner, TestLogger

                # Запускаем с LOG_LEVEL_ERROR (только ошибки)
                runner = ComprehensiveTestRunner(
                    self.iface,
                    log_level=TestLogger.LOG_LEVEL_ERROR,
                    skip_network_tests=skip_network_cb.isChecked()
                )

                # Запускаем все тесты
                runner.run_all_tests()

                # Выводим результат
                for line in runner.logger.get_log():
                    output.append(line)

            except Exception as e:
                output.append(f"КРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
                log_error(f"F_5_2: Критическая ошибка: {str(e)}")
                import traceback
                output.append(traceback.format_exc())

            finally:
                btn_run.setEnabled(True)
                btn_run.setText("Запустить тестирование")

        btn_run.clicked.connect(run_comprehensive_test)
        btn_close.clicked.connect(dialog.close)

        dialog.exec_()
