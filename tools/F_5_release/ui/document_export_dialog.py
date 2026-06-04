# -*- coding: utf-8 -*-
"""
Диалог выбора продуктов для экспорта документов

Функциональность:
    - Плоский список чекбоксов продуктов из ProductRegistry.get_products()
    - Доступность / tooltip / подтекст состава — ТОЛЬКО через describe()
      (non-mutating интроспекция; expand() при отрисовке НЕ вызывается)
    - Недоступный продукт: disabled + tooltip с искомыми слоями
    - Опция создания версии WGS-84 для перечней координат
    - Информация о папке сохранения

Продукты: Fsm_5_3_10_product_registry.py (ExportProduct, ProductRegistry)
Эталон UX: background_dialog.py (диалог F_5_2)
"""

from typing import List, Dict, Any

from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QGroupBox, QScrollArea, QWidget
)
from qgis.PyQt.QtCore import Qt

from Daman_QGIS.core.base_responsive_dialog import BaseResponsiveDialog
from Daman_QGIS.utils import path_for_display, log_warning

from ..submodules.Fsm_5_3_10_product_registry import (
    ExportProduct, ProductRegistry
)


class DocumentExportDialog(BaseResponsiveDialog):
    """Диалог выбора продуктов для экспорта документов"""

    # Адаптивные размеры диалога (компактные, как у background_dialog)
    WIDTH_RATIO = 0.30
    HEIGHT_RATIO = 0.45
    MIN_WIDTH = 360
    MAX_WIDTH = 520
    MIN_HEIGHT = 300
    MAX_HEIGHT = 460

    def __init__(
        self,
        parent=None,
        output_folder: str = ""
    ):
        """
        Инициализация диалога

        Args:
            parent: Родительский виджет
            output_folder: Путь к папке сохранения
        """
        super().__init__(parent)
        self.output_folder = output_folder
        # {product_id: QCheckBox} — только для enabled-продуктов учитываем в
        # выборе; disabled-чекбоксы тоже хранятся (для единообразия), но никогда
        # не отмечены.
        self.checkboxes: Dict[str, QCheckBox] = {}
        self.create_wgs84_checkbox = None

        self.setWindowTitle("Выберите документы для экспорта")

        self._init_ui()

    def _init_ui(self):
        """Инициализация интерфейса"""
        layout = QVBoxLayout()

        # === ЗАГОЛОВОК ===
        header_label = QLabel("<b>Выберите документы для экспорта:</b>")
        layout.addWidget(header_label)

        # === СПИСОК ПРОДУКТОВ (SCROLL AREA) ===
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumHeight(160)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout()
        scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll_layout.setSpacing(6)

        products = ProductRegistry.get_products()
        if not products:
            no_products_label = QLabel(
                "<i>Нет доступных продуктов экспорта</i>"
            )
            no_products_label.setStyleSheet("color: #999; padding: 20px;")
            scroll_layout.addWidget(no_products_label)
        else:
            for product in products:
                widget = self._create_product_widget(product)
                scroll_layout.addWidget(widget)

        scroll_widget.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

        # === ОПЦИИ ===
        options_group = QGroupBox("Опции")
        options_layout = QVBoxLayout()

        self.create_wgs84_checkbox = QCheckBox(
            "Создать версию в WGS-84 для перечней координат"
        )
        self.create_wgs84_checkbox.setChecked(False)
        options_layout.addWidget(self.create_wgs84_checkbox)

        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        # === ВЫБОР ВСЕХ / СНЯТЬ ВСЕ ===
        selection_layout = QHBoxLayout()

        select_all_btn = QPushButton("Выбрать все")
        select_all_btn.clicked.connect(self._select_all)
        selection_layout.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("Снять все")
        deselect_all_btn.clicked.connect(self._deselect_all)
        selection_layout.addWidget(deselect_all_btn)

        selection_layout.addStretch()
        layout.addLayout(selection_layout)

        # === ИНФОРМАЦИЯ О ПАПКЕ СОХРАНЕНИЯ ===
        if self.output_folder:
            folder_info = QLabel(
                f"<i>Файлы будут сохранены в: {path_for_display(self.output_folder)}</i>"
            )
            folder_info.setStyleSheet("color: #555; padding: 5px;")
            folder_info.setWordWrap(True)
            layout.addWidget(folder_info)

        # === КНОПКИ OK / CANCEL ===
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        ok_btn = QPushButton("Экспортировать")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        buttons_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_btn)

        layout.addLayout(buttons_layout)

        self.setLayout(layout)

    def _create_product_widget(self, product: ExportProduct) -> QWidget:
        """
        Создать виджет одного продукта: чекбокс + серый подтекст состава.

        Доступность, tooltip и подтекст берутся ТОЛЬКО через
        ProductRegistry.describe() (non-mutating). expand() здесь НЕ вызывается.

        Args:
            product: Продукт экспорта (ExportProduct).

        Returns:
            QWidget с чекбоксом и подтекстом.
        """
        info = self._describe_safe(product.product_id)
        available = bool(info.get('available'))

        container = QWidget()
        container_layout = QVBoxLayout()
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(1)

        checkbox = QCheckBox(product.name)
        checkbox.setChecked(False)
        checkbox.setEnabled(available)

        if available:
            # tooltip — описание продукта (краткое назначение)
            checkbox.setToolTip(product.description)
            subtitle = self._compose_subtitle(info)
        else:
            # Недоступный продукт: disabled + tooltip с искомыми слоями/паттернами
            checkbox.setToolTip(self._compose_unavailable_tooltip(info))
            subtitle = "Нет слоёв для этого документа"

        container_layout.addWidget(checkbox)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setWordWrap(True)
            subtitle_label.setStyleSheet(
                "color: #777; font-size: 11px; padding-left: 22px;"
            )
            container_layout.addWidget(subtitle_label)

        container.setLayout(container_layout)

        self.checkboxes[product.product_id] = checkbox
        return container

    @staticmethod
    def _describe_safe(product_id: str) -> Dict[str, Any]:
        """
        Безопасно получить describe()-словарь продукта.

        describe() уже перехватывает свои исключения и возвращает безопасный
        словарь; обёртка добавляет защиту на случай неожиданного сбоя, чтобы
        отрисовка диалога не падала.

        Args:
            product_id: Идентификатор продукта.

        Returns:
            Словарь describe(): {available, groups, searched_patterns}.
        """
        try:
            return ProductRegistry.describe(product_id)
        except Exception as e:
            log_warning(
                f"F_5_3: ошибка describe() продукта '{product_id}': {e}"
            )
            return {'available': False, 'groups': [], 'searched_patterns': []}

    @staticmethod
    def _compose_subtitle(info: Dict[str, Any]) -> str:
        """
        Собрать серый подтекст состава доступного продукта одной строкой.

        Формат: группы через "; ", для каждой группы — имя и (если есть) этапы.
        Пример: «ОКС: Этап 1, Этап 2, Итог; ПО».

        Args:
            info: Словарь describe() продукта.

        Returns:
            Строка подтекста (может быть пустой).
        """
        groups = info.get('groups') or []
        parts: List[str] = []
        for grp in groups:
            name = grp.get('name', '')
            stages = grp.get('stages') or []
            if stages:
                parts.append(f"{name}: {', '.join(stages)}")
            elif name:
                parts.append(name)
        return "; ".join(parts)

    @staticmethod
    def _compose_unavailable_tooltip(info: Dict[str, Any]) -> str:
        """
        Собрать tooltip недоступного продукта со списком искомых слоёв.

        Args:
            info: Словарь describe() продукта.

        Returns:
            Текст tooltip.
        """
        patterns = info.get('searched_patterns') or []
        if not patterns:
            return "Нет слоёв для этого документа"
        searched = "\n".join(f"  - {p}" for p in patterns)
        return "Нет слоёв для этого документа.\nИскомые слои:\n" + searched

    def _select_all(self):
        """Выбрать все доступные (enabled) продукты"""
        for checkbox in self.checkboxes.values():
            if checkbox.isEnabled():
                checkbox.setChecked(True)

    def _deselect_all(self):
        """Снять выбор со всех продуктов"""
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(False)

    def get_selected_product_ids(self) -> List[str]:
        """
        Получить список product_id выбранных продуктов.

        Returns:
            Список product_id отмеченных enabled-чекбоксов в порядке отрисовки.
        """
        selected: List[str] = []
        for product in ProductRegistry.get_products():
            checkbox = self.checkboxes.get(product.product_id)
            if checkbox is not None and checkbox.isEnabled() and checkbox.isChecked():
                selected.append(product.product_id)
        return selected

    def get_create_wgs84(self) -> bool:
        """
        Получить значение опции создания WGS-84.

        Returns:
            True если нужно создавать версию WGS-84.
        """
        return self.create_wgs84_checkbox.isChecked() if self.create_wgs84_checkbox else False
