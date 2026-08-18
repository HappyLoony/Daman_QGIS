# -*- coding: utf-8 -*-
"""
Fsm_2_4_9_StageBuilder - Данные 1 этапа и итогового слоя этапности

НАЗНАЧЕНИЕ:
    Собирает записи объектов для слоя 1 этапа (копия нарезки с привязкой к
    контурам ЗПР) и для итогового слоя (контуры 1 этапа, не участвовавшие в
    объединении, плюс результаты 2 этапа).

ОСОБЕННОСТИ:
    - Объект с пустой геометрией пропускается.
    - Итоговый слой наследует План_ВРИ от контуров ЗПР через M_46.

ИСПОЛЬЗОВАНИЕ:
    Вызывается F_2_4_Staging при формировании слоёв этапности.
"""

from typing import Any, Dict, List, Optional

from qgis.core import QgsGeometry, QgsVectorLayer

from Daman_QGIS.managers import VRIAssignmentManager
from Daman_QGIS.utils import log_info, log_warning


class Fsm_2_4_9_StageBuilder:
    """Сборка данных 1 этапа и итогового слоя"""

    def __init__(self, vri_manager: Optional[VRIAssignmentManager]) -> None:
        """Инициализация

        Args:
            vri_manager: Менеджер присвоения План_ВРИ (M_46) из F_2_4_Staging
        """
        self._vri_manager = vri_manager

    def prepare_stage1_data(
        self,
        source_layer: QgsVectorLayer,
        feature_zpr_mapping: Dict[int, int],
        matching_features: set,
        merging_features: set,
        next_id_base: int
    ) -> List[Dict[str, Any]]:
        """Подготовка данных для 1 этапа

        ID назначается:
        - Для соответствующих ЗПР: ID = ID контура ЗПР
        - Для несоответствующих: ID = next_id_base + счётчик

        Флаг is_temporary помечает временные (объединяемые) контуры того же
        снимка fid, что и merging_features: используется при формировании слоя
        Итог (§4.2 — временные исключаются) и Т_Итог (§4.3 — точки временных
        не попадают в итоговый точечный слой).
        """
        stage1_data = []
        non_matching_counter = 0

        for feature in source_layer.getFeatures():
            feature_id = feature.id()
            geom = feature.geometry()

            if geom.isEmpty():
                continue

            # Копируем атрибуты
            attrs = {}
            for field in source_layer.fields():
                attrs[field.name()] = feature[field.name()]

            # Назначаем ID
            if feature_id in feature_zpr_mapping:
                zpr_id = feature_zpr_mapping[feature_id]
                if feature_id in matching_features:
                    # Соответствует ЗПР → ID = ID ЗПР
                    attrs['ID'] = zpr_id
                else:
                    # Требует объединения → ID с нового разряда
                    attrs['ID'] = next_id_base + non_matching_counter
                    non_matching_counter += 1
            else:
                # Не привязан к ЗПР
                attrs['ID'] = next_id_base + non_matching_counter
                non_matching_counter += 1

            stage1_data.append({
                'geometry': QgsGeometry(geom),
                'attributes': attrs,
                'original_fid': feature_id,
                'zpr_id': feature_zpr_mapping.get(feature_id),
                # Временный (объединяемый) контур — из того же снимка fid, что и
                # merging_features. Исключается из Итог и Т_Итог.
                'is_temporary': feature_id in merging_features
            })

        # Сортировка по ID
        stage1_data.sort(key=lambda x: x['attributes'].get('ID', 0))

        return stage1_data

    def prepare_final_data(
        self,
        stage1_data: List[Dict[str, Any]],
        stage2_data: List[Dict[str, Any]],
        zpr_layer: QgsVectorLayer
    ) -> List[Dict[str, Any]]:
        """Подготовка данных для итогового слоя

        Итог = ВСЕ контуры из 1 этапа + ВСЕ контуры из 2 этапа

        Поле Этап:
        - Для контуров из 1 этапа: 1
        - Для контуров из 2 этапа: 2

        Поле Состав_контуров:
        - Для контуров 1 этапа: "-"
        - Для объединённых (2 этап): "100, 101, 102"

        Поля План_ВРИ и Общая_земля:
        - Присваиваются на основе ВРИ из слоя ЗПР по ID контура

        Raises:
            RuntimeError: контур помечен временным, но ни в один объединённый
                          контур 2 этапа не вошёл — Итог был бы неполным
        """
        # Машинная сверка множеств до сборки: временный контур исключается из
        # Итога, поэтому он обязан быть покрыт составом какого-то контура 2 этапа
        temporary_ids = {
            str(item['attributes'].get('ID'))
            for item in stage1_data if item.get('is_temporary')
        }
        covered_ids: set = set()
        for item in stage2_data:
            composition = item.get('merged_contours') or ''
            for part in str(composition).replace(';', ',').split(','):
                part = part.strip()
                if part and part != '-':
                    covered_ids.add(part)

        lost = temporary_ids - covered_ids
        if lost:
            raise RuntimeError(
                f"Fsm_2_4_9: контуры {sorted(lost)} помечены временными, но не вошли "
                f"ни в один контур 2 этапа — итоговый слой был бы неполным"
            )

        final_data = []

        # Добавляем контуры из 1 этапа (Этап=1), КРОМЕ временных (§4.2).
        # Временные (объединяемые) контуры заменяются объединённым контуром
        # 2 этапа → в слое Итог физически отсутствуют. Остаются: matching
        # (соответствуют ЗПР) и одиночные-без-ЗПР.
        for item in stage1_data:
            if item.get('is_temporary'):
                continue
            zpr_id = item['attributes'].get('ID')
            final_data.append({
                'geometry': QgsGeometry(item['geometry']),
                'attributes': dict(item['attributes']),
                'merged_contours': '-',  # Контуры 1 этапа не имеют Состав_контуров
                'zpr_id': zpr_id,
                'stage': 1  # Этап 1
            })

        # Добавляем ВСЕ контуры из 2 этапа (Этап=2)
        for item in stage2_data:
            attrs = dict(item['attributes'])
            # ID объединённого контура = ID ЗПР
            zpr_id = item.get('zpr_id') or attrs.get('ID')
            merged_contours = item.get('merged_contours')
            if not merged_contours or str(merged_contours) in ('-', '', 'NULL', 'None'):
                # Без состава M_22 не отличит объединение от раздела и выдаст
                # формулировку раздела для контура 2 этапа
                log_warning(
                    f"Fsm_2_4_9: контур 2 этапа ID={attrs.get('ID')} без состава "
                    f"объединённых контуров"
                )
                merged_contours = '-'
            final_data.append({
                'geometry': QgsGeometry(item['geometry']),
                'attributes': attrs,
                'merged_contours': merged_contours,
                'zpr_id': zpr_id,
                'stage': 2  # Этап 2
            })

        # Присвоение План_ВРИ и Общее через VRIAssignmentManager
        if self._vri_manager and zpr_layer:
            final_data = self._vri_manager.assign_vri_to_features(
                zpr_layer, final_data, zpr_id_key='zpr_id'
            )

        # Сортировка по Этапу, затем по ID
        final_data.sort(key=lambda x: (x.get('stage', 1), x['attributes'].get('ID', 0)))

        return final_data
