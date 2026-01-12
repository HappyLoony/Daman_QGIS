# -*- coding: utf-8 -*-
"""
Msm_25_4 - Диалог ручной классификации прав на земельные участки

GUI для пользователя, позволяющий вручную классифицировать
участки, которые не удалось распознать автоматически.

Перенесено из Fsm_2_3_2_2_rights_classifier_dialog.py
"""

from typing import List, Dict, Any, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem,
    QGroupBox, QHeaderView
)
from qgis.core import QgsFeature

from Daman_QGIS.utils import log_info


class Msm_25_4_RightsDialog(QDialog):
    """Диалог для классификации одного неопознанного земельного участка по правам"""

    # Ключевые атрибуты для отображения (display_name, field_name)
    KEY_ATTRIBUTES = [
        ("Кадастровый номер", "КН"),
        ("Единый земельный", "ЕЗ"),
        ("Тип объекта", "Тип_объекта"),
        ("Адрес", "Адрес_Местоположения"),
        ("Категория", "Категория"),
        ("Использование (ВРИ)", "ВРИ"),
        ("Площадь, м2", "Площадь"),
        ("Права", "Права"),
        ("Обременения", "Обременения"),
        ("Собственники", "Собственники"),
        ("Арендаторы", "Арендаторы"),
        ("Статус", "Статус"),
    ]

    # Поля для выделения жёлтым (ключевые для классификации)
    HIGHLIGHT_FIELDS = ["Права", "Собственники", "Обременения", "Арендаторы"]

    def __init__(
        self,
        parent: Any,
        feature: QgsFeature,
        rights_layers: List[Dict[str, Any]],
        current_index: int,
        total_count: int
    ):
        """
        Инициализация диалога

        Args:
            parent: Родительское окно
            feature: Объект для классификации (QgsFeature)
            rights_layers: Список словарей с данными о слоях Права_ЗУ
            current_index: Номер текущего объекта (начиная с 1)
            total_count: Общее количество неопознанных объектов
        """
        super().__init__(parent)
        self.feature = feature
        self.rights_layers = rights_layers
        self.current_index = current_index
        self.total_count = total_count

        self.selected_layer: Optional[str] = None
        self.skip_all: bool = False

        self.setWindowTitle(f"Классификация прав ЗУ ({current_index} из {total_count})")
        self.setModal(True)
        self.setMinimumWidth(1000)
        self.setMinimumHeight(850)

        self._init_ui()

    def _init_ui(self):
        """Создание интерфейса"""
        layout = QVBoxLayout()

        # Заголовок
        title_label = QLabel(
            f"Неопознанный земельный участок ({self.current_index} из {self.total_count})"
        )
        title_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 10px;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        # Инструкция
        instruction_label = QLabel(
            "Не удалось автоматически определить права на земельный участок.\n"
            "Просмотрите атрибуты объекта и выберите подходящий слой из списка ниже."
        )
        instruction_label.setStyleSheet("padding: 5px; color: #555;")
        instruction_label.setWordWrap(True)
        layout.addWidget(instruction_label)

        # Группа с атрибутами
        attributes_group = QGroupBox("Атрибуты земельного участка")
        attributes_layout = QVBoxLayout()

        self.attributes_table = self._create_attributes_table()
        attributes_layout.addWidget(self.attributes_table)
        attributes_group.setLayout(attributes_layout)
        layout.addWidget(attributes_group)

        # Группа выбора слоя
        selection_group = QGroupBox("Выбор слоя прав на земельный участок")
        selection_layout = QVBoxLayout()

        selection_label = QLabel("Выберите слой, в который нужно поместить этот участок:")
        selection_label.setStyleSheet("padding: 5px;")
        selection_layout.addWidget(selection_label)

        self.layer_combo = self._create_layer_combo()
        selection_layout.addWidget(self.layer_combo)
        selection_group.setLayout(selection_layout)
        layout.addWidget(selection_group)

        # Кнопки
        buttons_layout = self._create_buttons_layout()
        layout.addLayout(buttons_layout)

        self.setLayout(layout)

    def _create_attributes_table(self) -> QTableWidget:
        """Создание таблицы атрибутов"""
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Атрибут", "Значение"])
        table.setRowCount(len(self.KEY_ATTRIBUTES))

        for row, (display_name, field_name) in enumerate(self.KEY_ATTRIBUTES):
            # Колонка 1: название атрибута
            key_item = QTableWidgetItem(display_name)
            key_item.setFlags(key_item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row, 0, key_item)

            # Колонка 2: значение
            value = self.feature.attribute(field_name) if self.feature else None
            value_str = str(value) if value is not None else ""
            value_item = QTableWidgetItem(value_str)
            value_item.setFlags(value_item.flags() & ~Qt.ItemIsEditable)

            # Выделяем ключевые поля для классификации
            if field_name in self.HIGHLIGHT_FIELDS:
                value_item.setBackground(Qt.yellow)

            table.setItem(row, 1, value_item)

        # Настройка ширины колонок
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)

        # Настройка высоты строк
        table.verticalHeader().setDefaultSectionSize(30)

        return table

    def _create_layer_combo(self) -> QComboBox:
        """Создание комбобокса для выбора слоя"""
        combo = QComboBox()

        # Сортируем слои по layer_num
        sorted_layers = sorted(
            self.rights_layers,
            key=lambda x: int(x.get('layer_num', '999'))
        )

        for layer_data in sorted_layers:
            layer_name_short = layer_data.get('layer', '')
            layer_name_full = layer_data.get('full_name', '')
            description = layer_data.get('description', '')

            # Показываем layer + description, храним full_name
            display_text = f"{layer_name_short} - {description}" if description else layer_name_short
            combo.addItem(display_text, layer_name_full)

        combo.setStyleSheet("QComboBox { padding: 5px; font-size: 11px; }")

        return combo

    def _create_buttons_layout(self) -> QHBoxLayout:
        """Создание панели кнопок"""
        layout = QHBoxLayout()

        # Кнопка "Пропустить"
        skip_btn = QPushButton("Пропустить (Сведения нет)")
        skip_btn.setToolTip("Пропустить этот участок, он попадёт в слой 'L_2_3_6_Права_ЗУ_Свед_нет'")
        skip_btn.clicked.connect(self._on_skip)
        layout.addWidget(skip_btn)

        # Кнопка "Пропустить все"
        skip_all_btn = QPushButton("Пропустить все (Сведения нет)")
        skip_all_btn.setToolTip("Пропустить все оставшиеся участки, они попадут в слой 'L_2_3_6_Права_ЗУ_Свед_нет'")
        skip_all_btn.clicked.connect(self._on_skip_all)
        layout.addWidget(skip_all_btn)

        layout.addStretch()

        # Кнопка "Применить"
        apply_btn = QPushButton("Применить")
        apply_btn.setToolTip("Поместить участок в выбранный слой")
        apply_btn.clicked.connect(self._on_apply)
        apply_btn.setDefault(True)
        apply_btn.setStyleSheet("QPushButton { font-weight: bold; padding: 8px 20px; }")
        layout.addWidget(apply_btn)

        return layout

    def _on_apply(self):
        """Обработчик кнопки 'Применить'"""
        self.selected_layer = self.layer_combo.currentData()
        log_info(f"Msm_25_4: Пользователь выбрал слой: {self.selected_layer}")
        self.accept()

    def _on_skip(self):
        """Обработчик кнопки 'Пропустить'"""
        self.selected_layer = None
        log_info("Msm_25_4: Пользователь пропустил объект")
        self.accept()

    def _on_skip_all(self):
        """Обработчик кнопки 'Пропустить все'"""
        self.selected_layer = None
        self.skip_all = True
        log_info("Msm_25_4: Пользователь выбрал 'Пропустить все'")
        self.accept()

    def get_result(self) -> tuple:
        """
        Получить результат выбора пользователя

        Returns:
            tuple: (selected_layer_full_name, skip_all_flag)
                   selected_layer_full_name - полное имя слоя или None
                   skip_all_flag - True если нажато "Пропустить все"
        """
        return self.selected_layer, self.skip_all


def show_rights_classification_dialog(
    parent,
    feature: QgsFeature,
    rights_layers: List[Dict[str, Any]],
    current_index: int,
    total_count: int
) -> tuple:
    """
    Показать диалог классификации прав

    Удобная функция-обёртка для вызова диалога

    Args:
        parent: Родительское окно (обычно iface.mainWindow())
        feature: Объект для классификации
        rights_layers: Конфигурация слоёв прав из Base_layers.json
        current_index: Текущий номер объекта (1-based)
        total_count: Общее количество неопознанных объектов

    Returns:
        tuple: (selected_layer, skip_all, dialog_accepted)
            - selected_layer: str или None
            - skip_all: bool
            - dialog_accepted: bool
    """
    dialog = Msm_25_4_RightsDialog(
        parent=parent,
        feature=feature,
        rights_layers=rights_layers,
        current_index=current_index,
        total_count=total_count
    )

    accepted = dialog.exec_()
    selected_layer, skip_all = dialog.get_result()

    return selected_layer, skip_all, bool(accepted)
