# -*- coding: utf-8 -*-
"""
Msm_25_2 - Классификатор прав на земельные участки

Определяет в какой слой L_1_11_* должен попасть объект
на основе полей "Права", "__Форма_тех" (транзитная форма собственности),
"Обременения".

Вариант B (§4/§5.5): классификатор читает ТРАНЗИТНУЮ ФОРМУ (__Форма_тех),
а НЕ "Собственники" (та теперь = ИМЯ правообладателя, в классификации не
участвует). Параметр `owners_value` в методах сохранён по имени, но несёт
значение формы (см. classify_feature / get_field_names).

Объект может попасть в несколько слоёв:
- Один основной (по праву собственности)
- Дополнительные (по обременениям)

Перенесено из Fsm_2_3_2_1_rights_classifier.py
"""

from collections import Counter
from typing import Dict, List, Tuple, Optional

from Daman_QGIS.utils import log_info, log_warning, log_error, normalize_for_classification

# Lazy import для избежания циклических зависимостей
def _get_reference_managers():
    from Daman_QGIS.managers import get_reference_managers
    return get_reference_managers()


class Msm_25_2_RightsClassifier:
    """Классификатор прав на земельные участки"""

    # Разделитель для множественных значений в полях
    FIELD_SEPARATOR = " / "

    # Правила классификации (классы A/B) грузятся из справочника
    # Base_rights_classification.json через RightsClassificationManager
    # (BaseReferenceLoader, кэш на сессию), сортируются по rule_id. Хардкод-словари
    # PRIMARY/ADDITIONAL/OWNER_FALLBACK вынесены в справочник (рефакторинг фазы-2,
    # PLAN_rights_classification_registry). Владелец отлаживает маппинг в Excel.
    # Класс A (record_kind='right') — основной слой по паре (право, форма);
    # класс B (record_kind ∈ {'semi_right','encumbrance'}) — доп-слои.

    # Слой для неопознанных участков
    UNKNOWN_LAYER = "L_1_11_6_Права_ЗУ_Свед_нет"

    # Имя транзитного поля формы собственности (Вариант B): читается вместо
    # "Собственники" (та теперь = ИМЯ правообладателя). Форма несёт словарь
    # классификатора (Частная/Муниципальная/...). Исключено из экспорта.
    FORM_FIELD_NAME = "__Форма_тех"

    # Род-нормализация формы (K1, §5.5): НСПД `ownership_type` даёт форму в
    # среднем роде ("Частное"), словарь классификатора — в женском ("Частная").
    # Единый словарь на входе в поле, БЕЗ плодения ключей классификатора.
    # Применяется к формам no-выписка ЗУ (форма из НСПД); формы выписки уже
    # приходят из ветки holder в правильном роде (§3).
    FORM_NORMALIZATION: Dict[str, str] = {
        "Частное": "Частная",
        "Государственное": "Государственная",
        "Муниципальное": "Муниципальная",
    }

    def __init__(self):
        """Инициализация классификатора"""
        self._rights_layers_config: Optional[List[Dict]] = None
        self._unclassified: Counter = Counter()
        # Кэш правил справочника на время жизни экземпляра (один прогон
        # распределения). JSON и так кэшируется на уровне BaseReferenceLoader;
        # здесь — чтобы не пересортировывать/не переопрашивать менеджер на каждой
        # фиче (classify_feature зовётся в цикле по всем ЗУ выборки).
        self._rules_cache: Optional[List[Dict]] = None

    def get_rights_layers_config(self) -> List[Dict]:
        """
        Получить конфигурацию слоёв прав из Base_layers.json

        Returns:
            List[Dict]: Список данных о слоях прав
        """
        if self._rights_layers_config is not None:
            return self._rights_layers_config

        ref_managers = _get_reference_managers()
        layer_ref_manager = ref_managers.layer

        if not layer_ref_manager:
            log_warning("Msm_25_2: Не удалось получить layer reference manager")
            return []

        rights_layers = []
        all_layers = layer_ref_manager.get_base_layers()

        for layer_data in all_layers:
            group = layer_data.get('group', '')
            if group == 'Права':
                rights_layers.append(layer_data)

        self._rights_layers_config = rights_layers
        log_info(f"Msm_25_2: Загружена конфигурация для {len(rights_layers)} слоёв прав")

        return rights_layers

    def _get_rules(self) -> List[Dict]:
        """Получить правила справочника Base_rights_classification.json (кэш экземпляра).

        Правила отсортированы по rule_id (приоритет). Возвращает пустой список
        при недоступности менеджера — fail-closed: без справочника primary/
        additional не определяются, объект уходит в Свед_нет (сетевой сбой —
        политика проекта, см. BaseReferenceLoader).
        """
        if self._rules_cache is not None:
            return self._rules_cache

        ref_managers = _get_reference_managers()
        rights_ref_manager = getattr(ref_managers, 'rights_classification', None)

        if rights_ref_manager is None:
            # Fail-closed + ГРОМКО (канон-8): без менеджера все ЗУ уйдут в Свед_нет.
            log_error(
                "Msm_25_2: rights_classification reference manager недоступен — "
                "все ЗУ уйдут в Свед_нет (fail-closed). Классификация прав не работает."
            )
            self._rules_cache = []
            return self._rules_cache

        rules = rights_ref_manager.get_rules()
        if not rules:
            # Пустой справочник при доступном менеджере = сетевой / integrity сбой
            # (на валидных данных правила всегда есть). Fail-closed, но ГРОМКО
            # (канон-8): иначе тихий обвал всей выборки в Свед_нет неотличим от
            # штатного «нет данных». Кэшируем даже пустое — иначе _get_rules зовётся
            # на каждую фичу (primary+additional) и BaseReferenceLoader не кэширует
            # неудачу → сотни retry-циклов (сетевой хаммер). Оператор видит log_error
            # и перезапускает распределение.
            log_error(
                "Msm_25_2: справочник классификации прав ПУСТ (сетевой сбой / "
                "integrity) — все ЗУ уйдут в Свед_нет (fail-closed). Перезапустите "
                "распределение после восстановления связи."
            )
        else:
            log_info(f"Msm_25_2: Загружено {len(rules)} правил классификации прав")
        self._rules_cache = rules
        return self._rules_cache

    def _rules_of_kind(self, *kinds: str) -> List[Dict]:
        """Правила заданных record_kind, в порядке rule_id."""
        allowed = set(kinds)
        return [r for r in self._get_rules() if r.get('record_kind') in allowed]

    @staticmethod
    def _value_matches(data_value: str, match_value: str, match_mode: str) -> bool:
        """Сравнение значения данных с ключом правила (нормализация С ОБЕИХ сторон).

        `normalize_for_classification` убирает невидимые символы НСПД (\\xa0,
        zero-width, юникод-тире) — обязательная гоча проекта. Режимы:
        - 'contains' — подстрока, регистронезависимо (casefold): ключ «аренд»
          ловит «Аренда», «федеральн» ловит «Федеральное». Допустим ТОЛЬКО когда
          все строки-надмножества ключа целят в тот же слой (§7 R1 плана).
        - 'exact' (по умолчанию) — точное равенство после нормализации.
        """
        dv = normalize_for_classification(data_value)
        mv = normalize_for_classification(match_value)
        if match_mode == 'contains':
            return bool(mv) and mv.casefold() in dv.casefold()
        return dv.casefold() == mv.casefold()

    def _primary_rule_matches(self, rule: Dict, right: str, form: str) -> bool:
        """Проверка совпадения A-правила (record_kind='right') с парой (право, форма).

        match_value сверяется с ПРАВОМ по match_mode правила; условие form —
        всегда exact (строка-синоним формы); пустой form = любая форма (долевая/
        совместная, rule 11-12).
        """
        if not self._value_matches(right, rule.get('match_value', ''),
                                   rule.get('match_mode', 'exact')):
            return False
        rule_form = rule.get('form')
        if not rule_form:
            return True
        return self._value_matches(form, rule_form, 'exact')

    @staticmethod
    def parse_field(value: Optional[str]) -> List[str]:
        """
        Парсинг поля с множественными значениями

        Разделяет строку по разделителю " / " и очищает пробелы

        Args:
            value: Значение поля (может быть None или пустым)

        Returns:
            List[str]: Список значений (пустой если value=None)

        Examples:
            >>> parse_field("Собственность / Постоянное (бессрочное) пользование")
            ["Собственность", "Постоянное (бессрочное) пользование"]

            >>> parse_field("Собственность")
            ["Собственность"]

            >>> parse_field(None)
            []

            >>> parse_field("-")
            []
        """
        if not value:
            return []

        # Очищаем строку
        value = value.strip()

        # Проверяем на пустую строку или "-"
        if not value or value == "-":
            return []

        # Разделяем по " / " и очищаем
        parts = [part.strip() for part in value.split(Msm_25_2_RightsClassifier.FIELD_SEPARATOR)]

        # Фильтруем пустые значения и "-"
        return [part for part in parts if part and part != "-"]

    def classify_primary_layer(
        self,
        rights_list: List[str],
        forms_list: List[str]
    ) -> Optional[str]:
        """
        Определение основного слоя по ПОЗИЦИОННОЙ паре (право[i], форма[i]).

        Основной слой определяет ТОЛЬКО право собственности (§2 плана): A-правила
        справочника (record_kind='right') — виды собственности + «Сведения
        отсутствуют» × форма. Полу-права (ПБП и т.п.) и обременения основной слой
        НЕ определяют (их A-пара отсутствует → не дают кандидата) — они дают
        доп-слои через classify_additional_layers.

        Алгоритм (§5.2): строим позиционные пары (право[i], форма[i]); выбор —
        первое совпавшее A-правило в порядке rule_id (приоритет РФ>Суб>Мун>...
        задан нумерацией строк Excel). Guard рассинхрона длин осей (Права per
        right_record, форма per right_holder — мультихолдер даёт разную кратность)
        → log_warning + откат на cartesian. На корпусе Чижика 0 мультихолдеров
        (позиционная пара корректна на всех реальных данных); guard страхует
        гипотетический будущий мультихолдер (OWNER-3, R5).

        Args:
            rights_list: Список прав из поля "Права"
            forms_list: Список форм собственности из "__Форма_тех" (уже
                нормализованы вызывающим classify_feature)

        Returns:
            Optional[str]: full_name слоя или None если A-пара не найдена
        """
        a_rules = self._rules_of_kind('right')
        if not a_rules or not rights_list or not forms_list:
            return None

        # Кандидатные пары: позиционные при равной кратности осей, иначе cartesian
        if len(rights_list) == len(forms_list):
            pairs = list(zip(rights_list, forms_list))
        else:
            log_warning(
                f"Msm_25_2: мультихолдерная запись "
                f"(прав={len(rights_list)} != форм={len(forms_list)}) → откат на "
                f"cartesian, основной слой может быть недетерминирован "
                f"(права={rights_list}, формы={forms_list})"
            )
            pairs = [(right, form) for right in rights_list for form in forms_list]

        # Первое A-правило в порядке rule_id, совпавшее с любой парой-кандидатом
        for rule in a_rules:
            for right, form in pairs:
                if self._primary_rule_matches(rule, right, form):
                    return rule.get('target_layer')

        return None

    def classify_additional_layers(
        self,
        rights_list: List[str],
        encumbrances_list: List[str]
    ) -> List[str]:
        """
        Определение дополнительных слоёв для дублирования объекта

        Применяет B-правила справочника (record_kind ∈ {'semi_right',
        'encumbrance'}, match_mode exact/contains) к ОБЪЕДИНЕНИЮ полей
        "Права" + "Обременения" (OWNER-2: аренда из любого поля → доп-слой).
        Правило заведено ТОЛЬКО при наличии target_layer (ЗОУИТ-стиль, OWNER-1):
        класс без слоя доп-слой не даёт. Итерация по rule_id (порядок членства
        на дублирование не влияет — важна принадлежность, не порядок).

        Args:
            rights_list: Список прав из поля "Права"
            encumbrances_list: Список обременений из поля "Обременения"

        Returns:
            List[str]: Список full_name слоёв для дублирования
        """
        b_rules = self._rules_of_kind('semi_right', 'encumbrance')
        if not b_rules:
            return []

        all_values = rights_list + encumbrances_list
        additional_layers: List[str] = []

        for rule in b_rules:
            target_layer = rule.get('target_layer')
            if not target_layer or target_layer in additional_layers:
                continue
            match_value = rule.get('match_value', '')
            match_mode = rule.get('match_mode', 'exact')
            for value in all_values:
                if self._value_matches(value, match_value, match_mode):
                    additional_layers.append(target_layer)
                    break

        return additional_layers

    def classify_feature(
        self,
        rights_value: Optional[str],
        owners_value: Optional[str],
        encumbrances_value: Optional[str]
    ) -> Tuple[Optional[str], List[str]]:
        """
        Полная классификация объекта по правам, форме собственности и обременениям

        Args:
            rights_value: Значение поля "Права"
            owners_value: Значение поля "__Форма_тех" (транзитная форма
                собственности; параметр назван owners_value по историческому
                контракту get_field_names, но несёт форму — Вариант B)
            encumbrances_value: Значение поля "Обременения"

        Returns:
            Tuple[Optional[str], List[str]]:
                - primary_layer: full_name основного слоя (None если A-пара не
                  найдена → распределитель шлёт в Свед_нет)
                - additional_layers: список full_name дополнительных слоёв

        Examples (позиционная пара право[i] ↔ форма[i], primary — только
        собственность):
            >>> classify_feature(
                "Постоянное (бессрочное) пользование / Собственность",
                "Частная / Российская Федерация",
                None
            )
            ("L_1_11_1_Права_ЗУ_РФ", ["L_1_11_7_Права_ЗУ_ПБП"])
            # (ПБП,Частная) не A-пара; (Собственность,РФ) → L_1_11_1; ПБП → доп-слой

            >>> classify_feature("Собственность", "Частная", "Сервитут (Право)")
            ("L_1_11_4_Права_ЗУ_Частное", ["L_1_11_13_Права_ЗУ_Сервитут"])

            >>> classify_feature("-", "-", "-")
            ("L_1_11_6_Права_ЗУ_Свед_нет", [])
        """
        # Проверяем на отсутствие данных ДО парсинга
        def is_no_data(value: Optional[str]) -> bool:
            """Проверка что поле содержит '-' (нет данных)"""
            if not value:
                return True
            return value.strip() == "-"

        # Если хотя бы одно из ключевых полей = "-" -> в "Свед_нет"
        if is_no_data(rights_value) or is_no_data(owners_value):
            return (self.UNKNOWN_LAYER, [])

        # Парсим поля
        rights_list = self.parse_field(rights_value)
        # owners_value здесь = ТРАНЗИТНАЯ ФОРМА (__Форма_тех), не имя правообладателя.
        # Нормализуем: невидимые символы НСПД (\xa0 и др.) + род ("Частное"->"Частная").
        forms_list = [self._normalize_form(f) for f in self.parse_field(owners_value)]
        encumbrances_list = self.parse_field(encumbrances_value)

        # Определяем основной слой (позиционные пары право[i] ↔ форма[i])
        primary_layer = self.classify_primary_layer(rights_list, forms_list)

        # Определяем дополнительные слои
        additional_layers = self.classify_additional_layers(rights_list, encumbrances_list)

        # Считаем неклассифицированные для сводки
        if not primary_layer:
            key = (tuple(rights_list), tuple(forms_list))
            self._unclassified[key] += 1

        return primary_layer, additional_layers

    def log_unclassified_summary(self) -> None:
        """Вывести сводку по неклассифицированным объектам и сбросить счётчик"""
        if not self._unclassified:
            return

        total = sum(self._unclassified.values())
        parts = [f"Msm_25_2: Не классифицировано {total} объектов:"]
        for (rights, owners), count in self._unclassified.most_common():
            parts.append(f"  {list(rights)} + {list(owners)}: {count} шт.")
        log_warning("\n".join(parts))
        self._unclassified.clear()

    @classmethod
    def _normalize_form(cls, form_value: str) -> str:
        """Нормализация значения формы собственности для классификатора.

        Двухступенчато (K1, §5.5):
        1. `normalize_for_classification` — убирает невидимые символы НСПД
           (`\\xa0`, zero-width, юникод-тире), которые может нести
           `ownership_type` из WFS → иначе точное `==` в словаре промахнётся.
        2. Род-нормализация ("Частное" -> "Частная") — НСПД даёт форму в ср.
           роде, словарь классификатора — в ж. роде.

        Args:
            form_value: Значение формы (один токен из parse_field)

        Returns:
            Нормализованное значение формы
        """
        normalized = normalize_for_classification(form_value)
        return cls.FORM_NORMALIZATION.get(normalized, normalized)

    def get_field_names(self) -> Tuple[str, str, str]:
        """
        Получить имена полей для классификации

        ВАЖНО (Вариант B): второе поле — ТРАНЗИТНАЯ ФОРМА (__Форма_тех),
        а НЕ "Собственники". Форма несёт словарь классификатора; "Собственники"
        переосмыслено в чистое имя правообладателя и в классификации не участвует.

        Returns:
            Tuple[str, str, str]: (rights_field, form_field, encumbrances_field)
        """
        return ("Права", self.FORM_FIELD_NAME, "Обременения")
