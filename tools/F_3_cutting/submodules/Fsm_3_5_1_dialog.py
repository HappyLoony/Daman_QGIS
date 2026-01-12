# -*- coding: utf-8 -*-
"""
Fsm_3_5_1_Dialog - Диалог выбора ЗУ для изъятия

GUI диалог с таблицей для выбора земельных участков,
подлежащих изъятию для государственных и муниципальных нужд.

Функционал:
- ComboBox для выбора слоя-источника (Раздел или НГС)
- Таблица с checkbox для множественного выбора ЗУ
- Кнопки "Выбрать все" / "Снять все"
- Кнопка "Выделить на карте"
- Кнопка "К изъятию" (копирование в L_3_3_1)
"""

from typing import Optional, List, Dict, Any, Callable

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QCheckBox, QWidget,
    QMessageBox
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry
from qgis.gui import QgsRubberBand

from Daman_QGIS.utils import log_info, log_warning


class Fsm_3_5_1_Dialog(QDialog):
    """Диалог выбора ЗУ для изъятия

    Attributes:
        layers: Список доступных слоёв-источников (Раздел, НГС)
        transfer_callback: Функция копирования (source_layer, feature_ids) -> result
    """

    # Индексы колонок таблицы
    COL_CHECK = 0
    COL_ID = 1
    COL_USLOV_KN = 2
    COL_KN = 3
    COL_AREA = 4
    COL_ADDRESS = 5
    COL_FID = 6  # Скрытая колонка с fid

    def __init__(
        self,
        parent: Optional[QWidget],
        layers: List[QgsVectorLayer],
        transfer_callback: Callable[[QgsVectorLayer, List[int]], Dict[str, Any]]
    ) -> None:
        """Инициализация диалога

        Args:
            parent: Родительский виджет
            layers: Список доступных слоёв-источников
            transfer_callback: Callback функция для выполнения копирования
        """
        super().__init__(parent)
        self.layers = layers
        self.transfer_callback = transfer_callback
        self.current_layer: Optional[QgsVectorLayer] = None
        self._rubber_band: Optional[QgsRubberBand] = None

        self.setWindowTitle("Отбор ЗУ для изъятия")
        self.resize(900, 550)
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
        title = QLabel("<h3>Отбор ЗУ для изъятия</h3>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Описание
        description = QLabel(
            "Выберите земельные участки, подлежащие изъятию для государственных\n"
            "и муниципальных нужд. Участки будут СКОПИРОВАНЫ в слой L_3_3_1_Изъятие_ЗУ."
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

        # Таблица ЗУ
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
        self.table.setColumnWidth(self.COL_USLOV_KN, 180)
        self.table.setColumnWidth(self.COL_KN, 180)
        self.table.setColumnWidth(self.COL_AREA, 80)
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
        self.count_label = QLabel("Выбрано: 0 из 0")
        layout.addWidget(self.count_label)

        # Кнопки выбора
        select_layout = QHBoxLayout()

        self.select_all_btn = QPushButton("Выбрать все")
        self.select_all_btn.clicked.connect(self._on_select_all)
        select_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Снять все")
        self.deselect_all_btn.clicked.connect(self._on_deselect_all)
        select_layout.addWidget(self.deselect_all_btn)

        self.highlight_btn = QPushButton("Выделить на карте")
        self.highlight_btn.clicked.connect(self._on_highlight)
        select_layout.addWidget(self.highlight_btn)

        select_layout.addStretch()
        layout.addLayout(select_layout)

        # Кнопки действий
        action_layout = QHBoxLayout()
        action_layout.addStretch()

        self.transfer_btn = QPushButton("К изъятию")
        self.transfer_btn.setEnabled(False)
        self.transfer_btn.clicked.connect(self._on_transfer)
        self.transfer_btn.setStyleSheet(
            "QPushButton { background-color: #ff6b6b; color: white; "
            "font-weight: bold; padding: 8px 16px; }"
        )
        action_layout.addWidget(self.transfer_btn)

        self.cancel_btn = QPushButton("Закрыть")
        self.cancel_btn.clicked.connect(self.reject)
        action_layout.addWidget(self.cancel_btn)

        layout.addLayout(action_layout)
        self.setLayout(layout)

    def _connect_signals(self) -> None:
        """Подключение сигналов"""
        self.layer_combo.currentIndexChanged.connect(self._on_layer_changed)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)

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

        if self.current_layer is None:
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
        log_info(f"Fsm_3_5_1: Загружено {len(features)} объектов из {self.current_layer.name()}")

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

        self.count_label.setText(f"Выбрано: {selected} из {total}")
        self.transfer_btn.setEnabled(selected > 0)

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

        if self.current_layer is None:
            return

        fids = self._get_selected_fids()
        if not fids:
            QMessageBox.information(
                self, "Информация", "Не выбрано ни одного объекта"
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
        self._rubber_band.setColor(QColor(255, 0, 0, 100))
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

        log_info(f"Fsm_3_5_1: Выделено {len(fids)} объектов на карте")

    def _on_row_double_clicked(self, row: int, column: int) -> None:
        """Обработка двойного клика по строке - выделить на карте

        Args:
            row: Номер строки
            column: Номер колонки
        """
        from qgis.utils import iface

        if self.current_layer is None:
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
            log_info(f"Fsm_3_5_1: Переход к объекту fid={fid}")

    def _on_transfer(self) -> None:
        """Выполнить копирование выбранных объектов в слой изъятия"""
        if self.current_layer is None:
            return

        fids = self._get_selected_fids()
        if not fids:
            QMessageBox.warning(
                self, "Предупреждение", "Не выбрано ни одного объекта для изъятия"
            )
            return

        # Подтверждение
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Скопировать {len(fids)} объект(ов) в слой Изъятие_ЗУ?\n\n"
            "Объекты будут СКОПИРОВАНЫ (источник не изменится).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Выполнить копирование через callback
        result = self.transfer_callback(self.current_layer, fids)

        if result.get('error'):
            # Ошибка обрабатывается в F_3_5
            pass
        else:
            # Успешно - снять выбор с перенесённых
            self._on_deselect_all()

            # Очистить подсветку
            if self._rubber_band:
                self._rubber_band.reset()
                self._rubber_band = None

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
