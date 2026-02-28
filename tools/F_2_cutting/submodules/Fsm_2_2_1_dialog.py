# -*- coding: utf-8 -*-
"""
Fsm_2_2_1_Dialog - Диалог выбора ЗУ для переноса в Без_Меж

GUI диалог с таблицей для выбора земельных участков,
которые не требуют межевых работ.

НОВАЯ ЛОГИКА (v2):
- Показывает исходные ЗУ из Выборки (не нарезанные части)
- Фильтрует по наличию КН в слоях Раздел или Изм
- При выборе возвращает список КН (не fid)

Функционал:
- Таблица с checkbox для множественного выбора ЗУ
- Кнопки "Выбрать все" / "Снять все"
- Кнопка "Выделить на карте"
- Кнопка "Перенести"
"""

from typing import Optional, List, Dict, Any, Callable, Set

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QCheckBox, QWidget,
    QMessageBox
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry
from qgis.gui import QgsRubberBand

from Daman_QGIS.utils import log_info, log_warning


class Fsm_2_2_1_Dialog(QDialog):
    """Диалог выбора ЗУ для переноса в слой Без_Меж

    Показывает исходные ЗУ из Выборки, чьи КН найдены в слоях Раздел или Изм.
    При выборе возвращает список КН для переноса.
    """

    # Индексы колонок таблицы
    COL_CHECK = 0
    COL_KN = 1           # Кадастровый номер (основной идентификатор)
    COL_AREA = 2         # Площадь
    COL_VRI = 3          # ВРИ
    COL_CATEGORY = 4     # Категория
    COL_PRAVA = 5        # Права
    COL_OBREMENENIE = 6  # Обременения
    COL_SOBSTVENNIKI = 7 # Собственники
    COL_ARENDATORY = 8   # Арендаторы
    COL_ZPR_TYPES = 9    # Типы ЗПР где найден КН (ОКС, ПО, ВО)

    def __init__(
        self,
        parent: Optional[QWidget],
        selection_layer: QgsVectorLayer,
        razdel_layers: List[QgsVectorLayer],
        izm_layers: List[QgsVectorLayer],
        layer_to_zpr_type: Dict[str, str],
        transfer_callback: Callable[[List[str]], Dict[str, Any]]
    ) -> None:
        """Инициализация диалога

        Args:
            parent: Родительский виджет
            selection_layer: Слой Выборки ЗУ (источник исходных ЗУ)
            razdel_layers: Список слоёв Раздел
            izm_layers: Список слоёв Изм
            layer_to_zpr_type: Маппинг имя_слоя -> тип_ЗПР
            transfer_callback: Callback функция (List[КН]) -> result
        """
        super().__init__(parent)
        self.selection_layer = selection_layer
        self.razdel_layers = razdel_layers
        self.izm_layers = izm_layers
        self.layer_to_zpr_type = layer_to_zpr_type
        self.transfer_callback = transfer_callback

        # Кэш: КН -> Set[тип_ЗПР]
        self._kn_to_zpr_types: Dict[str, Set[str]] = {}
        self._rubber_band: Optional[QgsRubberBand] = None

        self.setWindowTitle("Перенос ЗУ в слой Без межевания")
        self.resize(1200, 500)
        self.setModal(True)

        self._setup_ui()
        self._connect_signals()

        # Загрузить данные
        self._collect_kn_in_cutting_layers()
        self._load_features()

    def _setup_ui(self) -> None:
        """Настройка UI"""
        layout = QVBoxLayout()

        # Заголовок
        title = QLabel("<h3>Перенос ЗУ в слой \"Без межевания\"</h3>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Описание
        description = QLabel(
            "Выберите земельные участки, которые НЕ требуют межевых работ.\n"
            "Показаны исходные ЗУ, геометрия которых изменяется при нарезке.\n"
            "При переносе исходная геометрия ЗУ будет сохранена."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        # Таблица ЗУ
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "", "КН", "Площадь", "ВРИ", "Категория",
            "Права", "Обременения", "Собственники", "Арендаторы", "ЗПР"
        ])
        self.table.horizontalHeader().setSectionResizeMode(
            self.COL_CHECK, QHeaderView.ResizeMode.Fixed
        )
        self.table.setColumnWidth(self.COL_CHECK, 30)
        self.table.setColumnWidth(self.COL_KN, 170)
        self.table.setColumnWidth(self.COL_AREA, 80)
        self.table.setColumnWidth(self.COL_VRI, 200)
        self.table.setColumnWidth(self.COL_CATEGORY, 100)
        self.table.setColumnWidth(self.COL_PRAVA, 100)
        self.table.setColumnWidth(self.COL_OBREMENENIE, 100)
        self.table.setColumnWidth(self.COL_SOBSTVENNIKI, 150)
        self.table.setColumnWidth(self.COL_ARENDATORY, 100)
        self.table.horizontalHeader().setSectionResizeMode(
            self.COL_ZPR_TYPES, QHeaderView.ResizeMode.Stretch
        )
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

        self.transfer_btn = QPushButton("Перенести")
        self.transfer_btn.setEnabled(False)
        self.transfer_btn.clicked.connect(self._on_transfer)
        action_layout.addWidget(self.transfer_btn)

        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.clicked.connect(self.reject)
        action_layout.addWidget(self.cancel_btn)

        layout.addLayout(action_layout)
        self.setLayout(layout)

    def _connect_signals(self) -> None:
        """Подключение сигналов"""
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)

    def _refresh_layer_references(self) -> None:
        """Обновить ссылки на слои из проекта

        После commit в GPKG кэшированные слои могут содержать устаревшие данные.
        Перечитываем актуальные слои из проекта QGIS.
        """
        from qgis.core import QgsProject
        from Daman_QGIS.constants import LAYER_SELECTION_ZU

        project = QgsProject.instance()

        # Обновить слой Выборки
        selection_layers = project.mapLayersByName(LAYER_SELECTION_ZU)
        if selection_layers and isinstance(selection_layers[0], QgsVectorLayer):
            self.selection_layer = selection_layers[0]
            log_info(f"Fsm_2_2_1: Обновлён слой Выборки ({self.selection_layer.featureCount()} объектов)")

        # Обновить слои Раздел
        new_razdel = []
        for old_layer in self.razdel_layers:
            layer_name = old_layer.name()
            layers = project.mapLayersByName(layer_name)
            if layers and isinstance(layers[0], QgsVectorLayer):
                new_razdel.append(layers[0])
        self.razdel_layers = new_razdel

        # Обновить слои Изм
        new_izm = []
        for old_layer in self.izm_layers:
            layer_name = old_layer.name()
            layers = project.mapLayersByName(layer_name)
            if layers and isinstance(layers[0], QgsVectorLayer):
                new_izm.append(layers[0])
        self.izm_layers = new_izm

    def _collect_kn_in_cutting_layers(self) -> None:
        """Собрать все КН из слоёв Раздел и Изм

        Заполняет _kn_to_zpr_types: Dict[КН, Set[тип_ЗПР]]
        """
        self._kn_to_zpr_types.clear()

        # Обходим слои Раздел
        for layer in self.razdel_layers:
            zpr_type = self.layer_to_zpr_type.get(layer.name())
            if not zpr_type:
                continue

            for feature in layer.getFeatures():
                kn = self._get_kn_from_feature(feature)
                if kn:
                    if kn not in self._kn_to_zpr_types:
                        self._kn_to_zpr_types[kn] = set()
                    self._kn_to_zpr_types[kn].add(zpr_type)

        # Обходим слои Изм
        for layer in self.izm_layers:
            zpr_type = self.layer_to_zpr_type.get(layer.name())
            if not zpr_type:
                continue

            for feature in layer.getFeatures():
                kn = self._get_kn_from_feature(feature)
                if kn:
                    if kn not in self._kn_to_zpr_types:
                        self._kn_to_zpr_types[kn] = set()
                    self._kn_to_zpr_types[kn].add(zpr_type)

        log_info(f"Fsm_2_2_1: Найдено {len(self._kn_to_zpr_types)} уникальных КН в слоях нарезки")

    def _get_kn_from_feature(self, feature: QgsFeature) -> Optional[str]:
        """Получить КН из feature

        Args:
            feature: Feature

        Returns:
            КН или None
        """
        try:
            kn = feature['КН']
            if kn and str(kn).strip() not in ('', '-', 'NULL', 'None'):
                return str(kn).strip()
        except (KeyError, IndexError):
            pass
        return None

    def _load_features(self) -> None:
        """Загрузить ЗУ из Выборки, отфильтровав по КН в Раздел/Изм"""
        self.table.setRowCount(0)

        if not self.selection_layer:
            log_warning("Fsm_2_2_1: Слой Выборки не задан")
            return

        if not self._kn_to_zpr_types:
            log_warning("Fsm_2_2_1: Нет КН в слоях нарезки")
            return

        # Диагностика: вывести КН из нарезки
        log_info(f"Fsm_2_2_1: КН в нарезке: {list(self._kn_to_zpr_types.keys())}")

        # Собираем features из Выборки с фильтрацией по КН
        filtered_features = []
        selection_kns = []
        for feature in self.selection_layer.getFeatures():
            kn = self._get_kn_from_feature(feature)
            if kn:
                selection_kns.append(kn)
            if kn and kn in self._kn_to_zpr_types:
                filtered_features.append(feature)

        # Диагностика: вывести КН из Выборки
        log_info(f"Fsm_2_2_1: КН в Выборке: {selection_kns}")

        # Сортировка по КН
        filtered_features.sort(key=lambda f: self._get_kn_from_feature(f) or "")

        self.table.setRowCount(len(filtered_features))

        for row, feature in enumerate(filtered_features):
            kn = self._get_kn_from_feature(feature) or ""
            zpr_types = self._kn_to_zpr_types.get(kn, set())

            # Checkbox
            checkbox = QCheckBox()
            checkbox.stateChanged.connect(self._update_count)
            checkbox_widget = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_widget)
            checkbox_layout.addWidget(checkbox)
            checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row, self.COL_CHECK, checkbox_widget)

            # КН
            item_kn = QTableWidgetItem(kn)
            item_kn.setFlags(item_kn.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, self.COL_KN, item_kn)

            # Площадь
            area = self._get_field_value(feature, 'Площадь')
            try:
                area_str = f"{float(area):.0f}" if area else ""
            except (ValueError, TypeError):
                area_str = str(area) if area else ""
            item_area = QTableWidgetItem(area_str)
            item_area.setFlags(item_area.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, self.COL_AREA, item_area)

            # ВРИ
            vri = self._get_field_value(feature, 'ВРИ')
            item_vri = QTableWidgetItem(vri)
            item_vri.setFlags(item_vri.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, self.COL_VRI, item_vri)

            # Категория
            category = self._get_field_value(feature, 'Категория')
            item_cat = QTableWidgetItem(category)
            item_cat.setFlags(item_cat.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, self.COL_CATEGORY, item_cat)

            # Права
            prava = self._get_field_value(feature, 'Права')
            item_prava = QTableWidgetItem(prava)
            item_prava.setFlags(item_prava.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, self.COL_PRAVA, item_prava)

            # Обременения (в Выборке поле называется "Обременения")
            obremenenie = self._get_field_value(feature, 'Обременения')
            item_obrem = QTableWidgetItem(obremenenie)
            item_obrem.setFlags(item_obrem.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, self.COL_OBREMENENIE, item_obrem)

            # Собственники
            sobstvenniki = self._get_field_value(feature, 'Собственники')
            item_sobst = QTableWidgetItem(sobstvenniki)
            item_sobst.setFlags(item_sobst.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, self.COL_SOBSTVENNIKI, item_sobst)

            # Арендаторы
            arendatory = self._get_field_value(feature, 'Арендаторы')
            item_arend = QTableWidgetItem(arendatory)
            item_arend.setFlags(item_arend.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, self.COL_ARENDATORY, item_arend)

            # Типы ЗПР
            zpr_str = ', '.join(sorted(zpr_types))
            item_zpr = QTableWidgetItem(zpr_str)
            item_zpr.setFlags(item_zpr.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, self.COL_ZPR_TYPES, item_zpr)

        self._update_count()
        log_info(f"Fsm_2_2_1: Загружено {len(filtered_features)} ЗУ для выбора")

    def _get_field_value(self, feature: QgsFeature, field_name: str) -> str:
        """Безопасное получение значения поля

        Args:
            feature: Feature
            field_name: Имя поля

        Returns:
            Строковое значение или пустая строка
        """
        try:
            value = feature[field_name]
            if value is None or str(value).strip() in ('', 'NULL', '-', 'None'):
                return ""
            return str(value)
        except (KeyError, IndexError):
            return ""

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

    def _get_selected_kn(self) -> List[str]:
        """Получить список КН выбранных объектов

        Returns:
            Список КН
        """
        kn_list = []
        for row in range(self.table.rowCount()):
            checkbox = self._get_checkbox(row)
            if checkbox and checkbox.isChecked():
                kn_item = self.table.item(row, self.COL_KN)
                if kn_item and kn_item.text():
                    kn_list.append(kn_item.text())
        return kn_list

    def _find_feature_by_kn(self, kn: str) -> Optional[QgsFeature]:
        """Найти feature в Выборке по КН

        Args:
            kn: Кадастровый номер

        Returns:
            QgsFeature или None
        """
        if not self.selection_layer:
            return None

        for feature in self.selection_layer.getFeatures():
            feature_kn = self._get_kn_from_feature(feature)
            if feature_kn == kn:
                return feature
        return None

    def _on_highlight(self) -> None:
        """Выделить выбранные объекты на карте"""
        from qgis.utils import iface

        if not self.selection_layer:
            return

        kn_list = self._get_selected_kn()
        if not kn_list:
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
        for kn in kn_list:
            feature = self._find_feature_by_kn(kn)
            if feature and feature.hasGeometry():
                self._rubber_band.addGeometry(feature.geometry(), self.selection_layer)

        # Масштабировать к выбранным
        if self._rubber_band.asGeometry():
            extent = self._rubber_band.asGeometry().boundingBox()
            extent.scale(1.2)
            iface.mapCanvas().setExtent(extent)
            iface.mapCanvas().refresh()

        log_info(f"Fsm_2_2_1: Выделено {len(kn_list)} объектов на карте")

    def _on_row_double_clicked(self, row: int, column: int) -> None:
        """Обработка двойного клика по строке - выделить на карте

        Args:
            row: Номер строки
            column: Номер колонки
        """
        from qgis.utils import iface

        if not self.selection_layer:
            return

        kn_item = self.table.item(row, self.COL_KN)
        if not kn_item:
            return

        kn = kn_item.text()
        feature = self._find_feature_by_kn(kn)

        if feature and feature.hasGeometry():
            extent = feature.geometry().boundingBox()
            extent.scale(2.0)
            iface.mapCanvas().setExtent(extent)
            iface.mapCanvas().refresh()
            log_info(f"Fsm_2_2_1: Переход к ЗУ с КН {kn}")

    def _on_transfer(self) -> None:
        """Выполнить перенос выбранных объектов"""
        kn_list = self._get_selected_kn()
        if not kn_list:
            QMessageBox.warning(
                self, "Предупреждение", "Не выбрано ни одного объекта для переноса"
            )
            return

        # Подтверждение
        reply = QMessageBox.question(
            self,
            "Подтверждение переноса",
            f"Перенести {len(kn_list)} ЗУ в слой Без_Меж?\n\n"
            "Нарезанные части будут удалены из слоёв Раздел и Изм.\n"
            "Исходная геометрия ЗУ будет скопирована в Без_Меж.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Выполнить перенос через callback
        result = self.transfer_callback(kn_list)

        if result.get('errors'):
            errors = result['errors']
            QMessageBox.warning(
                self,
                "Предупреждение",
                f"Перенос завершён с ошибками:\n" + "\n".join(errors[:5])
            )
        else:
            # Успешно - перезагрузить ссылки на слои из проекта
            # (после commit в GPKG кэшированные ссылки могут быть невалидными)
            self._refresh_layer_references()

            # Перезагрузить данные
            self._collect_kn_in_cutting_layers()
            self._load_features()

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
