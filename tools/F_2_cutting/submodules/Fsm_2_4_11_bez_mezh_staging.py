# -*- coding: utf-8 -*-
"""
Fsm_2_4_11_BezMezhStaging - Ветка Без_Меж в этапности

НАЗНАЧЕНИЕ:
    Формирует слои 1 этапа и Итога для существующих ЗУ без межевания: копия
    источника без нумерации точек, без точечных слоёв и без 2 этапа.

ОСОБЕННОСТИ:
    - Поле «Точки» остаётся пустым: нумерация для Без_Меж не ведётся.
    - Вид_Работ фиксирован; План_ВРИ наследуется от контуров ЗПР.

ИСПОЛЬЗОВАНИЕ:
    Вызывается F_2_4_Staging для слоя Без_Меж.
"""

from typing import Optional

from qgis.core import QgsGeometry, QgsVectorLayer

from Daman_QGIS.constants import WORK_TYPE_BEZ_MEZH, POINTS_FIELD_NONE
from Daman_QGIS.managers import VRIAssignmentManager
from Daman_QGIS.utils import log_info

from .Fsm_2_4_1_layer_writer import Fsm_2_4_1_LayerWriter


class Fsm_2_4_11_BezMezhStaging:
    """Формирование слоёв этапности для Без_Меж"""

    def __init__(
        self,
        layer_writer: Fsm_2_4_1_LayerWriter,
        vri_manager: Optional[VRIAssignmentManager],
        work_type_manager
    ) -> None:
        """Инициализация

        Args:
            layer_writer: Запись полигональных слоёв этапности (Fsm_2_4_1)
            vri_manager: Менеджер присвоения План_ВРИ (M_46)
            work_type_manager: Менеджер видов работ
        """
        self._layer_writer = layer_writer
        self._vri_manager = vri_manager
        self._work_type_manager = work_type_manager

    def process_bez_mezh_staging(
        self,
        source_layer: QgsVectorLayer,
        zpr_layer: QgsVectorLayer,
        stage1_name: str,
        final_name: str
    ) -> None:
        """Обработка Без_Меж: только 1 этап и Итог, без точек и объединения

        Без_Меж - существующие ЗУ без межевания:
        - НЕ нумеруем точки (поле «Точки» = прочерк, конвенция пакета)
        - НЕ создаём точечные слои
        - НЕ создаём 2 этап (нет объединения)
        - Просто копируем: Источник -> 1 этап -> Итог
        - Присваиваем Вид_Работ из work_types.json
        """
        log_info("Fsm_2_4_11: Обработка Без_Меж (без точек и 2 этапа)")

        # Сбор данных из источника
        features_data = []
        for feature in source_layer.getFeatures():
            geom = feature.geometry()
            if geom.isEmpty():
                continue

            attrs = {}
            for field in source_layer.fields():
                attrs[field.name()] = feature[field.name()]

            # Поле «Точки» — прочерк: нумерации нет
            attrs['Точки'] = POINTS_FIELD_NONE

            features_data.append({
                'geometry': QgsGeometry(geom),
                'attributes': attrs,
                'stage': 1,  # Всё в 1 этапе
                # zpr_id НЕ заполняется: поле ID здесь — собственный порядковый
                # номер контура Без_Меж, а не ID контура ЗПР. M_21 трактует
                # совпадение как связь и перезаписал бы План_ВРИ чужим значением
                'zpr_id': None
            })

        if not features_data:
            log_info("Fsm_2_4_11: Нет данных Без_Меж для обработки")
            return

        # Вид_Работ для Без_Меж — константа проекта. Прежняя охрана менеджером
        # была бутафорской: сам менеджер в этой ветке не использовался, а
        # строка дублировала значение из constants
        for item in features_data:
            item['attributes']['Вид_Работ'] = WORK_TYPE_BEZ_MEZH

        # План_ВРИ для Без_Меж НЕ берётся из ЗПР: у существующего сохраняемого
        # ЗУ это точная копия его собственного ВРИ, установленная в Fsm_2_1_9.
        # Прежняя привязка по совпадению номеров затирала верное значение.

        # Создание слоя 1 этапа (БЕЗ точечного слоя!)
        self._layer_writer.create_staging_layer(
            stage1_name, source_layer.crs(), source_layer.fields(),
            features_data, add_merged_field=False
        )

        # Подготовка данных для итогового слоя
        # Добавляем поля Этап и Состав_контуров
        for item in features_data:
            item['merged_contours'] = '-'  # Нет объединения

        # Создание итогового слоя (БЕЗ точечного слоя!)
        self._layer_writer.create_staging_layer(
            final_name, source_layer.crs(), source_layer.fields(),
            features_data,
            add_merged_field=True,
            add_stage_field=True
        )

        log_info(f"Fsm_2_4_11: Без_Меж обработан: {len(features_data)} объектов "
                f"(1 этап и Итог, без точек)")
