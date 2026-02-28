# -*- coding: utf-8 -*-
"""
F_0_6_CoordinateTransform - Трансформация координат слоя по контрольным точкам

Пересчёт координат (геометрий) выбранного слоя для стыковки
с вершинами смежных слоёв. CRS не затрагивается.

Методы: Offset (2P), Helmert2D (4P), Affine (6P).
Минимум: 4 пары контрольных точек.
Точность: 0.01м (кадастровая).
"""

import os
from typing import Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsProject,
    QgsPointXY,
    QgsVectorLayer,
    QgsSnappingConfig,
    QgsTolerance,
    QgsPointLocator,
    Qgis,
)
from qgis.gui import QgsMapToolEmitPoint, QgsSnapIndicator

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.constants import MESSAGE_INFO_DURATION
from Daman_QGIS.utils import log_info, log_error, log_warning


class F_0_6_CoordinateTransform(BaseTool):
    """
    Трансформация координат слоя по контрольным точкам.

    Workflow:
    1. Пользователь выбирает изменяемый слой
    2. Кликает пары точек: исходная (на целевом слое) -> целевая (на любом другом)
    3. Рассчитывает трансформацию (auto-select лучший метод)
    4. Применяет к слою с backup и округлением 0.01м
    """

    def __init__(self, iface):
        """Инициализация инструмента."""
        super().__init__(iface)
        self.dialog = None
        self.map_tool = None
        self._target_layer: Optional[QgsVectorLayer] = None

    @property
    def name(self) -> str:
        return "F_0_6_Трансформация координат"

    @property
    def icon(self) -> QIcon:
        plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        return QIcon(os.path.join(plugin_dir, "resources", "icons", "icon.svg"))

    def run(self) -> None:
        """Запуск инструмента."""
        # Проверка открытого проекта
        if not self.check_project_opened():
            return

        # Проверка наличия векторных слоёв
        vector_layers = [
            layer for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer)
        ]
        if not vector_layers:
            self.iface.messageBar().pushMessage(
                "Ошибка",
                "В проекте нет векторных слоёв",
                level=Qgis.MessageLevel.Critical,
                duration=MESSAGE_INFO_DURATION
            )
            log_error("F_0_6: В проекте нет векторных слоёв")
            return

        # Создание и показ диалога
        self.create_dialog()

    def create_dialog(self) -> None:
        """Создание диалога трансформации."""
        from .submodules.Fsm_0_6_1_transform_dialog import CoordinateTransformDialog

        self.dialog = CoordinateTransformDialog(self.iface, self)

        # Позиционируем диалог сбоку
        self._position_dialog_aside()

        # Показываем диалог
        self.dialog.show()

        # Активируем инструмент захвата точек
        self.activate_map_tool()

    def _position_dialog_aside(self) -> None:
        """Позиционирование диалога сбоку от главного окна."""
        if not self.dialog:
            return

        main_window = self.iface.mainWindow()
        main_geometry = main_window.geometry()

        dialog_x = main_geometry.x() + main_geometry.width() - self.dialog.width() - 50
        dialog_y = main_geometry.y() + 100

        self.dialog.move(dialog_x, dialog_y)

    def activate_map_tool(self) -> None:
        """Активация инструмента захвата точек."""
        if self.map_tool:
            self.iface.mapCanvas().unsetMapTool(self.map_tool)

        self.map_tool = CoordinateTransformTool(self.iface.mapCanvas(), self)
        self.iface.mapCanvas().setMapTool(self.map_tool)

    def deactivate_map_tool(self) -> None:
        """Деактивация инструмента захвата точек."""
        if self.map_tool:
            self.iface.mapCanvas().unsetMapTool(self.map_tool)
            self.map_tool = None

        # Восстанавливаем стандартный инструмент панорамирования
        self.iface.actionPan().trigger()

    @property
    def target_layer(self) -> Optional[QgsVectorLayer]:
        """Текущий целевой слой (изменяемый)."""
        return self._target_layer

    @target_layer.setter
    def target_layer(self, layer: Optional[QgsVectorLayer]) -> None:
        """Установить целевой слой."""
        self._target_layer = layer
        if layer:
            log_info(f"F_0_6: Целевой слой: {layer.name()}")


class CoordinateTransformTool(QgsMapToolEmitPoint):
    """
    MapTool для захвата пар контрольных точек.

    Фильтрация слоёв через post-snap валидацию:
    - Исходная точка: только на целевом (изменяемом) слое
    - Целевая точка: на любом другом слое (reference)

    Координаты извлекаются из геометрии слоя (native), не через OTF.
    """

    def __init__(self, canvas, parent_tool: F_0_6_CoordinateTransform):
        super().__init__(canvas)
        self.canvas = canvas
        self.parent_tool = parent_tool

        # Snap indicator
        self.snap_indicator = QgsSnapIndicator(canvas)

        # Сохраняем текущую конфигурацию привязки
        self.old_snapping_config = None

        # Курсор
        self.setCursor(Qt.CursorShape.CrossCursor)

    def activate(self):
        """Активация инструмента."""
        super().activate()
        self._setup_snapping()

    def _setup_snapping(self):
        """Настройка привязки к вершинам всех слоёв."""
        project = QgsProject.instance()
        config = project.snappingConfig()

        # Сохраняем старую конфигурацию
        self.old_snapping_config = QgsSnappingConfig(config)

        # Привязка к вершинам, все слои, 10px
        config.setEnabled(True)
        config.setType(QgsSnappingConfig.VertexFlag)
        config.setMode(QgsSnappingConfig.AllLayers)
        config.setTolerance(10)
        config.setUnits(QgsTolerance.Pixels)

        project.setSnappingConfig(config)

    def canvasMoveEvent(self, event):
        """Показ индикатора привязки при движении мыши."""
        match = self.canvas.snappingUtils().snapToMap(event.pos())
        self.snap_indicator.setMatch(match)

    def canvasReleaseEvent(self, event):
        """
        Обработка клика на карте.

        Извлекает native координаты вершины из геометрии слоя.
        Выполняет post-snap фильтрацию: проверяет что вершина
        принадлежит нужному слою (исходная -> target, целевая -> any other).
        """
        match = self.canvas.snappingUtils().snapToMap(event.pos())

        if not match.isValid():
            return

        # Проверяем что есть диалог и целевой слой
        dialog = self.parent_tool.dialog
        target_layer = self.parent_tool.target_layer

        if not dialog or not target_layer:
            return

        # Получаем слой, к которому привязалась точка
        snapped_layer = match.layer()
        if not snapped_layer or not isinstance(snapped_layer, QgsVectorLayer):
            return

        # Определяем тип точки из диалога
        selecting_source = dialog.is_selecting_source()

        # Post-snap фильтрация слоёв
        if selecting_source:
            # Исходная точка: ТОЛЬКО на целевом (изменяемом) слое
            if snapped_layer.id() != target_layer.id():
                self.parent_tool.iface.messageBar().pushMessage(
                    "Подсказка",
                    f"Исходная точка должна быть на слое '{target_layer.name()}'",
                    level=Qgis.MessageLevel.Info,
                    duration=3
                )
                return
        else:
            # Целевая точка: на ЛЮБОМ другом слое (не целевом)
            if snapped_layer.id() == target_layer.id():
                self.parent_tool.iface.messageBar().pushMessage(
                    "Подсказка",
                    "Целевая точка должна быть на другом слое (reference)",
                    level=Qgis.MessageLevel.Info,
                    duration=3
                )
                return

        # Извлекаем native координаты вершины из геометрии
        native_coords = None
        try:
            feature = snapped_layer.getFeature(match.featureId())
            if feature.isValid() and feature.hasGeometry():
                geom = feature.geometry()
                vertex_idx = match.vertexIndex()
                if vertex_idx >= 0:
                    vertex = geom.vertexAt(vertex_idx)
                    native_coords = QgsPointXY(vertex.x(), vertex.y())
        except Exception as e:
            log_warning(f"F_0_6: Не удалось извлечь native координаты: {e}")

        if native_coords is None:
            # Fallback: координаты из snap match (project CRS)
            native_coords = QgsPointXY(match.point())
            log_warning("F_0_6: Используются координаты из snap match (не native)")

        # Передаём точку в диалог
        dialog.set_point_from_map(native_coords, selecting_source)

    def deactivate(self):
        """Деактивация инструмента."""
        # Очищаем индикатор
        self.snap_indicator.setMatch(QgsPointLocator.Match())

        # Восстанавливаем старую конфигурацию привязки
        if self.old_snapping_config is not None:
            QgsProject.instance().setSnappingConfig(self.old_snapping_config)

        super().deactivate()
