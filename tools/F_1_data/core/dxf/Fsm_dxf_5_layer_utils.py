# -*- coding: utf-8 -*-
"""
Субмодуль 5: Утилиты для работы со слоями DXF

Содержит утилиты для:
- Получения информации о слоях из Base_layers.json
- Определения нужен ли блок для слоя
- Получения стилей AutoCAD
- Добавления типов линий в документ DXF
"""

from typing import Optional, Dict, Any
from qgis.core import QgsVectorLayer

from Daman_QGIS.utils import log_info, log_warning, log_error, log_debug


class DxfLayerUtils:
    """Утилиты для работы со слоями и стилями DXF"""

    def __init__(self, ref_managers, style_manager=None):
        """
        Инициализация утилит слоёв

        Args:
            ref_managers: Reference managers для доступа к базам данных
            style_manager: Менеджер стилей AutoCAD (опционально)
        """
        self.ref_managers = ref_managers
        self.style_manager = style_manager

    def get_layer_info_from_base(self, full_name: str) -> Optional[Dict[str, Any]]:
        """
        Получить информацию о слое из Base_layers.json по full_name

        Args:
            full_name: Полное имя слоя (например, "Le_2_1_1_1_Выборка_ЗУ")

        Returns:
            Словарь с данными слоя или None
        """
        try:
            # Получаем данные слоя через layer manager
            layer_data = self.ref_managers.layer.get_layer_by_full_name(full_name)
            return layer_data
        except Exception as e:
            log_warning(f"Fsm_dxf_5: Не удалось получить данные слоя {full_name}: {str(e)}")
            return None

    def should_use_blocks_for_layer(self, full_name: str, force_blocks: bool = False) -> bool:
        """
        Определить нужно ли экспортировать слой с использованием блоков (BLOCK + атрибуты)

        БЛОКИ используются для:
        - ЗУ (земельные участки): слои с full_name содержащие "WFS_ЗУ" или "Выборка_ЗУ"
        - ОКС (объекты капитального строительства): слои с "WFS_ОКС" или "Выборка_ОКС"
        - ЗОУИТ (зоны с особыми условиями): слои с "ЗОУИТ" в названии
        - Нарезка ЗПР (для П_ОЗУ): слои Le_3_1_, Le_3_2_, Le_3_5_, Le_3_6_, Le_3_7_ (полигоны)
          НО НЕ для точек (Le_3_8_) - они экспортируются как простая геометрия

        ВСЕ ОСТАЛЬНЫЕ СЛОИ экспортируются как простая геометрия без блоков.

        Args:
            full_name: Полное имя слоя из Base_layers.json
            force_blocks: Принудительно использовать блоки (для специальных случаев)

        Returns:
            True если нужны блоки, False если простая геометрия
        """
        if not full_name:
            return False

        if force_blocks:
            log_debug(f"Fsm_dxf_5: Слой {full_name} будет экспортирован с блоками (force_blocks=True)")
            return True

        # Ключевые слова для определения слоев с блоками
        block_keywords = [
            'WFS_ЗУ',           # WFS земельные участки
            'Выборка_ЗУ',      # Выборка земельных участков
            'WFS_ОКС',         # WFS объекты капстроительства
            'Выборка_ОКС',     # Выборка ОКС
            'ЗОУИТ'            # Зоны с особыми условиями использования территории
        ]

        # Проверяем наличие ключевых слов в имени слоя
        for keyword in block_keywords:
            if keyword in full_name:
                log_debug(f"Fsm_dxf_5: Слой {full_name} будет экспортирован с блоками (найдено: {keyword})")
                return True

        # П_ОЗУ: слои нарезки ЗПР экспортируются как блоки (полигоны)
        # НО НЕ слои точек (Le_3_8_) - они остаются простой геометрией
        pozu_polygon_prefixes = ['Le_3_1_', 'Le_3_2_', 'Le_3_5_', 'Le_3_6_', 'Le_3_7_']
        for prefix in pozu_polygon_prefixes:
            if full_name.startswith(prefix):
                log_debug(f"Fsm_dxf_5: Слой {full_name} (П_ОЗУ нарезка) будет экспортирован с блоками")
                return True

        log_debug(f"Fsm_dxf_5: Слой {full_name} будет экспортирован как простая геометрия (без блоков)")
        return False

    def get_layer_style(self, layer: QgsVectorLayer) -> Dict[str, Any]:
        """
        Получение стиля AutoCAD для слоя

        Args:
            layer: Слой QGIS

        Returns:
            Словарь со стилем AutoCAD
        """
        # Если есть менеджер стилей, используем его
        if self.style_manager:
            style = self.style_manager.get_autocad_attributes(layer)
            if style:
                # Добавляем глобальную ширину если её нет
                if 'width' not in style:
                    # Глобальная ширина зависит от lineweight
                    lineweight = style.get('lineweight', 100)
                    style['width'] = lineweight / 100.0  # Переводим в мм
                return style

        # Стиль по умолчанию: красная сплошная линия толщиной 1мм
        return {
            'linetype': 'CONTINUOUS',
            'color': 1,  # Красный в AutoCAD
            'lineweight': 100,  # Толщина 1.00мм
            'transparency': 0,
            'hatch': None,
            'width': 1.0  # Глобальная ширина полилиний
        }

    def add_linetype(self, doc, linetype_name: str):
        """
        Добавление типа линии в документ DXF

        Args:
            doc: Документ DXF
            linetype_name: Имя типа линии (CONTINUOUS, DASHED, etc.)
        """
        if linetype_name in doc.linetypes:
            return  # Тип линии уже существует

        try:
            if linetype_name == 'DASHED':
                doc.linetypes.add(
                    name='DASHED',
                    pattern=[0.5, -0.25],  # 0.5 единиц линии, 0.25 пробел
                    description='Штриховая'
                )
            elif linetype_name == 'DASHDOT':
                doc.linetypes.add(
                    name='DASHDOT',
                    pattern=[0.5, -0.25, 0.0, -0.25],  # Штрих-пунктирная
                    description='Штрихпунктирная'
                )
            # Добавьте другие типы линий по необходимости
            log_debug(f"Fsm_dxf_5: Добавлен тип линии: {linetype_name}")
        except Exception as e:
            log_warning(f"Fsm_dxf_5: Не удалось добавить тип линии {linetype_name}: {str(e)}")

    def add_text_style(self, doc, style_name: str, font_file: str):
        """
        Добавление текстового стиля в документ DXF

        Args:
            doc: Документ DXF
            style_name: Имя стиля (например, 'GOST 2.304')
            font_file: Имя файла шрифта (например, 'gost.shx' или 'GOST_A.ttf')
        """
        if style_name in doc.styles:
            return  # Стиль уже существует

        try:
            doc.styles.add(
                name=style_name,
                font=font_file
            )
            log_debug(f"Fsm_dxf_5: Добавлен текстовый стиль: {style_name} (шрифт: {font_file})")
        except Exception as e:
            log_warning(f"Fsm_dxf_5: Не удалось добавить текстовый стиль {style_name}: {str(e)}")
