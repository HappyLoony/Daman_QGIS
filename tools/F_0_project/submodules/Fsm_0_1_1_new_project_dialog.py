# -*- coding: utf-8 -*-
"""
Диалог создания нового проекта
"""

import os
from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPushButton, QLabel,
    QDialogButtonBox, QFileDialog, QMessageBox, QWidget,
    QCheckBox
)
from qgis.PyQt.QtCore import Qt, QSettings, QStandardPaths
from qgis.gui import QgsProjectionSelectionDialog
from qgis.core import QgsCoordinateReferenceSystem
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
        self.MODULE_ID = "Fsm_0_1_1"
        self.project_path = ""

        self.setup_ui()
        
    def setup_ui(self):
        """Настройка интерфейса"""
        self.setWindowTitle("Создание нового проекта")
        self.setModal(True)

        # Главный layout
        main_layout = QVBoxLayout()

        # Контейнер для скроллируемого содержимого
        content_widget = QWidget()
        form_layout = QFormLayout(content_widget)
        
        # Обязательные поля (префикс 1_)
        
        # 1_0 Рабочее название (для папок)
        self.working_name_edit = QLineEdit()
        self.working_name_edit.setPlaceholderText("Обязательно")
        form_layout.addRow("Рабочее название (для папок):", self.working_name_edit)
        
        # 1_1 Полное наименование объекта
        self.object_full_name_edit = QLineEdit()
        self.object_full_name_edit.setPlaceholderText("Обязательно")
        form_layout.addRow("Полное наименование объекта:", self.object_full_name_edit)
        
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

        # 1_7 Единственный объект
        self.single_object_checkbox = QCheckBox("Единственный объект")
        self.single_object_checkbox.setChecked(True)
        self.single_object_checkbox.setToolTip(
            "Определяет грамматическое число в наименованиях (объект/объекты)"
        )
        form_layout.addRow("", self.single_object_checkbox)

        # 1_5 Тип документации
        self.doc_type_combo = QComboBox()
        self.populate_enum_combo(self.doc_type_combo, '1_5_doc_type')
        form_layout.addRow("Тип документации (разработка):", self.doc_type_combo)

        # Ограничение: для Линейный доступен только ДПТ (МП только для площадок)
        self.setup_conditional_restriction(
            self.object_type_combo,
            self.doc_type_combo,
            '1_5_doc_type',
            {"Линейный": ["ДПТ"]}
        )

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

        # Создание CRS-виджетов ДО комбобоксов региона/зоны,
        # так как _on_zone_changed обращается к self.crs_label и self.selected_crs
        self.selected_crs = QgsCoordinateReferenceSystem()  # Хранение выбранной СК

        crs_layout = QHBoxLayout()
        self.crs_label = QLineEdit()
        self.crs_label.setReadOnly(True)
        self.crs_label.setPlaceholderText("Не выбрана")
        crs_layout.addWidget(self.crs_label)

        self.crs_button = QPushButton("Выбрать...")
        self.crs_button.clicked.connect(self.select_crs)
        crs_layout.addWidget(self.crs_button)

        # 1_4 Регион (из Base_CRS.json)
        self.region_code_combo = QComboBox()
        self.region_code_combo.setStyleSheet("QComboBox { combobox-popup: 0; }")
        self.region_code_combo.setMaxVisibleItems(12)

        # "Не указано" = кастомная CRS, pipeline недоступен
        self.region_code_combo.addItem("Не указано", None)

        # Заполнение из Base_CRS.json
        self._crs_regions_data = []
        try:
            crs_ref = self.reference_db.crs
            self._crs_regions_data = crs_ref.get_regions_for_combo()
            for region in self._crs_regions_data:
                label = f"{region['region_code']} — {region['region_name']}"
                self.region_code_combo.addItem(label, region['region_code'])
        except Exception as e:
            log_warning(f"Fsm_0_1_1: Не удалось загрузить регионы из Base_CRS.json: {e}")

        self.region_code_combo.currentIndexChanged.connect(self._on_region_changed)
        form_layout.addRow("Регион:", self.region_code_combo)

        # 1_4_1 Зона (каскад от региона)
        self.zone_code_combo = QComboBox()
        self.zone_code_combo.addItem("-", "-")
        self.zone_code_combo.setEnabled(False)
        self.zone_code_combo.currentIndexChanged.connect(self._on_zone_changed)
        form_layout.addRow("Зона:", self.zone_code_combo)

        # 1_4_2 Система координат — размещаем в layout после Региона/Зоны
        form_layout.addRow("Система координат:", crs_layout)

        # Разделитель для сведений оформления
        separator_label = QLabel("<b>Сведения для оформления:</b>")
        form_layout.addRow("", separator_label)

        # 2_1 Шифр
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("Заполнить позже")
        form_layout.addRow("Шифр:", self.code_edit)

        # 2_2 Дата выпуска
        self.release_date_edit = QLineEdit()
        self.release_date_edit.setPlaceholderText("Например: 01.2025")
        form_layout.addRow("Дата выпуска:", self.release_date_edit)

        # 2_3 Компания
        self.company_combo = QComboBox()
        self.populate_enum_combo(self.company_combo, '2_3_company', editable=True)
        form_layout.addRow("Компания:", self.company_combo)

        # 2_4 Город разработки
        self.city_combo = QComboBox()
        self.populate_enum_combo(self.city_combo, '2_4_city', editable=True)
        form_layout.addRow("Город разработки:", self.city_combo)

        # Зависимость: БТИиК -> всегда Санкт-Петербург
        self.setup_company_city_dependency()

        # 2_5 Заказчик
        self.customer_edit = QLineEdit()
        self.customer_edit.setPlaceholderText("Заполнить позже")
        form_layout.addRow("Заказчик:", self.customer_edit)

        # 2_6 Генеральный директор (скрыто, редко меняется)
        self.general_director_combo = QComboBox()
        self.populate_enum_combo(self.general_director_combo, '2_6_general_director', editable=True)
        # Скрываем поле из GUI (редко меняется)
        # form_layout.addRow("Генеральный директор:", self.general_director_combo)

        # 2_7 Технический директор (скрыто, редко меняется)
        self.technical_director_combo = QComboBox()
        self.populate_enum_combo(self.technical_director_combo, '2_7_technical_director', editable=True)
        # Скрываем поле из GUI (редко меняется)
        # form_layout.addRow("Технический директор:", self.technical_director_combo)

        # 2_13 Н.Контроль (read-only, динамическая связь с типом объекта)
        self.quality_control_edit = QLineEdit()
        self.quality_control_edit.setReadOnly(True)
        self.quality_control_edit.setStyleSheet("background-color: #f0f0f0;")  # Серый фон для read-only
        form_layout.addRow("Н.Контроль:", self.quality_control_edit)

        # 2_8 Обложка
        self.cover_combo = QComboBox()
        self.populate_enum_combo(self.cover_combo, '2_8_cover')
        self.cover_combo.currentTextChanged.connect(self.on_cover_changed)
        form_layout.addRow("Обложка:", self.cover_combo)

        # 2_9 С какого листа начинается наш титул
        self.title_start_edit = QLineEdit()
        self.title_start_edit.setPlaceholderText("Номер листа")
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
        # Устанавливаем A4 по умолчанию
        index = self.sheet_format_combo.findText("A4")
        if index >= 0:
            self.sheet_format_combo.setCurrentIndex(index)
        form_layout.addRow("Формат листа:", self.sheet_format_combo)

        # 2_14 Ориентация листа (дополнительно)
        self.sheet_orientation_combo = QComboBox()
        self.populate_enum_combo(self.sheet_orientation_combo, '2_14_sheet_orientation')
        form_layout.addRow("Ориентация листа:", self.sheet_orientation_combo)

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

        # Инициализируем значения по умолчанию
        self.update_quality_control()
        self.on_cover_changed()  # Устанавливаем начальное состояние для поля "титул"
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
    def _on_region_changed(self, index: int):
        """Обработчик изменения региона — каскадное обновление зоны и CRS."""
        region_code = self.region_code_combo.currentData()

        # Сброс зоны
        self.zone_code_combo.blockSignals(True)
        self.zone_code_combo.clear()

        if region_code is None:
            # "Не указано" — кастомная CRS
            self.zone_code_combo.addItem("-", "-")
            self.zone_code_combo.setEnabled(False)
            self.crs_button.setEnabled(True)
            self.selected_crs = QgsCoordinateReferenceSystem()
            self.crs_label.clear()
            self.crs_label.setPlaceholderText("Не выбрана")
            self.zone_code_combo.blockSignals(False)
            log_info("Fsm_0_1_1: Регион не указан — кастомная CRS")
            return

        # Находим данные региона
        region_data = None
        for r in self._crs_regions_data:
            if r['region_code'] == region_code:
                region_data = r
                break

        if not region_data:
            self.zone_code_combo.addItem("-", "-")
            self.zone_code_combo.setEnabled(False)
            self.zone_code_combo.blockSignals(False)
            return

        zones = region_data['zones']

        if len(zones) == 1 and zones[0] == '-':
            # Нет зон — заблокировать
            self.zone_code_combo.addItem("-", "-")
            self.zone_code_combo.setEnabled(False)
        elif len(zones) == 1:
            # Одна зона — показать, заблокировать
            self.zone_code_combo.addItem(f"Зона {zones[0]}", zones[0])
            self.zone_code_combo.setEnabled(False)
        else:
            # Несколько зон — placeholder + выбор
            self.zone_code_combo.addItem("Выберите зону", None)
            for z in sorted(zones):
                self.zone_code_combo.addItem(f"Зона {z}", z)
            self.zone_code_combo.setEnabled(True)

        self.zone_code_combo.blockSignals(False)

        # CRS подтягиваем только если зона однозначна (1 зона или "-")
        if len(zones) == 1:
            self._on_zone_changed(0)

        log_info(f"Fsm_0_1_1: Регион {region_code} — {region_data['region_name']}")

    def _on_zone_changed(self, index: int):
        """Обработчик изменения зоны — подтяжка CRS из Base_CRS.json."""
        region_code = self.region_code_combo.currentData()
        zone = self.zone_code_combo.currentData()

        if region_code is None or zone is None:
            return

        crs_ref = self.reference_db.crs
        entry = crs_ref.get_crs_entry(region_code, zone)
        crs = QgsCoordinateReferenceSystem.fromWkt(entry['wkt2'])
        self.selected_crs = crs
        self.crs_label.setText(entry.get('name', crs.description()))
        self.crs_button.setEnabled(False)
        log_info(f"Fsm_0_1_1: CRS из базы: {entry.get('name')}")

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

        if dialog.exec():
            crs = dialog.crs()
            if crs and crs.isValid():
                self.selected_crs = crs
                self.crs_label.setText(crs.description())
                log_info(f"Fsm_0_1_1: CRS выбрана: {crs.authid()}")
    
    def select_folder(self):
        """Выбор папки для проекта"""
        # Начальная директория: последняя использованная или рабочий стол
        settings = QSettings()
        saved_dir = settings.value("Daman_QGIS/last_project_folder", "")
        if not saved_dir or not os.path.isdir(saved_dir):
            saved_dir = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.DesktopLocation
            )

        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку для проекта",
            saved_dir,
            QFileDialog.Option.ShowDirsOnly
        )

        if folder:
            folder = os.path.normpath(folder)
            self.folder_edit.setText(folder)
            self.project_path = folder
            # Сохраняем для следующего использования
            settings.setValue("Daman_QGIS/last_project_folder", folder)
    
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

        # Код региона (из currentData combo, '-' для "Не указано")
        region_code = self.region_code_combo.currentData() or '-'

        # Код зоны ("-" = нет зон или "Не указано", номер = конкретная зона)
        zone_code = self.zone_code_combo.currentData() or '-'

        return {
            'working_name': self.working_name_edit.text().strip(),
            'object_full_name': self.object_full_name_edit.text().strip(),
            'object_type': self.object_type_combo.currentData(),
            'object_type_name': self.object_type_combo.currentText(),
            'object_type_value': object_type_value,  # Обязательное поле 1_2_1 (условное)
            'object_type_value_name': object_type_value_name,  # Обязательное поле 1_2_1 (условное)
            'is_single_object': self.single_object_checkbox.isChecked(),  # Обязательное поле 1_7
            'doc_type': self.doc_type_combo.currentData(),
            'doc_type_name': self.doc_type_combo.currentText(),
            'stage': self.stage_combo.currentData(),  # Обязательное поле 1_6
            'stage_name': self.stage_combo.currentText(),  # Обязательное поле 1_6
            'project_path': self.project_path,
            'project_folder': self.project_path,  # Обязательное поле 1_3 (папка проекта)
            'crs': crs,
            'crs_epsg': crs.postgisSrid() if crs else 0,
            'crs_description': crs.description() if crs else "",
            'region_code': region_code,  # Обязательное поле 1_4 (код региона)
            'zone_code': zone_code,  # Обязательное поле 1_4_1 (код зоны, "-" для регионов без зон)
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
