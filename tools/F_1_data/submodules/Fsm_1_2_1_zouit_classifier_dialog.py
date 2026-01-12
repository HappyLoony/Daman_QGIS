# -*- coding: utf-8 -*-
"""
Диалог классификации неопознанных объектов ЗОУИТ
Позволяет пользователю вручную классифицировать объекты, которые не удалось распознать автоматически
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem,
    QGroupBox, QHeaderView
)


class ZouitClassifierDialog(QDialog):
    """Диалог для классификации одного неопознанного объекта ЗОУИТ"""

    def __init__(self, parent, feature_data, zouit_layers, current_index, total_count):
        """
        Инициализация диалога

        Args:
            parent: Родительское окно
            feature_data: Данные объекта (GeoJSON feature)
            zouit_layers: Список доступных слоёв ЗОУИТ для выбора
            current_index: Номер текущего объекта (начиная с 1)
            total_count: Общее количество неопознанных объектов
        """
        super().__init__(parent)
        self.feature_data = feature_data
        self.zouit_layers = zouit_layers
        self.current_index = current_index
        self.total_count = total_count

        self.selected_layer = None  # Результат выбора пользователя
        self.skip_all = False  # Флаг "Пропустить все"

        self.setWindowTitle(f"Классификация ЗОУИТ ({current_index} из {total_count})")
        self.setModal(True)
        self.setMinimumWidth(1400)
        self.setMinimumHeight(1000)

        self.init_ui()

    def init_ui(self):
        """Создание интерфейса"""
        layout = QVBoxLayout()

        # Заголовок
        title_label = QLabel(f"Неопознанный объект ЗОУИТ ({self.current_index} из {self.total_count})")
        title_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 10px;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        # Инструкция
        instruction_label = QLabel(
            "Не удалось автоматически определить тип ЗОУИТ.\n"
            "Просмотрите атрибуты объекта и выберите подходящий слой из списка ниже."
        )
        instruction_label.setStyleSheet("padding: 5px; color: #555;")
        instruction_label.setWordWrap(True)
        layout.addWidget(instruction_label)

        # Группа с атрибутами
        attributes_group = QGroupBox("Атрибуты объекта")
        attributes_layout = QVBoxLayout()

        # Таблица атрибутов (вертикальная: колонка 1 = название, колонка 2 = значение)
        self.attributes_table = QTableWidget()
        self.attributes_table.setColumnCount(2)
        self.attributes_table.setHorizontalHeaderLabels(["Атрибут", "Значение"])

        # Заполняем таблицу атрибутами
        properties = self.feature_data.get("properties", {}).get("options", {})
        self.attributes_table.setRowCount(len(properties))

        for row, (key, value) in enumerate(properties.items()):
            # Колонка 1: название атрибута
            key_item = QTableWidgetItem(str(key))
            key_item.setFlags(key_item.flags() & ~Qt.ItemIsEditable)  # Только чтение
            self.attributes_table.setItem(row, 0, key_item)

            # Колонка 2: значение
            value_str = str(value) if value is not None else ""
            value_item = QTableWidgetItem(value_str)
            value_item.setFlags(value_item.flags() & ~Qt.ItemIsEditable)  # Только чтение
            self.attributes_table.setItem(row, 1, value_item)

        # Настройка ширины колонок
        header = self.attributes_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)

        # Настройка высоты строк
        self.attributes_table.verticalHeader().setDefaultSectionSize(25)

        attributes_layout.addWidget(self.attributes_table)
        attributes_group.setLayout(attributes_layout)
        layout.addWidget(attributes_group)

        # Группа выбора слоя
        selection_group = QGroupBox("Выбор слоя ЗОУИТ")
        selection_layout = QVBoxLayout()

        selection_label = QLabel("Выберите слой, в который нужно поместить этот объект:")
        selection_label.setStyleSheet("padding: 5px;")
        selection_layout.addWidget(selection_label)

        # Комбобокс для выбора слоя
        self.layer_combo = QComboBox()

        # Фильтруем только слои ЗОУИТ (Le_1_2_5_*)
        zouit_only = [
            layer for layer in self.zouit_layers
            if layer.get('full_name', '').startswith('Le_1_2_5_')
        ]

        # Сортируем по порядковому номеру в группе (sublayer_num из layer)
        # Это сохраняет логический порядок слоёв (например, "Первая зона", "Вторая зона" и т.д.)
        def get_sort_key(layer):
            # Извлекаем sublayer_num из полной информации о слое
            layer_info = layer.get('layer', {})
            sublayer_num = layer_info.get('sublayer_num', 999)

            # Преобразуем в число для корректной сортировки
            try:
                return int(sublayer_num) if sublayer_num else 999
            except (ValueError, TypeError):
                return 999

        sorted_layers = sorted(zouit_only, key=get_sort_key)

        for layer in sorted_layers:
            layer_name = layer.get('name', '')
            full_name = layer.get('full_name', '')
            # Показываем description, храним full_name
            self.layer_combo.addItem(layer_name, full_name)

        # Устанавливаем размер шрифта и высоту элементов
        self.layer_combo.setStyleSheet("QComboBox { padding: 5px; font-size: 11px; }")

        selection_layout.addWidget(self.layer_combo)
        selection_group.setLayout(selection_layout)
        layout.addWidget(selection_group)

        # Кнопки
        buttons_layout = QHBoxLayout()

        # Кнопка "Пропустить"
        skip_btn = QPushButton("Пропустить (в Иные)")
        skip_btn.setToolTip("Пропустить этот объект, он попадёт в слой 'ИНАЯ_ЗОНА'")
        skip_btn.clicked.connect(self.on_skip)
        buttons_layout.addWidget(skip_btn)

        # Кнопка "Пропустить все"
        skip_all_btn = QPushButton("Пропустить все (в Иные)")
        skip_all_btn.setToolTip("Пропустить все оставшиеся объекты, они попадут в слой 'ИНАЯ_ЗОНА'")
        skip_all_btn.clicked.connect(self.on_skip_all)
        buttons_layout.addWidget(skip_all_btn)

        buttons_layout.addStretch()

        # Кнопка "Применить"
        apply_btn = QPushButton("Применить")
        apply_btn.setToolTip("Поместить объект в выбранный слой")
        apply_btn.clicked.connect(self.on_apply)
        apply_btn.setDefault(True)
        apply_btn.setStyleSheet("QPushButton { font-weight: bold; padding: 8px 20px; }")
        buttons_layout.addWidget(apply_btn)

        layout.addLayout(buttons_layout)
        self.setLayout(layout)

    def on_apply(self):
        """Обработчик кнопки 'Применить'"""
        # Получаем выбранный слой
        self.selected_layer = self.layer_combo.currentData()
        self.accept()

    def on_skip(self):
        """Обработчик кнопки 'Пропустить'"""
        # Оставляем selected_layer = None, что означает "в ИНАЯ_ЗОНА"
        self.selected_layer = None
        self.accept()

    def on_skip_all(self):
        """Обработчик кнопки 'Пропустить все'"""
        self.selected_layer = None
        self.skip_all = True
        self.accept()

    def get_result(self):
        """
        Получить результат выбора пользователя

        Returns:
            tuple: (selected_layer_full_name, skip_all_flag)
                   selected_layer_full_name - полное имя слоя или None для "ИНАЯ_ЗОНА"
                   skip_all_flag - True если нажато "Пропустить все"
        """
        return self.selected_layer, self.skip_all
