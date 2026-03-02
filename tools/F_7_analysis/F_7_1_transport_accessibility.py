# -*- coding: utf-8 -*-
"""
F_7_1: Транспортная доступность - Анализ транспортной и пешей
доступности с поддержкой ГОЧС сценариев.

UI функция: диалог с 3 вкладками (Изохроны / Маршруты / ГОЧС).
Все вычисления делегируются M_41 IsochroneTransportManager.
"""

from typing import Optional, Any

from Daman_QGIS.core.base_tool import BaseTool
from Daman_QGIS.utils import log_info, log_error


class F_7_1_TransportAccessibility(BaseTool):
    """Анализ транспортной доступности и ГОЧС сценариев."""

    def __init__(self, iface: Any) -> None:
        super().__init__(iface)
        self._m41 = None

    def create_dialog(self) -> Any:
        """Создать диалог транспортной доступности."""
        log_info("F_7_1: Создание диалога")

        if self._m41 is None:
            from Daman_QGIS.managers.processing.M_41_isochrone_transport_manager import (
                IsochroneTransportManager,
            )
            self._m41 = IsochroneTransportManager(self.iface)

        from .submodules.Fsm_7_1_1_dialog import Fsm_7_1_1_Dialog

        return Fsm_7_1_1_Dialog(
            iface=self.iface,
            m41=self._m41,
            parent=self.iface.mainWindow(),
        )
