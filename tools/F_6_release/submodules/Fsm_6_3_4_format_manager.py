# -*- coding: utf-8 -*-
"""
Fsm_6_3_4 - Менеджер форматирования Excel

Унифицированный менеджер форматов для Excel экспорта.
Предоставляет готовые форматы для заголовков, шапок таблиц,
данных и автоподбор ширины колонок.
"""

from typing import Dict, Any, List, Optional, Tuple


class ExcelFormatManager:
    """
    Единый менеджер форматирования Excel

    Предоставляет готовые форматы и утилиты для форматирования
    Excel документов (перечней и ведомостей).
    """

    # Стандартные цвета
    COLORS = {
        'header_bg': '#DDEBF7',      # Светло-голубой фон заголовков
        'header_dark_bg': '#BDD7EE', # Темнее голубой для акцентов
        'white': '#FFFFFF',
        'black': '#000000',
        'light_gray': '#F2F2F2',
        'border': '#000000',
    }

    # Стандартные шрифты
    FONTS = {
        'default': 'Times New Roman',
        'monospace': 'Courier New',
    }

    def __init__(self, workbook):
        """
        Инициализация менеджера форматов

        Args:
            workbook: Объект xlsxwriter.Workbook
        """
        self.workbook = workbook
        self._format_cache: Dict[str, Any] = {}

    def get_appendix_format(self) -> Any:
        """
        Формат для номера приложения (правый верхний угол)

        Returns:
            xlsxwriter Format объект
        """
        if 'appendix' not in self._format_cache:
            self._format_cache['appendix'] = self.workbook.add_format({
                'font_name': self.FONTS['default'],
                'font_size': 11,
                'italic': True,
                'bold': True,
                'align': 'right',
                'valign': 'vcenter',
                'text_wrap': True
            })
        return self._format_cache['appendix']

    def get_title_format(self, font_size: int = 16) -> Any:
        """
        Формат заголовка документа

        Args:
            font_size: Размер шрифта (по умолчанию 16)

        Returns:
            xlsxwriter Format объект
        """
        cache_key = f'title_{font_size}'
        if cache_key not in self._format_cache:
            self._format_cache[cache_key] = self.workbook.add_format({
                'font_name': self.FONTS['default'],
                'font_size': font_size,
                'bold': True,
                'align': 'center',
                'valign': 'vcenter',
                'text_wrap': True
            })
        return self._format_cache[cache_key]

    def get_subtitle_format(self, font_size: int = 12) -> Any:
        """
        Формат подзаголовка (контур, раздел)

        Args:
            font_size: Размер шрифта (по умолчанию 12)

        Returns:
            xlsxwriter Format объект
        """
        cache_key = f'subtitle_{font_size}'
        if cache_key not in self._format_cache:
            self._format_cache[cache_key] = self.workbook.add_format({
                'font_name': self.FONTS['default'],
                'font_size': font_size,
                'align': 'center',
                'valign': 'vcenter',
                'text_wrap': True
            })
        return self._format_cache[cache_key]

    def get_crs_format(self) -> Any:
        """
        Формат для строки системы координат

        Returns:
            xlsxwriter Format объект
        """
        if 'crs' not in self._format_cache:
            self._format_cache['crs'] = self.workbook.add_format({
                'font_name': self.FONTS['default'],
                'font_size': 12,
                'bold': True,
                'align': 'right',
                'valign': 'vcenter'
            })
        return self._format_cache['crs']

    def get_header_format(self, with_border: bool = True, bg_color: Optional[str] = None) -> Any:
        """
        Формат шапки таблицы (заголовки колонок)

        Args:
            with_border: Добавлять рамку (по умолчанию True)
            bg_color: Цвет фона (по умолчанию header_bg)

        Returns:
            xlsxwriter Format объект
        """
        color = bg_color or self.COLORS['header_bg']
        cache_key = f'header_{with_border}_{color}'

        if cache_key not in self._format_cache:
            fmt_dict = {
                'font_name': self.FONTS['default'],
                'font_size': 11,
                'bold': True,
                'align': 'center',
                'valign': 'vcenter',
                'text_wrap': True,
                'bg_color': color
            }
            if with_border:
                fmt_dict['border'] = 1

            self._format_cache[cache_key] = self.workbook.add_format(fmt_dict)

        return self._format_cache[cache_key]

    def get_column_number_format(self) -> Any:
        """
        Формат для номеров колонок под заголовками (1, 2, 3, ...)

        Returns:
            xlsxwriter Format объект
        """
        if 'col_number' not in self._format_cache:
            self._format_cache['col_number'] = self.workbook.add_format({
                'font_name': self.FONTS['default'],
                'font_size': 11,
                'bold': True,
                'align': 'center',
                'valign': 'vcenter',
                'border': 1,
                'bg_color': self.COLORS['header_bg']
            })
        return self._format_cache['col_number']

    def get_data_format(
        self,
        align: str = 'center',
        with_border: bool = True,
        text_wrap: bool = True
    ) -> Any:
        """
        Формат для ячеек данных

        Args:
            align: Выравнивание ('left', 'center', 'right')
            with_border: Добавлять рамку
            text_wrap: Переносить текст

        Returns:
            xlsxwriter Format объект
        """
        cache_key = f'data_{align}_{with_border}_{text_wrap}'

        if cache_key not in self._format_cache:
            fmt_dict = {
                'font_name': self.FONTS['default'],
                'font_size': 11,
                'align': align,
                'valign': 'vcenter',
                'text_wrap': text_wrap
            }
            if with_border:
                fmt_dict['border'] = 1

            self._format_cache[cache_key] = self.workbook.add_format(fmt_dict)

        return self._format_cache[cache_key]

    def get_number_format(
        self,
        num_format: str = '#,##0',
        decimals: int = 0,
        with_border: bool = True
    ) -> Any:
        """
        Формат для числовых данных

        Args:
            num_format: Формат числа (xlsxwriter number format)
            decimals: Количество знаков после запятой
            with_border: Добавлять рамку

        Returns:
            xlsxwriter Format объект
        """
        if decimals > 0:
            num_format = f'#,##0.{"0" * decimals}'

        cache_key = f'number_{num_format}_{with_border}'

        if cache_key not in self._format_cache:
            fmt_dict = {
                'font_name': self.FONTS['default'],
                'font_size': 11,
                'align': 'center',
                'valign': 'vcenter',
                'num_format': num_format
            }
            if with_border:
                fmt_dict['border'] = 1

            self._format_cache[cache_key] = self.workbook.add_format(fmt_dict)

        return self._format_cache[cache_key]

    def get_coordinate_format(self, is_wgs84: bool = False) -> Any:
        """
        Формат для координат

        Args:
            is_wgs84: True для WGS-84 (6 знаков), False для МСК (2 знака)

        Returns:
            xlsxwriter Format объект
        """
        decimals = 6 if is_wgs84 else 2
        num_format = f'0.{"0" * decimals}'
        cache_key = f'coord_{decimals}'

        if cache_key not in self._format_cache:
            self._format_cache[cache_key] = self.workbook.add_format({
                'font_name': self.FONTS['default'],
                'font_size': 11,
                'align': 'center',
                'valign': 'vcenter',
                'num_format': num_format
            })

        return self._format_cache[cache_key]

    def auto_fit_columns(
        self,
        worksheet,
        data: List[List[Any]],
        header_row: int = 0,
        min_width: float = 8,
        max_width: float = 50
    ) -> None:
        """
        Автоподбор ширины колонок на основе данных

        Args:
            worksheet: Лист Excel
            data: Двумерный массив данных
            header_row: Индекс строки заголовков
            min_width: Минимальная ширина
            max_width: Максимальная ширина
        """
        if not data:
            return

        num_cols = max(len(row) for row in data) if data else 0

        for col_idx in range(num_cols):
            max_len = min_width

            for row in data:
                if col_idx < len(row):
                    value = row[col_idx]
                    if value is not None:
                        cell_len = len(str(value)) * 1.1  # Коэффициент для шрифта
                        max_len = max(max_len, cell_len)

            # Ограничиваем ширину
            width = min(max_len, max_width)
            worksheet.set_column(col_idx, col_idx, width)

    def set_smart_column_widths(
        self,
        worksheet,
        column_names: List[str],
        column_hints: Optional[Dict[str, float]] = None
    ) -> None:
        """
        Установить ширину колонок на основе имён и подсказок

        Args:
            worksheet: Лист Excel
            column_names: Список имён колонок
            column_hints: Словарь {ключевое_слово: ширина}
        """
        default_hints = {
            '№': 8,
            'id': 8,
            'номер': 15,
            'кадастровый': 25,
            'адрес': 40,
            'местоположение': 40,
            'категория': 35,
            'ври': 35,
            'собственник': 40,
            'правообладатель': 40,
            'площадь': 15,
            'координат': 15,
            'x': 15,
            'y': 15,
            'широта': 18,
            'долгота': 18,
        }

        hints = {**default_hints, **(column_hints or {})}

        for col_idx, col_name in enumerate(column_names):
            col_lower = col_name.lower()

            # Ищем подходящую ширину по ключевым словам
            width = 15  # default

            for keyword, hint_width in hints.items():
                if keyword in col_lower:
                    width = hint_width
                    break

            # Минимальная ширина по длине заголовка
            header_width = len(col_name) * 1.2
            width = max(width, header_width)

            worksheet.set_column(col_idx, col_idx, width)

    def get_row_heights(self) -> Dict[str, int]:
        """
        Получить рекомендуемые высоты строк

        Returns:
            Словарь {тип_строки: высота}
        """
        return {
            'title': 30,
            'header': 40,
            'column_numbers': 20,
            'data': 18,
            'empty': 15,
        }

    def clear_cache(self):
        """Очистить кэш форматов"""
        self._format_cache.clear()
