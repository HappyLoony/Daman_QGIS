# -*- coding: utf-8 -*-
"""
Модуль управления стилями растровых слоев
Часть инструмента F_1_4_Запрос
"""

from qgis.core import QgsMessageLog, Qgis
from qgis.PyQt.QtGui import QColor
from Daman_QGIS.constants import PLUGIN_NAME
from Daman_QGIS.utils import log_info, log_warning, log_error


class StyleManager:
    """Менеджер стилей растровых слоев"""
    
    def __init__(self, iface):
        """Инициализация менеджера
        
        Args:
            iface: Интерфейс QGIS
        """
        self.iface = iface
    def apply_raster_style(self, layer, color_hex, saturation=None, grayscale=None,
                          brightness=None, contrast=None, blend_strength=50):
        """Применение стиля к растровому слою с тонировкой

        Args:
            layer: Растровый слой
            color_hex: Цвет тонировки в формате '#RRGGBB'
            saturation: Насыщенность (0-200, 100 - без изменений)
            grayscale: Режим обесцвечивания ('lightness', 'luminosity', 'average', None)
            brightness: Яркость (-100 до 100, 0 - без изменений)
            contrast: Контрастность (-100 до 100, 0 - без изменений)
            blend_strength: Интенсивность тонировки (0-100%)

        Returns:
            tuple: (success, error_msg)
        """
        if not layer or not layer.isValid():
            raise ValueError("Недействительный слой")

        # Получаем рендерер
        renderer = layer.renderer()
        if not renderer:
            raise ValueError("Рендерер не найден")

        # Настраиваем Hue/Saturation фильтр
        hueSaturationFilter = layer.hueSaturationFilter()

        # Устанавливаем насыщенность
        if saturation is not None:
            hueSaturationFilter.setSaturation(saturation - 100)  # QGIS использует диапазон -100 до 100

        # Настраиваем режим обесцвечивания
        if grayscale:
            hueSaturationFilter.setGrayscaleMode(self._get_grayscale_mode(grayscale))

        # Настраиваем яркость и контраст
        brightnessFilter = layer.brightnessFilter()
        if brightness is not None:
            brightnessFilter.setBrightness(brightness)
        if contrast is not None:
            brightnessFilter.setContrast(contrast)

        # Настраиваем тонировку (colorization)
        hueSaturationFilter.setColorizeOn(True)

        # Преобразуем цвет из hex в RGB
        color = QColor(color_hex)

        # Устанавливаем цвет тонировки
        hueSaturationFilter.setColorizeColor(color)

        # Устанавливаем интенсивность тонировки
        hueSaturationFilter.setColorizeStrength(blend_strength)

        # Применяем изменения
        layer.triggerRepaint()

        log_info(f"Fsm_1_4_7: Стиль применен к слою {layer.name()}")

        return True, None
    
    def _get_grayscale_mode(self, mode_str):
        """Получение режима обесцвечивания для QGIS
        
        Args:
            mode_str: Строковое представление режима
            
        Returns:
            Режим обесцвечивания QGIS
        """
        from qgis.core import QgsHueSaturationFilter
        
        modes = {
            'lightness': QgsHueSaturationFilter.GrayscaleLightness,
            'luminosity': QgsHueSaturationFilter.GrayscaleLuminosity,
            'average': QgsHueSaturationFilter.GrayscaleAverage,
            None: QgsHueSaturationFilter.GrayscaleOff
        }
        return modes.get(mode_str, QgsHueSaturationFilter.GrayscaleOff)
