# -*- coding: utf-8 -*-
"""
Base responsive dialog with screen-adaptive sizing and scroll support.

Subclasses override class constants to customize behavior:
- WIDTH_RATIO / HEIGHT_RATIO: fraction of available screen (0.0 - 1.0)
- MIN_WIDTH / MAX_WIDTH / MIN_HEIGHT / MAX_HEIGHT: pixel bounds
"""
from typing import Optional, List

from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QWidget, QLayout, QApplication
from qgis.gui import QgsScrollArea


class BaseResponsiveDialog(QDialog):
    """Базовый диалог с адаптивным размером и поддержкой скролла."""

    WIDTH_RATIO = 0.55
    HEIGHT_RATIO = 0.75
    MIN_WIDTH = 500
    MAX_WIDTH = 1200
    MIN_HEIGHT = 400
    MAX_HEIGHT = 900

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._apply_screen_sizing()

    def _apply_screen_sizing(self) -> None:
        """Рассчитать и применить размер диалога по доступной области экрана."""
        screen = self.screen()
        if not screen:
            screen = QApplication.primaryScreen()
        if not screen:
            self.resize(self.MIN_WIDTH, self.MIN_HEIGHT)
            return

        avail = screen.availableGeometry()
        w = max(self.MIN_WIDTH, min(int(avail.width() * self.WIDTH_RATIO), self.MAX_WIDTH))
        h = max(self.MIN_HEIGHT, min(int(avail.height() * self.HEIGHT_RATIO), self.MAX_HEIGHT))
        self.resize(w, h)
        self._center_on_parent(avail)

    def _center_on_parent(self, avail_geometry=None) -> None:
        """Центрировать диалог на parent widget или на экране."""
        parent = self.parentWidget()
        if parent:
            parent_geo = parent.geometry()
            x = parent_geo.x() + (parent_geo.width() - self.width()) // 2
            y = parent_geo.y() + (parent_geo.height() - self.height()) // 2
            self.move(max(0, x), max(0, y))
            return

        if avail_geometry is None:
            screen = self.screen() or QApplication.primaryScreen()
            if not screen:
                return
            avail_geometry = screen.availableGeometry()

        x = avail_geometry.x() + (avail_geometry.width() - self.width()) // 2
        y = avail_geometry.y() + (avail_geometry.height() - self.height()) // 2
        self.move(x, y)

    def _create_scroll_wrapper(
        self,
        content_widget: QWidget,
        vertical_only: bool = True
    ) -> QgsScrollArea:
        """Обернуть widget в QgsScrollArea.

        :param content_widget: Виджет с содержимым для скролла
        :param vertical_only: Только вертикальный скролл (убирает горизонтальный)
        :return: Настроенный QgsScrollArea
        """
        scroll = QgsScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QgsScrollArea.Shape.NoFrame)

        if vertical_only and hasattr(scroll, 'setVerticalOnly'):
            scroll.setVerticalOnly(True)

        scroll.setWidget(content_widget)
        return scroll

    def _build_scrollable_layout(
        self,
        content_layout: QLayout,
        button_layout: Optional[QLayout] = None,
        header_widgets: Optional[List[QWidget]] = None,
        vertical_only: bool = True
    ) -> QVBoxLayout:
        """Собрать layout: header (фиксирован) + scroll(content) + buttons (фиксированы).

        :param content_layout: Layout с основным содержимым (будет внутри скролла)
        :param button_layout: Layout с кнопками (снаружи скролла, всегда видны)
        :param header_widgets: Виджеты заголовка (снаружи скролла, сверху)
        :param vertical_only: Только вертикальный скролл
        :return: Главный QVBoxLayout (уже установлен на self)
        """
        main_layout = QVBoxLayout(self)

        if header_widgets:
            for widget in header_widgets:
                main_layout.addWidget(widget)

        scroll_content = QWidget()
        scroll_content.setLayout(content_layout)
        scroll_area = self._create_scroll_wrapper(scroll_content, vertical_only)
        main_layout.addWidget(scroll_area, stretch=1)

        if button_layout:
            main_layout.addLayout(button_layout)

        return main_layout
