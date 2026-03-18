# -*- coding: utf-8 -*-
"""
Fsm_5_1_2 - Схема слоёв DPT_* для региона 78 (СПб)

Источник: Приказ КГА СПб N 1-16-82 от 04.07.2025
(Обновлённая редакция приказа 208-116 от 19.10.2018)

Определяет:
- Перечень итоговых слоёв DPT_* с полями и типами данных
- Состав слоёв по этапам/разделам ДПТ
- Справочники значений для атрибутов
- Проекцию (план-схема, МСК-64)

Маппинг L_*/Le_* -> DPT_* определяется отдельно (при реализации экспорта).
"""

from typing import Dict, List, Any


# === Типы полей (совместимы с MapInfo TAB) ===

_S50: Dict[str, Any] = {'type': 'string', 'length': 50}
_S254: Dict[str, Any] = {'type': 'string', 'length': 254}
_FLOAT: Dict[str, Any] = {'type': 'float'}
_INT: Dict[str, Any] = {'type': 'integer'}


# === Определения полей по пунктам приказа ===
#
# Каждое поле: (имя_в_TAB, полное_наименование, тип, обязательность)
# Для условно-обязательных полей указан комментарий.


# п.4.1 — DPT_OKS_PL (планируемые ОКС)
FIELDS_4_1: List[Dict[str, Any]] = [
    {'name': 'Номер_зоны', 'full_name': 'Номер зоны', 'info': 'Номер зоны ОКС в соответствии с ДПТ', **_S50, 'required': True},
    {'name': 'Наименование', 'full_name': 'Функциональное назначение ОКС', 'info': 'Описание ВРИ ЗУ по Классификатору', **_S254, 'required': True},
    {'name': 'Наименование_2', 'full_name': 'Функциональное назначение ОКС', 'info': 'Описание ВРИ ЗУ по Классификатору', **_S254, 'required': True},
    {'name': 'Наименование_3', 'full_name': 'Функциональное назначение ОКС', 'info': 'Описание ВРИ ЗУ по Классификатору', **_S254, 'required': True},
    {'name': 'Наименование_4', 'full_name': 'Функциональное назначение ОКС', 'info': 'Описание ВРИ ЗУ по Классификатору', **_S254, 'required': True},
    {'name': 'Вид_разр_использования', 'full_name': 'Вид разрешенного использования ОКС', 'info': 'По Классификатору', **_S254, 'required': True},
    {'name': 'Код_вида', 'full_name': 'Код вида разрешенного использования', 'info': 'По Классификатору', **_S254, 'required': True},
    {'name': 'Площадь_застр', 'full_name': 'Площадь застройки, кв.м', 'info': 'По материалам ДПТ', **_FLOAT, 'required': True},
    {'name': 'Общая_площадь', 'full_name': 'Общая площадь ОКС, кв.м', 'info': 'Максимальная общая площадь ОКС', **_FLOAT, 'required': True},
    {'name': 'Площадь_квартир', 'full_name': 'Общая площадь квартир, кв.м', 'info': '0 при отсутствии квартир', **_FLOAT, 'required': True},
    {'name': 'Площадь_встройки', 'full_name': 'Общая площадь встроенных помещений, кв.м', 'info': '0 при отсутствии', **_FLOAT, 'required': True},
    {'name': 'Высота', 'full_name': 'Высота ОКС, м', 'info': 'Значение планируемой высоты', **_S254, 'required': True},
    {'name': 'Обеспеченность', 'full_name': 'Обеспеченность населения объектами соц. инфраструктуры', 'info': 'По НГП', **_S254, 'required': True},
]

# п.4.2 — DPT_REDL, DPT_redl_project, DPT_redl_save, DPT_redl_off
FIELDS_4_2: List[Dict[str, Any]] = [
    {'name': 'Номер', 'full_name': 'Номер красной линии', 'info': 'Номер контура КЛ соответствующего чертежа', **_S50, 'required': True},
    {'name': 'Статус', 'full_name': 'Статус красной линии', 'info': 'Устанавливаемая,изменяемая/существующая/отменяемая', **_S254, 'required': True},
]

# п.4.3 — DPT_P_PS, DPT_S_PS
FIELDS_4_3: List[Dict[str, Any]] = [
    {'name': 'Номер', 'full_name': 'Номер элемента планировочной структуры', 'info': 'По ДПТ', **_S50, 'required': True},
    {'name': 'Вид', 'full_name': 'Вид элемента планировочной структуры', 'info': 'Из справочника 6.1', **_S254, 'required': True},
    {'name': 'Площадь_га', 'full_name': 'Площадь элемента планировочной структуры, га', 'info': 'По ДПТ, округление до 2 знаков', **_FLOAT, 'required': True},
]

# п.4.4 — DPT_ZONE_OKS
FIELDS_4_4: List[Dict[str, Any]] = [
    {'name': 'Номер', 'full_name': 'Номер зоны', 'info': 'Номер зоны размещения ОКС по ДПТ', **_S50, 'required': True},
    {'name': 'Наименование', 'full_name': 'Функциональное назначение ОКС', 'info': 'Описание ВРИ ЗУ по Классификатору', **_S254, 'required': True},
    {'name': 'Наименование_2', 'full_name': 'Функциональное назначение ОКС', 'info': 'Описание ВРИ ЗУ по Классификатору', **_S254, 'required': True},
    {'name': 'Наименование_3', 'full_name': 'Функциональное назначение ОКС', 'info': 'Описание ВРИ ЗУ по Классификатору', **_S254, 'required': True},
    {'name': 'Наименование_4', 'full_name': 'Функциональное назначение ОКС', 'info': 'Описание ВРИ ЗУ по Классификатору', **_S254, 'required': True},
    {'name': 'Вид_разр_использования', 'full_name': 'Вид разрешенного использования ОКС', 'info': 'По Классификатору', **_S254, 'required': True},
    {'name': 'Код_вида', 'full_name': 'Код вида разрешенного использования', 'info': 'По Классификатору', **_S254, 'required': True},
]

# п.4.5 — DPT_O_ZU, DPT_I_ZU, DPT_S_ZU
# Некоторые поля условно-обязательные (для образуемых/изменяемых)
FIELDS_4_5: List[Dict[str, Any]] = [
    {'name': 'Номер', 'full_name': 'Номер ЗУ', 'info': 'Условный/кадастровый номер ЗУ', **_S50, 'required': True},
    {'name': 'Статус', 'full_name': 'Статус земельного участка', 'info': 'Из справочника 6.3', **_S254, 'required': True},
    {'name': 'Примечание', 'full_name': 'Примечание', 'info': 'Из справочника 6.3, для изменяемых ЗУ', **_S254, 'required': False, 'required_for': ['DPT_I_ZU']},
    {'name': 'Способ_образования_ЗУ', 'full_name': 'Способ образования', 'info': 'Из справочника 6.4, для образуемых ЗУ', **_S254, 'required': False, 'required_for': ['DPT_O_ZU']},
    {'name': 'Вид_разр_использования', 'full_name': 'Вид разрешенного использования ЗУ', 'info': 'По Классификатору', **_S254, 'required': True},
    {'name': 'Код_вида', 'full_name': 'Код вида разрешенного использования', 'info': 'По Классификатору', **_S254, 'required': True},
    {'name': 'Площадь_ЗУ', 'full_name': 'Площадь ЗУ, кв.м', 'info': 'По материалам ДПТ', **_INT, 'required': True},
]

# п.4.6 — DPT_UDS
FIELDS_4_6: List[Dict[str, Any]] = [
    {'name': 'Номер', 'full_name': 'Номер элемента УДС', 'info': 'Номер элемента УДС из чертежа ДПТ', **_S50, 'required': True},
    {'name': 'Тип_УДС', 'full_name': 'Тип УДС', 'info': 'По НГП', **_S254, 'required': True},
    {'name': 'Категория_УДС', 'full_name': 'Категория УДС', 'info': 'По НГП', **_S254, 'required': True},
    {'name': 'Ширина_УДС', 'full_name': 'Ширина УДС в красных линиях, м', 'info': 'Из чертежа ДПТ', **_S254, 'required': True},
]

# п.4.7 — DPT_OI_I
FIELDS_4_7: List[Dict[str, Any]] = [
    {'name': 'Номер', 'full_name': 'Номер объекта инженерной инфраструктуры', 'info': 'По ДПТ', **_S50, 'required': True},
    {'name': 'Вид', 'full_name': 'Вид инженерного обеспечения', 'info': 'Из справочника 6.5', **_S254, 'required': True},
    {'name': 'Наименование', 'full_name': 'Наименование объекта', 'info': 'ТП, РТП, КНС и т.д.', **_S254, 'required': True},
    {'name': 'Статус_объекта', 'full_name': 'Статус объекта инженерной инфраструктуры', 'info': 'Из справочника 6.2', **_S254, 'required': True},
    {'name': 'Примечание', 'full_name': 'Примечание', 'info': 'Иные сведения об ОИИ', **_S254, 'required': False},
]

# п.4.8 — DPT_ZEL_ZNOP, DPT_ZEL_ZU
FIELDS_4_8: List[Dict[str, Any]] = [
    {'name': 'Номер', 'full_name': 'Номер', 'info': 'Номер ОЗУ/номер зоны ОКС', **_S50, 'required': True},
    {'name': 'Площадь_га', 'full_name': 'Площадь ЗН, га', 'info': 'По ДПТ, округление до 4 знаков', **_FLOAT, 'required': True},
]

# п.4.9 — DPT_PARK, DPT_PARK_ZU
FIELDS_4_9: List[Dict[str, Any]] = [
    {'name': 'Номер', 'full_name': 'Номер парковки', 'info': 'По номеру зоны ОКС/ОЗУ/порядковый номер', **_S50, 'required': True},
    {'name': 'Площадь', 'full_name': 'Площадь парковки, кв.м', 'info': 'По ДПТ', **_FLOAT, 'required': True},
    {'name': 'Количество_мест', 'full_name': 'Количество мест стоянок (размещения)', 'info': 'По ДПТ', **_INT, 'required': True},
]

# п.4.10 — DPT_OTREDL
FIELDS_4_10: List[Dict[str, Any]] = [
    {'name': 'Величина_отступа', 'full_name': 'Величина отступа от красных линий, м', 'info': 'По ДПТ', **_S254, 'required': False},
]

# п.4.11 — DPT_SERV
FIELDS_4_11: List[Dict[str, Any]] = [
    {'name': 'Номер_ЗУ', 'full_name': 'Номер ЗУ', 'info': 'Условный/кадастровый номер ЗУ, обременяемый сервитутом', **_S50, 'required': True},
    {'name': 'Граница_сервитута', 'full_name': 'Описание сервитута', 'info': 'Цель установления сервитута, срок действия', **_S254, 'required': False},
]

# п.4.12 — DPT_OKS_SO, DPT_OKS_SN
FIELDS_4_12: List[Dict[str, Any]] = [
    {'name': 'Кад_номер', 'full_name': 'Кадастровый номер', 'info': 'Кадастровый номер ОКС', **_S50, 'required': False},
]


# === Реестр слоёв DPT_* ===
#
# Каждый слой: имя файла TAB, описание, тип геометрии, ссылка на поля.
# geometry_type: 'Polygon', 'LineString', 'Point', 'Mixed' (полилиния+полигон+точка)

DPT_LAYERS: Dict[str, Dict[str, Any]] = {
    # --- Красные линии (п.4.2) ---
    'DPT_REDL': {
        'description': 'Красные линии (устанавливаемые, изменяемые, существующие)',
        'geometry_type': 'LineString',
        'fields': FIELDS_4_2,
    },
    'DPT_redl_project': {
        'description': 'Красные линии устанавливаемые, изменяемые',
        'geometry_type': 'LineString',
        'fields': FIELDS_4_2,
    },
    'DPT_redl_save': {
        'description': 'Красные линии существующие (сохраняемые)',
        'geometry_type': 'LineString',
        'fields': FIELDS_4_2,
    },
    'DPT_redl_off': {
        'description': 'Красные линии отменяемые',
        'geometry_type': 'LineString',
        'fields': FIELDS_4_2,
    },

    # --- ОКС (п.4.1, п.4.12) ---
    'DPT_OKS_PL': {
        'description': 'Планируемые объекты капитального строительства',
        'geometry_type': 'Polygon',
        'fields': FIELDS_4_1,
    },
    'DPT_OKS_SO': {
        'description': 'Существующие (сохраняемые) ОКС',
        'geometry_type': 'Polygon',
        'fields': FIELDS_4_12,
    },
    'DPT_OKS_SN': {
        'description': 'ОКС, подлежащие сносу',
        'geometry_type': 'Polygon',
        'fields': FIELDS_4_12,
    },

    # --- Зоны размещения ОКС (п.4.4) ---
    'DPT_ZONE_OKS': {
        'description': 'Границы зон планируемого размещения ОКС',
        'geometry_type': 'Polygon',
        'fields': FIELDS_4_4,
    },

    # --- Земельные участки (п.4.5) ---
    'DPT_O_ZU': {
        'description': 'Границы образуемых ЗУ (в т.ч. к резервированию/изъятию)',
        'geometry_type': 'Polygon',
        'fields': FIELDS_4_5,
    },
    'DPT_I_ZU': {
        'description': 'Границы изменяемых ЗУ (в т.ч. к резервированию/изъятию)',
        'geometry_type': 'Polygon',
        'fields': FIELDS_4_5,
    },
    'DPT_S_ZU': {
        'description': 'Границы существующих ЗУ',
        'geometry_type': 'Polygon',
        'fields': FIELDS_4_5,
    },

    # --- Элементы планировочной структуры (п.4.3) ---
    'DPT_P_PS': {
        'description': 'Границы планируемых элементов планировочной структуры',
        'geometry_type': 'Polygon',
        'fields': FIELDS_4_3,
    },
    'DPT_S_PS': {
        'description': 'Границы существующих элементов планировочной структуры',
        'geometry_type': 'Polygon',
        'fields': FIELDS_4_3,
    },

    # --- УДС (п.4.6) ---
    'DPT_UDS': {
        'description': 'Линии, обозначающие дороги, улицы, проезды',
        'geometry_type': 'Mixed',  # полилиния + полигон
        'fields': FIELDS_4_6,
    },

    # --- ОИИ (п.4.7) ---
    'DPT_OI_I': {
        'description': 'Объекты инженерной инфраструктуры',
        'geometry_type': 'Mixed',  # полилиния + полигон + точка
        'fields': FIELDS_4_7,
    },

    # --- Зелёные насаждения (п.4.8) ---
    'DPT_ZEL_ZNOP': {
        'description': 'Территории планируемых зелёных насаждений общего пользования',
        'geometry_type': 'Polygon',
        'fields': FIELDS_4_8,
    },
    'DPT_ZEL_ZU': {
        'description': 'Озеленение земельных участков (по ПЗЗ, в границах ЗУ к развитию)',
        'geometry_type': 'Polygon',
        'fields': FIELDS_4_8,
    },

    # --- Парковки (п.4.9) ---
    'DPT_PARK': {
        'description': 'Парковки на территории общего пользования',
        'geometry_type': 'Polygon',
        'fields': FIELDS_4_9,
    },
    'DPT_PARK_ZU': {
        'description': 'Парковки в границах ЗУ, предполагаемых к развитию',
        'geometry_type': 'Polygon',
        'fields': FIELDS_4_9,
    },

    # --- Линии отступа (п.4.10) ---
    'DPT_OTREDL': {
        'description': 'Линии отступа от красных линий',
        'geometry_type': 'LineString',
        'fields': FIELDS_4_10,
    },

    # --- Публичные сервитуты (п.4.11) ---
    'DPT_SERV': {
        'description': 'Границы установленных/подлежащих установлению публичных сервитутов',
        'geometry_type': 'Polygon',
        'fields': FIELDS_4_11,
    },
}


# === Состав слоёв по этапам/разделам ДПТ ===
#
# Ключ — идентификатор раздела, значение — список имён слоёв DPT_*.
# Порядок слоёв соответствует приказу (раздел 3).

SECTION_LAYERS: Dict[str, List[str]] = {
    # Материалы 1-го этапа подготовки ДПТ
    'stage_1': [
        'DPT_redl_project',
        'DPT_redl_save',
        'DPT_redl_off',
        'DPT_ZEL_ZNOP',
        'DPT_ZONE_OKS',
        'DPT_O_ZU',
        'DPT_PARK',
        'DPT_OKS_PL',
        'DPT_PARK_ZU',
        'DPT_ZEL_ZU',
        'DPT_UDS',
    ],

    # Материалы 2-го этапа — Проект планировки территории
    'stage_2_pp': [
        'DPT_OKS_PL',
        'DPT_OKS_SO',
        'DPT_OKS_SN',
        'DPT_ZEL_ZU',
        'DPT_ZEL_ZNOP',
        'DPT_PARK_ZU',
        'DPT_REDL',
        'DPT_redl_project',
        'DPT_redl_save',
        'DPT_redl_off',
        'DPT_P_PS',
        'DPT_S_PS',
        'DPT_PARK',
        'DPT_ZONE_OKS',
        'DPT_UDS',
        'DPT_OI_I',
    ],

    # Материалы 2-го этапа — Проект межевания территории
    'stage_2_pmt': [
        'DPT_REDL',
        'DPT_OTREDL',
        'DPT_O_ZU',
        'DPT_I_ZU',
        'DPT_S_ZU',
        'DPT_P_PS',
        'DPT_S_PS',
        'DPT_SERV',
    ],
}


# === Тип проекта -> какие разделы включаются ===

PROJECT_TYPE_SECTIONS: Dict[str, List[str]] = {
    'ПП': ['stage_1', 'stage_2_pp'],
    'ПМ': ['stage_1', 'stage_2_pmt'],
    'ПП совмещенный с ПМ': ['stage_1', 'stage_2_pp', 'stage_2_pmt'],
}


# === Справочники значений (раздел 6 приказа) ===

# 6.1 — Виды элементов планировочной структуры
# Используется для: DPT_S_PS, DPT_P_PS (поле "Вид")
REFERENCE_6_1_PLAN_STRUCTURE: Dict[str, str] = {
    'Район': 'Район',
    'Микрорайон': 'Микрорайон',
    'Квартал': 'Квартал',
    'ТОП': 'Территория общего пользования',
    'Садоводство, Огородничество': 'Территория ведения гражданами садоводства или огородничества для собственных нужд',
    'ТПУ': 'Территория транспортно-пересадочного узла',
    'УДС': 'Улично-дорожная сеть',
}

# 6.2 — Статусы объектов инженерной инфраструктуры
# Используется для: DPT_OI_I (поле "Статус_объекта")
REFERENCE_6_2_OII_STATUS: List[str] = [
    'Существующий',
    'Реконструируемый',
    'Строящийся',
    'Планируемый к размещению',
    'Планируемый к реконструкции',
    'Планируемый к ликвидации',
]

# 6.3 — Статусы земельных участков
# Используется для: DPT_O_ZU, DPT_I_ZU, DPT_S_ZU (поле "Статус")
REFERENCE_6_3_ZU_STATUS: List[str] = [
    'Образуемый',
    'Образуемый к резервированию',
    'Образуемый к изъятию',
    'Существующий к резервированию',
    'Существующий к изъятию',
    'Существующий',
    'Изменяемый',
]

# 6.4 — Способы образования земельных участков
# Используется для: DPT_O_ZU (поле "Способ_образования_ЗУ")
REFERENCE_6_4_ZU_FORMATION: List[str] = [
    'Раздел',
    'Объединение',
    'Перераспределение',
    'Выдел из ЗУ',
    'Образование земельного участка из земель, находящихся в государственной собственности',
]

# 6.5 — Виды объектов инженерной инфраструктуры
# Используется для: DPT_OI_I (поле "Вид")
REFERENCE_6_5_OII_TYPE: List[str] = [
    'Водоснабжение',
    'Водоотведение',
    'Газоснабжение',
    'Электроснабжение',
    'Теплоснабжение',
]


# === Проекция ===
#
# Формат TAB: проекция "план-схема(метры)"
# МСК-64 (местная система координат 1964 года)
# Балтийская система высот
#
# MapInfo CoordSys:
#   CoordSys NonEarth Units "m" Bounds (0, 0) (200000, 200000)
# Параметры: Min X: 0 m, Min Y: 0 m, Max X: 200000 m, Max Y: 200000 m

PROJECTION_COORDSYS = 'CoordSys NonEarth Units "m" Bounds (0, 0) (200000, 200000)'


# === Структура выходных папок ===

OUTPUT_FOLDERS: Dict[str, str] = {
    'vector_layers': 'Геоинформационные слои',
    'coord_zu': 'Земельные участки',
    'coord_redl': 'Красные линии',
    'coord_border': 'Границы территории',
    'registry': '',  # корень — Реестр.XLS
}


# === Вспомогательные функции ===

def get_layers_for_project_type(project_type: str) -> List[str]:
    """
    Получить полный список уникальных слоёв DPT_* для типа проекта.

    Args:
        project_type: 'ПП', 'ПМ', 'ПП совмещенный с ПМ'

    Returns:
        Список уникальных имён слоёв (без дубликатов, в порядке первого появления)
    """
    sections = PROJECT_TYPE_SECTIONS.get(project_type, [])
    seen = set()
    result = []

    for section_id in sections:
        for layer_name in SECTION_LAYERS.get(section_id, []):
            if layer_name not in seen:
                seen.add(layer_name)
                result.append(layer_name)

    return result


def get_layer_fields(layer_name: str) -> List[Dict[str, Any]]:
    """
    Получить список полей для слоя DPT_*.

    Args:
        layer_name: Имя слоя (например, 'DPT_O_ZU')

    Returns:
        Список определений полей или пустой список
    """
    layer_def = DPT_LAYERS.get(layer_name)
    if layer_def:
        return layer_def['fields']
    return []


def get_required_fields(layer_name: str) -> List[str]:
    """
    Получить имена обязательных полей для слоя.

    Args:
        layer_name: Имя слоя

    Returns:
        Список имён обязательных полей
    """
    fields = get_layer_fields(layer_name)
    result = []
    for field in fields:
        if field.get('required'):
            result.append(field['name'])
        elif layer_name in field.get('required_for', []):
            result.append(field['name'])
    return result
