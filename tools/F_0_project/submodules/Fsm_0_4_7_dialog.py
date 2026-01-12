# -*- coding: utf-8 -*-
"""
Диалог проверки топологии с двумя этапами
Stage 1: Обнаружение ошибок
Stage 2: Исправление ошибок (активируется после Stage 1)
"""

from typing import Dict, List, Optional
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTextEdit
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.core import QgsVectorLayer


class Fsm_0_4_7_TopologyCheckDialog(QDialog):
    """
    Диалог двухэтапной проверки топологии

    Кнопки:
    1. "Проверить" - Stage 1 (обнаружение)
    2. "Исправить" - Stage 2 (исправление, изначально заблокирована)
    """

    # Сигналы для коммуникации с F_0_4
    check_requested = pyqtSignal()  # Запрос на проверку (Stage 1), всегда async через M_17
    fix_requested = pyqtSignal()    # Запрос на исправление (Stage 2)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Проверка топологии")
        self.resize(600, 400)

        # Данные о найденных ошибках
        self.check_results = None
        self.fixable_errors_found = False

        self._setup_ui()

    def _setup_ui(self):
        """Настройка UI"""
        layout = QVBoxLayout()

        # Заголовок
        title = QLabel("<h2>Проверка топологии</h2>")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Описание
        description = QLabel(
            "<b>Этап 1:</b> Обнаружение топологических ошибок<br>"
            "<b>Этап 2:</b> Автоматическое исправление (доступно после проверки)<br>"
            "<i>Проверка выполняется в фоновом режиме через QgsTask (не блокирует интерфейс)</i>"
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        # Текстовое поле для результатов
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setPlaceholderText(
            "Нажмите 'Проверить' для начала проверки топологии всех слоёв проекта"
        )
        # CSS стили для компактного отображения (уменьшенные отступы)
        self.results_text.setStyleSheet("""
            QTextEdit {
                font-family: Consolas, 'Courier New', monospace;
                font-size: 9pt;
                line-height: 1.2;
            }
        """)
        # HTML стили для уменьшения отступов у параграфов
        self.results_text.document().setDefaultStyleSheet("""
            p { margin: 2px 0px; padding: 0px; }
            h3 { margin: 4px 0px 2px 0px; padding: 0px; }
        """)
        layout.addWidget(self.results_text)

        # Кнопки
        buttons_layout = QHBoxLayout()

        self.check_button = QPushButton("Проверить топологию")
        self.check_button.setToolTip("Stage 1: Обнаружение ошибок")
        self.check_button.clicked.connect(self._on_check_clicked)
        buttons_layout.addWidget(self.check_button)

        self.fix_button = QPushButton("Исправить ошибки")
        self.fix_button.setToolTip("Stage 2: Автоматическое исправление (временно отключено)")
        # TODO: Функция автоисправления требует тестирования перед включением.
        # После тестирования Fsm_0_4_6_fixer.py раскомментировать строки 190 и 245
        # для разблокировки кнопки после проверки.
        self.fix_button.setEnabled(False)  # Заблокирована навсегда до тестирования
        # self.fix_button.clicked.connect(self._on_fix_clicked)  # Отключено до тестирования
        buttons_layout.addWidget(self.fix_button)

        self.close_button = QPushButton("Закрыть")
        self.close_button.clicked.connect(self.close)
        buttons_layout.addWidget(self.close_button)

        layout.addLayout(buttons_layout)

        self.setLayout(layout)

    def _on_check_clicked(self):
        """Обработка нажатия 'Проверить'"""
        # Блокируем кнопки на время проверки
        self.check_button.setEnabled(False)
        self.fix_button.setEnabled(False)

        # Очищаем результаты
        self.results_text.clear()

        self.results_text.append("<p><b>Запуск проверки топологии...</b></p>")
        self.results_text.append("<p><i>Проверка выполняется в фоновом режиме. "
                                "Вы можете продолжать работу в QGIS.</i></p>")

        # Прогресс отображается через QgsMessageBar (M_17 AsyncTaskManager)

        # Эмитируем сигнал для F_0_4 (всегда async)
        self.check_requested.emit()

    def _on_fix_clicked(self):
        """Обработка нажатия 'Исправить'"""
        # Блокируем кнопки на время исправления
        self.check_button.setEnabled(False)
        self.fix_button.setEnabled(False)

        # Обновляем текст
        self.results_text.append("<p style='margin-top: 8px;'><b>Запуск исправления ошибок...</b></p>")

        # Прогресс теперь отображается через QgsMessageBar (в F_0_4)

        # Эмитируем сигнал для F_0_4
        self.fix_requested.emit()

    def on_check_completed(self, errors_by_layer: Dict, total_errors: int,
                          fixable_errors_count: int):
        """
        Вызывается после завершения Stage 1

        Args:
            errors_by_layer: Ошибки по слоям
            total_errors: Всего ошибок
            fixable_errors_count: Количество автоматически исправляемых ошибок
        """
        # Прогресс скрывается в F_0_4 (QgsMessageBar)

        # Разблокируем кнопку проверки
        self.check_button.setEnabled(True)

        # Сохраняем результаты
        self.check_results = errors_by_layer
        self.fixable_errors_found = fixable_errors_count > 0

        # Формируем отчёт
        self.results_text.clear()
        self.results_text.append("<h3>Результаты проверки топологии</h3>")

        if total_errors == 0:
            self.results_text.append(
                "<p style='color: green;'><b>✓ Топологические ошибки не обнаружены!</b></p>"
            )
            self.fix_button.setEnabled(False)
            return

        self.results_text.append(f"<p><b>Обнаружено ошибок: {total_errors}</b></p>")

        # Детализация по слоям
        for layer_name, errors in errors_by_layer.items():
            self.results_text.append(f"<p><b>Слой:</b> {layer_name}</p>")

            for error in errors:
                error_type = error.get('error_type', 'unknown')
                error_count = error.get('error_count', 0)
                can_fix = error.get('can_auto_fix', False)

                fix_status = "✓ Авто" if can_fix else "✗ Вручную"
                color = "green" if can_fix else "orange"

                self.results_text.append(
                    f"<p>  • {error_type}: <b>{error_count}</b> "
                    f"<span style='color: {color};'>({fix_status})</span></p>"
                )

        # Активируем кнопку исправления если есть автоматически исправляемые ошибки
        if fixable_errors_count > 0:
            self.results_text.append(
                f"<p style='color: blue; margin-top: 6px;'><b>→ Доступно автоматическое исправление "
                f"для {fixable_errors_count} ошибок</b></p>"
            )
            # self.fix_button.setEnabled(True)  # Отключено до тестирования Fsm_0_4_6_fixer.py
        else:
            self.results_text.append(
                "<p style='color: orange; margin-top: 6px;'><b>! Все ошибки требуют ручного исправления</b></p>"
            )
            self.fix_button.setEnabled(False)

    def on_fix_completed(self, fixes_applied: int, fixes_by_type: Dict):
        """
        Вызывается после завершения Stage 2

        Args:
            fixes_applied: Количество применённых исправлений
            fixes_by_type: Исправления по типам
        """
        # Прогресс скрывается в F_0_4 (QgsMessageBar)

        # Разблокируем кнопки
        self.check_button.setEnabled(True)
        self.fix_button.setEnabled(False)  # Блокируем до новой проверки

        # Добавляем результаты исправления
        self.results_text.append("<h3 style='margin-top: 8px;'>Результаты исправления</h3>")

        if fixes_applied == 0:
            self.results_text.append(
                "<p style='color: orange;'><b>! Исправления не применены</b></p>"
            )
            return

        self.results_text.append(
            f"<p style='color: green;'><b>✓ Применено исправлений: {fixes_applied}</b></p>"
        )

        # Детализация по типам
        for fix_type, count in fixes_by_type.items():
            if count > 0:
                self.results_text.append(f"<p>  • {fix_type}: <b>{count}</b></p>")

        self.results_text.append(
            "<p style='margin-top: 6px;'><i>Слои ошибок обновлены. Запустите проверку заново для подтверждения.</i></p>"
        )

    def on_error(self, error_message: str):
        """
        Вызывается при ошибке

        Args:
            error_message: Сообщение об ошибке
        """
        # Прогресс скрывается в F_0_4 (QgsMessageBar)

        # Разблокируем кнопки
        self.check_button.setEnabled(True)
        # if self.fixable_errors_found:
        #     self.fix_button.setEnabled(True)  # Отключено до тестирования Fsm_0_4_6_fixer.py

        # Показываем ошибку
        self.results_text.append(
            f"<p style='color: red; margin-top: 6px;'><b>✗ Ошибка: {error_message}</b></p>"
        )
