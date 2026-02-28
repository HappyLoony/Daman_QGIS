# -*- coding: utf-8 -*-
"""
Базовый класс для диалогов с метаданными проекта

Предоставляет общую функциональность для работы с метаданными:
- Автоматическая загрузка enum значений из JSON
- Интеграция с DataValidator
- Общие методы для заполнения полей
"""

from typing import Dict, Any, List, Tuple
from qgis.PyQt.QtWidgets import QDialog, QComboBox, QLineEdit, QMessageBox
from Daman_QGIS.utils import log_info, log_warning
from Daman_QGIS.managers import DataValidator

# Маппинг необязательных метаданных: field -> (db_key, description)
# Единый источник истины для F_0_1 (создание) и F_0_3 (редактирование)
OPTIONAL_METADATA_DESCRIPTIONS = {
    'code': ('2_1_code', 'Шифр (внутренняя кодировка объекта)'),
    'release_date': ('2_2_date', 'Дата выпуска для титулов, обложек, и штампов'),
    'company': ('2_3_company', 'Компания выполняющая договор'),
    'city': ('2_4_city', 'Город'),
    'customer': ('2_5_customer', 'Заказчик'),
    'general_director': ('2_6_general_director', 'Генеральный директор'),
    'technical_director': ('2_7_technical_director', 'Технический директор'),
    'cover': ('2_8_cover', 'Обложка обычно не наша'),
    'title_start': ('2_9_title_start', 'С какого листа начинается наш титул, так как перед нами могут быть еще подрядчики'),
    'main_scale': ('2_10_main_scale', 'Основной масштаб, основной массы чертежей (прописано в ТЗ)'),
    'dxf_text_height': ('2_10_1_DXF_SCALE_TO_TEXT_HEIGHT', 'Высота текста в DXF (определяется масштабом)'),
    'developer': ('2_11_developer', 'Разработал'),
    'examiner': ('2_12_examiner', 'Проверил'),
    'quality_control': ('2_13_quality_control', 'Н.Контроль'),
    'sheet_format': ('2_13_sheet_format', 'Формат листа для макетов'),
    'sheet_orientation': ('2_14_sheet_orientation', 'Ориентация листа'),
}


# Маппинг масштаба -> высота текста в DXF (единицы чертежа, метры для МСК)
# Источник: Project_Metadata.json (2_10_1_DXF_SCALE_TO_TEXT_HEIGHT)
SCALE_TO_TEXT_HEIGHT_MAP = {
    '500': '1.5',
    '1000': '3',
    '2000': '6',
}


class BaseMetadataDialog(QDialog):
    """
    Базовый класс для диалогов работы с метаданными проекта

    Предоставляет:
    - Инициализацию валидатора метаданных
    - Методы для загрузки enum из JSON
    - Общую валидацию метаданных
    """

    def __init__(self, parent=None, reference_db=None):
        """
        Инициализация базового диалога

        Args:
            parent: Родительское окно
            reference_db: Менеджер справочных БД
        """
        super().__init__(parent)
        self.reference_db = reference_db

        # ID модуля для логирования (переопределяется в подклассах)
        self.MODULE_ID = "BaseMetadataDialog"

        # Инициализация валидатора метаданных
        self.validator = None
        self.metadata_manager = None

        if reference_db and hasattr(reference_db, 'project_metadata'):
            self.metadata_manager = reference_db.project_metadata
            self.validator = DataValidator(self.metadata_manager)

    def populate_enum_combo(self, combo: QComboBox, field_key: str,
                           editable: bool = False, add_empty: bool = False) -> bool:
        """
        Заполнение QComboBox значениями из метаданных

        Args:
            combo: QComboBox для заполнения
            field_key: Ключ поля в Project_Metadata.json (например '1_6_stage')
            editable: Разрешить редактирование (для полей с кастомными значениями)
            add_empty: Добавить пустой элемент в начало

        Returns:
            bool: True если успешно загружено, False если нет данных

        Example:
            self.populate_enum_combo(self.stage_combo, '1_6_stage')
            # Автоматически загрузит: Первичная, Внесение изменений
        """
        if not self.metadata_manager:
            log_warning(f"BaseMetadataDialog: Metadata manager недоступен для загрузки enum {field_key}")
            return False

        # Получаем значения с кодами из JSON
        values_with_codes = self.metadata_manager.get_field_values_with_codes(field_key)

        if not values_with_codes:
            log_warning(f"BaseMetadataDialog: Нет значений для enum поля {field_key}")
            return False

        # Очищаем комбобокс
        combo.clear()

        # Настраиваем редактируемость
        combo.setEditable(editable)

        # Добавляем пустой элемент если нужно
        if add_empty:
            combo.addItem("", "")

        # Заполняем значениями
        for label, code in values_with_codes:
            combo.addItem(label, code)

        return True

    def _map_short_keys_to_full(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Преобразование коротких ключей в полные для валидации

        Args:
            metadata: Словарь с короткими ключами (working_name, full_name и т.д.)

        Returns:
            Словарь с полными ключами (1_0_working_name, 1_1_full_name и т.д.)
        """
        # Для enum-полей используем *_name значения (отображаемые тексты)
        # вместо ключей, так как валидатор проверяет по отображаемым значениям
        mapped = {
            '1_0_working_name': metadata.get('working_name'),
            '1_1_full_name': metadata.get('full_name'),
            '1_2_object_type': metadata.get('object_type_name'),  # Используем _name для enum
            '1_2_1_object_type_value': metadata.get('object_type_value_name'),  # Используем _name для enum
            '1_3_project_folder': metadata.get('project_folder'),
            '1_4_crs': metadata.get('crs'),
            '1_4_crs_description': metadata.get('crs_description'),
            '1_4_crs_epsg': metadata.get('crs_epsg'),
            '1_4_crs_wkt': metadata.get('crs_wkt'),
            '1_4_1_code_region': metadata.get('code_region'),  # Код региона
            '1_4_2_code_zone': metadata.get('code_zone'),  # Код зоны
            '1_5_doc_type': metadata.get('doc_type_name'),  # Используем _name для enum
            '1_6_stage': metadata.get('stage_name'),  # Используем _name для enum
            '2_1_code': metadata.get('code'),
            '2_2_date': metadata.get('release_date'),
            '2_3_company': metadata.get('company'),
            '2_4_city': metadata.get('city'),
            '2_5_customer': metadata.get('customer'),
            '2_6_general_director': metadata.get('general_director'),
            '2_7_technical_director': metadata.get('technical_director'),
            '2_8_cover': metadata.get('cover'),
            '2_9_title_start': metadata.get('title_start'),
            '2_10_main_scale': metadata.get('main_scale'),
            '2_10_1_DXF_SCALE_TO_TEXT_HEIGHT': metadata.get('dxf_text_height'),
            '2_11_developer': metadata.get('developer'),
            '2_12_examiner': metadata.get('examiner')
        }

        # Добавляем остальные ключи как есть (для служебных полей)
        for key, value in metadata.items():
            if key not in ['working_name', 'full_name', 'object_type', 'object_type_name',
                          'object_type_value', 'object_type_value_name', 'project_folder',
                          'crs', 'crs_description', 'crs_epsg', 'crs_wkt',
                          'code_region', 'code_zone',
                          'doc_type', 'doc_type_name', 'stage', 'stage_name', 'code',
                          'release_date', 'company', 'city', 'customer', 'general_director',
                          'technical_director', 'cover', 'title_start', 'main_scale',
                          'dxf_text_height', 'developer', 'examiner', 'changed_fields']:
                mapped[key] = value

        return mapped

    def validate_metadata(self, metadata: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Валидация метаданных с использованием DataValidator

        Args:
            metadata: Словарь метаданных для проверки

        Returns:
            Tuple[bool, List[str]]: (is_valid, errors)
        """
        if self.validator:
            # Преобразуем короткие ключи в полные
            full_metadata = self._map_short_keys_to_full(metadata)

            is_valid, errors = self.validator.validate_all(full_metadata)

            if not is_valid:
                log_warning(f"BaseMetadataDialog: Найдено {len(errors)} ошибок валидации метаданных")
                # Выводим ошибки в лог для диагностики
                for error in errors:
                    log_warning(f"BaseMetadataDialog:   - {error}")
            else:
                log_info("BaseMetadataDialog: Валидация метаданных прошла успешно")

            return is_valid, errors

        # Fallback если валидатор недоступен
        log_warning("BaseMetadataDialog: DataValidator недоступен, валидация пропущена")
        return True, []

    def show_validation_errors(self, errors: List[str], title: str = "Ошибки валидации") -> None:
        """
        Показать ошибки валидации пользователю

        Args:
            errors: Список ошибок
            title: Заголовок окна
        """
        if not errors:
            return

        error_message = "Обнаружены следующие ошибки:\n\n"
        error_message += "\n".join(f"• {err}" for err in errors)

        QMessageBox.warning(self, title, error_message)

    def validate_and_show_errors(self, metadata: Dict[str, Any]) -> bool:
        """
        Валидация метаданных с автоматическим показом ошибок

        Args:
            metadata: Словарь метаданных

        Returns:
            bool: True если валидация прошла
        """
        is_valid, errors = self.validate_metadata(metadata)

        if not is_valid:
            self.show_validation_errors(errors)

        return is_valid

    def load_developers(self):
        """Загрузка разработчиков из справочной БД"""
        self.developer_combo.addItem("")

        if self.reference_db:
            try:
                developers = self.reference_db.employee.get_employees_by_role('developed')
                last_names = sorted([emp.get('last_name', '') for emp in developers if emp.get('last_name')])

                for last_name in last_names:
                    self.developer_combo.addItem(last_name)

                if len(last_names) > 10:
                    from qgis.PyQt.QtWidgets import QListView
                    self.developer_combo.setView(QListView())
                    self.developer_combo.view().setMaximumHeight(300)
            except Exception as e:
                log_warning(f"{self.MODULE_ID}: Не удалось загрузить разработчиков: {e}")
        else:
            log_warning(f"{self.MODULE_ID}: Справочная БД недоступна для загрузки разработчиков")

    def load_examiners(self):
        """Загрузка проверяющих из справочной БД"""
        self.examiner_combo.addItem("")

        if self.reference_db:
            try:
                examiners = self.reference_db.employee.get_employees_by_role('verified')
                last_names = sorted([emp.get('last_name', '') for emp in examiners if emp.get('last_name')])

                for last_name in last_names:
                    self.examiner_combo.addItem(last_name)

                if len(last_names) > 10:
                    from qgis.PyQt.QtWidgets import QListView
                    self.examiner_combo.setView(QListView())
                    self.examiner_combo.view().setMaximumHeight(300)
            except Exception as e:
                log_warning(f"{self.MODULE_ID}: Не удалось загрузить проверяющих: {e}")
        else:
            log_warning(f"{self.MODULE_ID}: Справочная БД недоступна для загрузки проверяющих")

    def update_quality_control(self):
        """
        Автоматическое обновление поля "Н.Контроль" на основе типа объекта

        Логика:
        - "Площадной" -> Евдокимова
        - "Линейный" -> Никитин
        """
        object_type = self.object_type_combo.currentText()

        if "Площадной" in object_type:
            self.quality_control_edit.setText("Евдокимова")
        elif "Линейный" in object_type:
            self.quality_control_edit.setText("Никитин")
        else:
            self.quality_control_edit.clear()

    def on_scale_changed(self):
        """
        Автоматическое обновление высоты текста DXF при смене масштаба.

        Маппинг масштаб -> высота текста:
        - 1:500  -> 1.5м
        - 1:1000 -> 3м
        - 1:2000 -> 6м
        """
        scale_code = self.main_scale_combo.currentData()
        if scale_code and scale_code in SCALE_TO_TEXT_HEIGHT_MAP:
            self.dxf_text_height_edit.setText(SCALE_TO_TEXT_HEIGHT_MAP[scale_code])
        else:
            self.dxf_text_height_edit.clear()

    def on_cover_changed(self):
        """Обработчик изменения типа обложки"""
        cover_type = self.cover_combo.currentText()

        if cover_type == "Наша":
            self.title_start_edit.setText("2")
            self.title_start_edit.setReadOnly(True)
            self.title_start_edit.setStyleSheet("background-color: #f0f0f0;")
        else:
            self.title_start_edit.setReadOnly(False)
            self.title_start_edit.setStyleSheet("")
            if self.title_start_edit.text() == "2":
                self.title_start_edit.clear()

    def setup_company_city_dependency(self) -> None:
        """
        Настройка зависимости города от компании.

        Логика:
        - БТИиК -> город всегда "Санкт-Петербург", поле заблокировано
        - КРТ (и другие) -> город можно выбирать свободно
        """
        def on_company_changed(text: str):
            if 'БТИиК' in text:
                self.city_combo.setCurrentText('Санкт-Петербург')
                self.city_combo.setEnabled(False)
            else:
                self.city_combo.setEnabled(True)

        self.company_combo.currentTextChanged.connect(on_company_changed)
        # Инициализируем состояние по текущему значению
        on_company_changed(self.company_combo.currentText())

    def setup_conditional_field(self, parent_combo: QComboBox, child_combo: QComboBox,
                                parent_value_to_enable: str) -> None:
        """
        Настройка условной зависимости между полями

        Args:
            parent_combo: Родительский комбобокс
            child_combo: Дочерний комбобокс (будет активироваться/деактивироваться)
            parent_value_to_enable: Значение родителя при котором активируется дочерний

        Example:
            # object_type_value активен только для "Линейный"
            self.setup_conditional_field(
                self.object_type_combo,
                self.object_type_value_combo,
                "Линейный"
            )
        """
        def on_parent_changed(text):
            if parent_value_to_enable in text:
                child_combo.setEnabled(True)
            else:
                child_combo.setEnabled(False)
                child_combo.setCurrentIndex(0 if child_combo.count() > 0 else -1)

        # Подключаем обработчик
        parent_combo.currentTextChanged.connect(on_parent_changed)

        # Инициализируем состояние
        on_parent_changed(parent_combo.currentText())
