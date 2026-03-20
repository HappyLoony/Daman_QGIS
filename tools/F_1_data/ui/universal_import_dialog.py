# -*- coding: utf-8 -*-
"""
Универсальный диалог импорта данных
Интерфейс с 5 уровнями выбора: Раздел -> Группа -> Слой -> Подслой -> Файл
"""

import os
from typing import Dict, Optional, List, Any
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFileDialog, QGroupBox, QMessageBox,
    QLineEdit, QSizePolicy, QFrame
)
from qgis.PyQt.QtCore import Qt, pyqtSignal, QSettings, QStandardPaths
from qgis.PyQt.QtGui import QFont
from qgis.core import QgsMessageLog, Qgis, QgsProject
from Daman_QGIS.managers import get_reference_managers
from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.core.base_responsive_dialog import BaseResponsiveDialog


class UniversalImportDialog(BaseResponsiveDialog):
    """Универсальный диалог импорта с 5-уровневым выбором слоя"""

    WIDTH_RATIO = 0.40
    HEIGHT_RATIO = 0.55
    MIN_WIDTH = 550
    MAX_WIDTH = 750
    MIN_HEIGHT = 400
    MAX_HEIGHT = 550
    
    def __init__(self, plugin_dir: str, parent=None, object_type: Optional[str] = None):
        """
        Инициализация диалога

        Args:
            plugin_dir: Путь к директории плагина
            parent: Родительское окно
            object_type: Тип объекта проекта ('area'/'linear') из ProjectManager
        """
        super().__init__(parent)
        self.plugin_dir = plugin_dir
        self.setWindowTitle("Импорт данных")

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

        # Тип объекта проекта для фильтрации слоёв ЗПР (из ProjectManager)
        self.project_object_type = object_type
        log_info(f"UniversalImportDialog: project_object_type = '{self.project_object_type}'")

        # Парсим структуру
        self._parse_base_layers()

        # Создаем интерфейс
        self.setup_ui()

    def _is_group_allowed(self, group_key: str) -> bool:
        """
        Проверка доступна ли группа для текущего типа объекта.

        Для площадных объектов: группы РЕК (1_13, 2_2, 2_6, 3_3) скрыты полностью,
        в остальных ЗПР-группах проверяем наличие хотя бы одного разрешённого слоя.
        """
        if self.project_object_type != 'area':
            return True

        # Группы РЕК — полностью недоступны для площадных объектов
        rek_groups = ('1_13', '2_2', '2_6', '3_3')
        if group_key in rek_groups:
            return False

        # Остальные ЗПР-группы — проверяем есть ли хотя бы один разрешённый слой
        zpr_groups = ('1_12', '2_1', '2_5', '3_2')
        if group_key in zpr_groups:
            layers = self.layers_by_group.get(group_key, {})
            for layer_name in layers.values():
                parts = layer_name.split('_')
                zpr_name = '_'.join(parts[3:]) if len(parts) >= 4 else layer_name
                if self._is_zpr_layer_allowed(zpr_name):
                    return True
            return False

        return True

    def _is_zpr_layer_allowed(self, layer_name: str) -> bool:
        """
        Проверка разрешён ли импорт слоя ЗПР для текущего типа объекта.

        Бизнес-правило:
        - Площадной объект: только слои с ОКС (ЗПР_ОКС, Лес_ЗПР_ОКС и их нарезка)
        - Линейный объект: все слои ЗПР

        Args:
            layer_name: Имя слоя (например 'ЗПР_ОКС', 'ЗПР_ПО', 'Лес_ЗПР_ОКС')

        Returns:
            True если слой разрешён для импорта
        """
        # Если тип объекта не определён - разрешаем все
        if not self.project_object_type:
            return True

        # Для линейных объектов разрешены все слои ЗПР
        # Значение в БД: 'linear' (НЕ 'Линейный')
        if self.project_object_type == 'linear':
            return True

        # Для площадных объектов - только слои содержащие ОКС
        # Значение в БД: 'area' (НЕ 'Площадной')
        if self.project_object_type == 'area':
            return 'ОКС' in layer_name

        return True

    def _find_quick_matches(self, filename: str) -> List[Dict[str, Any]]:
        """
        Поиск топ-3 слоёв по релевантности к имени файла.

        Двухэтапный: точное совпадение подстроки, затем token overlap.
        Учитывает фильтрацию по типу объекта (area/linear).

        Args:
            filename: Имя файла без расширения (например 'DPT_UDS')

        Returns:
            Список до 3 записей с ключами: full_name, section_num, group_key,
            layer_key, sublayer_key (или None)
        """
        query = filename.upper()
        query_tokens = set(query.split('_'))
        candidates = []

        for full_name, layer_data in self.layer_info.items():
            name_upper = full_name.upper()
            section_num = layer_data.get('section_num', '')
            group_num = layer_data.get('group_num', '')
            group_key = f"{section_num}_{group_num}"

            # Фильтрация: import_enabled + тип объекта (группа + слой)
            if not self._is_group_allowed(group_key):
                continue
            zpr_groups = ('1_12', '1_13', '2_1', '2_2', '2_5', '2_6', '3_2', '3_3')
            if group_key in zpr_groups:
                parts = full_name.split('_')
                zpr_name = '_'.join(parts[3:]) if len(parts) >= 4 else full_name
                if not self._is_zpr_layer_allowed(zpr_name):
                    continue

            # Извлекаем суффикс full_name после L_X_Y_Z_ (или Le_X_Y_Z_A_)
            suffix = full_name
            if full_name.startswith('L_') or full_name.startswith('Le_'):
                parts = full_name.split('_')
                # L_1_12_1_ЗПР_ОКС -> ЗПР_ОКС (skip 4 parts)
                # Le_2_1_1_1_Нарезка -> Нарезка (skip 5 parts)
                skip = 5 if full_name.startswith('Le_') else 4
                suffix = '_'.join(parts[skip:]) if len(parts) > skip else full_name
            suffix_upper = suffix.upper()

            # Этап 1a: полное совпадение суффикса с запросом
            if query == suffix_upper:
                candidates.append((0, full_name, layer_data))
                continue

            # Этап 1b: запрос содержит суффикс или суффикс содержит запрос
            if query in suffix_upper or suffix_upper in query or query in name_upper:
                candidates.append((1, full_name, layer_data))
                continue

            # Этап 2: token overlap
            name_tokens = set(name_upper.split('_'))
            common = query_tokens & name_tokens
            if common:
                candidates.append((2 - len(common) / max(len(query_tokens), 1), full_name, layer_data))

        # Сортировка: по score (меньше = лучше), затем по длине разницы с запросом
        candidates.sort(key=lambda c: (c[0], abs(len(c[1]) - len(query))))

        results = []
        for _, full_name, layer_data in candidates[:3]:
            section_num = layer_data.get('section_num', '')
            group_num = layer_data.get('group_num', '')
            layer_num = layer_data.get('layer_num', '')
            sublayer_num = layer_data.get('sublayer_num')

            group_key = f"{section_num}_{group_num}"
            layer_key = f"{section_num}_{group_num}_{layer_num}"
            sublayer_key = f"{layer_key}_{sublayer_num}" if sublayer_num else None

            results.append({
                'full_name': full_name,
                'section_num': section_num,
                'group_key': group_key,
                'layer_key': layer_key,
                'sublayer_key': sublayer_key,
            })

        return results

    def _update_quick_matches(self, filename: str) -> None:
        """Обновить блок быстрого выбора после выбора файла."""
        matches = self._find_quick_matches(filename)
        self._quick_match_data = matches

        # Обновляем кнопки
        for i, btn in enumerate(self.quick_match_buttons):
            if i < len(matches):
                btn.setText(matches[i]['full_name'])
                btn.setVisible(True)
            else:
                btn.setVisible(False)

        # "Совпадений не найдено"
        self.quick_match_no_results.setVisible(len(matches) == 0)
        self.quick_match_group.setVisible(True)

    def _on_quick_match_clicked(self, index: int) -> None:
        """Обработчик нажатия кнопки быстрого выбора — заполняет комбобоксы."""
        if index >= len(self._quick_match_data):
            return

        match = self._quick_match_data[index]
        section_num = match['section_num']
        group_key = match['group_key']
        layer_key = match['layer_key']
        sublayer_key = match.get('sublayer_key')

        log_info(f"UniversalImportDialog: Quick match -> {match['full_name']}")

        # 1. Раздел
        idx = self.section_combo.findData(section_num)
        if idx >= 0:
            self.section_combo.setCurrentIndex(idx)

        # 2. Группа (после каскадного обновления от section)
        idx = self.group_combo.findData(group_key)
        if idx >= 0:
            self.group_combo.setCurrentIndex(idx)

        # 3. Слой
        idx = self.layer_combo.findData(layer_key)
        if idx >= 0:
            self.layer_combo.setCurrentIndex(idx)

        # 4. Подслой (если есть)
        if sublayer_key:
            idx = self.sublayer_combo.findData(sublayer_key)
            if idx >= 0:
                self.sublayer_combo.setCurrentIndex(idx)

    def _load_base_layers(self) -> List[Dict[str, Any]]:
        """Загрузка Base_layers.json через LayerReferenceManager"""
        from Daman_QGIS.managers import LayerReferenceManager

        layer_manager = LayerReferenceManager()
        data = layer_manager.get_base_layers()
        if not data:
            raise RuntimeError("Base_layers.json не найден или пуст")
        return data
    
    def _parse_base_layers(self):
        """Парсинг структуры слоев для формирования иерархии"""
        # Фильтрация по полю import_enabled из Base_layers.json
        # import_enabled=1 (или отсутствует) -> слой доступен для импорта
        # import_enabled=0 -> слой скрыт из диалога импорта

        for layer_data in self.base_layers:
            section_num = layer_data.get('section_num')
            full_name = layer_data.get('full_name', '')
            group_num = layer_data.get('group_num')
            group_name = layer_data.get('group', '')

            # Пропускаем пустые section_num
            if not section_num:
                continue

            # Проверяем флаг import_enabled (по умолчанию = 1 для обратной совместимости)
            import_enabled = layer_data.get('import_enabled', 1)
            if import_enabled == 0 or import_enabled == '0':
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
        # БЫСТРЫЙ ВЫБОР: Подсказки на основе имени файла
        # ========================================
        self.quick_match_group = QGroupBox("Быстрый выбор")
        quick_match_layout = QVBoxLayout()
        quick_match_layout.setSpacing(4)

        self.quick_match_buttons: List[QPushButton] = []
        for i in range(3):
            btn = QPushButton()
            btn.setFlat(True)
            btn.setStyleSheet(
                "QPushButton { text-align: left; padding: 4px 8px; "
                "border: 1px solid #ccc; border-radius: 3px; }"
                "QPushButton:hover { background-color: #e6f0ff; border-color: #0066cc; }"
            )
            btn.setVisible(False)
            btn.clicked.connect(lambda checked, idx=i: self._on_quick_match_clicked(idx))
            quick_match_layout.addWidget(btn)
            self.quick_match_buttons.append(btn)

        self.quick_match_no_results = QLabel("Совпадений не найдено")
        self.quick_match_no_results.setStyleSheet("color: #888; font-style: italic; padding: 4px;")
        self.quick_match_no_results.setVisible(False)
        quick_match_layout.addWidget(self.quick_match_no_results)

        self.quick_match_group.setLayout(quick_match_layout)
        self.quick_match_group.setVisible(False)
        layout.addWidget(self.quick_match_group)

        # Данные подсказок: [{full_name, section_num, group_key, layer_key, sublayer_key}, ...]
        self._quick_match_data: List[Dict[str, Any]] = []

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
        self.section_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
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
        self.group_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
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
        self.layer_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
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
        self.sublayer_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
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
                # Для площадных объектов скрываем группы без доступных слоёв
                if not self._is_group_allowed(group_key):
                    continue
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

        # Группы ЗПР: источники (1_12, 1_13), нарезка (2_1, 2_2),
        # точки (2_5, 2_6), лес (3_2, 3_3)
        is_zpr_group = group_key in (
            '1_12', '1_13', '2_1', '2_2', '2_5', '2_6', '3_2', '3_3'
        )

        # Заполняем слои для выбранной группы
        if group_key in self.layers_by_group:
            self.layer_combo.addItem("-- Выберите слой --", None)
            layers = self.layers_by_group[group_key]
            added_count = 0

            for layer_key, layer_name in sorted(layers.items()):
                # Для групп ЗПР применяем фильтрацию по типу объекта
                if is_zpr_group:
                    # Извлекаем имя слоя из layer_name (например "1_12_1_ЗПР_ОКС" -> "ЗПР_ОКС")
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
    
    def _get_default_dir(self) -> str:
        """Получение начальной директории для диалога выбора файлов"""
        settings = QSettings()
        saved = settings.value("Daman_QGIS/last_import_folder", "")
        if saved and os.path.isdir(saved):
            return saved
        return QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DesktopLocation
        )

    def _save_last_dir(self, file_path: str) -> None:
        """Сохранение директории последнего выбранного файла"""
        folder = os.path.dirname(file_path)
        if folder and os.path.isdir(folder):
            QSettings().setValue("Daman_QGIS/last_import_folder", folder)

    def browse_file(self):
        """Выбор файла для импорта"""
        # Фильтр только для разрешенных форматов
        filter_str = "Поддерживаемые форматы (*.xml *.tab *.dxf *.shp);;XML файлы (*.xml);;TAB файлы (*.tab);;DXF файлы (*.dxf);;Shapefile (*.shp);;Все файлы (*.*)"

        default_dir = self._get_default_dir()

        # Для XML разрешаем множественный выбор, для других - одиночный
        file_paths, selected_filter = QFileDialog.getOpenFileNames(
            self,
            "Выберите файл(ы) для импорта",
            default_dir,
            filter_str
        )

        if not file_paths:
            self.selected_file = None
            self.selected_format = None
            self.file_edit.clear()
            self.format_info_label.setText("")
            self.selection_group.setEnabled(False)
            self.quick_match_group.setVisible(False)
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
        self._save_last_dir(file_paths[0])

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
            self.quick_match_group.setVisible(False)
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

        elif ext == '.shp':
            self.selected_format = 'SHP'
            self.format_info_label.setText("✓ Формат: SHP (Shapefile)\nℹ Выберите целевой слой ниже")
            # РАЗБЛОКИРУЕМ выбор слоя
            self.selection_group.setEnabled(True)
            self.selected_full_name = None

        else:
            self.selected_format = None
            self.format_info_label.setText("Неподдерживаемый формат файла")
            self.selection_group.setEnabled(False)
            self.quick_match_group.setVisible(False)
            self.selected_full_name = None

        # Быстрый выбор для DXF/TAB/SHP
        if self.selected_format in ('DXF', 'TAB', 'SHP'):
            file_stem = os.path.splitext(os.path.basename(first_file))[0]
            self._update_quick_matches(file_stem)

        self.update_import_button_state()
    
    def update_import_button_state(self):
        """Обновление состояния кнопки импорта"""
        # Для XML достаточно выбрать файл (слой определится автоматически)
        if self.selected_format == 'XML':
            enabled = bool(self.selected_file)
        else:
            # Для DXF/TAB требуется выбрать и файл, и слой
            # Если есть подслои — нужно выбрать конкретный подслой
            sublayer_required = self.sublayer_combo.isEnabled() and not self.selected_sublayer
            enabled = bool(
                self.selected_file and
                self.selected_format and
                self.selected_full_name and
                not sublayer_required
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
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )

                if reply == QMessageBox.StandardButton.No:
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
        if self.result() != QDialog.DialogCode.Accepted:
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
