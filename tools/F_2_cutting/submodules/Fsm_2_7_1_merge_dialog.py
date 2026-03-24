# -*- coding: utf-8 -*-
"""
Fsm_2_7_1_MergeDialog - Диалог выбора контуров для объединения

GUI диалог с таблицей для выбора контуров нарезки,
которые нужно объединить в единый земельный участок.

Функционал:
- ComboBox для выбора слоя-источника (Раздел)
- Таблица с checkbox для множественного выбора (минимум 2)
- Кнопка "Выбрать по ЗПР" - групповой выбор
- Кнопка "Выделить на карте"
- Кнопка "Объединить" (активна при выборе >= 2)
"""

from typing import Optional, List, Dict, Any, Callable

from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QCheckBox, QWidget,
    QMessageBox
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsVectorLayer, QgsFeature
from qgis.gui import QgsRubberBand

from Daman_QGIS.core.base_responsive_dialog import BaseResponsiveDialog
from Daman_QGIS.utils import log_info, log_warning


class Fsm_2_7_1_MergeDialog(BaseResponsiveDialog):
    """Диалог выбора контуров для объединения

    Attributes:
        layers: Список доступных слоёв Раздел
        merge_callback: Функция объединения (source_layer, feature_ids) -> result
    """

    # Адаптивные размеры диалога
    WIDTH_RATIO = 0.62
    HEIGHT_RATIO = 0.70
    MIN_WIDTH = 700
    MAX_WIDTH = 1050
    MIN_HEIGHT = 480
    MAX_HEIGHT = 750

    # Индексы колонок таблицы
    COL_CHECK = 0
    COL_ID = 1
    COL_USLOV_KN = 2
    COL_KN = 3
    COL_AREA = 4
    COL_ADDRESS = 5
    COL_FID = 6  # Скрытая колонка с fid

    # Минимальное количество контуров для объединения
    MIN_MERGE_COUNT = 2

    def __init__(
        self,
        parent: Optional[QWidget],
        layers: List[QgsVectorLayer],
        merge_callback: Callable[[QgsVectorLayer, List[int]], Dict[str, Any]]
    ) -> None:
        """Инициализация диалога

        Args:
            parent: Родительский виджет
            layers: Список доступных слоёв Раздел
            merge_callback: Callback функция для выполнения объединения
        """
        super().__init__(parent)
        self.layers = layers
        self.merge_callback = merge_callback
        self.current_layer: Optional[QgsVectorLayer] = None
        self._rubber_band: Optional[QgsRubberBand] = None

        self.setWindowTitle("Объединение контуров нарезки")
        self.setModal(True)

        self._setup_ui()
        self._connect_signals()

        # Загрузить первый слой по умолчанию
        if self.layers:
            self._on_layer_changed(0)

    def _setup_ui(self) -> None:
        """Настройка UI"""
        layout = QVBoxLayout()

        # Заголовок
        title = QLabel("<h3>Объединение контуров в единый земельный участок</h3>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Описание
        description = QLabel(
            "Выберите минимум 2 контура для объединения.\n"
            "Смежные контуры будут объединены в Polygon, "
            "разнесённые - в MultiPolygon."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        # ComboBox выбора слоя
        layer_layout = QHBoxLayout()
        layer_layout.addWidget(QLabel("Слой-источник:"))

        self.layer_combo = QComboBox()
        for layer in self.layers:
            self.layer_combo.addItem(layer.name(), layer)
        layer_layout.addWidget(self.layer_combo, 1)
        layout.addLayout(layer_layout)

        # Таблица контуров
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "", "ID", "Услов_КН", "КН", "Площадь", "Адрес", "fid"
        ])
        self.table.horizontalHeader().setSectionResizeMode(
            self.COL_CHECK, QHeaderView.ResizeMode.Fixed
        )
        self.table.setColumnWidth(self.COL_CHECK, 30)
        self.table.setColumnWidth(self.COL_ID, 50)
        self.table.setColumnWidth(self.COL_USLOV_KN, 150)
        self.table.setColumnWidth(self.COL_KN, 150)
        self.table.setColumnWidth(self.COL_AREA, 100)
        self.table.horizontalHeader().setSectionResizeMode(
            self.COL_ADDRESS, QHeaderView.ResizeMode.Stretch
        )
        self.table.setColumnHidden(self.COL_FID, True)  # Скрыть колонку fid
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # Счётчик выбранных
        self.count_label = QLabel("Выбрано: 0 из 0 (минимум 2)")
        layout.addWidget(self.count_label)

        # Кнопки выбора
        select_layout = QHBoxLayout()

        self.select_all_btn = QPushButton("Выбрать все")
        self.select_all_btn.clicked.connect(self._on_select_all)
        select_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Снять все")
        self.deselect_all_btn.clicked.connect(self._on_deselect_all)
        select_layout.addWidget(self.deselect_all_btn)

        self.select_by_zpr_btn = QPushButton("Выбрать по ЗПР")
        self.select_by_zpr_btn.setToolTip(
            "Выбрать все контуры с одинаковым ЗПР-индексом"
        )
        self.select_by_zpr_btn.clicked.connect(self._on_select_by_zpr)
        select_layout.addWidget(self.select_by_zpr_btn)

        self.highlight_btn = QPushButton("Выделить на карте")
        self.highlight_btn.clicked.connect(self._on_highlight)
        select_layout.addWidget(self.highlight_btn)

        select_layout.addStretch()
        layout.addLayout(select_layout)

        # Кнопки действий
        action_layout = QHBoxLayout()
        action_layout.addStretch()

        self.merge_btn = QPushButton("Объединить")
        self.merge_btn.setEnabled(False)
        self.merge_btn.clicked.connect(self._on_merge)
        action_layout.addWidget(self.merge_btn)

        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.clicked.connect(self.reject)
        action_layout.addWidget(self.cancel_btn)

        layout.addLayout(action_layout)
        self.setLayout(layout)

    def _connect_signals(self) -> None:
        """Подключение сигналов"""
        self.layer_combo.currentIndexChanged.connect(self._on_layer_changed)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)

    def _rebuild_layer_combo(self) -> None:
        """Перестроить ComboBox после удаления слоя"""
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        for layer in self.layers:
            self.layer_combo.addItem(layer.name(), layer)
        self.layer_combo.blockSignals(False)

        if self.layers:
            self.layer_combo.setCurrentIndex(0)
            self._on_layer_changed(0)
        else:
            self.table.setRowCount(0)
            self._update_count()

    def _on_layer_changed(self, index: int) -> None:
        """Обработка смены слоя в ComboBox

        Args:
            index: Индекс выбранного слоя
        """
        if index < 0 or index >= len(self.layers):
            return

        self.current_layer = self.layers[index]
        self._load_features()

    def _load_features(self) -> None:
        """Загрузить объекты из текущего слоя в таблицу"""
        self.table.setRowCount(0)

        if not self.current_layer:
            return

        features = list(self.current_layer.getFeatures())

        # Сортировка по ID
        def get_id(f: QgsFeature) -> int:
            try:
                return int(f['ID']) if f['ID'] else 0
            except (ValueError, TypeError, KeyError):
                return 0

        features.sort(key=get_id)

        self.table.setRowCount(len(features))

        for row, feature in enumerate(features):
            # Checkbox
            checkbox = QCheckBox()
            checkbox.stateChanged.connect(self._update_count)
            checkbox_widget = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_widget)
            checkbox_layout.addWidget(checkbox)
            checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row, self.COL_CHECK, checkbox_widget)

            # ID
            id_val = str(feature['ID']) if feature['ID'] else ""
            item_id = QTableWidgetItem(id_val)
            item_id.setFlags(item_id.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, self.COL_ID, item_id)

            # Услов_КН
            uslov_kn = str(feature['Услов_КН']) if feature['Услов_КН'] else ""
            item_uslov = QTableWidgetItem(uslov_kn)
            item_uslov.setFlags(item_uslov.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, self.COL_USLOV_KN, item_uslov)

            # КН
            kn = str(feature['КН']) if feature['КН'] else ""
            item_kn = QTableWidgetItem(kn)
            item_kn.setFlags(item_kn.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, self.COL_KN, item_kn)

            # Площадь
            area = feature['Площадь_ОЗУ'] or feature['Площадь'] or 0
            try:
                area_str = f"{float(area):.0f}"
            except (ValueError, TypeError):
                area_str = str(area)
            item_area = QTableWidgetItem(area_str)
            item_area.setFlags(item_area.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, self.COL_AREA, item_area)

            # Адрес
            address = str(feature['Адрес_Местоположения']) if feature['Адрес_Местоположения'] else ""
            item_addr = QTableWidgetItem(address)
            item_addr.setFlags(item_addr.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, self.COL_ADDRESS, item_addr)

            # FID (скрытая колонка)
            item_fid = QTableWidgetItem(str(feature.id()))
            self.table.setItem(row, self.COL_FID, item_fid)

        self._update_count()
        log_info(f"Fsm_2_7_1: Загружено {len(features)} объектов из {self.current_layer.name()}")

    def _get_checkbox(self, row: int) -> Optional[QCheckBox]:
        """Получить checkbox для строки

        Args:
            row: Номер строки

        Returns:
            QCheckBox или None
        """
        widget = self.table.cellWidget(row, self.COL_CHECK)
        if widget:
            checkbox = widget.findChild(QCheckBox)
            return checkbox
        return None

    def _update_count(self) -> None:
        """Обновить счётчик выбранных"""
        total = self.table.rowCount()
        selected = 0

        for row in range(total):
            checkbox = self._get_checkbox(row)
            if checkbox and checkbox.isChecked():
                selected += 1

        self.count_label.setText(
            f"Выбрано: {selected} из {total} (минимум {self.MIN_MERGE_COUNT})"
        )
        # Активировать кнопку только при выборе >= MIN_MERGE_COUNT
        self.merge_btn.setEnabled(selected >= self.MIN_MERGE_COUNT)

    def _on_select_all(self) -> None:
        """Выбрать все"""
        for row in range(self.table.rowCount()):
            checkbox = self._get_checkbox(row)
            if checkbox:
                checkbox.setChecked(True)

    def _on_deselect_all(self) -> None:
        """Снять все"""
        for row in range(self.table.rowCount()):
            checkbox = self._get_checkbox(row)
            if checkbox:
                checkbox.setChecked(False)

    def _on_select_by_zpr(self) -> None:
        """Выбрать контуры по ЗПР

        Выбирает все контуры с таким же значением ЗПР,
        как у первого выбранного контура.
        """
        if not self.current_layer:
            return

        # Найти первый выбранный контур
        selected_row = None
        for row in range(self.table.rowCount()):
            checkbox = self._get_checkbox(row)
            if checkbox and checkbox.isChecked():
                selected_row = row
                break

        if selected_row is None:
            QMessageBox.information(
                self, "Информация",
                "Сначала выберите хотя бы один контур для определения ЗПР"
            )
            return

        # Получить ЗПР выбранного контура
        fid_item = self.table.item(selected_row, self.COL_FID)
        if not fid_item:
            return

        try:
            fid = int(fid_item.text())
        except ValueError:
            return

        feature = self.current_layer.getFeature(fid)
        if not feature:
            return

        target_zpr = feature['ЗПР'] if 'ЗПР' in feature.fields().names() else None
        if not target_zpr:
            QMessageBox.warning(
                self, "Предупреждение",
                "У выбранного контура не указан ЗПР"
            )
            return

        # Выбрать все контуры с таким же ЗПР
        count = 0
        for row in range(self.table.rowCount()):
            fid_item = self.table.item(row, self.COL_FID)
            if not fid_item:
                continue

            try:
                row_fid = int(fid_item.text())
            except ValueError:
                continue

            row_feature = self.current_layer.getFeature(row_fid)
            if row_feature:
                row_zpr = row_feature['ЗПР'] if 'ЗПР' in row_feature.fields().names() else None
                if row_zpr == target_zpr:
                    checkbox = self._get_checkbox(row)
                    if checkbox:
                        checkbox.setChecked(True)
                        count += 1

        log_info(f"Fsm_2_7_1: Выбрано {count} контуров с ЗПР={target_zpr}")

    def _get_selected_fids(self) -> List[int]:
        """Получить список fid выбранных объектов

        Returns:
            Список fid
        """
        fids = []
        for row in range(self.table.rowCount()):
            checkbox = self._get_checkbox(row)
            if checkbox and checkbox.isChecked():
                fid_item = self.table.item(row, self.COL_FID)
                if fid_item:
                    try:
                        fids.append(int(fid_item.text()))
                    except ValueError:
                        pass
        return fids

    def _on_highlight(self) -> None:
        """Выделить выбранные объекты на карте"""
        from qgis.utils import iface

        if not self.current_layer:
            return

        fids = self._get_selected_fids()
        if not fids:
            QMessageBox.information(
                self, "Информация", "Не выбрано ни одного контура"
            )
            return

        # Удалить старую подсветку
        if self._rubber_band:
            self._rubber_band.reset()

        # Создать новую подсветку
        from qgis.core import QgsWkbTypes
        self._rubber_band = QgsRubberBand(
            iface.mapCanvas(), QgsWkbTypes.GeometryType.PolygonGeometry
        )
        self._rubber_band.setColor(QColor(0, 128, 255, 100))  # Синий для объединения
        self._rubber_band.setWidth(2)

        # Добавить геометрии
        for fid in fids:
            feature = self.current_layer.getFeature(fid)
            if feature and feature.hasGeometry():
                self._rubber_band.addGeometry(feature.geometry(), self.current_layer)

        # Масштабировать к выбранным
        if self._rubber_band.asGeometry():
            extent = self._rubber_band.asGeometry().boundingBox()
            extent.scale(1.2)
            iface.mapCanvas().setExtent(extent)
            iface.mapCanvas().refresh()

        log_info(f"Fsm_2_7_1: Выделено {len(fids)} контуров на карте")

    def _on_row_double_clicked(self, row: int, column: int) -> None:
        """Обработка двойного клика по строке - выделить на карте

        Args:
            row: Номер строки
            column: Номер колонки
        """
        from qgis.utils import iface

        if not self.current_layer:
            return

        fid_item = self.table.item(row, self.COL_FID)
        if not fid_item:
            return

        try:
            fid = int(fid_item.text())
        except ValueError:
            return

        feature = self.current_layer.getFeature(fid)
        if feature and feature.hasGeometry():
            extent = feature.geometry().boundingBox()
            extent.scale(2.0)
            iface.mapCanvas().setExtent(extent)
            iface.mapCanvas().refresh()
            log_info(f"Fsm_2_7_1: Переход к контуру fid={fid}")

    def _get_selected_uslov_kn_list(self) -> List[str]:
        """Получить список условных КН выбранных контуров

        Returns:
            Список условных КН
        """
        uslov_kn_list = []
        for row in range(self.table.rowCount()):
            checkbox = self._get_checkbox(row)
            if checkbox and checkbox.isChecked():
                uslov_item = self.table.item(row, self.COL_USLOV_KN)
                if uslov_item and uslov_item.text():
                    uslov_kn_list.append(uslov_item.text())
        return uslov_kn_list

    def _on_merge(self) -> None:
        """Выполнить объединение выбранных контуров"""
        if not self.current_layer:
            return

        fids = self._get_selected_fids()
        if len(fids) < self.MIN_MERGE_COUNT:
            QMessageBox.warning(
                self, "Предупреждение",
                f"Выберите минимум {self.MIN_MERGE_COUNT} контура для объединения"
            )
            return

        # Получить условные КН для сообщения
        uslov_kn_list = self._get_selected_uslov_kn_list()
        uslov_kn_str = ", ".join(uslov_kn_list[:5])
        if len(uslov_kn_list) > 5:
            uslov_kn_str += f" и ещё {len(uslov_kn_list) - 5}"

        # Подтверждение
        reply = QMessageBox.question(
            self,
            "Подтверждение объединения",
            f"Объединить {len(fids)} контур(а) в один?\n\n"
            f"Условные номера: {uslov_kn_str}\n\n"
            "Исходные контуры будут удалены.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Выполнить объединение через callback
        result = self.merge_callback(self.current_layer, fids)

        if result.get('error'):
            # Ошибка обрабатывается в F_2_7
            pass
        else:
            # Очистить подсветку
            if self._rubber_band:
                self._rubber_band.reset()
                self._rubber_band = None

            # Если source слой удалён (все features перенесены в Раздел)
            if result.get('source_removed'):
                # Удалить слой из списка и combo
                if self.current_layer in self.layers:
                    self.layers.remove(self.current_layer)
                self.current_layer = None
                self._rebuild_layer_combo()

                # Если больше нет слоёв - закрыть диалог
                if not self.layers:
                    self.accept()
                    return
            else:
                # Перезагрузить таблицу
                self._load_features()

    def closeEvent(self, event) -> None:
        """Обработка закрытия диалога"""
        # Очистить подсветку
        if self._rubber_band:
            self._rubber_band.reset()
            self._rubber_band = None

        super().closeEvent(event)

    def reject(self) -> None:
        """Обработка отмены"""
        # Очистить подсветку
        if self._rubber_band:
            self._rubber_band.reset()
            self._rubber_band = None

        super().reject()
