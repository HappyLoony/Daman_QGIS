# -*- coding: utf-8 -*-
"""
Msm_21_1_ExistingVRIValidator - Валидатор существующего ВРИ

НАЗНАЧЕНИЕ:
    Мягкая валидация и сравнение existing_vri (из Выборка_ЗУ) с zpr_vri (из ЗПР).
    Позволяет сохранить оригинальное значение ВРИ если оно соответствует ЗПР.

ФОРМАТЫ existing_vri (из ЕГРН):
    - "Отдых (рекреация)" (только имя)
    - "5.0" (только код)
    - "код 5.0" (код с префиксом)
    - "(код 5.0) Отдых (рекреация)" (перевёрнутый порядок)
    - "Отдых (рекреация) (код 5.0)" (стандартный full_name)
    - "Благоустройство территории" vs "Благоустройство территории (код 12.0.2)"

ЛОГИКА:
    1. Парсинг existing_vri -> извлечение code и/или name
    2. Soft validation: проверка что хотя бы code ИЛИ name есть в VRI.json
    3. Сравнение с zpr_vri: совпадение по code ИЛИ name = юридически одинаковые
    4. Если совпадают -> сохраняем existing_vri как есть в План_ВРИ
    5. Если не совпадают -> используем zpr_vri (стандартная замена)

ИСПОЛЬЗОВАНИЕ:
    Вызывается из Msm_26_4_CuttingEngine после генерации features_data,
    перед записью в слой.
"""

import re
from typing import Dict, List, Optional, Tuple, Any

from Daman_QGIS.utils import log_info, log_warning, log_error


class Msm_21_1_ExistingVRIValidator:
    """
    Валидатор существующего ВРИ для сравнения с ВРИ из ЗПР

    Обеспечивает мягкую валидацию форматов ВРИ из ЕГРН и определяет,
    нужно ли заменять existing_vri на zpr_vri.
    """

    # Паттерны для парсинга ВРИ
    # Код: "5.0", "12.0.2", "3.1.1"
    CODE_PATTERN = re.compile(r'(\d+(?:\.\d+)*)')
    # Код с префиксом: "код 5.0", "(код 5.0)"
    CODE_WITH_PREFIX_PATTERN = re.compile(r'\(?код\s+(\d+(?:\.\d+)*)\)?', re.IGNORECASE)
    # Full name формат: "Название (код X.Y)"
    FULL_NAME_PATTERN = re.compile(r'^(.+?)\s*\(код\s+(\d+(?:\.\d+)*)\)$', re.IGNORECASE)
    # Перевёрнутый формат: "(код X.Y) Название"
    REVERSED_PATTERN = re.compile(r'^\(код\s+(\d+(?:\.\d+)*)\)\s*(.+)$', re.IGNORECASE)

    def __init__(self, vri_data: List[Dict]):
        """
        Инициализация валидатора

        Args:
            vri_data: Список словарей VRI из VRI.json
                      [{code, name, full_name, is_public_territory}, ...]
        """
        self._vri_data = vri_data

        # Индексы для быстрого поиска
        self._by_code: Dict[str, Dict] = {}
        self._by_name: Dict[str, Dict] = {}
        self._by_full_name: Dict[str, Dict] = {}

        self._build_indexes()

    def _build_indexes(self):
        """Построение индексов для быстрого поиска"""
        for vri in self._vri_data:
            code = vri.get('code', '').strip()
            name = vri.get('name', '').strip()
            full_name = vri.get('full_name', '').strip()

            if code:
                self._by_code[code] = vri
            if name:
                # Нормализуем имя для поиска (нижний регистр, без лишних пробелов)
                self._by_name[name.lower()] = vri
            if full_name:
                self._by_full_name[full_name.lower()] = vri

        log_info(f"Msm_21_1: Индексы построены - "
                f"{len(self._by_code)} кодов, {len(self._by_name)} имён")

    def parse_vri_value(self, value: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Парсинг значения ВРИ для извлечения кода и имени

        Args:
            value: Строка ВРИ в любом формате

        Returns:
            Tuple[code, name]: Извлечённые код и имя (могут быть None)
        """
        if not value or not isinstance(value, str):
            return None, None

        value = value.strip()
        if not value or value == '-':
            return None, None

        code = None
        name = None

        # Пробуем full_name формат: "Название (код X.Y)"
        match = self.FULL_NAME_PATTERN.match(value)
        if match:
            name = match.group(1).strip()
            code = match.group(2)
            return code, name

        # Пробуем перевёрнутый формат: "(код X.Y) Название"
        match = self.REVERSED_PATTERN.match(value)
        if match:
            code = match.group(1)
            name = match.group(2).strip()
            return code, name

        # Пробуем код с префиксом: "код 5.0", "(код 5.0)"
        match = self.CODE_WITH_PREFIX_PATTERN.search(value)
        if match:
            code = match.group(1)
            # Имя может быть остатком строки
            remaining = self.CODE_WITH_PREFIX_PATTERN.sub('', value).strip()
            if remaining:
                name = remaining
            return code, name

        # Пробуем только код: "5.0", "12.0.2"
        if self.CODE_PATTERN.fullmatch(value):
            return value, None

        # Всё остальное - считаем именем
        return None, value

    def soft_validate(self, value: str) -> Tuple[bool, Optional[Dict]]:
        """
        Мягкая валидация ВРИ по базе данных

        Проверяет что хотя бы код ИЛИ имя соответствуют записи в VRI.json.

        Args:
            value: Значение ВРИ для проверки

        Returns:
            Tuple[is_valid, vri_data]:
                - is_valid: True если ВРИ валиден (найден по коду или имени)
                - vri_data: Найденная запись VRI или None
        """
        code, name = self.parse_vri_value(value)

        # Поиск по коду (приоритет)
        if code and code in self._by_code:
            return True, self._by_code[code]

        # Поиск по имени (нечувствительно к регистру)
        if name:
            name_lower = name.lower()
            if name_lower in self._by_name:
                return True, self._by_name[name_lower]

        # Поиск по full_name (на случай если передали полное значение)
        value_lower = value.strip().lower()
        if value_lower in self._by_full_name:
            return True, self._by_full_name[value_lower]

        return False, None

    def strict_validate(self, value: str) -> Tuple[bool, Optional[Dict]]:
        """
        Строгая валидация ВРИ - точное соответствие full_name или коду

        Args:
            value: Значение ВРИ для проверки

        Returns:
            Tuple[is_valid, vri_data]
        """
        if not value or not isinstance(value, str):
            return False, None

        value_stripped = value.strip()
        if not value_stripped or value_stripped == '-':
            return False, None

        # Точное соответствие full_name
        value_lower = value_stripped.lower()
        if value_lower in self._by_full_name:
            return True, self._by_full_name[value_lower]

        # Точное соответствие коду
        if value_stripped in self._by_code:
            return True, self._by_code[value_stripped]

        return False, None

    def _normalize_vri_to_code(self, vri_part: str) -> Optional[str]:
        """
        Нормализует часть ВРИ к коду для сравнения множеств

        Args:
            vri_part: Одно значение ВРИ (код, имя или full_name)

        Returns:
            Код ВРИ или None если не удалось определить
        """
        code, name = self.parse_vri_value(vri_part)

        # Если есть код - возвращаем его
        if code:
            return code

        # Если только имя - ищем код в базе
        if name:
            vri_entry = self._by_name.get(name.lower())
            if vri_entry:
                return vri_entry.get('code')

        return None

    def _split_multiple_vri(self, vri_value: str) -> List[str]:
        """
        Разбивает строку с множественными ВРИ по разделителю ','

        Args:
            vri_value: Строка ВРИ (может содержать несколько через запятую)

        Returns:
            Список отдельных ВРИ
        """
        if not vri_value:
            return []

        # Разбиваем по запятой и очищаем
        parts = [p.strip() for p in vri_value.split(',')]
        return [p for p in parts if p and p != '-']

    def matches_zpr_vri(
        self,
        existing_vri: str,
        zpr_vri: str
    ) -> Tuple[bool, str]:
        """
        Проверка соответствия existing_vri и zpr_vri

        Поддерживает множественные ВРИ через запятую.
        Сравнение по множествам кодов - порядок не важен.

        Примеры:
        - "5.0" == "Отдых (рекреация) (код 5.0)" -> True
        - "Отдых, Благоустройство" == "5.0, 12.0.2" -> True (если коды соответствуют)
        - "Отдых, Благоустройство" == "Благоустройство" -> False (разные множества)

        Args:
            existing_vri: ВРИ из Выборка_ЗУ (может содержать несколько через ',')
            zpr_vri: ВРИ из ЗПР (может содержать несколько через ',')

        Returns:
            Tuple[matches, reason]:
                - matches: True если множества ВРИ совпадают
                - reason: Описание причины совпадения/несовпадения
        """
        # Разбиваем на части
        existing_parts = self._split_multiple_vri(existing_vri)
        zpr_parts = self._split_multiple_vri(zpr_vri)

        # Пустые значения не совпадают
        if not existing_parts or not zpr_parts:
            return False, "empty_vri"

        # Нормализуем к кодам
        existing_codes = set()
        for part in existing_parts:
            code = self._normalize_vri_to_code(part)
            if code:
                existing_codes.add(code)

        zpr_codes = set()
        for part in zpr_parts:
            code = self._normalize_vri_to_code(part)
            if code:
                zpr_codes.add(code)

        # Если не удалось нормализовать - fallback на строковое сравнение
        if not existing_codes or not zpr_codes:
            # Сравниваем как множества строк (нижний регистр)
            existing_names = {p.lower() for p in existing_parts}
            zpr_names = {p.lower() for p in zpr_parts}

            if existing_names == zpr_names:
                return True, f"match_by_names:{existing_names}"
            return False, f"no_match_names:existing={existing_names},zpr={zpr_names}"

        # Сравниваем множества кодов
        if existing_codes == zpr_codes:
            return True, f"match_by_codes:{sorted(existing_codes)}"

        return False, f"no_match_codes:existing={sorted(existing_codes)},zpr={sorted(zpr_codes)}"

    def validate_and_decide(
        self,
        existing_vri: Optional[str],
        zpr_vri: Optional[str]
    ) -> Tuple[str, bool, str]:
        """
        Валидация и принятие решения о значении План_ВРИ

        Логика:
        1. Если existing_vri пустой/None -> используем zpr_vri
        2. Если existing_vri не проходит soft validation -> используем zpr_vri
        3. Если existing_vri и zpr_vri совпадают -> сохраняем existing_vri как есть
        4. Иначе -> используем zpr_vri

        Args:
            existing_vri: ВРИ из Выборка_ЗУ (может быть None)
            zpr_vri: ВРИ из ЗПР (обычно full_name)

        Returns:
            Tuple[plan_vri, kept_existing, reason]:
                - plan_vri: Значение для поля План_ВРИ
                - kept_existing: True если сохранили existing_vri
                - reason: Причина решения для логирования
        """
        # Fallback если zpr_vri пустой
        if not zpr_vri or zpr_vri == '-':
            if existing_vri and existing_vri != '-':
                return existing_vri, True, "zpr_empty_use_existing"
            return "-", False, "both_empty"

        # existing_vri пустой - используем zpr_vri
        if not existing_vri or existing_vri == '-':
            return zpr_vri, False, "existing_empty"

        # Soft validation existing_vri
        is_valid, vri_data = self.soft_validate(existing_vri)
        if not is_valid:
            return zpr_vri, False, f"soft_validation_failed:{existing_vri}"

        # Сравнение с zpr_vri
        matches, match_reason = self.matches_zpr_vri(existing_vri, zpr_vri)
        if matches:
            # Сохраняем existing_vri как есть
            return existing_vri, True, match_reason

        # Не совпадают - используем zpr_vri
        return zpr_vri, False, match_reason

    def validate_batch(
        self,
        features_data: List[Dict[str, Any]],
        existing_vri_field: str = 'ВРИ',
        zpr_vri_key: str = 'zpr_vri',
        plan_vri_field: str = 'План_ВРИ'
    ) -> List[Dict[str, Any]]:
        """
        Пакетная валидация и обновление План_ВРИ

        Args:
            features_data: Список features с 'attributes' и 'zpr_vri'
            existing_vri_field: Имя поля с existing_vri в attributes
            zpr_vri_key: Ключ с zpr_vri в item (не в attributes)
            plan_vri_field: Имя поля для записи результата

        Returns:
            Обновлённый features_data
        """
        if not features_data:
            return features_data

        stats = {
            'total': 0,
            'kept_existing': 0,
            'used_zpr': 0,
            'soft_passed_strict_failed': 0  # Интересные случаи для логирования
        }

        for item in features_data:
            attrs = item.get('attributes', {})
            existing_vri = attrs.get(existing_vri_field)
            zpr_vri = item.get(zpr_vri_key)

            stats['total'] += 1

            plan_vri, kept_existing, reason = self.validate_and_decide(
                existing_vri, zpr_vri
            )

            attrs[plan_vri_field] = plan_vri

            if kept_existing:
                stats['kept_existing'] += 1

                # Проверяем интересный случай: soft прошёл, strict нет
                strict_valid, _ = self.strict_validate(existing_vri)
                if not strict_valid:
                    stats['soft_passed_strict_failed'] += 1
                    log_info(f"Msm_21_1: ВРИ '{existing_vri}' сохранён "
                            f"(soft validation, {reason})")
            else:
                stats['used_zpr'] += 1

        log_info(f"Msm_21_1: Валидация завершена - "
                f"всего {stats['total']}, "
                f"сохранено existing: {stats['kept_existing']}, "
                f"заменено на ZPR: {stats['used_zpr']}, "
                f"soft!=strict: {stats['soft_passed_strict_failed']}")

        return features_data
