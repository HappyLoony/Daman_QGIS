# -*- coding: utf-8 -*-
"""
Fsm_7_1_1: Dialog - Диалог транспортной доступности.

QDialog с QTabWidget (3 вкладки):
1. Изохроны - зоны доступности от точки/слоя
2. Маршруты - кратчайший путь A -> B
3. ГОЧС - эвакуация, ближайший объект, покрытие станций

Все вычисления делегируются M_41 IsochroneTransportManager.
"""

from __future__ import annotations

from typing import Any, Optional

from qgis.core import (
    QgsGeometry,
    QgsMapLayerProxyModel,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapLayerComboBox, QgsMapToolEmitPoint
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from Daman_QGIS.constants import (
    LAYER_GOCHS_ACCESSIBILITY,
    LAYER_GOCHS_GROUP,
    LAYER_GOCHS_ROUTES,
)
from Daman_QGIS.core.base_responsive_dialog import BaseResponsiveDialog
from Daman_QGIS.utils import log_error, log_info

from Daman_QGIS.managers.processing.submodules.Msm_41_4_speed_profiles import (
    REGULATORY_PRESETS,
)

__all__ = ['Fsm_7_1_1_Dialog']


class Fsm_7_1_1_Dialog(BaseResponsiveDialog):
    """Диалог анализа транспортной доступности."""

    WIDTH_RATIO = 0.40
    HEIGHT_RATIO = 0.75
    MIN_WIDTH = 480
    MAX_WIDTH = 650
    MIN_HEIGHT = 500
    MAX_HEIGHT = 800

    MODULE_ID = "Fsm_7_1_1"

    def __init__(
        self,
        iface: Any,
        m41: Any,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._iface = iface
        self._m41 = m41
        self._map_tool: Optional[QgsMapToolEmitPoint] = None
        self._pick_target: Optional[str] = None  # 'origin', 'dest', 'evac_origin'

        # Результаты последнего вычисления
        self._last_routes: list = []
        self._last_isochrones: list = []

        self._setup_ui()
        self._connect_signals()

    # ==================================================================
    # UI Setup
    # ==================================================================

    def _setup_ui(self) -> None:
        """Построить интерфейс."""
        self.setWindowTitle("F_7_1: Транспортная доступность")

        main_layout = QVBoxLayout(self)

        # --- Tab widget ---
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_isochrone_tab(), "Изохроны")
        self._tabs.addTab(self._build_route_tab(), "Маршруты")
        self._tabs.addTab(self._build_gochs_tab(), "ГОЧС")
        main_layout.addWidget(self._tabs)

        # --- Общая нижняя панель ---
        bottom_group = QGroupBox("Результаты")
        bottom_layout = QVBoxLayout(bottom_group)

        self._result_info = QTextEdit()
        self._result_info.setReadOnly(True)
        self._result_info.setMaximumHeight(120)
        self._result_info.setStyleSheet("background-color: #f5f5f5;")
        bottom_layout.addWidget(self._result_info)

        # Сохранение
        save_layout = QHBoxLayout()
        save_layout.addWidget(QLabel("Имя слоя:"))
        self._layer_name_edit = QLineEdit(LAYER_GOCHS_ACCESSIBILITY)
        save_layout.addWidget(self._layer_name_edit)
        self._save_btn = QPushButton("Сохранить результат")
        self._save_btn.setEnabled(False)
        save_layout.addWidget(self._save_btn)
        bottom_layout.addLayout(save_layout)

        # Прогресс
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        bottom_layout.addWidget(self._progress)

        main_layout.addWidget(bottom_group)

    def _build_isochrone_tab(self) -> QWidget:
        """Вкладка 1: Изохроны."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Центр
        center_group = QGroupBox("Центральная точка")
        center_layout = QFormLayout(center_group)

        self._iso_layer_combo = QgsMapLayerComboBox()
        self._iso_layer_combo.setFilters(QgsMapLayerProxyModel.Filter.PointLayer)
        self._iso_layer_combo.setAllowEmptyLayer(True)
        center_layout.addRow("Слой точек:", self._iso_layer_combo)

        self._iso_coord_label = QLabel("Не выбрана")
        pick_layout = QHBoxLayout()
        pick_layout.addWidget(self._iso_coord_label)
        self._iso_pick_btn = QPushButton("Указать на карте")
        pick_layout.addWidget(self._iso_pick_btn)
        center_layout.addRow("Точка:", pick_layout)

        layout.addWidget(center_group)

        # Параметры
        params_group = QGroupBox("Параметры")
        params_layout = QFormLayout(params_group)

        self._iso_profile = QComboBox()
        self._iso_profile.addItems(["walk", "drive", "fire_truck"])
        params_layout.addRow("Профиль:", self._iso_profile)

        self._iso_preset = QComboBox()
        self._iso_preset.addItem("Свои параметры", "custom")
        for name, preset in REGULATORY_PRESETS.items():
            self._iso_preset.addItem(
                f"{name} ({preset['description']})", name
            )
        params_layout.addRow("Пресет:", self._iso_preset)

        self._iso_intervals = QLineEdit("5, 10, 15")
        self._iso_intervals.setToolTip(
            "Интервалы через запятую (минуты для времени, метры для расстояния)"
        )
        params_layout.addRow("Интервалы:", self._iso_intervals)

        unit_layout = QHBoxLayout()
        self._iso_unit_time = QRadioButton("Время (мин)")
        self._iso_unit_time.setChecked(True)
        self._iso_unit_dist = QRadioButton("Расстояние (м)")
        unit_layout.addWidget(self._iso_unit_time)
        unit_layout.addWidget(self._iso_unit_dist)
        params_layout.addRow("Единицы:", unit_layout)

        self._iso_cell_size = QSpinBox()
        self._iso_cell_size.setRange(5, 50)
        self._iso_cell_size.setValue(15)
        self._iso_cell_size.setSuffix(" м")
        params_layout.addRow("Размер ячейки:", self._iso_cell_size)

        layout.addWidget(params_group)

        # Кнопка
        self._iso_run_btn = QPushButton("Построить изохроны")
        layout.addWidget(self._iso_run_btn)
        layout.addStretch()

        return tab

    def _build_route_tab(self) -> QWidget:
        """Вкладка 2: Маршруты."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Точки
        points_group = QGroupBox("Точки маршрута")
        points_layout = QFormLayout(points_group)

        self._route_origin_label = QLabel("Не выбрана")
        origin_layout = QHBoxLayout()
        origin_layout.addWidget(self._route_origin_label)
        self._route_origin_btn = QPushButton("Точка А")
        origin_layout.addWidget(self._route_origin_btn)
        points_layout.addRow("Начало:", origin_layout)

        self._route_dest_label = QLabel("Не выбрана")
        dest_layout = QHBoxLayout()
        dest_layout.addWidget(self._route_dest_label)
        self._route_dest_btn = QPushButton("Точка Б")
        dest_layout.addWidget(self._route_dest_btn)
        points_layout.addRow("Конец:", dest_layout)

        self._route_dest_layer = QgsMapLayerComboBox()
        self._route_dest_layer.setFilters(QgsMapLayerProxyModel.Filter.PointLayer)
        self._route_dest_layer.setAllowEmptyLayer(True)
        points_layout.addRow("Или слой целей:", self._route_dest_layer)

        layout.addWidget(points_group)

        # Параметры
        params_group = QGroupBox("Параметры")
        params_layout = QFormLayout(params_group)

        self._route_profile = QComboBox()
        self._route_profile.addItems(["drive", "walk", "fire_truck"])
        params_layout.addRow("Профиль:", self._route_profile)

        layout.addWidget(params_group)

        # Кнопки
        btn_layout = QHBoxLayout()
        self._route_single_btn = QPushButton("Найти маршрут")
        self._route_batch_btn = QPushButton("Маршруты ко всем")
        btn_layout.addWidget(self._route_single_btn)
        btn_layout.addWidget(self._route_batch_btn)
        layout.addLayout(btn_layout)
        layout.addStretch()

        return tab

    def _build_gochs_tab(self) -> QWidget:
        """Вкладка 3: ГОЧС."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Режим
        mode_layout = QFormLayout()
        self._gochs_mode = QComboBox()
        self._gochs_mode.addItems([
            "Эвакуация из зоны",
            "Ближайший объект",
            "Покрытие станций",
        ])
        mode_layout.addRow("Режим:", self._gochs_mode)
        layout.addLayout(mode_layout)

        # Stacked widget для разных режимов
        self._gochs_stack = QStackedWidget()

        # --- Page 0: Эвакуация ---
        evac_page = QWidget()
        evac_layout = QFormLayout(evac_page)

        self._evac_origin_label = QLabel("Не выбрана")
        evac_origin_layout = QHBoxLayout()
        evac_origin_layout.addWidget(self._evac_origin_label)
        self._evac_origin_btn = QPushButton("Указать на карте")
        evac_origin_layout.addWidget(self._evac_origin_btn)
        evac_layout.addRow("Точка внутри зоны:", evac_origin_layout)

        self._evac_zone_layer = QgsMapLayerComboBox()
        self._evac_zone_layer.setFilters(QgsMapLayerProxyModel.Filter.PolygonLayer)
        evac_layout.addRow("Слой зоны:", self._evac_zone_layer)

        self._evac_profile = QComboBox()
        self._evac_profile.addItems(["walk", "drive"])
        evac_layout.addRow("Профиль:", self._evac_profile)

        self._gochs_stack.addWidget(evac_page)

        # --- Page 1: Ближайший объект ---
        nearest_page = QWidget()
        nearest_layout = QFormLayout(nearest_page)

        self._nearest_origin_label = QLabel("Не выбрана")
        nearest_origin_layout = QHBoxLayout()
        nearest_origin_layout.addWidget(self._nearest_origin_label)
        self._nearest_origin_btn = QPushButton("Указать на карте")
        nearest_origin_layout.addWidget(self._nearest_origin_btn)
        nearest_layout.addRow("Начальная точка:", nearest_origin_layout)

        self._nearest_facilities = QgsMapLayerComboBox()
        self._nearest_facilities.setFilters(QgsMapLayerProxyModel.Filter.PointLayer)
        nearest_layout.addRow("Слой объектов:", self._nearest_facilities)

        self._nearest_profile = QComboBox()
        self._nearest_profile.addItems(["drive", "walk", "fire_truck"])
        nearest_layout.addRow("Профиль:", self._nearest_profile)

        self._gochs_stack.addWidget(nearest_page)

        # --- Page 2: Покрытие станций ---
        coverage_page = QWidget()
        coverage_layout = QFormLayout(coverage_page)

        self._coverage_layer = QgsMapLayerComboBox()
        self._coverage_layer.setFilters(QgsMapLayerProxyModel.Filter.PointLayer)
        coverage_layout.addRow("Слой станций:", self._coverage_layer)

        self._coverage_preset = QComboBox()
        for name, preset in REGULATORY_PRESETS.items():
            if 'fire' in name or 'evacuation' in name:
                self._coverage_preset.addItem(
                    f"{name} ({preset['description']})", name
                )
        coverage_layout.addRow("Пресет:", self._coverage_preset)

        self._gochs_stack.addWidget(coverage_page)

        layout.addWidget(self._gochs_stack)

        # Кнопка
        self._gochs_run_btn = QPushButton("Выполнить")
        layout.addWidget(self._gochs_run_btn)
        layout.addStretch()

        return tab

    # ==================================================================
    # Signals
    # ==================================================================

    def _connect_signals(self) -> None:
        """Подключить сигналы виджетов."""
        # Изохроны
        self._iso_pick_btn.clicked.connect(
            lambda: self._start_map_pick('iso_center')
        )
        self._iso_preset.currentIndexChanged.connect(self._on_preset_changed)
        self._iso_run_btn.clicked.connect(self._run_isochrone)

        # Маршруты
        self._route_origin_btn.clicked.connect(
            lambda: self._start_map_pick('origin')
        )
        self._route_dest_btn.clicked.connect(
            lambda: self._start_map_pick('dest')
        )
        self._route_single_btn.clicked.connect(self._run_single_route)
        self._route_batch_btn.clicked.connect(self._run_batch_routes)

        # ГОЧС
        self._gochs_mode.currentIndexChanged.connect(
            self._gochs_stack.setCurrentIndex
        )
        self._evac_origin_btn.clicked.connect(
            lambda: self._start_map_pick('evac_origin')
        )
        self._nearest_origin_btn.clicked.connect(
            lambda: self._start_map_pick('nearest_origin')
        )
        self._gochs_run_btn.clicked.connect(self._run_gochs)

        # Сохранение
        self._save_btn.clicked.connect(self._save_results)

    # ==================================================================
    # Map tool
    # ==================================================================

    def _start_map_pick(self, target: str) -> None:
        """Начать выбор точки на карте."""
        self._pick_target = target
        canvas = self._iface.mapCanvas()
        self._map_tool = QgsMapToolEmitPoint(canvas)
        self._map_tool.canvasClicked.connect(self._on_map_clicked)
        canvas.setMapTool(self._map_tool)
        self._iface.messageBar().pushMessage(
            "F_7_1", "Кликните на карте для выбора точки",
            duration=3
        )

    def _on_map_clicked(self, point: QgsPointXY, button: Any) -> None:
        """Обработать клик на карте."""
        coord_text = f"{point.x():.1f}, {point.y():.1f}"

        label_map: dict[str, QLabel] = {
            'iso_center': self._iso_coord_label,
            'origin': self._route_origin_label,
            'dest': self._route_dest_label,
            'evac_origin': self._evac_origin_label,
            'nearest_origin': self._nearest_origin_label,
        }

        target = self._pick_target or ''
        if target in label_map:
            label_map[target].setText(coord_text)
            label_map[target].setProperty('point', point)

        # Восстановить инструмент навигации
        self._iface.mapCanvas().unsetMapTool(self._map_tool)
        self._map_tool = None
        self._pick_target = None

        # Вернуть фокус на диалог
        self.raise_()
        self.activateWindow()

    # ==================================================================
    # Runners
    # ==================================================================

    def _run_isochrone(self) -> None:
        """Запуск построения изохрон."""
        log_info("Fsm_7_1_1: Запуск изохрон")

        # Получить центр
        center = self._get_point_from_label(self._iso_coord_label)
        if center is None:
            QMessageBox.warning(self, "F_7_1", "Укажите центральную точку на карте")
            return

        # Получить параметры
        profile = self._iso_profile.currentText()
        preset_data = self._iso_preset.currentData()

        if preset_data and preset_data != 'custom':
            # Использовать пресет
            try:
                self._show_progress(True)
                results = self._m41.isochrone_from_preset(
                    center=center,
                    preset_name=preset_data,
                    cell_size=self._iso_cell_size.value(),
                )
                self._last_isochrones = results
                self._display_isochrone_results(results)
            except Exception as e:
                self._show_error(f"Ошибка изохрон: {e}")
            finally:
                self._show_progress(False)
        else:
            # Свои параметры
            intervals = self._parse_intervals()
            if not intervals:
                return

            unit = 'time' if self._iso_unit_time.isChecked() else 'distance'
            # Конвертация минут -> секунды для time
            if unit == 'time':
                intervals = [i * 60 for i in intervals]

            try:
                self._show_progress(True)
                results = self._m41.isochrone(
                    center=center,
                    intervals=intervals,
                    profile=profile,
                    unit=unit,
                    cell_size=self._iso_cell_size.value(),
                )
                self._last_isochrones = results
                self._display_isochrone_results(results)
            except Exception as e:
                self._show_error(f"Ошибка изохрон: {e}")
            finally:
                self._show_progress(False)

    def _run_single_route(self) -> None:
        """Запуск одиночного маршрута."""
        log_info("Fsm_7_1_1: Запуск одиночного маршрута")

        origin = self._get_point_from_label(self._route_origin_label)
        dest = self._get_point_from_label(self._route_dest_label)

        if origin is None or dest is None:
            QMessageBox.warning(
                self, "F_7_1", "Укажите точки А и Б на карте"
            )
            return

        profile = self._route_profile.currentText()

        try:
            self._show_progress(True)
            result = self._m41.shortest_route(
                origin=origin,
                destination=dest,
                profile=profile,
            )
            self._last_routes = [result]
            self._layer_name_edit.setText(LAYER_GOCHS_ROUTES)
            self._display_route_results([result])
        except Exception as e:
            self._show_error(f"Ошибка маршрута: {e}")
        finally:
            self._show_progress(False)

    def _run_batch_routes(self) -> None:
        """Запуск маршрутов ко всем точкам слоя."""
        log_info("Fsm_7_1_1: Запуск batch маршрутов")

        origin = self._get_point_from_label(self._route_origin_label)
        if origin is None:
            QMessageBox.warning(self, "F_7_1", "Укажите точку А на карте")
            return

        dest_layer = self._route_dest_layer.currentLayer()
        if dest_layer is None:
            QMessageBox.warning(self, "F_7_1", "Выберите слой целей")
            return

        profile = self._route_profile.currentText()

        try:
            self._show_progress(True)
            results = self._m41.routes_from_point_to_layer(
                origin=origin,
                destinations=dest_layer,
                profile=profile,
            )
            self._last_routes = results
            self._layer_name_edit.setText(LAYER_GOCHS_ROUTES)
            self._display_route_results(results)
        except Exception as e:
            self._show_error(f"Ошибка batch маршрутов: {e}")
        finally:
            self._show_progress(False)

    def _run_gochs(self) -> None:
        """Запуск ГОЧС анализа по текущему режиму."""
        mode_index = self._gochs_mode.currentIndex()

        if mode_index == 0:
            self._run_evacuation()
        elif mode_index == 1:
            self._run_nearest_facility()
        elif mode_index == 2:
            self._run_station_coverage()

    def _run_evacuation(self) -> None:
        """Эвакуация из зоны."""
        log_info("Fsm_7_1_1: Запуск эвакуации")

        origin = self._get_point_from_label(self._evac_origin_label)
        if origin is None:
            QMessageBox.warning(
                self, "F_7_1", "Укажите точку внутри зоны на карте"
            )
            return

        zone_layer = self._evac_zone_layer.currentLayer()
        if zone_layer is None:
            QMessageBox.warning(self, "F_7_1", "Выберите слой зоны")
            return

        # Получить геометрию первого объекта зоны
        feat = next(zone_layer.getFeatures(), None)
        if feat is None or not feat.hasGeometry():
            QMessageBox.warning(self, "F_7_1", "Слой зоны пуст")
            return

        boundary = feat.geometry()
        profile = self._evac_profile.currentText()

        try:
            self._show_progress(True)
            result = self._m41.shortest_route_to_boundary(
                origin=origin,
                boundary=boundary,
                profile=profile,
            )
            self._last_routes = [result]
            self._layer_name_edit.setText(LAYER_GOCHS_ROUTES)
            self._display_route_results([result])
        except Exception as e:
            self._show_error(f"Ошибка эвакуации: {e}")
        finally:
            self._show_progress(False)

    def _run_nearest_facility(self) -> None:
        """Маршрут до ближайшего объекта."""
        log_info("Fsm_7_1_1: Запуск поиска ближайшего объекта")

        origin = self._get_point_from_label(self._nearest_origin_label)
        if origin is None:
            QMessageBox.warning(
                self, "F_7_1", "Укажите начальную точку на карте"
            )
            return

        facilities = self._nearest_facilities.currentLayer()
        if facilities is None:
            QMessageBox.warning(self, "F_7_1", "Выберите слой объектов")
            return

        profile = self._nearest_profile.currentText()

        try:
            self._show_progress(True)
            result = self._m41.nearest_facility_route(
                origin=origin,
                facilities_layer=facilities,
                profile=profile,
            )
            self._last_routes = [result]
            self._layer_name_edit.setText(LAYER_GOCHS_ROUTES)
            self._display_route_results([result])
        except Exception as e:
            self._show_error(f"Ошибка поиска: {e}")
        finally:
            self._show_progress(False)

    def _run_station_coverage(self) -> None:
        """Покрытие станций изохронами."""
        log_info("Fsm_7_1_1: Запуск покрытия станций")

        station_layer = self._coverage_layer.currentLayer()
        if station_layer is None:
            QMessageBox.warning(self, "F_7_1", "Выберите слой станций")
            return

        preset_name = self._coverage_preset.currentData()
        if not preset_name:
            QMessageBox.warning(self, "F_7_1", "Выберите пресет")
            return

        preset = REGULATORY_PRESETS.get(preset_name)
        if not preset:
            return

        try:
            self._show_progress(True)
            task_id = self._m41.batch_isochrones(
                points_layer=station_layer,
                intervals=preset['intervals'],
                profile=preset['profile'],
                unit=preset['unit'],
                layer_name=LAYER_GOCHS_ACCESSIBILITY,
                on_completed=self._on_batch_completed,
                on_failed=self._on_batch_failed,
            )
            self._result_info.setText(
                f"Фоновая задача запущена: {task_id}\n"
                f"Результат появится в проекте автоматически."
            )
        except Exception as e:
            self._show_error(f"Ошибка batch: {e}")
        finally:
            self._show_progress(False)

    # ==================================================================
    # Result display
    # ==================================================================

    def _display_isochrone_results(self, results: list) -> None:
        """Показать результаты изохрон."""
        lines = []
        for r in results:
            if r.geometry and not r.geometry.isEmpty():
                unit_label = "с" if r.unit == 'time' else "м"
                lines.append(
                    f"  Интервал {r.interval} {unit_label}: "
                    f"площадь {r.area_sq_m:.0f} кв.м "
                    f"({r.area_sq_m / 10000:.2f} га)"
                )
            else:
                lines.append(f"  Интервал {r.interval}: не построено")

        valid = sum(1 for r in results if r.geometry and not r.geometry.isEmpty())
        header = f"Построено {valid}/{len(results)} изохрон"
        self._result_info.setText(header + "\n" + "\n".join(lines))
        self._save_btn.setEnabled(valid > 0)
        self._layer_name_edit.setText(LAYER_GOCHS_ACCESSIBILITY)

    def _display_route_results(self, results: list) -> None:
        """Показать результаты маршрутов."""
        lines = []
        for i, r in enumerate(results, 1):
            if r.success:
                lines.append(
                    f"  Маршрут {i}: {r.distance_m:.0f} м, "
                    f"{r.duration_s / 60:.1f} мин ({r.profile})"
                )
            else:
                lines.append(f"  Маршрут {i}: {r.error_message}")

        found = sum(1 for r in results if r.success)
        header = f"Найдено {found}/{len(results)} маршрутов"
        self._result_info.setText(header + "\n" + "\n".join(lines))
        self._save_btn.setEnabled(found > 0)

    def _on_batch_completed(self, layer: QgsVectorLayer) -> None:
        """Callback завершения batch задачи."""
        self._result_info.setText(
            f"Batch завершен: слой '{layer.name()}' добавлен в проект"
        )

    def _on_batch_failed(self, error: str) -> None:
        """Callback ошибки batch задачи."""
        self._result_info.setText(f"Batch ошибка: {error}")

    # ==================================================================
    # Save results
    # ==================================================================

    def _save_results(self) -> None:
        """Сохранить результаты в слой."""
        layer_name = self._layer_name_edit.text().strip()
        if not layer_name:
            layer_name = LAYER_GOCHS_ACCESSIBILITY

        try:
            result_layer: Optional[QgsVectorLayer] = None

            if self._last_isochrones:
                result_layer = self._m41.save_isochrones_to_layer(
                    isochrones=self._last_isochrones,
                    layer_name=layer_name,
                )
            elif self._last_routes:
                successful = [r for r in self._last_routes if r.success]
                if successful:
                    result_layer = self._m41.save_routes_to_layer(
                        routes=successful,
                        layer_name=layer_name,
                    )

            if result_layer:
                self._place_in_gochs_group(result_layer)
                self._result_info.append(
                    f"\nСлой '{layer_name}' сохранен в группу '{LAYER_GOCHS_GROUP}'"
                )
                log_info(f"Fsm_7_1_1: Результат сохранен: {layer_name}")
            else:
                QMessageBox.warning(self, "F_7_1", "Нет данных для сохранения")

        except Exception as e:
            self._show_error(f"Ошибка сохранения: {e}")

    @staticmethod
    def _place_in_gochs_group(layer: QgsVectorLayer) -> None:
        """Переместить слой в группу ГОЧС в дереве проекта."""
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(LAYER_GOCHS_GROUP)
        if not group:
            group = root.addGroup(LAYER_GOCHS_GROUP)

        layer_node = root.findLayer(layer.id())
        if layer_node and layer_node.parent() != group:
            clone = layer_node.clone()
            group.insertChildNode(0, clone)
            parent = layer_node.parent()
            if parent:
                parent.removeChildNode(layer_node)

    # ==================================================================
    # Helpers
    # ==================================================================

    @staticmethod
    def _get_point_from_label(label: QLabel) -> Optional[QgsPointXY]:
        """Извлечь QgsPointXY из property label'а."""
        point = label.property('point')
        if isinstance(point, QgsPointXY):
            return point
        return None

    def _parse_intervals(self) -> list[int]:
        """Парсить строку интервалов."""
        text = self._iso_intervals.text().strip()
        if not text:
            QMessageBox.warning(self, "F_7_1", "Введите интервалы")
            return []

        try:
            intervals = [int(x.strip()) for x in text.split(',') if x.strip()]
            if not intervals:
                raise ValueError("Пустой список")
            return sorted(intervals)
        except ValueError:
            QMessageBox.warning(
                self, "F_7_1",
                "Неверный формат интервалов. Ожидается: 5, 10, 15"
            )
            return []

    def _on_preset_changed(self, index: int) -> None:
        """Обработка смены пресета."""
        preset_data = self._iso_preset.currentData()
        is_custom = (preset_data == 'custom' or preset_data is None)
        self._iso_intervals.setEnabled(is_custom)
        self._iso_unit_time.setEnabled(is_custom)
        self._iso_unit_dist.setEnabled(is_custom)

        if not is_custom and preset_data in REGULATORY_PRESETS:
            preset = REGULATORY_PRESETS[preset_data]
            self._iso_profile.setCurrentText(preset['profile'])

    def _show_progress(self, visible: bool) -> None:
        """Показать/скрыть прогресс."""
        self._progress.setVisible(visible)
        if visible:
            self._progress.setRange(0, 0)  # Indeterminate

    def _show_error(self, message: str) -> None:
        """Показать ошибку."""
        log_error(f"Fsm_7_1_1: {message}")
        self._result_info.setText(f"Ошибка: {message}")
        QMessageBox.critical(self, "F_7_1", message)

    def closeEvent(self, event: Any) -> None:
        """Очистка при закрытии."""
        if self._map_tool:
            self._iface.mapCanvas().unsetMapTool(self._map_tool)
            self._map_tool = None
        super().closeEvent(event)
