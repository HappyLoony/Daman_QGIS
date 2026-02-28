# -*- coding: utf-8 -*-
"""
Msm_13_2: Attribute Processor - Обработка атрибутов

Обработка атрибутивных данных:
- Парсинг и объединение множественных значений
- Капитализация текстовых полей
- Нормализация NULL значений
- Переупорядочивание прав и собственников
- Финальная обработка слоёв ("наведение красоты")
- Определение типа объекта по формату КН (НГС vs Раздел ЗУ)
"""

import re
from typing import List, Optional, Tuple
from qgis.core import QgsVectorLayer, QgsFeature, NULL
from Daman_QGIS.utils import log_info, log_debug


class AttributeProcessor:
    """
    Обработка атрибутов таблиц и ведомостей

    Примеры использования:
        >>> processor = AttributeProcessor()
        >>> parts = processor.parse_field("Право1 / Право2")
        >>> capitalized = processor.capitalize_field("хранение автотранспорта")
        >>> processor.finalize_layer_processing(layer, "L_1_1_1_ЗУ")
    """

    # Поля с особой обработкой NULL - вместо "-" используется специальный текст
    # Формат: {имя_поля: текст_для_NULL}
    NULL_REPLACEMENTS = {
        'Права': 'Сведения отсутствуют',
        'Собственники': 'Сведения отсутствуют',
        'Категория': 'Категория не установлена',
    }

    # Исключения из NULL_REPLACEMENTS для определённых слоёв
    # Формат: {ключевое_слово_в_имени_слоя: [поля_для_исключения]}
    # Для этих слоёв указанные поля будут заполняться "-" вместо специального текста
    NULL_REPLACEMENT_EXCEPTIONS = {
        'НГС': ['Категория'],  # У НГС категория не устанавливается - оставляем "-"
    }

    # Регулярные выражения для определения типа КН
    # НГС: XX:XX:XXXXXX или XX:XX:XXXXXXX (6-7 цифр в конце, БЕЗ номера ЗУ)
    # Раздел ЗУ: XX:XX:XXXXXX:N (есть номер ЗУ после последнего двоеточия)
    KN_PATTERN_NGS = re.compile(r'^\d{2}:\d{2}:\d{6,7}$')
    KN_PATTERN_ZU = re.compile(r'^\d{2}:\d{2}:\d{6,7}:\d+$')

    # Поля, которые должны быть "-" для НГС на основе валидации КН
    # (независимо от имени слоя)
    # При образовании ЗУ на НГС (незастроенной территории) исходного ЗУ не существует,
    # поэтому все поля связанные с ИСХОДНЫМ ЗУ должны быть "-"
    NGS_NULL_FIELDS = [
        # Категория ИСХОДНОГО ЗУ (его не существует)
        'Категория',
        # Площадь исходного ЗУ (его не существует)
        'Площадь',
        # Права и собственники исходного ЗУ
        'Права',
        'Собственники',
        'Арендаторы',
        'Обременения',
        # ВРИ исходного ЗУ
        'ВРИ',
        # Тип объекта исходного ЗУ
        'Тип_объекта',
    ]

    # Поля, которые должны быть "ЗАПОЛНИ!" для НГС (требуют ручного заполнения)
    # Планируемые параметры для образуемого ЗУ - их нельзя определить автоматически
    NGS_FILLME_FIELDS = [
        'План_категория',
    ]

    # Заглушка для полей требующих ручного заполнения
    FILLME_PLACEHOLDER = 'ЗАПОЛНИ!'

    # Разделитель для множественных значений в полях (используется во всех операциях парсинга)
    FIELD_SEPARATOR = " / "

    # Приоритет прав (в порядке убывания приоритета) для normalize_rights_order()
    PRIORITY_RIGHTS = [
        "Собственность",
        "Общая долевая собственность",
        "Общая совместная собственность"
    ]

    def __init__(self):
        """Инициализация процессора атрибутов"""
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
                log_debug(f"Msm_13_2_AttributeProcessor: Не удалось загрузить менеджер сокращений: {e}")
                return None
        return self._legal_abbreviations_manager

    def _abbreviate_legal_forms(self, value: str) -> str:
        """
        Сокращение организационно-правовых форм юридических лиц

        Использует базу сокращений из Base_legal_abbreviations.json через менеджер.
        Примеры: "АКЦИОНЕРНОЕ ОБЩЕСТВО" -> "АО", "Общество с ограниченной ответственностью" -> "ООО"

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
            log_debug(f"Msm_13_2_AttributeProcessor: Ошибка сокращения юрлиц: {e}")
            return value

    def is_ngs_by_kn(self, kn_value: Optional[str]) -> bool:
        """
        Определяет, является ли объект НГС по формату кадастрового номера

        НГС (Населённые пункты/Географические сущности):
        - Формат: XX:XX:XXXXXX или XX:XX:XXXXXXX (6-7 цифр в конце)
        - Примеры: 91:01:012001, 91:01:0120010

        Раздел ЗУ (Земельные участки):
        - Формат: XX:XX:XXXXXX:N (есть номер ЗУ после последнего :)
        - Примеры: 91:01:012001:1, 91:01:0120010:15

        Args:
            kn_value: Значение поля КН (может быть None или пустым)

        Returns:
            True если объект НГС, False если раздел ЗУ или КН невалидный
        """
        if not kn_value:
            return False

        kn_str = str(kn_value).strip()

        # Пустой или "-"
        if not kn_str or kn_str == '-':
            return False

        # Проверяем формат НГС
        if self.KN_PATTERN_NGS.match(kn_str):
            return True

        return False

    def is_zu_by_kn(self, kn_value: Optional[str]) -> bool:
        """
        Определяет, является ли объект разделом ЗУ по формату кадастрового номера

        Args:
            kn_value: Значение поля КН

        Returns:
            True если объект является разделом ЗУ (имеет номер ЗУ в КН)
        """
        if not kn_value:
            return False

        kn_str = str(kn_value).strip()

        if not kn_str or kn_str == '-':
            return False

        # Проверяем формат ЗУ
        if self.KN_PATTERN_ZU.match(kn_str):
            return True

        return False

    def _is_field_excluded_from_null_replacement(self, field_name: str, layer_name: str) -> bool:
        """
        Проверяет, должно ли поле быть исключено из NULL_REPLACEMENTS для данного слоя

        Args:
            field_name: Имя поля
            layer_name: Имя слоя

        Returns:
            True если поле должно заполняться "-" вместо специального текста
        """
        for keyword, excluded_fields in self.NULL_REPLACEMENT_EXCEPTIONS.items():
            if keyword in layer_name and field_name in excluded_fields:
                return True
        return False

    def _get_kn_from_feature(self, feature: QgsFeature) -> Optional[str]:
        """
        Получает значение КН из объекта

        Args:
            feature: Объект слоя

        Returns:
            Значение КН или None
        """
        field_names = feature.fields().names()

        for kn_field in ['КН', 'Услов_КН', 'kn', 'cadastral_number']:
            if kn_field in field_names:
                kn_value = feature[kn_field]
                if kn_value:
                    return str(kn_value).strip()
        return None

    def _is_field_excluded_by_kn(self, field_name: str, feature: QgsFeature) -> bool:
        """
        Проверяет, должно ли поле быть "-" на основе валидации КН в объекте

        Для объектов НГС (КН формата XX:XX:XXXXXX) поля из NGS_NULL_FIELDS
        должны быть "-", а не специальным текстом.

        Args:
            field_name: Имя поля
            feature: Объект слоя для проверки КН

        Returns:
            True если поле должно заполняться "-" (объект НГС)
        """
        # Проверяем только для полей из NGS_NULL_FIELDS
        if field_name not in self.NGS_NULL_FIELDS:
            return False

        kn_value = self._get_kn_from_feature(feature)
        if not kn_value:
            return False

        # Проверяем формат КН
        return self.is_ngs_by_kn(kn_value)

    def _is_field_fillme_by_kn(self, field_name: str, feature: QgsFeature) -> bool:
        """
        Проверяет, должно ли поле быть "ЗАПОЛНИ!" на основе валидации КН в объекте

        Для объектов НГС (КН формата XX:XX:XXXXXX) поля из NGS_FILLME_FIELDS
        должны быть "ЗАПОЛНИ!" для ручного заполнения.

        Args:
            field_name: Имя поля
            feature: Объект слоя для проверки КН

        Returns:
            True если поле должно заполняться "ЗАПОЛНИ!" (объект НГС)
        """
        # Проверяем только для полей из NGS_FILLME_FIELDS
        if field_name not in self.NGS_FILLME_FIELDS:
            return False

        kn_value = self._get_kn_from_feature(feature)
        if not kn_value:
            return False

        # Проверяем формат КН
        return self.is_ngs_by_kn(kn_value)

    def parse_field(self, value: Optional[str]) -> List[str]:
        """
        Парсинг поля с множественными значениями

        Разделяет строку по FIELD_SEPARATOR, очищает каждый элемент,
        фильтрует пустые значения и "-".

        Args:
            value: Значение поля (может быть None или пустым)

        Returns:
            List[str]: Список значений (пустой список если value=None или пустая строка)

        Examples:
            >>> parse_field("Право1 / Право2")
            ["Право1", "Право2"]

            >>> parse_field("Право1 / - / Право2")
            ["Право1", "Право2"]

            >>> parse_field(None)
            []
        """
        if not value:
            return []

        value = value.strip()

        if not value or value == "-":
            return []

        # Разделяем по FIELD_SEPARATOR и очищаем каждое значение
        parts = [part.strip() for part in value.split(self.FIELD_SEPARATOR)]

        # Фильтруем пустые значения и "-"
        return [part for part in parts if part and part != "-"]

    def join_field(self, values: List[str]) -> str:
        """
        Объединение списка значений в строку через разделитель

        Args:
            values: Список значений

        Returns:
            str: Строка с разделителями FIELD_SEPARATOR, или "-" если список пустой

        Examples:
            >>> join_field(["Право1", "Право2"])
            "Право1 / Право2"

            >>> join_field([])
            "-"
        """
        if not values:
            return "-"
        return self.FIELD_SEPARATOR.join(values)

    def capitalize_first_letter(self, value: str) -> str:
        """
        Делает первую БУКВУ строки заглавной

        Ищет первую букву в строке (пропуская цифры, точки, пробелы и т.д.).
        Не трогает остальные символы (для сохранения аббревиатур типа "РФ").

        Исключение: если первая буква является частью сокращения (за ней следует точка,
        например "д.", "г.", "с.", "п."), капитализация НЕ применяется.
        Это важно для АТД слоёв: "д. Овсянниково" должно остаться как есть.

        Args:
            value: Строка для обработки

        Returns:
            str: Строка с заглавной первой буквой

        Examples:
            >>> capitalize_first_letter("7.1. сооружения")
            "7.1. Сооружения"

            >>> capitalize_first_letter("хранение")
            "Хранение"

            >>> capitalize_first_letter("д. Овсянниково")
            "д. Овсянниково"

            >>> capitalize_first_letter("муниципальное образование")
            "Муниципальное образование"
        """
        if not value:
            return value

        # Ищем первую БУКВУ в строке
        for i, char in enumerate(value):
            if char.isalpha():
                # Проверяем: если за буквой сразу идёт точка, это сокращение ("д.", "г.", "с.")
                # В таком случае НЕ капитализируем
                if i + 1 < len(value) and value[i + 1] == '.':
                    return value
                # Найдена первая буква - делаем заглавной
                return value[:i] + char.upper() + value[i+1:]

        # Если букв нет вообще - возвращаем без изменений
        return value

    def capitalize_field(self, field_value: Optional[str]) -> str:
        """
        Капитализация первой буквы в каждом элементе поля

        Парсит поле по разделителю FIELD_SEPARATOR, применяет capitalize к каждому элементу.

        Args:
            field_value: Значение поля (может содержать FIELD_SEPARATOR)

        Returns:
            str: Обработанное значение

        Examples:
            >>> capitalize_field("хранение автотранспорта (код 2.7.1)")
            "Хранение автотранспорта (код 2.7.1)"

            >>> capitalize_field("постоянное (бессрочное) пользование / собственность")
            "Постоянное (бессрочное) пользование / Собственность"
        """
        # Если пустое или "-", возвращаем как есть
        if not field_value or field_value.strip() in ["-", ""]:
            return field_value or "-"

        # Парсим поле через универсальный метод
        parts = self.parse_field(field_value)

        if not parts:
            return field_value

        # Применяем capitalize к каждому элементу
        capitalized_parts = [self.capitalize_first_letter(part) for part in parts]

        # Собираем обратно через универсальный метод
        return self.join_field(capitalized_parts)

    def normalize_null_value(self, value, field_name: str) -> str:
        """
        Нормализация NULL значения для конкретного поля

        Обрабатывает поля:
        - По умолчанию: NULL/пустое → "-"
        - ИСКЛЮЧЕНИЯ (из NULL_REPLACEMENTS):
          * "Права" → "Сведения отсутствуют"
          * "Собственники" → "Сведения отсутствуют"
          * "Категория" → "Категория не установлена"

        Args:
            value: Значение поля (может быть None, int, str)
            field_name: Имя поля

        Returns:
            str: Нормализованное значение
        """
        if value is None or value == '':
            # Для полей из NULL_REPLACEMENTS возвращаем специальный текст
            if field_name in self.NULL_REPLACEMENTS:
                return self.NULL_REPLACEMENTS[field_name]
            # Для всех остальных полей возвращаем "-"
            return '-'

        # Преобразуем в строку
        value_str = str(value)

        # Проверяем строку "NULL" из API
        if value_str.strip().upper() == 'NULL':
            if field_name in self.NULL_REPLACEMENTS:
                return self.NULL_REPLACEMENTS[field_name]
            return '-'

        return value_str

    def deduplicate_encumbrances_and_tenants(self, encumbrances_value: Optional[str],
                                              tenants_value: Optional[str]) -> Tuple[str, str]:
        """
        Дедупликация пар Обременения-Арендаторы (удаление дубликатов ТОЛЬКО для типа "Аренда")

        ВАЖНО: Сохраняет позиционное соответствие между полями!
        Дедупликация применяется ТОЛЬКО к парам с типом "Аренда".
        Другие типы обременений (Сервитут и т.д.) сохраняются как есть.

        Пример:
            Обременения: Аренда / Сервитут / Аренда / Сервитут / Аренда / Аренда / Аренда
            Арендаторы:  Физ1   / ООО      / Физ2   / ООО      / Физ1   / Физ1   / Физ1

            Уникальные пары Аренды: (Аренда, Физ1), (Аренда, Физ2)
            Сервитут не дедуплицируется!

            Результат:
            Обременения: Аренда / Сервитут / Аренда / Сервитут
            Арендаторы:  Физ1   / ООО      / Физ2   / ООО

        Args:
            encumbrances_value: Значение поля "Обременения"
            tenants_value: Значение поля "Арендаторы"

        Returns:
            Tuple[str, str]: (дедуплицированные обременения, дедуплицированные арендаторы)
        """
        # Если одно из значений пустое - возвращаем как есть
        if not encumbrances_value or not tenants_value:
            return encumbrances_value or "-", tenants_value or "-"

        if encumbrances_value.strip() == "-" or tenants_value.strip() == "-":
            return encumbrances_value, tenants_value

        # Парсим оба поля
        encumbrances_list = self.parse_field(encumbrances_value)
        tenants_list = self.parse_field(tenants_value)

        # Если списки пустые - ничего не делаем
        if not encumbrances_list or not tenants_list:
            return encumbrances_value, tenants_value

        # Отслеживаем уникальные пары ТОЛЬКО для типа "Аренда"
        seen_rent_pairs = set()
        new_encumbrances = []
        new_tenants = []

        # Обрабатываем по минимальной длине для синхронности
        min_len = min(len(encumbrances_list), len(tenants_list))

        for i in range(min_len):
            enc = encumbrances_list[i].strip()
            tenant = tenants_list[i].strip()

            # Дедупликация ТОЛЬКО для типа "Аренда"
            if enc == "Аренда":
                pair = (enc, tenant)
                if pair in seen_rent_pairs:
                    # Дубликат пары Аренда - пропускаем
                    continue
                seen_rent_pairs.add(pair)

            # Добавляем пару (или не-Аренда, или уникальная Аренда)
            new_encumbrances.append(enc)
            new_tenants.append(tenant)

        # Если ничего не изменилось - возвращаем исходные
        if len(new_encumbrances) == min_len:
            return encumbrances_value, tenants_value

        # Собираем обратно
        return self.join_field(new_encumbrances), self.join_field(new_tenants)

    def simplify_rent_individuals(self, encumbrances_value: Optional[str],
                                   tenants_value: Optional[str]) -> Tuple[str, str]:
        """
        Упрощение множественных арендаторов-физлиц в "Множество физических лиц"

        ПРАВИЛА:
        1. Работает ТОЛЬКО для пар "Аренда" + "Физическое лицо"
        2. Сокращает только если физлиц >= 2
        3. Сохраняет порядок остальных пар (Сервитут, юрлица и т.д.)
        4. Первая пара "Аренда"+"Физическое лицо" заменяется на "Аренда"+"Множество физических лиц"
        5. Остальные такие пары удаляются

        Args:
            encumbrances_value: Значение поля "Обременения" (через " / " или ";")
            tenants_value: Значение поля "Арендаторы" (через " / " или ";")

        Returns:
            Tuple[str, str]: (упрощённые обременения, упрощённые арендаторы)

        Examples:
            Исходник:
                Обременения: Аренда / Сервитут / Аренда / Аренда / Аренда
                Арендаторы: Физическое лицо / ООО "ИЛАР" / Физическое лицо / Физическое лицо / Физическое лицо

            Результат:
                Обременения: Аренда / Сервитут
                Арендаторы: Множество физических лиц / ООО "ИЛАР"

            ---

            Исходник (менее 2 физлиц - не сокращаем):
                Обременения: Аренда / Сервитут / Аренда
                Арендаторы: Физическое лицо / ООО "ИЛАР" / ООО "Рога"

            Результат (без изменений):
                Обременения: Аренда / Сервитут / Аренда
                Арендаторы: Физическое лицо / ООО "ИЛАР" / ООО "Рога"
        """
        # Если одно из значений пустое - возвращаем как есть
        if not encumbrances_value or not tenants_value:
            return encumbrances_value or "-", tenants_value or "-"

        if encumbrances_value.strip() == "-" or tenants_value.strip() == "-":
            return encumbrances_value, tenants_value

        # Парсим оба поля
        encumbrances_list = self.parse_field(encumbrances_value)
        tenants_list = self.parse_field(tenants_value)

        # Если списки пустые или разной длины - ничего не делаем
        if not encumbrances_list or not tenants_list:
            return encumbrances_value, tenants_value

        # Находим индексы всех пар "Аренда" + "Физическое лицо"
        rent_individual_indices = []
        for i in range(min(len(encumbrances_list), len(tenants_list))):
            enc = encumbrances_list[i].strip()
            tenant = tenants_list[i].strip()

            if enc == "Аренда" and tenant == "Физическое лицо":
                rent_individual_indices.append(i)

        # Если менее 2 пар - не сокращаем
        if len(rent_individual_indices) < 2:
            return encumbrances_value, tenants_value

        # Строим новые списки
        new_encumbrances = []
        new_tenants = []
        first_rent_individual_added = False

        for i in range(max(len(encumbrances_list), len(tenants_list))):
            enc = encumbrances_list[i].strip() if i < len(encumbrances_list) else "-"
            tenant = tenants_list[i].strip() if i < len(tenants_list) else "-"

            if i in rent_individual_indices:
                # Это пара "Аренда" + "Физическое лицо"
                if not first_rent_individual_added:
                    # Первое вхождение - заменяем на "Множество физических лиц"
                    new_encumbrances.append("Аренда")
                    new_tenants.append("Множество физических лиц")
                    first_rent_individual_added = True
                # Остальные вхождения пропускаем (удаляем)
            else:
                # Обычная пара - сохраняем
                new_encumbrances.append(enc)
                new_tenants.append(tenant)

        # Собираем обратно
        result_encumbrances = self.join_field(new_encumbrances)
        result_tenants = self.join_field(new_tenants)

        return result_encumbrances, result_tenants

    def normalize_rights_order(self, rights_value: Optional[str],
                               owners_value: Optional[str]) -> Tuple[str, str]:
        """
        Переупорядочивает права и собственников так, чтобы приоритетные права были первыми

        Приоритет прав (в порядке убывания):
        1. "Собственность"
        2. "Общая долевая собственность"
        3. "Общая совместная собственность"

        Логика:
        - Ищет приоритетное право в списке (из PRIORITY_RIGHTS)
        - Если найдено и НЕ на первом месте - переставляет
        - Синхронно переставляет собственников (если элемент с таким индексом существует)

        Args:
            rights_value: Значение поля "Права"
            owners_value: Значение поля "Собственники"

        Returns:
            Tuple[str, str]: (нормализованные права, нормализованные собственники)

        Examples:
            >>> normalize_rights_order(
                "Постоянное (бессрочное) пользование / Собственность",
                "Муниципальная / Частная"
            )
            ("Собственность / Постоянное (бессрочное) пользование", "Частная / Муниципальная")

            >>> normalize_rights_order(
                "Постоянное (бессрочное) пользование / Собственность",
                "Частная"
            )
            ("Собственность / Постоянное (бессрочное) пользование", "Частная")

            >>> normalize_rights_order("Собственность", "Частная")
            ("Собственность", "Частная")
        """
        # Если значения пустые или "-", ничего не делаем
        if not rights_value or rights_value.strip() == "-":
            return rights_value or "-", owners_value or "-"

        # Парсим поля
        rights_list = self.parse_field(rights_value)
        owners_list = self.parse_field(owners_value)

        if not rights_list:
            return rights_value, owners_value or "-"

        # Ищем приоритетное право
        priority_index = None
        priority_right = None

        for priority in self.PRIORITY_RIGHTS:
            if priority in rights_list:
                priority_index = rights_list.index(priority)
                priority_right = priority
                break

        # Если приоритетного права нет или оно уже первое - ничего не делаем
        if priority_index is None or priority_index == 0:
            return rights_value, owners_value or "-"

        # Переставляем права: приоритетное на первое место, остальные сдвигаются
        new_rights_list = [rights_list[priority_index]] + rights_list[:priority_index] + rights_list[priority_index+1:]

        # Переставляем собственников СИНХРОННО, НО только если элемент существует
        new_owners_list = owners_list.copy()
        if priority_index < len(owners_list):
            # Переставляем синхронно с правами
            new_owners_list = [owners_list[priority_index]] + owners_list[:priority_index] + owners_list[priority_index+1:]

        # Собираем обратно в строки
        new_rights_value = self.join_field(new_rights_list)
        new_owners_value = self.join_field(new_owners_list) if new_owners_list else (owners_value or "-")

        return new_rights_value, new_owners_value

    def finalize_layer_processing(self,
                                  layer: QgsVectorLayer,
                                  layer_name: str,
                                  fields_to_process: Optional[List[str]] = None,
                                  capitalize: bool = True,
                                  exclude_fields: Optional[List[str]] = None) -> None:
        """
        УНИВЕРСАЛЬНАЯ финальная обработка слоя - "наведение красоты"

        Выполняет комплексную обработку всех текстовых полей:
        1. Заполнение NULL/пустых значений ("-" или "Сведения отсутствуют")
        2. Капитализация первой буквы (опционально)

        ВАЖНО: Этот метод вызывается ПОСЛЕ сохранения/загрузки из GeoPackage.

        Args:
            layer: Слой для обработки
            layer_name: Имя слоя (для логирования)
            fields_to_process: Список полей для обработки. Если None, обрабатываются ВСЕ текстовые поля
            capitalize: Применять ли капитализацию первой буквы (по умолчанию True)
            exclude_fields: Список полей для исключения из обработки (например, технических полей)
        """
        log_debug(f"Msm_13_2_AttributeProcessor: Финальная обработка слоя {layer_name}")

        # Поля, которые не нужно капитализировать (технические и числовые)
        if exclude_fields is None:
            exclude_fields = []

        # Получаем список полей слоя
        fields = layer.fields()

        # Если список полей не указан, обрабатываем ВСЕ текстовые поля
        if fields_to_process is None:
            from qgis.PyQt.QtCore import QMetaType
            # Автоматически выбираем только текстовые поля (QString)
            # Integer поля (например "Площадь" в ЗУ) автоматически исключаются
            fields_to_process = [f.name() for f in fields if f.type() == QMetaType.Type.QString]
        else:
            # Фильтруем только существующие текстовые поля
            from qgis.PyQt.QtCore import QMetaType
            field_map = {f.name(): f for f in fields}
            fields_to_process = [
                f for f in fields_to_process
                if f in field_map and field_map[f].type() == QMetaType.Type.QString
            ]

        # Удаляем исключенные поля
        fields_to_process = [f for f in fields_to_process if f not in exclude_fields]

        if not fields_to_process:
            log_debug(f"Msm_13_2_AttributeProcessor: Нет текстовых полей для обработки в слое {layer_name}")
            return

        # Проверяем наличие полей Обременения/Арендаторы для связанной обработки
        field_names = [f.name() for f in fields]
        has_encumbrances = 'Обременения' in field_names
        has_tenants = 'Арендаторы' in field_names
        can_simplify_rent = has_encumbrances and has_tenants

        layer.startEditing()
        processed_count = 0
        capitalized_count = 0
        rent_simplified_count = 0

        for feature in layer.getFeatures():
            feature_modified = False

            # ЭТАП 0: Дедупликация и упрощение множественных арендаторов-физлиц
            # Выполняется ДО обработки отдельных полей, так как требует синхронной обработки пар
            if can_simplify_rent:
                enc_value = feature['Обременения']
                tenant_value = feature['Арендаторы']

                # Преобразуем в строки для обработки
                enc_str = str(enc_value) if enc_value is not None else None
                tenant_str = str(tenant_value) if tenant_value is not None else None

                if enc_str and tenant_str and enc_str != '-' and tenant_str != '-':
                    # ШАГ 0.1: Дедупликация пар (удаление полных дубликатов)
                    # Пример: "Аренда / Сервитут / Аренда / Сервитут" + "Физ1 / ООО / Физ1 / ООО"
                    #      -> "Аренда / Сервитут" + "Физ1 / ООО"
                    enc_str, tenant_str = self.deduplicate_encumbrances_and_tenants(enc_str, tenant_str)

                    # ШАГ 0.2: Упрощение физлиц (множественные "Физическое лицо" -> одно)
                    new_enc, new_tenant = self.simplify_rent_individuals(enc_str, tenant_str)

                    orig_enc = str(feature['Обременения']) if feature['Обременения'] is not None else None
                    orig_tenant = str(feature['Арендаторы']) if feature['Арендаторы'] is not None else None

                    if new_enc != orig_enc or new_tenant != orig_tenant:
                        feature['Обременения'] = new_enc
                        feature['Арендаторы'] = new_tenant
                        feature_modified = True
                        rent_simplified_count += 1

            for field_name in fields_to_process:
                value = feature[field_name]
                new_value = value
                field_modified = False

                # ЭТАП 1: Обработка NULL и пустых значений
                # NULL из qgis.core соответствует QVariant NULL (возвращается при чтении из GPKG)
                is_null = (
                    value is None or
                    value == NULL or
                    value == '' or
                    (isinstance(value, str) and value.strip() == '')
                )
                if is_null:
                    # Для полей из NULL_REPLACEMENTS используем специальный текст
                    # НО проверяем исключения:
                    # 1. По имени слоя (например, "НГС" в названии)
                    # 2. По формату КН в объекте (XX:XX:XXXXXX = НГС)
                    # 3. Для полей из NGS_FILLME_FIELDS у НГС ставим "ЗАПОЛНИ!"
                    is_excluded_by_layer = self._is_field_excluded_from_null_replacement(field_name, layer_name)
                    is_excluded_by_kn = self._is_field_excluded_by_kn(field_name, feature)
                    is_fillme_by_kn = self._is_field_fillme_by_kn(field_name, feature)

                    if is_fillme_by_kn:
                        # НГС - планируемые поля требуют ручного заполнения
                        new_value = self.FILLME_PLACEHOLDER
                    elif field_name in self.NULL_REPLACEMENTS and not is_excluded_by_layer and not is_excluded_by_kn:
                        new_value = self.NULL_REPLACEMENTS[field_name]
                    else:
                        new_value = '-'
                    field_modified = True

                # ЭТАП 2: Капитализация (для непустых значений если включена)
                if capitalize and isinstance(new_value, str) and new_value not in ['-', '', None]:
                    capitalized_value = self.capitalize_field(new_value)
                    if capitalized_value != new_value:
                        new_value = capitalized_value
                        field_modified = True
                        capitalized_count += 1

                # ЭТАП 3: Нормализация разделителей (; → /)
                # Заменяем точки с запятой на слэши для единообразия форматирования
                if isinstance(new_value, str) and ';' in new_value:
                    normalized_value = re.sub(r'\s*;\s*', ' / ', new_value)
                    if normalized_value != new_value:
                        new_value = normalized_value
                        field_modified = True

                # ЭТАП 4: Сокращение организационно-правовых форм юрлиц
                # Применяется к полям Собственники, Арендаторы и подобным
                if isinstance(new_value, str) and new_value not in ['-', '', None]:
                    abbreviated_value = self._abbreviate_legal_forms(new_value)
                    if abbreviated_value != new_value:
                        new_value = abbreviated_value
                        field_modified = True

                # Применяем изменения к полю
                if field_modified:
                    feature[field_name] = new_value
                    feature_modified = True

            # Обновляем feature если хотя бы одно поле изменилось
            if feature_modified:
                layer.updateFeature(feature)
                processed_count += 1

        layer.commitChanges()

        if processed_count > 0:
            details = []
            if capitalize and capitalized_count > 0:
                details.append(f"капитализировано: {capitalized_count}")
            if rent_simplified_count > 0:
                details.append(f"упрощено арендаторов: {rent_simplified_count}")
            details_str = f" ({', '.join(details)})" if details else ""
            log_debug(f"Msm_13_2_AttributeProcessor: Обработано {processed_count} объектов в слое {layer_name}{details_str}")
        else:
            log_debug(f"Msm_13_2_AttributeProcessor: Все значения уже корректны в слое {layer_name}")
