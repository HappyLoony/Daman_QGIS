# -*- coding: utf-8 -*-
"""
M_27_MinAreaValidator - Менеджер валидации минимальных площадей по ВРИ

Функции:
1. Проверка площадей контуров нарезки на соответствие минимальным требованиям
2. Получение MIN_AREA_VRI из исходных слоёв ЗПР по геометрическому пересечению
3. Отображение GUI диалога с проблемными контурами

Используется в:
- F_3_1 (после нарезки)
- F_3_3 (после корректировки)
- F_3_4 (после стейджинга)
"""

import os
from typing import Dict, List, Optional, Any

from qgis.core import QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry

from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.managers.submodules.Msm_27_1_validation_engine import ValidationEngine
from Daman_QGIS.managers.submodules.Msm_27_2_result_dialog import MinAreaResultDialog


class MinAreaValidator:
    """Менеджер валидации минимальных площадей по ВРИ"""

    # Имя поля с минимальной площадью в слоях ЗПР
    MIN_AREA_FIELD = 'MIN_AREA_VRI'

    # Маппинг типа ЗПР -> имя исходного слоя ЗПР
    ZPR_TYPE_TO_LAYER = {
        'ОКС': 'L_2_4_1_ЗПР_ОКС',
        'ПО': 'L_2_4_2_ЗПР_ПО',
        'ВО': 'L_2_4_3_ЗПР_ВО',
        'РЕК_АД': 'L_2_5_1_ЗПР_РЕК_АД',
        'СЕТИ_ПО': 'L_2_5_2_ЗПР_СЕТИ_ПО',
        'СЕТИ_ВО': 'L_2_5_3_ЗПР_СЕТИ_ВО',
        'НЭ': 'L_2_5_4_ЗПР_НЭ',
    }

    # Маппинг типа ЗПР -> список имён слоёв нарезки (Раздел, НГС, Без_Меж, ПС)
    ZPR_TYPE_TO_CUTTING_LAYERS = {
        'ОКС': [
            'Le_3_1_1_1_Раздел_ЗПР_ОКС',
            'Le_3_1_1_2_НГС_ЗПР_ОКС',
            'Le_3_1_1_3_Без_Меж_ЗПР_ОКС',
            'Le_3_1_1_4_ПС_ЗПР_ОКС',
        ],
        'ПО': [
            'Le_3_1_2_1_Раздел_ЗПР_ПО',
            'Le_3_1_2_2_НГС_ЗПР_ПО',
            'Le_3_1_2_3_Без_Меж_ЗПР_ПО',
            'Le_3_1_2_4_ПС_ЗПР_ПО',
        ],
        'ВО': [
            'Le_3_1_3_1_Раздел_ЗПР_ВО',
            'Le_3_1_3_2_НГС_ЗПР_ВО',
            'Le_3_1_3_3_Без_Меж_ЗПР_ВО',
            'Le_3_1_3_4_ПС_ЗПР_ВО',
        ],
        'РЕК_АД': [
            'Le_3_2_1_1_Раздел_ЗПР_РЕК_АД',
            'Le_3_2_1_2_НГС_ЗПР_РЕК_АД',
            'Le_3_2_1_3_Без_Меж_ЗПР_РЕК_АД',
            'Le_3_2_1_4_ПС_ЗПР_РЕК_АД',
        ],
        'СЕТИ_ПО': [
            'Le_3_2_2_1_Раздел_ЗПР_СЕТИ_ПО',
            'Le_3_2_2_2_НГС_ЗПР_СЕТИ_ПО',
            'Le_3_2_2_3_Без_Меж_ЗПР_СЕТИ_ПО',
            'Le_3_2_2_4_ПС_ЗПР_СЕТИ_ПО',
        ],
        'СЕТИ_ВО': [
            'Le_3_2_3_1_Раздел_ЗПР_СЕТИ_ВО',
            'Le_3_2_3_2_НГС_ЗПР_СЕТИ_ВО',
            'Le_3_2_3_3_Без_Меж_ЗПР_СЕТИ_ВО',
            'Le_3_2_3_4_ПС_ЗПР_СЕТИ_ВО',
        ],
        'НЭ': [
            'Le_3_2_4_1_Раздел_ЗПР_НЭ',
            'Le_3_2_4_2_НГС_ЗПР_НЭ',
            'Le_3_2_4_3_Без_Меж_ЗПР_НЭ',
            'Le_3_2_4_4_ПС_ЗПР_НЭ',
        ],
    }

    def __init__(self, plugin_dir: Optional[str] = None) -> None:
        """Инициализация менеджера

        Args:
            plugin_dir: Путь к папке плагина (если None - определяется автоматически)
        """
        if plugin_dir:
            self._plugin_dir = plugin_dir
        else:
            self._plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        self._validation_engine: Optional[ValidationEngine] = None

    def _get_layer_by_name(self, layer_name: str) -> Optional[QgsVectorLayer]:
        """Получить слой по имени из текущего проекта

        Args:
            layer_name: Имя слоя

        Returns:
            QgsVectorLayer или None
        """
        layers = QgsProject.instance().mapLayersByName(layer_name)
        if layers:
            layer = layers[0]
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                return layer
        return None

    def _get_zpr_layer(self, zpr_type: str) -> Optional[QgsVectorLayer]:
        """Получить исходный слой ЗПР по типу

        Args:
            zpr_type: Тип ЗПР (ОКС, ЛО, ВО, РЕК_АД и т.д.)

        Returns:
            QgsVectorLayer или None
        """
        layer_name = self.ZPR_TYPE_TO_LAYER.get(zpr_type)
        if not layer_name:
            log_warning(f"M_27: Неизвестный тип ЗПР: {zpr_type}")
            return None

        return self._get_layer_by_name(layer_name)

    def _get_cutting_layers(self, zpr_type: str) -> List[QgsVectorLayer]:
        """Получить слои нарезки по типу ЗПР

        Args:
            zpr_type: Тип ЗПР (ОКС, ЛО, ВО, РЕК_АД и т.д.)

        Returns:
            Список валидных слоёв нарезки
        """
        layer_names = self.ZPR_TYPE_TO_CUTTING_LAYERS.get(zpr_type, [])
        result = []

        for name in layer_names:
            layer = self._get_layer_by_name(name)
            if layer is not None and layer.isValid():
                result.append(layer)

        return result

    def _has_min_area_field(self, layer: QgsVectorLayer) -> bool:
        """Проверить наличие поля MIN_AREA_VRI в слое

        Args:
            layer: Слой для проверки

        Returns:
            True если поле существует
        """
        field_names = [f.name() for f in layer.fields()]
        return self.MIN_AREA_FIELD in field_names

    def validate_cutting_results(
        self,
        zpr_type: str,
        show_dialog: bool = True
    ) -> Dict[str, Any]:
        """Валидация результатов нарезки для указанного типа ЗПР

        Args:
            zpr_type: Тип ЗПР (ОКС, ЛО, ВО, РЕК_АД и т.д.)
            show_dialog: Показывать GUI диалог с результатами

        Returns:
            Dict с результатами:
                - 'success': bool - есть ли проблемные контуры
                - 'total_checked': int - всего проверено контуров
                - 'problem_count': int - количество проблемных
                - 'problems': List[Dict] - список проблемных контуров
                - 'skipped_no_field': bool - пропущено из-за отсутствия поля
        """
        log_info(f"M_27: Начало валидации минимальных площадей для {zpr_type}")

        result = {
            'success': True,
            'total_checked': 0,
            'problem_count': 0,
            'problems': [],
            'skipped_no_field': False,
        }

        # Получаем исходный слой ЗПР
        zpr_layer = self._get_zpr_layer(zpr_type)
        if zpr_layer is None or not zpr_layer.isValid():
            log_warning(f"M_27: Слой ЗПР для типа {zpr_type} не найден")
            return result

        # Проверяем наличие поля MIN_AREA_VRI
        if not self._has_min_area_field(zpr_layer):
            log_info(f"M_27: Поле {self.MIN_AREA_FIELD} отсутствует в слое {zpr_layer.name()}, пропуск валидации")
            result['skipped_no_field'] = True
            return result

        # Получаем слои нарезки
        cutting_layers = self._get_cutting_layers(zpr_type)
        if not cutting_layers:
            log_warning(f"M_27: Слои нарезки для типа {zpr_type} не найдены")
            return result

        # Создаём движок валидации
        self._validation_engine = ValidationEngine(zpr_layer, self.MIN_AREA_FIELD)

        # Валидируем каждый слой нарезки
        all_problems = []
        total_checked = 0

        for layer in cutting_layers:
            if self._validation_engine is None:
                log_error("M_27: Движок валидации не инициализирован")
                break
            problems, checked = self._validation_engine.validate_layer(layer)
            all_problems.extend(problems)
            total_checked += checked

        result['total_checked'] = total_checked
        result['problem_count'] = len(all_problems)
        result['problems'] = all_problems
        result['success'] = len(all_problems) == 0

        # Логируем результат
        if all_problems:
            log_warning(
                f"M_27: Найдено {len(all_problems)} контуров с недостаточной площадью "
                f"(проверено {total_checked})"
            )
        else:
            log_info(f"M_27: Валидация успешна, проверено {total_checked} контуров")

        # Показываем диалог если есть проблемы
        if show_dialog and all_problems:
            self._show_results_dialog(all_problems, zpr_type)

        return result

    def validate_all_zpr_types(self, show_dialog: bool = True) -> Dict[str, Any]:
        """Валидация всех типов ЗПР

        Args:
            show_dialog: Показывать GUI диалог с результатами

        Returns:
            Dict с агрегированными результатами
        """
        log_info("M_27: Начало валидации всех типов ЗПР")

        all_problems = []
        total_checked = 0
        types_checked = []

        for zpr_type in self.ZPR_TYPE_TO_LAYER.keys():
            result = self.validate_cutting_results(zpr_type, show_dialog=False)

            if not result['skipped_no_field']:
                types_checked.append(zpr_type)
                total_checked += result['total_checked']
                all_problems.extend(result['problems'])

        aggregate_result = {
            'success': len(all_problems) == 0,
            'total_checked': total_checked,
            'problem_count': len(all_problems),
            'problems': all_problems,
            'types_checked': types_checked,
        }

        if show_dialog and all_problems:
            self._show_results_dialog(all_problems, 'Все типы ЗПР')

        return aggregate_result

    def _show_results_dialog(self, problems: List[Dict], zpr_type: str) -> None:
        """Показать диалог с результатами валидации

        Args:
            problems: Список проблемных контуров
            zpr_type: Тип ЗПР для заголовка
        """
        try:
            from qgis.utils import iface
            dialog = MinAreaResultDialog(problems, zpr_type, iface.mainWindow())
            dialog.exec_()
        except Exception as e:
            log_error(f"M_27: Ошибка отображения диалога: {e}")

    def get_min_area_for_geometry(
        self,
        geometry: QgsGeometry,
        zpr_type: str
    ) -> Optional[int]:
        """Получить минимальную площадь для геометрии по пересечению с ЗПР

        Args:
            geometry: Геометрия контура
            zpr_type: Тип ЗПР

        Returns:
            Минимальная площадь или None если не определена
        """
        zpr_layer = self._get_zpr_layer(zpr_type)
        if zpr_layer is None or not zpr_layer.isValid():
            return None

        if not self._has_min_area_field(zpr_layer):
            return None

        engine = ValidationEngine(zpr_layer, self.MIN_AREA_FIELD)
        return engine.get_min_area_for_geometry(geometry)
