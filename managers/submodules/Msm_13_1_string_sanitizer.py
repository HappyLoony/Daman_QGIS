# -*- coding: utf-8 -*-
"""
Msm_13_1: String Sanitizer - Очистка строк

Очистка и нормализация строковых данных:
- Очистка имен файлов для Windows
- Очистка значений атрибутов таблиц
- Очистка имен слоев
- Удаление переносов строк
- Нормализация разделителей
- Сокращение организационно-правовых форм юрлиц
"""

import re
from typing import Any, Optional
from Daman_QGIS.utils import log_debug, log_warning


class StringSanitizer:
    """
    Очистка и нормализация строковых данных

    Примеры использования:
        >>> sanitizer = StringSanitizer()
        >>> clean_name = sanitizer.sanitize_filename("Файл:Данные")
        >>> clean_value = sanitizer.sanitize_attribute_value("Право1;Право2")
    """

    def __init__(self):
        """Инициализация санитайзера"""
        # Lazy-загрузка менеджера сокращений для избежания циклического импорта
        self._legal_abbreviations_manager = None

    def _get_legal_abbreviations_manager(self):
        """
        Получить менеджер сокращений юрлиц (lazy-loading)

        Returns:
            LegalAbbreviationsManager или None если недоступен
        """
        if self._legal_abbreviations_manager is None:
            try:
                from Daman_QGIS.managers import get_reference_managers
                ref_managers = get_reference_managers()
                self._legal_abbreviations_manager = ref_managers.legal_abbreviations
            except Exception as e:
                log_warning(f"Msm_13_1_StringSanitizer: Не удалось загрузить менеджер сокращений: {e}")
                return None
        return self._legal_abbreviations_manager

    def sanitize_attribute_value(self, value: Any) -> Any:
        """
        Очистка значений атрибутов таблиц (полей ведомостей, прав, собственников)

        Особенности:
        - Замена разделителя `;` на ` / ` (с пробелами)
        - Группировка повторяющихся "Физическое лицо" в "Множество лиц"
        - Сокращение организационно-правовых форм юрлиц (ООО, АО, ПАО и т.д.)
        - Сохранение ВСЕХ символов, включая `/` (для разделения прав)
        - НЕ удаляет и НЕ заменяет спецсимволы

        Примеры:
            >>> sanitize_attribute_value("Право1;Право2")
            "Право1 / Право2"

            >>> sanitize_attribute_value("Физическое лицо;Физическое лицо")
            "Множество лиц"

            >>> sanitize_attribute_value("Физическое лицо;конь;Физическое лицо")
            "Множество лиц / конь"

            >>> sanitize_attribute_value('Общество с ограниченной ответственностью "Рога"')
            'ООО "Рога"'

        Args:
            value: Исходное значение поля

        Returns:
            str: Очищенное значение с нормализованными разделителями
        """
        if not value or not isinstance(value, str):
            return value

        # Замена `;` на ` / ` с нормализацией пробелов вокруг точки с запятой
        # Паттерн: любое количество пробелов + ";" + любое количество пробелов → " / "
        result = re.sub(r'\s*;\s*', ' / ', value)

        # Группировка повторяющихся "Физическое лицо"
        parts = result.split(' / ')

        # Подсчитываем количество "Физическое лицо"
        physical_person_count = sum(
            1 for part in parts
            if part.strip() == "Физическое лицо"
        )

        # Если больше одного физического лица, объединяем в "Множество лиц"
        if physical_person_count > 1:
            grouped_parts = []
            replaced_first = False

            for part in parts:
                is_physical_person = part.strip() == "Физическое лицо"

                if is_physical_person:
                    # Первое вхождение заменяем на "Множество лиц"
                    if not replaced_first:
                        grouped_parts.append("Множество лиц")
                        replaced_first = True
                    # Остальные вхождения пропускаем (удаляем)
                else:
                    # Все остальные части сохраняем
                    grouped_parts.append(part)

            result = ' / '.join(grouped_parts)

        # Сокращение организационно-правовых форм юрлиц
        result = self._abbreviate_legal_forms(result)

        return result

    def _abbreviate_legal_forms(self, value: str) -> str:
        """
        Сокращение организационно-правовых форм юридических лиц

        Использует базу сокращений из Base_legal_abbreviations.json через менеджер.

        Args:
            value: Строка для обработки

        Returns:
            Строка с сокращенными наименованиями
        """
        if not value:
            return value

        manager = self._get_legal_abbreviations_manager()
        if manager is None:
            return value

        try:
            return manager.abbreviate_value(value)
        except Exception as e:
            log_debug(f"Msm_13_1_StringSanitizer: Ошибка сокращения юрлиц: {e}")
            return value

    def sanitize_filename(self, name: Any) -> str:
        """
        Очистка имен для Windows (файлы, слои, кадастровые номера, папки)

        Особенности:
        - Замена запрещенных символов Windows < > : " / \\ | ? * на `_`
        - Замена множественных подчеркиваний `__` на `_`
        - Удаление подчеркиваний и пробелов с краёв
        - Проверка зарезервированных имен Windows (CON, PRN, AUX, etc.)
        - Обработка точек и пробелов в конце имени

        Примеры:
            >>> sanitize_filename("Слой: Здания")
            "Слой_Здания"

            >>> sanitize_filename("Файл/Данные")
            "Файл_Данные"

            >>> sanitize_filename("Граница___работ")
            "Граница_работ"

            >>> sanitize_filename("CON")
            "_CON_"

        Args:
            name: Исходное имя файла/слоя

        Returns:
            str: Очищенное имя, безопасное для использования в Windows

        Raises:
            ValueError: Если имя пустое после очистки
        """
        if not name or not isinstance(name, str):
            raise ValueError("Имя не может быть пустым")

        original_name = name

        # Шаг 1: Замена запрещенных символов Windows на подчёркивание
        # Запрещенные: < > : " / \ | ? *
        forbidden_chars = '<>:"/\\|?*'
        for char in forbidden_chars:
            name = name.replace(char, '_')

        # Шаг 2: Замена множественных подчеркиваний на одно
        name = re.sub(r'_{2,}', '_', name)

        # Шаг 3: Удаление подчёркиваний и пробелов с краёв
        name = name.strip('_ ')

        # Шаг 4: Удаление точек и пробелов с конца (Windows не допускает)
        name = name.rstrip('. ')

        # Шаг 5: Проверка на пустое имя
        if not name:
            raise ValueError(f"Имя файла пустое после очистки: '{original_name}'")

        # Шаг 6: Проверка зарезервированных имен Windows
        # Имена без учета регистра и расширения
        name_upper = name.upper()
        # Убираем расширение для проверки
        name_without_ext = name_upper.split('.')[0] if '.' in name_upper else name_upper

        # Список зарезервированных имен Windows
        reserved_names = {
            'CON', 'PRN', 'AUX', 'NUL',
            'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
            'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
        }

        if name_without_ext in reserved_names:
            # Добавляем подчёркивания с двух сторон для безопасности
            name = f'_{name}_'
            log_warning(f"Msm_13_1_StringSanitizer: Зарезервированное имя Windows: '{original_name}' → '{name}'")

        # Логирование если имя изменилось
        if name != original_name:
            log_debug(f"Msm_13_1_StringSanitizer: Имя файла очищено: '{original_name}' → '{name}'")

        return name

    def sanitize_layer_name(self, name: str) -> str:
        """
        Очистка имени слоя QGIS

        Использует sanitize_filename() но с дополнительной обработкой
        для конкретных требований слоев QGIS.

        Args:
            name: Исходное имя слоя

        Returns:
            str: Очищенное имя слоя
        """
        # Используем базовую очистку filename
        # Имена слоёв имеют те же ограничения, что и файлы
        return self.sanitize_filename(name)

    def remove_line_breaks(self, value: Any) -> Any:
        """
        Удаление переносов строк из значения

        Заменяет все виды переносов строк (\\n, \\r\\n, \\r) на пробелы
        и схлопывает множественные пробелы.

        Args:
            value: Строка с возможными переносами

        Returns:
            str: Строка без переносов строк
        """
        if not value or not isinstance(value, str):
            return value

        # Замена всех переносов строк на пробелы
        result = value.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')

        # Схлопывание множественных пробелов
        result = re.sub(r'\s+', ' ', result)

        # Удаление пробелов с краёв
        result = result.strip()

        return result

    def normalize_separators(self, value: Any, target_separator: str = " / ") -> Any:
        """
        Нормализация разделителей в значении

        Заменяет различные разделители (;, |, /) на единый формат

        Args:
            value: Строка с разделителями
            target_separator: Целевой разделитель (по умолчанию " / ")

        Returns:
            str: Строка с нормализованными разделителями
        """
        if not value or not isinstance(value, str):
            return value

        # Замена всех распространённых разделителей на целевой
        # Паттерн: пробелы + разделитель + пробелы → целевой разделитель
        result = re.sub(r'\s*[;|/]\s*', target_separator, value)

        return result
