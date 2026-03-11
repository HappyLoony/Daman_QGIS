# -*- coding: utf-8 -*-
"""
Диалог редактирования свойств проекта
"""

import os
from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QLabel,
    QDialogButtonBox, QMessageBox, QGroupBox, QWidget,
    QFileDialog, QFrame
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIntValidator
from qgis.gui import QgsProjectionSelectionWidget
from qgis.core import QgsCoordinateReferenceSystem
from Daman_QGIS.utils import log_info, log_warning
from Daman_QGIS.tools.F_0_project.submodules.base_metadata_dialog import BaseMetadataDialog
from Daman_QGIS.constants import FIXED_ZONE_REGIONS, SPECIAL_REGION_NAMES


class EditProjectDialog(BaseMetadataDialog):
    """Диалог редактирования свойств проекта"""

    def __init__(self, parent=None, current_metadata=None, reference_db=None):
        """
        Инициализация диалога

        Args:
            parent: Родительское окно
            current_metadata: Текущие метаданные проекта
            reference_db: Менеджер справочных БД
        """
        super().__init__(parent, reference_db)
        self.MODULE_ID = "F_0_3"
        self.current_metadata = current_metadata or {}

        self.setup_ui()
        self.load_current_values()
        
    def setup_ui(self):
        """Настройка интерфейса"""
        self.setWindowTitle("Изменение свойств проекта")
        self.setModal(True)

        # Главный layout
        main_layout = QVBoxLayout()

        # Контейнер для скроллируемого содержимого
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # Группа обязательных свойств
        required_group = QGroupBox("Обязательные свойства")
        required_layout = QFormLayout()
        
        # 1_0 Рабочее название (для папок)
        self.working_name_edit = QLineEdit()
        self.working_name_edit.setPlaceholderText("Обязательно")
        required_layout.addRow("Рабочее название (для папок):", self.working_name_edit)
        
        # 1_1 Полное наименование объекта
        self.full_name_edit = QLineEdit()
        self.full_name_edit.setPlaceholderText("Обязательно")
        required_layout.addRow("Полное наименование объекта:", self.full_name_edit)
        
        # 1_2 Тип объекта
        self.object_type_combo = QComboBox()
        self.object_type_combo.addItem("Площадной", "area")
        self.object_type_combo.addItem("Линейный", "linear")
        # Подключаем сигнал для автоматического обновления "Н.Контроль"
        self.object_type_combo.currentTextChanged.connect(self.update_quality_control)
        required_layout.addRow("Тип объекта:", self.object_type_combo)

        # 1_2_1 Значение линейного объекта (условное обязательное поле)
        self.object_type_value_combo = QComboBox()
        self.populate_enum_combo(self.object_type_value_combo, '1_2_1_object_type_value')
        self.object_type_value_combo.setEnabled(False)  # Изначально заблокировано
        required_layout.addRow("Значение линейного объекта:", self.object_type_value_combo)

        # Настройка условной зависимости между типом объекта и его значением
        self.setup_conditional_field(
            self.object_type_combo,
            self.object_type_value_combo,
            "Линейный"
        )

        # 1_5 Тип документации
        self.doc_type_combo = QComboBox()
        self.populate_enum_combo(self.doc_type_combo, '1_5_doc_type')
        required_layout.addRow("Тип документации (разработка):", self.doc_type_combo)

        # 1_6 Этап разработки
        self.stage_combo = QComboBox()
        self.populate_enum_combo(self.stage_combo, '1_6_stage')
        self.stage_combo.setPlaceholderText("Обязательно")
        required_layout.addRow("Этап разработки:", self.stage_combo)

        # 1_3 Папка проекта
        folder_layout = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Обязательно")
        folder_layout.addWidget(self.folder_edit)
        
        self.folder_button = QPushButton("Обзор...")
        self.folder_button.clicked.connect(self.select_folder)
        folder_layout.addWidget(self.folder_button)
        
        required_layout.addRow("Папка проекта:", folder_layout)
        
        required_group.setLayout(required_layout)
        content_layout.addWidget(required_group)
        
        # Группа системы координат
        crs_group = QGroupBox("Система координат")
        crs_layout = QVBoxLayout()
        
        # Текущая СК (только для отображения)
        current_crs_layout = QHBoxLayout()
        current_crs_layout.addWidget(QLabel("Текущая СК:"))
        self.current_crs_label = QLabel()
        self.current_crs_label.setWordWrap(True)
        self.current_crs_label.setStyleSheet("QLabel { color: #0066cc; }")
        current_crs_layout.addWidget(self.current_crs_label, 1)
        crs_layout.addLayout(current_crs_layout)
        
        # Новая СК
        new_crs_layout = QHBoxLayout()
        new_crs_layout.addWidget(QLabel("Новая СК:"))
        self.crs_widget = QgsProjectionSelectionWidget()
        self.crs_widget.setOptionVisible(
            QgsProjectionSelectionWidget.CurrentCrs, False
        )
        self.crs_widget.setOptionVisible(
            QgsProjectionSelectionWidget.DefaultCrs, False
        )
        # Не устанавливаем message чтобы избежать огромной подсказки
        # Отключаем tooltip для виджета
        self.crs_widget.setToolTip("")
        # Пытаемся отключить tooltip для всех дочерних виджетов
        for child in self.crs_widget.findChildren(QWidget):
            child.setToolTip("")
        
        # Подключаем обработчик изменения СК
        self.crs_widget.crsChanged.connect(self.on_crs_changed)
        
        new_crs_layout.addWidget(self.crs_widget, 1)
        crs_layout.addLayout(new_crs_layout)
        
        # Предупреждение о переопределении СК
        warning_label = QLabel(
            "<b style='color: #ff6600;'>⚠ Внимание:</b> Изменение СК выполнит <b>переопределение</b> "
            "системы координат для всех слоев проекта.<br>"
            "Координаты объектов <b>НЕ будут</b> трансформированы.<br>"
            "Используйте только для исправления ошибочно заданной СК!"
        )
        warning_label.setWordWrap(True)
        warning_label.setStyleSheet("QLabel { background-color: #fff3cd; padding: 10px; border: 1px solid #ffc107; border-radius: 3px; }")
        crs_layout.addWidget(warning_label)

        # Форма для кода региона и зоны
        region_form = QFormLayout()

        # 1_4_1 Код региона (ОБЯЗАТЕЛЬНОЕ поле, выбор из списка)
        self.region_code_combo = QComboBox()
        # Заполняем значениями 01-91 (максимальный код региона РФ)
        self.region_code_combo.addItem("")  # Пустой элемент для "не выбрано"
        for i in range(1, 92):
            code = f"{i:02d}"  # Форматируем как 01, 02, ... 91
            self.region_code_combo.addItem(code, code)

        # Ограничиваем высоту выпадающего списка
        self.region_code_combo.setMaxVisibleItems(12)

        self.region_code_combo.currentTextChanged.connect(self.on_region_changed)
        region_form.addRow("Код региона:", self.region_code_combo)

        # 1_4_2 Код зоны (УСЛОВНОЕ поле, ручной ввод)
        self.zone_code_edit = QLineEdit()
        self.zone_code_edit.setPlaceholderText("Например: 1")
        self.zone_code_edit.setMaxLength(1)
        self.zone_code_edit.setValidator(QIntValidator(1, 9, self))
        region_form.addRow("Код зоны:", self.zone_code_edit)

        # Информационная метка о типе региона
        self.region_hint_label = QLabel()
        self.region_hint_label.setStyleSheet("color: gray; font-style: italic;")
        region_form.addRow("", self.region_hint_label)

        crs_layout.addLayout(region_form)

        crs_group.setLayout(crs_layout)
        content_layout.addWidget(crs_group)

        # Разделитель
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        content_layout.addWidget(separator)
        
        # Группа дополнительных свойств
        optional_group = QGroupBox("Дополнительные свойства")
        optional_layout = QFormLayout()
        
        # 2_1 Шифр
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("Дополнительно")
        optional_layout.addRow("Шифр:", self.code_edit)

        # 2_2 Дата выпуска
        self.release_date_edit = QLineEdit()
        self.release_date_edit.setPlaceholderText("Дополнительно (например: 01.2025)")
        optional_layout.addRow("Дата выпуска:", self.release_date_edit)

        # 2_3 Компания
        self.company_combo = QComboBox()
        self.populate_enum_combo(self.company_combo, '2_3_company', editable=True)
        optional_layout.addRow("Компания:", self.company_combo)

        # 2_4 Город
        self.city_combo = QComboBox()
        self.populate_enum_combo(self.city_combo, '2_4_city', editable=True)
        optional_layout.addRow("Город:", self.city_combo)

        # Зависимость: БТИиК -> всегда Санкт-Петербург
        self.setup_company_city_dependency()

        # 2_5 Заказчик
        self.customer_edit = QLineEdit()
        self.customer_edit.setPlaceholderText("Дополнительно")
        optional_layout.addRow("Заказчик:", self.customer_edit)

        # 2_6 Генеральный директор (скрыто)
        self.general_director_combo = QComboBox()
        self.populate_enum_combo(self.general_director_combo, '2_6_general_director', editable=True)
        # Скрываем поле из GUI (редко меняется)
        # optional_layout.addRow("Генеральный директор:", self.general_director_combo)

        # 2_7 Технический директор (скрыто)
        self.technical_director_combo = QComboBox()
        self.populate_enum_combo(self.technical_director_combo, '2_7_technical_director', editable=True)
        # Скрываем поле из GUI (редко меняется)
        # optional_layout.addRow("Технический директор:", self.technical_director_combo)

        # 2_13 Н.Контроль (read-only, динамическая связь с типом объекта)
        self.quality_control_edit = QLineEdit()
        self.quality_control_edit.setReadOnly(True)
        self.quality_control_edit.setStyleSheet("background-color: #f0f0f0;")  # Серый фон для read-only
        optional_layout.addRow("Н.Контроль:", self.quality_control_edit)

        # 2_8 Обложка
        self.cover_combo = QComboBox()
        self.populate_enum_combo(self.cover_combo, '2_8_cover')
        self.cover_combo.currentTextChanged.connect(self.on_cover_changed)
        optional_layout.addRow("Обложка:", self.cover_combo)

        # 2_9 С какого листа начинается наш титул
        self.title_start_edit = QLineEdit()
        self.title_start_edit.setPlaceholderText("Дополнительно (номер листа)")
        optional_layout.addRow("С какого листа начинается наш титул:", self.title_start_edit)

        # 2_10 Основной масштаб
        self.main_scale_combo = QComboBox()
        self.populate_enum_combo(self.main_scale_combo, '2_10_main_scale')
        self.main_scale_combo.currentIndexChanged.connect(self.on_scale_changed)
        optional_layout.addRow("Основной масштаб:", self.main_scale_combo)

        # 2_10_1 Высота текста в DXF (readonly, автоматически по масштабу)
        self.dxf_text_height_edit = QLineEdit()
        self.dxf_text_height_edit.setReadOnly(True)
        self.dxf_text_height_edit.setStyleSheet("background-color: #f0f0f0;")
        self.dxf_text_height_edit.setPlaceholderText("Определяется масштабом")
        optional_layout.addRow("Высота текста DXF:", self.dxf_text_height_edit)

        # 2_11 Разработчик
        self.developer_combo = QComboBox()
        self.developer_combo.setEditable(True)
        self.load_developers()
        optional_layout.addRow("Разработчик:", self.developer_combo)

        # 2_12 Проверяющий
        self.examiner_combo = QComboBox()
        self.examiner_combo.setEditable(True)
        self.load_examiners()
        optional_layout.addRow("Проверяющий:", self.examiner_combo)

        # 2_13 Формат листа
        self.sheet_format_combo = QComboBox()
        self.populate_enum_combo(self.sheet_format_combo, '2_13_sheet_format')
        optional_layout.addRow("Формат листа:", self.sheet_format_combo)

        # 2_14 Ориентация листа
        self.sheet_orientation_combo = QComboBox()
        self.populate_enum_combo(self.sheet_orientation_combo, '2_14_sheet_orientation')
        optional_layout.addRow("Ориентация листа:", self.sheet_orientation_combo)

        optional_group.setLayout(optional_layout)
        content_layout.addWidget(optional_group)

        # Скроллируемая область для содержимого
        scroll = self._create_scroll_wrapper(content_widget)
        main_layout.addWidget(scroll, stretch=1)

        # Кнопки (снаружи скролла, всегда видны)
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.validate_and_accept)
        self.button_box.rejected.connect(self.reject)

        main_layout.addWidget(self.button_box)

        self.setLayout(main_layout)
    
    def select_folder(self):
        """Выбор новой папки для проекта"""
        # Получаем текущую папку для начального пути
        current_folder = self.folder_edit.text()
        if not current_folder:
            current_folder = os.path.expanduser("~")
        
        # Получаем родительскую папку от текущей
        parent_folder = os.path.dirname(current_folder)
        
        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите новое расположение папки проекта",
            parent_folder,
            QFileDialog.Option.ShowDirsOnly
        )
        
        if folder:
            # Добавляем имя папки проекта к выбранному пути
            project_folder_name = os.path.basename(current_folder)
            new_path = os.path.join(folder, project_folder_name)
            self.folder_edit.setText(new_path)
    def load_current_values(self):
        """Загрузка текущих значений из метаданных"""
        # Рабочее название
        if '1_0_working_name' in self.current_metadata:
            self.working_name_edit.setText(
                self.current_metadata['1_0_working_name'].get('value', '')
            )

        # Полное наименование объекта
        if '1_1_full_name' in self.current_metadata:
            self.full_name_edit.setText(
                self.current_metadata['1_1_full_name'].get('value', '')
            )

        # Тип объекта
        if '1_2_object_type' in self.current_metadata:
            object_type = self.current_metadata['1_2_object_type'].get('value', 'area')
            index = self.object_type_combo.findData(object_type)
            if index >= 0:
                self.object_type_combo.setCurrentIndex(index)

        # Значение линейного объекта (1_2_1)
        if '1_2_1_object_type_value' in self.current_metadata:
            object_type_value = self.current_metadata['1_2_1_object_type_value'].get('value', '')
            if object_type_value:
                index = self.object_type_value_combo.findData(object_type_value)
                if index >= 0:
                    self.object_type_value_combo.setCurrentIndex(index)

        # Обновляем состояние условного поля после загрузки значений
        # Вызываем сигнал чтобы обработчик из setup_conditional_field обновил состояние
        current_object_type = self.object_type_combo.currentText()
        if "Линейный" in current_object_type:
            self.object_type_value_combo.setEnabled(True)
        else:
            self.object_type_value_combo.setEnabled(False)

        # Тип документации
        if '1_5_doc_type' in self.current_metadata:
            doc_type = self.current_metadata['1_5_doc_type'].get('value', 'dpt')
            index = self.doc_type_combo.findData(doc_type)
            if index >= 0:
                self.doc_type_combo.setCurrentIndex(index)

        # Этап разработки (1_6)
        if '1_6_stage' in self.current_metadata:
            stage = self.current_metadata['1_6_stage'].get('value', 'initial')
            index = self.stage_combo.findData(stage)
            if index >= 0:
                self.stage_combo.setCurrentIndex(index)

        # Папка проекта
        if '1_3_project_folder' in self.current_metadata:
            self.folder_edit.setText(
                self.current_metadata['1_3_project_folder'].get('value', '')
            )

        # Шифр
        if '2_1_code' in self.current_metadata:
            self.code_edit.setText(
                self.current_metadata['2_1_code'].get('value', '')
            )

        # Дата выпуска
        if '2_2_date' in self.current_metadata:
            self.release_date_edit.setText(
                self.current_metadata['2_2_date'].get('value', '')
            )

        # Текущая система координат
        crs_desc = ""
        if '1_4_crs_description' in self.current_metadata:
            crs_desc = self.current_metadata['1_4_crs_description'].get('value', '')

        self.current_crs_label.setText(crs_desc if crs_desc else "Не задана")

        # Устанавливаем текущую СК в виджет выбора
        if '1_4_crs_wkt' in self.current_metadata:
            crs = QgsCoordinateReferenceSystem()
            crs.createFromWkt(self.current_metadata['1_4_crs_wkt'].get('value', ''))
            if crs.isValid():
                self.crs_widget.setCrs(crs)

        # Короткое название СК (crs_short_name) теперь генерируется динамически
        # в BaseExporter._build_crs_display_name() из code_region и code_zone

        # Отключаем tooltip после установки СК
        self.crs_widget.setToolTip("")
        for child in self.crs_widget.findChildren(QWidget):
            child.setToolTip("")

        # Загрузка кода региона (1_4_1)
        # Блокируем сигналы чтобы on_region_changed не вызывался до загрузки зоны
        self.region_code_combo.blockSignals(True)
        if '1_4_1_code_region' in self.current_metadata:
            region_code = self.current_metadata['1_4_1_code_region'].get('value', '')
            if region_code:
                index = self.region_code_combo.findText(region_code)
                if index >= 0:
                    self.region_code_combo.setCurrentIndex(index)
        self.region_code_combo.blockSignals(False)

        # Загрузка кода зоны (1_4_2)
        if '1_4_2_code_zone' in self.current_metadata:
            zone_code = self.current_metadata['1_4_2_code_zone'].get('value', '')
            if zone_code:
                self.zone_code_edit.setText(zone_code)

        # Вызываем обработчик изменения региона для обновления состояния поля зоны
        self.on_region_changed()

        # Загрузка дополнительных метаданных (2_3 - 2_12)

        # 2_3 Компания
        if '2_3_company' in self.current_metadata:
            company = self.current_metadata['2_3_company'].get('value', '')
            self.company_combo.setCurrentText(company)

        # 2_4 Город
        if '2_4_city' in self.current_metadata:
            city = self.current_metadata['2_4_city'].get('value', '')
            self.city_combo.setCurrentText(city)

        # 2_5 Заказчик
        if '2_5_customer' in self.current_metadata:
            self.customer_edit.setText(
                self.current_metadata['2_5_customer'].get('value', '')
            )

        # 2_6 Генеральный директор
        if '2_6_general_director' in self.current_metadata:
            general_director = self.current_metadata['2_6_general_director'].get('value', '')
            self.general_director_combo.setCurrentText(general_director)

        # 2_7 Технический директор
        if '2_7_technical_director' in self.current_metadata:
            technical_director = self.current_metadata['2_7_technical_director'].get('value', '')
            self.technical_director_combo.setCurrentText(technical_director)

        # 2_8 Обложка
        if '2_8_cover' in self.current_metadata:
            cover = self.current_metadata['2_8_cover'].get('value', '')
            index = self.cover_combo.findText(cover)
            if index >= 0:
                self.cover_combo.setCurrentIndex(index)

        # Применяем логику блокировки поля в зависимости от типа обложки
        # ВАЖНО: вызываем ДО загрузки title_start, чтобы on_cover_changed()
        # не затёр значение из БД (очистка "2" при не-"Наша" обложке)
        self.on_cover_changed()

        # 2_9 С какого листа начинается наш титул
        # Загружается ПОСЛЕ on_cover_changed() чтобы значение из БД
        # всегда имело приоритет над автоматической логикой обложки
        if '2_9_title_start' in self.current_metadata:
            self.title_start_edit.setText(
                self.current_metadata['2_9_title_start'].get('value', '')
            )

        # 2_10 Основной масштаб
        if '2_10_main_scale' in self.current_metadata:
            main_scale = self.current_metadata['2_10_main_scale'].get('value', '')
            index = self.main_scale_combo.findData(main_scale)
            if index >= 0:
                self.main_scale_combo.setCurrentIndex(index)

        # 2_10_1 Высота текста DXF (автоматически по масштабу)
        self.on_scale_changed()

        # 2_11 Разработчик
        if '2_11_developer' in self.current_metadata:
            developer = self.current_metadata['2_11_developer'].get('value', '')
            self.developer_combo.setCurrentText(developer)

        # 2_12 Проверяющий
        if '2_12_examiner' in self.current_metadata:
            examiner = self.current_metadata['2_12_examiner'].get('value', '')
            self.examiner_combo.setCurrentText(examiner)

        # 2_13 Н.Контроль (автоматически устанавливается на основе типа объекта)
        if '2_13_quality_control' in self.current_metadata:
            quality_control = self.current_metadata['2_13_quality_control'].get('value', '')
            self.quality_control_edit.setText(quality_control)
        else:
            # Если нет в метаданных, обновляем на основе типа объекта
            self.update_quality_control()

        # 2_13 Формат листа (sheet_format)
        if '2_13_sheet_format' in self.current_metadata:
            sheet_format = self.current_metadata['2_13_sheet_format'].get('value', '')
            index = self.sheet_format_combo.findText(sheet_format)
            if index >= 0:
                self.sheet_format_combo.setCurrentIndex(index)

        # 2_14 Ориентация листа
        if '2_14_sheet_orientation' in self.current_metadata:
            sheet_orientation = self.current_metadata['2_14_sheet_orientation'].get('value', '')
            index = self.sheet_orientation_combo.findText(sheet_orientation)
            if index >= 0:
                self.sheet_orientation_combo.setCurrentIndex(index)
    def on_crs_changed(self, crs=None):
        """Обработчик изменения системы координат

        Args:
            crs: Система координат (передается автоматически сигналом crsChanged, игнорируется)
        """
        # Короткое название СК (crs_short_name) теперь генерируется динамически
        # в BaseExporter._build_crs_display_name() из code_region и code_zone
        pass

    def on_region_changed(self):
        """
        Обработчик изменения кода региона.

        Логика:
        - Фиксированные регионы (FIXED_ZONE_REGIONS): блокируем поле зоны
        - Особые регионы (77, 78): показываем кастомное название
        - Обычные регионы: разблокируем поле зоны
        """
        region_code = self.region_code_combo.currentText().strip()

        if not region_code:
            # Регион не выбран - сбрасываем состояние
            self.zone_code_edit.setEnabled(True)
            self.zone_code_edit.clear()
            self.zone_code_edit.setPlaceholderText("Например: 1")
            self.region_hint_label.clear()
            return

        if region_code in FIXED_ZONE_REGIONS:
            # Фиксированная зона - блокируем поле
            self.zone_code_edit.setEnabled(False)
            self.zone_code_edit.clear()

            if region_code in SPECIAL_REGION_NAMES:
                # Особый регион с кастомным названием
                special_name = SPECIAL_REGION_NAMES[region_code]
                self.zone_code_edit.setPlaceholderText("Не требуется")
                self.region_hint_label.setText(f"Особый регион: {special_name}")
                self.region_hint_label.setStyleSheet("color: blue; font-style: italic;")
            else:
                # Обычный фиксированный регион
                self.zone_code_edit.setPlaceholderText("Не требуется")
                self.region_hint_label.setText("Единственная зона в регионе")
                self.region_hint_label.setStyleSheet("color: gray; font-style: italic;")

            log_info(f"F_0_3: Регион {region_code} - фиксированная зона")
        else:
            # Обычный регион - разблокируем поле зоны
            self.zone_code_edit.setEnabled(True)
            self.zone_code_edit.setPlaceholderText("Обязательно")

            # Если зона уже заполнена, показываем нейтральную подсказку
            if self.zone_code_edit.text().strip():
                self.region_hint_label.setText(f"Зона: {self.zone_code_edit.text().strip()}")
                self.region_hint_label.setStyleSheet("color: gray; font-style: italic;")
            else:
                self.region_hint_label.setText("Укажите номер зоны (1-9)")
                self.region_hint_label.setStyleSheet("color: orange; font-style: italic;")
                log_info(f"F_0_3: Регион {region_code} - требуется указать зону")
    def validate_and_accept(self):
        """Валидация и принятие диалога"""
        # Получаем обновленные данные для валидации
        updated_data = self.get_updated_data()

        # Используем базовый метод валидации с автоматическим показом ошибок
        if not self.validate_and_show_errors(updated_data):
            return

        # Проверка папки проекта
        if not self.folder_edit.text().strip():
            QMessageBox.warning(
                self,
                "Внимание",
                "Укажите папку проекта"
            )
            return

        # Проверка системы координат
        crs = self.crs_widget.crs()
        if not crs or not crs.isValid():
            QMessageBox.warning(
                self,
                "Внимание",
                "Выберите корректную систему координат"
            )
            return

        # Валидация кода региона (обязательное поле)
        region_code = self.region_code_combo.currentText().strip()
        if not region_code:
            QMessageBox.warning(
                self,
                "Внимание",
                "Выберите код региона"
            )
            self.region_code_combo.setFocus()
            return

        # Валидация кода зоны (обязательно для обычных регионов)
        zone_code = self.zone_code_edit.text().strip()

        if region_code not in FIXED_ZONE_REGIONS:
            # Обычный регион - зона обязательна
            if not zone_code:
                QMessageBox.warning(
                    self,
                    "Внимание",
                    "Укажите код зоны (например: 1)"
                )
                self.zone_code_edit.setFocus()
                return
        
        # Предупреждение о переопределении СК
        current_crs_desc = self.current_crs_label.text()
        new_crs_desc = crs.description()
        
        if current_crs_desc != new_crs_desc and current_crs_desc != "Не задана":
            reply = QMessageBox.warning(
                self,
                "Подтверждение изменения СК",
                f"Вы изменяете систему координат с:\n"
                f"{current_crs_desc}\n\n"
                f"На:\n"
                f"{new_crs_desc}\n\n"
                f"Это выполнит ПЕРЕОПРЕДЕЛЕНИЕ СК для всех слоев.\n"
                f"Координаты НЕ будут трансформированы!\n\n"
                f"Продолжить?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        
        self.accept()
    
    def get_updated_data(self):
        """
        Получение обновленных данных проекта

        Returns:
            Словарь с обновленными данными и флагами изменений
        """
        crs = self.crs_widget.crs()

        # Дескрипторы полей: (field_name, metadata_key, widget, extraction_method)
        # extraction_method: 'text' = QLineEdit.text().strip()
        #                    'combo_data' = QComboBox.currentData()
        #                    'combo_text' = QComboBox.currentText().strip()
        field_descriptors = [
            ('working_name', '1_0_working_name', self.working_name_edit, 'text'),
            ('full_name', '1_1_full_name', self.full_name_edit, 'text'),
            ('object_type', '1_2_object_type', self.object_type_combo, 'combo_data'),
            ('doc_type', '1_5_doc_type', self.doc_type_combo, 'combo_data'),
            ('stage', '1_6_stage', self.stage_combo, 'combo_data'),
            ('project_folder', '1_3_project_folder', self.folder_edit, 'text'),
            ('code', '2_1_code', self.code_edit, 'text'),
            ('release_date', '2_2_date', self.release_date_edit, 'text'),
            ('code_region', '1_4_1_code_region', self.region_code_combo, 'combo_text'),
            ('company', '2_3_company', self.company_combo, 'combo_text'),
            ('city', '2_4_city', self.city_combo, 'combo_text'),
            ('customer', '2_5_customer', self.customer_edit, 'text'),
            ('general_director', '2_6_general_director', self.general_director_combo, 'combo_text'),
            ('technical_director', '2_7_technical_director', self.technical_director_combo, 'combo_text'),
            ('cover', '2_8_cover', self.cover_combo, 'combo_text'),
            ('title_start', '2_9_title_start', self.title_start_edit, 'text'),
            ('main_scale', '2_10_main_scale', self.main_scale_combo, 'combo_data'),
            ('dxf_text_height', '2_10_1_DXF_SCALE_TO_TEXT_HEIGHT', self.dxf_text_height_edit, 'text'),
            ('developer', '2_11_developer', self.developer_combo, 'combo_text'),
            ('examiner', '2_12_examiner', self.examiner_combo, 'combo_text'),
            ('quality_control', '2_13_quality_control', self.quality_control_edit, 'text'),
            ('sheet_format', '2_13_sheet_format', self.sheet_format_combo, 'combo_text'),
            ('sheet_orientation', '2_14_sheet_orientation', self.sheet_orientation_combo, 'combo_text'),
        ]

        # Извлечение значений и детекция изменений
        changed_fields = []
        values = {}

        for field_name, meta_key, widget, method in field_descriptors:
            if method == 'text':
                new_val = widget.text().strip()
            elif method == 'combo_data':
                new_val = widget.currentData()
            elif method == 'combo_text':
                new_val = widget.currentText().strip()
            else:
                new_val = ''

            old_val = self.current_metadata.get(meta_key, {}).get('value', '')
            if old_val != new_val:
                changed_fields.append(field_name)

            values[field_name] = new_val

        # Специальные поля с нестандартной логикой извлечения

        # object_type_value: условное поле, зависит от isEnabled()
        old_type_value = self.current_metadata.get('1_2_1_object_type_value', {}).get('value', '')
        new_type_value = self.object_type_value_combo.currentData() if self.object_type_value_combo.isEnabled() else ''
        if old_type_value != new_type_value:
            changed_fields.append('object_type_value')

        # CRS: сравнение по описанию
        old_crs_desc = self.current_metadata.get('1_4_crs_description', {}).get('value', '')
        new_crs_desc = crs.description() if crs else ""
        if old_crs_desc != new_crs_desc:
            changed_fields.append('crs')

        # code_zone: условное поле, зависит от isEnabled()
        old_code_zone = self.current_metadata.get('1_4_2_code_zone', {}).get('value', '')
        new_code_zone = self.zone_code_edit.text().strip() if self.zone_code_edit.isEnabled() else ""
        if old_code_zone != new_code_zone:
            changed_fields.append('code_zone')

        # Значение линейного объекта (только если активно)
        object_type_value = None
        object_type_value_name = None
        if self.object_type_value_combo.isEnabled():
            object_type_value = self.object_type_value_combo.currentData()
            object_type_value_name = self.object_type_value_combo.currentText()

        # Сборка результата
        result = dict(values)
        result.update({
            'object_type_name': self.object_type_combo.currentText(),
            'object_type_value': object_type_value,
            'object_type_value_name': object_type_value_name,
            'doc_type_name': self.doc_type_combo.currentText(),
            'stage_name': self.stage_combo.currentText(),
            'crs': crs,
            'crs_epsg': crs.postgisSrid() if crs else 0,
            'crs_description': new_crs_desc,
            'crs_wkt': crs.toWkt() if crs else "",
            'code_zone': new_code_zone,
            'changed_fields': changed_fields,
        })

        return result
