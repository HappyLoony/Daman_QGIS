# -*- coding: utf-8 -*-
"""
Модуль создания слоев для легенды
Часть инструмента F_1_4_Запрос

ОБНОВЛЕНО: Модуль отключен, так как теперь используются векторные слои из okno_egrn
которые автоматически отображаются в легенде
"""

from qgis.core import QgsProject, QgsMessageLog, Qgis
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error


class LegendLayersCreator:
    """Создатель слоев для легенды (отключен)"""
    
    def __init__(self, iface):
        """Инициализация создателя
        
        Args:
            iface: Интерфейс QGIS
        """
        self.iface = iface
    
    def create_legend_layers(self):
        """Метод-заглушка для совместимости
        
        Векторные слои из okno_egrn автоматически отображаются в легенде,
        поэтому дополнительные legend слои больше не нужны.
        
        Returns:
            tuple: (success, error_msg)
        """
        log_info("Legend слои не создаются - используются векторные слои ЕГРН")
        
        return True, None
