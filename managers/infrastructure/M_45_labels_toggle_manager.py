# -*- coding: utf-8 -*-
"""
LabelsToggleManager - Глобальное переключение подписей

Обеспечивает:
- Toggle всех подписей на всех векторных слоях проекта
- Запоминание состояния (какие слои имели подписи до отключения)
- Восстановление подписей только на тех слоях, где они были
"""

__all__ = ['LabelsToggleManager']

from typing import Set

from qgis.PyQt.QtWidgets import QToolButton
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsVectorLayer

from Daman_QGIS.utils import log_info, log_warning


class LabelsToggleManager:
    """Глобальное включение/выключение подписей на всех слоях"""

    def __init__(self, iface):
        self.iface = iface
        self._labels_hidden: bool = False
        self._layers_with_labels: Set[str] = set()  # layer IDs где были подписи
        self._button: QToolButton | None = None

    def init_gui(self, toolbar) -> None:
        """Создает кнопку на тулбаре (вызывается после построения меню функций)"""
        toolbar.addSeparator()

        self._button = QToolButton()
        self._button.setText("Подписи")
        self._button.setToolTip("Скрыть/показать все подписи на карте")
        self._button.setCheckable(True)
        self._button.clicked.connect(self._toggle)
        toolbar.addWidget(self._button)

        log_info("M_45: Toggle подписей инициализирован")

    def _toggle(self) -> None:
        """Переключение состояния подписей"""
        if self._labels_hidden:
            self._show_labels()
        else:
            self._hide_labels()

    def _hide_labels(self) -> None:
        """Скрыть все подписи, запомнив где они были"""
        self._layers_with_labels.clear()

        for layer_id, layer in QgsProject.instance().mapLayers().items():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if layer.labelsEnabled():
                self._layers_with_labels.add(layer_id)
                layer.setLabelsEnabled(False)
                layer.triggerRepaint()

        self._labels_hidden = True
        if self._button:
            self._button.setChecked(True)

        count = len(self._layers_with_labels)
        log_info(f"M_45: Подписи скрыты на {count} слоях")

    def _show_labels(self) -> None:
        """Восстановить подписи только на тех слоях, где они были"""
        restored = 0
        for layer_id in self._layers_with_labels:
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer and isinstance(layer, QgsVectorLayer):
                layer.setLabelsEnabled(True)
                layer.triggerRepaint()
                restored += 1

        self._layers_with_labels.clear()
        self._labels_hidden = False
        if self._button:
            self._button.setChecked(False)

        log_info(f"M_45: Подписи восстановлены на {restored} слоях")

    def unload(self) -> None:
        """Очистка при выгрузке плагина"""
        if self._labels_hidden:
            self._show_labels()
        self._button = None
        self._layers_with_labels.clear()
