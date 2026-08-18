# -*- coding: utf-8 -*-
"""
Fsm_2_4_5_Finisher - Завершающая обработка слоёв этапности

НАЗНАЧЕНИЕ:
    Валидация минимальных площадей по ВРИ (M_27) и применение стилей с подписями
    (M_5, M_12) ко всем созданным слоям этапности.

ОСОБЕННОСТИ:
    - Отсутствующий слой пропускается: набор слоёв зависит от данных прогона.
    - Валидация площадей работает только с ОКС — этапность только для площадных.

ИСПОЛЬЗОВАНИЕ:
    Вызывается F_2_4_Staging после создания всех слоёв.
"""

from typing import Optional

from qgis.core import QgsProject

from Daman_QGIS.managers import StyleManager, LabelManager
from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.constants import (
    LAYER_STAGING_1_RAZDEL, LAYER_STAGING_1_NGS,
    LAYER_STAGING_1_BEZ_MEZH,
    LAYER_STAGING_2_RAZDEL, LAYER_STAGING_2_NGS,
    LAYER_STAGING_FINAL_RAZDEL, LAYER_STAGING_FINAL_NGS,
    LAYER_STAGING_FINAL_BEZ_MEZH,
    LAYER_STAGING_POINTS_1_RAZDEL, LAYER_STAGING_POINTS_1_NGS,
    LAYER_STAGING_POINTS_2_RAZDEL, LAYER_STAGING_POINTS_2_NGS,
    LAYER_STAGING_POINTS_FINAL_RAZDEL, LAYER_STAGING_POINTS_FINAL_NGS,
)


class Fsm_2_4_5_Finisher:
    """Завершающая обработка слоёв этапности"""

    def __init__(self, plugin_dir: Optional[str] = None) -> None:
        """Инициализация

        Args:
            plugin_dir: Путь к папке плагина (нужен валидатору площадей)
        """
        self.plugin_dir = plugin_dir

    def validate_min_areas(self) -> None:
        """Валидация минимальных площадей по ВРИ для ОКС

        Вызывает M_27_MinAreaValidator для проверки контуров стейджинга.
        F_2_4 работает только с ОКС, поэтому проверяем только этот тип.
        """
        try:
            from Daman_QGIS.managers import MinAreaValidator

            validator = MinAreaValidator(self.plugin_dir)
            result = validator.validate_cutting_results('ОКС', show_dialog=True)

            if result.get('skipped_no_layer'):
                log_info(f"Fsm_2_4_5: Валидация ОКС не требуется ({result.get('reason')})")
            elif result.get('skipped_no_field'):
                log_info("Fsm_2_4_5: Валидация ОКС пропущена (нет поля MIN_AREA_VRI)")
            elif result.get('success'):
                log_info(
                    f"Fsm_2_4_5: Валидация ОКС успешна, проверено "
                    f"{result.get('total_checked', 0)} контуров"
                )
            elif result.get('total_checked', 0) == 0:
                # Ноль проверенных — это не успех: раньше в лог уходило
                # «успешна», хотя проверка фактически не состоялась
                log_error(
                    f"Fsm_2_4_5: Валидация ОКС НЕ ВЫПОЛНЕНА "
                    f"({result.get('reason') or 'причина не указана'})"
                )
            else:
                log_warning(
                    f"Fsm_2_4_5: Валидация ОКС - найдено {result.get('problem_count', 0)} "
                    f"контуров с недостаточной площадью"
                )
        except Exception as e:
            log_error(f"Fsm_2_4_5: Ошибка валидации минимальных площадей: {e}")

    def apply_styles_and_labels(self) -> None:
        """Применение стилей и подписей ко всем слоям этапности"""
        style_manager = StyleManager()
        label_manager = LabelManager()
        project = QgsProject.instance()

        # Собираем все слои этапности
        all_layer_names = [
            # Полигоны - Раздел
            LAYER_STAGING_1_RAZDEL, LAYER_STAGING_2_RAZDEL, LAYER_STAGING_FINAL_RAZDEL,
            # Полигоны - НГС
            LAYER_STAGING_1_NGS, LAYER_STAGING_2_NGS, LAYER_STAGING_FINAL_NGS,
            # Полигоны - Без_Меж (без 2 этапа!)
            LAYER_STAGING_1_BEZ_MEZH, LAYER_STAGING_FINAL_BEZ_MEZH,
            # Точки - Раздел
            LAYER_STAGING_POINTS_1_RAZDEL, LAYER_STAGING_POINTS_2_RAZDEL,
            LAYER_STAGING_POINTS_FINAL_RAZDEL,
            # Точки - НГС
            LAYER_STAGING_POINTS_1_NGS, LAYER_STAGING_POINTS_2_NGS,
            LAYER_STAGING_POINTS_FINAL_NGS,
            # Примечание: Без_Меж НЕ имеет точечных слоёв!
        ]

        for layer_name in all_layer_names:
            layers = project.mapLayersByName(layer_name)
            if not layers:
                continue

            layer = layers[0]
            if not layer.isValid():
                continue

            style_manager.apply_qgis_style(layer, layer_name)
            label_manager.apply_labels(layer, layer_name)
            layer.triggerRepaint()

        log_info("Fsm_2_4_5: Стили и подписи применены")
