# -*- coding: utf-8 -*-
"""
Fsm_0_5_2 - Построитель кастомных проекций для межзональных объектов
Создает оптимизированную проекцию Transverse Mercator для линейных объектов на стыке зон МСК
"""

from typing import Optional, Tuple, Dict, List
import math

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox, QTextEdit, QMessageBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView
)
from qgis.PyQt.QtCore import Qt

from qgis.core import (
    QgsProject, QgsCoordinateReferenceSystem, QgsVectorLayer, QgsPointXY,
    QgsApplication, Qgis
)

from Daman_QGIS.utils import log_info, log_error, log_warning, log_success


class CustomProjectionBuilderDialog(QDialog):
    """Диалог создания кастомной проекции для межзональных объектов"""
    
    def __init__(self, iface, parent_tool):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.parent_tool = parent_tool

        # Параметры проекции
        self.optimal_params = {}  # Оптимизированные параметры

        # Геометрия объекта
        self.object_bounds = None  # Границы объекта (min_lon, max_lon)
        self.object_center = None  # Центр объекта (center_lon, center_lat)

        # Расширенный режим (калибровка по контрольным точкам)
        self.advanced_mode = False
        self.point_pairs: List[Optional[Tuple[QgsPointXY, QgsPointXY]]] = [None, None, None, None]
        self.current_selection_pair = None  # Индекс пары (0-3)
        self.current_selection_point = None  # 'wrong' или 'correct'

        self.setup_ui()
        self.auto_load_default_layer()
        
    def setup_ui(self):
        """Настройка интерфейса"""
        self.setWindowTitle("0_5 Кастомная проекция")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(700)
        self.setMinimumHeight(300)

        layout = QVBoxLayout()

        # Checkbox расширенного режима
        self.advanced_checkbox = QCheckBox(
            "Расширенный режим (калибровка x_0/y_0 по контрольным точкам)"
        )
        self.advanced_checkbox.setToolTip(
            "Включите для точной калибровки смещений через 4 пары контрольных точек.\n"
            "Укажите пары: неправильная позиция (в МСК) → правильная позиция (из WFS/эталона)."
        )
        self.advanced_checkbox.stateChanged.connect(self.on_advanced_mode_toggled)
        layout.addWidget(self.advanced_checkbox)

        # Информация
        info_label = QLabel(
            "Автоматическое создание оптимизированной проекции.\n"
            "Параметры рассчитываются из extent слоя L_1_1_1_Границы_работ."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Группа контрольных точек (скрыта по умолчанию)
        self.points_group = QGroupBox("Контрольные точки (4 пары обязательны)")
        points_layout = QVBoxLayout()

        points_info = QLabel(
            "Кликните на карте для каждой пары: сначала неправильная позиция (в МСК), "
            "затем правильная позиция (эталон).\nКоординаты можно редактировать вручную."
        )
        points_info.setWordWrap(True)
        points_layout.addWidget(points_info)

        self.points_table = QTableWidget(4, 5)
        self.points_table.setHorizontalHeaderLabels([
            "№", "Неправильная X", "Неправильная Y", "Правильная X", "Правильная Y"
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

        # Подключаем обработчики
        self.points_table.itemChanged.connect(self.on_table_cell_changed)
        self.points_table.itemSelectionChanged.connect(self.on_table_selection_changed)

        points_layout.addWidget(self.points_table)

        # Кнопки управления таблицей
        table_buttons = QHBoxLayout()
        self.clear_row_button = QPushButton("Очистить строку")
        self.clear_row_button.clicked.connect(self.on_clear_row_clicked)
        self.clear_row_button.setEnabled(False)
        table_buttons.addWidget(self.clear_row_button)

        self.clear_all_points_button = QPushButton("Очистить все точки")
        self.clear_all_points_button.clicked.connect(self.on_clear_all_points_clicked)
        table_buttons.addWidget(self.clear_all_points_button)

        table_buttons.addStretch()
        points_layout.addLayout(table_buttons)

        self.points_group.setLayout(points_layout)
        self.points_group.setVisible(False)  # Скрыта по умолчанию
        layout.addWidget(self.points_group)

        # Результирующая PROJ-строка
        proj_group = QGroupBox("Результирующая проекция")
        proj_layout = QVBoxLayout()

        self.proj_text = QTextEdit()
        self.proj_text.setReadOnly(True)
        self.proj_text.setMaximumHeight(100)
        self.proj_text.setPlainText("Нажмите 'Рассчитать' для создания проекции...")
        proj_layout.addWidget(self.proj_text)

        proj_group.setLayout(proj_layout)
        layout.addWidget(proj_group)

        # Кнопки
        buttons_layout = QHBoxLayout()

        self.calculate_button = QPushButton("Рассчитать")
        self.calculate_button.clicked.connect(self.on_calculate_clicked)
        buttons_layout.addWidget(self.calculate_button)

        self.apply_button = QPushButton("Применить")
        self.apply_button.clicked.connect(self.on_apply_clicked)
        self.apply_button.setEnabled(False)
        buttons_layout.addWidget(self.apply_button)

        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(self.cancel_button)

        layout.addLayout(buttons_layout)

        self.setLayout(layout)

    def calculate_optimal_parameters(self):
        """Расчет оптимальных параметров проекции"""
        if not self.object_bounds or not self.object_center:
            return

        # Импортируем оптимизатор
        from .Fsm_0_5_3_projection_optimizer import ProjectionOptimizer

        optimizer = ProjectionOptimizer()

        # Type guards для Pylance
        min_lon, max_lon = self.object_bounds
        center_lon, center_lat = self.object_center

        # Расчет центрального меридиана - середина extent объекта
        central_meridian = (min_lon + max_lon) / 2
        log_info(f"Fsm_0_5_2: Центральный меридиан (lon_0): {central_meridian:.6f}°")

        # Расчет протяженности объекта
        extent_km = (max_lon - min_lon) * 111.32 * math.cos(math.radians(center_lat))
        log_info(f"Fsm_0_5_2: Протяженность объекта: {extent_km:.1f} км по долготе")

        # Расчет масштабного коэффициента с автооптимизацией
        scale_factor = optimizer.calculate_optimal_scale_factor(extent_km / 2)
        log_info(f"Fsm_0_5_2: Масштабный коэффициент (k_0): {scale_factor:.8f}")

        # Расчет ожидаемого искажения
        distortion_ppm = optimizer.estimate_distortion(
            central_meridian, scale_factor,
            (min_lon, max_lon), center_lat
        )
        log_info(f"Fsm_0_5_2: Ожидаемое искажение: {distortion_ppm:.2f} ppm")

        # Извлекаем базовые параметры из текущей CRS проекта
        project_crs = QgsProject.instance().crs()
        base_proj = project_crs.toProj()

        # Парсим lat_0, x_0, y_0, ellps, towgs84 из базовой CRS
        import re
        lat_0 = 0.0
        x_0_old = 500000.0  # fallback значение
        y_0_old = 0.0  # fallback значение

        # Извлекаем lon_0 из базовой CRS для пересчета смещений
        lon_0_old = 0.0
        if "+lon_0=" in base_proj:
            match = re.search(r'\+lon_0=([\d\.\-]+)', base_proj)
            if match:
                lon_0_old = float(match.group(1))

        if "+lat_0=" in base_proj:
            match = re.search(r'\+lat_0=([\d\.\-]+)', base_proj)
            if match:
                lat_0 = float(match.group(1))

        if "+x_0=" in base_proj:
            match = re.search(r'\+x_0=([\d\.\-]+)', base_proj)
            if match:
                x_0_old = float(match.group(1))

        if "+y_0=" in base_proj:
            match = re.search(r'\+y_0=([\d\.\-]+)', base_proj)
            if match:
                y_0_old = float(match.group(1))

        # Парсим ellps и towgs84 для пересчета
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

        log_info(f"Fsm_0_5_2: Параметры из базовой CRS:")
        log_info(f"  - lon_0: {lon_0_old:.6f}° (старый центральный меридиан)")
        log_info(f"  - lat_0: {lat_0:.1f}° (из базовой CRS)")
        log_info(f"  - x_0: {x_0_old:.1f} м (старое смещение)")
        log_info(f"  - y_0: {y_0_old:.1f} м (старое смещение)")

        # ПЕРЕСЧЕТ x_0 и y_0 для компенсации изменения lon_0
        # Проверяем расширенный режим
        if self.advanced_mode and all(p is not None for p in self.point_pairs):
            # РАСШИРЕННЫЙ РЕЖИМ: калибровка по контрольным точкам
            log_info("Fsm_0_5_2: Расширенный режим - калибровка по 4 парам контрольных точек")

            try:
                from pyproj import Transformer

                # Создаем временную PROJ-строку новой проекции без смещений
                temp_proj = (
                    f"+proj=tmerc +lat_0={lat_0} +lon_0={central_meridian} +k_0={scale_factor} "
                    f"+x_0=0 +y_0=0 "
                )
                if ellps_param:
                    temp_proj += f"{ellps_param} "
                if towgs84_param:
                    temp_proj += f"{towgs84_param} "
                temp_proj += "+units=m +no_defs"

                # Вычисляем смещения для каждой пары
                delta_x_list = []
                delta_y_list = []

                for i, pair in enumerate(self.point_pairs):
                    if pair is None:
                        continue

                    wrong_point, correct_point = pair

                    # wrong_point - координаты в текущей МСК проекции
                    # correct_point - эталонные координаты (например, из WFS в МСК)

                    # Вычисляем где "неправильная" точка окажется в новой проекции
                    # Преобразуем из старой CRS → WGS84 → новая CRS
                    from qgis.core import QgsCoordinateTransform

                    # Старая CRS → WGS84
                    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
                    transform_to_wgs = QgsCoordinateTransform(project_crs, wgs84, QgsProject.instance())
                    wrong_in_wgs = transform_to_wgs.transform(wrong_point)

                    # WGS84 → Новая CRS (через pyproj, т.к. это кастомная CRS)
                    transformer_new = Transformer.from_crs("EPSG:4326", temp_proj, always_xy=True)
                    x_new, y_new = transformer_new.transform(wrong_in_wgs.x(), wrong_in_wgs.y())

                    # Смещение = правильная координата - координата в новой CRS
                    delta_x = correct_point.x() - x_new
                    delta_y = correct_point.y() - y_new

                    delta_x_list.append(delta_x)
                    delta_y_list.append(delta_y)

                    log_info(f"  Пара {i+1}: Δx={delta_x:.2f} м, Δy={delta_y:.2f} м")

                # Вычисляем среднее смещение
                x_0 = sum(delta_x_list) / len(delta_x_list)
                y_0 = sum(delta_y_list) / len(delta_y_list)

                # Вычисляем СКО (RMS)
                rms_x = math.sqrt(sum((dx - x_0)**2 for dx in delta_x_list) / len(delta_x_list))
                rms_y = math.sqrt(sum((dy - y_0)**2 for dy in delta_y_list) / len(delta_y_list))
                rms = math.sqrt(rms_x**2 + rms_y**2)

                log_info(f"Fsm_0_5_2: Среднее смещение: x_0={x_0:.2f} м, y_0={y_0:.2f} м")
                log_info(f"Fsm_0_5_2: СКО (RMS): {rms:.2f} м")

            except ImportError:
                log_error("Fsm_0_5_2: pyproj не установлен - расчет x_0/y_0 невозможен")
                QMessageBox.critical(
                    self,
                    "Ошибка",
                    "Библиотека pyproj не установлена.\nУстановите через меню Плагины -> F_5_1 Установка зависимостей."
                )
                return
            except Exception as e:
                log_error(f"Fsm_0_5_2: Ошибка расширенного режима: {e}")
                QMessageBox.warning(
                    self,
                    "Ошибка расчета",
                    f"Ошибка при расчете смещений: {e}\nИспользуются старые значения."
                )
                x_0 = x_0_old
                y_0 = y_0_old

        else:
            # ОБЫЧНЫЙ РЕЖИМ: опорная точка - центр extent
            try:
                from pyproj import Transformer

                # Создаем временную PROJ-строку новой проекции без смещений
                temp_proj = (
                    f"+proj=tmerc +lat_0={lat_0} +lon_0={central_meridian} +k_0={scale_factor} "
                    f"+x_0=0 +y_0=0 "
                )
                if ellps_param:
                    temp_proj += f"{ellps_param} "
                if towgs84_param:
                    temp_proj += f"{towgs84_param} "
                temp_proj += "+units=m +no_defs"

                # Опорная точка - центр extent
                wgs84 = "EPSG:4326"

                # Координаты центра в старой CRS
                transformer_old = Transformer.from_crs(wgs84, base_proj, always_xy=True)
                x_old, y_old = transformer_old.transform(center_lon, center_lat)

                # Координаты центра в новой CRS (без смещений)
                transformer_new = Transformer.from_crs(wgs84, temp_proj, always_xy=True)
                x_new, y_new = transformer_new.transform(center_lon, center_lat)

                # Вычисляем новые смещения чтобы центр extent имел те же координаты
                # x_old уже включает старое смещение, x_new не включает (=0)
                # Поэтому разница дает нужное новое смещение
                x_0 = x_old - x_new
                y_0 = y_old - y_new

                log_info(f"Fsm_0_5_2: Пересчет false easting/northing для компенсации изменения lon_0:")
                log_info(f"  - Опорная точка (центр extent): {center_lon:.6f}°E, {center_lat:.6f}°N")
                log_info(f"  - Координаты в старой CRS (lon_0={lon_0_old:.2f}°): x={x_old:.2f} м, y={y_old:.2f} м")
                log_info(f"  - Координаты в новой CRS (lon_0={central_meridian:.6f}°, x_0=0, y_0=0): x={x_new:.2f} м, y={y_new:.2f} м")
                log_info(f"  - Требуемое смещение для сохранения координат: x_0={x_0:.2f} м, y_0={y_0:.2f} м")
                log_info(f"  - Изменение смещения: Δx_0={x_0 - x_0_old:.2f} м, Δy_0={y_0 - y_0_old:.2f} м")

            except ImportError:
                log_error("Fsm_0_5_2: pyproj не установлен - расчет x_0/y_0 невозможен")
                QMessageBox.critical(
                    self,
                    "Ошибка",
                    "Библиотека pyproj не установлена.\nУстановите через меню Плагины -> F_5_1 Установка зависимостей."
                )
                return
            except Exception as e:
                log_error(f"Fsm_0_5_2: Ошибка пересчета x_0/y_0: {e}")
                QMessageBox.warning(
                    self,
                    "Ошибка расчета",
                    f"Ошибка при расчете смещений: {e}\nИспользуются старые значения."
                )
                x_0 = x_0_old
                y_0 = y_0_old

        # Сохраняем параметры
        self.optimal_params = {
            "lon_0": central_meridian,
            "lat_0": lat_0,
            "k_0": scale_factor,
            "x_0": x_0,
            "y_0": y_0
        }

        # Обновляем PROJ-строку
        self.update_proj_string()
        
    def update_proj_string(self):
        """Обновление PROJ-строки"""
        if not self.optimal_params:
            return

        # Получаем текущую CRS проекта для базовых параметров
        project_crs = QgsProject.instance().crs()
        base_proj = project_crs.toProj()

        log_info(f"Fsm_0_5_2: Базовая CRS проекта: {project_crs.description()}")
        log_info(f"Fsm_0_5_2: Базовая PROJ-строка: {base_proj}")

        # Извлекаем параметры эллипсоида и трансформации из базовой CRS
        ellps_param = ""
        towgs84_param = ""
        datum_param = ""
        units_param = "+units=m"

        # Парсим базовую PROJ-строку
        import re
        if "+ellps=" in base_proj:
            match = re.search(r'\+ellps=(\S+)', base_proj)
            if match:
                ellps_param = f"+ellps={match.group(1)}"
                log_info(f"Fsm_0_5_2: Использован эллипсоид: {match.group(1)}")

        if "+towgs84=" in base_proj:
            match = re.search(r'\+towgs84=([\d\.,\-]+)', base_proj)
            if match:
                towgs84_param = f"+towgs84={match.group(1)}"
                log_info(f"Fsm_0_5_2: Использованы параметры towgs84: {match.group(1)}")

        if "+datum=" in base_proj:
            match = re.search(r'\+datum=(\S+)', base_proj)
            if match:
                datum_param = f"+datum={match.group(1)}"
                log_info(f"Fsm_0_5_2: Использован датум: {match.group(1)}")

        # Формируем новую PROJ-строку с оптимизированными параметрами
        proj_string = (
            f"+proj=tmerc "
            f"+lat_0={self.optimal_params['lat_0']:.1f} "
            f"+lon_0={self.optimal_params['lon_0']:.6f} "
            f"+k_0={self.optimal_params['k_0']:.8f} "
            f"+x_0={self.optimal_params['x_0']:.1f} "
            f"+y_0={self.optimal_params['y_0']:.1f} "
        )

        # Добавляем параметры эллипсоида/датума
        if datum_param:
            proj_string += f"{datum_param} "
        elif ellps_param:
            proj_string += f"{ellps_param} "

        # Добавляем параметры трансформации
        if towgs84_param:
            proj_string += f"{towgs84_param} "

        proj_string += f"{units_param} +no_defs"

        log_info(f"Fsm_0_5_2: Результирующая PROJ-строка: {proj_string}")

        self.proj_text.setPlainText(proj_string)
        
    def on_calculate_clicked(self):
        """Расчет оптимальных параметров"""
        self.calculate_optimal_parameters()

        if self.optimal_params:
            self.apply_button.setEnabled(True)

            QMessageBox.information(
                self,
                "Расчет завершен",
                f"Оптимальные параметры рассчитаны.\n\n"
                f"Детальная информация выведена в лог QGIS.\n"
                f"Нажмите 'Применить' для создания и применения проекции к проекту."
            )

    def on_apply_clicked(self):
        """Применение кастомной проекции к проекту"""
        if not self.optimal_params:
            return

        proj_string = self.proj_text.toPlainText()

        # Сначала создаём временную CRS из PROJ для получения WKT2
        temp_crs = QgsCoordinateReferenceSystem()
        if not temp_crs.createFromProj(proj_string):
            QMessageBox.critical(self, "Ошибка", "Не удалось создать проекцию из PROJ строки")
            return

        # Конвертируем в WKT2 (ISO 19162:2019) для lossless сохранения
        wkt2_string = temp_crs.toWkt(Qgis.CrsWktVariant.Wkt2_2019)
        log_info(f"Fsm_0_5_2: Конвертирован PROJ -> WKT2 (первые 200 символов): {wkt2_string[:200]}...")

        # Создаём финальную CRS из WKT2
        new_crs = QgsCoordinateReferenceSystem.fromWkt(wkt2_string)
        if not new_crs.isValid():
            # Fallback: используем PROJ напрямую
            log_warning("Fsm_0_5_2: WKT2 не сработал, используем PROJ fallback")
            new_crs = temp_crs

        # Генерируем имя
        crs_name = self.generate_crs_name()

        # Сохраняем как USER CRS через Registry API (QGIS 3.18+, WKT формат)
        registry = QgsApplication.coordinateReferenceSystemRegistry()
        srsid = registry.addUserCrs(new_crs, crs_name, Qgis.CrsDefinitionFormat.Wkt)

        if srsid == -1:
            QMessageBox.critical(self, "Ошибка", "Не удалось сохранить проекцию")
            return

        # Очищаем кэш CRS
        QgsCoordinateReferenceSystem.invalidateCache()

        # Получаем сохранённую CRS по USER ID
        saved_crs = QgsCoordinateReferenceSystem(f"USER:{srsid}")

        # Применяем к проекту
        self.parent_tool.apply_crs_to_all_layers(saved_crs)

        log_success(f"Fsm_0_5_2: Создана и применена кастомная проекция '{crs_name}'")
        log_info(f"Fsm_0_5_2: Координаты объектов сохранены (setCrs), изменена система координат")

        QMessageBox.information(
            self,
            "Успех",
            f"Кастомная проекция '{crs_name}' создана и применена к проекту.\n\n"
            f"Координаты объектов сохранены, изменена система координат (setCrs)."
        )

        self.accept()
        
    def generate_crs_name(self):
        """Генерация имени для кастомной проекции"""
        # Читаем рабочее название проекта из метаданных
        project = QgsProject.instance()
        working_name = "Проект"

        project_path = project.absolutePath()
        if project_path:
            import os
            from Daman_QGIS.managers.M_19_project_structure_manager import get_project_structure_manager
            structure_manager = get_project_structure_manager()
            structure_manager.project_root = project_path
            gpkg_path = structure_manager.get_gpkg_path(create=False)

            if gpkg_path and os.path.exists(gpkg_path):
                from Daman_QGIS.database.project_db import ProjectDB
                try:
                    db = ProjectDB(gpkg_path)
                    metadata = db.get_metadata('1_0_working_name')
                    if metadata and metadata.get('value'):
                        working_name = metadata['value']
                except Exception as e:
                    log_warning(f"Fsm_0_5_2: Не удалось прочитать рабочее название: {e}")

        # Формат: {РабочееНазвание}_Custom_TM_{lon_0}
        lon_0 = self.optimal_params['lon_0']
        return f"{working_name}_Custom_TM_{lon_0:.2f}"

    def auto_load_default_layer(self):
        """Автоматическая загрузка extent из слоя L_1_1_1_Границы_работ"""
        target_layer_name = "L_1_1_1_Границы_работ"

        # Ищем слой по имени
        layers = QgsProject.instance().mapLayersByName(target_layer_name)

        if not layers:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Слой '{target_layer_name}' не найден в проекте.\n\n"
                f"Для создания кастомной проекции необходим слой с границами работ."
            )
            log_error(f"Fsm_0_5_2: Слой {target_layer_name} не найден")
            return

        # Берем первый найденный слой
        layer = layers[0]

        if not isinstance(layer, QgsVectorLayer):
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Слой '{target_layer_name}' не является векторным слоем."
            )
            log_error(f"Fsm_0_5_2: Слой {target_layer_name} не векторный")
            return

        # Получаем границы в WGS84
        source_crs = layer.crs()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")

        if source_crs != wgs84:
            from qgis.core import QgsCoordinateTransform
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

        log_info(f"Fsm_0_5_2: Автоматически загружены границы из слоя {target_layer_name}")
        log_info(f"Fsm_0_5_2: Мин. долгота: {min_lon:.6f}°, Макс. долгота: {max_lon:.6f}°")
        log_info(f"Fsm_0_5_2: Центр широты: {center_lat:.6f}°")

        # Автоматически рассчитываем параметры
        self.calculate_optimal_parameters()

    # ====== ОБРАБОТЧИКИ РАСШИРЕННОГО РЕЖИМА ======

    def on_advanced_mode_toggled(self, state):
        """Переключение расширенного режима"""
        self.advanced_mode = (state == Qt.Checked)
        self.points_group.setVisible(self.advanced_mode)

        if self.advanced_mode:
            # Активируем map tool для захвата точек
            self.parent_tool.activate_map_tool()
            log_info("Fsm_0_5_2: Расширенный режим активирован - калибровка по контрольным точкам")
        else:
            # Деактивируем map tool
            if hasattr(self.parent_tool, 'deactivate_map_tool'):
                self.parent_tool.deactivate_map_tool()
            log_info("Fsm_0_5_2: Расширенный режим деактивирован")

    def on_table_cell_changed(self, item):
        """Обработка изменения ячейки таблицы"""
        if not self.advanced_mode:
            return

        row = item.row()
        col = item.column()

        # Пропускаем колонку номера
        if col == 0:
            return

        try:
            # Читаем значения из таблицы
            wrong_x = self.points_table.item(row, 1)
            wrong_y = self.points_table.item(row, 2)
            correct_x = self.points_table.item(row, 3)
            correct_y = self.points_table.item(row, 4)

            # Проверяем, заполнена ли пара полностью
            if all([wrong_x and wrong_x.text(), wrong_y and wrong_y.text(),
                    correct_x and correct_x.text(), correct_y and correct_y.text()]):

                # Создаем точки
                wrong_point = QgsPointXY(float(wrong_x.text()), float(wrong_y.text()))
                correct_point = QgsPointXY(float(correct_x.text()), float(correct_y.text()))

                # Сохраняем пару
                self.point_pairs[row] = (wrong_point, correct_point)
                log_info(f"Fsm_0_5_2: Пара {row+1} обновлена из таблицы")
            else:
                # Неполная пара - удаляем
                self.point_pairs[row] = None

        except ValueError:
            # Неверное значение
            self.point_pairs[row] = None

    def on_table_selection_changed(self):
        """Обработка изменения выбранной ячейки"""
        if not self.advanced_mode:
            return

        selected = self.points_table.selectedItems()
        if not selected:
            self.clear_row_button.setEnabled(False)
            self.current_selection_pair = None
            self.current_selection_point = None
            return

        item = selected[0]
        row = item.row()
        col = item.column()

        self.clear_row_button.setEnabled(True)

        # Определяем текущую пару и тип точки
        self.current_selection_pair = row
        if col in [1, 2]:  # Неправильные координаты
            self.current_selection_point = 'wrong'
        elif col in [3, 4]:  # Правильные координаты
            self.current_selection_point = 'correct'
        else:
            self.current_selection_point = None

    def on_clear_row_clicked(self):
        """Очистка выбранной строки"""
        if not self.advanced_mode:
            return

        selected = self.points_table.selectedItems()
        if not selected:
            return

        row = selected[0].row()

        # Очищаем ячейки
        for col in range(1, 5):
            self.points_table.setItem(row, col, QTableWidgetItem(""))

        # Очищаем данные
        self.point_pairs[row] = None
        log_info(f"Fsm_0_5_2: Пара {row+1} очищена")

    def on_clear_all_points_clicked(self):
        """Очистка всех точек"""
        if not self.advanced_mode:
            return

        # Очищаем таблицу
        for row in range(4):
            for col in range(1, 5):
                self.points_table.setItem(row, col, QTableWidgetItem(""))

        # Очищаем данные
        self.point_pairs = [None, None, None, None]
        log_info("Fsm_0_5_2: Все пары очищены")

    def add_point_from_map(self, point: QgsPointXY):
        """Добавление точки с карты (вызывается из map tool)"""
        if not self.advanced_mode:
            return

        if self.current_selection_pair is None or self.current_selection_point is None:
            QMessageBox.warning(
                self,
                "Выберите ячейку",
                "Сначала выберите ячейку в таблице, куда добавить координату."
            )
            return

        row = self.current_selection_pair

        # Определяем колонки для записи
        if self.current_selection_point == 'wrong':
            col_x, col_y = 1, 2
        else:  # 'correct'
            col_x, col_y = 3, 4

        # Записываем координаты в таблицу
        self.points_table.setItem(row, col_x, QTableWidgetItem(f"{point.x():.2f}"))
        self.points_table.setItem(row, col_y, QTableWidgetItem(f"{point.y():.2f}"))

        log_info(f"Fsm_0_5_2: Точка добавлена в пару {row+1} ({self.current_selection_point})")

        # Переключаемся на следующую ячейку
        if self.current_selection_point == 'wrong':
            # Переходим к правильной точке этой же пары
            self.points_table.setCurrentCell(row, col_x + 2)
        else:
            # Переходим к следующей паре
            next_row = (row + 1) % 4
            self.points_table.setCurrentCell(next_row, 1)
