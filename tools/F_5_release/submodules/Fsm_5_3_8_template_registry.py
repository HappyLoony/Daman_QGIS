# -*- coding: utf-8 -*-
"""
Fsm_5_3_8 - Реестр шаблонов документов

Все шаблоны документов для экспорта (перечни координат, ведомости, перечни КН)
определяются как Python константы. Внешние JSON файлы не используются.

Каждый шаблон задаёт:
- Тип документа (coordinate_list, attribute_list, cadnum_list и др.)
- Паттерны слоёв-источников (с поддержкой wildcard *)
- Шаблон заголовка с {переменными}
- Формат контуров (для перечней координат)
- Источник колонок (для ведомостей)
- Шаблон имени файла
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from Daman_QGIS.utils import log_info, log_debug


@dataclass
class DocumentTemplate:
    """Шаблон документа для экспорта"""

    template_id: str
    doc_type: str  # coordinate_list | attribute_list | cadnum_list | gpmt_coordinates | gpmt_characteristics
    name: str
    source_layers: List[str]  # паттерны слоёв (prefix_ или wildcard *)
    title_template: str  # с {переменными}
    supports_wgs84: bool = False
    contour_format: Optional[str] = None  # "Контур {№}" для перечней координат
    column_source: Optional[Dict[str, str]] = field(default=None)  # {"database": "Base_cutting", "field": "full_name"}
    filename_template: str = ""  # шаблон имени файла
    priority: int = 0  # -1 = universal fallback

    # Специфичные для cadnum_list
    cadnum_field: Optional[str] = None  # имя поля КН
    cadnum_sheet_name: Optional[str] = None  # имя листа Excel
    cadnum_fallback_layer: Optional[str] = None  # fallback имя слоя


# === Перечни координат ОЗУ ===

COORD_CUTTING_OKS_RAZDEL = DocumentTemplate(
    template_id='coord_cutting_oks_razdel',
    doc_type='coordinate_list',
    name='Перечень координат ОЗУ ОКС (Раздел)',
    source_layers=['Le_2_1_1_*_Раздел'],
    title_template='Перечень координат характерных точек границ образуемых земельных участков',
    contour_format='Контур {№}',
    supports_wgs84=True,
    filename_template='Приложение_{appendix}_координаты_ОЗУ_Раздел',
)

COORD_CUTTING_OKS_NGS = DocumentTemplate(
    template_id='coord_cutting_oks_ngs',
    doc_type='coordinate_list',
    name='Перечень координат ОЗУ ОКС (НГС)',
    source_layers=['Le_2_1_1_*_НГС'],
    title_template='Перечень координат характерных точек границ образуемых земельных участков',
    contour_format='Контур {№}',
    supports_wgs84=True,
    filename_template='Приложение_{appendix}_координаты_ОЗУ_НГС',
)

COORD_CUTTING_OKS_IZM = DocumentTemplate(
    template_id='coord_cutting_oks_izm',
    doc_type='coordinate_list',
    name='Перечень координат ОЗУ ОКС (Изм)',
    source_layers=['Le_2_1_1_*_Изм'],
    title_template='Перечень координат характерных точек границ образуемых земельных участков',
    contour_format='Контур {№}',
    supports_wgs84=True,
    filename_template='Приложение_{appendix}_координаты_ОЗУ_Изм',
)

COORD_CUTTING_OKS_PS = DocumentTemplate(
    template_id='coord_cutting_oks_ps',
    doc_type='coordinate_list',
    name='Перечень координат (ПС)',
    source_layers=['Le_2_1_1_*_ПС*'],
    title_template='Перечень координат характерных точек контуров публичных сервитутов',
    contour_format='Контур {№}',
    supports_wgs84=True,
    filename_template='Приложение_{appendix}_координаты_ПС',
)

COORD_CUTTING_LO = DocumentTemplate(
    template_id='coord_cutting_lo',
    doc_type='coordinate_list',
    name='Перечень координат',
    source_layers=['Le_2_1_2_*'],
    title_template='Перечень координат характерных точек границ образуемых земельных участков',
    contour_format='Контур {№}',
    supports_wgs84=True,
    filename_template='Приложение_{appendix}_координаты',
)

COORD_CUTTING_VO = DocumentTemplate(
    template_id='coord_cutting_vo',
    doc_type='coordinate_list',
    name='Перечень координат ОЗУ ВО',
    source_layers=['Le_2_1_3_*'],
    title_template='Перечень координат характерных точек границ образуемых земельных участков',
    contour_format='Контур {№}',
    supports_wgs84=True,
    filename_template='Приложение_{appendix}_координаты_ОЗУ_ВО',
)

COORD_CUTTING_REK_AD = DocumentTemplate(
    template_id='coord_cutting_rek_ad',
    doc_type='coordinate_list',
    name='Перечень координат ОЗУ РЕК АД',
    source_layers=['Le_2_2_1_*'],
    title_template='Перечень координат характерных точек границ образуемых земельных участков',
    contour_format='Контур {№}',
    supports_wgs84=True,
    filename_template='Приложение_{appendix}_координаты_ОЗУ_РЕК_АД',
)

COORD_CUTTING_SETI_PO = DocumentTemplate(
    template_id='coord_cutting_seti_po',
    doc_type='coordinate_list',
    name='Перечень координат ОЗУ СЕТИ ПО',
    source_layers=['Le_2_2_2_*'],
    title_template='Перечень координат характерных точек границ образуемых земельных участков',
    contour_format='Контур {№}',
    supports_wgs84=True,
    filename_template='Приложение_{appendix}_координаты_ОЗУ_СЕТИ_ПО',
)

COORD_CUTTING_SETI_VO = DocumentTemplate(
    template_id='coord_cutting_seti_vo',
    doc_type='coordinate_list',
    name='Перечень координат ОЗУ СЕТИ ВО',
    source_layers=['Le_2_2_3_*'],
    title_template='Перечень координат характерных точек границ образуемых земельных участков',
    contour_format='Контур {№}',
    supports_wgs84=True,
    filename_template='Приложение_{appendix}_координаты_ОЗУ_СЕТИ_ВО',
)

COORD_CUTTING_NE = DocumentTemplate(
    template_id='coord_cutting_ne',
    doc_type='coordinate_list',
    name='Перечень координат ОЗУ НЭ',
    source_layers=['Le_2_2_4_*'],
    title_template='Перечень координат характерных точек границ образуемых земельных участков',
    contour_format='Контур {№}',
    supports_wgs84=True,
    filename_template='Приложение_{appendix}_координаты_ОЗУ_НЭ',
)

# === Перечни координат этапности ===

COORD_STAGE_1 = DocumentTemplate(
    template_id='coord_stage_1',
    doc_type='coordinate_list',
    name='Перечень координат ОЗУ (Этап 1)',
    source_layers=['Le_2_7_1_*'],
    title_template='Перечень координат характерных точек границ образуемых земельных участков (1 этап)',
    contour_format='Контур {№}',
    supports_wgs84=True,
    filename_template='Приложение_{appendix}_координаты_Этап_1',
)

COORD_STAGE_2 = DocumentTemplate(
    template_id='coord_stage_2',
    doc_type='coordinate_list',
    name='Перечень координат ОЗУ (Этап 2)',
    source_layers=['Le_2_7_2_*'],
    title_template='Перечень координат характерных точек границ образуемых земельных участков (2 этап)',
    contour_format='Контур {№}',
    supports_wgs84=True,
    filename_template='Приложение_{appendix}_координаты_Этап_2',
)

COORD_STAGE_FINAL = DocumentTemplate(
    template_id='coord_stage_final',
    doc_type='coordinate_list',
    name='Перечень координат ОЗУ (Итог)',
    source_layers=['Le_2_7_3_*'],
    title_template='Перечень координат характерных точек границ образуемых земельных участков (итог)',
    contour_format='Контур {№}',
    supports_wgs84=True,
    filename_template='Приложение_{appendix}_координаты_Итог',
)

# === Перечни координат существующих ЗУ ===

COORD_ZU_SELECTION = DocumentTemplate(
    template_id='coord_zu_selection',
    doc_type='coordinate_list',
    name='Перечень координат существующих ЗУ',
    source_layers=['L_2_1_1_Выборка_ЗУ'],
    title_template='Перечень координат характерных точек границ существующих земельных участков',
    contour_format='Контур {№}',
    supports_wgs84=True,
    filename_template='Приложение_{appendix}_координаты_ЗУ',
)

# === ГПМТ ===

COORD_GPMT = DocumentTemplate(
    template_id='coord_gpmt',
    doc_type='gpmt_coordinates',
    name='Координаты ГПМТ',
    source_layers=['L_2_6_1_ГПМТ'],
    title_template='Перечень координат характерных точек границ территории, '
                   'применительно к которой осуществляется подготовка проекта '
                   'межевания территории {object_type} объекта',
    supports_wgs84=True,
    filename_template='ГПМТ_координаты',
)

CHARACTERISTICS_GPMT = DocumentTemplate(
    template_id='characteristics_gpmt',
    doc_type='gpmt_characteristics',
    name='Характеристики ГПМТ',
    source_layers=['L_2_6_1_ГПМТ'],
    title_template='Ведомость характеристик ГПМТ',
    filename_template='ГПМТ_характеристики',
)

# === Ведомости ===

VEDOMOST_ZU_SELECTION = DocumentTemplate(
    template_id='vedomost_zu_selection',
    doc_type='attribute_list',
    name='Ведомость существующих ЗУ',
    source_layers=['L_2_1_1_Выборка_ЗУ'],
    title_template='Ведомость земельных участков в границах {1_3_object_type}',
    column_source={'database': 'Base_selection_ZU', 'field': 'full_name'},
    filename_template='Ведомость_ЗУ',
)

VEDOMOST_ZU_RAZDEL = DocumentTemplate(
    template_id='vedomost_zu_razdel',
    doc_type='attribute_list',
    name='Ведомость ОЗУ (Раздел)',
    source_layers=['Le_2_1_1_*_Раздел', 'Le_2_7_*_Раздел'],
    title_template='Ведомость образуемых земельных участков',
    column_source={'database': 'Base_cutting', 'field': 'full_name'},
    filename_template='Ведомость_ОЗУ_Раздел',
)

VEDOMOST_ZU_LO = DocumentTemplate(
    template_id='vedomost_zu_lo',
    doc_type='attribute_list',
    name='Ведомость',
    source_layers=['Le_2_1_2_*'],
    title_template='Ведомость образуемых земельных участков',
    column_source={'database': 'Base_cutting', 'field': 'full_name'},
    filename_template='Ведомость',
)

VEDOMOST_ZU_VO = DocumentTemplate(
    template_id='vedomost_zu_vo',
    doc_type='attribute_list',
    name='Ведомость ОЗУ (ВО)',
    source_layers=['Le_2_1_3_*'],
    title_template='Ведомость образуемых земельных участков (водные объекты)',
    column_source={'database': 'Base_cutting', 'field': 'full_name'},
    filename_template='Ведомость_ОЗУ_ВО',
)

# === Перечни кадастровых номеров ===

CADNUM_ZU = DocumentTemplate(
    template_id='cadnum_zu',
    doc_type='cadnum_list',
    name='Перечень КН земельных участков',
    source_layers=['Le_2_1_1_1_Выборка_ЗУ'],
    title_template='Кадастровый номер ЗУ',
    filename_template='Перечень_КН',
    cadnum_field='cad_num',
    cadnum_sheet_name='Земельные участки',
    cadnum_fallback_layer='L_2_1_1_Выборка_ЗУ',
)

CADNUM_OKS = DocumentTemplate(
    template_id='cadnum_oks',
    doc_type='cadnum_list',
    name='Перечень КН ОКС',
    source_layers=['L_1_2_4_WFS_ОКС'],
    title_template='Кадастровый номер ОКС',
    filename_template='Перечень_КН',
    cadnum_field='cad_num',
    cadnum_sheet_name='ОКС',
)

CADNUM_KK = DocumentTemplate(
    template_id='cadnum_kk',
    doc_type='cadnum_list',
    name='Перечень КН кадастровых кварталов',
    source_layers=['L_1_2_2_WFS_КК'],
    title_template='Кадастровый номер КК',
    filename_template='Перечень_КН',
    cadnum_field='cad_num',
    cadnum_sheet_name='Кадастровые кварталы',
)

# === Универсальные шаблоны (fallback) ===

COORD_UNIVERSAL = DocumentTemplate(
    template_id='coord_universal',
    doc_type='coordinate_list',
    name='Перечень координат (универсальный)',
    source_layers=['*'],
    title_template='Перечень координат характерных точек границ {layer_name}',
    contour_format='Контур {№}',
    supports_wgs84=True,
    filename_template='Координаты_{layer_name}',
    priority=-1,
)

VEDOMOST_UNIVERSAL = DocumentTemplate(
    template_id='vedomost_universal',
    doc_type='attribute_list',
    name='Ведомость (универсальная)',
    source_layers=['*'],
    title_template='Ведомость {layer_name}',
    filename_template='Ведомость_{layer_name}',
    priority=-1,
)


# === Реестр всех шаблонов ===

DOCUMENT_TEMPLATES: List[DocumentTemplate] = [
    # Перечни координат ОЗУ
    COORD_CUTTING_OKS_RAZDEL,
    COORD_CUTTING_OKS_NGS,
    COORD_CUTTING_OKS_IZM,
    COORD_CUTTING_OKS_PS,
    COORD_CUTTING_LO,
    COORD_CUTTING_VO,
    COORD_CUTTING_REK_AD,
    COORD_CUTTING_SETI_PO,
    COORD_CUTTING_SETI_VO,
    COORD_CUTTING_NE,
    # Перечни координат этапности
    COORD_STAGE_1,
    COORD_STAGE_2,
    COORD_STAGE_FINAL,
    # Перечни координат существующих ЗУ
    COORD_ZU_SELECTION,
    # ГПМТ
    COORD_GPMT,
    CHARACTERISTICS_GPMT,
    # Ведомости
    VEDOMOST_ZU_SELECTION,
    VEDOMOST_ZU_RAZDEL,
    VEDOMOST_ZU_LO,
    VEDOMOST_ZU_VO,
    # Перечни КН
    CADNUM_ZU,
    CADNUM_OKS,
    CADNUM_KK,
    # Универсальные (fallback)
    COORD_UNIVERSAL,
    VEDOMOST_UNIVERSAL,
]

# Поля для поиска номера точки (используется в Fsm_5_3_1)
POINT_NUMBER_FIELDS = ['n', 'num', 'point_num', 'number', 'ID', 'id']

# Альтернативные имена поля КН (используется в Fsm_5_3_6)
CADNUM_FIELD_ALTERNATIVES = ['КН', 'cad_num', 'cadnum', 'cadastral_number']

# Слой границ проекта для фильтрации КН
BOUNDARIES_LAYER_NAME = 'L_1_1_1_Границы_работ'

# Исключения для слоёв точек (слои которые не имеют Т_* слоёв)
POINTS_LAYER_EXCLUSIONS = ['1_4']

# Заголовки колонок координат
COORD_HEADERS_LOCAL = {'point_num': '№ Точки', 'x': 'X, м', 'y': 'Y, м'}
COORD_HEADERS_WGS84 = {'point_num': '№ Точки', 'x': 'Широта', 'y': 'Долгота'}


class TemplateRegistry:
    """Реестр шаблонов документов"""

    @staticmethod
    def get_templates_for_layer(layer_name: str) -> List[DocumentTemplate]:
        """
        Получить все шаблоны подходящие для слоя

        Если есть точные совпадения (priority >= 0), универсальные (priority < 0) исключаются.

        Args:
            layer_name: Имя слоя

        Returns:
            Список подходящих шаблонов
        """
        exact = []
        fallback = []

        for template in DOCUMENT_TEMPLATES:
            if TemplateRegistry.matches_layer(layer_name, template.source_layers):
                if template.priority < 0:
                    fallback.append(template)
                else:
                    exact.append(template)

        result = exact if exact else fallback
        log_debug(f"Fsm_5_3_8: Для слоя '{layer_name}' найдено {len(result)} шаблонов")
        return result

    @staticmethod
    def get_template_by_id(template_id: str) -> Optional[DocumentTemplate]:
        """
        Получить шаблон по ID

        Args:
            template_id: ID шаблона

        Returns:
            Шаблон или None
        """
        for template in DOCUMENT_TEMPLATES:
            if template.template_id == template_id:
                return template
        return None

    @staticmethod
    def get_all_templates() -> List[DocumentTemplate]:
        """Получить все шаблоны"""
        return DOCUMENT_TEMPLATES

    @staticmethod
    def get_templates_by_type(doc_type: str) -> List[DocumentTemplate]:
        """
        Получить шаблоны по типу документа

        Args:
            doc_type: Тип документа

        Returns:
            Список шаблонов указанного типа
        """
        return [t for t in DOCUMENT_TEMPLATES if t.doc_type == doc_type]

    @staticmethod
    def matches_layer(layer_name: str, patterns: List[str]) -> bool:
        """
        Проверить соответствие имени слоя списку паттернов

        Поддерживает:
        - Точное совпадение: "L_2_1_1_Выборка_ЗУ"
        - Префикс: "Le_2_1_1_" (если кончается на _)
        - Wildcard: "Le_2_1_1_*_Раздел"
        - Глобальный: "*"

        Args:
            layer_name: Имя слоя
            patterns: Список паттернов

        Returns:
            True если слой соответствует хотя бы одному паттерну
        """
        for pattern in patterns:
            if pattern == '*':
                return True

            if pattern == layer_name:
                return True

            if '*' in pattern:
                regex_pattern = pattern.replace('*', '.*')
                if re.match(f'^{regex_pattern}$', layer_name):
                    return True
            elif layer_name.startswith(pattern):
                return True

        return False

    @staticmethod
    def get_coord_headers(is_wgs84: bool) -> Dict[str, str]:
        """
        Получить заголовки колонок для координат

        Args:
            is_wgs84: True для WGS-84

        Returns:
            Словарь с заголовками
        """
        return COORD_HEADERS_WGS84 if is_wgs84 else COORD_HEADERS_LOCAL
