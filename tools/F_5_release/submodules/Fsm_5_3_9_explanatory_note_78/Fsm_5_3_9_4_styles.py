# -*- coding: utf-8 -*-
"""Fsm_5_3_9_4 — Стилевые утилиты для DOCX-генераторов.

Соответствуют ГОСТ 21.101-2020 (рамки 0.5pt single по ГОСТ 2.303) и
типографским требованиям эталона ЧИЖИК (TNR 12, justify, отступ 1.25 см, 1.5 интервал).

Переиспользуемы в будущих DOCX-генераторах (другие ведомости / тома).
"""
from typing import List


class ExplanatoryNoteStyles:
    """Переиспользуемые стилевые утилиты."""

    FONT_NAME = 'Times New Roman'
    FONT_SIZE_PT = 12
    FIRST_LINE_INDENT_CM = 1.25
    LINE_SPACING = 1.5
    TABLE_BORDER_SZ = 4  # Word units: 4 = 0.5pt по ГОСТ 2.303
    HEADER_FONT_NAME = 'Times New Roman'

    @staticmethod
    def set_para_style(p, justify: bool = True, first_line_cm: float = 1.25,
                       line_spacing: float = 1.5,
                       space_before_pt: float = 0, space_after_pt: float = 0) -> None:
        """Задать стиль абзаца: alignment, отступ первой строки, интервал.

        Word по умолчанию ставит space_after = 8-10pt после каждого абзаца —
        это раздувает таблицы штампа и тело документа. Защита: явно
        выставляем space_after = 0 (по требованию пользователя).
        """
        from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
        from docx.shared import Cm, Pt

        if justify:
            p.alignment = WD_PARAGRAPH_ALIGNMENT.JUSTIFY
        pf = p.paragraph_format
        pf.first_line_indent = Cm(first_line_cm)
        pf.line_spacing = line_spacing
        pf.space_before = Pt(space_before_pt)
        pf.space_after = Pt(space_after_pt)

    @staticmethod
    def set_run_style(run, font: str = 'Times New Roman', size_pt: int = 12,
                      bold: bool = False, italic: bool = False) -> None:
        """Задать стиль run: шрифт, размер, жирность, курсив."""
        from docx.shared import Pt

        run.font.name = font
        run.font.size = Pt(size_pt)
        run.font.bold = bold
        run.font.italic = italic

    @staticmethod
    def apply_table_borders(table, sz: int = 4) -> None:
        """Single 0.5pt borders: top/left/bottom/right/insideH/insideV (color=auto)."""
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement

        tbl = table._tbl
        tblPr = tbl.tblPr
        tblBorders = OxmlElement('w:tblBorders')
        for border_name in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
            border = OxmlElement(f'w:{border_name}')
            border.set(qn('w:val'), 'single')
            border.set(qn('w:sz'), str(sz))
            border.set(qn('w:color'), 'auto')
            tblBorders.append(border)
        existing = tblPr.find(qn('w:tblBorders'))
        if existing is not None:
            tblPr.remove(existing)
        tblPr.append(tblBorders)

    @staticmethod
    def set_column_widths(table, widths_cm: List[float]) -> None:
        """Задать ширины колонок в см."""
        from docx.shared import Cm

        for i, width_cm in enumerate(widths_cm):
            for cell in table.columns[i].cells:
                cell.width = Cm(width_cm)
