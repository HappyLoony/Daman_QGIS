# -*- coding: utf-8 -*-
"""
Базовый класс для диалогов с метаданными проекта

Предоставляет общую функциональность для работы с метаданными:
- Автоматическая загрузка enum значений из JSON
- Интеграция с DataValidator
- Общие методы для заполнения полей
"""

from typing import Dict, Any, Optional, List, Tuple
from qgis.PyQt.QtWidgets import QDialog, QComboBox, QLineEdit, QMessageBox
from Daman_QGIS.utils import log_info, log_warning
from Daman_QGIS.managers.submodules.Msm_13_4_data_validator import DataValidator


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

    def populate_enum_combo_simple(self, combo: QComboBox, field_key: str) -> bool:
        """
        Упрощенная загрузка enum (только labels, без codes)

        Args:
            combo: QComboBox для заполнения
            field_key: Ключ поля

        Returns:
            bool: True если успешно
        """
        if not self.metadata_manager:
            return False

        values = self.metadata_manager.get_field_values(field_key)

        if not values:
            return False

        combo.clear()
        for value in values:
            combo.addItem(value)

        return True

    def set_combo_by_code(self, combo: QComboBox, code: str) -> bool:
        """
        Установка значения комбобокса по коду (data)

        Args:
            combo: QComboBox
            code: Код для поиска

        Returns:
            bool: True если найдено и установлено
        """
        if not code:
            return False

        index = combo.findData(code)
        if index >= 0:
            combo.setCurrentIndex(index)
            return True

        log_warning(f"BaseMetadataDialog: Код '{code}' не найден в комбобоксе")
        return False

    def set_combo_by_text(self, combo: QComboBox, text: str) -> bool:
        """
        Установка значения комбобокса по тексту (label)

        Args:
            combo: QComboBox
            text: Текст для поиска

        Returns:
            bool: True если найдено и установлено
        """
        if not text:
            return False

        index = combo.findText(text)
        if index >= 0:
            combo.setCurrentIndex(index)
            return True

        # Если не найдено и комбобокс редактируемый, устанавливаем текст
        if combo.isEditable():
            combo.setCurrentText(text)
            return True

        log_warning(f"BaseMetadataDialog: Текст '{text}' не найден в комбобоксе")
        return False

    def get_combo_code(self, combo: QComboBox) -> Optional[str]:
        """
        Получение кода (data) из комбобокса

        Args:
            combo: QComboBox

        Returns:
            str: Код или None
        """
        return combo.currentData()

    def get_combo_text(self, combo: QComboBox) -> str:
        """
        Получение текста (label) из комбобокса

        Args:
            combo: QComboBox

        Returns:
            str: Текст
        """
        return combo.currentText().strip()

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
            '1_4_crs_short_name': metadata.get('crs_short_name'),
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
            '2_11_developer': metadata.get('developer'),
            '2_12_examiner': metadata.get('examiner')
        }

        # Добавляем остальные ключи как есть (для служебных полей)
        for key, value in metadata.items():
            if key not in ['working_name', 'full_name', 'object_type', 'object_type_name',
                          'object_type_value', 'object_type_value_name', 'project_folder',
                          'crs', 'crs_description', 'crs_epsg', 'crs_wkt', 'crs_short_name',
                          'doc_type', 'doc_type_name', 'stage', 'stage_name', 'code',
                          'release_date', 'company', 'city', 'customer', 'general_director',
                          'technical_director', 'cover', 'title_start', 'main_scale',
                          'developer', 'examiner', 'changed_fields']:
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

    def get_field_name(self, field_key: str) -> str:
        """
        Получить название поля по ключу

        Args:
            field_key: Ключ поля

        Returns:
            str: Название поля
        """
        if self.metadata_manager:
            return self.metadata_manager.get_field_name(field_key)
        return field_key

    def is_field_enum(self, field_key: str) -> bool:
        """
        Проверка является ли поле enum

        Args:
            field_key: Ключ поля

        Returns:
            bool: True если enum
        """
        if self.metadata_manager:
            return self.metadata_manager.is_field_enum(field_key)
        return False

    def get_field_values(self, field_key: str) -> List[str]:
        """
        Получить список значений для enum поля

        Args:
            field_key: Ключ поля

        Returns:
            List[str]: Список значений
        """
        if self.metadata_manager:
            return self.metadata_manager.get_field_values(field_key)
        return []

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
