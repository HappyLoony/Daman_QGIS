# -*- coding: utf-8 -*-
"""
Диалог выбора слоев для экспорта
"""

import os
import subprocess
from typing import List, Optional

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QDialogButtonBox,
    QCheckBox, QGroupBox, QMessageBox
)
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QIcon

from qgis.core import QgsProject, QgsVectorLayer, QgsMessageLog, Qgis
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.managers import get_project_structure_manager, FolderType


class ExportDialog(QDialog):
    """Диалог выбора слоев для экспорта"""
    
    def __init__(self, parent=None, export_format=""):
        """
        Инициализация диалога
        
        Args:
            parent: Родительский виджет
            export_format: Формат экспорта (Excel, DXF, TAB, Batch)
        """
        super().__init__(parent)
        self.export_format = export_format
        self.settings = QSettings(PLUGIN_NAME, 'ExportDialog')
        
        self.selected_layers = []
        self.output_folder = self._get_export_folder()

        self.setup_ui()
        self.load_layers()
        self.load_settings()

    def _get_export_folder(self) -> str:
        """
        Получение фиксированной папки экспорта через M_19.

        Returns:
            str: Путь к папке Экспорт или пустая строка
        """
        structure = get_project_structure_manager()
        if structure.is_active():
            folder = structure.get_folder(FolderType.EXPORT, create=True)
            return folder if folder else ""
        return ""
    
    def setup_ui(self):
        """Создание интерфейса"""
        self.setWindowTitle(f"Экспорт в {self.export_format}")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)
        
        layout = QVBoxLayout(self)
        
        # Заголовок
        title_label = QLabel(f"<h3>Экспорт слоев в {self.export_format}</h3>")
        layout.addWidget(title_label)
        
        # Группа выбора слоев
        layers_group = QGroupBox("Выбор слоев для экспорта")
        layers_layout = QVBoxLayout()
        
        # Дерево слоев
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabel("Слои проекта")
        self.tree_widget.setSelectionMode(QTreeWidget.ExtendedSelection)
        layers_layout.addWidget(self.tree_widget)
        
        # Кнопки выбора
        button_layout = QHBoxLayout()
        
        self.select_all_btn = QPushButton("Выбрать все")
        self.select_all_btn.clicked.connect(self.select_all)
        button_layout.addWidget(self.select_all_btn)
        
        self.deselect_all_btn = QPushButton("Снять выделение")
        self.deselect_all_btn.clicked.connect(self.deselect_all)
        button_layout.addWidget(self.deselect_all_btn)
        
        button_layout.addStretch()
        layers_layout.addLayout(button_layout)
        
        layers_group.setLayout(layers_layout)
        layout.addWidget(layers_group)

        # Опции экспорта
        if self.export_format != "Batch":
            options_group = QGroupBox("Опции экспорта")
            options_layout = QVBoxLayout()
            
            self.wgs84_check = QCheckBox("Создать дополнительный файл в WGS-84")
            self.wgs84_check.setChecked(True)
            options_layout.addWidget(self.wgs84_check)
            
            if self.export_format == "Excel":
                self.add_headers_check = QCheckBox("Добавить заголовки в файл")
                self.add_headers_check.setChecked(True)
                options_layout.addWidget(self.add_headers_check)
                
                self.add_summary_check = QCheckBox("Добавить итоговую информацию")
                self.add_summary_check.setChecked(True)
                options_layout.addWidget(self.add_summary_check)
            
            options_group.setLayout(options_layout)
            layout.addWidget(options_group)
        else:
            # Для пакетного экспорта
            self.wgs84_check = QCheckBox("Создать дополнительные файлы в WGS-84")
            self.wgs84_check.setChecked(True)
            layout.addWidget(self.wgs84_check)
        
        # Кнопки диалога
        buttons_layout = QHBoxLayout()

        # Кнопка открытия папки экспорта
        self.open_folder_btn = QPushButton("Открыть папку экспорта")
        self.open_folder_btn.clicked.connect(self.open_export_folder)
        buttons_layout.addWidget(self.open_folder_btn)

        buttons_layout.addStretch()

        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        buttons_layout.addWidget(button_box)

        layout.addLayout(buttons_layout)
    
    def load_layers(self):
        """Загрузка слоев проекта в дерево"""
        self.tree_widget.clear()
        
        # Получаем все слои проекта
        layers = QgsProject.instance().mapLayers().values()
        
        # Фильтруем векторные слои с префиксами L_ или Le_
        vector_layers = []
        for layer in layers:
            if isinstance(layer, QgsVectorLayer):
                name = layer.name()
                # Проверяем префикс L_ или Le_
                if name.startswith('L_') or name.startswith('Le_'):
                    vector_layers.append(layer)
        
        # Сортируем по имени
        vector_layers.sort(key=lambda x: x.name())
        
        # Группируем по разделам (первая цифра после L_ или Le_)
        sections = {}
        for layer in vector_layers:
            name = layer.name()
            # Извлекаем номер раздела
            if name.startswith('Le_'):
                parts = name[3:].split('_')  # Пропускаем 'Le_'
            else:
                parts = name[2:].split('_')  # Пропускаем 'L_'

            if parts:
                section = parts[0]  # Первая цифра - номер раздела
                if section not in sections:
                    sections[section] = []
                sections[section].append(layer)
        
        # Добавляем в дерево
        for section, layers in sorted(sections.items()):
            # Создаем раздел
            section_names = {
                '0': 'F_0_Проект',
                '1': 'F_1_Данные',
                '2': 'F_2_Обработка',
                '3': 'F_3_Нарезка',
                '4': 'F_4_ХЛУ',
                '5': 'F_5_Настройка',
                '6': 'F_6_Выпуск'
            }
            section_name = section_names.get(section, f'F_{section}_Раздел')
            
            section_item = QTreeWidgetItem(self.tree_widget, [section_name])
            section_item.setExpanded(True)
            section_item.setFlags(section_item.flags() | Qt.ItemIsTristate | Qt.ItemIsUserCheckable)
            
            # Добавляем слои в раздел
            for layer in layers:
                layer_item = QTreeWidgetItem(section_item, [layer.name()])
                layer_item.setData(0, Qt.UserRole, layer.id())
                layer_item.setCheckState(0, Qt.Unchecked)
                layer_item.setFlags(layer_item.flags() | Qt.ItemIsUserCheckable)
    
    def select_all(self):
        """Выбрать все слои"""
        for i in range(self.tree_widget.topLevelItemCount()):
            section_item = self.tree_widget.topLevelItem(i)
            section_item.setCheckState(0, Qt.Checked)
    
    def deselect_all(self):
        """Снять выделение со всех слоев"""
        for i in range(self.tree_widget.topLevelItemCount()):
            section_item = self.tree_widget.topLevelItem(i)
            section_item.setCheckState(0, Qt.Unchecked)

    def open_export_folder(self):
        """Открыть папку экспорта в проводнике"""
        if self.output_folder and os.path.exists(self.output_folder):
            # Windows
            if os.name == 'nt':
                os.startfile(self.output_folder)
            # macOS
            elif os.sys.platform == 'darwin':
                subprocess.run(['open', self.output_folder])
            # Linux
            else:
                subprocess.run(['xdg-open', self.output_folder])
        else:
            QMessageBox.warning(
                self,
                "Предупреждение",
                "Папка экспорта не найдена.\nОткройте проект Daman."
            )

    def load_settings(self):
        """Загрузка сохраненных настроек"""
        # Опция WGS-84
        create_wgs84 = self.settings.value('create_wgs84', True, type=bool)
        self.wgs84_check.setChecked(create_wgs84)

    def save_settings(self):
        """Сохранение настроек"""
        # Сохраняем опцию WGS-84
        self.settings.setValue('create_wgs84', self.wgs84_check.isChecked())
    
    def get_selected_layers(self) -> List[QgsVectorLayer]:
        """Получение выбранных слоев"""
        selected = []
        
        for i in range(self.tree_widget.topLevelItemCount()):
            section_item = self.tree_widget.topLevelItem(i)
            
            for j in range(section_item.childCount()):
                layer_item = section_item.child(j)
                
                if layer_item.checkState(0) == Qt.Checked:
                    layer_id = layer_item.data(0, Qt.UserRole)
                    layer = QgsProject.instance().mapLayer(layer_id)
                    if layer:
                        selected.append(layer)
        
        return selected
    
    def get_export_options(self) -> dict:
        """Получение опций экспорта"""
        options = {
            'create_wgs84': self.wgs84_check.isChecked()
        }
        
        if self.export_format == "Excel":
            if hasattr(self, 'add_headers_check'):
                options['add_headers'] = self.add_headers_check.isChecked()
            if hasattr(self, 'add_summary_check'):
                options['add_summary'] = self.add_summary_check.isChecked()
        
        return options
    
    def accept(self):
        """Обработка нажатия OK"""
        # Проверяем выбранные слои
        self.selected_layers = self.get_selected_layers()
        if not self.selected_layers:
            QMessageBox.warning(
                self,
                "Предупреждение",
                "Не выбрано ни одного слоя для экспорта"
            )
            return

        # Проверяем папку экспорта (фиксированная через M_19)
        if not self.output_folder:
            QMessageBox.warning(
                self,
                "Предупреждение",
                "Папка экспорта не определена.\nОткройте проект Daman."
            )
            return

        # Папка создаётся автоматически через M_19
        if not os.path.exists(self.output_folder):
            os.makedirs(self.output_folder, exist_ok=True)

        # Сохраняем настройки
        self.save_settings()

        # Закрываем диалог
        super().accept()
