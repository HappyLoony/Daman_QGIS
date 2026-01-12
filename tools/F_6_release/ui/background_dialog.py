# -*- coding: utf-8 -*-
"""
Диалог выбора подложек для экспорта в DXF

Функциональность:
    - Динамическая загрузка шаблонов из Base_drawings_background.json через менеджер
    - Отображение списка всех доступных шаблонов подложек
    - Множественный выбор с чекбоксами (по умолчанию все выключены)
    - Автоматическое сохранение в папку "Подложки" рядом с project.gpkg
"""

from typing import List, Dict, Any, Optional

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QScrollArea, QWidget
)
from qgis.PyQt.QtCore import Qt


class BackgroundExportDialog(QDialog):
    """Диалог выбора подложек для экспорта"""

    def __init__(self, parent=None, templates: Optional[List[Dict[str, Any]]] = None, output_folder: str = ""):
        """
        Инициализация диалога

        Args:
            parent: Родительский виджет
            templates: Список шаблонов подложек из Base_drawings_background.json
            output_folder: Путь к папке "Подложки" (автоматически определяется)
        """
        super().__init__(parent)
        self.templates = templates or []
        self.checkboxes = {}  # {template_index: QCheckBox}
        self.output_folder = output_folder

        self.setWindowTitle("Экспорт подложек в DXF")
        self.setMinimumWidth(350)
        self.setMinimumHeight(300)

        self._init_ui()

    def _init_ui(self):
        """Инициализация интерфейса"""
        layout = QVBoxLayout()

        # === ЗАГОЛОВОК ===
        header_label = QLabel("<b>Выберите подложки для экспорта:</b>")
        layout.addWidget(header_label)

        # === СПИСОК ПОДЛОЖЕК (SCROLL AREA) ===
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumHeight(150)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout()
        scroll_layout.setAlignment(Qt.AlignTop)
        scroll_layout.setSpacing(4)

        # Создаём чекбоксы для каждой подложки
        for idx, template in enumerate(self.templates):
            checkbox = self._create_checkbox(idx, template)
            scroll_layout.addWidget(checkbox)

        scroll_widget.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

        # === ВЫБОР ВСЕХ / СНЯТЬ ВСЕ ===
        selection_layout = QHBoxLayout()

        select_all_btn = QPushButton("Выбрать все")
        select_all_btn.clicked.connect(self._select_all)
        selection_layout.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("Снять все")
        deselect_all_btn.clicked.connect(self._deselect_all)
        selection_layout.addWidget(deselect_all_btn)

        selection_layout.addStretch()
        layout.addLayout(selection_layout)

        # === ИНФОРМАЦИЯ О ПАПКЕ СОХРАНЕНИЯ ===
        if self.output_folder:
            folder_info = QLabel(f"<i>Сохранение в: {self.output_folder}</i>")
            folder_info.setStyleSheet("color: #555; padding: 5px;")
            folder_info.setWordWrap(True)
            layout.addWidget(folder_info)

        # === КНОПКИ OK / CANCEL ===
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        ok_btn = QPushButton("Экспортировать")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        buttons_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_btn)

        layout.addLayout(buttons_layout)

        self.setLayout(layout)

    def _create_checkbox(self, idx: int, template: Dict[str, Any]) -> QCheckBox:
        """
        Создать чекбокс для одной подложки

        Args:
            idx: Индекс шаблона в списке
            template: Данные шаблона

        Returns:
            QCheckBox для выбора подложки
        """
        name = template.get('name', 'Unknown')
        layers = template.get('layers', [])

        checkbox = QCheckBox(name)
        checkbox.setChecked(False)  # По умолчанию выключен

        # Отключаем чекбокс если нет слоёв
        if not layers:
            checkbox.setEnabled(False)
            checkbox.setToolTip("Подложка не содержит слоёв")

        self.checkboxes[idx] = checkbox
        return checkbox

    def _select_all(self):
        """Выбрать все подложки"""
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(True)

    def _deselect_all(self):
        """Снять выбор со всех подложек"""
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(False)

    def get_selected_templates(self) -> List[Dict[str, Any]]:
        """
        Получить список выбранных шаблонов

        Returns:
            Список выбранных шаблонов подложек
        """
        selected = []
        for idx, checkbox in self.checkboxes.items():
            if checkbox.isChecked():
                selected.append(self.templates[idx])
        return selected

    def get_output_folder(self) -> str:
        """
        Получить выбранную папку для сохранения

        Returns:
            Путь к папке
        """
        return self.output_folder
