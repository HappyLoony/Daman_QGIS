# -*- coding: utf-8 -*-
"""
Субмодуль 4: Менеджер штриховок DXF

Содержит функциональность для:
- Применения штриховок SOLID к полигонам
- Применения паттернов ANSI31 и других стандартных штриховок
- Настройки параметров штриховки (масштаб, цвет)
"""

from typing import Dict, Any, List, Tuple

from Daman_QGIS.utils import log_warning, log_debug
from Daman_QGIS.constants import DXF_COLOR_BYLAYER


class DxfHatchManager:
    """Менеджер штриховок для DXF экспорта"""

    def __init__(self):
        """Инициализация менеджера штриховок"""
        pass

    def apply_hatch(self, msp, coords: List[Tuple[float, float]],
                   style: Dict[str, Any], dxf_attribs: dict):
        """
        Применение штриховки к полигону

        Args:
            msp: Пространство модели DXF
            coords: Координаты полигона [(x1, y1), (x2, y2), ...]
            style: Стиль со значениями:
                - hatch: тип штриховки ('SOLID', 'ANSI31', и т.д.)
                - hatch_scale: масштаб штриховки (по умолчанию 1.0)
            dxf_attribs: Атрибуты DXF со значениями:
                - color: цвет штриховки (256 = BYLAYER, 7 = белый/чёрный)
                - layer: имя слоя DXF
        """
        try:
            # Создаём объект штриховки с заданным цветом
            # DXF_COLOR_BYLAYER (256) = наследует цвет от слоя - используется по умолчанию
            hatch = msp.add_hatch(color=dxf_attribs.get('color', DXF_COLOR_BYLAYER))

            # Устанавливаем паттерн штриховки
            hatch_type = style.get('hatch', 'SOLID')
            if hatch_type == 'SOLID':
                hatch.set_pattern_fill('SOLID')
                log_debug(f"Fsm_dxf_4: Применена сплошная штриховка SOLID")
            elif hatch_type == 'ANSI31':
                hatch_scale = style.get('hatch_scale', 1.0)
                hatch.set_pattern_fill('ANSI31', scale=hatch_scale)
                log_debug(f"Fsm_dxf_4: Применена штриховка ANSI31 с масштабом {hatch_scale}")
            else:
                # Другие стандартные паттерны AutoCAD
                hatch_scale = style.get('hatch_scale', 1.0)
                hatch.set_pattern_fill(hatch_type, scale=hatch_scale)
                log_debug(f"Fsm_dxf_4: Применена штриховка {hatch_type} с масштабом {hatch_scale}")

            # Добавляем контур полигона как границу штриховки
            hatch.paths.add_polyline_path(coords, is_closed=True)

            # Настраиваем слой
            hatch.dxf.layer = dxf_attribs['layer']

        except Exception as e:
            log_warning(f"Fsm_dxf_4: Ошибка применения штриховки: {str(e)}")

    def create_solid_hatch(self, msp, coords: List[Tuple[float, float]],
                          layer_name: str, color: int = 7):
        """
        Упрощённый метод для создания сплошной штриховки

        Args:
            msp: Пространство модели DXF
            coords: Координаты полигона
            layer_name: Имя слоя DXF
            color: Цвет штриховки (по умолчанию 7 - белый/чёрный)
        """
        style = {'hatch': 'SOLID'}
        dxf_attribs = {'color': color, 'layer': layer_name}
        self.apply_hatch(msp, coords, style, dxf_attribs)

    def create_pattern_hatch(self, msp, coords: List[Tuple[float, float]],
                            layer_name: str, pattern: str = 'ANSI31',
                            scale: float = 1.0, color: int = 7):
        """
        Упрощённый метод для создания паттерновой штриховки

        Args:
            msp: Пространство модели DXF
            coords: Координаты полигона
            layer_name: Имя слоя DXF
            pattern: Имя паттерна ('ANSI31', 'ANSI32', и т.д.)
            scale: Масштаб штриховки
            color: Цвет штриховки
        """
        style = {'hatch': pattern, 'hatch_scale': scale}
        dxf_attribs = {'color': color, 'layer': layer_name}
        self.apply_hatch(msp, coords, style, dxf_attribs)
