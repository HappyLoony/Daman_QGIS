# -*- coding: utf-8 -*-
"""
Диалог для инструмента уточнения проекции
Версия 3.0: Объединённый GUI с checkbox для межзональной проекции
"""

from typing import Optional, Tuple, List, Callable
import math
import re

from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QLineEdit, QTableWidget,
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
from Daman_QGIS.utils import log_info, log_warning, log_error, log_success
from Daman_QGIS.core.base_responsive_dialog import BaseResponsiveDialog


class RefineProjectionDialog(BaseResponsiveDialog):
    """Диалог уточнения проекции через контрольные точки (минимум 4 пары)"""

    WIDTH_RATIO = 0.55
    HEIGHT_RATIO = 0.80
    MIN_WIDTH = 750
    MAX_WIDTH = 1100
    MIN_HEIGHT = 550
    MAX_HEIGHT = 950

    # Порог отклонения для подсветки проблемных пар (в метрах)
    DEVIATION_WARNING_THRESHOLD = 1.0

    # Параметры итеративного уточнения (Post-Calculation Refinement)
    MAX_REFINEMENT_ITERATIONS = 3
    REFINEMENT_CONVERGENCE_THRESHOLD = 0.001  # 1 мм - порог сходимости

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
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)

        layout = QVBoxLayout()

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
        self.points_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.points_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.points_table.verticalHeader().setVisible(False)

        # Настройка ширины колонок
        header = self.points_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.points_table.setColumnWidth(0, 40)
        for i in range(1, 5):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        # Колонка "Отклонение" - фиксированная ширина
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.points_table.setColumnWidth(5, 90)

        # Заполняем номера пар
        for i in range(4):
            item = QTableWidgetItem(str(i + 1))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # Только чтение
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.points_table.setItem(i, 0, item)

            # Создаем ячейки для координат
            for col in range(1, 5):
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.points_table.setItem(i, col, item)

            # Ячейка для отклонения (только чтение)
            deviation_item = QTableWidgetItem("")
            deviation_item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # Только чтение
            deviation_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
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

        # Группа результатов (упрощённая)
        results_group = QGroupBox("Результат расчёта")
        results_layout = QVBoxLayout()

        # СКО (RMS)
        error_layout = QHBoxLayout()
        error_layout.addWidget(QLabel("СКО (RMS):"))
        self.error_edit = QLineEdit()
        self.error_edit.setReadOnly(True)
        self.error_edit.setPlaceholderText("0.00 м")
        self.error_edit.setMinimumWidth(150)
        error_layout.addWidget(self.error_edit)
        error_layout.addStretch()
        results_layout.addLayout(error_layout)

        # Коррекция (среднее смещение)
        shift_layout = QHBoxLayout()
        shift_layout.addWidget(QLabel("Коррекция:"))
        self.shift_edit = QLineEdit()
        self.shift_edit.setReadOnly(True)
        self.shift_edit.setPlaceholderText("—")
        shift_layout.addWidget(self.shift_edit)
        results_layout.addLayout(shift_layout)

        # Применённый метод
        method_layout = QHBoxLayout()
        method_layout.addWidget(QLabel("Метод:"))
        self.method_edit = QLineEdit()
        self.method_edit.setReadOnly(True)
        self.method_edit.setPlaceholderText("—")
        method_layout.addWidget(self.method_edit)
        results_layout.addLayout(method_layout)

        results_group.setLayout(results_layout)
        layout.addWidget(results_group)

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

    def _auto_detect_object_crs(self):
        """Автоматическое определение CRS объекта из Project CRS.

        Вызывается при инициализации диалога ДО переключения на EPSG:3857.
        Сохраняет исходную CRS проекта как CRS объекта.

        ВАЖНО: initial_object_layer_crs сохраняется как ИСХОДНАЯ CRS и НЕ меняется
        при последующих калибровках. Используется для "Перерасчёт СК".

        При повторной калибровке (когда Project CRS = USER:XXXXX от прошлой калибровки)
        загружаем исходную CRS из метаданных проекта.
        """
        project = QgsProject.instance()
        current_crs = project.crs()

        # Проверяем есть ли сохранённая исходная CRS в метаданных проекта
        # (для случая повторной калибровки после применения USER CRS)
        saved_initial_crs_wkt = project.readEntry("Daman_QGIS", "initial_object_crs_wkt", "")[0]
        if saved_initial_crs_wkt:
            saved_crs = QgsCoordinateReferenceSystem.fromWkt(saved_initial_crs_wkt)
            if saved_crs.isValid():
                self.initial_object_layer_crs = saved_crs
                log_info(
                    f"Fsm_0_5: Загружена исходная CRS из метаданных проекта: "
                    f"{saved_crs.authid()} ({saved_crs.description()})"
                )

        # Сохраняем текущую CRS проекта как CRS объекта (если это не 3857)
        if current_crs.isValid() and current_crs.authid() != "EPSG:3857":
            self.object_layer_crs = current_crs
            self.original_project_crs = current_crs

            # ИСХОДНАЯ CRS для перерасчёта СК:
            # - Если уже загружена из метаданных - используем её
            # - Иначе используем текущую CRS (даже если USER)
            # Система работает автоматически с ЛЮБОЙ CRS благодаря методу full_crs
            if self.initial_object_layer_crs is None:
                self.initial_object_layer_crs = current_crs
                if not current_crs.authid().startswith("USER:"):
                    # Первая калибровка - сохраняем исходную CRS в метаданные
                    project.writeEntry("Daman_QGIS", "initial_object_crs_wkt", current_crs.toWkt())
                    log_info(f"Fsm_0_5: Исходная CRS сохранена в метаданные проекта: {current_crs.authid()}")
                else:
                    # USER CRS - система найдёт оптимальную CRS автоматически
                    log_info(
                        f"Fsm_0_5: Обнаружена USER CRS ({current_crs.authid()}). "
                        "Система найдёт оптимальную CRS автоматически."
                    )

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
                            if not crs.authid().startswith("USER:"):
                                project.writeEntry("Daman_QGIS", "initial_object_crs_wkt", crs.toWkt())
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
        3. Обновляет canvas для корректного OTF reprojection

        Returns:
            bool: True если успешно, False при ошибке
        """
        project = QgsProject.instance()

        # Сохраняем исходную CRS (только если ещё не сохранена)
        if self.original_project_crs is None:
            self.original_project_crs = project.crs()
            log_info(f"Fsm_0_5: Сохранена исходная CRS проекта: {self.original_project_crs.authid()}")

        # Проверяем возможность трансформации из object_layer_crs в EPSG:3857
        web_mercator = QgsCoordinateReferenceSystem("EPSG:3857")

        if self.object_layer_crs and self.object_layer_crs.isValid():
            try:
                # Тестовая трансформация для проверки возможности OTF reprojection
                test_transform = QgsCoordinateTransform(
                    self.object_layer_crs, web_mercator, project
                )
                if not test_transform.isValid():
                    log_warning(
                        f"Fsm_0_5: Трансформация {self.object_layer_crs.authid()} -> EPSG:3857 "
                        f"может быть неточной"
                    )
            except QgsCsException as e:
                log_warning(f"Fsm_0_5: Проблема с трансформацией CRS: {e}")

        # Переключаем на EPSG:3857 с защитой от исключений
        crs_switched = False
        try:
            project.setCrs(web_mercator)
            crs_switched = True

            log_info(f"Fsm_0_5: Project CRS переключена на EPSG:3857 для калибровки")

            # ВАЖНО: Обновляем canvas для корректного OTF reprojection слоёв с USER CRS
            self.iface.mapCanvas().refresh()

            # Zoom to extent объекта чтобы слой стал видимым после репроекции
            if self.object_layer and self.object_layer.isValid():
                # Extent слоя в его native CRS, трансформируем в Project CRS (3857)
                layer_extent = self.object_layer.extent()
                layer_crs = self.object_layer.crs()

                if layer_crs != web_mercator:
                    try:
                        extent_transform = QgsCoordinateTransform(
                            layer_crs, web_mercator, project
                        )
                        layer_extent = extent_transform.transformBoundingBox(layer_extent)
                    except QgsCsException as e:
                        log_warning(f"Fsm_0_5: Не удалось трансформировать extent: {e}")

                self.iface.mapCanvas().setExtent(layer_extent)
                self.iface.mapCanvas().refresh()
                log_info(f"Fsm_0_5: Canvas обновлён, zoom на слой {self.object_layer.name()}")

            return True

        except Exception as e:
            log_error(f"Fsm_0_5: Ошибка в _switch_to_calibration_mode: {e}")
            # Rollback CRS если успели переключить
            if crs_switched:
                self._restore_original_crs()
            raise

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

        log_info(f"Fsm_0_5: Перерасчёт СК - extent загружен, протяженность: {extent_km:.1f} км")

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

    def set_point_from_map(
        self,
        point,
        native_coords: Optional[QgsPointXY] = None,
        native_layer_crs: Optional[QgsCoordinateReferenceSystem] = None
    ):
        """Установка точки из карты в текущую выбранную ячейку.

        WORKFLOW (Project CRS = EPSG:3857):
        - point приходит в CRS проекта (3857)
        - Wrong (объект в МСК): используем native_coords если доступны (избегаем круговой трансформации)
        - Correct (WFS): оставляем в 3857

        КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (2025-01):
        Для wrong точек используем NATIVE координаты вершины из геометрии слоя.
        Это избегает "круговой ошибки": если CRS слоя неправильная, OTF репроекция
        даёт смещённое визуальное положение, и обратная трансформация даёт
        неточные координаты.

        Args:
            point: Координаты в Project CRS (3857)
            native_coords: Нативные координаты вершины из геометрии слоя (опционально)
            native_layer_crs: CRS слоя из которого получены native_coords (опционально)
        """
        if self.current_selection_pair is None or self.current_selection_point is None:
            return

        row = self.current_selection_pair

        # Блокируем сигналы чтобы не вызывать on_table_cell_changed
        self.points_table.blockSignals(True)

        # Записываем координаты в таблицу
        if self.current_selection_point == 'wrong':
            # Wrong = координаты объекта в его native CRS (МСК)
            # ПРИОРИТЕТ: native_coords из геометрии слоя (без круговой трансформации)

            if native_coords is not None and native_layer_crs is not None:
                # НОВЫЙ МЕТОД: Используем координаты напрямую из геометрии слоя
                # Это избегает круговой ошибки при неправильной CRS
                point_in_msk = native_coords

                # Если native_layer_crs отличается от object_layer_crs, трансформируем
                if self.object_layer_crs and native_layer_crs != self.object_layer_crs:
                    try:
                        transform = QgsCoordinateTransform(
                            native_layer_crs,
                            self.object_layer_crs,
                            QgsProject.instance()
                        )
                        point_in_msk = transform.transform(native_coords)
                        log_info(
                            f"Fsm_0_5: Wrong точка (native): {native_layer_crs.authid()}"
                            f"({native_coords.x():.4f}, {native_coords.y():.4f}) -> "
                            f"{self.object_layer_crs.authid()}({point_in_msk.x():.4f}, {point_in_msk.y():.4f})"
                        )
                    except QgsCsException as e:
                        log_warning(f"Fsm_0_5: Ошибка трансформации native -> object_layer: {e}")
                        # Используем native_coords как есть
                        point_in_msk = native_coords
                else:
                    log_info(
                        f"Fsm_0_5: Wrong точка (native, без круговой трансформации): "
                        f"({point_in_msk.x():.4f}, {point_in_msk.y():.4f})"
                    )

                self.points_table.item(row, 1).setText(f"{point_in_msk.x():.4f}")
                self.points_table.item(row, 2).setText(f"{point_in_msk.y():.4f}")

                # Сохраняем ИСХОДНЫЕ координаты для перерасчёта СК
                self._save_original_point(row, 'wrong', point_in_msk)

            elif self.object_layer_crs and self.object_layer_crs.isValid():
                # СТАРЫЙ МЕТОД (fallback): Трансформация 3857 → МСК
                # Используется если snap не сработал
                try:
                    transform = QgsCoordinateTransform(
                        QgsProject.instance().crs(),  # 3857
                        self.object_layer_crs,         # МСК слоя объекта (текущая)
                        QgsProject.instance()
                    )
                    point_in_msk = transform.transform(point)
                    self.points_table.item(row, 1).setText(f"{point_in_msk.x():.4f}")
                    self.points_table.item(row, 2).setText(f"{point_in_msk.y():.4f}")
                    log_warning(
                        f"Fsm_0_5: Wrong точка (fallback, круговая трансформация!): "
                        f"3857({point.x():.2f}, {point.y():.2f}) -> "
                        f"МСК({point_in_msk.x():.4f}, {point_in_msk.y():.4f})"
                    )

                    # Сохраняем ИСХОДНЫЕ координаты для перерасчёта СК
                    # ВАЖНО: Для перерасчёта СК нужны координаты в ИСХОДНОЙ CRS
                    # (до калибровки), а не в текущей USER CRS
                    if self.initial_object_layer_crs and self.initial_object_layer_crs != self.object_layer_crs:
                        # Трансформируем в исходную CRS для перерасчёта
                        transform_to_initial = QgsCoordinateTransform(
                            QgsProject.instance().crs(),  # 3857
                            self.initial_object_layer_crs,  # Исходная МСК
                            QgsProject.instance()
                        )
                        point_in_initial_crs = transform_to_initial.transform(point)
                        self._save_original_point(row, 'wrong', point_in_initial_crs)
                        log_info(
                            f"Fsm_0_5: Для перерасчёта СК: 3857 -> исходная CRS "
                            f"({self.initial_object_layer_crs.authid()}): "
                            f"({point_in_initial_crs.x():.4f}, {point_in_initial_crs.y():.4f})"
                        )
                    else:
                        # Первая калибровка - исходная CRS = текущая
                        self._save_original_point(row, 'wrong', point_in_msk)

                except QgsCsException as e:
                    log_error(f"Fsm_0_5: Ошибка трансформации координат: {e}")
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
        arrow_band = QgsRubberBand(self.iface.mapCanvas(), Qgis.GeometryType.Line)
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
                arrow_part = QgsRubberBand(self.iface.mapCanvas(), Qgis.GeometryType.Line)
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

        # --- Текстовая подпись с номером пары на середине отрезка ---
        self._create_label(wrong_canvas, correct_canvas, str(pair_number), row)

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

            # Рисуем подпись на середине отрезка
            pair_number = row + 1
            self._create_label(wrong_canvas, correct_canvas, str(pair_number), row)

    def _create_label(self, point1: QgsPointXY, point2: QgsPointXY, text: str, row: int):
        """Создаёт текстовую подпись на середине отрезка между двумя точками.

        Использует QGraphicsSimpleTextItem для отображения текста.
        Подписи обновляются при изменении extent через _on_extent_changed.
        """
        canvas = self.iface.mapCanvas()

        # Вычисляем середину отрезка в map координатах
        mid_x = (point1.x() + point2.x()) / 2
        mid_y = (point1.y() + point2.y()) / 2
        mid_point = QgsPointXY(mid_x, mid_y)

        # Конвертируем map координаты в пиксели
        map_to_pixel = canvas.getCoordinateTransform()
        pixel_point = map_to_pixel.transform(mid_point)

        # Создаём текстовый элемент
        text_item = QGraphicsSimpleTextItem(text)

        # Настраиваем шрифт
        font = QFont("Arial", 12, QFont.Weight.Bold)
        text_item.setFont(font)

        # Настраиваем цвет текста - чёрный с тонкой белой обводкой для контраста
        text_item.setBrush(QBrush(QColor(0, 0, 0)))  # Чёрный текст
        text_item.setPen(QPen(QColor(255, 255, 255), 0.5))  # Тонкая белая обводка

        # Позиционируем текст по центру (смещение для центрирования)
        text_item.setPos(pixel_point.x() - 6, pixel_point.y() - 10)

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
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.points_table.setItem(new_row, 0, item)

        # Ячейки для координат
        for col in range(1, 5):
            item = QTableWidgetItem("")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.points_table.setItem(new_row, col, item)

        # Ячейка для отклонения
        deviation_item = QTableWidgetItem("")
        deviation_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        deviation_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.points_table.setItem(new_row, 5, deviation_item)

        self.points_table.blockSignals(False)

        # Добавляем элемент в списки данных
        self.point_pairs.append(None)
        self.pair_deviations.append(None)
        self.original_point_pairs.append(None)  # Исходные пары для перерасчёта СК

        log_info(f"Fsm_0_5: Добавлена пара {new_row + 1}. Всего пар: {len(self.point_pairs)}")

        self.update_buttons_state()

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

        self.error_edit.clear()
        self.shift_edit.clear()
        self.method_edit.clear()

        self.update_buttons_state()

        self.calculate_button.setEnabled(False)
        self.save_button.setEnabled(False)

    def on_calculate_clicked(self):
        """Расчет смещения / параметров проекции.

        UNIFIED WORKFLOW (2025-01):
        Всегда запускаются ОБА режима:
        1. Стандартный (простое смещение x_0/y_0)
        2. Перерасчёт СК (множество методов)

        Выбирается лучший по RMSE, результаты сравниваются.
        """
        if not all(pair is not None for pair in self.point_pairs):
            total_pairs = len(self.point_pairs)
            self.iface.messageBar().pushMessage(
                "Ошибка",
                f"Необходимо заполнить все {total_pairs} пар точек",
                level=Qgis.Warning,
                duration=MESSAGE_SUCCESS_DURATION
            )
            return

        self._calculate_unified()

    def _calculate_unified(self):
        """Единый расчёт: запуск ОБОИХ режимов и выбор лучшего.

        UNIFIED WORKFLOW (2025-01):
        1. Запускаем стандартный расчёт (простое смещение)
        2. Загружаем extent для перерасчёта СК (если нужно)
        3. Запускаем перерасчёт СК (множество методов)
        4. Сравниваем результаты по RMSE
        5. Выбираем лучший и показываем сравнение
        """
        log_info("Fsm_0_5: UNIFIED CALCULATION - запуск обоих режимов")

        # Проверяем наличие CRS слоя объекта
        if not self.object_layer_crs or not self.object_layer_crs.isValid():
            self.iface.messageBar().pushMessage(
                "Ошибка",
                "Не выбран слой объекта (МСК)",
                level=Qgis.Warning,
                duration=MESSAGE_INFO_DURATION
            )
            return

        # === ЭТАП 1: Стандартный расчёт ===
        standard_result = self._run_standard_calculation()

        # === ЭТАП 2: Перерасчёт СК ===
        # Загружаем extent если ещё не загружен
        if not self.object_bounds or not self.object_center:
            if not self.load_extent_from_boundaries():
                log_warning("Fsm_0_5: Не удалось загрузить extent - перерасчёт СК недоступен")
                # Используем только стандартный результат
                if standard_result:
                    standard_result = self._refine_standard_result(standard_result)
                    self._display_result(standard_result, None)
                    return
                else:
                    self.iface.messageBar().pushMessage(
                        "Ошибка",
                        "Не удалось выполнить расчёт",
                        level=Qgis.Critical,
                        duration=MESSAGE_INFO_DURATION
                    )
                    return

        interzonal_result = self._run_interzonal_calculation()

        # === ЭТАП 2.5: Итеративное уточнение (Post-Calculation Refinement) ===
        if standard_result:
            standard_result = self._refine_standard_result(standard_result)
        if interzonal_result:
            interzonal_result = self._refine_interzonal_result(interzonal_result)

        # === ЭТАП 3: Сравнение и выбор ===
        self._display_result(standard_result, interzonal_result)

    def _run_standard_calculation(self):
        """Запуск стандартного расчёта (простое смещение).

        Returns:
            dict или None: {'rmse': float, 'delta_x': float, 'delta_y': float,
                           'new_x_0': float, 'new_y_0': float, 'deviations': list}
        """
        log_info("Fsm_0_5: --- Стандартный расчёт ---")

        object_crs = self.object_layer_crs
        epsg_3857 = QgsCoordinateReferenceSystem("EPSG:3857")

        transform_3857_to_msk = QgsCoordinateTransform(epsg_3857, object_crs, QgsProject.instance())

        # Вычисляем смещения для каждой пары
        deltas = []
        for i, pair in enumerate(self.point_pairs):
            if pair is None:
                continue
            wrong_msk, correct_3857 = pair
            correct_msk = transform_3857_to_msk.transform(correct_3857)
            dx = wrong_msk.x() - correct_msk.x()
            dy = wrong_msk.y() - correct_msk.y()
            deltas.append((dx, dy))

        if not deltas:
            log_error("Fsm_0_5: Нет данных для стандартного расчёта")
            return None

        # Среднее смещение
        num_pairs = len(deltas)
        delta_x = sum(dx for dx, dy in deltas) / num_pairs
        delta_y = sum(dy for dx, dy in deltas) / num_pairs

        # Вычисляем отклонения и RMS
        squared_errors = []
        deviations = []
        for dx, dy in deltas:
            error_x = dx - delta_x
            error_y = dy - delta_y
            squared_error = error_x**2 + error_y**2
            squared_errors.append(squared_error)
            deviations.append(math.sqrt(squared_error))

        rmse = math.sqrt(sum(squared_errors) / len(squared_errors))

        # Извлекаем текущие x_0, y_0
        import re
        proj_str = object_crs.toProj()
        x_0_match = re.search(r'\+x_0=([\d\.\-]+)', proj_str)
        y_0_match = re.search(r'\+y_0=([\d\.\-]+)', proj_str)
        current_x_0 = float(x_0_match.group(1)) if x_0_match else 0.0
        current_y_0 = float(y_0_match.group(1)) if y_0_match else 0.0

        new_x_0 = current_x_0 + delta_x
        new_y_0 = current_y_0 + delta_y

        log_info(f"Fsm_0_5: Стандартный: RMSE={rmse:.4f}м, x_0={new_x_0:.2f}, y_0={new_y_0:.2f}")

        return {
            'rmse': rmse,
            'delta_x': delta_x,
            'delta_y': delta_y,
            'new_x_0': new_x_0,
            'new_y_0': new_y_0,
            'deviations': deviations,
            'method_name': 'Стандартный',
            'method_id': 'standard'
        }

    def _run_interzonal_calculation(self):
        """Запуск перерасчёта СК (множество методов).

        Returns:
            dict или None: {'rmse': float, 'method_name': str, 'method_id': str,
                           'lon_0': float, 'x_0': float, 'y_0': float, 'params': dict}
        """
        log_info("Fsm_0_5: --- Перерасчёт СК ---")

        # Проверяем минимум пар
        filled_pairs = [pair for pair in self.point_pairs if pair is not None]
        if len(filled_pairs) < 2:
            log_warning("Fsm_0_5: Мало точек для перерасчёта СК (нужно >= 2)")
            return None

        from .Fsm_0_5_3_projection_optimizer import ProjectionOptimizer

        # Подготовка данных
        source_crs = self.initial_object_layer_crs or self.object_layer_crs
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        epsg_3857 = QgsCoordinateReferenceSystem("EPSG:3857")

        transform_msk_to_wgs = QgsCoordinateTransform(source_crs, wgs84, QgsProject.instance())
        transform_3857_to_wgs = QgsCoordinateTransform(epsg_3857, wgs84, QgsProject.instance())

        # Используем original_point_pairs если доступны
        use_original = any(p is not None for p in self.original_point_pairs)

        control_points_wgs84 = []
        raw_wrong_coords = []
        reference_3857_list = []  # Для прямой трансформации 3857->proj

        pairs_source = self.original_point_pairs if use_original else self.point_pairs

        for i, pair_data in enumerate(pairs_source):
            if pair_data is None:
                continue

            if use_original:
                wrong_msk_orig, correct_3857_orig, orig_crs_authid = pair_data
                if wrong_msk_orig is None or correct_3857_orig is None:
                    continue
                raw_wrong_coords.append((wrong_msk_orig.x(), wrong_msk_orig.y()))
                reference_3857_list.append(correct_3857_orig)  # Сохраняем 3857 координаты
                object_wgs84 = transform_msk_to_wgs.transform(wrong_msk_orig)
                reference_wgs84 = transform_3857_to_wgs.transform(correct_3857_orig)
            else:
                wrong_msk, correct_3857 = pair_data
                raw_wrong_coords.append((wrong_msk.x(), wrong_msk.y()))
                reference_3857_list.append(correct_3857)  # Сохраняем 3857 координаты
                object_wgs84 = transform_msk_to_wgs.transform(wrong_msk)
                reference_wgs84 = transform_3857_to_wgs.transform(correct_3857)

            control_points_wgs84.append((object_wgs84, reference_wgs84))

        if len(control_points_wgs84) < 2:
            log_warning("Fsm_0_5: Недостаточно точек для перерасчёта СК")
            return None

        # Извлекаем параметры из исходной CRS
        import re
        proj_str = source_crs.toProj()
        lon_0_match = re.search(r'\+lon_0=([\d\.\-]+)', proj_str)
        initial_lon_0 = float(lon_0_match.group(1)) if lon_0_match else 45.0

        # Параметры для оптимизатора
        from Daman_QGIS.constants import ELLPS_KRASS, TOWGS84_SK42_PROJ
        center_lon, center_lat = self.object_center
        optimizer = ProjectionOptimizer()
        min_lon, max_lon = self.object_bounds
        extent_km = (max_lon - min_lon) * 111.32 * math.cos(math.radians(center_lat))
        k_0 = optimizer.calculate_optimal_scale_factor(extent_km / 2)

        base_params = {
            'lat_0': 0.0,
            'k_0': k_0,
            'ellps_param': ELLPS_KRASS,
            'towgs84_param': TOWGS84_SK42_PROJ,
            'raw_wrong_coords': raw_wrong_coords,
            'object_center_lon': center_lon,
            'reference_3857': reference_3857_list  # Для прямой трансформации 3857->proj
        }

        # Запускаем все методы
        try:
            all_results = optimizer.run_all_methods(
                control_points_wgs84,
                base_params,
                initial_lon_0,
                include_optional=False
            )
        except Exception as e:
            log_error(f"Fsm_0_5: Ошибка перерасчёта СК: {e}")
            return None

        if not all_results:
            log_warning("Fsm_0_5: Перерасчёт СК не дал результатов")
            return None

        # Выбираем лучший результат
        best_result = all_results[0]  # Уже отсортированы по RMSE

        # Вычисляем искажение
        distortion_ppm = optimizer.estimate_distortion(
            best_result.lon_0, k_0,
            self.object_bounds, center_lat
        )

        approach_type = getattr(best_result, 'approach_type', 'calibration')
        log_info(
            f"Fsm_0_5: Перерасчёт СК: {best_result.method_name} ({approach_type}) "
            f"RMSE={best_result.rmse:.4f}м, lon_0={best_result.lon_0:.4f}"
        )

        return {
            'rmse': best_result.rmse,
            'method_name': best_result.method_name,
            'method_id': best_result.method_id,
            'approach_type': approach_type,
            'lon_0': best_result.lon_0,
            'k_0': k_0,
            'x_0': best_result.x_0,
            'y_0': best_result.y_0,
            'ellps_param': ELLPS_KRASS,
            'towgs84_param': TOWGS84_SK42_PROJ,
            'distortion_ppm': distortion_ppm,
            'all_results': all_results
        }

    # =====================================================================
    # Post-Calculation Refinement (Iterative x_0/y_0 correction)
    #
    # Fixes systematic ~1.8cm error caused by pipeline difference between
    # EPSG CRS (specific pipeline) and USER CRS (generic towgs84 pipeline).
    # Creates virtual CRS using the SAME path as the actual apply methods,
    # so residuals capture the real error that would remain after applying.
    # =====================================================================

    def _set_wkt2_offsets(
        self, wkt2_string: str, easting: float, northing: float
    ) -> Tuple[str, bool]:
        """Set absolute False Easting/Northing values in WKT2 string.

        Unlike update_wkt2_params (which adds delta), this sets absolute values.
        Supports TM, Lambert, and Oblique Mercator parameter names.

        Args:
            wkt2_string: WKT2 CRS string
            easting: Absolute False Easting value
            northing: Absolute False Northing value

        Returns:
            Tuple of (modified_wkt2, success) where success=True if both params found
        """
        result = wkt2_string

        easting_names = [
            "False easting",
            "Easting at false origin",
            "Easting at projection centre",
        ]
        northing_names = [
            "False northing",
            "Northing at false origin",
            "Northing at projection centre",
        ]

        easting_set = False
        for param_name in easting_names:
            pattern = rf'(PARAMETER\s*\[\s*"{param_name}"\s*,\s*)(-?[\d.]+)(\s*,)'
            new_result = re.sub(
                pattern,
                lambda m, val=easting: f"{m.group(1)}{val:.4f}{m.group(3)}",
                result,
                flags=re.IGNORECASE
            )
            if new_result != result:
                result = new_result
                easting_set = True
                break

        northing_set = False
        for param_name in northing_names:
            pattern = rf'(PARAMETER\s*\[\s*"{param_name}"\s*,\s*)(-?[\d.]+)(\s*,)'
            new_result = re.sub(
                pattern,
                lambda m, val=northing: f"{m.group(1)}{val:.4f}{m.group(3)}",
                result,
                flags=re.IGNORECASE
            )
            if new_result != result:
                result = new_result
                northing_set = True
                break

        return result, easting_set and northing_set

    def _build_virtual_crs_standard(
        self, x_0: float, y_0: float
    ) -> Optional[QgsCoordinateReferenceSystem]:
        """Build virtual CRS for standard mode by modifying WKT2 of object_layer_crs.

        Matches the exact path of apply_projection_offset:
        current WKT2 -> regex replace FE/FN -> fromWkt().

        This ensures the virtual CRS uses the same pipeline as the eventual
        USER CRS, capturing any pipeline difference with the original EPSG CRS.
        """
        wkt2 = self.object_layer_crs.toWkt(Qgis.CrsWktVariant.Wkt2_2019)
        modified_wkt2, success = self._set_wkt2_offsets(wkt2, x_0, y_0)

        if not success:
            log_warning("Fsm_0_5: Refinement: FE/FN not found in WKT2, skipping")
            return None

        crs = QgsCoordinateReferenceSystem.fromWkt(modified_wkt2)
        return crs if crs.isValid() else None

    def _build_virtual_crs_interzonal(
        self,
        x_0: float,
        y_0: float,
        lon_0: float,
        lat_0: float,
        k_0: float,
        ellps_param: str,
        towgs84_param: str
    ) -> Optional[QgsCoordinateReferenceSystem]:
        """Build virtual CRS for interzonal mode via PROJ -> WKT2 -> CRS.

        Matches the exact path of apply_custom_projection:
        PROJ string -> createFromProj() -> toWkt() -> fromWkt().
        """
        proj_string = (
            f"+proj=tmerc "
            f"+lat_0={lat_0:.6f} "
            f"+lon_0={lon_0:.6f} "
            f"+k_0={k_0:.8f} "
            f"+x_0={x_0:.4f} "
            f"+y_0={y_0:.4f} "
            f"{ellps_param} "
            f"{towgs84_param} "
            f"+units=m +no_defs"
        )

        temp_crs = QgsCoordinateReferenceSystem()
        if not temp_crs.createFromProj(proj_string):
            return None

        # Convert PROJ -> WKT2 -> CRS (same path as apply_custom_projection)
        wkt2 = temp_crs.toWkt(Qgis.CrsWktVariant.Wkt2_2019)
        crs = QgsCoordinateReferenceSystem.fromWkt(wkt2)

        if not crs.isValid():
            # Fallback: use PROJ-based CRS directly (same as apply_custom_projection)
            return temp_crs if temp_crs.isValid() else None

        return crs

    def _iterative_refine(
        self,
        x_0: float,
        y_0: float,
        crs_builder: Callable[[float, float], Optional[QgsCoordinateReferenceSystem]]
    ) -> Optional[tuple]:
        """Iterative refinement of x_0/y_0 through virtual CRS verification.

        Creates virtual CRS via crs_builder (matching the actual apply path),
        transforms correct_3857 through it, compares with wrong_msk
        and adjusts x_0/y_0 by mean residual. Repeats until convergence.

        Fixes systematic ~1.8cm error caused by pipeline difference between
        EPSG CRS and USER CRS.

        Args:
            x_0, y_0: Initial false easting/northing to refine
            crs_builder: Callable(x_0, y_0) -> CRS matching the actual apply path

        Returns:
            Tuple (refined_x_0, refined_y_0, true_rmse, per_point_deviations)
            or None on error
        """
        filled_pairs = [(i, pair) for i, pair in enumerate(self.point_pairs) if pair is not None]
        if not filled_pairs:
            return None

        epsg_3857 = QgsCoordinateReferenceSystem("EPSG:3857")
        current_x_0 = x_0
        current_y_0 = y_0

        best_x_0 = x_0
        best_y_0 = y_0
        best_rmse = float('inf')
        best_deviations: list = []

        for iteration in range(self.MAX_REFINEMENT_ITERATIONS):
            test_crs = crs_builder(current_x_0, current_y_0)
            if test_crs is None or not test_crs.isValid():
                log_warning(
                    f"Fsm_0_5: Refinement: failed to build CRS at iteration {iteration + 1}"
                )
                break

            try:
                transform = QgsCoordinateTransform(epsg_3857, test_crs, QgsProject.instance())
            except Exception as e:
                log_warning(f"Fsm_0_5: Refinement: transform creation error: {e}")
                break

            residuals_x: list = []
            residuals_y: list = []
            deviations: list = []

            for idx, pair in filled_pairs:
                wrong_msk, correct_3857 = pair
                try:
                    correct_in_virtual = transform.transform(correct_3857)
                except QgsCsException:
                    log_warning(f"Fsm_0_5: Refinement: transform error for pair {idx + 1}")
                    continue

                res_x = wrong_msk.x() - correct_in_virtual.x()
                res_y = wrong_msk.y() - correct_in_virtual.y()
                residuals_x.append(res_x)
                residuals_y.append(res_y)
                deviations.append(math.sqrt(res_x**2 + res_y**2))

            if not residuals_x:
                log_warning("Fsm_0_5: Refinement: no valid residuals")
                break

            true_rmse = math.sqrt(sum(d**2 for d in deviations) / len(deviations))

            if true_rmse < best_rmse:
                best_x_0 = current_x_0
                best_y_0 = current_y_0
                best_rmse = true_rmse
                best_deviations = deviations[:]

            mean_res_x = sum(residuals_x) / len(residuals_x)
            mean_res_y = sum(residuals_y) / len(residuals_y)
            adjustment = math.sqrt(mean_res_x**2 + mean_res_y**2)

            log_info(
                f"Fsm_0_5: Refinement iteration {iteration + 1}: "
                f"adjustment={adjustment:.6f}m, RMSE={true_rmse:.6f}m"
            )

            if adjustment < self.REFINEMENT_CONVERGENCE_THRESHOLD:
                log_info(f"Fsm_0_5: Refinement converged at iteration {iteration + 1}")
                best_x_0 = current_x_0
                best_y_0 = current_y_0
                best_rmse = true_rmse
                best_deviations = deviations[:]
                break

            current_x_0 += mean_res_x
            current_y_0 += mean_res_y

        # Padding deviations to point_pairs length
        full_deviations: list = []
        dev_iter = iter(best_deviations)
        for pair in self.point_pairs:
            if pair is not None:
                full_deviations.append(next(dev_iter, None))
            else:
                full_deviations.append(None)

        return (best_x_0, best_y_0, best_rmse, full_deviations)

    def _refine_standard_result(self, result: dict) -> dict:
        """Refine standard result through iterative verification.

        Uses WKT2 modification path (same as apply_projection_offset).
        The virtual CRS uses the same pipeline as the eventual USER CRS,
        so residuals capture the real pipeline-difference error.
        """
        original_rmse = result['rmse']

        refined = self._iterative_refine(
            x_0=result['new_x_0'],
            y_0=result['new_y_0'],
            crs_builder=self._build_virtual_crs_standard
        )

        if refined is None:
            log_warning("Fsm_0_5: Refinement: standard refinement returned None, keeping original")
            return result

        refined_x_0, refined_y_0, true_rmse, deviations = refined

        if true_rmse > original_rmse * 1.5:
            log_warning(
                f"Fsm_0_5: Refinement: RMSE degraded ({original_rmse:.6f} -> {true_rmse:.6f}), "
                f"keeping original"
            )
            return result

        # Recalculate delta_x/delta_y from current CRS
        proj_str = self.object_layer_crs.toProj()
        x_0_match = re.search(r'\+x_0=([\d\.\-]+)', proj_str)
        y_0_match = re.search(r'\+y_0=([\d\.\-]+)', proj_str)
        current_x_0 = float(x_0_match.group(1)) if x_0_match else 0.0
        current_y_0 = float(y_0_match.group(1)) if y_0_match else 0.0

        result['new_x_0'] = refined_x_0
        result['new_y_0'] = refined_y_0
        result['delta_x'] = refined_x_0 - current_x_0
        result['delta_y'] = refined_y_0 - current_y_0
        result['rmse'] = true_rmse
        result['deviations'] = deviations

        log_info(
            f"Fsm_0_5: Standard refinement: RMSE {original_rmse:.6f} -> {true_rmse:.6f}m, "
            f"x_0={refined_x_0:.2f}, y_0={refined_y_0:.2f}"
        )

        return result

    def _refine_interzonal_result(self, result: dict) -> dict:
        """Refine interzonal result through iterative verification.

        Uses PROJ -> WKT2 -> CRS path (same as apply_custom_projection).
        """
        original_rmse = result['rmse']

        ellps_param = result.get('ellps_param', ELLPS_KRASS)
        towgs84_param = result.get('towgs84_param', TOWGS84_SK42_PROJ)
        lon_0 = result['lon_0']
        k_0 = result['k_0']

        def crs_builder(x_0: float, y_0: float) -> Optional[QgsCoordinateReferenceSystem]:
            return self._build_virtual_crs_interzonal(
                x_0, y_0, lon_0, 0.0, k_0, ellps_param, towgs84_param
            )

        refined = self._iterative_refine(
            x_0=result['x_0'],
            y_0=result['y_0'],
            crs_builder=crs_builder
        )

        if refined is None:
            log_warning(
                "Fsm_0_5: Refinement: interzonal refinement returned None, keeping original"
            )
            return result

        refined_x_0, refined_y_0, true_rmse, deviations = refined

        if true_rmse > original_rmse * 1.5:
            log_warning(
                f"Fsm_0_5: Refinement: interzonal RMSE degraded "
                f"({original_rmse:.6f} -> {true_rmse:.6f}), keeping original"
            )
            return result

        original_x_0 = result['x_0']
        original_y_0 = result['y_0']
        result['x_0'] = refined_x_0
        result['y_0'] = refined_y_0
        result['rmse'] = true_rmse
        result['refinement_dx'] = refined_x_0 - original_x_0
        result['refinement_dy'] = refined_y_0 - original_y_0

        if 'all_results' in result and result['all_results']:
            best = result['all_results'][0]
            if hasattr(best, 'diagnostics') and isinstance(best.diagnostics, dict):
                best.diagnostics['errors'] = [d for d in deviations if d is not None]
            best.x_0 = refined_x_0
            best.y_0 = refined_y_0
            best.rmse = true_rmse

        log_info(
            f"Fsm_0_5: Interzonal refinement: RMSE {original_rmse:.6f} -> {true_rmse:.6f}m, "
            f"x_0={refined_x_0:.2f}, y_0={refined_y_0:.2f}"
        )

        return result

    def _display_result(self, standard_result, interzonal_result):
        """Отображение результатов и выбор лучшего.

        Args:
            standard_result: dict с результатами стандартного расчёта
            interzonal_result: dict с результатами перерасчёта СК (может быть None)
        """
        # Определяем какой результат лучше
        use_interzonal = False
        comparison_text = ""

        if standard_result and interzonal_result:
            std_rmse = standard_result['rmse']
            int_rmse = interzonal_result['rmse']

            # Если оба RMSE ниже порога точности (1 мм) — различие несущественно,
            # предпочитаем стандартный (проверенный pipeline, стабильный x_0)
            RMSE_EQUIVALENT_THRESHOLD = 0.001  # 1 мм
            if std_rmse < RMSE_EQUIVALENT_THRESHOLD and int_rmse < RMSE_EQUIVALENT_THRESHOLD:
                use_interzonal = False
                comparison_text = "Оба RMSE < 1мм, выбран стандартный (стабильнее)"
            elif int_rmse < std_rmse * 0.8:
                use_interzonal = True
                improvement = (std_rmse - int_rmse) / std_rmse * 100
                comparison_text = f"Перерасчёт СК точнее на {improvement:.0f}%"
            elif std_rmse < int_rmse * 0.8:
                use_interzonal = False
                improvement = (int_rmse - std_rmse) / int_rmse * 100
                comparison_text = f"Стандартный точнее на {improvement:.0f}%"
            else:
                # Результаты близки - предпочитаем стандартный как более простой
                use_interzonal = False
                comparison_text = "Результаты близки, выбран стандартный"

            log_info(f"Fsm_0_5: Сравнение: std={std_rmse:.4f}м, int={int_rmse:.4f}м -> {comparison_text}")

        elif standard_result:
            use_interzonal = False
            comparison_text = "Перерасчёт СК недоступен"
        elif interzonal_result:
            use_interzonal = True
            comparison_text = "Стандартный расчёт не удался"
        else:
            self.iface.messageBar().pushMessage(
                "Ошибка",
                "Не удалось выполнить ни один расчёт",
                level=Qgis.Critical,
                duration=MESSAGE_INFO_DURATION
            )
            return

        # Применяем выбранный результат
        if use_interzonal:
            result = interzonal_result
            self.interzonal_mode = True
            self.interzonal_params = {
                "lon_0": result['lon_0'],
                "lat_0": 0.0,
                "k_0": result['k_0'],
                "x_0": result['x_0'],
                "y_0": result['y_0'],
                "ellps_param": result.get('ellps_param'),
                "towgs84_param": result.get('towgs84_param')
            }
            self.avg_error = result['rmse']
            method_display = f"{result['method_name']} ({result['method_id']}, {result['approach_type']})"

            # Обновляем отклонения из all_results если доступны
            if 'all_results' in result and result['all_results']:
                best = result['all_results'][0]
                if hasattr(best, 'diagnostics') and 'errors' in best.diagnostics:
                    self.pair_deviations = best.diagnostics['errors'][:len(self.point_pairs)]
                    # Дополняем None если нужно
                    while len(self.pair_deviations) < len(self.point_pairs):
                        self.pair_deviations.append(None)
        else:
            result = standard_result
            self.interzonal_mode = False
            self.delta_x = result['delta_x']
            self.delta_y = result['delta_y']
            self.avg_error = result['rmse']
            self.pair_deviations = result['deviations']
            # Дополняем None если нужно
            while len(self.pair_deviations) < len(self.point_pairs):
                self.pair_deviations.append(None)
            method_display = "Стандартный (смещение x_0/y_0)"

        # Обновляем GUI
        self.error_edit.setText(f"{self.avg_error:.4f} м")

        if use_interzonal:
            rdx = result.get('refinement_dx', 0.0)
            rdy = result.get('refinement_dy', 0.0)
            self.shift_edit.setText(f"dX = {rdx:+.4f} м, dY = {rdy:+.4f} м")
        else:
            dx = result.get('delta_x', 0.0)
            dy = result.get('delta_y', 0.0)
            self.shift_edit.setText(f"dX = {dx:+.4f} м, dY = {dy:+.4f} м")

        self.method_edit.setText(method_display)
        self._update_deviation_column()

        # Формируем статус
        status_lines = [f"Расчёт завершён: {comparison_text}"]
        status_lines.append("")

        if standard_result:
            status_lines.append(f"Стандартный: RMSE = {standard_result['rmse']:.4f} м")
            status_lines.append(f"  x_0 = {standard_result['new_x_0']:.2f} м, y_0 = {standard_result['new_y_0']:.2f} м")

        if interzonal_result:
            status_lines.append(f"Перерасчёт СК: RMSE = {interzonal_result['rmse']:.4f} м")
            status_lines.append(f"  Метод: {interzonal_result['method_name']} ({interzonal_result['approach_type']})")
            status_lines.append(f"  lon_0 = {interzonal_result['lon_0']:.4f}°")
            status_lines.append(f"  x_0 = {interzonal_result['x_0']:.2f} м, y_0 = {interzonal_result['y_0']:.2f} м")

        status_lines.append("")
        status_lines.append(f"ВЫБРАН: {'Перерасчёт СК' if use_interzonal else 'Стандартный'}")

        # Логируем результат
        for line in status_lines:
            if line.strip():
                log_info(f"Fsm_0_5: {line}")

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

        log_info("Fsm_0_5: Создаю новую проекцию и применяю к проекту...")

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

            log_info("Fsm_0_5: Новая проекция успешно создана и применена")
            self.iface.messageBar().pushMessage(
                "Успех",
                "Проекция создана и применена к проекту",
                level=Qgis.Success,
                duration=MESSAGE_SUCCESS_DURATION
            )
            self.clear_all_graphics()
            self.parent_tool.deactivate_map_tool()
            self.accept()
        else:
            log_error("Fsm_0_5: Ошибка при создании новой проекции")
            self.iface.messageBar().pushMessage(
                "Ошибка",
                "Не удалось создать проекцию. Проверьте логи.",
                level=Qgis.Critical,
                duration=MESSAGE_INFO_DURATION
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

        log_info("Fsm_0_5: Создаю кастомную проекцию и применяю к проекту...")

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

            log_success("Fsm_0_5: Кастомная проекция успешно создана и применена")
            self.clear_all_graphics()
            self.parent_tool.deactivate_map_tool()
            self.accept()
        else:
            log_error("Fsm_0_5: Ошибка при создании кастомной проекции")
            self.iface.messageBar().pushMessage(
                "Ошибка",
                "Не удалось создать кастомную проекцию. Проверьте логи.",
                level=Qgis.Critical,
                duration=MESSAGE_INFO_DURATION
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
