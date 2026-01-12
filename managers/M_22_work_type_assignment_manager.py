# -*- coding: utf-8 -*-
"""
M_22_WorkTypeAssignmentManager - Менеджер присвоения Вид_Работ

Функции:
1. Присвоение поля Вид_Работ на основе типа слоя
2. Присвоение поля План_ВРИ на основе ID ЗПР (делегирует M_21_VRIAssignmentManager)
3. Изменение разделителя в поле Состав_контуров с ";" на ","

Логика присвоения Вид_Работ:
- RAZDEL (внутри существующего ЗУ): "Образование земельного участка путем раздела"
- NGS (вне существующего ЗУ): "Образование земельных участков из земельных участков,
  находящихся в государственной или муниципальной собственности"
- Этап 2 (объединение): "...путем объединения земельных участков с условными номерами X, Y, Z"

ПРИМЕЧАНИЕ: Отнесение к территориям общего пользования определяется через
поле План_ВРИ (VRIAssignmentManager), а НЕ через Вид_Работ.

Зависимости:
- M_21_VRIAssignmentManager - для работы с ВРИ (делегирование)

Используется в:
- F_3_1 (нарезка) - базовая нарезка
- F_3_3 (корректировка) - корректировка контуров
- F_3_4 (этапность) - этапы 1 и 2
"""

import json
import os
from enum import Enum
from typing import Dict, List, Optional, Any, TYPE_CHECKING

from qgis.core import QgsVectorLayer

from Daman_QGIS.utils import log_info, log_warning, log_error

if TYPE_CHECKING:
    from Daman_QGIS.managers import VRIAssignmentManager


class LayerType(Enum):
    """Тип слоя нарезки"""
    RAZDEL = "razdel"       # Внутри существующего ЗУ (раздел)
    NGS = "ngs"             # Вне существующего ЗУ (из гос. собственности)
    BEZ_MEJ = "bez_mej"     # Без межевания
    PS = "ps"               # Пересечения


class StageType(Enum):
    """Тип этапа для F_3_4"""
    STAGE_1 = "stage_1"     # Первоначальный раздел
    STAGE_2 = "stage_2"     # Объединение
    FINAL = "final"         # Итог


class WorkTypeAssignmentManager:
    """Менеджер присвоения Вид_Работ и План_ВРИ

    VRI-операции делегируются M_21_VRIAssignmentManager.
    """

    def __init__(self, plugin_dir: Optional[str] = None) -> None:
        """Инициализация менеджера

        Args:
            plugin_dir: Путь к папке плагина (если None - определяется автоматически)
        """
        if plugin_dir:
            self._plugin_dir = plugin_dir
        else:
            self._plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        self._work_types_data: List[Dict] = []
        self._work_types_by_vedomost: Dict[str, Dict] = {}
        self._vri_manager: Optional['VRIAssignmentManager'] = None
        self._loaded = False

    def _load_databases(self) -> bool:
        """Загрузка базы данных Work_types.json

        VRI загружается через M_21_VRIAssignmentManager (делегирование).

        Returns:
            True если загрузка успешна
        """
        if self._loaded:
            return True

        # Загрузка Work_types.json
        from Daman_QGIS.constants import DATA_REFERENCE_PATH
        work_types_path = os.path.join(DATA_REFERENCE_PATH, 'Work_types.json')

        try:
            with open(work_types_path, 'r', encoding='utf-8') as f:
                self._work_types_data = json.load(f)

            # Строим индекс по vedomost_value
            for wt in self._work_types_data:
                vedomost_value = wt.get('vedomost_value', '')
                if vedomost_value:
                    self._work_types_by_vedomost[vedomost_value] = wt

            log_info(f"M_22: Загружена база Work_types ({len(self._work_types_data)} записей)")

        except Exception as e:
            log_error(f"M_22: Ошибка загрузки Work_types.json: {e}")
            return False

        self._loaded = True
        return True

    def _get_vri_manager(self) -> 'VRIAssignmentManager':
        """Получить экземпляр VRIAssignmentManager (lazy initialization)

        Returns:
            VRIAssignmentManager для работы с ВРИ
        """
        if self._vri_manager is None:
            from Daman_QGIS.managers import VRIAssignmentManager
            self._vri_manager = VRIAssignmentManager(self._plugin_dir)
        return self._vri_manager

    def _get_work_type_value(
        self,
        layer_type: LayerType,
        stage_type: Optional[StageType] = None,
        merged_ids: Optional[List[int]] = None
    ) -> str:
        """Получить значение Вид_Работ

        Args:
            layer_type: Тип слоя (RAZDEL, NGS, BEZ_MEJ, PS)
            stage_type: Тип этапа (для F_3_4)
            merged_ids: Список ID объединяемых контуров (для этапа 2)

        Returns:
            Значение для поля Вид_Работ
        """
        # Этап 2 - объединение
        if stage_type == StageType.STAGE_2 and merged_ids:
            ids_str = ', '.join(map(str, merged_ids))
            return (
                f"Образование земельного участка путем объединения земельных "
                f"участков с условными номерами {ids_str}"
            )

        # RAZDEL (раздел)
        # ПРИМЕЧАНИЕ: Отнесение к ТОП определяется через План_ВРИ, не через Вид_Работ
        if layer_type == LayerType.RAZDEL:
            return "Образование земельного участка путем раздела"

        # NGS (из гос. собственности)
        if layer_type == LayerType.NGS:
            return (
                "Образование земельного участка из земельных участков, находящихся "
                "в государственной или муниципальной собственности"
            )

        # BEZ_MEJ и PS - пока заглушки
        if layer_type == LayerType.BEZ_MEJ:
            return "-"

        if layer_type == LayerType.PS:
            return "-"

        return "-"

    def _get_work_type_record(self, vedomost_value: str) -> Optional[Dict]:
        """Получить запись из Work_types по значению ведомости

        Args:
            vedomost_value: Значение для ведомости

        Returns:
            Словарь с данными или None
        """
        return self._work_types_by_vedomost.get(vedomost_value)

    def get_plan_vri_from_zpr(
        self,
        zpr_layer: QgsVectorLayer,
        zpr_id: int
    ) -> str:
        """Получить значение План_ВРИ из слоя ЗПР по ID

        Делегирует M_21_VRIAssignmentManager.get_plan_vri()

        Args:
            zpr_layer: Слой ЗПР
            zpr_id: ID контура ЗПР

        Returns:
            Значение full_name через ", " или "-"
        """
        return self._get_vri_manager().get_plan_vri(zpr_layer, zpr_id)

    def assign_work_type_basic(
        self,
        features_data: List[Dict[str, Any]],
        layer_type: LayerType,
        zpr_layer: Optional[QgsVectorLayer] = None
    ) -> List[Dict[str, Any]]:
        """Присвоить Вид_Работ для базовой нарезки (F_3_1, F_3_3)

        Args:
            features_data: Список словарей с данными объектов
                          Каждый словарь должен содержать:
                          - 'attributes': dict с атрибутами (включая План_ВРИ)
            layer_type: Тип слоя (RAZDEL, NGS, BEZ_MEJ, PS)
            zpr_layer: Слой ЗПР (для определения План_ВРИ если не задан)

        Returns:
            Обновлённый список с заполненным Вид_Работ
        """
        if not self._load_databases():
            log_warning("M_22: Базы данных не загружены, пропуск присвоения")
            return features_data

        assigned_count = 0

        for item in features_data:
            attrs = item.get('attributes', {})

            # Получаем План_ВРИ
            plan_vri = attrs.get('План_ВРИ', '-')

            # Если План_ВРИ не задан и есть zpr_id - получаем из ЗПР
            zpr_id = item.get('zpr_id')
            if (plan_vri in ('-', '', 'NULL', 'None', None)) and zpr_id is not None and zpr_layer is not None:
                plan_vri = self.get_plan_vri_from_zpr(zpr_layer, zpr_id)
                attrs['План_ВРИ'] = plan_vri

            # Если План_ВРИ всё ещё не задан - копируем из ВРИ
            if plan_vri in ('-', '', 'NULL', 'None', None):
                existing_vri = attrs.get('ВРИ', '-')
                if existing_vri and existing_vri not in ('-', '', 'NULL', 'None'):
                    attrs['План_ВРИ'] = existing_vri
                    plan_vri = existing_vri

            # Получаем значение Вид_Работ
            work_type = self._get_work_type_value(layer_type)
            attrs['Вид_Работ'] = work_type

            assigned_count += 1

        log_info(f"M_22: Присвоен Вид_Работ для {assigned_count} объектов (тип: {layer_type.value})")
        return features_data

    def assign_work_type_stage1(
        self,
        features_data: List[Dict[str, Any]],
        layer_type: LayerType,
        zpr_layer: Optional[QgsVectorLayer] = None
    ) -> List[Dict[str, Any]]:
        """Присвоить Вид_Работ для этапа 1 (F_3_4)

        Этап 1 - первоначальный раздел, логика аналогична базовой нарезке

        Args:
            features_data: Список словарей с данными объектов
            layer_type: Тип слоя
            zpr_layer: Слой ЗПР

        Returns:
            Обновлённый список
        """
        return self.assign_work_type_basic(features_data, layer_type, zpr_layer)

    def assign_work_type_stage2(
        self,
        features_data: List[Dict[str, Any]],
        layer_type: LayerType,
        zpr_layer: Optional[QgsVectorLayer] = None
    ) -> List[Dict[str, Any]]:
        """Присвоить Вид_Работ для этапа 2 - объединение (F_3_4)

        Этап 2 - объединение контуров. Вид_Работ включает номера объединяемых контуров.

        Args:
            features_data: Список словарей с данными объектов
                          Каждый словарь должен содержать:
                          - 'attributes': dict с атрибутами
                          - 'merged_ids': список ID объединяемых контуров (опционально)
                          Или 'attributes' содержит 'Состав_контуров'
            layer_type: Тип слоя
            zpr_layer: Слой ЗПР

        Returns:
            Обновлённый список
        """
        if not self._load_databases():
            log_warning("M_22: Базы данных не загружены, пропуск присвоения")
            return features_data

        assigned_count = 0

        for item in features_data:
            attrs = item.get('attributes', {})

            # Получаем План_ВРИ
            plan_vri = attrs.get('План_ВРИ', '-')

            # Если План_ВРИ не задан и есть zpr_id - получаем из ЗПР
            zpr_id = item.get('zpr_id')
            if (plan_vri in ('-', '', 'NULL', 'None', None)) and zpr_id is not None and zpr_layer is not None:
                plan_vri = self.get_plan_vri_from_zpr(zpr_layer, zpr_id)
                attrs['План_ВРИ'] = plan_vri

            # Если План_ВРИ всё ещё не задан - копируем из ВРИ
            if plan_vri in ('-', '', 'NULL', 'None', None):
                existing_vri = attrs.get('ВРИ', '-')
                if existing_vri and existing_vri not in ('-', '', 'NULL', 'None'):
                    attrs['План_ВРИ'] = existing_vri
                    plan_vri = existing_vri

            # Получаем список ID объединяемых контуров
            merged_ids = item.get('merged_ids')

            if not merged_ids:
                # Пробуем получить из merged_contours (F_3_4 передаёт так)
                sostav = item.get('merged_contours', '')
                if not sostav or sostav in ('-', '', 'NULL', 'None'):
                    # Пробуем получить из поля Состав_контуров в attrs
                    sostav = attrs.get('Состав_контуров', '')
                if sostav and sostav not in ('-', '', 'NULL', 'None'):
                    # Разделитель может быть ";" или ","
                    if ';' in sostav:
                        merged_ids = [int(x.strip()) for x in sostav.split(';') if x.strip().isdigit()]
                    elif ',' in sostav:
                        merged_ids = [int(x.strip()) for x in sostav.split(',') if x.strip().isdigit()]

            # Получаем значение Вид_Работ
            work_type = self._get_work_type_value(
                layer_type,
                stage_type=StageType.STAGE_2,
                merged_ids=merged_ids
            )
            attrs['Вид_Работ'] = work_type

            assigned_count += 1

        log_info(f"M_22: Присвоен Вид_Работ для {assigned_count} объектов (этап 2)")
        return features_data

    def update_sostav_separator(
        self,
        features_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Обновить разделитель в поле Состав_контуров с ";" на ","

        Args:
            features_data: Список словарей с данными объектов

        Returns:
            Обновлённый список
        """
        updated_count = 0

        for item in features_data:
            attrs = item.get('attributes', {})
            sostav = attrs.get('Состав_контуров', '')

            if sostav and ';' in sostav:
                # Заменяем разделитель
                attrs['Состав_контуров'] = sostav.replace(';', ', ')
                updated_count += 1

        if updated_count > 0:
            log_info(f"M_22: Обновлён разделитель Состав_контуров для {updated_count} объектов")

        return features_data

    def get_work_type_record_for_vedomost(
        self,
        work_type_value: str
    ) -> Optional[Dict]:
        """Получить полную запись Work_types для значения Вид_Работ

        Используется для получения code, code_code, style, code_code_xml

        Логика поиска:
        1. Точное совпадение vedomost_value
        2. Для динамических значений с номерами контуров:
           - "...объединения...с условными номерами 100, 101" соответствует
             "...объединения...с условными номерами"

        Args:
            work_type_value: Значение поля Вид_Работ

        Returns:
            Словарь с данными или None
        """
        if not self._load_databases():
            return None

        # Ищем по точному совпадению vedomost_value
        if work_type_value in self._work_types_by_vedomost:
            return self._work_types_by_vedomost[work_type_value]

        # Для динамических значений с номерами контуров
        # Паттерн: "...с условными номерами X, Y, Z"
        if ("путем объединения" in work_type_value and
                "с условными номерами" in work_type_value):
            key = "Образование земельного участка путем объединения земельных участков с условными номерами"
            if key in self._work_types_by_vedomost:
                return self._work_types_by_vedomost[key]

        return None

    def get_all_work_types(self) -> List[Dict]:
        """Получить все записи Work_types из базы данных

        Returns:
            Список всех типов работ
        """
        if not self._load_databases():
            return []
        return self._work_types_data.copy()
