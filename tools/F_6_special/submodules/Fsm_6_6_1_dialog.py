# -*- coding: utf-8 -*-
"""
Fsm_6_6_1: Диалог выбора схем мастер-плана.

Показывает чекбоксы доступных схем (drawing_name из Base_drawings)
и позволяет выбрать папку экспорта.
"""

import os
from typing import List, Dict, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QDialogButtonBox,
    QGroupBox, QCheckBox, QScrollArea, QWidget,
    QFileDialog, QLineEdit
)
from qgis.core import QgsProject

from Daman_QGIS.utils import log_info, log_warning
from Daman_QGIS.core.base_responsive_dialog import BaseResponsiveDialog


class Fsm_6_6_1_Dialog(BaseResponsiveDialog):
    """Диалог выбора схем для мастер-плана."""

    WIDTH_RATIO = 0.35
    HEIGHT_RATIO = 0.5
    MIN_WIDTH = 500
    MAX_WIDTH = 700
    MIN_HEIGHT = 400
    MAX_HEIGHT = 650

    def __init__(self, available_drawings: List[Dict], parent=None):
        """
        Инициализация диалога.

        Args:
            available_drawings: Список доступных чертежей из Base_drawings.json
            parent: Родительский виджет
        """
        super().__init__(parent)
        self.setWindowTitle("Мастер-план - Выбор схем")

        self._available_drawings = available_drawings
        self._checkboxes: List[QCheckBox] = []
        self._output_folder: Optional[str] = None

        self._init_ui()

    def _init_ui(self) -> None:
        """Инициализация интерфейса."""
        layout = QVBoxLayout()

        # Заголовок
        title_label = QLabel("Выберите схемы для генерации:")
        title_label.setStyleSheet("font-weight: bold; font-size: 11pt;")
        layout.addWidget(title_label)

        # Информация
        info_label = QLabel(
            "Отображаются только схемы, для которых все необходимые слои "
            "загружены в текущий проект."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(info_label)

        # Счётчик
        self._counter_label = QLabel(f"Выбрано: 0 / {len(self._available_drawings)}")
        self._counter_label.setStyleSheet("color: #0066cc; font-weight: bold;")
        layout.addWidget(self._counter_label)

        # Группа чекбоксов с прокруткой
        schemes_group = QGroupBox("Доступные схемы")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(200)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        # Кнопки выбрать все / снять все
        select_buttons_layout = QHBoxLayout()
        btn_select_all = QPushButton("Выбрать все")
        btn_select_all.clicked.connect(self._select_all)
        select_buttons_layout.addWidget(btn_select_all)

        btn_deselect_all = QPushButton("Снять все")
        btn_deselect_all.clicked.connect(self._deselect_all)
        select_buttons_layout.addWidget(btn_deselect_all)

        select_buttons_layout.addStretch()
        scroll_layout.addLayout(select_buttons_layout)

        # Чекбоксы для каждой схемы
        for drawing in self._available_drawings:
            drawing_name = drawing.get('drawing_name', 'Без названия')
            visible_layers = drawing.get('visible_layers', [])

            cb = QCheckBox(drawing_name)
            cb.setToolTip(f"Слои: {', '.join(visible_layers)}")
            cb.setChecked(True)  # По умолчанию все выбраны
            cb.stateChanged.connect(self._update_counter)
            self._checkboxes.append(cb)
            scroll_layout.addWidget(cb)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)

        group_layout = QVBoxLayout()
        group_layout.addWidget(scroll)
        schemes_group.setLayout(group_layout)
        layout.addWidget(schemes_group)

        # Выбор папки экспорта
        folder_group = QGroupBox("Папка экспорта")
        folder_layout = QHBoxLayout()

        self._folder_edit = QLineEdit()
        self._folder_edit.setReadOnly(True)
        self._folder_edit.setPlaceholderText("Выберите папку...")

        # Значение по умолчанию: папка проекта / Мастер-план
        default_folder = self._get_default_folder()
        if default_folder:
            self._folder_edit.setText(default_folder)
            self._output_folder = default_folder

        folder_layout.addWidget(self._folder_edit)

        btn_browse = QPushButton("Обзор...")
        btn_browse.clicked.connect(self._browse_folder)
        folder_layout.addWidget(btn_browse)

        folder_group.setLayout(folder_layout)
        layout.addWidget(folder_group)

        # Кнопки OK / Отмена
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Генерировать")
        button_box.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        layout.addWidget(button_box)

        self.setLayout(layout)
        self._update_counter()

    def _get_default_folder(self) -> Optional[str]:
        """Получить папку по умолчанию (проект / Мастер-план)."""
        try:
            project_home = QgsProject.instance().homePath()
            if project_home:
                path = os.path.join(project_home, "Мастер-план")
                return os.path.normpath(path)
        except Exception:
            pass
        return None

    def _browse_folder(self) -> None:
        """Выбор папки через диалог."""
        start_dir = self._folder_edit.text() or QgsProject.instance().homePath() or ""
        folder = QFileDialog.getExistingDirectory(
            self, "Выберите папку для экспорта", start_dir
        )
        if folder:
            self._folder_edit.setText(folder)
            self._output_folder = folder

    def _select_all(self) -> None:
        """Выбрать все чекбоксы."""
        for cb in self._checkboxes:
            cb.setChecked(True)

    def _deselect_all(self) -> None:
        """Снять все чекбоксы."""
        for cb in self._checkboxes:
            cb.setChecked(False)

    def _update_counter(self) -> None:
        """Обновить счётчик выбранных схем."""
        selected = sum(1 for cb in self._checkboxes if cb.isChecked())
        total = len(self._checkboxes)
        self._counter_label.setText(f"Выбрано: {selected} / {total}")

        if selected == 0:
            color = "#cc0000"
        else:
            color = "#0066cc"
        self._counter_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def get_selected_drawings(self) -> List[Dict]:
        """
        Получить список выбранных чертежей.

        Returns:
            Список выбранных записей из Base_drawings.json
        """
        selected = []
        for i, cb in enumerate(self._checkboxes):
            if cb.isChecked():
                selected.append(self._available_drawings[i])
        return selected

    def get_output_folder(self) -> Optional[str]:
        """
        Получить выбранную папку экспорта.

        Returns:
            Путь к папке или None
        """
        text = self._folder_edit.text().strip()
        return text if text else self._output_folder

    def accept(self) -> None:
        """Обработка нажатия OK."""
        selected = self.get_selected_drawings()
        folder = self.get_output_folder()

        if not selected:
            log_warning("Fsm_6_6_1: Не выбрано ни одной схемы")
            return

        if not folder:
            log_warning("Fsm_6_6_1: Не указана папка экспорта")
            return

        log_info(f"Fsm_6_6_1: Выбрано {len(selected)} схем, папка: {folder}")
        super().accept()
