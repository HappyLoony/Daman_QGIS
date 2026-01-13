# -*- coding: utf-8 -*-
"""
Универсальный диалог импорта данных
Интерфейс с 5 уровнями выбора: Раздел -> Группа -> Слой -> Подслой -> Файл
"""

import os
import json
from typing import Dict, Optional, List, Any
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFileDialog, QGroupBox, QMessageBox,
    QLineEdit, QSizePolicy, QFrame
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QFont
from qgis.core import QgsMessageLog, Qgis, QgsProject
from Daman_QGIS.managers import get_reference_managers
from Daman_QGIS.database.project_db import ProjectDB
from Daman_QGIS.utils import log_info, log_warning, log_error


class UniversalImportDialog(QDialog):
    """Универсальный диалог импорта с 5-уровневым выбором слоя"""
    
    def __init__(self, plugin_dir: str, parent=None):
        """
        Инициализация диалога
        
        Args:
            plugin_dir: Путь к директории плагина
            parent: Родительское окно
        """
        super().__init__(parent)
        self.plugin_dir = plugin_dir
        self.setWindowTitle("Импорт данных")
        self.setMinimumWidth(600)
        self.setMaximumHeight(500)
        
        # Атрибуты для хранения выбранных опций
        self.selected_file = None
        self.selected_format = None
        self.selected_section = None
        self.selected_group = None
        self.selected_layer = None
        self.selected_sublayer = None
        self.selected_full_name = None  # Полное имя слоя (например: 2_1_1_Выборка_ЗУ)
        
        # Загружаем структуру слоев из Base_layers.json
        self.base_layers = self._load_base_layers()
        if not self.base_layers:
            self.base_layers = []  # Fallback на пустой список при ошибке

        # Структуры для хранения иерархии
        self.sections = {}  # {section_num: section_name}
        self.groups_by_section = {}  # {section_num: {group_key: group_name}}
        self.layers_by_group = {}  # {group_key: {layer_key: layer_name}}
        self.sublayers_by_layer = {}  # {layer_key: {sublayer_key: sublayer_name}}
        self.layer_info = {}  # {full_name: layer_data}

        # Получаем тип объекта проекта для фильтрации слоёв ЗПР
        self.project_object_type = self._get_project_object_type()

        # Парсим структуру
        self._parse_base_layers()

        # Создаем интерфейс
        self.setup_ui()

    def _get_project_object_type(self) -> Optional[str]:
        """
        Получение типа объекта проекта из метаданных.

        Returns:
            'Площадной', 'Линейный' или None если не определён
        """
        try:
            # Получаем путь к проекту
            project = QgsProject.instance()
            project_path = project.homePath()
            if not project_path:
                return None

            # Ищем GPKG файл
            gpkg_path = os.path.join(project_path, 'project.gpkg')
            if not os.path.exists(gpkg_path):
                return None

            # Получаем тип объекта из метаданных
            project_db = ProjectDB(gpkg_path)
            metadata = project_db.get_all_metadata()

            if metadata and '1_2_object_type' in metadata:
                object_type = metadata['1_2_object_type'].get('value', '')
                log_info(f"UniversalImportDialog: Тип объекта проекта = '{object_type}'")
                return object_type

            return None
        except Exception as e:
            log_warning(f"UniversalImportDialog: Не удалось получить тип объекта: {e}")
            return None

    def _is_zpr_layer_allowed(self, layer_name: str) -> bool:
        """
        Проверка разрешён ли импорт слоя ЗПР для текущего типа объекта.

        Бизнес-правило:
        - Площадной объект: только ЗПР_ОКС
        - Линейный объект: все слои ЗПР

        Args:
            layer_name: Имя слоя (например 'ЗПР_ОКС', 'ЗПР_ПО')

        Returns:
            True если слой разрешён для импорта
        """
        # Если тип объекта не определён - разрешаем все
        if not self.project_object_type:
            return True

        # Для линейных объектов разрешены все слои ЗПР
        if self.project_object_type == 'Линейный':
            return True

        # Для площадных объектов - только ЗПР_ОКС
        if self.project_object_type == 'Площадной':
            # Разрешённые слои для площадных объектов
            allowed_layers = ['ЗПР_ОКС']
            return layer_name in allowed_layers

        return True

    def _load_base_layers(self) -> List[Dict[str, Any]]:
        """Загрузка Base_layers.json через LayerReferenceManager"""
        from Daman_QGIS.managers.submodules.Msm_4_6_layer_reference_manager import LayerReferenceManager
        from Daman_QGIS.constants import DATA_REFERENCE_PATH

        layer_manager = LayerReferenceManager(DATA_REFERENCE_PATH)
        data = layer_manager.get_base_layers()
        if not data:
            raise RuntimeError("Base_layers.json не найден или пуст")
        return data
    
    def _parse_base_layers(self):
        """Парсинг структуры слоев для формирования иерархии"""
        # Разрешенные разделы (рабочие слои L_1, L_2, L_3, L_4)
        # Исключаем веб-слои (WFS, WMS) и служебные слои

        for layer_data in self.base_layers:
            section_num = layer_data.get('section_num')
            full_name = layer_data.get('full_name', '')
            group_num = layer_data.get('group_num')
            group_name = layer_data.get('group', '')

            # Пропускаем пустые section_num
            if not section_num:
                continue

            # section_num теперь без префикса (просто "1", "2" и т.д.)
            # full_name содержит префикс L_ или Le_

            # Пропускаем L_1_1_2, L_1_1_3 и L_1_1_4 (автоматически создаются при импорте L_1_1_1)
            if full_name in ['L_1_1_2_Границы_работ_10_м', 'L_1_1_3_Границы_работ_500_м', 'L_1_1_4_Границы_работ_-2_см']:
                continue

            # Пропускаем группу 1_2 (WFS) - загружается через веб
            if section_num == '1' and group_num == '2':
                continue

            # Пропускаем WMS слои из группы 1_3 - загружаются через F_1_2
            if section_num == '1' and group_num == '3' and group_name == 'WMS':
                continue

            # Пропускаем группу 1_4 (OSM) - загружается через F_1_2
            if section_num == '1' and group_num == '4':
                continue
            
            # Добавляем раздел
            section_name = layer_data.get('section', '')
            if section_num not in self.sections:
                self.sections[section_num] = f"{section_num}_{section_name}"
                self.groups_by_section[section_num] = {}

            # Добавляем группу (group_num и group_name уже получены выше)
            group_key = f"{section_num}_{group_num}"
            
            if group_key not in self.groups_by_section[section_num]:
                self.groups_by_section[section_num][group_key] = f"{group_key}_{group_name}"
                self.layers_by_group[group_key] = {}
            
            # Добавляем слой
            layer_num = layer_data.get('layer_num')
            layer_name = layer_data.get('layer', '')
            layer_key = f"{section_num}_{group_num}_{layer_num}"
            
            if layer_key not in self.layers_by_group[group_key]:
                self.layers_by_group[group_key][layer_key] = f"{layer_key}_{layer_name}"
                self.sublayers_by_layer[layer_key] = {}
            
            # Добавляем подслой если есть
            sublayer_num = layer_data.get('sublayer_num')
            sublayer_name = layer_data.get('sublayer', '')
            full_name = layer_data.get('full_name', '')
            
            if sublayer_num:
                sublayer_key = f"{layer_key}_{sublayer_num}"
                self.sublayers_by_layer[layer_key][sublayer_key] = f"{sublayer_key}_{sublayer_name}"
                self.layer_info[full_name] = layer_data
            else:
                # Для слоев без подслоев
                self.layer_info[full_name] = layer_data
    
    def setup_ui(self):
        """Создание интерфейса"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Заголовок
        title_label = QLabel("Импорт данных в проект")
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # ========================================
        # ПЕРВОЕ: Группа выбора файла
        # ========================================
        file_group = QGroupBox("Шаг 1: Выбор файла для импорта")
        file_layout = QVBoxLayout()

        file_input_layout = QHBoxLayout()

        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        self.file_edit.setPlaceholderText("Файл не выбран")
        file_input_layout.addWidget(self.file_edit)

        self.browse_button = QPushButton("Обзор...")
        self.browse_button.clicked.connect(self.browse_file)
        self.browse_button.setEnabled(True)  # Всегда доступна!
        file_input_layout.addWidget(self.browse_button)

        file_layout.addLayout(file_input_layout)

        # Информация о формате и автоопределении
        self.format_info_label = QLabel("")
        self.format_info_label.setStyleSheet("color: #0066cc; font-size: 9pt; font-weight: bold;")
        file_layout.addWidget(self.format_info_label)

        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        # ========================================
        # ВТОРОЕ: Группа выбора слоя (заблокирована по умолчанию)
        # ========================================
        selection_group = QGroupBox("Шаг 2: Выбор слоя для импорта (только для DXF/TAB)")
        selection_layout = QVBoxLayout()
        self.selection_group = selection_group  # Сохраняем ссылку
        
        # 1. Комбобокс раздела
        section_layout = QHBoxLayout()
        section_label = QLabel("Раздел:")
        section_label.setMinimumWidth(80)
        section_layout.addWidget(section_label)
        
        self.section_combo = QComboBox()
        self.section_combo.addItem("-- Выберите раздел --", None)
        for section_num in sorted(self.sections.keys()):
            self.section_combo.addItem(self.sections[section_num], section_num)
        self.section_combo.currentIndexChanged.connect(self.on_section_changed)
        self.section_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        section_layout.addWidget(self.section_combo)
        selection_layout.addLayout(section_layout)
        
        # 2. Комбобокс группы
        group_layout = QHBoxLayout()
        group_label = QLabel("Группа:")
        group_label.setMinimumWidth(80)
        group_layout.addWidget(group_label)
        
        self.group_combo = QComboBox()
        self.group_combo.addItem("-- Сначала выберите раздел --", None)
        self.group_combo.setEnabled(False)
        self.group_combo.currentIndexChanged.connect(self.on_group_changed)
        self.group_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        group_layout.addWidget(self.group_combo)
        selection_layout.addLayout(group_layout)
        
        # 3. Комбобокс слоя
        layer_layout = QHBoxLayout()
        layer_label = QLabel("Слой:")
        layer_label.setMinimumWidth(80)
        layer_layout.addWidget(layer_label)
        
        self.layer_combo = QComboBox()
        self.layer_combo.addItem("-- Сначала выберите группу --", None)
        self.layer_combo.setEnabled(False)
        self.layer_combo.currentIndexChanged.connect(self.on_layer_changed)
        self.layer_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        layer_layout.addWidget(self.layer_combo)
        selection_layout.addLayout(layer_layout)
        
        # 4. Комбобокс подслоя (опциональный)
        sublayer_layout = QHBoxLayout()
        sublayer_label = QLabel("Под слой:")
        sublayer_label.setMinimumWidth(80)
        sublayer_layout.addWidget(sublayer_label)
        
        self.sublayer_combo = QComboBox()
        self.sublayer_combo.addItem("-", None)  # По умолчанию нет подслоя
        self.sublayer_combo.setEnabled(False)
        self.sublayer_combo.currentIndexChanged.connect(self.on_sublayer_changed)
        self.sublayer_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        sublayer_layout.addWidget(self.sublayer_combo)
        selection_layout.addLayout(sublayer_layout)
        
        selection_group.setLayout(selection_layout)
        selection_group.setEnabled(False)  # По умолчанию заблокирована
        layout.addWidget(selection_group)
        
        # ========================================
        # ТРЕТЬЕ: Импорт координат (отдельная область)
        # ========================================
        coords_group = QGroupBox("Импорт координат вручную")
        coords_layout = QHBoxLayout()

        coords_info = QLabel("Вставка координат из буфера обмена")
        coords_info.setStyleSheet("color: #666;")
        coords_layout.addWidget(coords_info)

        coords_layout.addStretch()

        self.coords_import_btn = QPushButton("Импорт координат")
        self.coords_import_btn.clicked.connect(self.open_coordinate_input)
        coords_layout.addWidget(self.coords_import_btn)

        coords_group.setLayout(coords_layout)
        layout.addWidget(coords_group)

        # Растяжка
        layout.addStretch()

        # Кнопки
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.import_button = QPushButton("Импорт")
        self.import_button.clicked.connect(self.validate_and_accept)
        self.import_button.setEnabled(False)
        button_layout.addWidget(self.import_button)
        
        cancel_button = QPushButton("Закрыть")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
    
    def on_section_changed(self):
        """Обработка изменения раздела"""
        section_num = self.section_combo.currentData()
        
        # Очищаем все последующие комбобоксы
        self.group_combo.clear()
        self.layer_combo.clear()
        self.sublayer_combo.clear()
        self.sublayer_combo.addItem("-", None)
        
        if not section_num:
            self.group_combo.addItem("-- Сначала выберите раздел --", None)
            self.group_combo.setEnabled(False)
            self.layer_combo.addItem("-- Сначала выберите группу --", None)
            self.layer_combo.setEnabled(False)
            self.sublayer_combo.setEnabled(False)
            self.selected_section = None
            return
        
        self.selected_section = section_num
        
        # Заполняем группы для выбранного раздела
        if section_num in self.groups_by_section:
            self.group_combo.addItem("-- Выберите группу --", None)
            groups = self.groups_by_section[section_num]
            for group_key, group_name in sorted(groups.items()):
                self.group_combo.addItem(group_name, group_key)
            self.group_combo.setEnabled(True)
        else:
            self.group_combo.addItem("-- Нет групп в разделе --", None)
            self.group_combo.setEnabled(False)
        
        # Остальные комбобоксы остаются неактивными
        self.layer_combo.addItem("-- Сначала выберите группу --", None)
        self.layer_combo.setEnabled(False)
        self.sublayer_combo.setEnabled(False)

        self.update_import_button_state()
    
    def on_group_changed(self):
        """Обработка изменения группы"""
        group_key = self.group_combo.currentData()

        # Очищаем последующие комбобоксы
        self.layer_combo.clear()
        self.sublayer_combo.clear()
        self.sublayer_combo.addItem("-", None)

        if not group_key:
            self.layer_combo.addItem("-- Сначала выберите группу --", None)
            self.layer_combo.setEnabled(False)
            self.sublayer_combo.setEnabled(False)
            self.selected_group = None
            return

        self.selected_group = group_key

        # Определяем, является ли это группой ЗПР (2_4 или 2_5)
        is_zpr_group = group_key in ['2_4', '2_5']

        # Заполняем слои для выбранной группы
        if group_key in self.layers_by_group:
            self.layer_combo.addItem("-- Выберите слой --", None)
            layers = self.layers_by_group[group_key]
            added_count = 0

            for layer_key, layer_name in sorted(layers.items()):
                # Для групп ЗПР применяем фильтрацию по типу объекта
                if is_zpr_group:
                    # Извлекаем имя слоя из layer_name (например "2_4_1_ЗПР_ОКС" -> "ЗПР_ОКС")
                    parts = layer_name.split('_')
                    if len(parts) >= 4:
                        zpr_layer_name = '_'.join(parts[3:])  # "ЗПР_ОКС", "ЗПР_ПО", etc.
                    else:
                        zpr_layer_name = layer_name

                    # Проверяем разрешён ли слой для текущего типа объекта
                    if not self._is_zpr_layer_allowed(zpr_layer_name):
                        continue  # Пропускаем запрещённые слои

                self.layer_combo.addItem(layer_name, layer_key)
                added_count += 1

            if added_count > 0:
                self.layer_combo.setEnabled(True)
            else:
                # Если все слои отфильтрованы
                self.layer_combo.clear()
                self.layer_combo.addItem("-- Нет доступных слоев для Площадного объекта --", None)
                self.layer_combo.setEnabled(False)
                log_warning(f"UniversalImportDialog: Все слои группы {group_key} отфильтрованы для типа объекта '{self.project_object_type}'")
        else:
            self.layer_combo.addItem("-- Нет слоев в группе --", None)
            self.layer_combo.setEnabled(False)

        self.sublayer_combo.setEnabled(False)
        self.selected_layer = None
        self.update_import_button_state()
    
    def on_layer_changed(self):
        """Обработка изменения слоя"""
        layer_key = self.layer_combo.currentData()
        
        # Очищаем комбобокс подслоев
        self.sublayer_combo.clear()
        
        if not layer_key:
            self.sublayer_combo.addItem("-", None)
            self.sublayer_combo.setEnabled(False)
            self.browse_button.setEnabled(False)
            self.selected_layer = None
            self.selected_full_name = None
            return
        
        self.selected_layer = layer_key
        
        # Проверяем, есть ли подслои
        if layer_key in self.sublayers_by_layer and self.sublayers_by_layer[layer_key]:
            # Есть подслои
            self.sublayer_combo.addItem("-- Выберите под слой --", None)
            sublayers = self.sublayers_by_layer[layer_key]
            for sublayer_key, sublayer_name in sorted(sublayers.items()):
                self.sublayer_combo.addItem(sublayer_name, sublayer_key)
            self.sublayer_combo.setEnabled(True)
        else:
            # Нет подслоев
            self.sublayer_combo.addItem("-", None)
            self.sublayer_combo.setEnabled(False)
            # Формируем полное имя слоя
            layer_name_in_combo = self.layer_combo.currentText()
            self.selected_full_name = layer_name_in_combo
        
        self.update_import_button_state()
    
    def on_sublayer_changed(self):
        """Обработка изменения подслоя"""
        sublayer_key = self.sublayer_combo.currentData()
        
        if sublayer_key:
            self.selected_sublayer = sublayer_key
            # Формируем полное имя включая подслой
            sublayer_name_in_combo = self.sublayer_combo.currentText()
            self.selected_full_name = sublayer_name_in_combo
        else:
            self.selected_sublayer = None
            if self.selected_layer:
                # Если нет подслоя, используем имя слоя
                layer_name_in_combo = self.layer_combo.currentText()
                self.selected_full_name = layer_name_in_combo
        
        self.update_import_button_state()
    
    def browse_file(self):
        """Выбор файла для импорта"""
        # Фильтр только для разрешенных форматов
        filter_str = "Поддерживаемые форматы (*.xml *.tab *.dxf);;XML файлы (*.xml);;TAB файлы (*.tab);;DXF файлы (*.dxf);;Все файлы (*.*)"

        # Для XML разрешаем множественный выбор, для других - одиночный
        file_paths, selected_filter = QFileDialog.getOpenFileNames(
            self,
            "Выберите файл(ы) для импорта",
            "",
            filter_str
        )

        if not file_paths:
            self.selected_file = None
            self.selected_format = None
            self.file_edit.clear()
            self.format_info_label.setText("")
            self.selection_group.setEnabled(False)
            self.update_import_button_state()
            return

        # Определяем формат по расширению первого файла
        first_file = file_paths[0]
        ext = os.path.splitext(first_file)[1].lower()

        # Проверяем что все файлы одного формата
        for fp in file_paths:
            if os.path.splitext(fp)[1].lower() != ext:
                QMessageBox.warning(
                    self,
                    "Ошибка",
                    "Все выбранные файлы должны быть одного формата!"
                )
                return

        self.selected_file = file_paths if len(file_paths) > 1 else file_paths[0]

        # Отображение выбранных файлов
        if isinstance(self.selected_file, list):
            self.file_edit.setText(f"{len(self.selected_file)} файл(ов): {os.path.basename(file_paths[0])} ...")
        else:
            self.file_edit.setText(os.path.basename(self.selected_file))

        # Определяем формат и управляем UI
        if ext == '.xml':
            self.selected_format = 'XML'
            self.format_info_label.setText(
                "✓ Формат: XML (КПТ/Выписки ЕГРН)\n"
                "ℹ Слои будут определены автоматически"
            )
            # БЛОКИРУЕМ выбор слоя для XML
            self.selection_group.setEnabled(False)
            self.selected_full_name = "AUTO_XML"  # Специальное значение для XML

        elif ext == '.tab':
            self.selected_format = 'TAB'
            self.format_info_label.setText("✓ Формат: TAB (MapInfo)\nℹ Выберите целевой слой ниже")
            # РАЗБЛОКИРУЕМ выбор слоя
            self.selection_group.setEnabled(True)
            self.selected_full_name = None

        elif ext == '.dxf':
            self.selected_format = 'DXF'
            self.format_info_label.setText("✓ Формат: DXF (AutoCAD)\nℹ Выберите целевой слой ниже")
            # РАЗБЛОКИРУЕМ выбор слоя
            self.selection_group.setEnabled(True)
            self.selected_full_name = None

        else:
            self.selected_format = None
            self.format_info_label.setText("❌ Неподдерживаемый формат файла")
            self.selection_group.setEnabled(False)
            self.selected_full_name = None

        self.update_import_button_state()
    
    def update_import_button_state(self):
        """Обновление состояния кнопки импорта"""
        # Для XML достаточно выбрать файл (слой определится автоматически)
        if self.selected_format == 'XML':
            enabled = bool(self.selected_file)
        else:
            # Для DXF/TAB требуется выбрать и файл, и слой
            enabled = bool(
                self.selected_file and
                self.selected_format and
                self.selected_full_name
            )
        self.import_button.setEnabled(enabled)
    
    def validate_and_accept(self):
        """Валидация и принятие диалога"""
        if not self.selected_file:
            QMessageBox.warning(
                self,
                "Предупреждение",
                "Не выбран файл для импорта"
            )
            return

        if not self.selected_format:
            QMessageBox.warning(
                self,
                "Предупреждение",
                "Неподдерживаемый формат файла"
            )
            return

        # Для XML слой определяется автоматически, проверка не нужна
        if self.selected_format != 'XML':
            if not self.selected_full_name:
                QMessageBox.warning(
                    self,
                    "Предупреждение",
                    "Не выбран слой для импорта"
                )
                return

            # Проверяем существование слоя в проекте (только для DXF/TAB)
            existing_layers = QgsProject.instance().mapLayersByName(self.selected_full_name)
            if existing_layers:
                # Слой уже существует, спрашиваем о замене
                reply = QMessageBox.question(
                    self,
                    "Подтверждение",
                    f"Слой '{self.selected_full_name}' уже существует в проекте.\nЗаменить?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )

                if reply == QMessageBox.No:
                    return

                # Удаляем существующий слой
                for layer in existing_layers:
                    QgsProject.instance().removeMapLayer(layer.id())

        self.accept()
    
    def open_coordinate_input(self):
        """Открытие диалога импорта координат."""
        from Daman_QGIS.tools.F_1_data.submodules.Fsm_1_1_3_coordinate_input import Fsm_1_1_3_CoordinateInput

        handler = Fsm_1_1_3_CoordinateInput(self, self.plugin_dir)
        handler.show_dialog()

    def get_import_options(self) -> Optional[Dict]:
        """
        Получение опций импорта

        Returns:
            Словарь с параметрами импорта или None
        """
        if self.result() != QDialog.Accepted:
            return None

        # Ищем информацию о слое по его полному имени
        # ВАЖНО: В layer_info ключи имеют префикс L_ или Le_ (из full_name в базе),
        # а selected_full_name берется из комбобокса без префикса
        # Нужно добавить правильный префикс:
        # - Le_ для подслоев (когда selected_sublayer != None)
        # - L_ для основных слоев
        search_key = self.selected_full_name
        if search_key and not search_key.startswith('L_') and not search_key.startswith('Le_'):
            if self.selected_sublayer:
                # Это подслой - используем префикс Le_
                search_key = f"Le_{search_key}"
            else:
                # Это основной слой - используем префикс L_
                search_key = f"L_{search_key}"

        layers = {}
        layer_data = self.layer_info.get(search_key)

        if layer_data:
            # Формируем данные слоя для импорта
            layers[search_key] = {
                'data': layer_data,
                'group': self.selected_group,
                'name': search_key
            }
        else:
            # Для AUTO_XML это нормально - слои определяются автоматически
            if self.selected_full_name != "AUTO_XML":
                log_error(f"UniversalImportDialog: Слой '{search_key}' не найден в базе данных!")
                log_error(f"UniversalImportDialog: Доступные слои: {', '.join(sorted(self.layer_info.keys())[:5])}...")

        # Нормализуем files в список
        files_list = self.selected_file if isinstance(self.selected_file, list) else [self.selected_file]

        return {
            "format": self.selected_format,
            "files": files_list,
            "layers": layers,
            "layer_name": search_key if layer_data else self.selected_full_name,  # Полное имя слоя с префиксом
            "options": {
                # Эти опции всегда включены
                "check_precision": False,  # Отключено по требованию
                "save_to_gpkg": True,      # Всегда сохраняем
                "apply_styles": True,       # Всегда применяем стили
                "organize_groups": True     # Всегда группируем
            }
        }
