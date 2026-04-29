# -*- coding: utf-8 -*-
"""
Msm_34_1: LayoutBuilder - Программная генерация макетов из JSON конфигурации

Универсальный генератор макетов из JSON конфигурации.
Конфигурация загружается из Base_layout.json через API.
Единый файл содержит параметры для всех форматов: A4_landscape, A4_portrait, A3_landscape и т.д.

Используется: M_34_layout_manager.py
"""

import os
from typing import Optional, Dict, Any

from qgis.PyQt.QtCore import Qt, QPointF, QSizeF
from qgis.PyQt.QtGui import QFont, QColor
from qgis.core import (
    QgsProject, QgsPrintLayout, QgsLayoutSize, Qgis,
    QgsLayoutItemMap, QgsLayoutItemLegend, QgsLayoutItemLabel,
    QgsLayoutItemPicture, QgsLayoutItemPage, QgsLayoutPoint,
    QgsTextFormat, QgsLayoutMeasurement, QgsLegendStyle, QgsLayoutItem,
    QgsLayoutGuide
)

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.database.base_reference_loader import BaseReferenceLoader
from Daman_QGIS.constants import EXPORT_DPI_ROSREESTR, DOC_TYPE_FONTS

from .Msm_46_types import LegendLayoutMode


class LayoutBuilder:
    """
    Программный генератор макетов из JSON конфигурации

    Создает QgsPrintLayout с элементами (набор зависит от конфигурации):
    - Страница (page_width, page_height)
    - Основная карта (main_map)
    - Обзорная карта (overview_map)
    - Легенда (legend)
    - Заголовок (title_label)
    - Номер приложения (appendix_label)
    - Стрелка севера (north_arrow)
    - Штамп (stamp) - для чертежей
    """

    # Маппинг numpad → QgsLayoutItem.ReferencePoint
    # 1=LowerLeft, 2=LowerMiddle, 3=LowerRight
    # 4=MiddleLeft, 5=Middle, 6=MiddleRight
    # 7=UpperLeft, 8=UpperMiddle, 9=UpperRight
    _REF_POINTS = {
        1: QgsLayoutItem.LowerLeft,
        2: QgsLayoutItem.LowerMiddle,
        3: QgsLayoutItem.LowerRight,
        4: QgsLayoutItem.MiddleLeft,
        5: QgsLayoutItem.Middle,
        6: QgsLayoutItem.MiddleRight,
        7: QgsLayoutItem.UpperLeft,
        8: QgsLayoutItem.UpperMiddle,
        9: QgsLayoutItem.UpperRight,
    }

    def __init__(self):
        """
        Инициализация генератора
        """
        self._config_file = 'Base_layout.json'
        self._config: Optional[Dict[str, Any]] = None
        self._layout: Optional[QgsPrintLayout] = None
        self._font_family: str = DOC_TYPE_FONTS.get('ДПТ', 'GOST 2.304')

    # Кэш зарегистрированных шрифтов (class-level, один раз за сессию)
    _registered_fonts: set = set()

    def _ensure_font_registered(self, font_family: str) -> None:
        """
        Регистрация шрифта в Qt если он не найден в системе.
        Ищет TTF файлы в data/fonts/ плагина.
        """
        if font_family in self._registered_fonts:
            return

        from qgis.PyQt.QtGui import QFontDatabase
        db = QFontDatabase()

        # Проверяем есть ли шрифт
        if font_family in db.families():
            self._registered_fonts.add(font_family)
            return

        # Ищем TTF в data/fonts/
        plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        fonts_dir = os.path.join(plugin_dir, 'data', 'fonts')

        if not os.path.isdir(fonts_dir):
            log_warning(f"Msm_34_1: Папка шрифтов не найдена: {fonts_dir}")
            return

        registered = 0
        for filename in os.listdir(fonts_dir):
            if font_family.lower().replace(' ', '') in filename.lower().replace(' ', ''):
                if filename.endswith(('.ttf', '.otf')):
                    font_path = os.path.join(fonts_dir, filename)
                    font_id = QFontDatabase.addApplicationFont(font_path)
                    if font_id >= 0:
                        registered += 1
                    else:
                        log_warning(f"Msm_34_1: Не удалось зарегистрировать: {filename}")

        if registered > 0:
            self._registered_fonts.add(font_family)
            log_info(f"Msm_34_1: Шрифт '{font_family}' зарегистрирован ({registered} файлов)")
        else:
            log_warning(f"Msm_34_1: Шрифт '{font_family}' не найден в {fonts_dir}")

    def load_config(self) -> bool:
        """
        Загрузка конфигурации из Base_layout.json

        Returns:
            bool: True если конфигурация загружена успешно
        """
        try:
            loader = BaseReferenceLoader()
            self._config = loader._load_json(self._config_file)

            if not self._config:
                log_error(f"Msm_34_1: Не удалось загрузить {self._config_file}")
                return False

            # Проверяем наличие хотя бы одного ключа формата
            config_keys = list(self._config.keys())
            if not config_keys:
                log_error(f"Msm_34_1: Конфигурация {self._config_file} пуста")
                return False

            log_info(f"Msm_34_1: Конфигурация загружена ({', '.join(config_keys)})")
            return True

        except Exception as e:
            log_error(f"Msm_34_1: Ошибка загрузки конфигурации {self._config_file}: {e}")
            return False

    def build(self, config_key: str = 'A4_landscape', layout_name: str = 'Layout',
              doc_type: str = 'ДПТ') -> Optional[QgsPrintLayout]:
        """
        Создание макета из конфигурации

        Args:
            config_key: Ключ конфигурации (например 'A4_landscape', 'A3_landscape')
            layout_name: Имя создаваемого макета
            doc_type: Тип документации для выбора шрифта из DOC_TYPE_FONTS

        Returns:
            QgsPrintLayout или None при ошибке
        """
        # Загружаем конфигурацию если не загружена
        if not self._config:
            if not self.load_config():
                return None

        # Получаем параметры для выбранного формата
        params = self._config.get(config_key)
        if not params:
            log_error(f"Msm_34_1: Ключ '{config_key}' не найден в конфигурации "
                      f"(доступны: {', '.join(self._config.keys())})")
            return None

        try:
            # Шрифт из базы данных (font_family в params)
            self._font_family = str(params['font_family'])
            self._ensure_font_registered(self._font_family)

            # Создаем макет
            self._layout = QgsPrintLayout(QgsProject.instance())
            self._layout.initializeDefaults()
            self._layout.setName(layout_name)

            # Сохраняем config_key как customProperty для использования
            # в Msm_34_2.shift_extent_for_legend (mode lookup без передачи
            # config_key через API сигнатуру M_34.adapt_legend).
            self._layout.setCustomProperty('layout/config_key', config_key)

            # Настраиваем страницу
            self._setup_page(params)

            # Добавляем направляющие (отступы по ГОСТ)
            self._add_guides(params)

            # Добавляем элементы
            self._add_main_map(params)
            self._add_overview_map(params)
            self._add_legend(params)
            self._add_title_label(params)
            self._add_appendix_label(params)
            self._add_north_arrow(params)

            log_info(f"Msm_34_1: Макет '{layout_name}' создан программно ({config_key})")
            return self._layout

        except Exception as e:
            log_error(f"Msm_34_1: Ошибка создания макета: {e}")
            return None

    def _setup_page(self, params: Dict[str, Any]) -> None:
        """
        Настройка страницы макета

        Args:
            params: Параметры из конфигурации
        """
        page = self._layout.pageCollection().page(0)

        width = params.get('page_width', 297)
        height = params.get('page_height', 210)

        page.setPageSize(QgsLayoutSize(width, height, Qgis.LayoutUnit.Millimeters))

        # 300 DPI - требование Приказа Росреестра П/0148 (с изм. от 22.10.2024)
        self._layout.renderContext().setDpi(EXPORT_DPI_ROSREESTR)

        log_info(f"Msm_34_1: Страница настроена: {width}x{height} мм, DPI={EXPORT_DPI_ROSREESTR}")

    def _add_guides(self, params: Dict[str, Any]) -> None:
        """
        Добавление направляющих (guides)

        Два уровня:
        1. Рамка (margin) — отступы от края листа (ГОСТ 2.301: 20/5/5/5)
        2. Padding — внутренние отступы от рамки для подгонки элементов

        Args:
            params: Параметры из конфигурации
        """
        page_width = params.get('page_width', 297)
        page_height = params.get('page_height', 210)

        # Рамка: отступы от края листа (ГОСТ 2.301)
        margin_left = 20   # мм (для подшивки)
        margin_right = 5   # мм
        margin_top = 5     # мм
        margin_bottom = 5  # мм

        # Padding: внутренние отступы от рамки
        padding = 5

        guide_collection = self._layout.guides()
        page = self._layout.pageCollection().page(0)

        # --- Рамка (4 направляющие) ---

        guide_collection.addGuide(QgsLayoutGuide(
            Qt.Orientation.Vertical,
            QgsLayoutMeasurement(margin_left, Qgis.LayoutUnit.Millimeters),
            page
        ))
        guide_collection.addGuide(QgsLayoutGuide(
            Qt.Orientation.Vertical,
            QgsLayoutMeasurement(page_width - margin_right, Qgis.LayoutUnit.Millimeters),
            page
        ))
        guide_collection.addGuide(QgsLayoutGuide(
            Qt.Orientation.Horizontal,
            QgsLayoutMeasurement(margin_top, Qgis.LayoutUnit.Millimeters),
            page
        ))
        guide_collection.addGuide(QgsLayoutGuide(
            Qt.Orientation.Horizontal,
            QgsLayoutMeasurement(page_height - margin_bottom, Qgis.LayoutUnit.Millimeters),
            page
        ))

        # --- Padding (4 направляющие внутри рамки) ---

        guide_collection.addGuide(QgsLayoutGuide(
            Qt.Orientation.Vertical,
            QgsLayoutMeasurement(margin_left + padding, Qgis.LayoutUnit.Millimeters),
            page
        ))
        guide_collection.addGuide(QgsLayoutGuide(
            Qt.Orientation.Vertical,
            QgsLayoutMeasurement(page_width - margin_right - padding, Qgis.LayoutUnit.Millimeters),
            page
        ))
        guide_collection.addGuide(QgsLayoutGuide(
            Qt.Orientation.Horizontal,
            QgsLayoutMeasurement(margin_top + padding, Qgis.LayoutUnit.Millimeters),
            page
        ))
        guide_collection.addGuide(QgsLayoutGuide(
            Qt.Orientation.Horizontal,
            QgsLayoutMeasurement(page_height - margin_bottom - padding, Qgis.LayoutUnit.Millimeters),
            page
        ))

        log_info(
            f"Msm_34_1: Направляющие: рамка ({margin_left}/{margin_right}/{margin_top}/{margin_bottom}), "
            f"padding {padding} мм"
        )

    def _add_main_map(self, params: Dict[str, Any]) -> Optional[QgsLayoutItemMap]:
        """
        Добавление основной карты

        Args:
            params: Параметры из конфигурации

        Returns:
            QgsLayoutItemMap или None
        """
        x = params.get('main_map_x', 10)
        y = params.get('main_map_y', 35)
        width = params.get('main_map_width', 276)
        height = params.get('main_map_height', 109)

        ref_point = self._REF_POINTS[params['main_map_ref_point']]

        map_item = QgsLayoutItemMap(self._layout)
        map_item.setId('main_map')
        map_item.setReferencePoint(ref_point)

        # Позиция и размер
        map_item.attemptMove(QgsLayoutPoint(x, y, Qgis.LayoutUnit.Millimeters))
        map_item.attemptResize(QgsLayoutSize(width, height, Qgis.LayoutUnit.Millimeters))

        # Рамка и фон
        map_item.setFrameEnabled(True)
        map_item.setBackgroundEnabled(True)

        # Тема карты задаётся вызывающим кодом (Fsm_1_4_5, F_6_6 и т.д.)

        self._layout.addLayoutItem(map_item)
        log_info(f"Msm_34_1: Добавлена main_map ({x}, {y}, {width}x{height})")

        return map_item

    def _add_overview_map(self, params: Dict[str, Any]) -> Optional[QgsLayoutItemMap]:
        """
        Добавление обзорной карты

        Args:
            params: Параметры из конфигурации

        Returns:
            QgsLayoutItemMap или None
        """
        x = params.get('overview_map_x', 220)
        y = params.get('overview_map_y', 150)
        width = params.get('overview_map_width', 66)
        height = params.get('overview_map_height', 49)

        ref_point = self._REF_POINTS[params['overview_map_ref_point']]

        map_item = QgsLayoutItemMap(self._layout)
        map_item.setId('overview_map')
        map_item.setReferencePoint(ref_point)

        # Позиция и размер
        map_item.attemptMove(QgsLayoutPoint(x, y, Qgis.LayoutUnit.Millimeters))
        map_item.attemptResize(QgsLayoutSize(width, height, Qgis.LayoutUnit.Millimeters))

        # Рамка и фон
        map_item.setFrameEnabled(True)
        map_item.setBackgroundEnabled(True)

        # Тема карты задаётся вызывающим кодом

        self._layout.addLayoutItem(map_item)
        log_info(f"Msm_34_1: Добавлена overview_map ({x}, {y}, {width}x{height})")

        return map_item

    def _add_legend(self, params: Dict[str, Any]) -> Optional[QgsLayoutItemLegend]:
        """
        Добавление легенды

        Args:
            params: Параметры из конфигурации

        Returns:
            QgsLayoutItemLegend или None
        """
        # Routing по legend_layout_mode (из v0.4 рефакторинга):
        # - dynamic → legend_dynamic_x/y/ref_point
        # - fixed_panel → legend_panel_x/y/ref_point
        # - outside → legend_outside_x/y/ref_point
        layout_mode = params.get('legend_layout_mode', LegendLayoutMode.DYNAMIC)
        prefix_map = {
            LegendLayoutMode.DYNAMIC: 'legend_dynamic_',
            LegendLayoutMode.FIXED_PANEL: 'legend_panel_',
            LegendLayoutMode.OUTSIDE: 'legend_outside_',
        }
        prefix = prefix_map.get(layout_mode)
        if prefix is None:
            raise ValueError(
                f"Msm_34_1: некорректный legend_layout_mode='{layout_mode}'"
            )

        x = float(params[f'{prefix}x'])
        y = float(params[f'{prefix}y'])
        ref_point_num = int(params[f'{prefix}ref_point'])
        ref_point = self._REF_POINTS[ref_point_num]

        log_info(
            f"Msm_34_1: legend mode={layout_mode}, поля {prefix}x={x}, "
            f"{prefix}y={y}, {prefix}ref_point={ref_point_num}"
        )

        # Начальные значения (M_34.adapt_legend() может адаптировать после заполнения)
        column_count = 1
        symbol_width = 15
        symbol_height = 5

        legend = QgsLayoutItemLegend(self._layout)
        legend.setId('legend')
        legend.setReferencePoint(ref_point)

        # Позиция (указывает нижний левый угол)
        legend.attemptMove(QgsLayoutPoint(x, y, Qgis.LayoutUnit.Millimeters))

        # Настройки легенды
        legend.setTitle('Условные обозначения:')
        legend.setColumnCount(column_count)
        legend.setSymbolWidth(symbol_width)
        legend.setSymbolHeight(symbol_height)

        # Символ переноса строки для подписей легенды
        # Текст будет разбит по \n (применяется в Fsm_1_4_5_layout_manager.wrap_legend_text)
        legend.setWrapString('\n')

        # Frame state — единственное место установки: стратегии Msm_46_4
        # (DynamicPlacement → True, FixedPanelPlacement → False, OutsidePlacement → не трогает)
        # через M_46.plan_and_apply. Здесь не устанавливаем.
        legend.setBackgroundEnabled(True)

        # Настройка стилей текста легенды
        self._setup_legend_styles(legend, params)

        # Привязка к карте main_map для фильтрации (всегда)
        main_map = self._layout.itemById('main_map')
        if main_map and isinstance(main_map, QgsLayoutItemMap):
            legend.setLinkedMap(main_map)
            legend.setLegendFilterByMapEnabled(True)

        # Автоматическое обновление модели
        legend.setAutoUpdateModel(False)  # Отключаем для ручного управления

        self._layout.addLayoutItem(legend)
        log_info(f"Msm_34_1: Добавлена legend ({x}, {y}) с referencePoint=LowerLeft")

        return legend

    def _setup_legend_styles(self, legend: QgsLayoutItemLegend, params: Dict[str, Any]) -> None:
        """
        Настройка стилей текста легенды.

        Шрифт из DOC_TYPE_FONTS, стиль (bold/italic) из Base_layout.json (legend_font).
        Title получает bold дополнительно к стилю из базы.

        Args:
            legend: Элемент легенды
            params: Параметры из конфигурации
        """
        font_family = self._font_family
        font_size = 14
        text_color = QColor(50, 50, 50)
        font_style = str(params.get('legend_font', 'regular')).lower()

        base_bold = 'bold' in font_style
        base_italic = 'italic' in font_style

        # Title style (base + bold)
        title_style = legend.style(QgsLegendStyle.Title)
        title_format = QgsTextFormat()
        title_font = QFont(font_family, font_size)
        title_font.setBold(True)
        title_font.setItalic(base_italic)
        title_format.setFont(title_font)
        title_format.setSize(font_size)
        title_format.setColor(text_color)
        title_style.setTextFormat(title_format)
        title_style.setMargin(QgsLegendStyle.Bottom, 3)
        legend.setStyle(QgsLegendStyle.Title, title_style)

        # Group, Subgroup, SymbolLabel — одинаковый стиль из базы
        for style_type in [QgsLegendStyle.Group, QgsLegendStyle.Subgroup]:
            style = legend.style(style_type)
            fmt = QgsTextFormat()
            f = QFont(font_family, font_size)
            f.setBold(base_bold)
            f.setItalic(base_italic)
            fmt.setFont(f)
            fmt.setSize(font_size)
            fmt.setColor(text_color)
            style.setTextFormat(fmt)
            if style_type == QgsLegendStyle.Subgroup:
                style.setMargin(QgsLegendStyle.Top, 1)
            legend.setStyle(style_type, style)

        # SymbolLabel style (из базы + margins)
        symbol_style = legend.style(QgsLegendStyle.SymbolLabel)
        symbol_format = QgsTextFormat()
        symbol_font = QFont(font_family, font_size)
        symbol_font.setBold(base_bold)
        symbol_font.setItalic(base_italic)
        symbol_format.setFont(symbol_font)
        symbol_format.setSize(font_size)
        symbol_format.setColor(text_color)
        symbol_style.setTextFormat(symbol_format)
        symbol_style.setMargin(QgsLegendStyle.Top, 2)
        symbol_style.setMargin(QgsLegendStyle.Left, 5)
        legend.setStyle(QgsLegendStyle.SymbolLabel, symbol_style)

        log_info(f"Msm_34_1: Стили легенды настроены ({font_family}, {font_style})")

    def _add_title_label(self, params: Dict[str, Any]) -> Optional[QgsLayoutItemLabel]:
        """
        Добавление заголовка

        Args:
            params: Параметры из конфигурации

        Returns:
            QgsLayoutItemLabel или None
        """
        x = params.get('title_label_x', 15)
        y = params.get('title_label_y', 10)
        width = params.get('title_label_width', 267)
        height = params.get('title_label_height', 25)
        font_family = self._font_family
        font_style = str(params.get('title_label_font', 'regular')).lower()

        ref_point = self._REF_POINTS[params['title_label_ref_point']]

        label = QgsLayoutItemLabel(self._layout)
        label.setId('title_label')
        label.setReferencePoint(ref_point)

        # Позиция и размер
        label.attemptMove(QgsLayoutPoint(x, y, Qgis.LayoutUnit.Millimeters))
        label.attemptResize(QgsLayoutSize(width, height, Qgis.LayoutUnit.Millimeters))

        # Шрифт (size=14 константа, стиль из базы)
        text_format = QgsTextFormat()
        font = QFont(font_family, 14)
        font.setBold('bold' in font_style)
        font.setItalic('italic' in font_style)
        text_format.setFont(font)
        text_format.setSize(14)
        label.setTextFormat(text_format)

        # Текст по умолчанию (будет заменен при заполнении)
        label.setText('')

        # Выравнивание по центру
        label.setHAlign(Qt.AlignmentFlag.AlignHCenter)
        label.setVAlign(Qt.AlignmentFlag.AlignVCenter)

        self._layout.addLayoutItem(label)
        log_info(f"Msm_34_1: Добавлен title_label ({x}, {y})")

        return label

    def _add_appendix_label(self, params: Dict[str, Any]) -> Optional[QgsLayoutItemLabel]:
        """
        Добавление номера приложения

        Args:
            params: Параметры из конфигурации

        Returns:
            QgsLayoutItemLabel или None
        """
        x = params.get('appendix_label_x', 247)
        y = params.get('appendix_label_y', 5)
        width = params.get('appendix_label_width', 35)
        height = params.get('appendix_label_height', 5)
        font_family = self._font_family
        font_style = str(params.get('appendix_label_font', 'regular')).lower()

        ref_point = self._REF_POINTS[params['appendix_label_ref_point']]

        label = QgsLayoutItemLabel(self._layout)
        label.setId('appendix_label')
        label.setReferencePoint(ref_point)

        # Позиция и размер
        label.attemptMove(QgsLayoutPoint(x, y, Qgis.LayoutUnit.Millimeters))
        label.attemptResize(QgsLayoutSize(width, height, Qgis.LayoutUnit.Millimeters))

        # Шрифт (size=14 константа, стиль из базы)
        text_format = QgsTextFormat()
        font = QFont(font_family, 14)
        font.setBold('bold' in font_style)
        font.setItalic('italic' in font_style)
        font.setUnderline(True)
        text_format.setFont(font)
        text_format.setSize(14)
        label.setTextFormat(text_format)

        # Текст по умолчанию
        label.setText('Приложение 1')

        # Выравнивание справа
        label.setHAlign(Qt.AlignmentFlag.AlignRight)
        label.setVAlign(Qt.AlignmentFlag.AlignTop)

        self._layout.addLayoutItem(label)
        log_info(f"Msm_34_1: Добавлен appendix_label ({x}, {y})")

        return label

    def _add_north_arrow(self, params: Dict[str, Any]) -> Optional[QgsLayoutItemPicture]:
        """
        Добавление стрелки севера

        Использует SVG из конфигурации (north_arrow_file).
        Путь относительный от data/svg/ плагина.

        Args:
            params: Параметры из конфигурации

        Returns:
            QgsLayoutItemPicture или None
        """
        x = params.get('north_arrow_x', 247)
        y = params.get('north_arrow_y', 40)
        width = params.get('north_arrow_width', 35)
        height = params.get('north_arrow_height', 35)
        svg_file = params.get('north_arrow_file', 'north_arrow_rus.svg')

        ref_point = self._REF_POINTS[params['north_arrow_ref_point']]

        picture = QgsLayoutItemPicture(self._layout)
        picture.setId('north_arrow')
        picture.setReferencePoint(ref_point)

        # Позиция и размер
        picture.attemptMove(QgsLayoutPoint(x, y, Qgis.LayoutUnit.Millimeters))
        picture.attemptResize(QgsLayoutSize(width, height, Qgis.LayoutUnit.Millimeters))

        # SVG из data/svg/ плагина (путь из конфигурации)
        plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        svg_path = os.path.join(plugin_dir, 'data', 'svg', svg_file)

        if os.path.exists(svg_path):
            picture.setPicturePath(svg_path)
            log_info(f"Msm_34_1: Добавлена north_arrow ({x}, {y}), SVG: {svg_file}")
        else:
            log_error(f"Msm_34_1: SVG не найден: {svg_path}")

        # Привязка к карте для вращения
        main_map = self._layout.itemById('main_map')
        if main_map and isinstance(main_map, QgsLayoutItemMap):
            picture.setLinkedMap(main_map)

        self._layout.addLayoutItem(picture)

        return picture

    def get_layout(self) -> Optional[QgsPrintLayout]:
        """
        Получить текущий созданный макет

        Returns:
            QgsPrintLayout или None
        """
        return self._layout

    def get_config(self, config_key: str = 'A4_landscape') -> Optional[Dict[str, Any]]:
        """
        Получить параметры конфигурации

        Args:
            config_key: Ключ конфигурации (например 'A4_landscape', 'A3_landscape')

        Returns:
            Dict параметров или None
        """
        if not self._config:
            self.load_config()

        return self._config.get(config_key) if self._config else None
