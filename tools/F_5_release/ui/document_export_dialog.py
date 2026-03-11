# -*- coding: utf-8 -*-
"""
Диалог выбора документов для экспорта

Функциональность:
    - Отображение слоёв с доступными шаблонами из TemplateRegistry
    - Выбор типа документа: ведомость / перечень координат
    - Опция создания версии WGS-84 для перечней координат
    - Информация о папке сохранения

Шаблоны: Fsm_5_3_8_template_registry.py (DocumentTemplate, TemplateRegistry)
"""

from typing import List, Dict, Any

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QGroupBox, QScrollArea, QWidget, QComboBox
)
from qgis.PyQt.QtCore import Qt

from Daman_QGIS.core.base_responsive_dialog import BaseResponsiveDialog

from ..submodules.Fsm_5_3_8_template_registry import (
    DocumentTemplate, TemplateRegistry
)


class DocumentExportDialog(BaseResponsiveDialog):
    """Диалог выбора документов для экспорта"""

    # Адаптивные размеры диалога
    WIDTH_RATIO = 0.50
    HEIGHT_RATIO = 0.65
    MIN_WIDTH = 600
    MAX_WIDTH = 900
    MIN_HEIGHT = 450
    MAX_HEIGHT = 700

    def __init__(
        self,
        parent=None,
        output_folder: str = ""
    ):
        """
        Инициализация диалога

        Args:
            parent: Родительский виджет
            output_folder: Путь к папке сохранения
        """
        super().__init__(parent)
        self.output_folder = output_folder
        self.layer_widgets: List[tuple] = []  # [(layer, checkbox, combo, templates), ...]
        self.create_wgs84_checkbox = None

        self.setWindowTitle("Экспорт документов по шаблону")

        self._init_ui()

    def _init_ui(self):
        """Инициализация интерфейса"""
        layout = QVBoxLayout()

        # === ЗАГОЛОВОК ===
        header_label = QLabel("<b>Выберите документы для экспорта:</b>")
        layout.addWidget(header_label)

        # === СПИСОК СЛОЁВ (SCROLL AREA) ===
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumHeight(300)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout()
        scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Собираем слои с доступными шаблонами
        layers_data = self._collect_layers_with_templates()

        if not layers_data:
            no_layers_label = QLabel(
                "<i>Нет слоёв с доступными шаблонами документов</i>"
            )
            no_layers_label.setStyleSheet("color: #999; padding: 20px;")
            scroll_layout.addWidget(no_layers_label)
        else:
            for layer_data in layers_data:
                widget = self._create_layer_widget(layer_data)
                scroll_layout.addWidget(widget)

        scroll_widget.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

        # === ОПЦИИ ===
        options_group = QGroupBox("Опции")
        options_layout = QVBoxLayout()

        self.create_wgs84_checkbox = QCheckBox(
            "Создать версию в WGS-84 для перечней координат"
        )
        self.create_wgs84_checkbox.setChecked(False)
        options_layout.addWidget(self.create_wgs84_checkbox)

        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

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
            folder_info = QLabel(
                f"<i>Файлы будут сохранены в: {self.output_folder}</i>"
            )
            folder_info.setStyleSheet("color: #555; padding: 10px;")
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

    def _collect_layers_with_templates(self) -> List[Dict[str, Any]]:
        """
        Собрать слои с доступными шаблонами из TemplateRegistry

        Returns:
            Список [{layer, templates: [DocumentTemplate, ...]}]
        """
        result: List[Dict[str, Any]] = []

        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if layer.featureCount() == 0:
                continue

            templates = TemplateRegistry.get_templates_for_layer(layer.name())
            if templates:
                result.append({
                    'layer': layer,
                    'templates': templates
                })

        return result

    def _create_layer_widget(self, layer_data: Dict[str, Any]) -> QGroupBox:
        """
        Создать виджет для одного слоя

        Args:
            layer_data: {layer, templates: [DocumentTemplate, ...]}

        Returns:
            QGroupBox с чекбоксом и выбором типа документа
        """
        layer = layer_data['layer']
        templates: List[DocumentTemplate] = layer_data['templates']

        group_box = QGroupBox()
        layout = QHBoxLayout()

        # Чекбокс с именем слоя
        checkbox = QCheckBox(layer.name())
        checkbox.setChecked(False)
        checkbox.setMinimumWidth(300)
        layout.addWidget(checkbox)

        # Комбобокс для выбора шаблона
        combo = QComboBox()
        combo.setMinimumWidth(250)
        for template in templates:
            combo.addItem(template.name, template)
        layout.addWidget(combo)

        # Если только 1 шаблон - скрываем комбобокс, показываем label
        if len(templates) == 1:
            info_label = QLabel(f"<i>({templates[0].name})</i>")
            info_label.setStyleSheet("color: #666;")
            layout.addWidget(info_label)
            combo.setVisible(False)

        layout.addStretch()

        group_box.setLayout(layout)

        # Сохраняем ссылки для получения выбора
        self.layer_widgets.append((layer, checkbox, combo, templates))

        return group_box

    def _select_all(self):
        """Выбрать все слои"""
        for _layer, checkbox, _combo, _templates in self.layer_widgets:
            checkbox.setChecked(True)

    def _deselect_all(self):
        """Снять выбор со всех слоёв"""
        for _layer, checkbox, _combo, _templates in self.layer_widgets:
            checkbox.setChecked(False)

    def get_selected_items(self) -> List[Dict[str, Any]]:
        """
        Получить список выбранных элементов

        Returns:
            Список [{layer: QgsVectorLayer, template: DocumentTemplate}]
        """
        selected: List[Dict[str, Any]] = []

        for layer, checkbox, combo, templates in self.layer_widgets:
            if checkbox.isChecked():
                # Получаем выбранный шаблон
                if len(templates) == 1:
                    template = templates[0]
                else:
                    template = combo.currentData()

                if template:
                    selected.append({
                        'layer': layer,
                        'template': template,
                    })

        return selected

    def get_create_wgs84(self) -> bool:
        """
        Получить значение опции создания WGS-84

        Returns:
            True если нужно создавать версию WGS-84
        """
        return self.create_wgs84_checkbox.isChecked() if self.create_wgs84_checkbox else False
