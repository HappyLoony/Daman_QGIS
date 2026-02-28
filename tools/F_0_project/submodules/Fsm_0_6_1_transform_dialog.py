# -*- coding: utf-8 -*-
"""
Fsm_0_6_1 - Диалог трансформации координат

GUI для F_0_6: выбор слоя, таблица контрольных точек (4+ пар),
результаты расчёта, графика на карте, backup/restore.

По аналогии с Fsm_0_5_refine_dialog.py (RefineProjectionDialog).
"""

import math
from typing import Optional, Tuple, List, Dict

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QMessageBox, QGraphicsSimpleTextItem,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont, QBrush, QPen

from qgis.core import (
    QgsPointXY, Qgis, QgsGeometry, QgsWkbTypes,
    QgsProject, QgsVectorLayer,
)
from qgis.gui import QgsRubberBand, QgsVertexMarker

from .Fsm_0_6_2_transform_methods import (
    TransformResult, BaseTransformMethod, auto_select_method,
)
from .Fsm_0_6_3_transform_applicator import TransformApplicator

from Daman_QGIS.utils import log_info, log_warning, log_error


# Цвета невязок (порог 0.01м)
COLOR_RESIDUAL_OK = QColor(200, 255, 200)       # Зелёный: < 0.01м
COLOR_RESIDUAL_BAD = QColor(255, 200, 200)       # Красный: > 0.01м
COLOR_RESIDUAL_BLUNDER = QColor(255, 100, 100)   # Ярко-красный: blunder

# Цвета пар на карте
PAIR_COLORS = [
    QColor(255, 0, 0, 200),     # Красный
    QColor(0, 150, 0, 200),     # Зелёный
    QColor(0, 0, 255, 200),     # Синий
    QColor(255, 165, 0, 200),   # Оранжевый
    QColor(128, 0, 128, 200),   # Пурпурный
    QColor(0, 128, 128, 200),   # Бирюзовый
    QColor(139, 69, 19, 200),   # Коричневый
    QColor(255, 20, 147, 200),  # Розовый
]

# Порог RMSE (кадастровая точность)
RMSE_THRESHOLD = 0.01  # метров


class CoordinateTransformDialog(QDialog):
    """
    Диалог трансформации координат слоя по контрольным точкам.

    Минимум 4 пары точек.
    Автовыбор метода: Offset / Helmert2D / Affine.
    """

    def __init__(self, iface, parent_tool):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.parent_tool = parent_tool

        # Данные точек: список пар (source, target), начинаем с 4
        self.point_pairs: List[Optional[Tuple[QgsPointXY, QgsPointXY]]] = [
            None, None, None, None
        ]

        # Режим выбора точки
        self._current_row: int = 0
        self._selecting_source: bool = True  # True = исходная, False = целевая

        # Результаты расчёта
        self._transform_result: Optional[TransformResult] = None
        self._transform_method: Optional[BaseTransformMethod] = None

        # Backup геометрий
        self._backup: Optional[Dict[int, QgsGeometry]] = None

        # Редактируемость слоя
        self._layer_editable: bool = True

        # Графика на карте
        self.pair_graphics: Dict[int, dict] = {}
        self._extent_changed_connected = False

        # Настройка UI
        self.setWindowTitle("Трансформация координат")
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
        )

        self._init_ui()
        self._populate_layers()
        self._update_selection_label()
        self._update_buttons_state()

    def _init_ui(self):
        """Построение UI."""
        layout = QVBoxLayout(self)

        # --- Выбор слоя ---
        layer_group = QGroupBox("Изменяемый слой")
        layer_layout = QHBoxLayout()
        self.layer_combo = QComboBox()
        self.layer_combo.currentIndexChanged.connect(self._on_layer_changed)
        layer_layout.addWidget(self.layer_combo)
        layer_group.setLayout(layer_layout)
        layout.addWidget(layer_group)

        # --- Инструкция ---
        self.instruction_label = QLabel()
        self.instruction_label.setWordWrap(True)
        layout.addWidget(self.instruction_label)

        # --- Таблица точек ---
        table_group = QGroupBox("Контрольные точки (минимум 4 пары)")
        table_layout = QVBoxLayout()

        self.table = QTableWidget(4, 8)
        self.table.setHorizontalHeaderLabels([
            "N", "Исх. X", "Исх. Y", "Цел. X", "Цел. Y",
            "dX", "dY", "Невязка"
        ])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 30)
        for col in range(1, 8):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)

        # Нумерация строк
        for row in range(4):
            item = QTableWidgetItem(str(row + 1))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, item)

        self.table.currentCellChanged.connect(self._on_table_selection_changed)
        table_layout.addWidget(self.table)

        # Кнопки таблицы
        btn_layout = QHBoxLayout()
        self.add_pair_btn = QPushButton("+ Добавить пару")
        self.add_pair_btn.clicked.connect(self._add_pair)
        self.remove_pair_btn = QPushButton("- Удалить пару")
        self.remove_pair_btn.clicked.connect(self._remove_pair)
        self.clear_row_btn = QPushButton("Очистить строку")
        self.clear_row_btn.clicked.connect(self._clear_current_row)
        self.clear_all_btn = QPushButton("Очистить все")
        self.clear_all_btn.clicked.connect(self._clear_all_points)

        btn_layout.addWidget(self.add_pair_btn)
        btn_layout.addWidget(self.remove_pair_btn)
        btn_layout.addWidget(self.clear_row_btn)
        btn_layout.addWidget(self.clear_all_btn)
        table_layout.addLayout(btn_layout)

        table_group.setLayout(table_layout)
        layout.addWidget(table_group)

        # --- Результаты ---
        result_group = QGroupBox("Результаты")
        result_layout = QVBoxLayout()

        # RMSE и метод
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("RMSE:"))
        self.rmse_edit = QLineEdit()
        self.rmse_edit.setReadOnly(True)
        row1.addWidget(self.rmse_edit)
        row1.addWidget(QLabel("Метод:"))
        self.method_edit = QLineEdit()
        self.method_edit.setReadOnly(True)
        row1.addWidget(self.method_edit)
        result_layout.addLayout(row1)

        # Параметры трансформации
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("dX:"))
        self.dx_edit = QLineEdit()
        self.dx_edit.setReadOnly(True)
        row2.addWidget(self.dx_edit)
        row2.addWidget(QLabel("dY:"))
        self.dy_edit = QLineEdit()
        self.dy_edit.setReadOnly(True)
        row2.addWidget(self.dy_edit)
        result_layout.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Поворот:"))
        self.rotation_edit = QLineEdit()
        self.rotation_edit.setReadOnly(True)
        row3.addWidget(self.rotation_edit)
        row3.addWidget(QLabel("Масштаб:"))
        self.scale_edit = QLineEdit()
        self.scale_edit.setReadOnly(True)
        row3.addWidget(self.scale_edit)
        result_layout.addLayout(row3)

        # Max невязка
        row4 = QHBoxLayout()
        row4.addWidget(QLabel("Max невязка:"))
        self.max_residual_edit = QLineEdit()
        self.max_residual_edit.setReadOnly(True)
        row4.addWidget(self.max_residual_edit)
        result_layout.addLayout(row4)

        result_group.setLayout(result_layout)
        layout.addWidget(result_group)

        # --- Кнопки действий ---
        action_layout = QHBoxLayout()
        self.calculate_btn = QPushButton("Рассчитать")
        self.calculate_btn.clicked.connect(self._on_calculate)
        self.save_btn = QPushButton("Сохранить")
        self.save_btn.clicked.connect(self._on_save)
        self.save_btn.setEnabled(False)
        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.clicked.connect(self._on_cancel)

        action_layout.addWidget(self.calculate_btn)
        action_layout.addWidget(self.save_btn)
        action_layout.addWidget(self.cancel_btn)
        layout.addLayout(action_layout)

    # ========== Layer management ==========

    def _populate_layers(self):
        """Заполнить ComboBox векторными слоями проекта."""
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()

        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                self.layer_combo.addItem(layer.name(), layer.id())

        self.layer_combo.blockSignals(False)

        # Установить первый слой
        if self.layer_combo.count() > 0:
            self._on_layer_changed(0)

    def _on_layer_changed(self, index: int):
        """Обработка смены выбранного слоя."""
        layer_id = self.layer_combo.currentData()
        if not layer_id:
            return

        layer = QgsProject.instance().mapLayer(layer_id)
        if not isinstance(layer, QgsVectorLayer):
            return

        # Проверка поддержки редактирования геометрий
        provider = layer.dataProvider()
        can_edit = False
        if provider:
            can_edit = bool(provider.capabilities() & provider.ChangeGeometries)

        if not can_edit:
            # Предлагаем автоматическую конвертацию в GPKG
            reply = QMessageBox.question(
                self,
                "Слой не поддерживает редактирование",
                f"Слой '{layer.name()}' ({layer.providerType()}) не поддерживает "
                f"изменение геометрий.\n\n"
                f"Источник: {layer.source().split('|')[0]}\n\n"
                f"Создать редактируемую копию в GeoPackage?\n"
                f"(исходный слой будет заменён копией в проекте)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                converted_layer = self._convert_layer(layer)
                if converted_layer is not None:
                    layer = converted_layer
                    can_edit = True
                    # Обновляем ComboBox: слой заменён
                    self._populate_layers()
                    # Выбираем конвертированный слой
                    for i in range(self.layer_combo.count()):
                        if self.layer_combo.itemData(i) == layer.id():
                            self.layer_combo.blockSignals(True)
                            self.layer_combo.setCurrentIndex(i)
                            self.layer_combo.blockSignals(False)
                            break
            else:
                log_warning(
                    f"Fsm_0_6_1: Слой '{layer.name()}' не поддерживает редактирование "
                    f"(provider={layer.providerType()}, canChangeGeom=False)"
                )

        self.parent_tool.target_layer = layer
        self._layer_editable = can_edit

        # Сбросить точки и результаты
        self._clear_all_points()

        log_info(
            f"Fsm_0_6_1: Выбран слой: {layer.name()} "
            f"({layer.featureCount()} фич, editable={can_edit})"
        )

    def _convert_layer(self, layer: QgsVectorLayer) -> Optional[QgsVectorLayer]:
        """
        Конвертировать non-editable слой в GPKG.

        Returns:
            Новый GPKG слой или None при ошибке
        """
        from .Fsm_0_6_3_transform_applicator import TransformApplicator

        new_layer = TransformApplicator.convert_layer_to_gpkg(layer)

        if new_layer is None:
            QMessageBox.critical(
                self,
                "Ошибка конвертации",
                f"Не удалось создать GPKG копию слоя '{layer.name()}'.\n"
                f"Проверьте права записи в папку с исходным файлом."
            )
            return None

        self.iface.messageBar().pushMessage(
            "Конвертация",
            f"Слой '{new_layer.name()}' сконвертирован в GeoPackage",
            level=Qgis.MessageLevel.Success,
            duration=5
        )

        log_info(
            f"Fsm_0_6_1: Слой сконвертирован в GPKG: "
            f"{new_layer.name()} ({new_layer.featureCount()} фич)"
        )

        return new_layer

    def _get_target_layer(self) -> Optional[QgsVectorLayer]:
        """Получить текущий целевой слой."""
        return self.parent_tool.target_layer

    # ========== Point selection ==========

    def is_selecting_source(self) -> bool:
        """Текущий режим: выбираем исходную точку?"""
        return self._selecting_source

    def set_point_from_map(self, point: QgsPointXY, is_source: bool):
        """
        Установить точку из MapTool.

        Parameters:
            point: Native координаты вершины
            is_source: True = исходная (на целевом слое), False = целевая (reference)
        """
        row = self._current_row
        if row < 0 or row >= len(self.point_pairs):
            return

        # Инициализируем пару если нужно
        pair = self.point_pairs[row]
        if pair is None:
            src = None
            dst = None
        else:
            src, dst = pair

        if is_source:
            src = point
            # Следующий клик — целевая точка для этой же пары
            self._selecting_source = False
        else:
            dst = point
            # Пара заполнена — переключаем на следующую строку
            self._selecting_source = True
            # Автоматически переходим к следующей строке
            if row + 1 < len(self.point_pairs):
                self._current_row = row + 1
                self.table.selectRow(self._current_row)

        # Сохраняем пару
        if src is not None and dst is not None:
            self.point_pairs[row] = (src, dst)
        elif src is not None:
            self.point_pairs[row] = (src, QgsPointXY(0, 0))  # Placeholder
        else:
            self.point_pairs[row] = None

        # Обновляем таблицу
        self._update_table_row(row, src, dst)

        # Рисуем графику если пара полная
        if src is not None and dst is not None:
            self.point_pairs[row] = (src, dst)
            self.draw_pair_graphics(row)

        # Обновляем UI
        self._update_selection_label()
        self._update_buttons_state()

    def _update_selection_label(self):
        """Обновить инструкцию."""
        row = self._current_row + 1
        point_type = "ИСХОДНУЮ (на изменяемом слое)" if self._selecting_source \
            else "ЦЕЛЕВУЮ (на reference слое)"
        self.instruction_label.setText(
            f"Пара {row}: Кликните {point_type} точку на карте"
        )

    def _on_table_selection_changed(self, row: int, col: int, prev_row: int, prev_col: int):
        """Обработка выбора строки в таблице."""
        if row < 0 or row >= len(self.point_pairs):
            return

        self._current_row = row

        # Определяем что нужно выбрать
        pair = self.point_pairs[row]
        if pair is None:
            self._selecting_source = True
        else:
            src, dst = pair
            # Если исходная уже есть, выбираем целевую
            if src is not None and (dst is None or dst == QgsPointXY(0, 0)):
                self._selecting_source = False
            else:
                self._selecting_source = True

        self._update_selection_label()

    # ========== Table management ==========

    def _update_table_row(
        self,
        row: int,
        src: Optional[QgsPointXY],
        dst: Optional[QgsPointXY]
    ):
        """Обновить одну строку таблицы."""
        # Номер
        num_item = QTableWidgetItem(str(row + 1))
        num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 0, num_item)

        if src is not None:
            self.table.setItem(row, 1, self._coord_item(src.x()))
            self.table.setItem(row, 2, self._coord_item(src.y()))
        else:
            self.table.setItem(row, 1, QTableWidgetItem(""))
            self.table.setItem(row, 2, QTableWidgetItem(""))

        if dst is not None and dst != QgsPointXY(0, 0):
            self.table.setItem(row, 3, self._coord_item(dst.x()))
            self.table.setItem(row, 4, self._coord_item(dst.y()))
        else:
            self.table.setItem(row, 3, QTableWidgetItem(""))
            self.table.setItem(row, 4, QTableWidgetItem(""))

        # dX, dY
        if src is not None and dst is not None and dst != QgsPointXY(0, 0):
            dx = dst.x() - src.x()
            dy = dst.y() - src.y()
            self.table.setItem(row, 5, self._coord_item(dx))
            self.table.setItem(row, 6, self._coord_item(dy))
        else:
            self.table.setItem(row, 5, QTableWidgetItem(""))
            self.table.setItem(row, 6, QTableWidgetItem(""))

        # Невязка (после расчёта)
        self.table.setItem(row, 7, QTableWidgetItem(""))

    def _coord_item(self, value: float) -> QTableWidgetItem:
        """Создать ячейку с координатой."""
        item = QTableWidgetItem(f"{value:.2f}")
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return item

    def _add_pair(self):
        """Добавить пустую пару."""
        row = len(self.point_pairs)
        self.point_pairs.append(None)
        self.table.setRowCount(row + 1)

        # Нумерация
        num_item = QTableWidgetItem(str(row + 1))
        num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 0, num_item)

        self._update_buttons_state()

    def _remove_pair(self):
        """Удалить последнюю пару (минимум 4)."""
        if len(self.point_pairs) <= 4:
            return

        row = len(self.point_pairs) - 1
        self.clear_pair_graphics(row)
        self.point_pairs.pop()
        self.table.setRowCount(row)

        if self._current_row >= len(self.point_pairs):
            self._current_row = len(self.point_pairs) - 1
            self.table.selectRow(self._current_row)

        self._update_buttons_state()

    def _clear_current_row(self):
        """Очистить текущую строку."""
        row = self._current_row
        if row < 0 or row >= len(self.point_pairs):
            return

        self.point_pairs[row] = None
        self.clear_pair_graphics(row)
        self._update_table_row(row, None, None)
        self._selecting_source = True
        self._update_selection_label()
        self._update_buttons_state()

    def _clear_all_points(self):
        """Очистить все точки."""
        self.clear_all_graphics()

        # Сбросить до 4 пар
        self.point_pairs = [None, None, None, None]
        self.table.setRowCount(4)
        for row in range(4):
            self._update_table_row(row, None, None)

        self._current_row = 0
        self._selecting_source = True
        self._transform_result = None
        self._transform_method = None

        # Сбросить результаты
        self.rmse_edit.clear()
        self.method_edit.clear()
        self.dx_edit.clear()
        self.dy_edit.clear()
        self.rotation_edit.clear()
        self.scale_edit.clear()
        self.max_residual_edit.clear()
        self.save_btn.setEnabled(False)

        self._update_selection_label()
        self._update_buttons_state()

    def _update_buttons_state(self):
        """Обновить состояние кнопок."""
        # Рассчитать: минимум 4 полных пары
        filled = sum(
            1 for p in self.point_pairs
            if p is not None and p[1] != QgsPointXY(0, 0)
        )
        self.calculate_btn.setEnabled(filled >= 4)
        self.remove_pair_btn.setEnabled(len(self.point_pairs) > 4)

    # ========== Calculation ==========

    def _on_calculate(self):
        """Расчёт трансформации."""
        # Собираем заполненные пары
        src_points: List[Tuple[float, float]] = []
        dst_points: List[Tuple[float, float]] = []
        pair_indices: List[int] = []  # Маппинг индексов для невязок

        for i, pair in enumerate(self.point_pairs):
            if pair is None:
                continue
            src, dst = pair
            if dst == QgsPointXY(0, 0):
                continue
            src_points.append((src.x(), src.y()))
            dst_points.append((dst.x(), dst.y()))
            pair_indices.append(i)

        if len(src_points) < 4:
            QMessageBox.warning(self, "Недостаточно точек", "Нужно минимум 4 полных пары.")
            return

        # Расчёт
        result, method = auto_select_method(src_points, dst_points)

        if not result.success:
            QMessageBox.critical(self, "Ошибка", "Не удалось рассчитать трансформацию.")
            return

        self._transform_result = result
        self._transform_method = method

        # Обновляем UI
        self._display_result(result, pair_indices)
        self.save_btn.setEnabled(self._layer_editable)

        log_info(
            f"Fsm_0_6_1: Расчёт завершён. Метод={result.method_name}, "
            f"RMSE={result.rmse:.4f}м"
        )

    def _display_result(self, result: TransformResult, pair_indices: List[int]):
        """Отобразить результаты расчёта."""
        # RMSE
        rmse_str = f"{result.rmse:.4f} м"
        self.rmse_edit.setText(rmse_str)
        if result.rmse <= RMSE_THRESHOLD:
            self.rmse_edit.setStyleSheet("background-color: rgb(200, 255, 200);")
        else:
            self.rmse_edit.setStyleSheet("background-color: rgb(255, 200, 200);")

        # Метод
        self.method_edit.setText(result.method_name)

        # Параметры
        params = result.params
        self.dx_edit.setText(f"{params.get('dx', 0.0):.2f} м")
        self.dy_edit.setText(f"{params.get('dy', 0.0):.2f} м")

        rotation_deg = params.get('rotation_deg', 0.0)
        rotation_arcsec = params.get('rotation_arcsec', 0.0)
        if rotation_deg is not None:
            self.rotation_edit.setText(f"{rotation_deg:.6f} ({rotation_arcsec:.2f}\")")
        else:
            self.rotation_edit.setText("N/A")

        scale = params.get('scale', 1.0)
        scale_ppm = params.get('scale_ppm', 0.0)
        if scale is not None:
            self.scale_edit.setText(f"{scale:.8f} ({scale_ppm:.2f} ppm)")
        else:
            self.scale_edit.setText("N/A")

        # Max невязка
        if result.residuals:
            max_res = result.max_residual
            max_idx = result.residuals.index(max_res) if max_res in result.residuals else 0
            # pair_indices маппит обратно к строке таблицы
            table_row = pair_indices[max_idx] if max_idx < len(pair_indices) else max_idx
            self.max_residual_edit.setText(f"{max_res:.4f} м (пара N{table_row + 1})")
        else:
            self.max_residual_edit.setText("N/A")

        # Невязки в таблице
        for i, residual in enumerate(result.residuals):
            if i >= len(pair_indices):
                break
            table_row = pair_indices[i]
            item = QTableWidgetItem(f"{residual:.4f}")
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

            # Цвет невязки
            if i in result.blunder_indices:
                item.setBackground(QBrush(COLOR_RESIDUAL_BLUNDER))
            elif residual <= RMSE_THRESHOLD:
                item.setBackground(QBrush(COLOR_RESIDUAL_OK))
            else:
                item.setBackground(QBrush(COLOR_RESIDUAL_BAD))

            self.table.setItem(table_row, 7, item)

        # Предупреждение о blunders
        if result.blunder_indices:
            blunder_rows = [pair_indices[i] + 1 for i in result.blunder_indices
                            if i < len(pair_indices)]
            QMessageBox.warning(
                self,
                "Грубые ошибки",
                f"Подозрительные пары (невязка > 3x медианы): N{blunder_rows}\n"
                f"Рекомендуется перевыбрать или удалить эти пары."
            )

    # ========== Save / Cancel ==========

    def _on_save(self):
        """Применить трансформацию к слою."""
        layer = self._get_target_layer()
        if not layer:
            QMessageBox.critical(self, "Ошибка", "Слой не выбран.")
            return

        if not self._transform_result or not self._transform_method:
            QMessageBox.critical(self, "Ошибка", "Сначала рассчитайте трансформацию.")
            return

        # Предупреждение если RMSE > 0.01м
        if self._transform_result.rmse > RMSE_THRESHOLD:
            reply = QMessageBox.question(
                self,
                "RMSE превышает порог",
                f"RMSE = {self._transform_result.rmse:.4f} м > {RMSE_THRESHOLD} м.\n"
                f"Применить трансформацию?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Предупреждение о blunders
        if self._transform_result.blunder_indices:
            reply = QMessageBox.question(
                self,
                "Грубые ошибки",
                "Обнаружены подозрительные пары. Продолжить?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Backup
        self._backup = TransformApplicator.backup_layer(layer)

        # Применение
        success, warnings = TransformApplicator.apply_transform(
            layer, self._transform_method
        )

        if not success:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось применить трансформацию:\n{chr(10).join(warnings)}"
            )
            # Restore
            if self._backup:
                TransformApplicator.restore_from_backup(layer, self._backup)
                self._backup = None
            return

        # Пост-валидация
        validation_warnings = TransformApplicator.validate_result(layer)
        if validation_warnings:
            QMessageBox.warning(
                self,
                "Предупреждения",
                "Трансформация применена, но есть замечания:\n" +
                "\n".join(validation_warnings)
            )

        if warnings:
            log_warning(f"Fsm_0_6_1: Предупреждения: {warnings}")

        # Успех
        self._backup = None  # Не нужен rollback
        self.iface.messageBar().pushMessage(
            "Трансформация",
            f"Координаты слоя '{layer.name()}' обновлены. "
            f"Метод: {self._transform_result.method_name}, "
            f"RMSE: {self._transform_result.rmse:.4f} м",
            level=Qgis.MessageLevel.Success,
            duration=5
        )

        log_info(
            f"Fsm_0_6_1: Трансформация применена к '{layer.name()}'. "
            f"Метод={self._transform_result.method_name}, "
            f"RMSE={self._transform_result.rmse:.4f}м"
        )

        # Обновить карту
        self.iface.mapCanvas().refreshAllLayers()

        # Закрыть диалог
        self.clear_all_graphics()
        self.parent_tool.deactivate_map_tool()
        self.accept()

    def _on_cancel(self):
        """Отмена: восстановить из backup если нужно."""
        layer = self._get_target_layer()

        if self._backup and layer:
            reply = QMessageBox.question(
                self,
                "Отмена",
                "Восстановить исходные координаты?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                TransformApplicator.restore_from_backup(layer, self._backup)
                self.iface.mapCanvas().refreshAllLayers()
                self._backup = None

        self.clear_all_graphics()
        self.parent_tool.deactivate_map_tool()
        self.reject()

    # ========== Map graphics ==========

    def draw_pair_graphics(self, row: int):
        """Рисование стрелки и маркеров для пары точек."""
        self.clear_pair_graphics(row)

        pair = self.point_pairs[row]
        if pair is None:
            return

        src, dst = pair
        if dst == QgsPointXY(0, 0):
            return

        canvas = self.iface.mapCanvas()
        color = PAIR_COLORS[row % len(PAIR_COLORS)]

        # Инициализируем хранилище
        self.pair_graphics[row] = {'arrows': [], 'markers': [], 'labels': []}

        # --- Стрелка ---
        line_geom = QgsGeometry.fromPolylineXY([src, dst])
        arrow_band = QgsRubberBand(canvas, Qgis.GeometryType.Line)
        arrow_band.setColor(color)
        arrow_band.setWidth(3)
        arrow_band.setToGeometry(line_geom)
        self.pair_graphics[row]['arrows'].append(arrow_band)

        # Наконечник стрелки
        dx = dst.x() - src.x()
        dy = dst.y() - src.y()
        angle = math.atan2(dy, dx)
        line_length = math.sqrt(dx ** 2 + dy ** 2)

        if line_length > 0:
            arrow_length = min(line_length * 0.20, 50)
            arrow_angle = math.radians(25)

            for sign in [1, -1]:
                px = dst.x() - arrow_length * math.cos(angle + sign * arrow_angle)
                py = dst.y() - arrow_length * math.sin(angle + sign * arrow_angle)
                arrow_part = QgsRubberBand(canvas, Qgis.GeometryType.Line)
                arrow_part.setColor(color)
                arrow_part.setWidth(3)
                arrow_part.setToGeometry(
                    QgsGeometry.fromPolylineXY([dst, QgsPointXY(px, py)])
                )
                self.pair_graphics[row]['arrows'].append(arrow_part)

        # --- Маркеры ---
        # Исходная (квадрат)
        marker_src = QgsVertexMarker(canvas)
        marker_src.setCenter(src)
        marker_src.setColor(color)
        marker_src.setFillColor(QColor(255, 255, 255, 180))
        marker_src.setIconType(QgsVertexMarker.ICON_BOX)
        marker_src.setIconSize(14)
        marker_src.setPenWidth(2)
        self.pair_graphics[row]['markers'].append(marker_src)

        # Целевая (круг)
        marker_dst = QgsVertexMarker(canvas)
        marker_dst.setCenter(dst)
        marker_dst.setColor(color)
        marker_dst.setFillColor(QColor(255, 255, 255, 180))
        marker_dst.setIconType(QgsVertexMarker.ICON_CIRCLE)
        marker_dst.setIconSize(14)
        marker_dst.setPenWidth(2)
        self.pair_graphics[row]['markers'].append(marker_dst)

        # --- Текстовая подпись ---
        self._create_label(src, dst, str(row + 1), row)

        # Подключаем обработчик extent
        self._connect_extent_changed()

    def _create_label(self, point1: QgsPointXY, point2: QgsPointXY, text: str, row: int):
        """Создать подпись на середине отрезка."""
        canvas = self.iface.mapCanvas()

        mid_x = (point1.x() + point2.x()) / 2
        mid_y = (point1.y() + point2.y()) / 2
        mid_point = QgsPointXY(mid_x, mid_y)

        map_to_pixel = canvas.getCoordinateTransform()
        pixel_point = map_to_pixel.transform(mid_point)

        text_item = QGraphicsSimpleTextItem(text)
        font = QFont("Arial", 12, QFont.Weight.Bold)
        text_item.setFont(font)
        text_item.setBrush(QBrush(QColor(0, 0, 0)))
        text_item.setPen(QPen(QColor(255, 255, 255), 0.5))
        text_item.setPos(pixel_point.x() - 6, pixel_point.y() - 10)

        canvas.scene().addItem(text_item)

        if row in self.pair_graphics:
            self.pair_graphics[row]['labels'].append(text_item)

    def _connect_extent_changed(self):
        """Подключить обработчик изменения extent."""
        if self._extent_changed_connected:
            return
        self.iface.mapCanvas().extentsChanged.connect(self._on_extent_changed)
        self._extent_changed_connected = True

    def _disconnect_extent_changed(self):
        """Отключить обработчик изменения extent."""
        if not self._extent_changed_connected:
            return
        try:
            self.iface.mapCanvas().extentsChanged.disconnect(self._on_extent_changed)
        except (RuntimeError, TypeError):
            pass
        self._extent_changed_connected = False

    def _on_extent_changed(self):
        """Перерисовка подписей при изменении extent."""
        canvas = self.iface.mapCanvas()
        scene = canvas.scene()

        for row, graphics in self.pair_graphics.items():
            # Удаляем старые подписи
            for label in graphics.get('labels', []):
                scene.removeItem(label)
            graphics['labels'] = []

            # Перерисовываем
            pair = self.point_pairs[row]
            if pair is None:
                continue
            src, dst = pair
            if dst == QgsPointXY(0, 0):
                continue

            self._create_label(src, dst, str(row + 1), row)

    def clear_pair_graphics(self, row: int):
        """Удалить графику конкретной пары."""
        if row not in self.pair_graphics:
            return

        graphics = self.pair_graphics[row]
        scene = self.iface.mapCanvas().scene()

        for arrow in graphics.get('arrows', []):
            arrow.reset()
            scene.removeItem(arrow)

        for marker in graphics.get('markers', []):
            scene.removeItem(marker)

        for label in graphics.get('labels', []):
            scene.removeItem(label)

        del self.pair_graphics[row]

    def clear_all_graphics(self):
        """Очистить всю графику с карты."""
        self._disconnect_extent_changed()
        for row in list(self.pair_graphics.keys()):
            self.clear_pair_graphics(row)
        self.pair_graphics.clear()

    # ========== Dialog lifecycle ==========

    def closeEvent(self, event):
        """Обработка закрытия диалога."""
        self.clear_all_graphics()
        self.parent_tool.deactivate_map_tool()

        # Restore если был backup
        layer = self._get_target_layer()
        if self._backup and layer:
            TransformApplicator.restore_from_backup(layer, self._backup)
            self.iface.mapCanvas().refreshAllLayers()
            self._backup = None

        super().closeEvent(event)
