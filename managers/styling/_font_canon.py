# -*- coding: utf-8 -*-
"""
Канон шрифтов Daman_QGIS — единственный источник правды (data-слой M_49).

QGIS-FREE МОДУЛЬ: НИКАКИХ импортов qgis.* / PyQt. Импортируется напрямую
(`from Daman_QGIS.managers.styling import _font_canon`) из любого слоя,
включая tools/ (DXF/Excel/Word-экспортеры) и smoke-скрипты без QGIS
(ezdxf-планка M_49 грузит модуль по file-path через importlib).
Stateful-часть (регистрация TTF через QFontDatabase, фабрика QFont) живёт
в `M_49_font_manager.py` и доступна через `registry.get('M_49')`.
Конвенция split по образцу `managers/geometry/_ring_utils.py`.

Канон семейств (утверждён владельцем 2026-06-04):

| Роль       | Семейство       | Назначение                                       |
|------------|-----------------|--------------------------------------------------|
| DRAWING    | GOST 2.304      | чертёжный (ДПТ): подписи канвы, лайауты, DXF     |
| MASTERPLAN | Avenir Next W1G | мастер-план (F_5_4 через M_34/M_46)              |
| DOCUMENT   | Times New Roman | Word-документы и Excel-таблицы (системный шрифт) |
| PLUGIN_UI  | IBM Plex Sans   | шрифт интерфейса плагина                         |

Почему DOCUMENT отсутствует в FONT_FILES: Times New Roman — системный шрифт
Windows; плагином НЕ устанавливается и НЕ регистрируется.

Вне канона (намеренно, решение владельца 2026-06-04):
- Arial — локальная специфика штампа пояснительной записки формы 78
  (Fsm_5_3_9_3), роль не вводится: один потребитель.

Двойная привязка DXF-шрифта выносок («что и как называется и почему»):
- `DXF_FONT_FILE_LABELS` = 'GOST-2.304_Type-B_italic.ttf' — имя ФАЙЛА
  шрифта на целевых ПК пользователей (так шрифт называется в системе,
  куда он установлен).
- Локально в `data/fonts/` плагина ТОТ ЖЕ шрифт лежит под именем
  'gost_2.304_Bold_Italic.ttf' (реестр FONT_FILES, роль DRAWING).
- Расхождение имён файлов НЕ ломает AutoCAD: он матчит TTF не по имени
  файла из записи STYLE, а по СЕМЕЙСТВУ ('GOST 2.304' + флаги bold/italic)
  из extended font data (XDATA ACAD), которую плагин пишет в текстовый
  стиль при экспорте.

История gost.shx: до 2026-06-04 текстовый стиль DXF-выносок ссылался на
gost.shx — прямой SHX-шрифт без жирности и курсива. Заменён на TTF-схему
(стиль `DXF_TEXT_STYLE_LABELS` + extended font data bold/italic) по итогам
расследования MULTILEADER-выносок 2026-06-04.

Установка шрифтов на машины пользователей — через F_4_1 (checker/installer
работают по `required_font_files()`). Канон-список гарантирует, что
ставится ТОЛЬКО перечисленное в FONT_FILES (без легаси из data/fonts).

Парсер начертаний `parse_font_style` един для всех исторических форматов
БД: 'Bold Italic' (Base_labels.json), 'bold;italic' / 'regular ' с
trailing space (Base_layout.json), '' / '-' / None. Case-insensitive,
substring-семантика. Форматы БД НЕ нормализуются — парсер читает как есть.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    'FontRole',
    'FAMILIES',
    'FONT_FILES',
    'DXF_TEXT_STYLE_LABELS',
    'DXF_FONT_FILE_LABELS',
    'DOC_TYPE_FAMILIES',
    'get_family',
    'get_family_for_doc_type',
    'parse_font_style',
    'excel_font_name',
    'word_font_name',
    'dxf_label_text_style',
    'required_font_files',
]


class FontRole(Enum):
    """Роли шрифтов плагина (канон владельца 2026-06-04)."""
    DRAWING = "drawing"        # GOST 2.304
    MASTERPLAN = "masterplan"  # Avenir Next W1G
    DOCUMENT = "document"      # Times New Roman (Word + Excel)
    PLUGIN_UI = "plugin_ui"    # IBM Plex Sans


# Семейства по ролям (единственный источник строк семейств в плагине)
FAMILIES: Dict[FontRole, str] = {
    FontRole.DRAWING: "GOST 2.304",
    FontRole.MASTERPLAN: "Avenir Next W1G",
    FontRole.DOCUMENT: "Times New Roman",
    FontRole.PLUGIN_UI: "IBM Plex Sans",
}

# Реестр файлов для установки (F_4_1) и runtime-регистрации (M_49).
# Имена файлов — как в data/fonts/ плагина.
# DOCUMENT отсутствует намеренно: Times New Roman — системный шрифт Windows.
FONT_FILES: Dict[FontRole, List[str]] = {
    FontRole.DRAWING: [
        "gost_2.304.ttf",
        "gost_2.304_Bold.ttf",
        "gost_2.304_italic.ttf",
        "gost_2.304_Bold_Italic.ttf",
    ],
    FontRole.MASTERPLAN: [
        "Avenir Next W1G Regular.ttf",
        "Avenir Next W1G Medium.ttf",
        "Avenir Next W1G Demi.ttf",
        "Avenir Next W1G Bold.ttf",
        "Avenir Next W1G Light.ttf",
    ],
    FontRole.PLUGIN_UI: [
        "IBMPlexSans-Regular.ttf",
        "IBMPlexSans-Bold.ttf",
    ],
}

# DXF текстовый стиль выносок (история и двойная привязка — в docstring модуля)
DXF_TEXT_STYLE_LABELS = "GOST 2.304 Type B italic"
DXF_FONT_FILE_LABELS = "GOST-2.304_Type-B_italic.ttf"  # имя файла на целевых ПК

# Шрифт по виду документации (переезд из constants.py DOC_TYPE_FONTS)
DOC_TYPE_FAMILIES: Dict[str, FontRole] = {
    "ДПТ": FontRole.DRAWING,
    "Мастер-план": FontRole.MASTERPLAN,
}


def get_family(role: FontRole) -> str:
    """Имя семейства шрифта по роли.

    Args:
        role: Роль из FontRole

    Returns:
        Имя семейства (например 'GOST 2.304')
    """
    return FAMILIES[role]


def get_family_for_doc_type(doc_type: str) -> str:
    """Семейство шрифта по виду документации (замена DOC_TYPE_FONTS.get).

    Неизвестный doc_type → DRAWING (GOST 2.304) — сохраняет fallback
    прежнего `DOC_TYPE_FONTS.get(..., 'GOST 2.304')`.

    Args:
        doc_type: 'ДПТ' | 'Мастер-план'

    Returns:
        Имя семейства шрифта
    """
    role = DOC_TYPE_FAMILIES.get(doc_type, FontRole.DRAWING)
    return FAMILIES[role]


def parse_font_style(value: Optional[str]) -> Tuple[bool, bool]:
    """Разбор начертания из ЛЮБОГО исторического формата БД.

    Поддерживает: 'Bold Italic' (Base_labels), 'bold;italic' / 'regular '
    (Base_layout, включая trailing spaces), '' / '-' / None.
    Case-insensitive, substring-семантика — токен 'regular' игнорируется.

    Args:
        value: Строка начертания из БД (или None)

    Returns:
        Кортеж (bold, italic)
    """
    if not value:
        return (False, False)
    lowered = str(value).lower()
    return ('bold' in lowered, 'italic' in lowered)


def excel_font_name() -> str:
    """Имя шрифта для программных Excel-экспортов (роль DOCUMENT)."""
    return FAMILIES[FontRole.DOCUMENT]


def word_font_name() -> str:
    """Имя шрифта для программных Word-документов (роль DOCUMENT).

    Единая точка для текущих и будущих Word-функций (решение владельца
    2026-06-04). Статику Word-шаблонов (docx) НЕ перезаписывает.
    """
    return FAMILIES[FontRole.DOCUMENT]


def dxf_label_text_style() -> Dict[str, Any]:
    """Параметры текстового стиля DXF-выносок (единым словарём).

    Returns:
        {'name': имя стиля, 'font_file': имя TTF на целевых ПК,
         'family': семейство, 'bold': True, 'italic': True}
    """
    return {
        'name': DXF_TEXT_STYLE_LABELS,
        'font_file': DXF_FONT_FILE_LABELS,
        'family': FAMILIES[FontRole.DRAWING],
        'bold': True,
        'italic': True,
    }


def required_font_files() -> List[str]:
    """Канон-список файлов шрифтов для установки/диагностики (F_4_1).

    Плоский список из FONT_FILES (замена сканирования data/fonts целиком).

    Returns:
        Список имён файлов (11 шт: 4 GOST + 5 Avenir + 2 IBM Plex)
    """
    files: List[str] = []
    for role_files in FONT_FILES.values():
        files.extend(role_files)
    return files
