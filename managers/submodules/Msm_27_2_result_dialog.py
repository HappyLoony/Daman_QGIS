# -*- coding: utf-8 -*-
"""
Msm_27_2_ResultDialog - GUI диалог результатов валидации минимальных площадей

Отображает таблицу проблемных контуров с возможностью:
- Просмотра списка контуров с недостаточной площадью
- Выделения контура на карте
- Экспорта в CSV (опционально)
"""

from typing import Dict, List, Optional, Any

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QHeaderView, QAbstractItemView,
    QMessageBox
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsProject,
    QgsRectangle, QgsCoordinateReferenceSystem, QgsCoordinateTransform
)
from qgis.gui import QgsRubberBand

from Daman_QGIS.utils import log_info, log_error


class MinAreaResultDialog(QDialog):
    """Диалог отображения контуров с недостаточной площадью"""

    # Колонки таблицы
    COLUMNS = [
        ('ID', 60),
        ('Услов_КН', 120),
        ('План_ВРИ', 200),
        ('Площадь', 80),
        ('Мин.площадь', 90),
        ('Дефицит', 80),
        ('Слой', 150),
    ]

    def __init__(
        self,
        problems: List[Dict],
        zpr_type: str,
        parent: Optional[Any] = None
    ) -> None:
        """Инициализация диалога

        Args:
            problems: Список проблемных контуров
            zpr_type: Тип ЗПР для заголовка
            parent: Родительский виджет
        """
        super().__init__(parent)
        self._problems = problems
        self._zpr_type = zpr_type
        self._rubber_band: Optional[QgsRubberBand] = None

        self._setup_ui()
        self._populate_table()

    def _setup_ui(self) -> None:
        """Настройка интерфейса"""
        self.setWindowTitle(f'Проверка минимальных площадей - {self._zpr_type}')
        self.setMinimumSize(800, 400)
        self.resize(900, 500)

        layout = QVBoxLayout(self)

        # Заголовок с количеством проблем
        header_label = QLabel(
            f'Найдено контуров с недостаточной площадью: {len(self._problems)}'
        )
        header_label.setStyleSheet('font-weight: bold; font-size: 12pt;')
        layout.addWidget(header_label)

        # Таблица
        self._table = QTableWidget()
        self._table.setColumnCount(len(self.COLUMNS))
        self._table.setHorizontalHeaderLabels([col[0] for col in self.COLUMNS])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        # Настройка ширины колонок
        header = self._table.horizontalHeader()
        for i, (_, width) in enumerate(self.COLUMNS):
            self._table.setColumnWidth(i, width)
        header.setStretchLastSection(True)

        # Сигнал двойного клика - выделение на карте
        self._table.doubleClicked.connect(self._on_row_double_clicked)

        layout.addWidget(self._table)

        # Кнопки
        button_layout = QHBoxLayout()

        self._zoom_btn = QPushButton('Выделить на карте')
        self._zoom_btn.clicked.connect(self._zoom_to_selected)
        self._zoom_btn.setEnabled(False)
        button_layout.addWidget(self._zoom_btn)

        # Включаем кнопку при выборе строки
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        button_layout.addStretch()

        close_btn = QPushButton('Закрыть')
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _populate_table(self) -> None:
        """Заполнение таблицы данными"""
        self._table.setRowCount(len(self._problems))

        for row, problem in enumerate(self._problems):
            # ID
            item = QTableWidgetItem(str(problem.get('feature_id', '-')))
            item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, 0, item)

            # Услов_КН
            item = QTableWidgetItem(str(problem.get('uslov_kn', '-')))
            self._table.setItem(row, 1, item)

            # План_ВРИ
            item = QTableWidgetItem(str(problem.get('plan_vri', '-')))
            self._table.setItem(row, 2, item)

            # Площадь (факт)
            actual = problem.get('actual_area', 0)
            item = QTableWidgetItem(f'{actual:,}'.replace(',', ' ') if actual else '-')
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(row, 3, item)

            # Мин. площадь
            min_area = problem.get('min_area', 0)
            item = QTableWidgetItem(f'{min_area:,}'.replace(',', ' ') if min_area else '-')
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(row, 4, item)

            # Дефицит
            deficit = problem.get('deficit', 0)
            item = QTableWidgetItem(f'{deficit:,}'.replace(',', ' ') if deficit else '-')
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            # Подсветка дефицита красным
            if deficit and deficit > 0:
                item.setForeground(QColor(200, 0, 0))
            self._table.setItem(row, 5, item)

            # Слой
            item = QTableWidgetItem(str(problem.get('layer_name', '-')))
            self._table.setItem(row, 6, item)

    def _on_selection_changed(self) -> None:
        """Обработка изменения выбора в таблице"""
        has_selection = len(self._table.selectedItems()) > 0
        self._zoom_btn.setEnabled(has_selection)

    def _on_row_double_clicked(self) -> None:
        """Обработка двойного клика по строке"""
        self._zoom_to_selected()

    def _zoom_to_selected(self) -> None:
        """Выделить выбранный контур на карте"""
        selected_rows = self._table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        if row >= len(self._problems):
            return

        problem = self._problems[row]
        geometry = problem.get('geometry')

        if geometry is None or geometry.isEmpty():
            QMessageBox.warning(
                self,
                'Предупреждение',
                'Геометрия контура недоступна'
            )
            return

        try:
            from qgis.utils import iface
            canvas = iface.mapCanvas()

            # Удаляем предыдущую подсветку
            self._clear_rubber_band()

            # Создаем новую подсветку
            self._rubber_band = QgsRubberBand(canvas, geometry.type())
            self._rubber_band.setColor(QColor(255, 0, 0, 100))
            self._rubber_band.setWidth(3)
            self._rubber_band.setFillColor(QColor(255, 0, 0, 50))

            # Трансформируем геометрию если нужно
            layer_name = problem.get('layer_name', '')
            layer = self._get_layer_by_name(layer_name)

            if layer:
                layer_crs = layer.crs()
                canvas_crs = canvas.mapSettings().destinationCrs()

                if layer_crs != canvas_crs:
                    transform = QgsCoordinateTransform(
                        layer_crs, canvas_crs, QgsProject.instance()
                    )
                    geom_transformed = QgsGeometry(geometry)
                    geom_transformed.transform(transform)
                    self._rubber_band.setToGeometry(geom_transformed, None)
                else:
                    self._rubber_band.setToGeometry(geometry, None)
            else:
                self._rubber_band.setToGeometry(geometry, None)

            # Зуммируем к контуру
            bbox = geometry.boundingBox()

            if layer:
                layer_crs = layer.crs()
                canvas_crs = canvas.mapSettings().destinationCrs()
                if layer_crs != canvas_crs:
                    transform = QgsCoordinateTransform(
                        layer_crs, canvas_crs, QgsProject.instance()
                    )
                    bbox = transform.transformBoundingBox(bbox)

            # Добавляем отступ 10%
            bbox.scale(1.2)
            canvas.setExtent(bbox)
            canvas.refresh()

            log_info(f"Msm_27_2: Выделен контур ID={problem.get('feature_id')}")

        except Exception as e:
            log_error(f"Msm_27_2: Ошибка выделения контура: {e}")
            QMessageBox.warning(
                self,
                'Ошибка',
                f'Не удалось выделить контур: {e}'
            )

    def _get_layer_by_name(self, layer_name: str) -> Optional[QgsVectorLayer]:
        """Получить слой по имени"""
        layers = QgsProject.instance().mapLayersByName(layer_name)
        if layers:
            layer = layers[0]
            if isinstance(layer, QgsVectorLayer):
                return layer
        return None

    def _clear_rubber_band(self) -> None:
        """Удалить подсветку с карты"""
        if self._rubber_band:
            try:
                from qgis.utils import iface
                canvas = iface.mapCanvas()
                canvas.scene().removeItem(self._rubber_band)
            except Exception:
                pass
            self._rubber_band = None

    def closeEvent(self, event) -> None:
        """Очистка при закрытии"""
        self._clear_rubber_band()
        super().closeEvent(event)

    def reject(self) -> None:
        """Очистка при отмене"""
        self._clear_rubber_band()
        super().reject()

    def accept(self) -> None:
        """Очистка при подтверждении"""
        self._clear_rubber_band()
        super().accept()
