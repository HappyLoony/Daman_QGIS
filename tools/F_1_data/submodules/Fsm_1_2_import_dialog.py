# -*- coding: utf-8 -*-
"""
Диалог импорта данных КПТ с выбором формата файла
Поддерживает XML, DXF и TAB форматы
"""

import os
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QFileDialog,
    QGroupBox, QLineEdit, QMessageBox
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont
from qgis.core import QgsMessageLog, Qgis


class Tool_1_2_ImportDialog(QDialog):
    """Диалог импорта данных КПТ с выбором формата"""
    
    # Маппинг типов слоев на нумерацию и типы геометрии
    LAYER_TYPES = {
        "1_2_1_Земельные_участки": {
            "name": "Земельные участки",
            "allowed_geometry": ["Polygon", "MultiPolygon"],
            "code": "1_2_1"
        },
        "1_2_2_Здания": {
            "name": "Здания", 
            "allowed_geometry": ["Polygon", "MultiPolygon"],
            "code": "1_2_2"
        },
        "1_2_3_Сооружения_полигон": {
            "name": "Сооружения (полигон)",
            "allowed_geometry": ["Polygon", "MultiPolygon"],
            "code": "1_2_3",
            "suffix": "_полигон"
        },
        "1_2_3_Сооружения_линия": {
            "name": "Сооружения (линия)",
            "allowed_geometry": ["LineString", "MultiLineString"],
            "code": "1_2_3",
            "suffix": "_линия"
        },
        "1_2_3_Сооружения_точка": {
            "name": "Сооружения (точка)",
            "allowed_geometry": ["Point", "MultiPoint"],
            "code": "1_2_3",
            "suffix": "_точка"
        },
        "1_2_4_ОНС": {
            "name": "Объекты незавершенного строительства",
            "allowed_geometry": ["Polygon", "MultiPolygon"],
            "code": "1_2_4"
        },
        "1_2_5_Кварталы": {
            "name": "Кадастровые кварталы",
            "allowed_geometry": ["Polygon", "MultiPolygon"],
            "code": "1_2_5"
        },
        "1_2_6_Границы_субъектов_полигон": {
            "name": "Границы субъектов РФ (полигон)",
            "allowed_geometry": ["Polygon", "MultiPolygon"],
            "code": "1_2_6",
            "suffix": "_полигон"
        },
        "1_2_6_Границы_субъектов_линия": {
            "name": "Границы субъектов РФ (линия)",
            "allowed_geometry": ["LineString", "MultiLineString"],
            "code": "1_2_6",
            "suffix": "_линия"
        },
        "1_2_7_Муниципальные_границы": {
            "name": "Муниципальные границы",
            "allowed_geometry": ["Polygon", "MultiPolygon"],
            "code": "1_2_7"
        },
        "1_2_8_Населенные_пункты": {
            "name": "Населенные пункты",
            "allowed_geometry": ["Polygon", "MultiPolygon"],
            "code": "1_2_8"
        },
        "1_2_9_Береговые_линии_полигон": {
            "name": "Береговые линии (полигон)",
            "allowed_geometry": ["Polygon", "MultiPolygon"],
            "code": "1_2_9",
            "suffix": "_полигон"
        },
        "1_2_9_Береговые_линии_линия": {
            "name": "Береговые линии (линия)",
            "allowed_geometry": ["LineString", "MultiLineString"],
            "code": "1_2_9",
            "suffix": "_линия"
        },
        "1_2_9_Береговые_линии_точка": {
            "name": "Береговые линии (точка)",
            "allowed_geometry": ["Point", "MultiPoint"],
            "code": "1_2_9",
            "suffix": "_точка"
        },
        "1_2_10_Зоны_и_территории": {
            "name": "Зоны и территории",
            "allowed_geometry": ["Polygon", "MultiPolygon"],
            "code": "1_2_10"
        },
        "1_2_11_Проекты_межевания": {
            "name": "Проекты межевания",
            "allowed_geometry": ["Polygon", "MultiPolygon"],
            "code": "1_2_11"
        },
        "1_2_12_Сервитуты": {
            "name": "Сервитуты",
            "allowed_geometry": ["Polygon", "MultiPolygon"],
            "code": "1_2_12"
        }
    }
    
    def __init__(self, parent=None):
        """Инициализация диалога"""
        super().__init__(parent)
        self.setWindowTitle("Импорт данных КПТ")
        self.setMinimumWidth(500)
        
        # Атрибуты для хранения выбранных опций
        self.selected_files = []
        self.file_format = "XML"
        self.layer_type = None
        
        self.setup_ui()
    
    def setup_ui(self):
        """Создание интерфейса"""
        layout = QVBoxLayout(self)
        
        # Заголовок
        title_label = QLabel("Импорт кадастровых данных")
        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        
        # Группа выбора формата
        format_group = QGroupBox("Формат файла")
        format_layout = QVBoxLayout()
        
        # ComboBox для выбора формата
        format_label = QLabel("Выберите формат:")
        format_layout.addWidget(format_label)
        
        self.format_combo = QComboBox()
        self.format_combo.addItems(["XML", "DXF", "TAB"])
        self.format_combo.setCurrentText("XML")
        self.format_combo.currentTextChanged.connect(self.on_format_changed)
        format_layout.addWidget(self.format_combo)
        
        format_group.setLayout(format_layout)
        layout.addWidget(format_group)
        
        # Группа выбора типа слоя (для DXF/TAB)
        self.layer_type_group = QGroupBox("Тип слоя")
        layer_type_layout = QVBoxLayout()
        
        layer_type_label = QLabel("Выберите тип слоя для импорта:")
        layer_type_layout.addWidget(layer_type_label)
        
        self.layer_type_combo = QComboBox()
        # Заполняем типами слоев
        for key, value in self.LAYER_TYPES.items():
            self.layer_type_combo.addItem(value["name"], key)
        layer_type_layout.addWidget(self.layer_type_combo)
        
        self.layer_type_hint = QLabel(
            "Внимание: убедитесь, что тип геометрии в файле\n"
            "соответствует выбранному типу слоя"
        )
        self.layer_type_hint.setStyleSheet("color: #666; font-size: 9pt;")
        layer_type_layout.addWidget(self.layer_type_hint)
        
        self.layer_type_group.setLayout(layer_type_layout)
        self.layer_type_group.setEnabled(False)  # По умолчанию отключено для XML
        layout.addWidget(self.layer_type_group)
        
        # Группа выбора файлов
        file_group = QGroupBox("Выбор файлов")
        file_layout = QVBoxLayout()
        
        # Поле для отображения выбранных файлов
        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        self.file_edit.setPlaceholderText("Файлы не выбраны")
        file_layout.addWidget(self.file_edit)
        
        # Кнопка выбора файлов
        browse_button = QPushButton("Обзор...")
        browse_button.clicked.connect(self.browse_files)
        file_layout.addWidget(browse_button)
        
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)
        
        # Информация о формате
        self.info_label = QLabel()
        self.update_format_info()
        layout.addWidget(self.info_label)
        
        # Кнопки OK/Cancel
        button_layout = QHBoxLayout()
        
        self.ok_button = QPushButton("Импорт")
        self.ok_button.clicked.connect(self.validate_and_accept)
        self.ok_button.setEnabled(False)
        button_layout.addWidget(self.ok_button)
        
        cancel_button = QPushButton("Отмена")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
    
    def on_format_changed(self, format_text):
        """Обработка изменения формата файла"""
        self.file_format = format_text
        
        # Включаем/отключаем выбор типа слоя
        if format_text == "XML":
            self.layer_type_group.setEnabled(False)
            self.layer_type = None
        else:
            self.layer_type_group.setEnabled(True)
            self.layer_type = self.layer_type_combo.currentData()
        
        # Обновляем информацию о формате
        self.update_format_info()
        
        # Сбрасываем выбранные файлы
        self.selected_files = []
        self.file_edit.clear()
        self.ok_button.setEnabled(False)
    
    def update_format_info(self):
        """Обновление информации о выбранном формате"""
        info_texts = {
            "XML": (
                "XML файлы Росреестра содержат полную информацию\n"
                "о кадастровых объектах. Будут импортированы все\n"
                "типы слоев с атрибутами и стилями."
            ),
            "DXF": (
                "DXF файлы с Публичной кадастровой карты.\n"
                "Выберите один файл и укажите тип слоя.\n"
                "Атрибуты сохраняются как есть."
            ),
            "TAB": (
                "TAB файлы MapInfo с Публичной кадастровой карты.\n"
                "Выберите один файл и укажите тип слоя.\n"
                "Вспомогательные файлы (.dat, .map) должны быть\n"
                "в той же папке."
            )
        }
        
        self.info_label.setText(info_texts.get(self.file_format, ""))
        self.info_label.setStyleSheet("color: #333; font-size: 9pt; padding: 5px;")
    
    def browse_files(self):
        """Выбор файлов для импорта"""
        # Определяем фильтр файлов
        if self.file_format == "XML":
            filter_str = "XML файлы (*.xml);;Все файлы (*.*)"
            caption = "Выберите XML файлы КПТ"
            # Для XML можно выбрать несколько файлов
            files, _ = QFileDialog.getOpenFileNames(
                self, caption, "", filter_str
            )
        elif self.file_format == "DXF":
            filter_str = "DXF файлы (*.dxf);;Все файлы (*.*)"
            caption = "Выберите DXF файл"
            # Для DXF только один файл
            file_path, _ = QFileDialog.getOpenFileName(
                self, caption, "", filter_str
            )
            files = [file_path] if file_path else []
        elif self.file_format == "TAB":
            filter_str = "TAB файлы (*.tab);;Все файлы (*.*)"
            caption = "Выберите TAB файл"
            # Для TAB только один файл
            file_path, _ = QFileDialog.getOpenFileName(
                self, caption, "", filter_str
            )
            files = [file_path] if file_path else []
        else:
            files = []
        
        if files:
            self.selected_files = files
            # Отображаем имена файлов
            if len(files) == 1:
                self.file_edit.setText(os.path.basename(files[0]))
            else:
                self.file_edit.setText(f"Выбрано файлов: {len(files)}")
            
            self.ok_button.setEnabled(True)
        else:
            self.selected_files = []
            self.file_edit.clear()
            self.ok_button.setEnabled(False)
    
    def validate_and_accept(self):
        """Валидация и принятие диалога"""
        if not self.selected_files:
            QMessageBox.warning(
                self,
                "Предупреждение",
                "Не выбраны файлы для импорта"
            )
            return
        
        # Для DXF/TAB проверяем выбор типа слоя
        if self.file_format in ["DXF", "TAB"]:
            if not self.layer_type_combo.currentData():
                QMessageBox.warning(
                    self,
                    "Предупреждение",
                    "Выберите тип слоя для импорта"
                )
                return
            self.layer_type = self.layer_type_combo.currentData()
        
        self.accept()
    
    def get_import_options(self):
        """Получение опций импорта
        
        Returns:
            dict: Словарь с опциями импорта
        """
        options = {
            "format": self.file_format,
            "files": self.selected_files,
            "layer_type": self.layer_type
        }
        
        # Добавляем информацию о типе слоя для DXF/TAB
        if self.layer_type and self.layer_type in self.LAYER_TYPES:
            layer_info = self.LAYER_TYPES[self.layer_type]
            options["layer_info"] = layer_info
            options["layer_name"] = self.layer_type + "_" + layer_info["name"].replace(" ", "_")
        
        return options
