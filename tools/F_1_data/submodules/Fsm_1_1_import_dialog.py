# -*- coding: utf-8 -*-
"""
Tool_1_X_ImportDialog - Универсальный диалог импорта данных

Объединенный диалог для выбора типа данных и формата файла
с иерархической структурой выбора (группа -> слой)
"""

import os
from typing import Dict, Optional, List

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFileDialog, QGroupBox, QMessageBox, QFormLayout,
    QCheckBox, QLineEdit, QRadioButton, QButtonGroup
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont
from qgis.core import QgsProject, QgsMessageLog, Qgis


class Tool_1_X_ImportDialog(QDialog):
    """Универсальный диалог импорта с выбором группа -> слой"""
    
    # Структура всех доступных слоев для импорта
    IMPORT_STRUCTURE = {
        "1_1_Границы_работ": {
            "name": "Границы работ",
            "layers": {
                "1_1_1_Границы_работ": {
                    "name": "Границы работ",
                    "formats": ["DXF", "TAB"],
                    "geometry": ["LineString", "MultiLineString"],
                    "attributes": ["id", "name", "description", "length_m"]
                }
            }
        },
        "1_2_КПТ": {
            "name": "Кадастровые планы территорий",
            "layers": {
                "1_2_1_Земельные_участки": {
                    "name": "Земельные участки",
                    "formats": ["XML", "DXF", "TAB"],
                    "geometry": ["Polygon", "MultiPolygon"]
                },
                "1_2_2_Здания": {
                    "name": "Здания",
                    "formats": ["XML", "DXF", "TAB"],
                    "geometry": ["Polygon", "MultiPolygon", "NoGeometry"]
                },
                "1_2_3_Сооружения": {
                    "name": "Сооружения",
                    "formats": ["XML", "DXF", "TAB"],
                    "geometry": ["Polygon", "LineString", "Point", "NoGeometry"],
                    "variants": ["полигон", "линия", "точка", "без_геометрии"]
                },
                "1_2_4_ОНС": {
                    "name": "Объекты незавершенного строительства",
                    "formats": ["XML", "DXF", "TAB"],
                    "geometry": ["Polygon", "MultiPolygon", "NoGeometry"]
                },
                "1_2_5_Кварталы": {
                    "name": "Кадастровые кварталы",
                    "formats": ["XML", "DXF", "TAB"],
                    "geometry": ["Polygon", "MultiPolygon"]
                },
                "1_2_6_Границы_субъектов": {
                    "name": "Границы субъектов РФ",
                    "formats": ["XML", "DXF", "TAB"],
                    "geometry": ["Polygon", "LineString"],
                    "variants": ["полигон", "линия"]
                },
                "1_2_7_Муниципальные_границы": {
                    "name": "Муниципальные границы",
                    "formats": ["XML", "DXF", "TAB"],
                    "geometry": ["Polygon", "MultiPolygon"]
                },
                "1_2_8_Населенные_пункты": {
                    "name": "Населенные пункты",
                    "formats": ["XML", "DXF", "TAB"],
                    "geometry": ["Polygon", "MultiPolygon"]
                },
                "1_2_9_Береговые_линии": {
                    "name": "Береговые линии",
                    "formats": ["XML", "DXF", "TAB"],
                    "geometry": ["Polygon", "LineString", "Point"],
                    "variants": ["полигон", "линия", "точка"]
                },
                "1_2_10_Зоны_и_территории": {
                    "name": "Зоны и территории",
                    "formats": ["XML", "DXF", "TAB"],
                    "geometry": ["Polygon", "MultiPolygon"]
                },
                "1_2_11_Проекты_межевания": {
                    "name": "Проекты межевания",
                    "formats": ["XML", "DXF", "TAB"],
                    "geometry": ["Polygon", "MultiPolygon", "NoGeometry"]
                },
                "1_2_12_Сервитуты": {
                    "name": "Сервитуты",
                    "formats": ["XML", "DXF", "TAB"],
                    "geometry": ["Polygon", "MultiPolygon"]
                }
            }
        },
        "2_3_ЗПР": {
            "name": "Зоны планируемого размещения",
            "subgroups": {
                "2_3_1_ЗПР": {
                    "name": "Зоны планируемого размещения",
                    "layers": {
                        "2_3_1_1_ЗПР_ОКС": {
                            "name": "ЗПР объектов капитального строительства",
                            "formats": ["DXF", "TAB"],
                            "geometry": ["Polygon", "MultiPolygon"]
                        },
                        "2_3_1_2_ЗПР_ПО": {
                            "name": "ЗПР постоянного отвода (на период эксплуатации)",
                            "formats": ["DXF", "TAB"],
                            "geometry": ["Polygon", "MultiPolygon"]
                        },
                        "2_3_1_3_ЗПР_ВО": {
                            "name": "ЗПР линейного объекта (на период строительства)",
                            "formats": ["DXF", "TAB"],
                            "geometry": ["Polygon", "MultiPolygon"]
                        }
                    }
                },
                "2_3_2_ЗПР_РЕК": {
                    "name": "ЗПР подлежащих реконструкции",
                    "layers": {
                        "2_3_2_1_ЗПР_РЕК_АД": {
                            "name": "ЗПР реконструкция автомобильных дорог",
                            "formats": ["DXF", "TAB"],
                            "geometry": ["Polygon", "MultiPolygon"]
                        },
                        "2_3_2_2_ЗПР_СЕТИ_ПО": {
                            "name": "ЗПР реконструкции инженерных сетей (эксплуатация)",
                            "formats": ["DXF", "TAB"],
                            "geometry": ["Polygon", "MultiPolygon"]
                        },
                        "2_3_2_3_ЗПР_СЕТИ_ВО": {
                            "name": "ЗПР реконструкции инженерных сетей (реконструкция)",
                            "formats": ["DXF", "TAB"],
                            "geometry": ["Polygon", "MultiPolygon"]
                        },
                        "2_3_2_4_ЗПР_НЭ": {
                            "name": "ЗПР наземных элементов инженерных сетей",
                            "formats": ["DXF", "TAB"],
                            "geometry": ["Polygon", "MultiPolygon"]
                        }
                    }
                }
            }
        }
    }
    
    def __init__(self, parent=None):
        """Инициализация диалога"""
        super().__init__(parent)
        self.setWindowTitle("Универсальный импорт данных")
        self.setMinimumWidth(700)
        
        # Атрибуты для хранения выбранных опций
        self.selected_files = []
        self.file_format = None
        self.selected_group = None
        self.selected_subgroup = None
        self.selected_layer = None
        
        self.setup_ui()
    
    def setup_ui(self):
        """Создание интерфейса"""
        layout = QVBoxLayout(self)
        
        # Заголовок
        title_label = QLabel("Универсальный импорт данных")
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        
        # Группа выбора типа данных
        data_group = QGroupBox("Выбор типа данных")
        data_layout = QVBoxLayout()
        
        # Группа (1_1, 1_2, 2_3)
        group_layout = QHBoxLayout()
        group_layout.addWidget(QLabel("Группа данных:"))
        self.group_combo = QComboBox()
        self.group_combo.addItem("-- Выберите группу --", None)
        
        # Заполняем группами
        for group_key, group_data in self.IMPORT_STRUCTURE.items():
            self.group_combo.addItem(f"{group_key} - {group_data['name']}", group_key)
        
        self.group_combo.currentIndexChanged.connect(self.on_group_changed)
        group_layout.addWidget(self.group_combo)
        group_layout.addStretch()
        data_layout.addLayout(group_layout)
        
        # Подгруппа (для ЗПР)
        self.subgroup_layout = QHBoxLayout()
        self.subgroup_label = QLabel("Подгруппа:")
        self.subgroup_layout.addWidget(self.subgroup_label)
        self.subgroup_combo = QComboBox()
        self.subgroup_combo.currentIndexChanged.connect(self.on_subgroup_changed)
        self.subgroup_layout.addWidget(self.subgroup_combo)
        self.subgroup_layout.addStretch()
        data_layout.addLayout(self.subgroup_layout)
        
        # Слой
        layer_layout = QHBoxLayout()
        layer_layout.addWidget(QLabel("Слой для импорта:"))
        self.layer_combo = QComboBox()
        self.layer_combo.setMinimumWidth(450)  # Увеличенный размер поля
        self.layer_combo.currentIndexChanged.connect(self.on_layer_changed)
        layer_layout.addWidget(self.layer_combo)
        layer_layout.addStretch()
        data_layout.addLayout(layer_layout)
        
        # Вариант геометрии (для слоев с вариантами)
        self.variant_layout = QHBoxLayout()
        self.variant_label = QLabel("Тип геометрии:")
        self.variant_layout.addWidget(self.variant_label)
        self.variant_combo = QComboBox()
        self.variant_layout.addWidget(self.variant_combo)
        self.variant_layout.addStretch()
        data_layout.addLayout(self.variant_layout)
        
        # Информация о слое
        self.layer_info = QLabel()
        self.layer_info.setWordWrap(True)
        self.layer_info.setStyleSheet("color: #666; font-size: 10pt;")
        data_layout.addWidget(self.layer_info)
        
        data_group.setLayout(data_layout)
        layout.addWidget(data_group)
        
        # Группа выбора формата
        format_group = QGroupBox("Формат файла")
        format_layout = QVBoxLayout()
        
        # Формат файла
        format_combo_layout = QHBoxLayout()
        format_combo_layout.addWidget(QLabel("Формат:"))
        self.format_combo = QComboBox()
        self.format_combo.setEnabled(False)
        self.format_combo.currentTextChanged.connect(self.on_format_changed)
        format_combo_layout.addWidget(self.format_combo)
        format_combo_layout.addStretch()
        format_layout.addLayout(format_combo_layout)
        
        # Информация о формате
        self.format_info = QLabel()
        self.format_info.setWordWrap(True)
        self.format_info.setStyleSheet("color: #333; font-size: 9pt; padding: 5px;")
        format_layout.addWidget(self.format_info)
        
        format_group.setLayout(format_layout)
        layout.addWidget(format_group)
        
        # Группа выбора файлов
        file_group = QGroupBox("Выбор файлов")
        file_layout = QVBoxLayout()
        
        # Поле для отображения выбранных файлов
        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        self.file_edit.setPlaceholderText("Файлы не выбраны")
        file_layout.addWidget(self.file_edit)
        
        # Кнопка выбора файлов
        self.browse_button = QPushButton("Обзор...")
        self.browse_button.clicked.connect(self.browse_files)
        self.browse_button.setEnabled(False)
        file_layout.addWidget(self.browse_button)
        
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)
        
        # Кнопки OK/Cancel
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.import_button = QPushButton("Импорт")
        self.import_button.clicked.connect(self.validate_and_accept)
        self.import_button.setEnabled(False)
        button_layout.addWidget(self.import_button)
        
        cancel_button = QPushButton("Отмена")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        
        # Скрываем элементы подгруппы и варианта по умолчанию
        self.subgroup_label.setVisible(False)
        self.subgroup_combo.setVisible(False)
        self.variant_label.setVisible(False)
        self.variant_combo.setVisible(False)
    
    def on_group_changed(self):
        """Обработка изменения группы"""
        group_key = self.group_combo.currentData()
        
        if not group_key:
            self.layer_combo.clear()
            self.format_combo.clear()
            self.format_combo.setEnabled(False)
            self.browse_button.setEnabled(False)
            self.import_button.setEnabled(False)
            self.layer_info.clear()
            self.format_info.clear()
            self.subgroup_label.setVisible(False)
            self.subgroup_combo.setVisible(False)
            return
        
        self.selected_group = group_key
        group_data = self.IMPORT_STRUCTURE[group_key]
        
        # Проверяем наличие подгрупп (для ЗПР)
        if "subgroups" in group_data:
            # Показываем выбор подгруппы
            self.subgroup_label.setVisible(True)
            self.subgroup_combo.setVisible(True)
            self.subgroup_combo.clear()
            self.subgroup_combo.addItem("-- Выберите подгруппу --", None)
            
            for subgroup_key, subgroup_data in group_data["subgroups"].items():
                self.subgroup_combo.addItem(
                    f"{subgroup_key} - {subgroup_data['name']}",
                    subgroup_key
                )
            
            self.layer_combo.clear()
        else:
            # Скрываем подгруппу
            self.subgroup_label.setVisible(False)
            self.subgroup_combo.setVisible(False)
            self.selected_subgroup = None
            
            # Заполняем слои
            self.update_layers(group_data["layers"])
    
    def on_subgroup_changed(self):
        """Обработка изменения подгруппы"""
        subgroup_key = self.subgroup_combo.currentData()
        
        if not subgroup_key:
            self.layer_combo.clear()
            return
        
        self.selected_subgroup = subgroup_key

        if not self.selected_group:
            return

        group_data = self.IMPORT_STRUCTURE[self.selected_group]
        subgroup_data = group_data["subgroups"][subgroup_key]
        
        # Заполняем слои
        self.update_layers(subgroup_data["layers"])
    
    def update_layers(self, layers_dict):
        """Обновление списка слоев"""
        self.layer_combo.clear()
        self.layer_combo.addItem("-- Выберите слой --", None)
        
        for layer_key, layer_data in layers_dict.items():
            self.layer_combo.addItem(
                f"{layer_key} - {layer_data['name']}",
                layer_key
            )
    
    def on_layer_changed(self):
        """Обработка изменения слоя"""
        layer_key = self.layer_combo.currentData()
        
        if not layer_key:
            self.format_combo.clear()
            self.format_combo.setEnabled(False)
            self.browse_button.setEnabled(False)
            self.import_button.setEnabled(False)
            self.layer_info.clear()
            self.format_info.clear()
            self.variant_label.setVisible(False)
            self.variant_combo.setVisible(False)
            return
        
        self.selected_layer = layer_key
        
        # Получаем данные слоя
        layer_data = self.get_layer_data(layer_key)
        
        if not layer_data:
            return
        
        # Проверяем наличие вариантов геометрии
        if "variants" in layer_data:
            self.variant_label.setVisible(True)
            self.variant_combo.setVisible(True)
            self.variant_combo.clear()
            
            for variant in layer_data["variants"]:
                self.variant_combo.addItem(variant, variant)
        else:
            self.variant_label.setVisible(False)
            self.variant_combo.setVisible(False)
        
        # Обновляем список форматов
        self.format_combo.setEnabled(True)
        self.format_combo.clear()
        
        formats = layer_data.get("formats", [])
        
        # Особая обработка для XML - он доступен только для всей группы 1_2
        if self.selected_group == "1_2_КПТ" and "XML" not in formats:
            formats = ["XML"] + formats
        
        for fmt in formats:
            self.format_combo.addItem(fmt, fmt)
        
        # Обновляем информацию о слое
        geometry_types = layer_data.get("geometry", [])
        self.layer_info.setText(
            f"Типы геометрии: {', '.join(geometry_types)}\n"
            f"Поддерживаемые форматы: {', '.join(formats)}"
        )
        
        # Активируем кнопку обзора
        self.browse_button.setEnabled(True)
    
    def get_layer_data(self, layer_key):
        """Получение данных слоя"""
        if not self.selected_group:
            return None

        group_data = self.IMPORT_STRUCTURE[self.selected_group]
        
        if "subgroups" in group_data and self.selected_subgroup:
            subgroup_data = group_data["subgroups"][self.selected_subgroup]
            return subgroup_data["layers"].get(layer_key)
        else:
            return group_data["layers"].get(layer_key)
    
    def on_format_changed(self, format_text):
        """Обработка изменения формата"""
        self.file_format = format_text
        
        # Обновляем информацию о формате
        self.update_format_info()
        
        # Сбрасываем выбранные файлы
        self.selected_files = []
        self.file_edit.clear()
        self.import_button.setEnabled(False)
        
        # Особая обработка для XML
        if format_text == "XML":
            # Для XML можно импортировать все слои группы 1_2
            self.layer_info.setText(
                "При импорте XML будут созданы все доступные слои КПТ\n"
                "с автоматическим определением типов геометрии"
            )
    
    def update_format_info(self):
        """Обновление информации о формате"""
        info_texts = {
            "XML": (
                "XML файлы Росреестра содержат полную информацию о кадастровых объектах.\n"
                "Будут импортированы все типы слоев с атрибутами и стилями.\n"
                "Можно выбрать несколько файлов для пакетной обработки."
            ),
            "DXF": (
                "DXF файлы AutoCAD или экспорт с Публичной кадастровой карты.\n"
                "Выберите один файл. Будет импортирован указанный тип слоя."
            ),
            "TAB": (
                "TAB файлы MapInfo с кадастровыми данными.\n"
                "Выберите один файл. Вспомогательные файлы (.dat, .map, .id)\n"
                "должны находиться в той же папке."
            )
        }
        
        self.format_info.setText(info_texts.get(self.file_format or "", ""))
    
    def browse_files(self):
        """Выбор файлов для импорта"""
        if not self.file_format:
            return
        
        # Определяем фильтр и режим выбора
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
            
            self.import_button.setEnabled(True)
        else:
            self.selected_files = []
            self.file_edit.clear()
            self.import_button.setEnabled(False)
    
    def validate_and_accept(self):
        """Валидация и принятие диалога"""
        if not self.selected_files:
            QMessageBox.warning(
                self,
                "Предупреждение",
                "Не выбраны файлы для импорта"
            )
            return
        
        if not self.selected_layer and self.file_format != "XML":
            QMessageBox.warning(
                self,
                "Предупреждение",
                "Не выбран тип слоя для импорта"
            )
            return
        
        self.accept()
    
    def get_import_options(self):
        """Получение опций импорта"""
        if self.result() != QDialog.Accepted:
            return None
        
        # Базовые опции
        options = {
            "format": self.file_format,
            "files": self.selected_files if self.file_format == "XML" else None,
            "file_path": self.selected_files[0] if self.selected_files and self.file_format != "XML" else None,
            "group": self.selected_group,
            "subgroup": self.selected_subgroup,
            "layer_id": self.selected_layer
        }
        
        # Добавляем вариант геометрии если есть
        if self.variant_combo.isVisible():
            variant = self.variant_combo.currentData()
            if variant:
                full_layer_id = f"{self.selected_layer}_{variant}"
                options["layer_id"] = full_layer_id
        
        # Формируем полное имя слоя
        if self.selected_layer:
            layer_data = self.get_layer_data(self.selected_layer)
            if layer_data:
                layer_name = f"{options['layer_id']}_{layer_data['name'].replace(' ', '_')}"
                options["layer_name"] = layer_name
            else:
                options["layer_name"] = options["layer_id"]
        
        # Добавляем имя группы для организации в дереве
        if self.selected_subgroup:
            options["group_name"] = self.selected_subgroup
        elif self.selected_group:
            # Для групп без подгрупп
            if self.selected_group == "1_1_Границы_работ":
                options["group_name"] = None  # Не нужна группа
            else:
                options["group_name"] = self.selected_group
        
        return options
