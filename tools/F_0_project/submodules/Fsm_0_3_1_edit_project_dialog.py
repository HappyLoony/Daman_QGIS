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
from qgis.gui import QgsProjectionSelectionWidget
from qgis.core import QgsCoordinateReferenceSystem
from Daman_QGIS.core.crs_utils import extract_crs_short_name
from Daman_QGIS.utils import log_info, log_warning
from Daman_QGIS.tools.F_0_project.submodules.base_metadata_dialog import BaseMetadataDialog


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
        self.current_metadata = current_metadata or {}
        self.crs_short_name = ""  # Для хранения короткого названия СК

        self.setup_ui()
        self.load_current_values()
        
    def setup_ui(self):
        """Настройка интерфейса"""
        self.setWindowTitle("Изменение свойств проекта")
        self.setModal(True)
        self.setMinimumWidth(550)
        
        # Главный layout
        main_layout = QVBoxLayout()
        
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
        main_layout.addWidget(required_group)
        
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
        
        crs_group.setLayout(crs_layout)
        main_layout.addWidget(crs_group)
        
        # Разделитель
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(separator)
        
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
        optional_layout.addRow("Основной масштаб:", self.main_scale_combo)

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
        main_layout.addWidget(optional_group)
        
        # Кнопки
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
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
            QFileDialog.ShowDirsOnly
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

        # Короткое название СК (загружаем в переменную)
        if '1_4_crs_short_name' in self.current_metadata:
            self.crs_short_name = self.current_metadata['1_4_crs_short_name'].get('value', '')
        else:
            # Если короткого названия нет, пытаемся извлечь автоматически
            if crs_desc:
                short_name = extract_crs_short_name(crs_desc)
                if short_name:
                    self.crs_short_name = short_name
                else:
                    self.crs_short_name = ""

        # Отключаем tooltip после установки СК
        self.crs_widget.setToolTip("")
        for child in self.crs_widget.findChildren(QWidget):
            child.setToolTip("")

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

        # 2_9 С какого листа начинается наш титул
        if '2_9_title_start' in self.current_metadata:
            self.title_start_edit.setText(
                self.current_metadata['2_9_title_start'].get('value', '')
            )

        # Применяем логику блокировки поля в зависимости от типа обложки
        self.on_cover_changed()

        # 2_10 Основной масштаб
        if '2_10_main_scale' in self.current_metadata:
            main_scale = self.current_metadata['2_10_main_scale'].get('value', '')
            index = self.main_scale_combo.findData(main_scale)
            if index >= 0:
                self.main_scale_combo.setCurrentIndex(index)

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
        crs = self.crs_widget.crs()
        if crs and crs.isValid():
            crs_desc = crs.description()
            # Извлекаем короткое название из описания СК и сохраняем в переменной
            short_name = extract_crs_short_name(crs_desc)
            if short_name:
                self.crs_short_name = short_name
            else:
                # Если не удалось извлечь, используем пустую строку
                self.crs_short_name = ""
                log_warning(f"Fsm_0_3_1: Не удалось автоматически определить короткое название СК из '{crs_desc}'")
        else:
            self.crs_short_name = ""
    def load_developers(self):
        """Загрузка разработчиков из справочной БД"""
        # Добавляем пустой элемент по умолчанию
        self.developer_combo.addItem("")

        if self.reference_db:
            try:
                developers = self.reference_db.employee.get_employees_by_role('developed')

                # Извлекаем только фамилии и сортируем по алфавиту
                last_names = sorted([emp.get('last_name', '') for emp in developers if emp.get('last_name')])

                # Добавляем каждую фамилию
                for last_name in last_names:
                    self.developer_combo.addItem(last_name)
            except Exception as e:
                log_warning(f"F_0_3: Не удалось загрузить разработчиков: {e}")
        else:
            log_warning("F_0_3: Справочная БД недоступна для загрузки разработчиков")
    def load_examiners(self):
        """Загрузка проверяющих из справочной БД"""
        # Добавляем пустой элемент по умолчанию
        self.examiner_combo.addItem("")

        if self.reference_db:
            try:
                examiners = self.reference_db.employee.get_employees_by_role('verified')

                # Извлекаем только фамилии и сортируем по алфавиту
                last_names = sorted([emp.get('last_name', '') for emp in examiners if emp.get('last_name')])

                # Добавляем каждую фамилию
                for last_name in last_names:
                    self.examiner_combo.addItem(last_name)
            except Exception as e:
                log_warning(f"F_0_3: Не удалось загрузить проверяющих: {e}")
        else:
            log_warning("F_0_3: Справочная БД недоступна для загрузки проверяющих")

    def update_quality_control(self):
        """
        Автоматическое обновление поля "Н.Контроль" на основе типа объекта

        Логика:
        - "Площадной" → Евдокимова
        - "Линейный" → Косынкина
        """
        object_type = self.object_type_combo.currentText()

        if "Площадной" in object_type:
            self.quality_control_edit.setText("Евдокимова")
        elif "Линейный" in object_type:
            self.quality_control_edit.setText("Косынкина")
        else:
            # Если тип объекта неизвестен, оставляем пустым
            self.quality_control_edit.clear()

    def on_cover_changed(self):
        """Обработчик изменения типа обложки"""
        cover_type = self.cover_combo.currentText()

        if cover_type == "Наша":
            # Если обложка наша, титул начинается со 2 страницы
            self.title_start_edit.setText("2")
            self.title_start_edit.setReadOnly(True)
            self.title_start_edit.setStyleSheet("background-color: #f0f0f0;")  # Серый фон для визуальной индикации
        else:
            # Если обложка заказчика, разблокируем поле
            self.title_start_edit.setReadOnly(False)
            self.title_start_edit.setStyleSheet("")  # Сбрасываем стиль
            # Очищаем поле, если там было автоматическое значение "2"
            if self.title_start_edit.text() == "2":
                self.title_start_edit.clear()

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
        
        # Автоматическое извлечение короткого названия СК (если еще не извлечено)
        if not self.crs_short_name:
            crs = self.crs_widget.crs()
            if crs and crs.isValid():
                short_name = extract_crs_short_name(crs.description())
                if short_name:
                    self.crs_short_name = short_name
                else:
                    # Если не удалось извлечь, используем пустое значение
                    self.crs_short_name = ""
                    log_warning("Fsm_0_3_1: Короткое название СК не определено, будет использовано пустое значение")
        
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
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        
        self.accept()
    
    def get_updated_data(self):
        """
        Получение обновленных данных проекта
        
        Returns:
            Словарь с обновленными данными и флагами изменений
        """
        crs = self.crs_widget.crs()
        
        # Определяем что изменилось
        changed_fields = []
        
        # Проверка изменения рабочего названия
        old_working_name = self.current_metadata.get('1_0_working_name', {}).get('value', '')
        new_working_name = self.working_name_edit.text().strip()
        if old_working_name != new_working_name:
            changed_fields.append('working_name')
        
        # Проверка изменения полного наименования
        old_full_name = self.current_metadata.get('1_1_full_name', {}).get('value', '')
        new_full_name = self.full_name_edit.text().strip()
        if old_full_name != new_full_name:
            changed_fields.append('full_name')
        
        # Проверка изменения типа
        old_type = self.current_metadata.get('1_2_object_type', {}).get('value', '')
        new_type = self.object_type_combo.currentData()
        if old_type != new_type:
            changed_fields.append('object_type')

        # Проверка изменения значения линейного объекта
        old_type_value = self.current_metadata.get('1_2_1_object_type_value', {}).get('value', '')
        new_type_value = self.object_type_value_combo.currentData() if self.object_type_value_combo.isEnabled() else None
        if old_type_value != new_type_value:
            changed_fields.append('object_type_value')

        # Проверка изменения типа документации
        old_doc_type = self.current_metadata.get('1_5_doc_type', {}).get('value', '')
        new_doc_type = self.doc_type_combo.currentData()
        if old_doc_type != new_doc_type:
            changed_fields.append('doc_type')

        # Проверка изменения этапа разработки
        old_stage = self.current_metadata.get('1_6_stage', {}).get('value', '')
        new_stage = self.stage_combo.currentData()
        if old_stage != new_stage:
            changed_fields.append('stage')

        # Проверка изменения папки проекта
        old_folder = self.current_metadata.get('1_3_project_folder', {}).get('value', '')
        new_folder = self.folder_edit.text().strip()
        if old_folder != new_folder:
            changed_fields.append('project_folder')
        
        # Проверка изменения шифра
        old_code = self.current_metadata.get('2_1_code', {}).get('value', '')
        new_code = self.code_edit.text().strip()
        if old_code != new_code:
            changed_fields.append('code')
        
        # Проверка изменения даты выпуска
        old_release_date = self.current_metadata.get('2_2_date', {}).get('value', '')
        new_release_date = self.release_date_edit.text().strip()
        if old_release_date != new_release_date:
            changed_fields.append('release_date')
        
        # Проверка изменения СК
        old_crs_desc = self.current_metadata.get('1_4_crs_description', {}).get('value', '')
        new_crs_desc = crs.description() if crs else ""
        if old_crs_desc != new_crs_desc:
            changed_fields.append('crs')
        
        # Проверка изменения короткого названия СК
        old_crs_short_name = self.current_metadata.get('1_4_crs_short_name', {}).get('value', '')
        new_crs_short_name = self.crs_short_name
        if old_crs_short_name != new_crs_short_name:
            changed_fields.append('crs_short_name')

        # Проверка изменения дополнительных метаданных (2_3 - 2_12)

        # 2_3 Компания
        old_company = self.current_metadata.get('2_3_company', {}).get('value', '')
        new_company = self.company_combo.currentText().strip()
        if old_company != new_company:
            changed_fields.append('company')

        # 2_4 Город
        old_city = self.current_metadata.get('2_4_city', {}).get('value', '')
        new_city = self.city_combo.currentText().strip()
        if old_city != new_city:
            changed_fields.append('city')

        # 2_5 Заказчик
        old_customer = self.current_metadata.get('2_5_customer', {}).get('value', '')
        new_customer = self.customer_edit.text().strip()
        if old_customer != new_customer:
            changed_fields.append('customer')

        # 2_6 Генеральный директор
        old_general_director = self.current_metadata.get('2_6_general_director', {}).get('value', '')
        new_general_director = self.general_director_combo.currentText().strip()
        if old_general_director != new_general_director:
            changed_fields.append('general_director')

        # 2_7 Технический директор
        old_technical_director = self.current_metadata.get('2_7_technical_director', {}).get('value', '')
        new_technical_director = self.technical_director_combo.currentText().strip()
        if old_technical_director != new_technical_director:
            changed_fields.append('technical_director')

        # 2_8 Обложка
        old_cover = self.current_metadata.get('2_8_cover', {}).get('value', '')
        new_cover = self.cover_combo.currentText().strip()
        if old_cover != new_cover:
            changed_fields.append('cover')

        # 2_9 С какого листа начинается наш титул
        old_title_start = self.current_metadata.get('2_9_title_start', {}).get('value', '')
        new_title_start = self.title_start_edit.text().strip()
        if old_title_start != new_title_start:
            changed_fields.append('title_start')

        # 2_10 Основной масштаб
        old_main_scale = self.current_metadata.get('2_10_main_scale', {}).get('value', '')
        new_main_scale = self.main_scale_combo.currentData()
        if old_main_scale != new_main_scale:
            changed_fields.append('main_scale')

        # 2_11 Разработчик
        old_developer = self.current_metadata.get('2_11_developer', {}).get('value', '')
        new_developer = self.developer_combo.currentText().strip()
        if old_developer != new_developer:
            changed_fields.append('developer')

        # 2_12 Проверяющий
        old_examiner = self.current_metadata.get('2_12_examiner', {}).get('value', '')
        new_examiner = self.examiner_combo.currentText().strip()
        if old_examiner != new_examiner:
            changed_fields.append('examiner')

        # 2_13 Н.Контроль
        old_quality_control = self.current_metadata.get('2_13_quality_control', {}).get('value', '')
        new_quality_control = self.quality_control_edit.text().strip()
        if old_quality_control != new_quality_control:
            changed_fields.append('quality_control')

        # 2_13 Формат листа (sheet_format)
        old_sheet_format = self.current_metadata.get('2_13_sheet_format', {}).get('value', '')
        new_sheet_format = self.sheet_format_combo.currentText().strip()
        if old_sheet_format != new_sheet_format:
            changed_fields.append('sheet_format')

        # 2_14 Ориентация листа
        old_sheet_orientation = self.current_metadata.get('2_14_sheet_orientation', {}).get('value', '')
        new_sheet_orientation = self.sheet_orientation_combo.currentText().strip()
        if old_sheet_orientation != new_sheet_orientation:
            changed_fields.append('sheet_orientation')

        # Получаем значение линейного объекта только если оно активно
        object_type_value = None
        object_type_value_name = None
        if self.object_type_value_combo.isEnabled():
            object_type_value = self.object_type_value_combo.currentData()
            object_type_value_name = self.object_type_value_combo.currentText()

        return {
            'working_name': new_working_name,
            'full_name': new_full_name,
            'object_type': new_type,
            'object_type_name': self.object_type_combo.currentText(),
            'object_type_value': object_type_value,
            'object_type_value_name': object_type_value_name,
            'doc_type': new_doc_type,
            'doc_type_name': self.doc_type_combo.currentText(),
            'stage': new_stage,
            'stage_name': self.stage_combo.currentText(),
            'project_folder': new_folder,
            'code': new_code,
            'release_date': new_release_date,
            'company': new_company,
            'city': new_city,
            'customer': new_customer,
            'general_director': new_general_director,
            'technical_director': new_technical_director,
            'cover': new_cover,
            'title_start': new_title_start,
            'main_scale': new_main_scale,
            'developer': new_developer,
            'examiner': new_examiner,
            'quality_control': new_quality_control,
            'sheet_format': new_sheet_format,
            'sheet_orientation': new_sheet_orientation,
            'crs': crs,
            'crs_epsg': crs.postgisSrid() if crs else 0,
            'crs_description': new_crs_desc,
            'crs_wkt': crs.toWkt() if crs else "",
            'crs_short_name': self.crs_short_name,
            'changed_fields': changed_fields
        }
