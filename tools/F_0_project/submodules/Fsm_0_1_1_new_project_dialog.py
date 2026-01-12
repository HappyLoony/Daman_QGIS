# -*- coding: utf-8 -*-
"""
Диалог создания нового проекта
"""

import os
from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QLabel,
    QDialogButtonBox, QFileDialog, QMessageBox
)
from qgis.PyQt.QtCore import Qt
from qgis.gui import QgsProjectionSelectionDialog
from qgis.core import QgsCoordinateReferenceSystem
from Daman_QGIS.core.crs_utils import extract_crs_short_name
from Daman_QGIS.utils import log_info, log_warning
from Daman_QGIS.managers import DataCleanupManager
from Daman_QGIS.tools.F_0_project.submodules.base_metadata_dialog import BaseMetadataDialog


class NewProjectDialog(BaseMetadataDialog):
    """Диалог создания нового проекта"""

    def __init__(self, parent=None, reference_db=None):
        """
        Инициализация диалога

        Args:
            parent: Родительское окно
            reference_db: Справочная БД для получения типов объектов
        """
        super().__init__(parent, reference_db)  # BaseMetadataDialog инициализирует validator
        self.project_path = ""
        self.crs_short_name = ""  # Для хранения короткого названия СК
        self.crs_from_database = False  # Флаг: CRS выбрана из базы данных (True) или нативно (False)

        self.setup_ui()
        
    def setup_ui(self):
        """Настройка интерфейса"""
        self.setWindowTitle("Создание нового проекта")
        self.setModal(True)
        self.setMinimumWidth(500)
        
        # Главный layout
        main_layout = QVBoxLayout()
        
        # Форма с полями
        form_layout = QFormLayout()
        
        # Обязательные поля (префикс 1_)
        
        # 1_0 Рабочее название (для папок)
        self.working_name_edit = QLineEdit()
        self.working_name_edit.setPlaceholderText("Обязательно")
        form_layout.addRow("Рабочее название (для папок):", self.working_name_edit)
        
        # 1_1 Полное наименование объекта
        self.full_name_edit = QLineEdit()
        self.full_name_edit.setPlaceholderText("Обязательно")
        form_layout.addRow("Полное наименование объекта:", self.full_name_edit)
        
        # 1_2 Тип объекта
        self.object_type_combo = QComboBox()
        # Загружаем типы из справочной БД
        self.load_object_types()
        # Подключаем сигнал для автоматического обновления "Н.Контроль"
        self.object_type_combo.currentTextChanged.connect(self.update_quality_control)
        form_layout.addRow("Тип объекта:", self.object_type_combo)

        # 1_2_1 Значение линейного объекта (условное обязательное поле)
        self.object_type_value_combo = QComboBox()
        self.populate_enum_combo(self.object_type_value_combo, '1_2_1_object_type_value')
        self.object_type_value_combo.setEnabled(False)  # Изначально заблокировано
        form_layout.addRow("Значение линейного объекта:", self.object_type_value_combo)

        # Настраиваем условную зависимость (автоматически!)
        self.setup_conditional_field(
            self.object_type_combo,
            self.object_type_value_combo,
            "Линейный"
        )

        # 1_5 Тип документации
        self.doc_type_combo = QComboBox()
        self.populate_enum_combo(self.doc_type_combo, '1_5_doc_type')
        form_layout.addRow("Тип документации (разработка):", self.doc_type_combo)

        # 1_6 Этап разработки
        self.stage_combo = QComboBox()
        self.populate_enum_combo(self.stage_combo, '1_6_stage')
        self.stage_combo.setPlaceholderText("Обязательно")
        form_layout.addRow("Этап разработки:", self.stage_combo)

        # 1_3 Папка проекта
        folder_layout = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText("Обязательно")
        folder_layout.addWidget(self.folder_edit)
        
        self.folder_button = QPushButton("Обзор...")
        self.folder_button.clicked.connect(self.select_folder)
        folder_layout.addWidget(self.folder_button)
        
        form_layout.addRow("Папка проекта:", folder_layout)
        
        # 1_4 Система координат (кастомный виджет с кнопкой)
        self.selected_crs = QgsCoordinateReferenceSystem()  # Хранение выбранной СК

        crs_layout = QHBoxLayout()
        self.crs_label = QLineEdit()
        self.crs_label.setReadOnly(True)
        self.crs_label.setPlaceholderText("Не выбрана")
        crs_layout.addWidget(self.crs_label)

        self.crs_button = QPushButton("Выбрать...")
        self.crs_button.clicked.connect(self.select_crs)
        crs_layout.addWidget(self.crs_button)

        form_layout.addRow("Система координат:", crs_layout)

        # 1_4_1 Код региона (ОБЯЗАТЕЛЬНОЕ поле)
        self.region_code_combo = QComboBox()
        self.region_code_combo.setEditable(True)
        self.region_code_combo.setPlaceholderText("Например: 05")
        self.region_code_combo.currentTextChanged.connect(self.on_region_changed)
        self.load_region_codes()
        form_layout.addRow("Код региона:", self.region_code_combo)

        # 1_4_2 Код района (УСЛОВНОЕ поле - активируется если у региона есть районы)
        self.district_code_combo = QComboBox()
        self.district_code_combo.setEnabled(False)
        self.district_code_combo.setPlaceholderText("Не требуется")
        self.district_code_combo.currentTextChanged.connect(self.on_district_changed)
        form_layout.addRow("Код района:", self.district_code_combo)

        # Информационная метка о найденной CRS
        self.crs_match_label = QLabel()
        self.crs_match_label.setStyleSheet("color: gray; font-style: italic;")
        form_layout.addRow("", self.crs_match_label)

        # Разделитель для дополнительных полей
        separator_label = QLabel("<b>Дополнительные метаданные:</b>")
        form_layout.addRow("", separator_label)

        # 2_1 Шифр (дополнительно)
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("Дополнительно")
        form_layout.addRow("Шифр:", self.code_edit)

        # 2_2 Дата выпуска (дополнительно)
        self.release_date_edit = QLineEdit()
        self.release_date_edit.setPlaceholderText("Дополнительно (например: 01.2025)")
        form_layout.addRow("Дата выпуска:", self.release_date_edit)

        # 2_3 Компания (дополнительно)
        self.company_combo = QComboBox()
        self.populate_enum_combo(self.company_combo, '2_3_company', editable=True)
        form_layout.addRow("Компания:", self.company_combo)

        # 2_4 Город (дополнительно)
        self.city_combo = QComboBox()
        self.populate_enum_combo(self.city_combo, '2_4_city', editable=True)
        form_layout.addRow("Город:", self.city_combo)

        # 2_5 Заказчик (дополнительно)
        self.customer_edit = QLineEdit()
        self.customer_edit.setPlaceholderText("Дополнительно")
        form_layout.addRow("Заказчик:", self.customer_edit)

        # 2_6 Генеральный директор (дополнительно, скрыто)
        self.general_director_combo = QComboBox()
        self.populate_enum_combo(self.general_director_combo, '2_6_general_director', editable=True)
        # Скрываем поле из GUI (редко меняется)
        # form_layout.addRow("Генеральный директор:", self.general_director_combo)

        # 2_7 Технический директор (дополнительно, скрыто)
        self.technical_director_combo = QComboBox()
        self.populate_enum_combo(self.technical_director_combo, '2_7_technical_director', editable=True)
        # Скрываем поле из GUI (редко меняется)
        # form_layout.addRow("Технический директор:", self.technical_director_combo)

        # 2_13 Н.Контроль (read-only, динамическая связь с типом объекта)
        self.quality_control_edit = QLineEdit()
        self.quality_control_edit.setReadOnly(True)
        self.quality_control_edit.setStyleSheet("background-color: #f0f0f0;")  # Серый фон для read-only
        form_layout.addRow("Н.Контроль:", self.quality_control_edit)

        # 2_8 Обложка (дополнительно)
        self.cover_combo = QComboBox()
        self.populate_enum_combo(self.cover_combo, '2_8_cover')
        self.cover_combo.currentTextChanged.connect(self.on_cover_changed)
        form_layout.addRow("Обложка:", self.cover_combo)

        # 2_9 С какого листа начинается наш титул (дополнительно)
        self.title_start_edit = QLineEdit()
        self.title_start_edit.setPlaceholderText("Дополнительно (номер листа)")
        form_layout.addRow("С какого листа начинается наш титул:", self.title_start_edit)

        # 2_10 Основной масштаб (дополнительно)
        self.main_scale_combo = QComboBox()
        self.populate_enum_combo(self.main_scale_combo, '2_10_main_scale')
        # Устанавливаем 1:1000 по умолчанию (если есть в списке)
        index = self.main_scale_combo.findData("1000")
        if index >= 0:
            self.main_scale_combo.setCurrentIndex(index)
        form_layout.addRow("Основной масштаб:", self.main_scale_combo)

        # 2_11 Разработчик (дополнительно)
        self.developer_combo = QComboBox()
        self.developer_combo.setEditable(True)
        self.load_developers()
        form_layout.addRow("Разработчик:", self.developer_combo)

        # 2_12 Проверяющий (дополнительно)
        self.examiner_combo = QComboBox()
        self.examiner_combo.setEditable(True)
        self.load_examiners()
        form_layout.addRow("Проверяющий:", self.examiner_combo)

        # 2_13 Формат листа (дополнительно)
        self.sheet_format_combo = QComboBox()
        self.populate_enum_combo(self.sheet_format_combo, '2_13_sheet_format')
        form_layout.addRow("Формат листа:", self.sheet_format_combo)

        # 2_14 Ориентация листа (дополнительно)
        self.sheet_orientation_combo = QComboBox()
        self.populate_enum_combo(self.sheet_orientation_combo, '2_14_sheet_orientation')
        form_layout.addRow("Ориентация листа:", self.sheet_orientation_combo)

        main_layout.addLayout(form_layout)
        
        # Кнопки
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.validate_and_accept)
        self.button_box.rejected.connect(self.reject)
        
        main_layout.addWidget(self.button_box)

        self.setLayout(main_layout)

        # Инициализируем значение "Н.Контроль" для типа объекта по умолчанию
        self.update_quality_control()
    def load_object_types(self):
        """Загрузка типов объектов из справочной БД"""
        if self.reference_db:
            # Получаем типы объектов из Project_Metadata.json
            object_types = self.reference_db.project_metadata.get_object_types()
            for obj_type in object_types:
                # Определяем код на основе названия
                code = "area" if "Площад" in obj_type else "linear"
                self.object_type_combo.addItem(obj_type, code)
        else:
            # Fallback если ReferenceManager не инициализирован
            self.object_type_combo.addItem("Площадной", "area")
            self.object_type_combo.addItem("Линейный", "linear")
    def load_developers(self):
        """Загрузка разработчиков из справочной БД"""
        # Добавляем пустой элемент по умолчанию
        self.developer_combo.addItem("")

        if self.reference_db:
            try:
                # Получаем сотрудников с ролью 'developed'
                developers = self.reference_db.employee.get_employees_by_role('developed')

                # Извлекаем только фамилии и сортируем по алфавиту
                last_names = sorted([emp.get('last_name', '') for emp in developers if emp.get('last_name')])

                # Добавляем каждую фамилию
                for last_name in last_names:
                    self.developer_combo.addItem(last_name)
            except Exception as e:
                log_warning(f"Fsm_0_1_1: Не удалось загрузить разработчиков: {e}")
        else:
            log_warning("Fsm_0_1_1: Справочная БД недоступна для загрузки разработчиков")
    def load_examiners(self):
        """Загрузка проверяющих из справочной БД"""
        # Добавляем пустой элемент по умолчанию
        self.examiner_combo.addItem("")

        if self.reference_db:
            try:
                # Получаем сотрудников с ролью 'verified'
                examiners = self.reference_db.employee.get_employees_by_role('verified')

                # Извлекаем только фамилии и сортируем по алфавиту
                last_names = sorted([emp.get('last_name', '') for emp in examiners if emp.get('last_name')])

                # Добавляем каждую фамилию
                for last_name in last_names:
                    self.examiner_combo.addItem(last_name)
            except Exception as e:
                log_warning(f"Fsm_0_1_1: Не удалось загрузить проверяющих: {e}")
        else:
            log_warning("Fsm_0_1_1: Справочная БД недоступна для загрузки проверяющих")

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

    def load_region_codes(self):
        """Загрузка списка кодов регионов из Base_CRS.json"""
        if self.reference_db and hasattr(self.reference_db, 'crs'):
            try:
                regions = self.reference_db.crs.get_regions_list()
                self.region_code_combo.addItem("")  # Пустой элемент
                for region in regions:
                    self.region_code_combo.addItem(region)
            except Exception as e:
                log_warning(f"Fsm_0_1_1: Не удалось загрузить коды регионов: {e}")

    def on_region_changed(self):
        """Обработчик изменения кода региона"""
        region_code = self.region_code_combo.currentText().strip()

        if not region_code:
            self.district_code_combo.setEnabled(False)
            self.district_code_combo.clear()
            self.crs_match_label.clear()
            return

        if not self.reference_db or not hasattr(self.reference_db, 'crs'):
            return

        # Проверяем есть ли у региона районы
        if self.reference_db.crs.has_districts(region_code):
            # Активируем выбор района
            self.district_code_combo.setEnabled(True)
            districts = self.reference_db.crs.get_districts_for_region(region_code)
            self.district_code_combo.clear()
            self.district_code_combo.addItem("")  # Пустой элемент
            for district in districts:
                self.district_code_combo.addItem(district)
            self.crs_match_label.setText("Выберите код района")
            self.crs_match_label.setStyleSheet("color: orange; font-style: italic;")
        else:
            # Район не нужен - ищем CRS по региону
            self.district_code_combo.setEnabled(False)
            self.district_code_combo.clear()
            self.district_code_combo.setPlaceholderText("Не требуется")
            self._try_load_crs(region_code)

    def on_district_changed(self):
        """Обработчик изменения кода района"""
        region_code = self.region_code_combo.currentText().strip()
        district_code = self.district_code_combo.currentText().strip()

        if district_code:
            full_code = f"{region_code}:{district_code}"
            self._try_load_crs(full_code)
        else:
            self.crs_match_label.setText("Выберите код района")
            self.crs_match_label.setStyleSheet("color: orange; font-style: italic;")

    def _try_load_crs(self, code: str):
        """Попытка загрузить CRS по коду"""
        if not self.reference_db or not hasattr(self.reference_db, 'crs'):
            return

        crs_data = self.reference_db.crs.get_crs_by_code(code)

        if crs_data:
            # CRS найдена в базе
            short_name = crs_data.get('full_name', '')
            self.crs_match_label.setText(f"Найдено: {short_name}")
            self.crs_match_label.setStyleSheet("color: green; font-style: italic;")

            # Предлагаем автоматически установить CRS
            self._suggest_crs(crs_data)
        else:
            # CRS не найдена
            self.crs_match_label.setText("CRS не найдена в базе")
            self.crs_match_label.setStyleSheet("color: orange; font-style: italic;")

    def _suggest_crs(self, crs_data: dict):
        """Предложить установить найденную CRS из базы данных"""
        if not self.reference_db or not hasattr(self.reference_db, 'crs'):
            return

        # Получаем или создаем CRS
        crs = self.reference_db.crs.get_or_create_crs(crs_data)

        if crs and crs.isValid():
            self.selected_crs = crs
            self.crs_label.setText(crs.description())
            self.crs_from_database = True  # CRS из базы данных
            self.on_crs_changed()
            log_info(f"Fsm_0_1_1: CRS автоматически установлена из базы: {crs.authid()}")

    def _get_full_region_district_code(self):
        """
        Получить полный код региона:района

        Returns:
            "РР:РР" если район указан, None если только регион
        """
        region_code = self.region_code_combo.currentText().strip()
        district_code = self.district_code_combo.currentText().strip()

        if district_code:
            return f"{region_code}:{district_code}"

        return None

    def select_crs(self):
        """Открыть диалог выбора системы координат (упрощённый)"""
        dialog = QgsProjectionSelectionDialog(self)
        dialog.setWindowTitle("Выбор системы координат")

        # Скрываем лишние элементы через поиск дочерних виджетов
        # Скрываем: недавние СК, информацию о СК
        from qgis.PyQt.QtWidgets import QTextEdit, QListWidget
        for widget in dialog.findChildren(QTextEdit):
            widget.hide()
        # Скрываем список недавних (первый QListWidget обычно это недавние)
        list_widgets = dialog.findChildren(QListWidget)
        if list_widgets:
            # Первый список - недавние СК, скрываем его
            list_widgets[0].hide()

        # Устанавливаем текущую СК если есть
        if self.selected_crs.isValid():
            dialog.setCrs(self.selected_crs)

        if dialog.exec_():
            crs = dialog.crs()
            if crs and crs.isValid():
                self.selected_crs = crs
                self.crs_label.setText(crs.description())
                self.crs_from_database = False  # CRS выбрана нативно (не из базы)
                self.on_crs_changed()
                log_info(f"Fsm_0_1_1: CRS выбрана нативно: {crs.authid()}")

    def on_crs_changed(self):
        """Обработчик изменения системы координат"""
        if self.selected_crs and self.selected_crs.isValid():
            crs_desc = self.selected_crs.description()
            log_info(f"Fsm_0_1_1: Описание СК для извлечения: '{crs_desc}'")
            # Извлекаем короткое название из описания СК и сохраняем в переменной
            short_name = extract_crs_short_name(crs_desc)
            if short_name:
                self.crs_short_name = short_name
                log_info(f"Fsm_0_1_1: Короткое название СК определено автоматически: {short_name}")
            else:
                # Если не удалось извлечь, используем пустую строку
                self.crs_short_name = ""
                log_warning(f"Fsm_0_1_1: Не удалось автоматически определить короткое название СК из '{crs_desc}'")
        else:
            self.crs_short_name = ""
    
    def select_folder(self):
        """Выбор папки для проекта"""
        # По умолчанию открываем рабочий стол
        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.exists(desktop_path):
            # Fallback на домашнюю директорию если рабочий стол не найден
            desktop_path = os.path.expanduser("~")

        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку для проекта",
            desktop_path,
            QFileDialog.ShowDirsOnly
        )
        
        if folder:
            self.folder_edit.setText(folder)
            self.project_path = folder
    
    def validate_and_accept(self):
        """Валидация и принятие диалога"""
        # Получаем данные проекта для валидации
        project_data = self.get_project_data()

        # Используем базовый метод валидации с автоматическим показом ошибок
        if not self.validate_and_show_errors(project_data):
            return

        # Проверка выбора папки
        if not self.project_path:
            QMessageBox.warning(
                self,
                "Внимание",
                "Выберите папку для проекта"
            )
            return

        # Проверка существования папки проекта (заменяем запрещённые символы, не удаляем)
        working_name = project_data['working_name']
        safe_name = DataCleanupManager().sanitize_filename(working_name)
        project_full_path = os.path.join(self.project_path, safe_name)
        
        if os.path.exists(project_full_path):
            QMessageBox.warning(
                self,
                "Внимание",
                f"Папка с именем '{safe_name}' уже существует в выбранной директории.\n"
                "Пожалуйста, измените рабочее название проекта."
            )
            self.working_name_edit.setFocus()
            return
        
        # Проверка системы координат
        if not self.selected_crs or not self.selected_crs.isValid():
            QMessageBox.warning(
                self,
                "Внимание",
                "Выберите систему координат (МСК региона)"
            )
            return

        # Гибридная логика валидации CRS:
        # - Если CRS из базы (crs_from_database=True) - код региона обязателен, валидация по базе
        # - Если CRS нативная (crs_from_database=False) - код региона опционален, без валидации по базе
        region_code = self.region_code_combo.currentText().strip()
        district_code = self.district_code_combo.currentText().strip()

        if self.crs_from_database:
            # CRS из базы данных - код региона обязателен
            if not region_code:
                QMessageBox.warning(
                    self,
                    "Внимание",
                    "Укажите код региона (например: 05)"
                )
                self.region_code_combo.setFocus()
                return

            # Формируем полный код для валидации
            full_code = f"{region_code}:{district_code}" if district_code else region_code

            # Проверяем соответствие CRS базе данных
            if self.reference_db and hasattr(self.reference_db, 'crs'):
                crs_data = self.reference_db.crs.get_crs_by_code(full_code)

                if crs_data:
                    # Валидируем что выбранная CRS соответствует базе
                    if not self.reference_db.crs.validate_crs_match(self.selected_crs, full_code):
                        reply = QMessageBox.question(
                            self,
                            "Несоответствие CRS",
                            f"Выбранная CRS не соответствует базе данных.\n\n"
                            f"Ожидается: {crs_data.get('full_name', '')}\n"
                            f"Выбрано: {self.selected_crs.description()}\n\n"
                            f"Использовать CRS из базы данных?",
                            QMessageBox.Yes | QMessageBox.No
                        )
                        if reply == QMessageBox.Yes:
                            self._suggest_crs(crs_data)
                else:
                    # CRS не найдена в базе - предупреждение
                    reply = QMessageBox.warning(
                        self,
                        "CRS не найдена",
                        f"Для кода '{full_code}' не найдена CRS в базе данных.\n\n"
                        f"Проверьте правильность кода региона/района.\n\n"
                        f"Продолжить с текущей CRS?",
                        QMessageBox.Yes | QMessageBox.No
                    )
                    if reply == QMessageBox.No:
                        return
        else:
            # CRS выбрана нативно - код региона опционален, без валидации по базе
            log_info(f"Fsm_0_1_1: CRS выбрана нативно, валидация по базе пропущена")

        # Автоматическое извлечение короткого названия СК (если еще не извлечено)
        if not self.crs_short_name:
            if self.selected_crs and self.selected_crs.isValid():
                short_name = extract_crs_short_name(self.selected_crs.description())
                if short_name:
                    self.crs_short_name = short_name
                    log_info(f"Fsm_0_1_1: Короткое название СК определено при валидации: {short_name}")
                else:
                    # Если не удалось извлечь, используем описание СК
                    self.crs_short_name = ""
                    log_warning("Fsm_0_1_1: Короткое название СК не определено, будет использовано пустое значение")

        # Проверка что выбрана МСК (по описанию)
        crs_desc = self.selected_crs.description()
        if not any(keyword in crs_desc.upper() for keyword in ["МСК", "MSK", "МЕСТНАЯ"]):
            reply = QMessageBox.question(
                self,
                "Подтверждение",
                f"Выбранная система координат:\n{crs_desc}\n\n"
                "Это не похоже на МСК региона. Продолжить?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        
        self.accept()
    
    def get_project_data(self):
        """
        Получение данных проекта

        Returns:
            Словарь с данными проекта
        """
        crs = self.selected_crs

        # Получаем значение линейного объекта только если тип объекта - Линейный
        object_type_value = None
        object_type_value_name = None
        if "Линейный" in self.object_type_combo.currentText() and self.object_type_value_combo.isEnabled():
            object_type_value = self.object_type_value_combo.currentData()
            object_type_value_name = self.object_type_value_combo.currentText()

        return {
            'working_name': self.working_name_edit.text().strip(),
            'full_name': self.full_name_edit.text().strip(),
            'object_type': self.object_type_combo.currentData(),
            'object_type_name': self.object_type_combo.currentText(),
            'object_type_value': object_type_value,  # Обязательное поле 1_2_1 (условное)
            'object_type_value_name': object_type_value_name,  # Обязательное поле 1_2_1 (условное)
            'doc_type': self.doc_type_combo.currentData(),
            'doc_type_name': self.doc_type_combo.currentText(),
            'stage': self.stage_combo.currentData(),  # Обязательное поле 1_6
            'stage_name': self.stage_combo.currentText(),  # Обязательное поле 1_6
            'project_path': self.project_path,
            'project_folder': self.project_path,  # Обязательное поле 1_3 (папка проекта)
            'crs': crs,
            'crs_epsg': crs.postgisSrid() if crs else 0,
            'crs_description': crs.description() if crs else "",
            'crs_short_name': self.crs_short_name,  # Короткое название СК (автоматически определенное)
            'code_region': self.region_code_combo.currentText().strip(),  # Обязательное поле 1_4_1
            'code_region_district': self._get_full_region_district_code(),  # Условное поле 1_4_2
            'code': self.code_edit.text().strip(),  # Дополнительное поле 2_1
            'release_date': self.release_date_edit.text().strip(),  # Дополнительное поле 2_2
            'company': self.company_combo.currentText().strip(),  # Дополнительное поле 2_3
            'city': self.city_combo.currentText().strip(),  # Дополнительное поле 2_4
            'customer': self.customer_edit.text().strip(),  # Дополнительное поле 2_5
            'general_director': self.general_director_combo.currentText().strip(),  # Дополнительное поле 2_6
            'technical_director': self.technical_director_combo.currentText().strip(),  # Дополнительное поле 2_7
            'cover': self.cover_combo.currentText().strip(),  # Дополнительное поле 2_8
            'title_start': self.title_start_edit.text().strip(),  # Дополнительное поле 2_9
            'main_scale': self.main_scale_combo.currentData(),  # Дополнительное поле 2_10
            'developer': self.developer_combo.currentText().strip(),  # Дополнительное поле 2_11
            'examiner': self.examiner_combo.currentText().strip(),  # Дополнительное поле 2_12
            'quality_control': self.quality_control_edit.text().strip(),  # Дополнительное поле 2_13 (авто)
            'sheet_format': self.sheet_format_combo.currentText().strip(),  # Дополнительное поле 2_13_sheet_format
            'sheet_orientation': self.sheet_orientation_combo.currentText().strip()  # Дополнительное поле 2_14
        }
