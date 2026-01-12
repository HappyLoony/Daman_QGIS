# -*- coding: utf-8 -*-
"""
Диалог выбора слоев для графики к запросу
Динамически загружает доступные слои из проекта с ограничением выбора до 4 слоёв
"""

from typing import Dict, List, Tuple
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QDialogButtonBox,
    QGroupBox, QCheckBox, QScrollArea, QWidget
)
from qgis.core import QgsProject, QgsMessageLog, Qgis
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers import get_reference_managers


class GraphicsRequestDialog(QDialog):
    """Диалог выбора слоев для включения в схему"""

    MAX_LAYERS = 4  # Максимальное количество слоёв с легендой (ограничение размера легенды)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Выбор слоев для схемы")
        self.setMinimumWidth(500)
        self.setMinimumHeight(500)

        self.selected_layers = []  # Не используется
        self.nspd_layers = {}  # Словарь для хранения выбранных слоев НСПД
        self.checkboxes = {}  # Словарь чекбоксов {layer_name: checkbox}
        self.layer_info = {}  # Информация о слоях {layer_name: (description, order)}

        self.init_ui()

    def init_ui(self):
        """Инициализация интерфейса"""
        layout = QVBoxLayout()

        # Заголовок
        label = QLabel("Выберите векторные слои для отображения на схеме (максимум 4):")
        label.setWordWrap(True)
        layout.addWidget(label)

        # Информационное сообщение
        info_label = QLabel("Отображаются только загруженные слои с объектами")
        info_label.setStyleSheet("QLabel { color: #666; font-style: italic; }")
        layout.addWidget(info_label)

        # Счётчик выбранных слоёв
        self.counter_label = QLabel(f"Выбрано слоёв: 0 / {self.MAX_LAYERS}")
        self.counter_label.setStyleSheet("QLabel { color: #0066cc; font-weight: bold; }")
        layout.addWidget(self.counter_label)

        # Группа с векторными данными ЕГРН (с прокруткой)
        nspd_group = QGroupBox("Векторные слои НСПД")
        nspd_scroll = QScrollArea()
        nspd_scroll.setWidgetResizable(True)
        nspd_scroll.setMinimumHeight(200)

        nspd_widget = QWidget()
        self.nspd_layout = QVBoxLayout(nspd_widget)

        # Динамически загружаем доступные слои
        self._load_available_layers()

        nspd_scroll.setWidget(nspd_widget)
        nspd_group_layout = QVBoxLayout()
        nspd_group_layout.addWidget(nspd_scroll)
        nspd_group.setLayout(nspd_group_layout)

        layout.addWidget(nspd_group)

        # Группа с настройками подложки
        basemap_group = QGroupBox("Настройки картоосновы")
        basemap_layout = QVBoxLayout()

        self.cb_use_satellite = QCheckBox("Использовать снимок с космоса (Google Earth)")
        self.cb_use_satellite.setChecked(False)  # По умолчанию выключен (используется ЦОС)
        self.cb_use_satellite.setToolTip("Переключить основную карту на спутниковый снимок вместо картоосновы ЦОС")
        basemap_layout.addWidget(self.cb_use_satellite)

        basemap_info = QLabel("По умолчанию: Картооснова НСПД (ЦОС)\n"
                              "При включении: Спутниковый снимок Google")
        basemap_info.setStyleSheet("QLabel { color: #666; font-size: 9pt; }")
        basemap_info.setWordWrap(True)
        basemap_layout.addWidget(basemap_info)

        basemap_group.setLayout(basemap_layout)
        layout.addWidget(basemap_group)

        # Примечание
        note_label = QLabel("Примечание: Слой границ работ (L_1_1_1) добавляется автоматически\n"
                           "Буферные слои (Le_1_1_2, Le_1_1_3) не отображаются на схеме")
        note_label.setWordWrap(True)
        note_label.setStyleSheet("QLabel { color: #888; font-size: 9pt; }")
        layout.addWidget(note_label)

        # Кнопки
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        button_box.button(QDialogButtonBox.Ok).setText("Создать схему")
        button_box.button(QDialogButtonBox.Cancel).setText("Отмена")
        layout.addWidget(button_box)

        self.setLayout(layout)

    def _load_available_layers(self):
        """Динамическая загрузка доступных слоёв из проекта

        ВАЖНО:
        - Показываются только слои с объектами
        - Исключаются буферные слои (Le_1_1_2, Le_1_1_3)
        - Порядок слоёв согласно Base_layers.json
        - Учитываются родительские слои (L_1_2_4_WFS_ОКС и др.)
        """
        project = QgsProject.instance()

        # Получаем информацию о слоях из Base_layers.json
        ref_managers = get_reference_managers()
        layer_manager = ref_managers.layer

        if not layer_manager:
            log_error("Не удалось получить layer_manager")
            return

        all_base_layers = layer_manager.get_base_layers()

        # Создаём маппинг: layer_name -> (description, order)
        layer_order_map = {}
        for idx, layer_data in enumerate(all_base_layers):
            full_name = layer_data.get('full_name', '')
            description = layer_data.get('description', full_name)

            # Проверяем что это векторный слой НСПД (группы L_1_2, Le_1_2)
            if full_name.startswith('L_1_2_') or full_name.startswith('Le_1_2_'):
                # Исключаем буферные слои и слои без легенды
                if not full_name.startswith('Le_1_1_2') and not full_name.startswith('Le_1_1_3'):
                    layer_order_map[full_name] = (description, idx)

        # Собираем существующие слои из проекта с объектами
        available_layers = []
        for layer in project.mapLayers().values():
            layer_name = layer.name()

            # Проверяем что слой есть в маппинге
            if layer_name in layer_order_map:
                # Проверяем наличие объектов
                if hasattr(layer, 'featureCount') and layer.featureCount() > 0:
                    description, order = layer_order_map[layer_name]
                    available_layers.append((layer_name, description, order))

        # Сортируем слои согласно порядку из Base_layers.json
        available_layers.sort(key=lambda x: x[2])

        if not available_layers:
            no_layers_label = QLabel("Нет доступных слоёв с объектами.\n"
                                    "Сначала загрузите слои через F_1_2_Загрузка Web карт")
            no_layers_label.setStyleSheet("QLabel { color: #cc0000; font-weight: bold; }")
            no_layers_label.setWordWrap(True)
            self.nspd_layout.addWidget(no_layers_label)
            return

        # Создаём чекбоксы для каждого доступного слоя
        default_layers = {'L_1_2_1_WFS_ЗУ', 'L_1_2_2_WFS_КК', 'Le_1_2_3_4_АТД_НП_line', 'Le_1_2_3_5_АТД_НП_poly'}  # По умолчанию включены
        selected_count = 0

        for layer_name, description, order in available_layers:
            checkbox = QCheckBox(f"{description} ({layer_name})")
            checkbox.setToolTip(f"Слой: {layer_name}\nОписание: {description}")

            # Устанавливаем состояние по умолчанию
            if layer_name in default_layers and selected_count < self.MAX_LAYERS:
                checkbox.setChecked(True)
                selected_count += 1

            # Подключаем обработчик изменения состояния
            checkbox.stateChanged.connect(self._on_checkbox_changed)

            self.checkboxes[layer_name] = checkbox
            self.layer_info[layer_name] = (description, order)
            self.nspd_layout.addWidget(checkbox)

        # Обновляем счётчик
        self._update_counter()

        log_info(f"Fsm_1_4_8: Загружено {len(available_layers)} доступных слоёв для выбора")

    def _on_checkbox_changed(self, state):
        """Обработчик изменения состояния чекбокса

        Блокирует невыбранные чекбоксы если достигнут лимит
        """
        selected_count = sum(1 for cb in self.checkboxes.values() if cb.isChecked())

        # Если достигнут лимит - блокируем невыбранные чекбоксы
        if selected_count >= self.MAX_LAYERS:
            for layer_name, checkbox in self.checkboxes.items():
                if not checkbox.isChecked():
                    checkbox.setEnabled(False)
        else:
            # Если ниже лимита - разблокируем все
            for checkbox in self.checkboxes.values():
                checkbox.setEnabled(True)

        # Обновляем счётчик
        self._update_counter()

    def _update_counter(self):
        """Обновление счётчика выбранных слоёв"""
        selected_count = sum(1 for cb in self.checkboxes.values() if cb.isChecked())
        self.counter_label.setText(f"Выбрано слоёв: {selected_count} / {self.MAX_LAYERS}")

        # Меняем цвет в зависимости от количества
        if selected_count == 0:
            color = "#cc0000"  # Красный - ничего не выбрано
        elif selected_count >= self.MAX_LAYERS:
            color = "#ff9900"  # Оранжевый - достигнут лимит
        else:
            color = "#0066cc"  # Синий - нормально

        self.counter_label.setStyleSheet(f"QLabel {{ color: {color}; font-weight: bold; }}")

    def accept(self):
        """Обработка нажатия кнопки OK"""
        # Оставляем пустой список для совместимости
        self.selected_layers = []

        # НОВАЯ ЛОГИКА: Сохраняем выбранные слои по полным именам
        self.nspd_layers = {}

        for layer_name, checkbox in self.checkboxes.items():
            if checkbox.isChecked():
                # Используем полное имя слоя как ключ
                self.nspd_layers[layer_name] = True

        # Сохраняем настройку спутниковой подложки
        self.use_satellite = self.cb_use_satellite.isChecked()

        # Проверяем, что хотя бы один слой выбран
        if not self.nspd_layers:
            log_warning("Не выбрано ни одного векторного слоя")

        log_info(f"Fsm_1_4_8: Выбрано слоёв: {len(self.nspd_layers)}")
        log_info(f"Fsm_1_4_8: Выбранные слои: {', '.join(self.nspd_layers.keys())}")

        super().accept()
