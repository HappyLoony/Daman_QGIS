# -*- coding: utf-8 -*-
"""
Msm_34_1: LayoutBuilder - Программная генерация макетов из JSON конфигурации

Универсальный генератор макетов из JSON конфигураций.
Конфигурация загружается из Base_layout_{layout_type}.json через API.

Поддерживаемые типы макетов:
- F_1_4: Графика к запросу (схема расположения)
- F_5_1: Чертёж планировки территории (будущее)
- F_5_2: Чертёж межевания территории (будущее)

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
from Daman_QGIS.constants import EXPORT_DPI_ROSREESTR


class LayoutBuilder:
    """
    Программный генератор макетов из JSON конфигурации

    Создает QgsPrintLayout с элементами (набор зависит от конфигурации):
    - Страница (page_width, page_height, print_resolution)
    - Основная карта (main_map)
    - Обзорная карта (overview_map)
    - Легенда (legend)
    - Заголовок (title_label)
    - Номер приложения (appendix_label)
    - Стрелка севера (north_arrow)
    - Штамп (stamp) - для чертежей
    """

    def __init__(self, layout_type: str = 'F_1_4'):
        """
        Инициализация генератора

        Args:
            layout_type: Тип макета (F_1_4, F_5_1, F_5_2 и т.д.)
        """
        self._layout_type = layout_type
        self._config_file = f'Base_layout_{layout_type}.json'
        self._config: Optional[Dict[str, Any]] = None
        self._layout: Optional[QgsPrintLayout] = None

    def load_config(self) -> bool:
        """
        Загрузка конфигурации из Base_layout_{layout_type}.json

        Returns:
            bool: True если конфигурация загружена успешно
        """
        try:
            loader = BaseReferenceLoader()
            self._config = loader._load_json(self._config_file)

            if not self._config:
                log_error(f"Msm_34_1: Не удалось загрузить {self._config_file}")
                return False

            # Проверяем наличие обязательных ключей
            if 'landscape' not in self._config and 'portrait' not in self._config:
                log_error(f"Msm_34_1: Конфигурация {self._config_file} не содержит landscape/portrait")
                return False

            log_info(f"Msm_34_1: Конфигурация {self._layout_type} загружена "
                     f"(landscape: {len(self._config.get('landscape', {}))}, "
                     f"portrait: {len(self._config.get('portrait', {}))} параметров)")
            return True

        except Exception as e:
            log_error(f"Msm_34_1: Ошибка загрузки конфигурации {self._config_file}: {e}")
            return False

    def build(self, orientation: str = 'landscape', layout_name: str = 'Layout') -> Optional[QgsPrintLayout]:
        """
        Создание макета из конфигурации

        Args:
            orientation: 'landscape' или 'portrait'
            layout_name: Имя создаваемого макета

        Returns:
            QgsPrintLayout или None при ошибке
        """
        # Загружаем конфигурацию если не загружена
        if not self._config:
            if not self.load_config():
                return None

        # Получаем параметры для выбранной ориентации
        params = self._config.get(orientation)
        if not params:
            log_error(f"Msm_34_1: Ориентация '{orientation}' не найдена в конфигурации")
            return None

        try:
            # Создаем макет
            self._layout = QgsPrintLayout(QgsProject.instance())
            self._layout.initializeDefaults()
            self._layout.setName(layout_name)

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

            log_info(f"Msm_34_1: Макет '{layout_name}' создан программно ({orientation})")
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
        # Разрешение 300 DPI согласно Приказу Росреестра от 19.04.2022 N П/0148
        dpi = params.get('print_resolution', EXPORT_DPI_ROSREESTR)

        page.setPageSize(QgsLayoutSize(width, height, Qgis.LayoutUnit.Millimeters))

        # Устанавливаем DPI для рендеринга макета
        # 300 DPI - требование Приказа Росреестра П/0148 (с изм. от 22.10.2024)
        self._layout.renderContext().setDpi(dpi)

        log_info(f"Msm_34_1: Страница настроена: {width}x{height} мм, DPI={dpi}")

    def _add_guides(self, params: Dict[str, Any]) -> None:
        """
        Добавление направляющих (guides) по ГОСТ

        Отступы от границ листа:
        - Левая: 20 мм (для подшивки)
        - Правая, верхняя, нижняя: 5 мм

        Args:
            params: Параметры из конфигурации
        """
        page_width = params.get('page_width', 297)
        page_height = params.get('page_height', 210)

        # Отступы по ГОСТ
        margin_left = 20  # мм (для подшивки)
        margin_right = 5  # мм
        margin_top = 5    # мм
        margin_bottom = 5 # мм

        guide_collection = self._layout.guides()
        page = self._layout.pageCollection().page(0)

        # Вертикальные направляющие (левая и правая границы рабочей области)
        # Левая направляющая - 20 мм от левого края
        guide_left = QgsLayoutGuide(
            Qt.Orientation.Vertical,
            QgsLayoutMeasurement(margin_left, Qgis.LayoutUnit.Millimeters),
            page
        )
        guide_collection.addGuide(guide_left)

        # Правая направляющая - 5 мм от правого края
        guide_right = QgsLayoutGuide(
            Qt.Orientation.Vertical,
            QgsLayoutMeasurement(page_width - margin_right, Qgis.LayoutUnit.Millimeters),
            page
        )
        guide_collection.addGuide(guide_right)

        # Горизонтальные направляющие (верхняя и нижняя границы рабочей области)
        # Верхняя направляющая - 5 мм от верхнего края
        guide_top = QgsLayoutGuide(
            Qt.Orientation.Horizontal,
            QgsLayoutMeasurement(margin_top, Qgis.LayoutUnit.Millimeters),
            page
        )
        guide_collection.addGuide(guide_top)

        # Нижняя направляющая - 5 мм от нижнего края
        guide_bottom = QgsLayoutGuide(
            Qt.Orientation.Horizontal,
            QgsLayoutMeasurement(page_height - margin_bottom, Qgis.LayoutUnit.Millimeters),
            page
        )
        guide_collection.addGuide(guide_bottom)

        log_info(f"Msm_34_1: Направляющие добавлены (левая: {margin_left} мм, остальные: {margin_right} мм)")

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
        frame = params.get('main_map_frame', True)
        background = params.get('main_map_background', True)
        theme = params.get('main_map_theme', 'F_1_4_1_main_map')

        map_item = QgsLayoutItemMap(self._layout)
        map_item.setId('main_map')

        # Позиция и размер
        map_item.attemptMove(QgsLayoutPoint(x, y, Qgis.LayoutUnit.Millimeters))
        map_item.attemptResize(QgsLayoutSize(width, height, Qgis.LayoutUnit.Millimeters))

        # Рамка и фон
        map_item.setFrameEnabled(frame)
        map_item.setBackgroundEnabled(background)

        # Тема карты (если существует)
        if QgsProject.instance().mapThemeCollection().hasMapTheme(theme):
            map_item.setFollowVisibilityPreset(True)
            map_item.setFollowVisibilityPresetName(theme)

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
        frame = params.get('overview_map_frame', True)
        background = params.get('overview_map_background', True)
        theme = params.get('overview_map_theme', 'F_1_4_2_overview_map')

        map_item = QgsLayoutItemMap(self._layout)
        map_item.setId('overview_map')

        # Позиция и размер
        map_item.attemptMove(QgsLayoutPoint(x, y, Qgis.LayoutUnit.Millimeters))
        map_item.attemptResize(QgsLayoutSize(width, height, Qgis.LayoutUnit.Millimeters))

        # Рамка и фон
        map_item.setFrameEnabled(frame)
        map_item.setBackgroundEnabled(background)

        # Тема карты
        if QgsProject.instance().mapThemeCollection().hasMapTheme(theme):
            map_item.setFollowVisibilityPreset(True)
            map_item.setFollowVisibilityPresetName(theme)

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
        x = params.get('legend_x', 10)
        y = params.get('legend_y', 199)
        title = params.get('legend_title', 'Условные обозначения:')
        filter_by_map = params.get('legend_filter_by_map', True)
        column_count = params.get('legend_column_count', 1)
        symbol_width = params.get('legend_symbol_width', 15)
        symbol_height = params.get('legend_symbol_height', 5)

        legend = QgsLayoutItemLegend(self._layout)
        legend.setId('legend')

        # Точка привязки - нижний левый угол (как в QPT referencePoint="6")
        legend.setReferencePoint(QgsLayoutItem.LowerLeft)

        # Позиция (указывает нижний левый угол)
        legend.attemptMove(QgsLayoutPoint(x, y, Qgis.LayoutUnit.Millimeters))

        # Настройки легенды
        legend.setTitle(title)
        legend.setColumnCount(column_count)
        legend.setSymbolWidth(symbol_width)
        legend.setSymbolHeight(symbol_height)

        # Символ переноса строки для подписей легенды
        # Текст будет разбит по \n (применяется в Fsm_1_4_5_layout_manager.wrap_legend_text)
        legend.setWrapString('\n')

        # Рамка и фон
        legend.setFrameEnabled(True)
        legend.setBackgroundEnabled(True)

        # Настройка стилей текста легенды (GOST 2.304)
        self._setup_legend_styles(legend)

        # Привязка к карте main_map для фильтрации
        if filter_by_map:
            main_map = self._layout.itemById('main_map')
            if main_map and isinstance(main_map, QgsLayoutItemMap):
                legend.setLinkedMap(main_map)
                legend.setLegendFilterByMapEnabled(True)

        # Автоматическое обновление модели
        legend.setAutoUpdateModel(False)  # Отключаем для ручного управления

        self._layout.addLayoutItem(legend)
        log_info(f"Msm_34_1: Добавлена legend ({x}, {y}) с referencePoint=LowerLeft")

        return legend

    def _setup_legend_styles(self, legend: QgsLayoutItemLegend) -> None:
        """
        Настройка стилей текста легенды по ГОСТ

        Устанавливает шрифт GOST 2.304 для всех компонентов легенды:
        - Title: Bold Italic, 14pt
        - Group: Italic, 14pt
        - Subgroup: Italic, 14pt
        - SymbolLabel: Italic, 14pt

        Args:
            legend: Элемент легенды
        """
        # Шрифт GOST 2.304 для всех элементов
        font_family = 'GOST 2.304'
        font_size = 14
        text_color = QColor(50, 50, 50)  # Темно-серый как в QPT

        # Title style (Bold Italic)
        title_style = legend.style(QgsLegendStyle.Title)
        title_format = QgsTextFormat()
        title_font = QFont(font_family, font_size)
        title_font.setBold(True)
        title_font.setItalic(True)
        title_format.setFont(title_font)
        title_format.setSize(font_size)
        title_format.setColor(text_color)
        title_style.setTextFormat(title_format)
        title_style.setMargin(QgsLegendStyle.Bottom, 3)
        legend.setStyle(QgsLegendStyle.Title, title_style)

        # Group style (Italic)
        group_style = legend.style(QgsLegendStyle.Group)
        group_format = QgsTextFormat()
        group_font = QFont(font_family, font_size)
        group_font.setItalic(True)
        group_format.setFont(group_font)
        group_format.setSize(font_size)
        group_format.setColor(text_color)
        group_style.setTextFormat(group_format)
        legend.setStyle(QgsLegendStyle.Group, group_style)

        # Subgroup style (Italic)
        subgroup_style = legend.style(QgsLegendStyle.Subgroup)
        subgroup_format = QgsTextFormat()
        subgroup_font = QFont(font_family, font_size)
        subgroup_font.setItalic(True)
        subgroup_format.setFont(subgroup_font)
        subgroup_format.setSize(font_size)
        subgroup_format.setColor(text_color)
        subgroup_style.setTextFormat(subgroup_format)
        subgroup_style.setMargin(QgsLegendStyle.Top, 1)
        legend.setStyle(QgsLegendStyle.Subgroup, subgroup_style)

        # SymbolLabel style (Italic)
        symbol_style = legend.style(QgsLegendStyle.SymbolLabel)
        symbol_format = QgsTextFormat()
        symbol_font = QFont(font_family, font_size)
        symbol_font.setItalic(True)
        symbol_format.setFont(symbol_font)
        symbol_format.setSize(font_size)
        symbol_format.setColor(text_color)
        symbol_style.setTextFormat(symbol_format)
        symbol_style.setMargin(QgsLegendStyle.Top, 2)
        symbol_style.setMargin(QgsLegendStyle.Left, 5)
        legend.setStyle(QgsLegendStyle.SymbolLabel, symbol_style)

        log_info("Msm_34_1: Стили легенды настроены (GOST 2.304)")

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
        font_family = params.get('title_label_font', 'GOST 2.304')
        font_size = params.get('title_label_font_size', 14)
        font_bold = params.get('title_label_font_bold', True)
        font_italic = params.get('title_label_font_italic', False)

        label = QgsLayoutItemLabel(self._layout)
        label.setId('title_label')

        # Позиция и размер
        label.attemptMove(QgsLayoutPoint(x, y, Qgis.LayoutUnit.Millimeters))
        label.attemptResize(QgsLayoutSize(width, height, Qgis.LayoutUnit.Millimeters))

        # Шрифт
        text_format = QgsTextFormat()
        font = QFont(font_family, font_size)
        if font_bold:
            font.setBold(True)
        if font_italic:
            font.setItalic(True)
        text_format.setFont(font)
        text_format.setSize(font_size)
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
        font_family = params.get('appendix_label_font', 'GOST 2.304')
        font_size = params.get('appendix_label_font_size', 14)
        underline = params.get('appendix_label_underline', True)

        label = QgsLayoutItemLabel(self._layout)
        label.setId('appendix_label')

        # Позиция и размер
        label.attemptMove(QgsLayoutPoint(x, y, Qgis.LayoutUnit.Millimeters))
        label.attemptResize(QgsLayoutSize(width, height, Qgis.LayoutUnit.Millimeters))

        # Шрифт
        text_format = QgsTextFormat()
        font = QFont(font_family, font_size)
        if underline:
            font.setUnderline(True)
        text_format.setFont(font)
        text_format.setSize(font_size)
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

        picture = QgsLayoutItemPicture(self._layout)
        picture.setId('north_arrow')

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

    def get_config(self, orientation: str = 'landscape') -> Optional[Dict[str, Any]]:
        """
        Получить параметры конфигурации

        Args:
            orientation: 'landscape' или 'portrait'

        Returns:
            Dict параметров или None
        """
        if not self._config:
            self.load_config()

        return self._config.get(orientation) if self._config else None
