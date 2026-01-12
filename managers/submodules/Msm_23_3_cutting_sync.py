# -*- coding: utf-8 -*-
"""
Msm_23_3 - CuttingSync: Синхронизация полей ОКС_на_ЗУ со слоями нарезки

Назначение:
    Синхронизация полей ОКС_на_ЗУ_выписка и ОКС_на_ЗУ_факт из слоя
    выборки ЗУ в слои нарезки (Le_3_1_*) и этапности (Le_3_7_*).

Логика:
    1. Для слоёв 1 этапа (Le_3_1_*): синхронизация по полю КН
    2. Для слоёв 2 этапа и итоговых (Le_3_7_* с полем Состав_контуров):
       - Парсинг Состав_контуров для получения ID контуров 1 этапа
       - Сбор и объединение данных ОКС из связанных контуров
       - Дедупликация значений
"""

from typing import Dict, List, Set
from qgis.core import QgsProject, QgsVectorLayer

from Daman_QGIS.utils import log_info, log_warning, log_error


class CuttingSync:
    """Синхронизация полей ОКС_на_ЗУ со слоями нарезки"""

    # Имена полей
    FIELD_VYPISKA = 'ОКС_на_ЗУ_выписка'
    FIELD_FACT = 'ОКС_на_ЗУ_факт'

    # Префиксы целевых слоёв
    TARGET_PREFIXES = ('Le_3_1_', 'Le_3_7_')

    def sync_cutting_layers(
        self,
        zu_layer: QgsVectorLayer,
    ) -> Dict[str, int]:
        """
        Синхронизировать поля ОКС_на_ЗУ из слоя выборки ЗУ в слои нарезки и этапности.

        Находит все слои Le_3_1_* (нарезка) и Le_3_7_* (этапность),
        синхронизирует поля по КН.

        Args:
            zu_layer: Слой выборки ЗУ (Le_2_1_1_1_Выборка_ЗУ)

        Returns:
            dict: {'layers_synced': N, 'features_synced': N}
        """
        stats = {
            'layers_synced': 0,
            'features_synced': 0
        }

        # Собираем данные из слоя выборки ЗУ по КН
        zu_data = self._collect_zu_oks_data(zu_layer)
        if not zu_data:
            log_info("Msm_23_3: Нет данных для синхронизации со слоями нарезки")
            return stats

        log_info(f"Msm_23_3: Собрано данных по {len(zu_data)} ЗУ для синхронизации")

        # Ищем слои нарезки Le_3_1_* и этапности Le_3_7_*
        cutting_layers = [
            layer for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer) and layer.name().startswith(self.TARGET_PREFIXES)
        ]

        if not cutting_layers:
            log_info("Msm_23_3: Слои нарезки Le_3_1_* и этапности Le_3_7_* не найдены")
            return stats

        log_info(f"Msm_23_3: Найдено {len(cutting_layers)} слоёв для синхронизации")

        # Синхронизируем каждый слой
        for cutting_layer in cutting_layers:
            synced = self._sync_single_cutting_layer(cutting_layer, zu_data)
            if synced > 0:
                stats['layers_synced'] += 1
                stats['features_synced'] += synced

        return stats

    def _collect_zu_oks_data(self, zu_layer: QgsVectorLayer) -> Dict[str, Dict[str, str]]:
        """
        Собрать данные ОКС_на_ЗУ из слоя выборки ЗУ.

        Args:
            zu_layer: Слой выборки ЗУ

        Returns:
            dict: {КН_ЗУ: {'vypiska': 'значение', 'fact': 'значение'}}
        """
        result: Dict[str, Dict[str, str]] = {}

        kn_idx = zu_layer.fields().indexOf('КН')
        vypiska_idx = zu_layer.fields().indexOf(self.FIELD_VYPISKA)
        fact_idx = zu_layer.fields().indexOf(self.FIELD_FACT)

        if kn_idx == -1:
            log_error("Msm_23_3: Поле 'КН' не найдено в слое выборки ЗУ")
            return result

        if vypiska_idx == -1 and fact_idx == -1:
            log_warning("Msm_23_3: Поля ОКС_на_ЗУ не найдены в слое выборки ЗУ")
            return result

        for feature in zu_layer.getFeatures():
            kn = feature[kn_idx]
            if not kn:
                continue

            kn = str(kn).strip()
            data: Dict[str, str] = {}

            if vypiska_idx != -1:
                value = feature[vypiska_idx]
                data['vypiska'] = str(value) if value and str(value).strip() not in ('', '-', 'NULL') else '-'

            if fact_idx != -1:
                value = feature[fact_idx]
                data['fact'] = str(value) if value and str(value).strip() not in ('', '-', 'NULL') else '-'

            if data:
                result[kn] = data

        return result

    def _sync_single_cutting_layer(
        self,
        cutting_layer: QgsVectorLayer,
        zu_data: Dict[str, Dict[str, str]]
    ) -> int:
        """
        Синхронизировать один слой нарезки.

        Для слоёв 1 этапа (Le_3_1_*) - синхронизация по полю КН.
        Для слоёв 2 этапа и итоговых (Le_3_7_*, с полем Состав_контуров != '-'):
        - Использует Состав_контуров для поиска ID в 1 этапе
        - Собирает данные ОКС из связанных контуров 1 этапа
        - Объединяет с дедупликацией

        Args:
            cutting_layer: Слой нарезки
            zu_data: Данные из слоя выборки ЗУ

        Returns:
            int: Количество синхронизированных объектов
        """
        layer_name = cutting_layer.name()

        # Проверяем наличие полей
        kn_idx = cutting_layer.fields().indexOf('КН')
        vypiska_idx = cutting_layer.fields().indexOf(self.FIELD_VYPISKA)
        fact_idx = cutting_layer.fields().indexOf(self.FIELD_FACT)
        sostav_idx = cutting_layer.fields().indexOf('Состав_контуров')

        if kn_idx == -1:
            log_warning(f"Msm_23_3: Поле 'КН' не найдено в {layer_name}")
            return 0

        if vypiska_idx == -1 and fact_idx == -1:
            log_warning(f"Msm_23_3: Поля ОКС_на_ЗУ не найдены в {layer_name}")
            return 0

        # Определяем тип слоя и загружаем данные 1 этапа если нужно
        is_stage2_or_final = sostav_idx != -1  # Слой с полем Состав_контуров
        stage1_data: Dict[int, Dict[str, str]] = {}

        if is_stage2_or_final:
            # Загружаем данные из слоёв 1 этапа для поиска по ID
            stage1_data = self._collect_stage1_oks_data()
            if stage1_data:
                log_info(f"Msm_23_3: Загружено данных из 1 этапа по {len(stage1_data)} ID")

        # Начинаем редактирование
        if not cutting_layer.startEditing():
            log_error(f"Msm_23_3: Не удалось начать редактирование {layer_name}")
            return 0

        synced_count = 0

        for feature in cutting_layer.getFeatures():
            feature_updated = False
            vypiska_value = '-'
            fact_value = '-'

            # Проверяем Состав_контуров для объединённых контуров
            sostav = None
            if is_stage2_or_final and sostav_idx != -1:
                sostav = feature[sostav_idx]
                if sostav and str(sostav).strip() not in ('', '-'):
                    sostav = str(sostav).strip()

            if sostav and stage1_data:
                # Объединённый контур - собираем данные по Состав_контуров
                vypiska_values: Set[str] = set()
                fact_values: Set[str] = set()

                # Парсим ID из Состав_контуров (формат: "100, 101, 102")
                for id_str in sostav.replace(';', ',').split(','):
                    id_str = id_str.strip()
                    if not id_str:
                        continue
                    try:
                        contour_id = int(id_str)
                        if contour_id in stage1_data:
                            data = stage1_data[contour_id]
                            # Собираем значения выписки
                            if 'vypiska' in data and data['vypiska'] != '-':
                                for kn in data['vypiska'].split(';'):
                                    kn_clean = kn.strip()
                                    if kn_clean and kn_clean != '-':
                                        vypiska_values.add(kn_clean)
                            # Собираем значения факта
                            if 'fact' in data and data['fact'] != '-':
                                for kn in data['fact'].split(';'):
                                    kn_clean = kn.strip()
                                    if kn_clean and kn_clean != '-':
                                        fact_values.add(kn_clean)
                    except ValueError:
                        continue

                vypiska_value = '; '.join(sorted(vypiska_values)) if vypiska_values else '-'
                fact_value = '; '.join(sorted(fact_values)) if fact_values else '-'
                feature_updated = True
            else:
                # Обычный контур - синхронизация по КН
                kn = feature[kn_idx]
                if kn:
                    kn = str(kn).strip()
                    data = zu_data.get(kn)
                    if data:
                        vypiska_value = data.get('vypiska', '-')
                        fact_value = data.get('fact', '-')
                        feature_updated = True

            if feature_updated:
                # Синхронизируем поле выписки
                if vypiska_idx != -1:
                    cutting_layer.changeAttributeValue(feature.id(), vypiska_idx, vypiska_value)
                # Синхронизируем поле факта
                if fact_idx != -1:
                    cutting_layer.changeAttributeValue(feature.id(), fact_idx, fact_value)
                synced_count += 1

        # Сохраняем изменения
        if synced_count > 0:
            if not cutting_layer.commitChanges():
                log_error(f"Msm_23_3: Ошибка сохранения {layer_name}: {cutting_layer.commitErrors()}")
                cutting_layer.rollBack()
                return 0
            log_info(f"Msm_23_3: Синхронизировано {synced_count} объектов в {layer_name}")
        else:
            cutting_layer.rollBack()

        return synced_count

    def _collect_stage1_oks_data(self) -> Dict[int, Dict[str, str]]:
        """
        Собрать данные ОКС_на_ЗУ из слоёв 1 этапа по ID.

        Ищет слои Le_3_1_* и собирает данные по полю ID.

        Returns:
            dict: {ID: {'vypiska': 'значение', 'fact': 'значение'}}
        """
        result: Dict[int, Dict[str, str]] = {}

        # Ищем слои 1 этапа
        stage1_layers = [
            layer for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer) and layer.name().startswith('Le_3_1_')
        ]

        for layer in stage1_layers:
            id_idx = layer.fields().indexOf('ID')
            vypiska_idx = layer.fields().indexOf(self.FIELD_VYPISKA)
            fact_idx = layer.fields().indexOf(self.FIELD_FACT)

            if id_idx == -1:
                continue

            for feature in layer.getFeatures():
                contour_id = feature[id_idx]
                if contour_id is None:
                    continue

                try:
                    contour_id = int(contour_id)
                except (ValueError, TypeError):
                    continue

                data: Dict[str, str] = {}

                if vypiska_idx != -1:
                    value = feature[vypiska_idx]
                    data['vypiska'] = str(value) if value and str(value).strip() not in ('', '-', 'NULL') else '-'

                if fact_idx != -1:
                    value = feature[fact_idx]
                    data['fact'] = str(value) if value and str(value).strip() not in ('', '-', 'NULL') else '-'

                if data:
                    result[contour_id] = data

        return result
