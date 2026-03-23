# -*- coding: utf-8 -*-
"""
Fsm_1_1_6_ZprAttributeDialog - Диалог ввода атрибутов контура ЗПР

Per-feature диалог для заполнения обязательных полей ЗПР:
ID, ID_KV, VRI (комбобокс из VRI.json), MIN_AREA_VRI.

Паттерн: аналогичен Fsm_1_2_1_zouit_classifier_dialog.py
(навигация по объектам, Skip/Skip All/Apply).
"""

from typing import Dict, List, Optional, Any, Tuple

from qgis.core import QgsFeature
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QComboBox, QLineEdit,
    QGroupBox, QCompleter,
)

from Daman_QGIS.core.base_responsive_dialog import BaseResponsiveDialog


class Fsm_1_1_6_ZprAttributeDialog(BaseResponsiveDialog):
    """Диалог ввода атрибутов одного контура ЗПР"""

    SIZING_MODE = 'screen'
    WIDTH_RATIO = 0.40
    HEIGHT_RATIO = 0.45
    MIN_WIDTH = 500
    MAX_WIDTH = 800
    MIN_HEIGHT = 350
    MAX_HEIGHT = 600

    def __init__(
        self,
        parent: Any,
        feature: QgsFeature,
        invalid_fields: Dict[str, Dict[str, Any]],
        vri_list: List[Dict],
        current_index: int,
        total_count: int,
        layer_name: str,
    ) -> None:
        """
        Args:
            parent: Родительское окно
            feature: Feature для редактирования
            invalid_fields: {field_name: {current_value, error}}
            vri_list: Все записи VRI из VRI.json
            current_index: Номер текущего объекта (1-based)
            total_count: Общее количество невалидных объектов
            layer_name: Имя слоя ЗПР
        """
        super().__init__(parent)
        self.feature = feature
        self.invalid_fields = invalid_fields
        self.vri_list = vri_list
        self.current_index = current_index
        self.total_count = total_count
        self.layer_name = layer_name

        self.result_values: Dict[str, str] = {}
        self.skip_all = False
        self.skipped = False

        # Виджеты полей
        self._id_edit: Optional[QLineEdit] = None
        self._id_kv_edit: Optional[QLineEdit] = None
        self._vri_combo: Optional[QComboBox] = None
        self._min_area_edit: Optional[QLineEdit] = None

        self.setWindowTitle(
            f"Атрибуты ЗПР ({current_index} из {total_count})"
        )
        self.setModal(True)
        self.init_ui()

    def init_ui(self) -> None:
        """Создание интерфейса"""
        layout = QVBoxLayout()

        # Заголовок
        title_label = QLabel(
            f"Атрибуты контура ЗПР ({self.current_index} из {self.total_count})"
        )
        title_label.setStyleSheet(
            "font-size: 14px; font-weight: bold; padding: 10px;"
        )
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # Информация о контуре
        area_text = self._get_feature_area()
        info_label = QLabel(
            f"Слой: {self.layer_name} | {area_text}"
        )
        info_label.setStyleSheet("padding: 5px; color: #555;")
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info_label)

        # Инструкция
        instruction_label = QLabel(
            "Заполните атрибуты контура ЗПР. "
            "Невалидные поля выделены."
        )
        instruction_label.setStyleSheet("padding: 5px; color: #666;")
        instruction_label.setWordWrap(True)
        layout.addWidget(instruction_label)

        # Группа атрибутов
        attrs_group = QGroupBox("Атрибуты контура")
        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        # ID
        self._id_edit = QLineEdit()
        id_row = self._create_field_row(
            'ID', self._id_edit
        )
        form_layout.addRow("ID:", id_row)

        # ID_KV
        self._id_kv_edit = QLineEdit()
        id_kv_row = self._create_field_row(
            'ID_KV', self._id_kv_edit
        )
        form_layout.addRow("ID_KV:", id_kv_row)

        # VRI (комбобокс)
        self._vri_combo = self._build_vri_combobox()
        vri_row = self._create_field_row(
            'VRI', self._vri_combo
        )
        form_layout.addRow("VRI:", vri_row)

        # MIN_AREA_VRI
        self._min_area_edit = QLineEdit()
        min_area_row = self._create_field_row(
            'MIN_AREA_VRI', self._min_area_edit
        )
        form_layout.addRow("MIN_AREA_VRI:", min_area_row)

        attrs_group.setLayout(form_layout)
        layout.addWidget(attrs_group)

        # Растяжка
        layout.addStretch()

        # Кнопки
        buttons_layout = QHBoxLayout()

        skip_btn = QPushButton("Пропустить")
        skip_btn.setToolTip(
            "Пропустить этот контур без заполнения атрибутов"
        )
        skip_btn.clicked.connect(self.on_skip)
        buttons_layout.addWidget(skip_btn)

        skip_all_btn = QPushButton("Пропустить все")
        skip_all_btn.setToolTip(
            "Пропустить все оставшиеся контуры без заполнения"
        )
        skip_all_btn.clicked.connect(self.on_skip_all)
        buttons_layout.addWidget(skip_all_btn)

        buttons_layout.addStretch()

        apply_btn = QPushButton("Применить")
        apply_btn.setToolTip("Записать введённые значения в атрибуты контура")
        apply_btn.clicked.connect(self.on_apply)
        apply_btn.setDefault(True)
        apply_btn.setStyleSheet(
            "QPushButton { font-weight: bold; padding: 8px 20px; }"
        )
        buttons_layout.addWidget(apply_btn)

        layout.addLayout(buttons_layout)
        self.setLayout(layout)

    def _get_feature_area(self) -> str:
        """Получить текст площади feature.

        Returns:
            Строка вида 'Площадь: 1234.56 кв.м' или 'Без геометрии'
        """
        if not self.feature.hasGeometry():
            return "Без геометрии"

        geom = self.feature.geometry()
        if geom.isEmpty():
            return "Без геометрии"

        area = geom.area()
        if area > 0:
            return f"Площадь: {area:.2f} кв.м"
        else:
            length = geom.length()
            if length > 0:
                return f"Длина: {length:.2f} м"
            return "Точечный объект"

    def _create_field_row(
        self,
        field_name: str,
        widget: Any,
    ) -> QHBoxLayout:
        """Создание строки поля: виджет + индикатор ошибки.

        Args:
            field_name: Имя поля
            widget: QLineEdit или QComboBox

        Returns:
            QHBoxLayout со виджетом и индикатором
        """
        row = QHBoxLayout()
        row.addWidget(widget, stretch=1)

        # Индикатор ошибки
        if field_name in self.invalid_fields:
            info = self.invalid_fields[field_name]
            error = info.get('error', 'empty')
            current = info.get('current_value')

            if error == 'empty':
                error_text = "пустое значение"
            elif error == 'invalid_vri':
                error_text = f"невалидный ВРИ: {current}" if current else "невалидный ВРИ"
            else:
                error_text = "невалидно"

            error_label = QLabel(f"(!) {error_text}")
            error_label.setStyleSheet(
                "color: #cc0000; font-size: 11px; padding-left: 5px;"
            )
            row.addWidget(error_label)

            # Pre-fill текущим значением если есть
            if current:
                if isinstance(widget, QLineEdit):
                    widget.setText(current)
                elif isinstance(widget, QComboBox):
                    # Попробуем найти в items
                    idx = widget.findText(current)
                    if idx >= 0:
                        widget.setCurrentIndex(idx)
                    else:
                        widget.setEditText(current)
        else:
            # Поле валидно — показываем текущее значение
            field_idx = self.feature.fields().indexOf(field_name)
            if field_idx >= 0:
                value = self.feature.attribute(field_idx)
                if value is not None and str(value).strip():
                    str_value = str(value).strip()
                    if isinstance(widget, QLineEdit):
                        widget.setText(str_value)
                    elif isinstance(widget, QComboBox):
                        idx = widget.findText(str_value)
                        if idx >= 0:
                            widget.setCurrentIndex(idx)

        return row

    def _build_vri_combobox(self) -> QComboBox:
        """Создание комбобокса VRI с поиском по подстроке.

        Returns:
            Настроенный QComboBox
        """
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.setStyleSheet("QComboBox { padding: 4px; }")

        # Пустой элемент
        combo.addItem("--- Выберите ВРИ ---", "")

        # Сортировка по коду
        sorted_vri = sorted(
            self.vri_list,
            key=lambda v: self._sort_vri_key(v.get('code', ''))
        )

        # Добавляем элементы
        for vri in sorted_vri:
            full_name = vri.get('full_name', '')
            if full_name:
                combo.addItem(full_name, full_name)

        # Настраиваем QCompleter для поиска по подстроке
        completer = QCompleter()
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setModel(combo.model())
        completer.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion
        )
        combo.setCompleter(completer)

        return combo

    @staticmethod
    def _sort_vri_key(code: str) -> Tuple:
        """Ключ сортировки VRI по коду (числовой).

        Args:
            code: Код ВРИ (например "2.5" или "12.0.1")

        Returns:
            Кортеж для сортировки
        """
        try:
            parts = code.split('.')
            return tuple(int(p) for p in parts)
        except (ValueError, AttributeError):
            return (999, 999, 999)

    def on_apply(self) -> None:
        """Обработчик 'Применить': собрать значения полей"""
        self.result_values = {}

        # ID
        if self._id_edit:
            val = self._id_edit.text().strip()
            if val:
                self.result_values['ID'] = val

        # ID_KV
        if self._id_kv_edit:
            val = self._id_kv_edit.text().strip()
            if val:
                self.result_values['ID_KV'] = val

        # VRI
        if self._vri_combo:
            val = self._vri_combo.currentText().strip()
            if val and val != "--- Выберите ВРИ ---":
                self.result_values['VRI'] = val

        # MIN_AREA_VRI
        if self._min_area_edit:
            val = self._min_area_edit.text().strip()
            if val:
                self.result_values['MIN_AREA_VRI'] = val

        self.skipped = False
        self.accept()

    def on_skip(self) -> None:
        """Обработчик 'Пропустить': пропуск текущего контура"""
        self.result_values = {}
        self.skipped = True
        self.accept()

    def on_skip_all(self) -> None:
        """Обработчик 'Пропустить все': пропуск всех оставшихся"""
        self.result_values = {}
        self.skipped = True
        self.skip_all = True
        self.accept()

    def get_result(self) -> Tuple[Dict[str, str], bool, bool]:
        """Получить результат диалога.

        Returns:
            Tuple: (values_dict, skipped, skip_all)
        """
        return self.result_values, self.skipped, self.skip_all
