# -*- coding: utf-8 -*-
"""
Fsm_6_5_5: Диалог подтверждения принудительного закрытия файлов.

Показывает список файлов и предупреждение о потере данных.
"""

from typing import List, Optional

from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .Fsm_6_5_2_scanner import LockedFile


class Fsm_6_5_5_ConfirmDialog(QDialog):
    """Диалог подтверждения перед принудительным закрытием."""

    def __init__(
        self,
        files: List[LockedFile],
        parent: Optional[QDialog] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Принудительное закрытие файлов")
        self.setMinimumWidth(550)
        self.setMinimumHeight(300)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Предупреждение
        warning = QLabel(
            "<b>ВНИМАНИЕ:</b> Несохранённые данные будут потеряны "
            "у пользователей, чьи файлы будут закрыты!"
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #CC0000; padding: 4px;")
        layout.addWidget(warning)

        # Заголовок списка
        count_label = QLabel(f"Будут закрыты ({len(files)} файлов):")
        count_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(count_label)

        # Таблица файлов
        table = QTableWidget()
        columns = ["Файл", "Пользователь", "Компьютер"]
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setRowCount(len(files))
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.verticalHeader().setVisible(False)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        for row, lf in enumerate(files):
            table.setItem(row, 0, QTableWidgetItem(lf.file_name))
            table.setItem(row, 1, QTableWidgetItem(lf.locked_by_user))
            table.setItem(row, 2, QTableWidgetItem(lf.locked_by_host))

        layout.addWidget(table, stretch=1)

        # Кнопки
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_close = QPushButton("Закрыть файлы")
        btn_close.setStyleSheet(
            "QPushButton { background-color: #CC3333; color: white; "
            "padding: 6px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #AA2222; }"
        )
        btn_close.clicked.connect(self.accept)

        btn_cancel = QPushButton("Отмена")
        btn_cancel.setMinimumWidth(80)
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(btn_close)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
