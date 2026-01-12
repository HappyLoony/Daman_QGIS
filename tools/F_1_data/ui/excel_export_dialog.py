# -*- coding: utf-8 -*-
"""
Диалог экспорта координат в Excel
Специализированный диалог для tool_8_3
"""

import os
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QCheckBox, QPushButton, QLineEdit, QFileDialog,
    QDialogButtonBox, QMessageBox, QGroupBox
)
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsProject, QgsVectorLayer, QgsWkbTypes


class ExcelExportDialog(QDialog):
    """Диалог для экспорта одного слоя в Excel"""
    
    def __init__(self, parent=None):
        """Инициализация диалога
        
        Args:
            parent: Родительское окно
        """
        super().__init__(parent)
        self.setWindowTitle("Экспорт координат в Excel")
        self.setModal(True)
        self.resize(500, 300)
        
        # Настройки
        self.settings = QSettings()
        
        # Выбранный слой
        self.selected_layer = None
        
        # Создаем интерфейс
        self.setup_ui()
        
        # Загружаем слои
        self.load_layers()
        
        # Загружаем последнюю папку
        self.load_last_folder()
    
    def setup_ui(self):
        """Создание интерфейса диалога"""
        layout = QVBoxLayout()
        
        # === Выбор слоя ===
        layer_group = QGroupBox("Выбор слоя")
        layer_layout = QVBoxLayout()
        
        layer_label = QLabel("Слой для экспорта:")
        layer_layout.addWidget(layer_label)
        
        self.layer_combo = QComboBox()
        self.layer_combo.currentIndexChanged.connect(self.on_layer_changed)
        layer_layout.addWidget(self.layer_combo)
        
        # Информация о слое
        self.layer_info_label = QLabel("")
        self.layer_info_label.setStyleSheet("color: gray; font-style: italic;")
        layer_layout.addWidget(self.layer_info_label)
        
        layer_group.setLayout(layer_layout)
        layout.addWidget(layer_group)
        
        # === Опции экспорта ===
        options_group = QGroupBox("Опции экспорта")
        options_layout = QVBoxLayout()
        
        # Checkbox для WGS-84
        self.wgs84_checkbox = QCheckBox("Создать файл WGS-84")
        self.wgs84_checkbox.setChecked(False)  # По умолчанию выключен
        self.wgs84_checkbox.setToolTip(
            "Создать дополнительный файл с координатами в WGS-84 (EPSG:4326)"
        )
        options_layout.addWidget(self.wgs84_checkbox)
        
        # Checkbox для площади
        self.area_checkbox = QCheckBox("Добавить площадь")
        self.area_checkbox.setToolTip(
            "Добавить расчет площади в конец таблицы (только для полигональных слоев)"
        )
        options_layout.addWidget(self.area_checkbox)
        
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)
        
        # === Папка сохранения ===
        folder_group = QGroupBox("Папка сохранения")
        folder_layout = QHBoxLayout()
        
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        folder_layout.addWidget(self.folder_edit)
        
        self.browse_button = QPushButton("Обзор...")
        self.browse_button.clicked.connect(self.browse_folder)
        folder_layout.addWidget(self.browse_button)
        
        folder_group.setLayout(folder_layout)
        layout.addWidget(folder_group)
        
        # === Информация о формате имени файла ===
        info_label = QLabel(
            "Формат имени файла:\n"
            "• Основной: [Название слоя]_[СК].xlsx\n"
            "• WGS-84: [Название слоя]_WGS-84.xlsx"
        )
        info_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(info_label)
        
        # Растягивающийся элемент
        layout.addStretch()
        
        # === Кнопки ===
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        # Переименовываем кнопку OK
        button_box.button(QDialogButtonBox.Ok).setText("Экспорт")
        
        layout.addWidget(button_box)
        
        self.setLayout(layout)
    
    def load_layers(self):
        """Загрузка слоев с префиксами X_Y_Z_"""
        self.layer_combo.clear()
        
        # Получаем все слои проекта
        layers = QgsProject.instance().mapLayers().values()
        
        # Фильтруем векторные слои с префиксами X_Y_Z_
        valid_layers = []
        for layer in layers:
            if isinstance(layer, QgsVectorLayer):
                # Проверяем префикс
                name = layer.name()
                parts = name.split('_')
                if len(parts) >= 3:
                    # Проверяем, что первые части - цифры
                    try:
                        int(parts[0])
                        int(parts[1])
                        int(parts[2])
                        valid_layers.append(layer)
                    except ValueError:
                        continue
        
        # Сортируем по имени
        valid_layers.sort(key=lambda l: l.name())
        
        # Добавляем в комбобокс
        if valid_layers:
            for layer in valid_layers:
                self.layer_combo.addItem(layer.name(), layer)
        else:
            self.layer_combo.addItem("Нет слоев с префиксами X_Y_Z_", None)
    
    def on_layer_changed(self):
        """Обработчик изменения выбранного слоя"""
        layer = self.layer_combo.currentData()
        
        if layer and isinstance(layer, QgsVectorLayer):
            # Обновляем информацию о слое
            geom_type = layer.geometryType()
            feature_count = layer.featureCount()
            
            if geom_type == QgsWkbTypes.PointGeometry:
                geom_type_str = "точки"
                # Отключаем площадь для точек
                self.area_checkbox.setEnabled(False)
                self.area_checkbox.setChecked(False)
            elif geom_type == QgsWkbTypes.LineGeometry:
                geom_type_str = "линии"
                # Отключаем площадь для линий
                self.area_checkbox.setEnabled(False)
                self.area_checkbox.setChecked(False)
            elif geom_type == QgsWkbTypes.PolygonGeometry:
                geom_type_str = "полигоны"
                # Включаем площадь для полигонов
                self.area_checkbox.setEnabled(True)
            else:
                geom_type_str = "неизвестно"
                self.area_checkbox.setEnabled(False)
                self.area_checkbox.setChecked(False)
            
            self.layer_info_label.setText(
                f"Тип: {geom_type_str}, Объектов: {feature_count}"
            )
        else:
            self.layer_info_label.setText("")
            self.area_checkbox.setEnabled(False)
            self.area_checkbox.setChecked(False)
    
    def browse_folder(self):
        """Выбор папки для сохранения"""
        # Получаем последнюю папку из настроек
        last_folder = self.settings.value(
            "Daman_QGIS/last_excel_export_folder",
            QgsProject.instance().homePath()
        )
        
        # Диалог выбора папки
        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку для сохранения Excel файлов",
            last_folder
        )
        
        if folder:
            self.folder_edit.setText(folder)
            # Сохраняем папку в настройки
            self.settings.setValue("Daman_QGIS/last_excel_export_folder", folder)
    
    def load_last_folder(self):
        """Загрузка последней использованной папки"""
        # Пытаемся получить папку экспорта из проекта
        project_path = QgsProject.instance().homePath()
        if project_path:
            export_folder = os.path.join(project_path, "export")
            if os.path.exists(export_folder):
                self.folder_edit.setText(export_folder)
                return
        
        # Иначе используем последнюю сохраненную папку
        last_folder = self.settings.value(
            "Daman_QGIS/last_excel_export_folder",
            project_path
        )
        
        if last_folder and os.path.exists(last_folder):
            self.folder_edit.setText(last_folder)
        else:
            self.folder_edit.setText(project_path)
    
    def accept(self):
        """Проверка перед закрытием диалога"""
        # Проверяем выбран ли слой
        layer = self.layer_combo.currentData()
        if not layer:
            QMessageBox.warning(
                self,
                "Предупреждение",
                "Не выбран слой для экспорта"
            )
            return
        
        # Проверяем выбрана ли папка
        folder = self.folder_edit.text()
        if not folder:
            QMessageBox.warning(
                self,
                "Предупреждение",
                "Не выбрана папка для сохранения"
            )
            return
        
        if not os.path.exists(folder):
            QMessageBox.warning(
                self,
                "Предупреждение",
                f"Папка не существует:\n{folder}"
            )
            return
        
        # Сохраняем выбранный слой
        self.selected_layer = layer
        
        # Закрываем диалог
        super().accept()
    
    def get_selected_layer(self):
        """Получение выбранного слоя
        
        Returns:
            QgsVectorLayer: Выбранный слой
        """
        return self.selected_layer
    
    def get_output_folder(self):
        """Получение папки для сохранения
        
        Returns:
            str: Путь к папке
        """
        return self.folder_edit.text()
    
    def get_export_options(self):
        """Получение опций экспорта
        
        Returns:
            dict: Словарь с опциями
        """
        return {
            'create_wgs84': self.wgs84_checkbox.isChecked(),
            'add_area': self.area_checkbox.isChecked() and self.area_checkbox.isEnabled()
        }
