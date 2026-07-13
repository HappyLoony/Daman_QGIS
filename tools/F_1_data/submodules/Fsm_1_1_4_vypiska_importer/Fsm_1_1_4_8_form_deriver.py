# -*- coding: utf-8 -*-
"""
Fsm_1_1_4_8 - Деривация формы собственности из ветки right_holder (транзитное __Форма_тех)

НАЗНАЧЕНИЕ:
    Форма собственности выписки ЕГРН — это ДИСКРИМИНАТОР ветки right_holder
    (XSD-подтверждено: RightHolderOut = xsd:choice { public_formation |
    individual | legal_entity | another }; PublicFormationType = xsd:choice
    { foreign_public | union_state | russia | subject_of_rf | municipality }).

    Штатный `Msm_4_17._extract_array_value` делает first-match + break и хранит
    ТОЛЬКО значение (имя правообладателя), индекс сработавшей ветки НЕ сохраняет,
    → форму им получить нельзя. Здесь — выделенный экстрактор присутствия ветки.

РЕЗУЛЬТАТ:
    Значение поля `__Форма_тех` = формы всех правообладателей, `" / "`-joined
    (одна форма на right_holder, в порядке holder). Разделитель СРАЗУ `" / "`
    (транзитное поле исключено из finalize, конверсия `;`->`/` его не тронет —
    иначе `parse_field` классификатора даст слипшийся токен, K3).

    Форма читается классификатором Msm_25_2 на слое выборки. Классификатор
    делает ДЕКАРТОВ перебор rights x forms (позицию НЕ читает) → достаточно,
    чтобы форма приоритетного права ПРИСУТСТВОВАЛА в списке.

КАРТА ВЕТКА -> ФОРМА (§3 плана, значения = ключи словаря классификатора):
    individual                          -> "Частная"
    legal_entity                        -> "Частная"
    public_formation/.../municipality   -> "Муниципальная"
    public_formation/.../subject_of_rf  -> "Государственная субъекта РФ"
    public_formation/.../russia         -> "Российская Федерация"
    public_formation/.../foreign_public -> "Сведения отсутствуют" (K2, решение 3)
    public_formation/.../union_state    -> "Сведения отсутствуют" (K2, решение 3)
    undefined                           -> "Сведения отсутствуют" (K2, решение 3)

    Все Свед_нет-ветки дают "Сведения отсутствуют" — штатно классифицируется
    в L_1_11_6, НЕ доводится до None-хендлера.
"""

from typing import List, Optional
from xml.etree.ElementTree import Element

from Daman_QGIS.utils import log_warning

# Разделитель, который ждёт классификатор Msm_25_2.parse_field на слое выборки
FORM_SEPARATOR = " / "

# Значение формы для нераспознанных/экзотических веток (K2)
FORM_UNKNOWN = "Сведения отсутствуют"

# XPath (относительно right_holder) веток public_formation -> форма.
# Проверяются по порядку; первое присутствие определяет форму holder.
_PUBLIC_FORMATION_BRANCHES = [
    ("public_formation/public_formation_type/municipality", "Муниципальная"),
    ("public_formation/public_formation_type/subject_of_rf", "Государственная субъекта РФ"),
    ("public_formation/public_formation_type/russia", "Российская Федерация"),
    ("public_formation/public_formation_type/foreign_public", FORM_UNKNOWN),
    ("public_formation/public_formation_type/union_state", FORM_UNKNOWN),
]

# Корневой контейнер правообладателей (совпадает с xml_xpath_root поля
# "Собственники" в Base_field_mapping_EGRN.json)
_RIGHT_HOLDER_ROOT = "right_records/right_record/right_holders/right_holder"


def _classify_holder_branch(right_holder: Element) -> str:
    """Определить форму собственности одного right_holder по присутствию ветки.

    Args:
        right_holder: XML элемент <right_holder>

    Returns:
        Значение формы (ключ словаря классификатора) или FORM_UNKNOWN
    """
    # individual / legal_entity -> Частная (обе ветки Частной формы)
    if right_holder.find("individual") is not None:
        return "Частная"
    if right_holder.find("legal_entity") is not None:
        return "Частная"

    # public_formation -> уровень собственности по под-ветке
    if right_holder.find("public_formation") is not None:
        for branch_xpath, form_value in _PUBLIC_FORMATION_BRANCHES:
            if right_holder.find(branch_xpath) is not None:
                return form_value
        # public_formation есть, но под-ветка неизвестна -> Свед_нет
        return FORM_UNKNOWN

    # undefined / another / отсутствие ветки -> Свед_нет (K2)
    return FORM_UNKNOWN


def derive_form_tech(root_element: Optional[Element]) -> Optional[str]:
    """Деривация транзитной формы собственности `__Форма_тех` из выписки.

    Итерирует ВСЕХ right_holder (right_records/right_record/right_holders/
    right_holder), для каждого определяет форму по сработавшей presence-ветке,
    собирает в `" / "`-joined список (порядок holder).

    Args:
        root_element: Корневой XML элемент выписки (right_records в корне)

    Returns:
        Строка форм через " / " или None если правообладателей нет
    """
    if root_element is None:
        return None

    try:
        holders = root_element.findall(_RIGHT_HOLDER_ROOT)
    except Exception as e:
        log_warning(f"Fsm_1_1_4_8 (derive_form_tech): Ошибка поиска right_holder: {e}")
        return None

    if not holders:
        return None

    forms: List[str] = [_classify_holder_branch(holder) for holder in holders]

    if not forms:
        return None

    return FORM_SEPARATOR.join(forms)
