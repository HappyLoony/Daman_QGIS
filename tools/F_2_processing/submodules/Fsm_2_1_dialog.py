# -*- coding: utf-8 -*-
"""
Диалог для инструмента 2_1_Выборка ЗУ
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QMessageBox
)
from qgis.PyQt.QtCore import Qt


class Fsm_2_1_Dialog(QDialog):
    """Диалог выбора действий для инструмента 2_1_Выборка ЗУ"""

    def __init__(self, parent=None):
        """Инициализация диалога"""
        super().__init__(parent)
        self.setWindowTitle("F_2_1_Выборка")
        self.setModal(True)
        self.setMinimumWidth(450)

        # Результат выбора пользователя
        self.action_selected = None

        self._setup_ui()

    def _setup_ui(self):
        """Настройка интерфейса"""
        layout = QVBoxLayout(self)

        # Заголовок
        title_label = QLabel("<h3>Выборка объектов</h3>")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        layout.addSpacing(10)

        # Описание
        desc_label = QLabel(
            "Функция автоматически создаст выборки для всех доступных объектов:\n\n"
            "• Земельные участки (ЗУ):\n"
            "  - Le_2_1_1_1_Выборка_ЗУ (точная выборка)\n"
            "  - Le_2_1_1_2_Выборка_ЗУ_10_м (с буфером 10м)\n\n"
            "• Объекты капитального строительства (ОКС):\n"
            "  - L_2_1_2_Выборка_ОКС\n\n"
            "Выборка будет выполнена для тех слоёв, которые загружены в проект."
        )
        desc_label.setWordWrap(True)
        desc_label.setMargin(10)
        layout.addWidget(desc_label)

        # Кнопка "Выполнить выборку"
        self.btn_selection = QPushButton("Выполнить выборку")
        self.btn_selection.setMinimumHeight(40)
        self.btn_selection.clicked.connect(self._on_selection_clicked)
        layout.addWidget(self.btn_selection)

        # Добавляем отступ
        layout.addSpacing(20)

        # Кнопка отмены
        cancel_button = QPushButton("Отмена")
        cancel_button.clicked.connect(self.reject)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

    def _on_selection_clicked(self):
        """Обработчик нажатия кнопки 'Выполнить выборку'"""
        self.action_selected = "selection"
        self.accept()

    def get_selected_action(self):
        """Получить выбранное действие

        Returns:
            str: 'selection' или None
        """
        return self.action_selected
