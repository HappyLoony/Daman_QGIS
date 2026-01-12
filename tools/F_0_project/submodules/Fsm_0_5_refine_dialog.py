# -*- coding: utf-8 -*-
"""
Диалог для инструмента уточнения проекции
Версия 3.0: Объединённый GUI с checkbox для межзональной проекции
"""

from typing import Optional, Tuple, List
import math
import re

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QLineEdit, QTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QCheckBox,
    QGraphicsSimpleTextItem
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont, QBrush, QPen

from qgis.core import (
    QgsPointXY, Qgis, QgsGeometry, QgsWkbTypes,
    QgsProject, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsVectorLayer, QgsCsException
)
from qgis.gui import QgsRubberBand, QgsVertexMarker

from Daman_QGIS.constants import (
    MESSAGE_SUCCESS_DURATION, MESSAGE_INFO_DURATION, PRECISION_DECIMALS,
    ELLPS_KRASS, TOWGS84_SK42_PROJ,
    RMSE_THRESHOLD_OK, RMSE_THRESHOLD_WARNING, RMSE_THRESHOLD_WRONG_CRS,
    RMS_ERROR_THRESHOLD
)
from Daman_QGIS.utils import log_info, log_warning, log_error


class RefineProjectionDialog(QDialog):
    """Диалог уточнения проекции через контрольные точки (минимум 4 пары)"""

    # Порог отклонения для подсветки проблемных пар (в метрах)
    DEVIATION_WARNING_THRESHOLD = 1.0

    def __init__(self, iface, parent_tool):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.parent_tool = parent_tool

        # Данные точек: динамический список пар, начинаем с 4
        # Формат: (wrong_msk, correct_3857) - wrong в CRS слоя объекта, correct в 3857
        self.point_pairs: List[Optional[Tuple[QgsPointXY, QgsPointXY]]] = [None, None, None, None]

        # ИСХОДНЫЕ пары точек для перерасчёта СК (сохраняются с исходной CRS)
        # Формат: (wrong_msk_original, correct_3857, original_crs_authid)
        # Используются для "Перерасчёт СК" чтобы избежать проблемы round-trip после калибровки
        # Тип: элементы кортежа могут быть None (частично заполненные пары)
        self.original_point_pairs: List[Optional[Tuple[Optional[QgsPointXY], Optional[QgsPointXY], Optional[str]]]] = [None, None, None, None]

        # Отклонения для каждой пары (заполняются после расчёта)
        self.pair_deviations: List[Optional[float]] = [None, None, None, None]

        # Результаты вычислений (обычный режим)
        self.delta_x = 0.0
        self.delta_y = 0.0
        self.avg_error = 0.0

        # Параметры перерасчёта СК
        self.interzonal_mode = False
        self.interzonal_params = {}  # lon_0, lat_0, k_0, x_0, y_0
        self.object_bounds = None  # (min_lon, max_lon)
        self.object_center = None  # (center_lon, center_lat)

        # Текущий режим выбора
        self.current_selection_pair = None  # Индекс пары (0-3)
        self.current_selection_point = None  # 'wrong' или 'correct'

        # Графические элементы на карте (словарь по номеру пары)
        # Формат: {pair_index: {'arrow': [QgsRubberBand, ...], 'markers': [QgsVertexMarker, ...]}}
        self.pair_graphics: dict = {}

        # CRS management для режима калибровки
        self.original_project_crs = None  # Исходная CRS проекта (для восстановления)
        self.object_layer = None  # Слой объекта с МСК (калибруемый)
        self.object_layer_crs = None  # CRS слоя объекта
        self.initial_object_layer_crs = None  # ИСХОДНАЯ CRS слоя объекта (до любых калибровок)

        # Подключение к сигналу изменения extent для перерисовки подписей
        self._extent_changed_connected = False

        self.setup_ui()

    def setup_ui(self):
        """Настройка интерфейса"""
        self.setWindowTitle("0_5 Уточнение проекции")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(700)
        self.setMinimumHeight(650)

        layout = QVBoxLayout()

        # Checkbox перерасчёта СК (итеративный подбор lon_0 включён по умолчанию)
        self.interzonal_checkbox = QCheckBox(
            "Перерасчет СК (итеративный подбор lon_0, k_0)"
        )
        self.interzonal_checkbox.setToolTip(
            "Создание кастомной проекции Transverse Mercator.\n"
            "lon_0 подбирается по контрольным точкам (минимум 2 пары).\n"
            "Если точек мало - расчёт по центру extent слоя L_1_1_1_Границы_работ."
        )
        self.interzonal_checkbox.stateChanged.connect(self.on_interzonal_toggled)
        layout.addWidget(self.interzonal_checkbox)

        # Автоматическое определение CRS объекта (из Project CRS до переключения на 3857)
        self._auto_detect_object_crs()

        # Информация (НОВЫЙ ПОРЯДОК: Wrong=объект, Correct=WFS)
        info_label = QLabel(
            "ПОРЯДОК ВЫБОРА ТОЧЕК (Project CRS = 3857 на время калибровки):\n"
            "1. 'Неправильная' = где объект СЕЙЧАС (клик на объекте в МСК)\n"
            "2. 'Правильная' = где объект ДОЛЖЕН БЫТЬ (клик на WFS в 3857)\n"
            "Стрелка указывает ОТ объекта К эталону WFS."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Таблица точек
        points_group = QGroupBox("Контрольные точки (4 пары обязательны)")
        points_layout = QVBoxLayout()

        self.points_table = QTableWidget(4, 6)
        self.points_table.setHorizontalHeaderLabels([
            "№", "Неправильная X", "Неправильная Y", "Правильная X", "Правильная Y", "Отклонение"
        ])

        # Настройка таблицы
        self.points_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.points_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.points_table.verticalHeader().setVisible(False)

        # Настройка ширины колонок
        header = self.points_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.points_table.setColumnWidth(0, 40)
        for i in range(1, 5):
            header.setSectionResizeMode(i, QHeaderView.Stretch)
        # Колонка "Отклонение" - фиксированная ширина
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        self.points_table.setColumnWidth(5, 90)

        # Заполняем номера пар
        for i in range(4):
            item = QTableWidgetItem(str(i + 1))
            item.setFlags(Qt.ItemIsEnabled)  # Только чтение
            item.setTextAlignment(Qt.AlignCenter)
            self.points_table.setItem(i, 0, item)

            # Создаем ячейки для координат
            for col in range(1, 5):
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignCenter)
                self.points_table.setItem(i, col, item)

            # Ячейка для отклонения (только чтение)
            deviation_item = QTableWidgetItem("")
            deviation_item.setFlags(Qt.ItemIsEnabled)  # Только чтение
            deviation_item.setTextAlignment(Qt.AlignCenter)
            self.points_table.setItem(i, 5, deviation_item)

        # Подключаем обработчик изменения ячеек
        self.points_table.itemChanged.connect(self.on_table_cell_changed)

        # Подключаем обработчик выбора ячейки
        self.points_table.itemSelectionChanged.connect(self.on_table_selection_changed)

        points_layout.addWidget(self.points_table)

        # Кнопки управления таблицей
        table_buttons = QHBoxLayout()

        self.add_pair_button = QPushButton("+ Добавить пару")
        self.add_pair_button.clicked.connect(self.on_add_pair_clicked)
        self.add_pair_button.setToolTip("Добавить ещё одну пару контрольных точек")
        table_buttons.addWidget(self.add_pair_button)

        self.remove_pair_button = QPushButton("- Удалить пару")
        self.remove_pair_button.clicked.connect(self.on_remove_pair_clicked)
        self.remove_pair_button.setEnabled(False)
        self.remove_pair_button.setToolTip("Удалить последнюю пару точек (минимум 4 пары)")
        table_buttons.addWidget(self.remove_pair_button)

        table_buttons.addStretch()

        self.clear_row_button = QPushButton("Очистить строку")
        self.clear_row_button.clicked.connect(self.on_clear_row_clicked)
        self.clear_row_button.setEnabled(False)
        table_buttons.addWidget(self.clear_row_button)

        self.clear_all_button = QPushButton("Очистить все")
        self.clear_all_button.clicked.connect(self.on_clear_all_clicked)
        table_buttons.addWidget(self.clear_all_button)

        points_layout.addLayout(table_buttons)

        points_group.setLayout(points_layout)
        layout.addWidget(points_group)

        # Группа результатов (обычный режим)
        results_group = QGroupBox("Вычисленное смещение")
        results_layout = QVBoxLayout()

        # Средние смещения
        offset_layout = QHBoxLayout()
        offset_layout.addWidget(QLabel("Среднее смещение:"))
        offset_layout.addWidget(QLabel("ΔX:"))
        self.dx_edit = QLineEdit()
        self.dx_edit.setReadOnly(True)
        self.dx_edit.setPlaceholderText("0.0000 м")
        offset_layout.addWidget(self.dx_edit)
        offset_layout.addWidget(QLabel("ΔY:"))
        self.dy_edit = QLineEdit()
        self.dy_edit.setReadOnly(True)
        self.dy_edit.setPlaceholderText("0.0000 м")
        offset_layout.addWidget(self.dy_edit)
        results_layout.addLayout(offset_layout)

        # СКО (RMS)
        error_layout = QHBoxLayout()
        error_layout.addWidget(QLabel("СКО (RMS):"))
        self.error_edit = QLineEdit()
        self.error_edit.setReadOnly(True)
        self.error_edit.setPlaceholderText("0.00 м")
        error_layout.addWidget(self.error_edit)
        error_layout.addStretch()
        results_layout.addLayout(error_layout)

        results_group.setLayout(results_layout)
        layout.addWidget(results_group)

        # Группа параметров перерасчёта СК (скрыта по умолчанию)
        self.interzonal_group = QGroupBox("Параметры перерасчёта СК")
        interzonal_layout = QVBoxLayout()

        # Центральный меридиан
        lon_layout = QHBoxLayout()
        lon_layout.addWidget(QLabel("Центральный меридиан (lon_0):"))
        self.lon_0_edit = QLineEdit()
        self.lon_0_edit.setReadOnly(True)
        self.lon_0_edit.setPlaceholderText("—")
        lon_layout.addWidget(self.lon_0_edit)
        lon_layout.addWidget(QLabel("°"))
        interzonal_layout.addLayout(lon_layout)

        # Масштабный коэффициент
        k_layout = QHBoxLayout()
        k_layout.addWidget(QLabel("Масштабный коэффициент (k_0):"))
        self.k_0_edit = QLineEdit()
        self.k_0_edit.setReadOnly(True)
        self.k_0_edit.setPlaceholderText("—")
        k_layout.addWidget(self.k_0_edit)
        interzonal_layout.addLayout(k_layout)

        # Ожидаемое искажение
        dist_layout = QHBoxLayout()
        dist_layout.addWidget(QLabel("Ожидаемое искажение:"))
        self.distortion_edit = QLineEdit()
        self.distortion_edit.setReadOnly(True)
        self.distortion_edit.setPlaceholderText("—")
        dist_layout.addWidget(self.distortion_edit)
        dist_layout.addWidget(QLabel("ppm"))
        interzonal_layout.addLayout(dist_layout)

        # Смещения x_0, y_0
        xy_layout = QHBoxLayout()
        xy_layout.addWidget(QLabel("x_0:"))
        self.x_0_edit = QLineEdit()
        self.x_0_edit.setReadOnly(True)
        self.x_0_edit.setPlaceholderText("—")
        xy_layout.addWidget(self.x_0_edit)
        xy_layout.addWidget(QLabel("м"))
        xy_layout.addWidget(QLabel("y_0:"))
        self.y_0_edit = QLineEdit()
        self.y_0_edit.setReadOnly(True)
        self.y_0_edit.setPlaceholderText("—")
        xy_layout.addWidget(self.y_0_edit)
        xy_layout.addWidget(QLabel("м"))
        interzonal_layout.addLayout(xy_layout)

        self.interzonal_group.setLayout(interzonal_layout)
        self.interzonal_group.setVisible(False)
        layout.addWidget(self.interzonal_group)

        # Статус
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(80)
        self.status_text.setPlainText(
            "Выберите ячейку в таблице и кликните на карте для указания координат.\n"
            "Или введите координаты вручную."
        )
        layout.addWidget(self.status_text)

        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        self.calculate_button = QPushButton("Рассчитать")
        self.calculate_button.clicked.connect(self.on_calculate_clicked)
        self.calculate_button.setEnabled(False)
        buttons_layout.addWidget(self.calculate_button)

        self.save_button = QPushButton("Сохранить")
        self.save_button.clicked.connect(self.on_save_clicked)
        self.save_button.setEnabled(False)
        buttons_layout.addWidget(self.save_button)

        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.clicked.connect(self.on_cancel_clicked)
        buttons_layout.addWidget(self.cancel_button)

        layout.addLayout(buttons_layout)

        self.setLayout(layout)

    def on_interzonal_toggled(self, state):
        """Переключение межзонального режима"""
        self.interzonal_mode = (state == Qt.Checked)
        self.interzonal_group.setVisible(self.interzonal_mode)

        if self.interzonal_mode:
            # Загружаем extent из слоя границ
            if self.load_extent_from_boundaries():
                # Рассчитываем предварительные параметры
                self.calculate_interzonal_preview()
                log_info("Fsm_0_5: Перерасчёт СК активирован (итеративный подбор по умолчанию)")
            else:
                # Ошибка загрузки - откатываем checkbox
                self.interzonal_checkbox.blockSignals(True)
                self.interzonal_checkbox.setChecked(False)
                self.interzonal_checkbox.blockSignals(False)
                self.interzonal_mode = False
                self.interzonal_group.setVisible(False)
        else:
            # Очищаем параметры межзональной проекции
            self.interzonal_params = {}
            self.object_bounds = None
            self.object_center = None
            self.lon_0_edit.clear()
            self.k_0_edit.clear()
            self.distortion_edit.clear()
            self.x_0_edit.clear()
            self.y_0_edit.clear()
            log_info("Fsm_0_5: Перерасчёт СК деактивирован")

        # Сбрасываем результаты и кнопку сохранения
        self.save_button.setEnabled(False)

    def _auto_detect_object_crs(self):
        """Автоматическое определение CRS объекта из Project CRS.

        Вызывается при инициализации диалога ДО переключения на EPSG:3857.
        Сохраняет исходную CRS проекта как CRS объекта.

        ВАЖНО: initial_object_layer_crs сохраняется как ИСХОДНАЯ CRS и НЕ меняется
        при последующих калибровках. Используется для "Перерасчёт СК".
        """
        project = QgsProject.instance()
        current_crs = project.crs()

        # Сохраняем текущую CRS проекта как CRS объекта (если это не 3857)
        if current_crs.isValid() and current_crs.authid() != "EPSG:3857":
            self.object_layer_crs = current_crs
            self.original_project_crs = current_crs
            # ИСХОДНАЯ CRS для перерасчёта СК (не меняется после калибровок)
            if self.initial_object_layer_crs is None:
                self.initial_object_layer_crs = current_crs
            # Ищем слой с этой CRS для установки object_layer
            for layer in project.mapLayers().values():
                if isinstance(layer, QgsVectorLayer) and layer.crs() == current_crs:
                    self.object_layer = layer
                    break
            log_info(f"Fsm_0_5: Автоопределена CRS объекта из Project CRS: {current_crs.authid()}")
            log_info(f"Fsm_0_5: {current_crs.description()}")

            # Переключаем на режим калибровки
            self._switch_to_calibration_mode()
        else:
            # Project CRS уже 3857 или невалидна - пробуем найти МСК слой
            for layer in project.mapLayers().values():
                if isinstance(layer, QgsVectorLayer):
                    crs = layer.crs()
                    if crs.isValid() and crs.authid() != "EPSG:3857":
                        self.object_layer_crs = crs
                        self.original_project_crs = crs
                        # ИСХОДНАЯ CRS для перерасчёта СК
                        if self.initial_object_layer_crs is None:
                            self.initial_object_layer_crs = crs
                        self.object_layer = layer
                        log_info(f"Fsm_0_5: CRS объекта определена из слоя {layer.name()}: {crs.authid()}")
                        self._switch_to_calibration_mode()
                        return

            log_warning("Fsm_0_5: Не удалось определить CRS объекта автоматически")

    def _switch_to_calibration_mode(self) -> bool:
        """
        Переключает проект в режим калибровки:
        1. Сохраняет текущую CRS проекта
        2. Переключает Project CRS на EPSG:3857

        Returns:
            bool: True если успешно, False при ошибке
        """
        project = QgsProject.instance()

        # Сохраняем исходную CRS (только если ещё не сохранена)
        if self.original_project_crs is None:
            self.original_project_crs = project.crs()
            log_info(f"Fsm_0_5: Сохранена исходная CRS проекта: {self.original_project_crs.authid()}")

        # Переключаем на EPSG:3857
        web_mercator = QgsCoordinateReferenceSystem("EPSG:3857")
        project.setCrs(web_mercator)

        log_info(f"Fsm_0_5: Project CRS переключена на EPSG:3857 для калибровки")

        # Обновляем статус только если UI уже создан
        if hasattr(self, 'status_text'):
            self.status_text.setPlainText(
                f"Режим калибровки активирован.\n"
                f"Project CRS: EPSG:3857 (WFS слои отображаются корректно).\n"
                f"Слой объекта: {self.object_layer.name() if self.object_layer else 'не выбран'}\n"
                f"CRS объекта: {self.object_layer_crs.authid() if self.object_layer_crs else '—'}"
            )

        return True

    def _restore_original_crs(self):
        """Восстанавливает исходную CRS проекта (при отмене/закрытии)"""
        if self.original_project_crs and self.original_project_crs.isValid():
            QgsProject.instance().setCrs(self.original_project_crs)
            log_info(f"Fsm_0_5: Восстановлена исходная CRS: {self.original_project_crs.authid()}")
            self.original_project_crs = None

    def load_extent_from_boundaries(self) -> bool:
        """Загрузка extent из слоя L_1_1_1_Границы_работ"""
        target_layer_name = "L_1_1_1_Границы_работ"

        # Ищем слой по имени
        layers = QgsProject.instance().mapLayersByName(target_layer_name)

        if not layers:
            self.iface.messageBar().pushMessage(
                "Ошибка",
                f"Слой '{target_layer_name}' не найден в проекте",
                level=Qgis.Critical,
                duration=MESSAGE_INFO_DURATION
            )
            log_error(f"Fsm_0_5: Слой {target_layer_name} не найден")
            return False

        layer = layers[0]

        if not isinstance(layer, QgsVectorLayer):
            self.iface.messageBar().pushMessage(
                "Ошибка",
                f"Слой '{target_layer_name}' не является векторным",
                level=Qgis.Critical,
                duration=MESSAGE_INFO_DURATION
            )
            log_error(f"Fsm_0_5: Слой {target_layer_name} не векторный")
            return False

        # Получаем границы в WGS84
        source_crs = layer.crs()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")

        if source_crs != wgs84:
            transform = QgsCoordinateTransform(source_crs, wgs84, QgsProject.instance())
            extent = transform.transformBoundingBox(layer.extent())
        else:
            extent = layer.extent()

        # Сохраняем границы объекта
        min_lon = extent.xMinimum()
        max_lon = extent.xMaximum()
        center_lat = (extent.yMinimum() + extent.yMaximum()) / 2

        self.object_bounds = (min_lon, max_lon)
        self.object_center = ((min_lon + max_lon) / 2, center_lat)

        log_info(f"Fsm_0_5: Загружены границы из слоя {target_layer_name}")
        log_info(f"Fsm_0_5: Долгота: {min_lon:.6f}° — {max_lon:.6f}°, Широта центра: {center_lat:.6f}°")

        return True

    def calculate_interzonal_preview(self):
        """Расчёт предварительных параметров межзональной проекции (без калибровки x_0/y_0)"""
        if not self.object_bounds or not self.object_center:
            return

        from .Fsm_0_5_3_projection_optimizer import ProjectionOptimizer

        optimizer = ProjectionOptimizer()

        min_lon, max_lon = self.object_bounds
        center_lon, center_lat = self.object_center

        # Центральный меридиан - середина extent
        central_meridian = (min_lon + max_lon) / 2

        # Протяженность объекта в км
        extent_km = (max_lon - min_lon) * 111.32 * math.cos(math.radians(center_lat))

        # Масштабный коэффициент
        scale_factor = optimizer.calculate_optimal_scale_factor(extent_km / 2)

        # Ожидаемое искажение
        distortion_ppm = optimizer.estimate_distortion(
            central_meridian, scale_factor,
            (min_lon, max_lon), center_lat
        )

        # Показываем предварительные значения
        self.lon_0_edit.setText(f"{central_meridian:.6f}")
        self.k_0_edit.setText(f"{scale_factor:.8f}")
        self.distortion_edit.setText(f"{distortion_ppm:.2f}")
        self.x_0_edit.setText("(рассчитается)")
        self.y_0_edit.setText("(рассчитается)")

        self.status_text.setPlainText(
            f"Перерасчёт СК: параметры загружены из extent.\n"
            f"Протяженность объекта: {extent_km:.1f} км\n"
            f"Укажите 4 пары точек для калибровки x_0/y_0."
        )

    def on_table_selection_changed(self):
        """Обработка изменения выбранной ячейки"""
        selected = self.points_table.selectedItems()
        if not selected:
            self.current_selection_pair = None
            self.current_selection_point = None
            self.clear_row_button.setEnabled(False)
            return

        item = selected[0]
        row = item.row()
        col = item.column()

        # Определяем пару и тип точки
        self.current_selection_pair = row
        if col in [1, 2]:  # Неправильная точка
            self.current_selection_point = 'wrong'
        elif col in [3, 4]:  # Правильная точка
            self.current_selection_point = 'correct'
        else:
            self.current_selection_point = None

        self.clear_row_button.setEnabled(True)

        # Обновляем статус
        if self.current_selection_point:
            point_type = "неправильную" if self.current_selection_point == 'wrong' else "правильную"
            self.status_text.setPlainText(
                f"Выбрана пара {row + 1}, {point_type} точка.\n"
                f"Кликните на карте для указания координат."
            )

    def on_table_cell_changed(self, item):
        """Обработка изменения значения в ячейке"""
        row = item.row()
        col = item.column()

        if col == 0:  # Номер пары - не редактируем
            return

        # Проверяем валидность введенного значения
        text = item.text().strip()
        if not text:
            return

        try:
            float(text.replace(',', '.'))
            # Обновляем данные
            self.update_point_from_table(row)
            # Проверяем возможность расчета
            self.update_buttons_state()
        except ValueError:
            # Невалидное значение - очищаем
            self.points_table.blockSignals(True)
            item.setText("")
            self.points_table.blockSignals(False)

    def update_point_from_table(self, row):
        """Обновление данных точки из таблицы"""
        try:
            # Читаем координаты из таблицы
            wrong_x_text = self.points_table.item(row, 1).text().strip()
            wrong_y_text = self.points_table.item(row, 2).text().strip()
            correct_x_text = self.points_table.item(row, 3).text().strip()
            correct_y_text = self.points_table.item(row, 4).text().strip()

            # Если все 4 значения заполнены, создаем пару точек
            if all([wrong_x_text, wrong_y_text, correct_x_text, correct_y_text]):
                wrong_x = float(wrong_x_text.replace(',', '.'))
                wrong_y = float(wrong_y_text.replace(',', '.'))
                correct_x = float(correct_x_text.replace(',', '.'))
                correct_y = float(correct_y_text.replace(',', '.'))

                self.point_pairs[row] = (
                    QgsPointXY(wrong_x, wrong_y),
                    QgsPointXY(correct_x, correct_y)
                )
            else:
                self.point_pairs[row] = None

        except (ValueError, AttributeError):
            self.point_pairs[row] = None

    def set_point_from_map(self, point):
        """Установка точки из карты в текущую выбранную ячейку.

        НОВЫЙ WORKFLOW (Project CRS = EPSG:3857):
        - point приходит в CRS проекта (3857)
        - Wrong (объект в МСК): трансформируем 3857 → CRS слоя объекта
        - Correct (WFS): оставляем в 3857

        ВАЖНО: Также сохраняем ИСХОДНЫЕ координаты для "Перерасчёт СК".
        """
        if self.current_selection_pair is None or self.current_selection_point is None:
            return

        row = self.current_selection_pair

        # Блокируем сигналы чтобы не вызывать on_table_cell_changed
        self.points_table.blockSignals(True)

        # Записываем координаты в таблицу
        if self.current_selection_point == 'wrong':
            # Wrong = координаты объекта в его native CRS (МСК)
            # Трансформируем из Project CRS (3857) в CRS слоя объекта
            if self.object_layer_crs and self.object_layer_crs.isValid():
                try:
                    transform = QgsCoordinateTransform(
                        QgsProject.instance().crs(),  # 3857
                        self.object_layer_crs,         # МСК слоя объекта
                        QgsProject.instance()
                    )
                    point_in_msk = transform.transform(point)
                    self.points_table.item(row, 1).setText(f"{point_in_msk.x():.4f}")
                    self.points_table.item(row, 2).setText(f"{point_in_msk.y():.4f}")
                    log_info(f"Fsm_0_5: Wrong точка: 3857({point.x():.2f}, {point.y():.2f}) -> МСК({point_in_msk.x():.4f}, {point_in_msk.y():.4f})")

                    # Сохраняем ИСХОДНЫЕ координаты для перерасчёта СК
                    self._save_original_point(row, 'wrong', point_in_msk)

                except QgsCsException as e:
                    log_error(f"Fsm_0_5: Ошибка трансформации координат: {e}")
                    self.status_text.setPlainText(f"Ошибка трансформации: {e}")
                    self.points_table.blockSignals(False)
                    return
            else:
                # Fallback: используем как есть (если слой не выбран)
                self.points_table.item(row, 1).setText(f"{point.x():.4f}")
                self.points_table.item(row, 2).setText(f"{point.y():.4f}")
                log_warning("Fsm_0_5: Слой объекта не выбран, координаты сохранены без трансформации")
        else:  # correct
            # Correct = координаты WFS в 3857 (эталон)
            # Оставляем без трансформации
            self.points_table.item(row, 3).setText(f"{point.x():.4f}")
            self.points_table.item(row, 4).setText(f"{point.y():.4f}")
            log_info(f"Fsm_0_5: Correct точка (3857): ({point.x():.4f}, {point.y():.4f})")

            # Сохраняем ИСХОДНЫЕ координаты для перерасчёта СК
            self._save_original_point(row, 'correct', point)

        self.points_table.blockSignals(False)

        # Обновляем данные
        self.update_point_from_table(row)

        # Рисуем стрелку если пара заполнена
        if self.point_pairs[row] is not None:
            self.draw_pair_graphics(row)

        # Обновляем состояние кнопок
        self.update_buttons_state()

        # Автоматическое переключение на следующую ячейку
        self.auto_select_next_cell()

        # Обновляем статус
        self.update_status_text()

    def _save_original_point(self, row: int, point_type: str, point: QgsPointXY):
        """Сохраняет ИСХОДНУЮ координату точки для перерасчёта СК.

        ВАЖНО: Сохраняет координаты в момент первого указания точки,
        до любых калибровок. Используется для режима "Перерасчёт СК".

        Args:
            row: Индекс пары (0-based)
            point_type: 'wrong' (МСК) или 'correct' (3857)
            point: Координаты точки

        Формат original_point_pairs:
            (wrong_msk_original, correct_3857, original_crs_authid)
        """
        # Расширяем список если нужно
        while len(self.original_point_pairs) <= row:
            self.original_point_pairs.append(None)

        # Получаем текущую запись или создаём новую
        current = self.original_point_pairs[row]

        # Используем ИСХОДНУЮ CRS слоя (до калибровок) для wrong точек
        crs_authid = self.initial_object_layer_crs.authid() if self.initial_object_layer_crs else None

        if current is None:
            # Создаём новую запись
            if point_type == 'wrong':
                self.original_point_pairs[row] = (point, None, crs_authid)
            else:  # correct
                self.original_point_pairs[row] = (None, point, crs_authid)
        else:
            # Обновляем существующую запись
            wrong_orig, correct_orig, orig_crs = current
            if point_type == 'wrong':
                self.original_point_pairs[row] = (point, correct_orig, crs_authid)
            else:  # correct
                self.original_point_pairs[row] = (wrong_orig, point, orig_crs if orig_crs else crs_authid)

        log_info(
            f"Fsm_0_5: Сохранена исходная {point_type} точка для пары {row+1}: "
            f"({point.x():.4f}, {point.y():.4f}) [CRS: {crs_authid}]"
        )

    def auto_select_next_cell(self):
        """Автоматический выбор следующей ячейки после ввода точки"""
        if self.current_selection_pair is None or self.current_selection_point is None:
            return

        row = self.current_selection_pair

        # Если была выбрана "неправильная" точка, переходим к "правильной" в той же паре
        if self.current_selection_point == 'wrong':
            self.points_table.setCurrentCell(row, 3)
            return

        # Если была выбрана "правильная" точка, переходим к следующей паре
        if self.current_selection_point == 'correct':
            next_row = row + 1
            if next_row < len(self.point_pairs):
                self.points_table.setCurrentCell(next_row, 1)

    def draw_pair_graphics(self, row: int):
        """Рисование графики для пары точек: стрелка + маркеры с номером.

        Сначала удаляет старую графику для этой пары, затем рисует новую.
        Важно: wrong хранится в МСК (object_layer_crs), correct в EPSG:3857.
        Канвас карты в EPSG:3857, поэтому нужно трансформировать wrong в 3857.
        """
        # Удаляем старую графику для этой пары
        self.clear_pair_graphics(row)

        pair = self.point_pairs[row]
        if pair is None:
            return

        wrong_msk, correct_3857 = pair

        # Трансформируем wrong из МСК в EPSG:3857 (CRS канваса)
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()

        if self.object_layer_crs and self.object_layer_crs.isValid():
            transform_to_canvas = QgsCoordinateTransform(
                self.object_layer_crs, canvas_crs, QgsProject.instance()
            )
            wrong_canvas = transform_to_canvas.transform(wrong_msk)
        else:
            wrong_canvas = wrong_msk

        correct_canvas = correct_3857

        # Инициализируем хранилище графики для пары
        self.pair_graphics[row] = {'arrows': [], 'markers': []}

        # Цвета для разных пар (циклический набор)
        pair_colors = [
            QColor(255, 0, 0, 200),     # Красный
            QColor(0, 150, 0, 200),     # Зелёный
            QColor(0, 0, 255, 200),     # Синий
            QColor(255, 165, 0, 200),   # Оранжевый
            QColor(128, 0, 128, 200),   # Пурпурный
            QColor(0, 128, 128, 200),   # Бирюзовый
            QColor(139, 69, 19, 200),   # Коричневый
            QColor(255, 20, 147, 200),  # Розовый
        ]
        color = pair_colors[row % len(pair_colors)]

        # --- Рисуем стрелку ---
        line_geom = QgsGeometry.fromPolylineXY([wrong_canvas, correct_canvas])
        arrow_band = QgsRubberBand(self.iface.mapCanvas(), QgsWkbTypes.LineGeometry)
        arrow_band.setColor(color)
        arrow_band.setWidth(3)
        arrow_band.setToGeometry(line_geom)
        self.pair_graphics[row]['arrows'].append(arrow_band)

        # Наконечник стрелки
        dx = correct_canvas.x() - wrong_canvas.x()
        dy = correct_canvas.y() - wrong_canvas.y()
        angle = math.atan2(dy, dx)
        line_length = math.sqrt(dx**2 + dy**2)

        if line_length > 0:
            arrow_length = min(line_length * 0.20, 50)  # Ограничиваем размер наконечника
            arrow_angle = math.radians(25)

            arrow_p1_x = correct_canvas.x() - arrow_length * math.cos(angle + arrow_angle)
            arrow_p1_y = correct_canvas.y() - arrow_length * math.sin(angle + arrow_angle)
            arrow_p2_x = correct_canvas.x() - arrow_length * math.cos(angle - arrow_angle)
            arrow_p2_y = correct_canvas.y() - arrow_length * math.sin(angle - arrow_angle)

            for px, py in [(arrow_p1_x, arrow_p1_y), (arrow_p2_x, arrow_p2_y)]:
                arrow_part = QgsRubberBand(self.iface.mapCanvas(), QgsWkbTypes.LineGeometry)
                arrow_part.setColor(color)
                arrow_part.setWidth(3)
                arrow_part.setToGeometry(QgsGeometry.fromPolylineXY([
                    correct_canvas, QgsPointXY(px, py)
                ]))
                self.pair_graphics[row]['arrows'].append(arrow_part)

        # --- Рисуем маркеры с номером пары ---
        pair_number = row + 1

        # Маркер для "неправильной" точки (wrong) - квадрат
        marker_wrong = QgsVertexMarker(self.iface.mapCanvas())
        marker_wrong.setCenter(wrong_canvas)
        marker_wrong.setColor(color)
        marker_wrong.setFillColor(QColor(255, 255, 255, 180))
        marker_wrong.setIconType(QgsVertexMarker.ICON_BOX)
        marker_wrong.setIconSize(14)
        marker_wrong.setPenWidth(2)
        self.pair_graphics[row]['markers'].append(marker_wrong)

        # Маркер для "правильной" точки (correct) - круг
        marker_correct = QgsVertexMarker(self.iface.mapCanvas())
        marker_correct.setCenter(correct_canvas)
        marker_correct.setColor(color)
        marker_correct.setFillColor(QColor(255, 255, 255, 180))
        marker_correct.setIconType(QgsVertexMarker.ICON_CIRCLE)
        marker_correct.setIconSize(14)
        marker_correct.setPenWidth(2)
        self.pair_graphics[row]['markers'].append(marker_correct)

        # --- Текстовые подписи с номером пары ---
        # Только номер пары (без суффиксов)
        self._create_label(wrong_canvas, str(pair_number), color, row)
        self._create_label(correct_canvas, str(pair_number), color, row)

        # Подключаем обработчик изменения extent (один раз)
        self._connect_extent_changed()

    def _connect_extent_changed(self):
        """Подключает обработчик изменения extent для перерисовки подписей."""
        if self._extent_changed_connected:
            return

        canvas = self.iface.mapCanvas()
        canvas.extentsChanged.connect(self._on_extent_changed)
        self._extent_changed_connected = True

    def _disconnect_extent_changed(self):
        """Отключает обработчик изменения extent."""
        if not self._extent_changed_connected:
            return

        try:
            canvas = self.iface.mapCanvas()
            canvas.extentsChanged.disconnect(self._on_extent_changed)
        except (RuntimeError, TypeError):
            pass  # Сигнал уже отключен или объект уничтожен

        self._extent_changed_connected = False

    def _on_extent_changed(self):
        """Обработчик изменения extent - перерисовывает подписи."""
        self._redraw_labels_only()

    def _redraw_labels_only(self):
        """Перерисовывает только текстовые подписи (не стрелки и маркеры)."""
        canvas = self.iface.mapCanvas()
        scene = canvas.scene()

        for row, graphics in self.pair_graphics.items():
            # Удаляем старые подписи
            for label in graphics.get('labels', []):
                scene.removeItem(label)
            graphics['labels'] = []

            # Получаем точки пары
            pair = self.point_pairs[row]
            if pair is None:
                continue

            wrong_msk, correct_3857 = pair

            # Трансформируем wrong в координаты канваса
            canvas_crs = canvas.mapSettings().destinationCrs()

            if self.object_layer_crs and self.object_layer_crs.isValid():
                transform_to_canvas = QgsCoordinateTransform(
                    self.object_layer_crs, canvas_crs, QgsProject.instance()
                )
                wrong_canvas = transform_to_canvas.transform(wrong_msk)
            else:
                wrong_canvas = wrong_msk

            correct_canvas = correct_3857

            # Получаем цвет пары
            pair_colors = [
                QColor(255, 0, 0, 200),
                QColor(0, 150, 0, 200),
                QColor(0, 0, 255, 200),
                QColor(255, 165, 0, 200),
                QColor(128, 0, 128, 200),
                QColor(0, 128, 128, 200),
                QColor(139, 69, 19, 200),
                QColor(255, 20, 147, 200),
            ]
            color = pair_colors[row % len(pair_colors)]

            # Рисуем подписи
            pair_number = row + 1
            self._create_label(wrong_canvas, str(pair_number), color, row)
            self._create_label(correct_canvas, str(pair_number), color, row)

    def _create_label(self, point: QgsPointXY, text: str, color: QColor, row: int):
        """Создаёт текстовую подпись над точкой.

        Использует QGraphicsSimpleTextItem для отображения текста.
        Подписи обновляются при изменении extent через _on_extent_changed.
        """
        canvas = self.iface.mapCanvas()

        # Конвертируем map координаты в пиксели
        map_to_pixel = canvas.getCoordinateTransform()
        pixel_point = map_to_pixel.transform(point)

        # Создаём текстовый элемент
        text_item = QGraphicsSimpleTextItem(text)

        # Настраиваем шрифт
        font = QFont("Arial", 12, QFont.Bold)
        text_item.setFont(font)

        # Настраиваем цвет текста (контрастный)
        text_item.setBrush(QBrush(color))
        text_item.setPen(QPen(QColor(255, 255, 255), 2))  # Белая обводка толще

        # Позиционируем текст над точкой (смещение вверх от центра)
        text_item.setPos(pixel_point.x() - 6, pixel_point.y() - 28)

        # Добавляем на сцену канваса
        canvas.scene().addItem(text_item)

        # Сохраняем для последующего удаления
        if row in self.pair_graphics:
            if 'labels' not in self.pair_graphics[row]:
                self.pair_graphics[row]['labels'] = []
            self.pair_graphics[row]['labels'].append(text_item)

    def clear_pair_graphics(self, row: int):
        """Удаление графики конкретной пары"""
        if row not in self.pair_graphics:
            return

        graphics = self.pair_graphics[row]
        scene = self.iface.mapCanvas().scene()

        # Удаляем стрелки
        for arrow in graphics.get('arrows', []):
            arrow.reset()
            scene.removeItem(arrow)

        # Удаляем маркеры
        for marker in graphics.get('markers', []):
            scene.removeItem(marker)

        # Удаляем текстовые подписи
        for label in graphics.get('labels', []):
            scene.removeItem(label)

        del self.pair_graphics[row]

    def clear_all_graphics(self):
        """Очистка всей графики с карты"""
        # Отключаем обработчик extent
        self._disconnect_extent_changed()

        for row in list(self.pair_graphics.keys()):
            self.clear_pair_graphics(row)
        self.pair_graphics.clear()

    def redraw_all_graphics(self):
        """Перерисовка графики для всех заполненных пар"""
        self.clear_all_graphics()
        for i in range(len(self.point_pairs)):
            if self.point_pairs[i] is not None:
                self.draw_pair_graphics(i)

    def update_status_text(self):
        """Обновление текста статуса"""
        filled_count = sum(1 for pair in self.point_pairs if pair is not None)
        total_pairs = len(self.point_pairs)
        mode_text = "перерасчёт СК" if self.interzonal_mode else "обычный режим"
        self.status_text.setPlainText(
            f"Заполнено пар: {filled_count}/{total_pairs} ({mode_text})\n"
            f"Выберите ячейку в таблице и кликните на карте."
        )

    def update_buttons_state(self):
        """Обновление состояния кнопок"""
        all_filled = all(pair is not None for pair in self.point_pairs)
        self.calculate_button.setEnabled(all_filled)
        # Кнопка удаления пары активна только если пар больше 4
        self.remove_pair_button.setEnabled(len(self.point_pairs) > 4)

    def on_add_pair_clicked(self):
        """Добавление новой пары точек"""
        row_count = self.points_table.rowCount()
        new_row = row_count

        # Добавляем строку в таблицу
        self.points_table.blockSignals(True)
        self.points_table.insertRow(new_row)

        # Номер пары
        item = QTableWidgetItem(str(new_row + 1))
        item.setFlags(Qt.ItemIsEnabled)
        item.setTextAlignment(Qt.AlignCenter)
        self.points_table.setItem(new_row, 0, item)

        # Ячейки для координат
        for col in range(1, 5):
            item = QTableWidgetItem("")
            item.setTextAlignment(Qt.AlignCenter)
            self.points_table.setItem(new_row, col, item)

        # Ячейка для отклонения
        deviation_item = QTableWidgetItem("")
        deviation_item.setFlags(Qt.ItemIsEnabled)
        deviation_item.setTextAlignment(Qt.AlignCenter)
        self.points_table.setItem(new_row, 5, deviation_item)

        self.points_table.blockSignals(False)

        # Добавляем элемент в списки данных
        self.point_pairs.append(None)
        self.pair_deviations.append(None)
        self.original_point_pairs.append(None)  # Исходные пары для перерасчёта СК

        log_info(f"Fsm_0_5: Добавлена пара {new_row + 1}. Всего пар: {len(self.point_pairs)}")

        self.update_buttons_state()
        self.update_status_text()

    def on_remove_pair_clicked(self):
        """Удаление последней пары точек (минимум 4 пары сохраняется)"""
        if len(self.point_pairs) <= 4:
            return

        row_to_remove = self.points_table.rowCount() - 1

        # Удаляем строку из таблицы
        self.points_table.blockSignals(True)
        self.points_table.removeRow(row_to_remove)
        self.points_table.blockSignals(False)

        # Удаляем элемент из списков
        self.point_pairs.pop()
        self.pair_deviations.pop()
        if len(self.original_point_pairs) > 4:
            self.original_point_pairs.pop()  # Исходные пары

        # Перерисовываем всю графику (индексы изменились)
        self.redraw_all_graphics()

        log_info(f"Fsm_0_5: Удалена пара {row_to_remove + 1}. Осталось пар: {len(self.point_pairs)}")

        self.update_buttons_state()
        self.update_status_text()

    def on_clear_row_clicked(self):
        """Очистка выбранной строки"""
        if self.current_selection_pair is None:
            return

        row = self.current_selection_pair

        self.points_table.blockSignals(True)
        for col in range(1, 6):  # Включаем колонку отклонения
            self.points_table.item(row, col).setText("")
        self.points_table.blockSignals(False)

        self.point_pairs[row] = None
        self.pair_deviations[row] = None
        if row < len(self.original_point_pairs):
            self.original_point_pairs[row] = None  # Очищаем исходные

        # Удаляем графику только для этой пары
        self.clear_pair_graphics(row)

        self.update_buttons_state()
        self.update_status_text()

    def on_clear_all_clicked(self):
        """Очистка всех точек (сбрасывает к 4 парам)"""
        # Удаляем лишние строки, оставляем 4
        self.points_table.blockSignals(True)
        while self.points_table.rowCount() > 4:
            self.points_table.removeRow(self.points_table.rowCount() - 1)

        # Очищаем оставшиеся строки
        for row in range(4):
            for col in range(1, 6):  # Включаем колонку отклонения
                self.points_table.item(row, col).setText("")
        self.points_table.blockSignals(False)

        self.point_pairs = [None, None, None, None]
        self.pair_deviations = [None, None, None, None]
        self.original_point_pairs = [None, None, None, None]  # Сбрасываем исходные пары
        self.delta_x = 0.0
        self.delta_y = 0.0
        self.avg_error = 0.0

        self.clear_all_graphics()

        self.dx_edit.clear()
        self.dy_edit.clear()
        self.error_edit.clear()

        if self.interzonal_mode:
            self.x_0_edit.setText("(рассчитается)")
            self.y_0_edit.setText("(рассчитается)")

        self.update_buttons_state()
        self.update_status_text()

        self.calculate_button.setEnabled(False)
        self.save_button.setEnabled(False)

    def on_calculate_clicked(self):
        """Расчет смещения / параметров проекции"""
        if not all(pair is not None for pair in self.point_pairs):
            total_pairs = len(self.point_pairs)
            self.iface.messageBar().pushMessage(
                "Ошибка",
                f"Необходимо заполнить все {total_pairs} пар точек",
                level=Qgis.Warning,
                duration=MESSAGE_SUCCESS_DURATION
            )
            return

        if self.interzonal_mode:
            self._calculate_interzonal()
        else:
            self._calculate_standard()

    def _calculate_standard(self):
        """Расчёт для обычного режима (только смещение x_0, y_0)

        НОВЫЙ WORKFLOW (2024-12):
        - "Неправильная" точка = координаты объекта в МСК слоя (wrong_msk)
        - "Правильная" точка = координаты WFS эталона в EPSG:3857 (correct_3857)

        Алгоритм:
        1. Трансформируем correct_3857 → МСК слоя объекта
        2. Смещение = correct_msk - wrong_msk (в одной CRS!)
        3. ΔX, ΔY прибавляются к x_0/y_0 проекции
        """
        log_info("Fsm_0_5: РАСЧЁТ СМЕЩЕНИЯ (обычный режим)")

        # Проверяем наличие CRS слоя объекта
        if not self.object_layer_crs or not self.object_layer_crs.isValid():
            self.iface.messageBar().pushMessage(
                "Ошибка",
                "Не выбран слой объекта (МСК)",
                level=Qgis.Warning,
                duration=MESSAGE_INFO_DURATION
            )
            return

        # CRS для трансформаций
        object_crs = self.object_layer_crs
        epsg_3857 = QgsCoordinateReferenceSystem("EPSG:3857")
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")

        log_info(f"Fsm_0_5: CRS слоя объекта: {object_crs.authid()} - {object_crs.description()}")
        log_info(f"Fsm_0_5: PROJ строка: {object_crs.toProj()}")

        # Трансформаторы
        transform_3857_to_msk = QgsCoordinateTransform(epsg_3857, object_crs, QgsProject.instance())
        transform_msk_to_wgs = QgsCoordinateTransform(object_crs, wgs84, QgsProject.instance())
        transform_3857_to_wgs = QgsCoordinateTransform(epsg_3857, wgs84, QgsProject.instance())

        # Вычисляем смещения для каждой пары
        deltas = []
        for i, pair in enumerate(self.point_pairs):
            if pair is None:
                continue

            wrong_msk, correct_3857 = pair

            # Трансформируем correct из 3857 в МСК слоя объекта
            correct_msk = transform_3857_to_msk.transform(correct_3857)

            # Смещение для x_0/y_0: wrong - correct (инвертированный знак!)
            #
            # Логика x_0 в TM проекции:
            #   E = x_0 + f(lon)  →  f(lon) = E - x_0
            #
            # Если объект левее чем нужно (wrong.x < correct.x):
            #   - Нужно сдвинуть объект ВПРАВО
            #   - Увеличение x_0 смещает интерпретацию ВЛЕВО (f уменьшается)
            #   - Значит нужно УМЕНЬШИТЬ x_0
            #   - delta_x = wrong - correct < 0 (отрицательное)
            dx = wrong_msk.x() - correct_msk.x()
            dy = wrong_msk.y() - correct_msk.y()
            deltas.append((dx, dy))

        # Компактный вывод смещений по парам
        log_info("Fsm_0_5: Смещения по парам (ΔX, ΔY, d):")
        for i, (dx, dy) in enumerate(deltas):
            d = math.sqrt(dx**2 + dy**2)
            log_info(f"  Пара {i+1}: ΔX={dx:+.2f} м, ΔY={dy:+.2f} м, d={d:.2f} м")

        # Среднее смещение (динамическое количество пар)
        num_pairs = len(deltas)
        self.delta_x = sum(dx for dx, dy in deltas) / num_pairs
        self.delta_y = sum(dy for dx, dy in deltas) / num_pairs

        # RMS (среднеквадратичная ошибка) - показывает разброс между парами
        errors = []
        self.pair_deviations = [None] * len(self.point_pairs)  # Сбрасываем отклонения
        for i, (dx, dy) in enumerate(deltas):
            error_x = dx - self.delta_x
            error_y = dy - self.delta_y
            error = math.sqrt(error_x**2 + error_y**2)
            errors.append(error)
            self.pair_deviations[i] = error  # Сохраняем отклонение

        self.avg_error = math.sqrt(sum(e**2 for e in errors) / num_pairs)

        # Компактный вывод результатов
        log_info(f"Fsm_0_5: Среднее: ΔX={self.delta_x:+.2f} м, ΔY={self.delta_y:+.2f} м | "
                 f"СКО={self.avg_error:.2f} м | Точек: {num_pairs}")

        if self.avg_error > 1.0:
            # Показываем топ-3 худших пары
            worst_pairs = sorted(enumerate(errors), key=lambda x: x[1], reverse=True)[:3]
            log_warning(f"Fsm_0_5: СКО > 1 м! Худшие пары: " +
                       ", ".join([f"#{i+1}({e:.2f}м)" for i, e in worst_pairs]))

        # Округляем результаты
        self.delta_x = round(self.delta_x, 4)
        self.delta_y = round(self.delta_y, 4)
        self.avg_error = round(self.avg_error, PRECISION_DECIMALS)

        # Предупреждение о подозрительно низком RMS при малом количестве точек
        rms_warning = ""
        if self.avg_error < RMS_ERROR_THRESHOLD and num_pairs <= 5:
            rms_warning = (
                f"\n\nВНИМАНИЕ: СКО < {RMS_ERROR_THRESHOLD} м при {num_pairs} парах точек.\n"
                "Возможные причины:\n"
                "- Все точки расположены слишком близко друг к другу\n"
                "- Точки выбраны на одном объекте (должны быть разнесены)\n"
                "- Недостаточно контрольных точек для надёжной оценки\n"
                "Рекомендуется добавить точки в разных частях объекта."
            )
            log_warning(f"Fsm_0_5: Подозрительно низкий RMS={self.avg_error:.6f} м при {num_pairs} парах")

        # Извлекаем текущие x_0, y_0 из CRS слоя объекта (не Project CRS!)
        proj_str = object_crs.toProj()
        x_0_match = re.search(r'\+x_0=([\d\.\-]+)', proj_str)
        y_0_match = re.search(r'\+y_0=([\d\.\-]+)', proj_str)
        current_x_0 = float(x_0_match.group(1)) if x_0_match else 0.0
        current_y_0 = float(y_0_match.group(1)) if y_0_match else 0.0

        new_x_0 = current_x_0 + self.delta_x
        new_y_0 = current_y_0 + self.delta_y

        log_info(f"Fsm_0_5: Новые параметры: x_0={new_x_0:.2f}, y_0={new_y_0:.2f}")

        # Отображаем результаты
        self.dx_edit.setText(f"{self.delta_x:.4f} м")
        self.dy_edit.setText(f"{self.delta_y:.4f} м")
        self.error_edit.setText(f"{self.avg_error:.2f} м")

        # Заполняем колонку отклонений в таблице
        self._update_deviation_column()

        self.status_text.setPlainText(
            f"Смещение рассчитано (обычный режим):\n"
            f"  ΔX = {self.delta_x:.4f} м\n"
            f"  ΔY = {self.delta_y:.4f} м\n"
            f"  СКО (RMS) = {self.avg_error:.2f} м"
            f"{rms_warning}"
        )

        self.save_button.setEnabled(True)

    def _update_deviation_column(self):
        """Обновление колонки отклонений в таблице с подсветкой проблемных пар"""
        self.points_table.blockSignals(True)

        for i, deviation in enumerate(self.pair_deviations):
            item = self.points_table.item(i, 5)
            if item is None:
                continue

            if deviation is not None:
                item.setText(f"{deviation:.2f} м")

                # Подсветка строк с большим отклонением
                if deviation > self.DEVIATION_WARNING_THRESHOLD:
                    # Красноватый фон для проблемных пар
                    item.setBackground(QColor(255, 200, 200))
                else:
                    # Зелёный фон для хороших пар
                    item.setBackground(QColor(200, 255, 200))
            else:
                item.setText("")
                item.setBackground(QColor(255, 255, 255))  # Белый фон

        self.points_table.blockSignals(False)

    def _calculate_interzonal(self):
        """Расчёт для межзонального режима (lon_0, k_0, x_0, y_0)

        Автоматический выбор режима:
        1. Если >= 2 пары точек - итеративный подбор lon_0 по контрольным точкам
        2. Если < 2 пар - расчёт по центру extent объекта
        """
        # Считаем заполненные пары
        filled_pairs = [pair for pair in self.point_pairs if pair is not None]

        # Итеративный подбор если >= 2 пары точек
        if len(filled_pairs) >= 2:
            self._calculate_interzonal_iterative()
            return

        log_info("Fsm_0_5: Мало точек для итеративного подбора, расчёт по extent")

        # Далее идёт обычный расчёт по extent
        if not self.object_bounds or not self.object_center:
            self.iface.messageBar().pushMessage(
                "Ошибка",
                "Не загружены границы объекта",
                level=Qgis.Critical,
                duration=MESSAGE_INFO_DURATION
            )
            return

        from .Fsm_0_5_3_projection_optimizer import ProjectionOptimizer

        optimizer = ProjectionOptimizer()

        min_lon, max_lon = self.object_bounds
        center_lon, center_lat = self.object_center

        # Центральный меридиан
        central_meridian = (min_lon + max_lon) / 2

        # Протяженность и масштабный коэффициент
        extent_km = (max_lon - min_lon) * 111.32 * math.cos(math.radians(center_lat))
        scale_factor = optimizer.calculate_optimal_scale_factor(extent_km / 2)

        # Искажение
        distortion_ppm = optimizer.estimate_distortion(
            central_meridian, scale_factor,
            (min_lon, max_lon), center_lat
        )

        # Извлекаем базовые параметры из текущей CRS
        project_crs = QgsProject.instance().crs()
        base_proj = project_crs.toProj()

        lat_0 = 0.0
        if "+lat_0=" in base_proj:
            match = re.search(r'\+lat_0=([\d\.\-]+)', base_proj)
            if match:
                lat_0 = float(match.group(1))

        # Извлекаем ellps и towgs84
        ellps_param = ""
        towgs84_param = ""
        if "+ellps=" in base_proj:
            match = re.search(r'\+ellps=(\S+)', base_proj)
            if match:
                ellps_param = f"+ellps={match.group(1)}"

        if "+towgs84=" in base_proj:
            match = re.search(r'\+towgs84=([\d\.,\-]+)', base_proj)
            if match:
                towgs84_param = f"+towgs84={match.group(1)}"

        # Расчёт x_0, y_0 по ЦЕНТРУ extent объекта
        # Это обеспечивает совпадение координат в центре объекта
        try:
            from pyproj import Transformer

            # Временная PROJ-строка без смещений
            temp_proj = (
                f"+proj=tmerc +lat_0={lat_0} +lon_0={central_meridian} +k_0={scale_factor} "
                f"+x_0=0 +y_0=0 "
            )
            if ellps_param:
                temp_proj += f"{ellps_param} "
            if towgs84_param:
                temp_proj += f"{towgs84_param} "
            temp_proj += "+units=m +no_defs"

            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            transform_to_wgs = QgsCoordinateTransform(project_crs, wgs84, QgsProject.instance())
            transformer_new = Transformer.from_crs("EPSG:4326", temp_proj, always_xy=True)

            # Получаем центр extent в исходной CRS
            # Для этого трансформируем центр из WGS84 в исходную CRS
            transform_from_wgs = QgsCoordinateTransform(wgs84, project_crs, QgsProject.instance())
            center_wgs = QgsPointXY(center_lon, center_lat)
            center_in_source_crs = transform_from_wgs.transform(center_wgs)
            
            log_info(f"Fsm_0_5: Центр extent в WGS84: {center_lon:.6f}, {center_lat:.6f}")
            log_info(f"Fsm_0_5: Центр extent в исходной CRS: {center_in_source_crs.x():.2f}, {center_in_source_crs.y():.2f}")

            # Трансформируем центр в новую CRS (x_0=0, y_0=0)
            x_center_new, y_center_new = transformer_new.transform(center_lon, center_lat)
            
            # x_0/y_0 = координаты в исходной CRS - координаты в новой CRS (без смещений)
            x_0 = center_in_source_crs.x() - x_center_new
            y_0 = center_in_source_crs.y() - y_center_new
            
            log_info(f"Fsm_0_5: Центр в новой CRS (без смещений): {x_center_new:.2f}, {y_center_new:.2f}")
            log_info(f"Fsm_0_5: Расчётные смещения: x_0={x_0:.2f}, y_0={y_0:.2f}")

            # Оценка качества по контрольным точкам (СКО)
            # Показывает, насколько хорошо новая проекция "подходит" для разных точек
            errors = []
            for i, pair in enumerate(self.point_pairs):
                if pair is None:
                    continue

                wrong_point, correct_point = pair

                # correct_point → WGS84 через ИСХОДНУЮ CRS
                correct_in_wgs = transform_to_wgs.transform(correct_point)

                # WGS84 → новая CRS (с рассчитанными x_0, y_0)
                x_new, y_new = transformer_new.transform(correct_in_wgs.x(), correct_in_wgs.y())
                x_final = x_new + x_0
                y_final = y_new + y_0

                # Ошибка = разница между эталоном и результатом
                error_x = correct_point.x() - x_final
                error_y = correct_point.y() - y_final
                error = math.sqrt(error_x**2 + error_y**2)
                errors.append(error)

                log_info(f"Fsm_0_5: Пара {i+1}: ошибка = {error:.2f} м (Δx={error_x:.2f}, Δy={error_y:.2f})")

            # СКО
            rms = math.sqrt(sum(e**2 for e in errors) / len(errors)) if errors else 0.0
            log_info(f"Fsm_0_5: СКО по контрольным точкам: {rms:.2f} м")

        except ImportError:
            self.iface.messageBar().pushMessage(
                "Ошибка",
                "Библиотека pyproj не установлена",
                level=Qgis.Critical,
                duration=MESSAGE_INFO_DURATION
            )
            log_error("Fsm_0_5: pyproj не установлен")
            return
        except Exception as e:
            self.iface.messageBar().pushMessage(
                "Ошибка",
                f"Ошибка расчёта: {str(e)}",
                level=Qgis.Critical,
                duration=MESSAGE_INFO_DURATION
            )
            log_error(f"Fsm_0_5: Ошибка расчёта межзональной проекции: {e}")
            return

        # Сохраняем параметры
        self.interzonal_params = {
            "lon_0": central_meridian,
            "lat_0": lat_0,
            "k_0": scale_factor,
            "x_0": x_0,
            "y_0": y_0,
            "ellps_param": ellps_param,
            "towgs84_param": towgs84_param
        }

        # Сохраняем RMS для отображения
        self.avg_error = round(rms, PRECISION_DECIMALS)

        # Отображаем результаты
        self.lon_0_edit.setText(f"{central_meridian:.6f}")
        self.k_0_edit.setText(f"{scale_factor:.8f}")
        self.distortion_edit.setText(f"{distortion_ppm:.2f}")
        self.x_0_edit.setText(f"{x_0:.2f}")
        self.y_0_edit.setText(f"{y_0:.2f}")

        self.dx_edit.setText("—")
        self.dy_edit.setText("—")
        self.error_edit.setText(f"{rms:.2f} м")

        # Предупреждение о большом СКО
        warning_text = ""
        if rms > 50:
            warning_text = f"\n\nВНИМАНИЕ: СКО = {rms:.2f} м слишком велико!\nЭто ожидаемо при большом изменении lon_0."

        self.status_text.setPlainText(
            f"Перерасчёт СК выполнен (по центру extent):\n"
            f"  lon_0 = {central_meridian:.6f}°\n"
            f"  k_0 = {scale_factor:.8f}\n"
            f"  x_0 = {x_0:.2f} м, y_0 = {y_0:.2f} м\n"
            f"  СКО по контр. точкам = {rms:.2f} м, Искажение = {distortion_ppm:.2f} ppm"
            f"{warning_text}"
        )

        self.save_button.setEnabled(True)

    def _calculate_interzonal_iterative(self):
        """Расчёт проекции напрямую из WGS84 координат.

        НОВЫЙ WORKFLOW (2024-12):
        1. Конвертируем все точки в WGS84
        2. Запускаем ВСЕ доступные методы расчёта через run_all_methods()
        3. Выбираем лучший результат по RMSE

        ВАЖНО (2024-12 v2): При "Перерасчёт СК" используем ИСХОДНЫЕ пары точек
        (original_point_pairs) с ИСХОДНОЙ CRS слоя (initial_object_layer_crs).
        Это избегает проблемы round-trip после предыдущих калибровок.

        Входные данные:
        - wrong точки в ИСХОДНОЙ CRS слоя объекта (МСК) → конвертируются в WGS84
        - correct точки в EPSG:3857 (WFS) → конвертируются в WGS84
        """
        # Для перерасчёта СК используем ИСХОДНУЮ CRS слоя
        source_crs = self.initial_object_layer_crs if self.initial_object_layer_crs else self.object_layer_crs

        # Проверяем наличие слоя объекта
        if not source_crs:
            self.iface.messageBar().pushMessage(
                "Ошибка",
                "Не выбран слой объекта (МСК)",
                level=Qgis.Warning,
                duration=MESSAGE_INFO_DURATION
            )
            return

        # Проверяем наличие ИСХОДНЫХ пар точек для перерасчёта СК
        original_pairs = [
            pair for pair in self.original_point_pairs
            if pair is not None and pair[0] is not None and pair[1] is not None
        ]

        # Fallback: если исходных пар нет, используем текущие
        use_original = len(original_pairs) > 0
        if use_original:
            log_info(f"Fsm_0_5: Используем ИСХОДНЫЕ пары точек ({len(original_pairs)}) для перерасчёта СК")
            log_info(f"Fsm_0_5: Исходная CRS: {source_crs.authid()}")
        else:
            # FALLBACK: исходные пары отсутствуют - используем текущие point_pairs
            # Это может произойти если:
            # 1. Диалог открыт повторно после предыдущей калибровки
            # 2. Точки введены вручную через таблицу (не через клик на карте)
            # 3. Баг - _save_original_point() не вызвался
            log_warning("Fsm_0_5: FALLBACK - исходные пары не найдены!")
            log_warning(f"Fsm_0_5: original_point_pairs = {self.original_point_pairs}")
            log_warning(f"Fsm_0_5: Используем текущие point_pairs с CRS: {source_crs.authid()}")

            # Fallback к текущим парам
            control_points = [
                pair for pair in self.point_pairs if pair is not None
            ]
            if len(control_points) < 1:
                self.iface.messageBar().pushMessage(
                    "Ошибка",
                    "Для расчёта нужна минимум 1 пара точек",
                    level=Qgis.Warning,
                    duration=MESSAGE_INFO_DURATION
                )
                return

        # Конвертируем точки в WGS84
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        epsg_3857 = QgsCoordinateReferenceSystem("EPSG:3857")

        # Трансформаторы (используем ИСХОДНУЮ CRS для wrong точек!)
        transform_obj_to_wgs = QgsCoordinateTransform(
            source_crs, wgs84, QgsProject.instance()
        )
        transform_ref_to_wgs = QgsCoordinateTransform(
            epsg_3857, wgs84, QgsProject.instance()
        )

        # Конвертируем все пары в WGS84
        control_points_wgs84 = []
        if use_original:
            # Используем исходные пары
            for wrong_msk_orig, correct_3857_orig, orig_crs_authid in original_pairs:
                # Проверка уже выполнена при фильтрации original_pairs (pair[0] is not None and pair[1] is not None)
                assert wrong_msk_orig is not None and correct_3857_orig is not None
                obj_wgs = transform_obj_to_wgs.transform(wrong_msk_orig)
                ref_wgs = transform_ref_to_wgs.transform(correct_3857_orig)
                control_points_wgs84.append((obj_wgs, ref_wgs))
                log_info(
                    f"Fsm_0_5: Исходная пара: wrong({wrong_msk_orig.x():.2f}, {wrong_msk_orig.y():.2f}) "
                    f"-> WGS84({obj_wgs.x():.6f}, {obj_wgs.y():.6f})"
                )
        else:
            # Fallback: используем текущие пары (с детальным логированием для отладки)
            log_warning(f"Fsm_0_5: FALLBACK - конвертируем {len(control_points)} текущих пар:")
            for i, (wrong_msk, correct_3857) in enumerate(control_points):
                obj_wgs = transform_obj_to_wgs.transform(wrong_msk)
                ref_wgs = transform_ref_to_wgs.transform(correct_3857)
                control_points_wgs84.append((obj_wgs, ref_wgs))
                log_warning(
                    f"Fsm_0_5: FALLBACK пара {i+1}: wrong({wrong_msk.x():.2f}, {wrong_msk.y():.2f}) "
                    f"-> WGS84({obj_wgs.x():.6f}, {obj_wgs.y():.6f})"
                )

        log_info(f"Fsm_0_5: Конвертировано {len(control_points_wgs84)} пар в WGS84")

        # Импортируем оптимизатор
        from .Fsm_0_5_3_projection_optimizer import ProjectionOptimizer

        optimizer = ProjectionOptimizer()

        # Извлекаем базовые параметры из ИСХОДНОЙ CRS СЛОЯ ОБЪЕКТА (для towgs84)
        base_proj = source_crs.toProj()
        log_info(f"Fsm_0_5: Базовая PROJ строка: {base_proj}")

        # Извлекаем параметры (фиксированные, кроме lon_0, x_0, y_0)
        lat_0 = 0.0
        k_0 = 1.0
        ellps_param = ELLPS_KRASS
        # ГОСТ 32453-2017: параметры преобразования СК-42 -> WGS-84
        towgs84_param = TOWGS84_SK42_PROJ

        if "+lat_0=" in base_proj:
            match = re.search(r'\+lat_0=([\d\.\-]+)', base_proj)
            if match:
                lat_0 = float(match.group(1))

        if "+k_0=" in base_proj or "+k=" in base_proj:
            match = re.search(r'\+k_?0?=([\d\.\-]+)', base_proj)
            if match:
                k_0 = float(match.group(1))

        if "+ellps=" in base_proj:
            match = re.search(r'\+ellps=(\S+)', base_proj)
            if match:
                ellps_param = f"+ellps={match.group(1)}"

        if "+towgs84=" in base_proj:
            match = re.search(r'\+towgs84=([\d\.,\-]+)', base_proj)
            if match:
                towgs84_param = f"+towgs84={match.group(1)}"

        base_params = {
            'lat_0': lat_0,
            'k_0': k_0,
            'ellps_param': ellps_param,
            'towgs84_param': towgs84_param
        }

        # Начальное приближение lon_0 из CRS слоя (или из базы МСК)
        initial_lon_0 = None  # Будет вычислен из центра эталонных точек
        if "+lon_0=" in base_proj:
            match = re.search(r'\+lon_0=([\d\.\-]+)', base_proj)
            if match:
                initial_lon_0 = float(match.group(1))

        # Если lon_0 не найден, вычисляем из центра эталонных точек
        if initial_lon_0 is None:
            ref_lons = [ref.x() for _, ref in control_points_wgs84]
            initial_lon_0 = sum(ref_lons) / len(ref_lons)

        # НОВОЕ: Запускаем ВСЕ методы через run_all_methods()
        all_results = optimizer.run_all_methods(
            control_points_wgs84=control_points_wgs84,
            base_params=base_params,
            initial_lon_0=initial_lon_0,
            include_optional=False  # Только базовые методы (1-4)
        )

        if not all_results:
            self.iface.messageBar().pushMessage(
                "Ошибка",
                "Не удалось выполнить ни один метод расчёта",
                level=Qgis.Critical,
                duration=MESSAGE_INFO_DURATION
            )
            return

        # Фильтруем результаты по допустимому искажению (max 50 ppm = 5 см/км)
        # Стандарт для высокоточных кадастровых работ (между LDP 20ppm и SPCS 100ppm)
        MAX_DISTORTION_PPM = 50.0

        if self.object_bounds:
            min_lon, max_lon = self.object_bounds
            center_lat = self.object_center[1] if self.object_center else lat_0

            # Оцениваем искажение для каждого результата и фильтруем
            filtered_results = []
            for r in all_results:
                distortion = optimizer.estimate_distortion(
                    r.lon_0, k_0, (min_lon, max_lon), center_lat
                )
                if distortion <= MAX_DISTORTION_PPM:
                    filtered_results.append((r, distortion))
                else:
                    log_warning(
                        f"Fsm_0_5: Метод {r.method_id} отклонён: искажение {distortion:.1f} ppm > {MAX_DISTORTION_PPM} ppm "
                        f"(lon_0={r.lon_0:.4f}° далеко от объекта {min_lon:.4f}°-{max_lon:.4f}°)"
                    )

            if filtered_results:
                # Выбираем лучший из отфильтрованных
                best_result, distortion_ppm = filtered_results[0]
                log_info(f"Fsm_0_5: После фильтрации по искажению осталось {len(filtered_results)} методов")
            else:
                # Все методы дают большое искажение - берём с минимальным искажением
                log_warning("Fsm_0_5: Все методы дают большое искажение - выбираем с минимальным")
                all_with_distortion = [
                    (r, optimizer.estimate_distortion(r.lon_0, k_0, (min_lon, max_lon), center_lat))
                    for r in all_results
                ]
                all_with_distortion.sort(key=lambda x: x[1])  # Сортируем по искажению
                best_result, distortion_ppm = all_with_distortion[0]
        else:
            best_result = all_results[0]
            distortion_ppm = 0.0

        # Формируем сводку по всем методам
        methods_summary = []
        for r in all_results:
            status = "OK" if r.success else "!"
            methods_summary.append(f"{r.method_name}: {r.rmse:.4f}м [{status}]")

        log_info(f"Fsm_0_5: Лучший метод: {best_result.method_name} (RMSE={best_result.rmse:.4f}м, искажение={distortion_ppm:.2f}ppm)")

        # Обновляем towgs84 если метод его изменил
        final_towgs84 = best_result.towgs84_param if best_result.towgs84_param else towgs84_param

        # Сохраняем параметры
        self.interzonal_params = {
            "lon_0": best_result.lon_0,
            "lat_0": lat_0,
            "k_0": k_0,
            "x_0": best_result.x_0,
            "y_0": best_result.y_0,
            "ellps_param": ellps_param,
            "towgs84_param": final_towgs84
        }

        self.avg_error = round(best_result.rmse, PRECISION_DECIMALS)

        # Предупреждение о подозрительно низком RMS при малом количестве точек
        num_points = len(control_points_wgs84)  # Используем общий список (независимо от источника)
        rms_warning = ""
        if self.avg_error < RMS_ERROR_THRESHOLD and num_points <= 5:
            rms_warning = (
                f"\n\nВНИМАНИЕ: RMSE < {RMS_ERROR_THRESHOLD} м при {num_points} парах точек.\n"
                "Рекомендуется добавить точки в разных частях объекта."
            )
            log_warning(f"Fsm_0_5: Подозрительно низкий RMSE={self.avg_error:.6f} м при {num_points} парах")

        # Сохраняем все результаты для возможного выбора пользователем
        self._all_calculation_results = all_results

        # Отображаем результаты
        self.lon_0_edit.setText(f"{best_result.lon_0:.6f}")
        self.k_0_edit.setText(f"{k_0:.8f}")
        self.distortion_edit.setText(f"{distortion_ppm:.2f}")
        self.x_0_edit.setText(f"{best_result.x_0:.2f}")
        self.y_0_edit.setText(f"{best_result.y_0:.2f}")

        self.dx_edit.setText("—")
        self.dy_edit.setText("—")
        self.error_edit.setText(f"{best_result.rmse:.4f} м")

        # Формируем статус с учётом порогов RMSE
        if best_result.rmse >= RMSE_THRESHOLD_WRONG_CRS:
            success_text = "ОШИБКА: Вероятно выбрана неправильная CRS/зона МСК"
            log_error(
                f"Fsm_0_5: RMSE={best_result.rmse:.1f}м > {RMSE_THRESHOLD_WRONG_CRS}м - "
                "вероятно неправильная исходная CRS"
            )
        elif best_result.rmse >= RMSE_THRESHOLD_WARNING:
            success_text = f"ВНИМАНИЕ: RMSE > {RMSE_THRESHOLD_WARNING:.0f} м - проверьте данные"
        elif best_result.rmse >= RMSE_THRESHOLD_OK:
            success_text = f"ВНИМАНИЕ: RMSE > {RMSE_THRESHOLD_OK:.0f} м"
        else:
            success_text = "УСПЕХ"

        # Формируем диагностический текст
        diagnostics = best_result.diagnostics
        errors = diagnostics.get('errors', [])
        if errors:
            min_err = min(errors)
            max_err = max(errors)
            diag_text = f"min={min_err:.3f}м, max={max_err:.3f}м"
        else:
            diag_text = "—"

        # Информация о методе
        method_info = f"Метод: {best_result.method_name} ({best_result.method_id})"

        # Информация об источнике точек
        source_info = ""
        if use_original:
            source_info = f"\n  Источник: ИСХОДНЫЕ пары ({num_points} шт.), CRS: {source_crs.authid()}"
        else:
            source_info = f"\n  Источник: текущие пары ({num_points} шт.)"

        # Сводка по всем методам
        all_methods_text = "\n".join([f"  {s}" for s in methods_summary])

        # Предупреждение о неправильной CRS
        crs_warning = ""
        if best_result.rmse >= RMSE_THRESHOLD_WRONG_CRS:
            crs_warning = (
                f"\n\nКРИТИЧЕСКАЯ ОШИБКА: RMSE = {best_result.rmse:.0f} м (> 1 км)!\n"
                "Вероятные причины:\n"
                "  - Выбрана неправильная зона МСК (проверьте lon_0)\n"
                "  - Выбрана не та система координат (СК-42 vs ГСК-2011)\n"
                "  - Координаты объекта и эталона в разных CRS\n"
                "Рекомендация: проверьте исходную CRS слоя объекта."
            )

        self.status_text.setPlainText(
            f"Расчёт завершён ({success_text}):\n"
            f"  {method_info}{source_info}\n"
            f"  lon_0 = {best_result.lon_0:.6f}°\n"
            f"  x_0 = {best_result.x_0:.2f}м, y_0 = {best_result.y_0:.2f}м\n"
            f"  RMSE = {best_result.rmse:.4f}м ({diag_text})\n"
            f"\nВсе методы:\n{all_methods_text}"
            f"{rms_warning}"
            f"{crs_warning}"
        )

        # Блокируем сохранение при критической ошибке CRS
        if best_result.rmse >= RMSE_THRESHOLD_WRONG_CRS:
            self.save_button.setEnabled(False)
        else:
            self.save_button.setEnabled(True)

    def on_save_clicked(self):
        """Сохранение новой проекции"""
        if self.interzonal_mode:
            self._save_interzonal()
        else:
            self._save_standard()

    def _save_standard(self):
        """Сохранение для обычного режима"""
        if self.delta_x == 0.0 and self.delta_y == 0.0:
            self.iface.messageBar().pushMessage(
                "Предупреждение",
                "Смещение равно нулю. Нечего сохранять.",
                level=Qgis.Warning,
                duration=MESSAGE_SUCCESS_DURATION
            )
            return

        self.status_text.setPlainText("Создаю новую проекцию и применяю к проекту...")

        # НОВЫЙ WORKFLOW: передаём CRS слоя объекта и сам слой
        success = self.parent_tool.apply_projection_offset(
            self.delta_x,
            self.delta_y,
            object_layer_crs=self.object_layer_crs,
            object_layer=self.object_layer
        )

        if success:
            # НЕ восстанавливаем старую CRS - новая уточнённая уже установлена
            self.original_project_crs = None

            # ВАЖНО: Обновляем object_layer_crs на новую CRS проекта
            # Это нужно если пользователь захочет сделать ещё одну калибровку
            new_project_crs = QgsProject.instance().crs()
            self.object_layer_crs = new_project_crs
            log_info(f"Fsm_0_5: object_layer_crs обновлена на {new_project_crs.authid()}")

            # Очищаем точки - они в старой CRS, повторное использование приведёт к ошибкам
            self.on_clear_all_clicked()

            self.status_text.setPlainText(
                "Новая проекция успешно создана и применена.\n"
                f"Project CRS = уточнённая МСК\n"
                "Окно можно закрыть."
            )
            self.clear_all_graphics()
            self.parent_tool.deactivate_map_tool()
            self.accept()
        else:
            self.status_text.setPlainText(
                "Ошибка при создании новой проекции.\n"
                "Проверьте логи для деталей."
            )

    def _save_interzonal(self):
        """Сохранение для межзонального режима.

        НОВЫЙ WORKFLOW:
        1. Создаём уточнённую CRS
        2. Применяем к слою объекта
        3. Устанавливаем как Project CRS (НЕ восстанавливаем старую!)
        """
        if not self.interzonal_params:
            self.iface.messageBar().pushMessage(
                "Ошибка",
                "Параметры проекции не рассчитаны",
                level=Qgis.Critical,
                duration=MESSAGE_INFO_DURATION
            )
            return

        self.status_text.setPlainText("Создаю кастомную проекцию и применяю к проекту...")

        # Передаём слой объекта и его CRS для переопределения
        success = self.parent_tool.apply_custom_projection(
            self.interzonal_params,
            object_layer=self.object_layer,
            object_layer_crs=self.object_layer_crs  # Для переопределения CRS слоёв
        )

        if success:
            # НЕ восстанавливаем старую CRS - новая уточнённая уже установлена
            self.original_project_crs = None

            # ВАЖНО: Обновляем object_layer_crs на новую CRS проекта
            new_project_crs = QgsProject.instance().crs()
            self.object_layer_crs = new_project_crs
            log_info(f"Fsm_0_5: object_layer_crs обновлена на {new_project_crs.authid()}")

            # Очищаем точки - они в старой CRS
            self.on_clear_all_clicked()

            self.status_text.setPlainText(
                "Кастомная проекция успешно создана и применена.\n"
                f"Project CRS = уточнённая МСК\n"
                "Окно можно закрыть."
            )
            self.clear_all_graphics()
            self.parent_tool.deactivate_map_tool()
            self.accept()
        else:
            self.status_text.setPlainText(
                "Ошибка при создании кастомной проекции.\n"
                "Проверьте логи для деталей."
            )

    def on_cancel_clicked(self):
        """Отмена - восстанавливаем исходную CRS"""
        self.clear_all_graphics()
        self.parent_tool.deactivate_map_tool()
        self._restore_original_crs()  # Восстановить CRS при отмене
        self.reject()

    def closeEvent(self, event):
        """Обработка закрытия окна - восстанавливаем исходную CRS"""
        self._disconnect_extent_changed()  # Отключаем обработчик extent
        self.clear_all_graphics()
        self.parent_tool.deactivate_map_tool()
        self._restore_original_crs()  # Восстановить CRS при закрытии
        event.accept()
